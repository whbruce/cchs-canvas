import sys
import os
import datetime
import pytz
import json
import wget
import io
import urllib
import logging
from enum import Enum
from typing import NamedTuple
from canvasapi import Canvas
from canvasapi import exceptions
from datetime import datetime
from datetime import timedelta
import tempfile
import pptx

API_URL = "https://cchs.instructure.com"
LOW_SCORE_THRESHOLD = 60

graded_courses = ["History", "Spanish", "Chemistry", "Algebra", "Geometry", "English", "Theology", "Biology", "Physics", "Computer", "Wellness", "PE", "Support" ]


def course_short_name(course):
    name = course if isinstance(course, str) else course.name
    for short_name in graded_courses:
        if short_name in name:
            return short_name
    return None

def convert_date(canvas_date):
    date = datetime.strptime(canvas_date, '%Y-%m-%dT%H:%M:%SZ')
    if date.hour < 8:
        date = date - timedelta(hours=8)
    return date.replace(tzinfo=pytz.UTC)


class Comment:
    def __init__(self, comment):
        self.author = comment["author_name"].split()[0]
        self.date = convert_date(comment["created_at"])
        text = comment["comment"].replace('\n', ' ')
        self.text = text

class Assignment:
    def __init__(self, course, assignment):
        self.course_name = course_short_name(course.name)
        self.course_id = course.id
        self.assignment = assignment
        self.id = assignment.id
        self.submission = assignment.submission
        self.submission_comments = []
        self.due_date = None
        self.status = SubmissionStatus.Not_Submitted
        self.attempts = self.submission.get('attempt')
        self.possible_gain = 0
        self.is_valid = self.assignment.points_possible is not None \
                        and self.assignment.points_possible > 0 \
                        and self.assignment.due_at is not None \
                        and not "Attendance" in self.assignment.name \
                        and not self.submission.get('excused')
        if (self.is_valid):
            self.due_date = convert_date(self.assignment.due_at)
            self.group = assignment.assignment_group_id
        #else:
        #    print("Invalid: {} {} {} {}".format(self.course_name, self.assignment.name, self.assignment.points_possible, self.submission.get('excused')))

    def get_course_name(self):
        return self.course_name

    def get_name(self):
        return self.assignment.name

    def get_due_date(self):
        return self.due_date

    def is_due(self, date):
        if not self.is_valid:
            return False, False
        return self.due_date.date() <= date.date(), self.due_date.date() == date.date()

    def can_submit(self):
        return 'none' not in self.assignment.submission_types and 'external_tool' not in self.assignment.submission_types

    def is_graded(self):
        return self.submission.get('entered_score') is not None

    def get_score(self):
        if self.is_graded() and self.assignment.points_possible > 0:
            return (100 * self.submission.get('score')) / self.assignment.points_possible
        else:
            return 0

    def get_points_possible(self):
        return self.assignment.points_possible

    def get_points_dropped(self):
        if self.is_graded():
            return self.assignment.points_possible - self.submission.get('score')
        elif self.is_missing():
            return self.assignment.points_possible
        else:
            return 0

    def get_raw_score(self):
        if self.is_graded():
            return self.submission.get('score')
        else:
            return 0

    def get_attempts(self):
        return self.attempts if self.attempts is not None else 0

    def is_submitted(self):
        return self.get_attempts() > 0 or self.get_score() > 0

    def is_being_marked(self):
        if not self.is_submitted():
            return False
        if self.is_submitted() and not self.is_graded():
            return True
        if self.submission.get('submitted_at') is not None:
            return self.submission.get('submitted_at') > self.submission.get('graded_at')
        else:
            return False

    def get_submission_date(self):
        if self.submission.get('submitted_at') is not None:
            return convert_date(self.submission.get('submitted_at'))
        else:
            return None

    def get_graded_date(self):
        if (self.is_graded()):
            return convert_date(self.submission.get('graded_at'))
        else:
            return None

    def is_missing(self):
        now = datetime.today().astimezone(pytz.timezone('US/Pacific'))
        #print("is_missing: %s %s %s %s %s %s" % (self.course_name, self.assignment.name, now, self.get_due_date(), self.is_due(now)[0], self.is_submitted()))
        return (self.submission.get('missing') and (not self.is_graded() or (self.is_graded() and self.get_raw_score() == 0))) \
               or (self.is_due(now)[0] and not self.is_submitted())

    def is_late(self):
        return self.submission.get('late') and self.get_score() == 0

    def get_group(self):
        return self.group


class Announcement(NamedTuple):
    course: str
    title: str
    message: str
    date: datetime

class CourseScore(NamedTuple):
    course: str
    score: int
    points: float

class SubmissionStatus(Enum):
    Submitted = 1
    Not_Submitted = 2
    Marked = 3
    Missing = 4
    Late = 5
    Low_Score = 6
    External = 7
    Being_Marked = 8

