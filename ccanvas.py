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

graded_courses = ["History", "Spanish", "Chemistry", "Algebra", "English", "Theology", "Biology", "Wellness", "Support"]


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


class Assignment:
    def __init__(self, course, assignment):
        self.course_name = course_short_name(course.name)
        self.course_id = course.id
        self.assignment = assignment
        # self.submission = assignment.get_submission(AB_USER_ID, include=["submission_comments"])
        self.submission = assignment.submission
        self.is_valid = self.assignment.points_possible != None \
                        and self.assignment.due_at \
                        and not "Attendance" in self.assignment.name \
                        and not self.submission.get('excused')
        # self.assignment.submission_type and
        if (self.is_valid):
            self.due_date = convert_date(self.assignment.due_at)
            self.group = assignment.assignment_group_id
        else:
            self.due_date = None

    def get_name(self):
        return self.assignment.name

    def get_due_date(self):
        return self.due_date

    def is_due(self, date):
        if not self.is_valid:
            return False
        return self.due_date.date() == date.date()

    def can_submit(self):
        return 'none' not in self.assignment.submission_types and 'external_tool' not in self.assignment.submission_types

    def is_graded(self):
        return self.submission.get('entered_score') is not None

    def get_score(self):
        if self.is_graded():
            return (100 * self.submission.get('score')) / self.assignment.points_possible
        else:
            return 0

    def get_points_possible(self):
        return self.assignment.points_possible

    def get_points_dropped(self):
        if self.is_graded():
            return self.assignment.points_possible - self.submission.get('score')
        else:
            # return self.assignment.points_possible
            return 0

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
    def __init__(self, api_key, user_id, log_level):
        self.user_id = user_id
        self.canvas = Canvas(API_URL, api_key)
        self.user = self.canvas.get_user('self')
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
        logging.basicConfig(level=log_level)
        self.logger = logging.getLogger(__name__)

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

    def reset(self):
        self.report = None

    def course_short_name(self, course):
        name = course if isinstance(course, str) else course.name
        for short_name in graded_courses:
            if short_name in name:
                return short_name
        return None

    def is_valid_course(self, course):
        return self.course_short_name(course)

    def get_course_scores(self):
        enrollments = self.user.get_enrollments()
        scores = []
        total = 0
        for e in enrollments:
            name = self.course_short_name(self.course_dict[e.course_id])
            if name and e.grades.get('current_score'):
                score = int(e.grades.get('current_score') + 0.5)
                scores.append(CourseScore(name, score))
                total = total + score
        if scores:
            scores.append(CourseScore("Average", int(total / len(scores) + 0.5)))
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
                status_list.append(AssignmentStatus(assignment, SubmissionStatus.Not_Submitted, assignment.get_points_possible()))
        return status_list

    def check_daily_course_submissions(self, date):
        date = date.astimezone(pytz.timezone('US/Pacific'))
        status_list = []
        for assignment in self.assignments:
            if assignment.is_due(date):
                if assignment.is_graded():
                    state = SubmissionStatus.Marked
                elif not assignment.can_submit():
                    state = SubmissionStatus.External
                elif assignment.is_submitted():
                    state = SubmissionStatus.Submitted
                else:
                    state = SubmissionStatus.Not_Submitted
                status_list.append(AssignmentStatus(assignment, state, 0))
        return status_list

    # Re-calculate weightings in case some some weights are not yet in use
    def update_weightings(self, end_date):
        for w in self.weightings:
            self.group_max[w] = 0
        course_groups = {}
        for assignment in self.assignments:
            if assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date:
                group_id = assignment.get_group()
                if assignment.is_valid and assignment.is_graded() and (group_id in self.group_max) and (assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date):
                    course_id = assignment.course_id
                    if not course_id in course_groups:
                        course_groups[course_id] = []
                    course_group = course_groups[course_id]
                    if group_id not in course_group:
                        course_group.append(group_id)
                    # print("{} {} {}".format(course_name, group_id, assignment.get_name()))
                    self.group_max[group_id] = self.group_max[group_id] + assignment.get_points_possible()

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


    def check_course_assigments(self, end_date):
        self.update_weightings(end_date)
        status_list = []
        for assignment in self.assignments:
            group_id = assignment.get_group()
            if assignment.is_valid and (group_id in self.group_max) and (assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date):
                status = None
                possible_gain = 0
                if assignment.is_missing():
                    status = SubmissionStatus.Missing
                #elif assignment.is_late():
                #    status = SubmissionStatus.Late
                elif assignment.is_graded():
                    possible_gain = int((self.weightings[assignment.group] * assignment.get_points_dropped()) / self.group_max[assignment.group])
                    # print("%s %s %d %d %d" % (assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.weightings[assignment.group], possible_gain))
                    if possible_gain > 1:
                        status = SubmissionStatus.Low_Score
                if (status):
                    status_list.append(AssignmentStatus(assignment, status, possible_gain))

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

    def run_assignment_report(self, filter):
        filtered_report = []
        yesterday = datetime.today().astimezone(pytz.timezone('US/Pacific')).replace(hour=0, minute=0)
        report = self.check_course_assigments(yesterday)
        for assignment in report:
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
            course_name = self.course_short_name(course)
            if course_name:
                assignments = course.get_assignments(order_by="due_at", include=["submission"])
                for a in assignments:
                    assignment = Assignment(course_name, a)
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
                    if (e.user_id == self.user_id):
                        t = convert_date(e.created_at).astimezone(pytz.timezone('US/Pacific'))
                        return t
            except exceptions.Forbidden:
                pass
        return None


    def download_file(self, file):
        path = os.path.join(tempfile.gettempdir(), file.filename)
        print(path)
        print(file.url)
        if not os.path.exists(path):
            try:
                wget.download(file.url, out=path)
            except:
                return None
        return path

    def get_course(self, name):
        for course in self.courses:
            print(dir(course))
            if name in course.name:
                return course
        return None

    def get_english_notes(self):
        date = datetime.today().astimezone(pytz.timezone('US/Pacific'))
        course = self.get_course("English")
        pptx_mime_type =  "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        files = course.get_files(content_types=pptx_mime_type, sort="created_at", order="desc")
        date_format = "%#m.%d.pptx" if "win" in sys.platform else "%-m.%d.pptx"
        expected_filename = date.strftime(date_format)
        print(expected_filename)
        for file in files:
                if file.filename <= expected_filename:
                    break
        else:
            return None
        filename = file.filename
        print(filename)
        download_path = filename
        download_path = self.download_file(file)
        if not download_path:
            return None
        print(download_path)
        buffer = io.StringIO()
        print("### English Notes (%s)" % (filename), file=buffer)
        presentation = pptx.Presentation(download_path)
        slides = presentation.slides
        for slide in slides:
            header = True
            for shape in slide.shapes:
                # print(" - %s %s" % (shape, shape.has_text_frame))
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                            if (paragraph.text):
                                marker = "####" if header else "*"
                                print("%s %s" % (marker, paragraph.text), file=buffer)
                                header = False
        markdown_text = buffer.getvalue()
        buffer.close()
        return markdown_text
