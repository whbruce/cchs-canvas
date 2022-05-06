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
from canvasapi import Canvas
from canvasapi import exceptions
from datetime import datetime
from datetime import timedelta
from datetime import date as datetime_date
from course import Course
from assignment import Assignment, AssignmentStatus, SubmissionStatus
from weighting import WeightedScoreCalculator
import utils
import inspect

API_URL = "https://cchs.instructure.com"
graded_courses = ["History", "Spanish", "Chemistry", "Algebra", "Geometry", "Geo/Trig", "English", "Theology", "Biology", "Physics", "Computer",
                  "Government", "Financing", "Law", "Politics", "Ceramics", "Wellness", "PE", "Support" ]


def course_short_name(course):
    name = course if isinstance(course, str) else course.name
    for short_name in graded_courses:
        if short_name in name:
            return short_name
    return None

class CourseGroup(NamedTuple):
    course_id: int



class CourseScore(NamedTuple):
    course: str
    score: int
    wpoints: float
    upoints: float

# Examples
# Physics submitted      https://cchs.instructure.com/courses/5347/assignments/160100/submissions/5573
# Geometry comments      https://cchs.instructure.com/courses/5205/assignments/159434/submissions/5573
# Geometry not submitted https://cchs.instructure.com/courses/5205/assignments/159972/submissions/5573
# Wellness no submission https://cchs.instructure.com/courses/5237/assignments/158002/submissions/5573
class Reporter:
    def __init__(self, api_key, user_id, term):
        self.logger = logging.getLogger(__name__)
        self.user_id = user_id
        self.canvas = Canvas(API_URL, api_key)
        self.user = self.canvas.get_user('self')
        self.term = term
        self.courses = {}
        if self.term is None:
            start_time = time.time()
            for course in self.user.get_courses(enrollment_state="active", include=["total_scores", "term"]):
                self.courses[course.id] = Course(course)
            self.logger.info("get_courses took {}s".format(time.time() - start_time))
        else:
            self.term = self.term.replace('_', ' ')
            all_courses = self.user.get_courses(include=["total_scores", "term"])
            for c in all_courses:
                if c.term.get('name') == self.term:
                    self.courses[c.id] = Course(c)
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
            for _, course in self.courses.items():
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
        if assignment:
            assignment.populate_comments()
        else:
            self.logger.info("Assignment not found")
        return assignment

    def get_points(self, score, is_honors):
        table  = [
            (97, 4.30, 4),
            (93, 4.00, 4),
            (90, 3.70, 4),
            (87, 3.30, 3),
            (83, 3.00, 3),
            (80, 2.70, 3),
            (77, 2.30, 2),
            (73, 2.00, 2),
            (70, 1.70, 2),
            (67, 1.30, 1),
            (63, 1.00, 1),
            (60, 0.70, 1),
            (0,  0.0, 0)
        ]
        for entry in table:
            if score >= entry[0]:
                return SimpleNamespace(weighted = entry[1] + (0.5 * is_honors), unweighted = entry[2])

    def get_course_scores(self):
        enrollments = self.user.get_enrollments(state=["current_and_concluded"])
        scores = []
        for e in enrollments:
            if e.course_id in self.courses:
                course = self.courses[e.course_id]
                if course.is_valid and e.grades.get('current_score') is not None:
                    score = int(e.grades.get('current_score') + 0.5)
                    points = self.get_points(score, course.is_honors)
                    course_score = CourseScore(course.name, score, points.weighted, points.unweighted)
                    if course_score not in scores:
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
                assignment.populate_comments()
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
        return filtered_report


    def is_valid_assignment_group(self, group_name):
        for name in ["Attendance", "Imported Assignments", "Extra", "Final"]:
            if name in group_name:
                return False
        return True

    def get_remaining_service_hours(self):
        for _, course in self.courses.items():
            if "Service" in course.raw.name:
                print("Christian service term = {}".format(course.term))
                assignments = course.get_assignments(self.user, get_invalid=True)
                for _, assignment in assignments.items():
                    if course.term in assignment.assignment.name:
                        expected = assignment.get_points_possible()
                        if expected:
                            done = assignment.get_raw_score()
                            if done is None:
                                done = 0
                            print("Hours = {}/{}".format(done, expected))
                            return expected - done
        return 10