class AssignmentStatus():
    def __init__(self, assignment):
        self.course_id = assignment.course_id
        self.course = assignment.course_name
        self.id = assignment.id
        self.name = assignment.get_name()
        self.due_date = assignment.get_due_date()
        self.score = assignment.get_score()
        self.submission_date = assignment.get_submission_date()
        self.graded_date = assignment.get_graded_date()
        self.status = assignment.status
        self.dropped = assignment.get_points_dropped()
        self.possible_gain = assignment.possible_gain
        self.attempts = assignment.get_attempts()
        self.submission_comments = assignment.submission_comments

# Examples
# Physics submitted      https://cchs.instructure.com/courses/5347/assignments/160100/submissions/5573
# Geometry comments      https://cchs.instructure.com/courses/5205/assignments/159434/submissions/5573
# Geometry not submitted https://cchs.instructure.com/courses/5205/assignments/159972/submissions/5573
# Wellness no submission https://cchs.instructure.com/courses/5237/assignments/158002/submissions/5573
class Reporter:
    def __init__(self, api_key, user_id, term, log_level):
        logging.basicConfig(level=log_level)
        self.logger = logging.getLogger(__name__)
        self.user_id = user_id
        self.canvas = Canvas(API_URL, api_key)
        self.user = self.canvas.get_user('self')
        self.term = term
        if self.term is None:
            self.courses = self.user.get_courses(enrollment_state="active", include=["total_scores", "term"])
        else:
            self.term = self.term.replace('_', ' ')
            all_courses = self.user.get_courses(include=["total_scores", "term"])
            self.courses = []
            for c in all_courses:
                if c.term.get('name') == self.term:
                    self.courses.append(c)
        self.course_dict = {}
        self.group_max = {}
        for c in self.courses:
            self.course_dict[c.id] = c.name
        self.weightings = self.get_assignments_weightings()
        for w in self.weightings:
            self.group_max[w] = 0
        self.report = None
        self.assignments = []

    def load_assignments(self):
        self.assignments = []
        for course in self.courses:
            course_name = self.course_short_name(course)
            if course_name:
                self.logger.info("Loading {} assignments".format(course_name))
                raw_assignments = course.get_assignments(order_by="due_at", include=["submission"])
                for a in raw_assignments:
                    assignment = Assignment(course, a)
                    # print("%s %s %s %s" % (assignment.get_due_date(), course_name, a, assignment.is_valid))
                    if assignment.is_valid:
                        self.assignments.append(assignment)

    def get_assignment(self, course_id, id):
        for assignment in self.assignments:
            if assignment.course_id == course_id and assignment.id == id:
                return assignment
        return None

    def course_short_name(self, course):
        name = course if isinstance(course, str) else course.name
        for short_name in graded_courses:
            if short_name in name:
                return short_name
        return None

    def is_valid_course(self, course):
        return self.course_short_name(course)

    def is_honors_course(self, course):
        return "Honors" in course

    def get_points(self, score, is_honors):
        table  = [
            (97, 4.30),
            (93, 4.00),
            (90, 3.70),
            (87, 3.30),
            (83, 3.00),
            (80, 2.70),
            (77, 2.30),
            (73, 2.00),
            (70, 1.70),
            (67, 1.30),
            (63, 1.00),
            (60, 0.70),
            (0, 0.0)
        ]
        for entry in table:
            if score >= entry[0]:
                return entry[1] + (0.5 * is_honors)

    def get_course_scores(self):
        enrollments = self.user.get_enrollments(state=["current_and_concluded"])
        scores = []
        total_score = 0
        total_points = 0.0
        for e in enrollments:
            if e.course_id in self.course_dict:
                full_name = self.course_dict[e.course_id]
                name = self.course_short_name(full_name)
                if name and e.grades.get('current_score'):
                    score = int(e.grades.get('current_score') + 0.5)
                    is_honors = self.is_honors_course(full_name)
                    points = self.get_points(score, is_honors)
                    if CourseScore(name, score, points) not in scores:
                        scores.append(CourseScore(name, score, points))
                    total_score = total_score + score
                    total_points = total_points + points

        # Fixing for missing score due to Canvas error
        if self.user_id == 5573 and self.term == "Fall 2020":
            score = 90
            points = self.get_points(score, False)
            scores.append(CourseScore("Algebra", score, points))
            total_score = total_score + score
            total_points = total_points + points

        if scores:
            scores.append(CourseScore("Average", int(total_score / len(scores) + 0.5), total_points / len(scores)))

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
        for assignment in self.assignments:
            due_date = assignment.get_due_date()
            if (due_date > start) and (due_date < end) and assignment.get_points_possible() > 0:
                assignment.possible_gain = assignment.get_points_possible()
                status_list.append(AssignmentStatus(assignment))
        return status_list

    def check_daily_course_submissions(self, date):
        date = date.astimezone(pytz.timezone('US/Pacific'))
        status_list = []
        for assignment in self.assignments:
            is_due, is_due_on_date = assignment.is_due(date)
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

    # Re-calculate weightings in case some some weights are not yet in use
    def update_weightings(self, end_date):
        for w in self.weightings:
            self.group_max[w] = 0
        course_groups = {}

        self.logger.info("Weighting first pass")
        for assignment in self.assignments:
            if assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date:
                group_id = assignment.get_group()
                self.logger.info(" {}[{}] = {}".format(assignment.get_course_name(), group_id, assignment.get_name()))
                self.logger.info(" - Checking assignment")
                self.logger.info("   - valid assignment: {}".format(assignment.is_valid))
                self.logger.info("   - valid group: {}".format(group_id in self.group_max))
                self.logger.info("   - graded: {}".format(assignment.is_graded()))
                self.logger.info("   - score: {}".format(assignment.get_score()))
                if assignment.is_valid and assignment.is_graded() and (group_id in self.group_max) and (assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date):
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


    def check_course_assigments(self, end_date, min_gain):
        self.update_weightings(end_date)
        status_list = []
        for i, assignment in enumerate(self.assignments):
            group_id = assignment.get_group()
            if assignment.is_valid and (group_id in self.group_max) and (assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date):
                status = None
                possible_gain = 0
                if assignment.is_missing():
                    status = SubmissionStatus.Missing
                    # print(assignment.get_name())
                    # print(self.group_max[assignment.group])
                    if self.group_max[assignment.group] + assignment.get_points_possible() == 0:
                        possible_gain = 0
                    else:
                        possible_gain = -1 * int((self.weightings[assignment.group] * assignment.get_points_dropped()) / (self.group_max[assignment.group] + assignment.get_points_possible()))
                #elif assignment.is_late():
                #    status = SubmissionStatus.Late
                elif assignment.is_graded() and not assignment.is_being_marked():
                    #print("%s %s %d %d %d" % (assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.weightings[assignment.group], possible_gain))
                    self.logger.info("{} [{}] {} {} {}".format(assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.weightings[assignment.group], self.group_max[assignment.group]))
                    possible_gain = int((self.weightings[assignment.group] * assignment.get_points_dropped()) / self.group_max[assignment.group])
                    if possible_gain >= min_gain:
                        status = SubmissionStatus.Low_Score
                elif assignment.is_being_marked():
                    status = SubmissionStatus.Being_Marked
                if (status):
                    submission = assignment.assignment.get_submission(self.user, include=["submission_comments"])
                    for comment in submission.submission_comments:
                        assignment.submission_comments.append(Comment(comment))
                    assignment.status = status
                    assignment.possible_gain = possible_gain
                    self.assignments[i] = assignment
                    status_list.append(AssignmentStatus(assignment))

        return status_list


    def run_daily_submission_report(self, date):
        end_of_today = date.astimezone(pytz.timezone('US/Pacific')).replace(hour=23, minute=59)
        # print(end_of_today)
        return self.check_daily_course_submissions(end_of_today)


    def run_calendar_report(self, date):
        start = date.astimezone(pytz.timezone('US/Pacific')).replace(hour=23, minute=59)
        end = start + timedelta(days=7)
        calendar =  self.check_calendar(start, end)
        return(sorted(calendar, key=lambda a: a.due_date))

    def run_assignment_report(self, filter, min_gain=3):
        filtered_report = []
        yesterday = datetime.today().astimezone(pytz.timezone('US/Pacific')).replace(hour=0, minute=0)
        if not self.report:
            self.report = self.check_course_assigments(yesterday, min_gain)
        for assignment in self.report:
            if (assignment.status == filter):
                filtered_report.append(assignment)
        if (filter in [SubmissionStatus.Low_Score, SubmissionStatus.Missing]):
            reverse = filter == SubmissionStatus.Low_Score
            filtered_report.sort(key=lambda a: a.possible_gain, reverse=reverse)
        return filtered_report


    def is_valid_assignment_group(self, group_name):
        for name in ["Attendance", "Imported Assignments", "Extra", "Final"]:
            if name in group_name:
                return False
        return True

    def get_assignments_weightings(self):
        weightings = {}
        self.assignment_groups = {}
        self.equal_weighted_courses = []
        for c in self.courses:
            if self.is_valid_course(c):
                assignment_group = []
                groups = c.get_assignment_groups()
                for g in groups:
                    # print("{}: {} ({})".format(c.name, g.name, g.id))
                    if self.is_valid_assignment_group(g.name):
                        w = g.group_weight
                        if w == 0:
                            w = 100
                            self.equal_weighted_courses.append(c.id)
                        weightings[g.id] = w
                        assignment_group.append(g.id)
                        # print("%s %s %s %d" % (self.course_short_name(c.name), g.name, g.id, w))
                self.assignment_groups[c.id] = assignment_group
        return weightings

