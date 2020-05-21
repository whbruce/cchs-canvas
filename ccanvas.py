import sys
import os
import datetime
import pytz
import json
from enum import Enum
from typing import NamedTuple
from canvasapi import Canvas
from canvasapi import exceptions
from datetime import datetime
from datetime import timedelta

API_URL = "https://cchs.instructure.com"
HB_API_KEY = "2817~tdljhwYEfDtAQtJhe5GDw0ACh4jrBT4Zm9MUz6LAFrYEPrebelWCZX6XwQNbZWVH"
AB_API_KEY = "2817~Ikko2aFRhG18kdv8dModOpP30IpW2sPLKw5sTOwwEFHD7E9Prvj5aki8c2oAXRiV"
AB_USER_ID = 5573
LOW_SCORE_THRESHOLD = 60
   

def course_short_name(course):
    name = course if isinstance(course, str) else course.name
    name = name[9:]
    return name.partition(' ')[0]

def convert_date(canvas_date):
    date = datetime.strptime(canvas_date, '%Y-%m-%dT%H:%M:%SZ')         
    if date.hour < 8:
        date = date - timedelta(hours=8)
    return date.replace(tzinfo=pytz.UTC)


class Assignment:
    def __init__(self, course, assignment):
        self.course_name = course_short_name(course)
        self.assignment = assignment
        # self.submission = assignment.get_submission(AB_USER_ID, include=["submission_comments"])
        self.submission = assignment.submission
        self.is_valid = self.assignment.due_at and self.assignment.points_possible
        if (self.is_valid):
             self.due_date = convert_date(self.assignment.due_at)
             self.group = assignment.assignment_group_id         

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
        return self.submission.get('entered_score')

    def get_score(self):
        if self.is_graded():
            return (100 * self.submission.get('score')) / self.assignment.points_possible
        else:
            return 0

    def get_points_dropped(self):
        if self.is_graded():
            return self.assignment.points_possible - self.submission.get('score')
        else:
            return self.assignment.points_possible

    def get_raw_score(self):
        if self.is_graded():
            return self.submission.get('score')
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
        return self.submission.get('missing') and not self.is_graded()

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

