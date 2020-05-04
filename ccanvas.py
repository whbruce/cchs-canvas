import sys
import datetime
import json
from enum import Enum
from typing import NamedTuple
from canvasapi import Canvas
from datetime import datetime
from datetime import timedelta

API_URL = "https://cchs.instructure.com"
HB_API_KEY = "2817~tdljhwYEfDtAQtJhe5GDw0ACh4jrBT4Zm9MUz6LAFrYEPrebelWCZX6XwQNbZWVH"
AB_API_KEY = "2817~Ikko2aFRhG18kdv8dModOpP30IpW2sPLKw5sTOwwEFHD7E9Prvj5aki8c2oAXRiV"
AB_USER_ID = 5573
   
class Assignment:
    def __init__(self, assignment):
        self.assignment = assignment
        # self.submission = assignment.get_submission(AB_USER_ID, include=["submission_comments"])
        self.submission = assignment.submission
        self.is_valid = self.assignment.due_at and self.assignment.points_possible
        if (self.is_valid):
            self.due_date = datetime.strptime(self.assignment.due_at, '%Y-%m-%dT%H:%M:%SZ')         
            if self.due_date.hour < 8:
                self.due_date = self.due_date - timedelta(hours=8)

    def get_name(self):
        return self.assignment.name

    def get_due_date(self):
        return self.due_date

    def is_due(self, date):
        if not self.is_valid:
            return False
        return self.due_date.date() == date.date()

    def can_submit(self):
        return 'none' not in self.assignment.submission_types

    def is_graded(self):
        return self.submission.get('score')

    def get_score(self):
        if self.is_graded():
            return (100 * self.submission.get('score')) / self.assignment.points_possible
        else:
            return 0

    def is_submitted(self):
        return self.submission.get('submitted_at')

    def is_missing(self):
        return self.submission.get('missing')

    def is_late(self):
        return self.submission.get('late') and self.get_score() == 0


class CourseStatus(NamedTuple):
    subject: str
    score: int

class SubmissionStatus(Enum):
    Submitted = 1
    Not_Submitted = 2
    Marked = 3
    Missing = 4
    Late = 5
    Low_Score = 6
    External = 7

class AssignmentStatus(NamedTuple):
    course: str
    name: str
    due_date: datetime
    score: int
    status: SubmissionStatus

# Examples
# Physics submitted      https://cchs.instructure.com/courses/5347/assignments/160100/submissions/5573
# Geometry comments      https://cchs.instructure.com/courses/5205/assignments/159434/submissions/5573
# Geometry not submitted https://cchs.instructure.com/courses/5205/assignments/159972/submissions/5573
# Wellness no submission https://cchs.instructure.com/courses/5237/assignments/158002/submissions/5573

class Reporter:
    def __init__(self):
        self.canvas = Canvas(API_URL, AB_API_KEY)
        self.user = self.canvas.get_user(AB_USER_ID)
        self.report = None

    def is_valid_course(self, course):
        for name in ['Support', 'Service', 'Utility', 'Counseling']:
            if name in course.name:
                return False
        return True

    def course_short_name(self, course):
        name = course.name[9:]
        return name.partition(' ')[0]

    def check_daily_course_submissions(self, course, date):
        status_list = []
        if not self.is_valid_course(course):
            return status_list
        assignments = course.get_assignments(order_by="due_at", include=["submission"])
        for a in assignments:
            assignment = Assignment(a)
            if assignment.is_due(date):
                if assignment.is_graded():
                    state  = SubmissionStatus.Marked
                elif not assignment.can_submit():
                    state = SubmissionStatus.External
                elif assignment.is_submitted():
                    state = SubmissionStatus.Submitted 
                else:
                    state = SubmissionStatus.Not_Submitted
                # print("%-8s: %-20.20s [%s]" % (course_name, assignment.get_name(), state))
                status_list.append(AssignmentStatus(self.course_short_name(course), assignment.get_name(), assignment.get_due_date(), assignment.get_score(), state))
        return status_list

    def check_course_assigments(self, course):
        status_list = []
        if not self.is_valid_course(course):
            return status_list
        assignments = course.get_assignments(order_by="due_at", include=["submission"])
        for a in assignments:
            assignment = Assignment(a)
            if assignment.is_valid and assignment.get_due_date() < datetime.today():
                status = None
                if assignment.is_missing():
                    status = SubmissionStatus.Missing
                elif assignment.is_late():
                    status = SubmissionStatus.Late
                elif assignment.get_score() > 0 and assignment.get_score() <= 50:
                    status = SubmissionStatus.Low_Score
                if (status):
                    status_list.append(AssignmentStatus(self.course_short_name(course), assignment.get_name(), assignment.get_due_date(), assignment.get_score(), status))
                    #print("%-8s, %-30.30s, %s, %s" % (self.course_short_name(course), assignment.get_name(), assignment.get_due_date().strftime("%m/%d"), status))
        return status_list

    def run_daily_submission_report(self, date):
        status_list = []
        courses = self.user.get_courses(enrollment_state="active")
        for course in courses:
            status_list.extend(self.check_daily_course_submissions(course, date))
        return status_list

    def check_all_assigments(self):
        courses = self.user.get_courses(enrollment_state="active")
        for course in courses:
            self.report.extend(self.check_course_assigments(course))

    def run_assignment_report(self, filter):
        filtered_report = []            
        if not self.report:
            self.report = []
            self.check_all_assigments()
        for assignment in self.report:
            if (assignment.status == filter):
                filtered_report.append(assignment)
        return filtered_report


