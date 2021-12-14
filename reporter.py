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
import utils
import inspect

API_URL = "https://cchs.instructure.com"
graded_courses = ["History", "Spanish", "Chemistry", "Algebra", "Geometry", "Geo/Trig", "English", "Theology", "Biology", "Physics", "Computer",
                  "Government", "Financing", "Ceramics", "Wellness", "PE", "Support" ]


def course_short_name(course):
    name = course if isinstance(course, str) else course.name
    for short_name in graded_courses:
        if short_name in name:
            return short_name
    return None

class CourseGroup(NamedTuple):
    course_id: int


class WeightedScoreCalculator:

    def __init__(self, courses):
        self.group_max = {}
        self.weightings = {}
        self.assignment_groups = {}
        self.equal_weighted_courses = []
        self.logger = logging.getLogger(__name__)
        for c in courses:
            course = Course(c)
            if course.is_valid:
                assignment_group = []
                groups = course.assignment_groups()
                for g in groups:
                    w = g.group_weight
                    if w == 0:
                        w = 100
                        self.equal_weighted_courses.append(c.id)
                    self.weightings[g.id] = w
                    assignment_group.append(g.id)
                    # print("%s %s %s %d" % (self.course_short_name(c.name), g.name, g.id, w))
                self.assignment_groups[c.id] = assignment_group
        for w in self.weightings:
            self.group_max[w] = 0


    # Re-calculate weightings in case some some weights are not yet in use
    def update(self, assignments, end_date):
        for w in self.weightings:
            self.group_max[w] = 0
        course_groups = {}

        self.logger.info("Weighting first pass")
        for id, assignment in assignments.items():
            if assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date:
                group_id = assignment.get_group()
                self.logger.info(" {}[{}] = {} ({})".format(assignment.get_course_name(), group_id, assignment.get_name(), id))
                self.logger.info(" - Checking assignment")
                self.logger.info("   - valid assignment: {}".format(assignment.is_valid))
                self.logger.info("   - valid group: {}".format(group_id in self.group_max))
                self.logger.info("   - graded: {}".format(assignment.is_graded()))
                self.logger.info("   - score: {}".format(assignment.get_score()))
                if assignment.is_graded() and (group_id in self.group_max):
                    course_id = assignment.course_id
                    if not course_id in course_groups:
                        course_groups[course_id] = []
                    course_group = course_groups[course_id]
                    if group_id not in course_group:
                        course_group.append(group_id)
                    self.group_max[group_id] = self.group_max[group_id] + assignment.get_points_possible()

        self.logger.info("Weighting second pass")
        for course_id in course_groups:
            group = course_groups[course_id]
            # print("{} {}".format(course_id, group))
            if len(group) == 1:
                for w in self.assignment_groups.get(course_id):
                    self.weightings[w] = 100
                if course_id not in self.equal_weighted_courses:
                    self.equal_weighted_courses.append(course_id)
            if course_id in self.equal_weighted_courses:
                points = 0
                for i in self.assignment_groups.get(course_id):
                    points = points + self.group_max[i]
                for i in self.assignment_groups.get(course_id):
                    self.group_max[i] = points

    def includes_assignment(self, assignment):
        group_id = assignment.get_group()
        return group_id in self.group_max

    def missing_gain(self, assignment):
        self.logger.info("Gain: {} [{}] {} {} {}".format(assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.weightings[assignment.group], self.group_max[assignment.group]))
        possible_gain = 0
        if self.group_max[assignment.group] + assignment.get_points_possible() > 0:
            possible_gain = int((self.weightings[assignment.group] * assignment.get_points_dropped()) / (self.group_max[assignment.group] + assignment.get_points_possible()))
        return possible_gain

    def marked_gain(self, assignment):
        possible_gain = int((self.weightings[assignment.group] * assignment.get_points_dropped()) / self.group_max[assignment.group])
        return possible_gain