class AssignmentStatus():
    def __init__(self, assignment, status, possible_gain = None):
        self.course = assignment.course_name
        self.name = assignment.get_name()
        self.due_date = assignment.get_due_date()
        self.score = assignment.get_score()
        self.status = status
        self.submission_date = assignment.get_submission_date()
        self.dropped = assignment.get_points_dropped()
        self.possible_gain = possible_gain

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
        self.group_max = {}        
        for c in self.courses:
            self.course_dict[c.id] = c.name
        self.weightings = self.get_assignments_weightings()
        for w in self.weightings:
            self.group_max[w] = 0
        self.assignments = None
        self.report = None

    def reset(self):
        self.report = None

    def is_valid_course(self, course):
        course_name = course if isinstance(course, str) else course.name
        for name in ['Academic', 'Service', 'Utility', 'Counseling', 'Sophomore']:
            if name in course_name:
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
            name = self.course_short_name(self.course_dict[e.course_id])
            if e.grades.get('current_score') and self.is_valid_course(name):
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


    def check_daily_course_submissions(self, date):
        date = date.astimezone(pytz.timezone('US/Pacific'))
        status_list = []
        for assignment in self.assignments:
            if assignment.is_due(date):
                if assignment.is_graded():
                    state  = SubmissionStatus.Marked
                elif not assignment.can_submit():
                    state = SubmissionStatus.External
                elif assignment.is_submitted():
                    state = SubmissionStatus.Submitted 
                else:
                    state = SubmissionStatus.Not_Submitted
                status_list.append(AssignmentStatus(assignment, state, 0))
        return status_list                    


    def check_course_assigments(self):
        status_list = []
        for assignment in self.assignments:
            status = None
            possible_gain = 0
            if assignment.is_missing():
                status = SubmissionStatus.Missing
            elif assignment.is_late():
                status = SubmissionStatus.Late
            elif assignment.get_points_dropped() > 5:
                status = SubmissionStatus.Low_Score
                possible_gain = (self.weightings[assignment.group] * assignment.get_points_dropped()) / self.group_max[assignment.group]
                # print("%s %s %d" % (assignment.course_name, assignment.get_name(), possible_gain))
            if (status):
                status_list.append(AssignmentStatus(assignment, status, possible_gain))
        return status_list

    def run_daily_submission_report(self, date):
        end_of_today = date.astimezone(pytz.timezone('US/Pacific')).replace(hour=23, minute=59)
        self.load_assignments(end_of_today)
        return self.check_daily_course_submissions(end_of_today)

    def load_assignments(self, end_date):
        for w in self.weightings:
            self.group_max[w] = 0
        self.assignments = []
        for course in self.courses:
            if self.is_valid_course(course):
                raw_assignments = course.get_assignments(order_by="due_at", include=["submission"])
                for a in raw_assignments:
                    assignment = Assignment(course, a)
                    if assignment.is_valid and assignment.get_due_date() < end_date:
                        self.assignments.append(assignment)
                        group_id = a.assignment_group_id
                        self.group_max[group_id] = self.group_max[group_id] + a.points_possible
                if course.id in self.equal_weighted_courses:
                    points = 0
                    for i in self.assignment_groups.get(course.id):
                        points = points + self.group_max[i]
                    for i in self.assignment_groups.get(course.id):
                        self.group_max[i] = points

    def run_assignment_report(self, filter):
        filtered_report = []            
        if not self.report:
            yesterday = datetime.today().astimezone(pytz.timezone('US/Pacific')).replace(hour=0, minute=0)
            self.load_assignments(yesterday)
            self.report = self.check_course_assigments()
        for assignment in self.report:
            if (assignment.status == filter):
                filtered_report.append(assignment)
        if (filter == SubmissionStatus.Low_Score):
            filtered_report.sort(key=lambda a: a.possible_gain, reverse=True)
        return filtered_report

    def run_submission_report(self):
        submissions = {}
        start_date = datetime(2020, 3, 16).astimezone(pytz.timezone('US/Pacific'))
        end_date = datetime.today().astimezone(pytz.timezone('US/Pacific'))
        num_submissions = 0
        for course in self.courses:
            if self.is_valid_course(course):
                assignments = course.get_assignments(order_by="due_at", include=["submission"])
                for a in assignments:
                    assignment = Assignment(a)
                    if assignment.is_valid:
                        due_date = assignment.get_due_date()
                        if due_date > start_date and due_date < end_date and assignment.is_submitted():
                            submission_date = assignment.get_submission_date().astimezone(pytz.timezone('US/Pacific'))
                            hour = submission_date.hour
                            if hour < 10:
                                hour = 10
                            if hour in submissions:
                                submissions[hour] = submissions[hour] + 1
                            else:
                                submissions[hour] = 1
                            num_submissions = num_submissions + 1    
                            print("%s %s is early" % (course, assignment.get_name()))
                            print("%s %s" % (due_date.strftime("%m/%d"), assignment.get_submission_date().astimezone(pytz.timezone('US/Pacific'))))
        print(len(submissions))
        max_hour = max(k for k, v in submissions.items())
        print(num_submissions)
        cum_pc = 0
        for hour in sorted(submissions.keys()):
            pc = (100 * submissions[hour]) / num_submissions
            cum_pc = cum_pc + pc
            print("%2d: %2d %2d %3d" % (hour, submissions[hour], pc, cum_pc))

    def is_useful_announcement(self, title):
        if title.startswith("****"):
            return False
        elif title.startswith("Attendance"):
            return False            
        return True

    def is_valid_assignment_group(self, group_name):
        for name in ["ATTENDANCE", "Imported", "Extra", "Final"]:
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

    def get_check_in_time(self, date):
        courses = [5237, 4843, 5237, 4843, 5237]
        day = date.weekday()
        if (day > 4):
            return None
        course_id = courses[day] 
        start_date = date - timedelta(hours=12)
        end_date = date + timedelta(hours=12)
        context_code = "course_" + str(course_id)        
        for a in self.canvas.get_announcements(context_codes=[context_code], start_date=start_date.strftime("%Y-%m-%d"), end_date=end_date.strftime("%Y-%m-%d")):
            a.course_id = int(a.context_code[7:])
            course = self.course_short_name(self.course_dict[int(a.context_code[7:])])
            try:
                for e in a.get_topic_entries():
                    if (e.user_id == AB_USER_ID):
                        t = convert_date(e.created_at).astimezone(pytz.timezone('US/Pacific'))
                        return t
            except exceptions.Forbidden:
                pass
        return None
