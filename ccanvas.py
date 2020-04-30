import sys
import argparse
import datetime
import json
from canvasapi import Canvas
from datetime import datetime
from datetime import timedelta

API_URL = "https://cchs.instructure.com"
HB_API_KEY = "2817~tdljhwYEfDtAQtJhe5GDw0ACh4jrBT4Zm9MUz6LAFrYEPrebelWCZX6XwQNbZWVH"
AB_API_KEY = "2817~Ikko2aFRhG18kdv8dModOpP30IpW2sPLKw5sTOwwEFHD7E9Prvj5aki8c2oAXRiV"
AB_USER_ID = 5573
   
def is_valid_course(course):
    for name in ['Support', 'Service', 'Utility', 'Counseling']:
        if name in course.name:
            return False
    return True


def course_short_name(course):
    name = course.name[9:]
    return name.partition(' ')[0]


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

# Physics submitted      https://cchs.instructure.com/courses/5347/assignments/160100/submissions/5573
# Geometry comments      https://cchs.instructure.com/courses/5205/assignments/159434/submissions/5573
# Geometry not submitted https://cchs.instructure.com/courses/5205/assignments/159972/submissions/5573
# Wellness no submission https://cchs.instructure.com/courses/5237/assignments/158002/submissions/5573
def check_daily_course_submissions(course, date):
    course_name = course_short_name(course)
    assignments = course.get_assignments(order_by="due_at", include=["submission"])
    for a in assignments:
        assignment = Assignment(a)
        if assignment.is_due(date):
            if assignment.is_graded():
                state = "Marked - %d%%" % (assignment.get_score())
            else:
                if assignment.is_submitted():
                    state = "Submitted" 
                else:
                    state = "Not submitted" 
            print("%-8s: %s [%s]" % (course_name, a.name, state))


def check_assigments(course):
    have_assignment = False
    course_name = course_short_name(course)
    assignments = course.get_assignments(order_by="due_at", include=["submission"])
    for a in assignments:
        assignment = Assignment(a)
        if assignment.is_valid and assignment.get_due_date() < datetime.today():
            status = None
            if assignment.is_missing():
                status = "Missing"
            elif assignment.is_late():
                status = "Late"
            elif assignment.get_score() > 0 and assignment.get_score() < 60:
                status = "Low score (%d%%)" % (assignment.get_score())
            if (status):
                print("%-8s, %-30.30s, %s, %s" % (course_name, assignment.get_name(), assignment.get_due_date().strftime("%m/%d"), status))


def run_daily_submission_report(user, date):
    print("Checking assignments for", date.strftime("%m/%d"))
    courses = user.get_courses(enrollment_state="active")
    for course in courses:
        if is_valid_course(course):
            check_daily_course_submissions(course, date)

def run_assignment_report(user):
    print("Course, Assignment, Date, Status")
    courses = user.get_courses(enrollment_state="active")
    for course in courses:
        if is_valid_course(course):
            check_assigments(course)

# Main
parser = argparse.ArgumentParser(description='Query Canvas')
parser.add_argument('--date', type=datetime.fromisoformat, default=datetime.today(), help='date in ISO format')
parser.add_argument('--all', action="store_true", help='check for missing assignments')
args = parser.parse_args()
canvas = Canvas(API_URL, AB_API_KEY)
user = canvas.get_user(AB_USER_ID)
if args.all:
    run_assignment_report(user)
else:
    run_daily_submission_report(user, args.date)


