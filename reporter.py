import sys
import os
import datetime
import pytz
import json
import io
import urllib
import logging
import time
import concurrent.futures
from enum import Enum
from typing import NamedTuple
from types import SimpleNamespace
from canvasapi import Canvas, exceptions
from datetime import datetime
from datetime import timedelta
from datetime import date as datetime_date
from course import Course, CourseScore
from assignment import Assignment, AssignmentStatus, SubmissionStatus
from weighting import WeightedScoreCalculator
import utils
import inspect

# Examples
# Physics submitted      https://cchs.instructure.com/courses/5347/assignments/160100/submissions/5573
# Geometry comments      https://cchs.instructure.com/courses/5205/assignments/159434/submissions/5573
# Geometry not submitted https://cchs.instructure.com/courses/5205/assignments/159972/submissions/5573
# Wellness no submission https://cchs.instructure.com/courses/5237/assignments/158002/submissions/5573
class Reporter:
    def __init__(self, config, term=None):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Config: {}".format(config))
        self.canvas = Canvas(config["url"], config["key"])
        self.user = self.canvas.get_user('self')
        self.term = term
        self.courses = {}
        enrollments = self.user.get_enrollments(state=["current_and_concluded"])
        start_time = time.time()
        if self.term is None:
            for course in self.user.get_courses(enrollment_state="active", include=["total_scores", "term"]):
                enrollment_result = [e for e in enrollments if e.course_id == course.id]
                enrollment = enrollment_result[0] if enrollment_result else None
                #print(f"{course.id}, {course.name}, {course.term['name']}, {enrollment.grades.get('current_score')}")
                self.courses[course.id] = Course(course, enrollment)
        else:
            self.term = self.term.replace('_', ' ')
            all_courses = self.user.get_courses(include=["total_scores", "term"])
            for c in all_courses:
                if c.term.get('name') == self.term:
                    self.courses[c.id] = Course(c)
        self.logger.info("get_courses took {}s".format(time.time() - start_time))
        now = datetime.today().replace(tzinfo=pytz.UTC)
        for id in list(self.courses):
            if not self.courses[id].is_current(now):
                del self.courses[id]
        self.calculator = WeightedScoreCalculator(self.courses)

    def get_assignments(self, user, course):
        return course.get_assignments(user)

    def load_assignments(self):
        self.assignments = {}
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for course in self.courses.values():
                futures.append(executor.submit(self.get_assignments, user=self.user, course=course))
            for future in concurrent.futures.as_completed(futures):
                self.assignments.update(future.result())
        self.logger.info("load_assignments took {}s".format(time.time() - start_time))

    def load_assignments_serial(self):
        self.assignments = {}
        start_time = time.time()
        for _, course in self.courses.items():
            #start_time = time.time()
            assignments = self.get_assignments(self.user, course)
            self.assignments.update(assignments)
            #self.logger.info("get_assignments({}) took {} {}".format(course.name, time.time(), start_time))
        self.logger.info("load_assignments took {}s".format(time.time() - start_time))

    def get_assignment(self, id):
        self.logger.info("Searching {} assignments for id {}".format(len(self.assignments), id))
        assignment = self.assignments.get(id)
        if not assignment:
            self.logger.warn("Assignment not found")
        return assignment

    def get_course_scores(self):
        today = datetime.today().astimezone(pytz.timezone('US/Pacific'))
        self.calculator.update(self.assignments, today)
        scores = []
        for course in self.courses.values():
            course_score = course.get_score(self.calculator)
            if course_score and course_score not in scores:
                scores.append(course_score)

        if scores:
            total_score = 0
            total_wpoints = 0.0
            total_upoints = 0.0
            for score in scores:
                total_score += score.score
                total_wpoints += score.wpoints
                total_upoints += score.upoints
            scores.append(CourseScore("Average", int(total_score / len(scores) + 0.5), total_wpoints / len(scores), total_upoints / len(scores)))

        return scores

    def get_average_score(self):
        scores = self.get_course_scores()
        total = 0
        for score in scores:
            total = total + score.score
        return int(total / len(scores) + 0.5)


    def check_calendar(self, start, end):
        status_list = []
        self.calculator.update(self.assignments, end)
        for _, assignment in self.assignments.items():
            due_date = assignment.get_due_date()
            if (due_date > start) and (due_date < end) and assignment.get_points_possible() > 0:
                assignment.possible_gain = self.calculator.gain(assignment)
                status_list.append(AssignmentStatus(assignment))
        return status_list

    def check_daily_course_submissions(self, date):
        date = date.astimezone(pytz.timezone('US/Pacific'))
        self.calculator.update(self.assignments, date)
        status_list = []
        for assignment in self.assignments.values():
            _, is_due_on_date = assignment.is_due(date)
            # print("{} {} {}".format(assignment.get_name(), assignment.get_due_date().date(), date.date()))
            if is_due_on_date:
                if assignment.is_graded():
                    state = SubmissionStatus.Marked
                elif not assignment.can_submit():
                    state = SubmissionStatus.External
                elif assignment.is_submitted():
                    state = SubmissionStatus.Submitted
                else:
                    state = SubmissionStatus.Not_Submitted
                assignment.status = state
                assignment.possible_gain = self.calculator.gain(assignment)
                status_list.append(AssignmentStatus(assignment))
        return status_list

    def check_course_assignments(self, end_date):
        report = []
        self.calculator.update(self.assignments, end_date)
        for id, assignment in self.assignments.items():
            #group_id = assignment.get_group()
            if assignment.is_valid and self.calculator.includes_assignment(assignment) and (assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date):
            #if assignment.is_valid and (group_id in self.group_max) and (assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date):
                status = None
                possible_gain = self.calculator.gain(assignment)
                if assignment.is_missing():
                    status = SubmissionStatus.Missing
                #elif assignment.is_late():
                #    status = SubmissionStatus.Late
                elif assignment.is_graded() and not assignment.is_being_marked():
                    #print("%s %s %d %d %d" % (assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.weightings[assignment.group], possible_gain))
                    if possible_gain > 0:
                        status = SubmissionStatus.Low_Score
                elif assignment.is_being_marked():
                    status = SubmissionStatus.Being_Marked
                if assignment.submission_comments and assignment.get_score() < 100:
                    last_comment = assignment.submission_comments[-1]
                    if last_comment.author not in self.user.name:
                        if not assignment.get_submission_date() or last_comment.date > assignment.get_submission_date():
                            status = SubmissionStatus.Has_Comment
                            # print("{} {} {}".format(last_comment.text, last_comment.date, assignment.get_score()))
                if status:
                    assignment.status = status
                    assignment.possible_gain = possible_gain
                    self.assignments[id] = assignment
                    report.append(AssignmentStatus(assignment))

        return report


    def run_daily_submission_report(self, date):
        end_of_today = date.astimezone(pytz.timezone('US/Pacific')).replace(hour=23, minute=59)
        # print(end_of_today)
        return self.check_daily_course_submissions(end_of_today)


    def run_calendar_report(self, date):
        start = date.astimezone(pytz.timezone('US/Pacific')).replace(hour=23, minute=59)
        end = start + timedelta(days=7)
        calendar = self.check_calendar(start, end)
        return(sorted(calendar, key=lambda a: a.due_date))

    def run_assignment_report(self, filter, min_gain):
        start_time = time.time()
        filtered_report = []
        yesterday = datetime.today().astimezone(pytz.timezone('US/Pacific')).replace(hour=0, minute=0)
        Assignment.comments_loaded = 0
        assignments = self.check_course_assignments(yesterday)
        for assignment in assignments:
            if (assignment.status == filter):
                filtered_report.append(assignment)
                if (filter in [SubmissionStatus.Low_Score, SubmissionStatus.Has_Comment]) and (min_gain > assignment.possible_gain):
                    filtered_report.pop()
        if filter in [SubmissionStatus.Low_Score, SubmissionStatus.Missing]:
            filtered_report.sort(key=lambda a: a.possible_gain, reverse=True)
        self.logger.info("Comments loaded {}/{}".format(Assignment.comments_loaded, len(self.assignments)))
        print("Time = {}".format(time.time() - start_time))
        return filtered_report


    def is_valid_assignment_group(self, group_name):
        for name in ["Attendance", "Imported Assignments", "Extra", "Final"]:
            if name in group_name:
                return False
        return True

    def get_remaining_service_hours(self):
        default_hours = 10
        for course in self.courses.values():
            if "Service" in course.raw.name:
                self.logger.info("Christian service term = {}".format(course.term))
                assignments = course.get_assignments(self.user, get_invalid=True)
                for _, assignment in assignments.items():
                    if course.term in assignment.assignment.name:
                        expected = assignment.get_points_possible()
                        if expected:
                            if expected > default_hours:
                                expected = default_hours
                            done = assignment.get_raw_score()
                            if done is None:
                                done = 0
                            print("Hours = {}/{}".format(done, expected))
                            hours_remaining =  expected - done
                            if hours_remaining < 0:
                                hours_remaining = 0
                            return hours_remaining
        return default_hours