class CourseScore(NamedTuple):
    course: str
    score: int
    points: float
    weighted_points: float

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
        if self.term is None:
            start_time = time.time()
            self.courses = self.user.get_courses(enrollment_state="active", include=["total_scores", "term"])
            self.logger.info("get_courses took {}s".format(time.time() - start_time))
        else:
            self.term = self.term.replace('_', ' ')
            all_courses = self.user.get_courses(include=["total_scores", "term"])
            self.courses = []
            for c in all_courses:
                if c.term.get('name') == self.term:
                    self.courses.append(c)
        now = datetime.today().replace(tzinfo=pytz.UTC)
        self.courses = [c for c in self.courses if utils.convert_date(c.term["end_at"]) > now]
        self.course_dict = {}
        for c in self.courses:
            self.course_dict[c.id] = Course(c)
        self.calculator = WeightedScoreCalculator(self.courses)

    def get_assignments(self, user, course):
        course = Course(course)
        return course.get_assignments(user)
        #if course.is_valid:
        #    self.logger.info("Loading {} assignments".format(course.name))
        #    raw_assignments = course.get_assignments(order_by="due_at", include=["submission"])
        #    for a in raw_assignments:
        #        assignment = Assignment(self.user, course, a)
        #        self.logger.info("   - name: {}".format(assignment.get_name()))
        #        self.logger.info("   - last updated: {}".format(a.updated_at))
        #        self.logger.info("   - submitted: {}".format(assignment.get_submission_date()))
        #        if assignment.is_valid:
        #            assignments[a.id] = assignment
        #return assignments

    def load_assignments(self):
        self.assignments = {}
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []
            for course in self.courses:
                futures.append(executor.submit(self.get_assignments, user=self.user, course=course))
            for future in concurrent.futures.as_completed(futures):
                self.assignments.update(future.result())
        self.logger.info("load_assignments took {}s".format(time.time() - start_time))

    def load_assignments_serial(self):
        self.assignments = {}
        start_time = time.time()
        for course in self.courses:
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
                return entry[1] + (0.5 * is_honors), entry[2] + (0.5 * is_honors)

    def get_course_scores(self):
        enrollments = self.user.get_enrollments(state=["current_and_concluded"])
        scores = []
        for e in enrollments:
            if e.course_id in self.course_dict:
                course = self.course_dict[e.course_id]
                if course.is_valid and e.grades.get('current_score') is not None:
                    score = int(e.grades.get('current_score') + 0.5)
                    points = self.get_points(score, course.is_honors)
                    course_score = CourseScore(course.name, score, points[0], points[1])
                    if course_score not in scores:
                        scores.append(course_score)

        # Fixing for missing score due to Canvas error
        if self.user_id == 5573 and self.term == "Fall 2020":
            score = 90
            points = self.get_points(score, False)
            scores.append(CourseScore("Algebra", score, points[0], points[1]))
            total_score = total_score + score
            total_points = total_points + points[0]

        if scores:
            total_score = 0
            total_points = 0.0
            total_weighted_points = 0.0
            for score in scores:
                total_score += score.score
                total_points += score.points
                total_weighted_points += score.weighted_points
            scores.append(CourseScore("Average", int(total_score / len(scores) + 0.5), total_points / len(scores), total_weighted_points / len(scores)))

        return scores

    def get_average_score(self):
        scores = self.get_course_scores()
        total = 0
        for score in scores:
            total = total + score.score
        return int(total / len(scores) + 0.5)


    def check_calendar(self, start, end):
        status_list = []
        #self.update_weightings(end)
        for _, assignment in self.assignments.items():
            due_date = assignment.get_due_date()
            if (due_date > start) and (due_date < end) and assignment.get_points_possible() > 0:
                assignment.possible_gain = assignment.get_points_possible()
                status_list.append(AssignmentStatus(assignment))
        return status_list

    def check_daily_course_submissions(self, date):
        date = date.astimezone(pytz.timezone('US/Pacific'))
        status_list = []
        for _, assignment in self.assignments.items():
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
                possible_gain = 0
                if assignment.is_missing():
                    possible_gain = self.calculator.missing_gain(assignment)
                    status = SubmissionStatus.Missing
                #elif assignment.is_late():
                #    status = SubmissionStatus.Late
                elif assignment.is_graded() and not assignment.is_being_marked():
                    #print("%s %s %d %d %d" % (assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.weightings[assignment.group], possible_gain))
                    possible_gain = self.calculator.marked_gain(assignment)
                    if possible_gain > 0:
                        status = SubmissionStatus.Low_Score
                elif assignment.is_being_marked():
                    status = SubmissionStatus.Being_Marked
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
            # print(json.dumps(assignment.a.assignment.__dict__, default=str))
            if (assignment.status == filter):
                filtered_report.append(assignment)
                if (filter in [SubmissionStatus.Low_Score, SubmissionStatus.Missing]) and (min_gain > assignment.possible_gain):
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
        for course in self.courses:
            if "Service" in course.name:
                term = course.term["name"].split(' ')[0]
                print("Christian service term = {}".format(term))
                assignments = course.get_assignments(order_by="due_at", include=["submission"])
                for assignment in assignments:
                    if term in assignment.name:
                        expected = assignment.points_possible
                        if expected:
                            done = assignment.submission.get('score')
                            if done is None:
                                done = 0
                            print("Hours = {}/{}".format(done, expected))
                            return expected - done
        return 10
