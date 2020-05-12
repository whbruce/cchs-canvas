import sys
import os
import datetime
import pytz
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
LOW_SCORE_THRESHOLD = 60
   

def convert_date(canvas_date):
    date = datetime.strptime(canvas_date, '%Y-%m-%dT%H:%M:%SZ')         
    if date.hour < 8:
        date = date - timedelta(hours=8)
    return date


class Assignment:
    def __init__(self, assignment):
        self.assignment = assignment
        # self.submission = assignment.get_submission(AB_USER_ID, include=["submission_comments"])
        self.submission = assignment.submission
        self.is_valid = self.assignment.due_at and self.assignment.points_possible
        if (self.is_valid):
            self.due_date = convert_date(self.assignment.due_at)         

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

    def get_submission_date(self):
        if (self.is_submitted()):
            return convert_date(self.submission.get('submitted_at'))
        else:
            return None

    def is_missing(self):
        return self.submission.get('missing')

    def is_late(self):
        return self.submission.get('late') and self.get_score() == 0


class Announcement(NamedTuple):
    course: str
    title: str
    message: str
    date: datetime

class CourseScore(NamedTuple):
    course: str
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
    submission_date: datetime = None

# Examples
# Physics submitted      https://cchs.instructure.com/courses/5347/assignments/160100/submissions/5573
# Geometry comments      https://cchs.instructure.com/courses/5205/assignments/159434/submissions/5573
# Geometry not submitted https://cchs.instructure.com/courses/5205/assignments/159972/submissions/5573
# Wellness no submission https://cchs.instructure.com/courses/5237/assignments/158002/submissions/5573

class Reporter:
    def __init__(self):
        self.canvas = Canvas(API_URL, AB_API_KEY)
        self.user = self.canvas.get_user(AB_USER_ID)
        self.courses = self.user.get_courses(enrollment_state="active", include=["total_scores"])
        self.course_dict = {}        
        for c in self.courses:
            self.course_dict[c.id] = c.name
        self.report = None

    def reset(self):
        self.report = None

    def is_valid_course(self, course):
        for name in ['Support', 'Service', 'Utility', 'Counseling']:
            if name in course.name:
                return False
        return True

    def course_short_name(self, course):
        name = course if isinstance(course, str) else course.name
        name = name[9:]
        return name.partition(' ')[0]

    def get_course_scores(self):
        enrollments = self.user.get_enrollments()
        scores = []
        total = 0        
        for e in enrollments:
            if e.grades.get('current_score'):
                name = self.course_short_name(self.course_dict[e.course_id])
                score = int(e.grades.get('current_score') + 0.5)
                scores.append(CourseScore(name, score))
                total = total + score
        scores.append(CourseScore("Average", int(total / len(scores) + 0.5)))
        return scores
            
    def get_average_score(self):
        scores = self.get_course_scores()
        total = 0
        for score in scores:
            total = total + score.score
        return int(total / len(scores) + 0.5)


    def check_daily_course_submissions(self, course, date):
        date = date.astimezone(pytz.timezone('US/Pacific'))
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
                elif assignment.get_score() > 0 and assignment.get_score() <= LOW_SCORE_THRESHOLD:
                    status = SubmissionStatus.Low_Score
                if (status):
                    status_list.append(AssignmentStatus(self.course_short_name(course), assignment.get_name(), assignment.get_due_date(), assignment.get_score(), status, assignment.get_submission_date()))
                    #print("%-8s, %-30.30s, %s, %s" % (self.course_short_name(course), assignment.get_name(), assignment.get_due_date().strftime("%m/%d"), status))
        return status_list

    def run_daily_submission_report(self, date):
        status_list = []
        for course in self.courses:
            status_list.extend(self.check_daily_course_submissions(course, date))
        return status_list

    def run_assignment_report(self, filter):
        filtered_report = []            
        if not self.report:
            self.report = []
            for course in self.courses:
                self.report.extend(self.check_course_assigments(course))
        for assignment in self.report:
            if (assignment.status == filter):
                filtered_report.append(assignment)
        if (filter == SubmissionStatus.Low_Score):
            filtered_report.sort(key=lambda a: a.score)
        return filtered_report

    def is_useful_announcement(self, title):
        if title.startswith("****"):
            return False
        elif title.startswith("Attendance"):
            return False            
        return True

    def get_announcements(self):
        courses=[]
        for id in self.course_dict:
            courses.append("course_" + str(id))
        today = datetime.today().astimezone(pytz.timezone('US/Pacific'))
        start_date = today - timedelta(hours=12)
        start_date = start_date.strftime("%Y-%m-%d")
        announcements=[]
        for a in self.canvas.get_announcements(context_codes=courses, start_date=start_date):
            if self.is_useful_announcement(a.title):
                course = self.course_short_name(self.course_dict[int(a.context_code[7:])])
                announcements.append(Announcement(course, a.title, a.message, a.posted_at))
        return announcements
