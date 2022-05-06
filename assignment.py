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
import utils
import inspect


class Comment:
    def __init__(self, comment):
        self.author = comment["author_name"].split()[0]
        self.date = utils.convert_date(comment["created_at"])
        text = comment["comment"].replace('\n', ' ')
        self.text = text

class Assignment:
    comments_loaded = 0

    def __init__(self, user, course_name, raw_assignment):
        self.logger = logging.getLogger(__name__)
        self.user = user
        self.course_name = course_name
        self.assignment = raw_assignment
        self.id = self.assignment.id
        self.course_id = self.assignment.course_id
        self.submission = self.assignment.submission
        self.submission_date = None
        self.have_loaded_submission_comments = False
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
            self.due_date = utils.convert_date(self.assignment.due_at)
            self.group = self.assignment.assignment_group_id
        else:
            self.logger.warn("Invalid assignment: {} {} {} {}".format(self.course_name, self.assignment.name, self.assignment.points_possible, self.submission.get('excused')))

    def populate_comments(self):
        if not self.have_loaded_submission_comments:
            # print("populate_comments(): {} called from {} ".format(self.get_name(), inspect.stack()[1].function))
            submission = self.assignment.get_submission(self.user, include=["submission_comments"])
            self.have_loaded_submission_comments = True
            Assignment.comments_loaded += 1
            for comment in submission.submission_comments:
                self.submission_comments.append(Comment(comment))

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
        for submission_type in self.assignment.submission_types:
            if submission_type in ['none', 'external_tool', 'on_paper']:
                return False
        return True

    def is_graded(self):
        return self.submission.get('entered_score') is not None and self.submission.get('workflow_state') != "pending_review"

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
        if self.get_attempts() == 0 and self.get_score() == 0:
            return self.get_submission_date() is not None
        else:
            return True

    def is_being_marked(self):
        if not self.is_submitted():
            return False
        if self.is_submitted() and not self.is_graded():
            return True
        if self.submission.get('submitted_at'):
            # print("{} {} {}".format(self.get_name(), self.get_submission_date(), self.get_graded_date()))
            return self.get_submission_date() > self.get_graded_date()
        else:
            return False

    def get_submission_date(self):
        if self.submission_date:
            return self.submission_date
        if self.submission.get('submitted_at') is None:
            # print("get_submission_date(): {} called from {} ".format(self.get_name(), inspect.stack()[1].function))
            date = None
            self.populate_comments()
            for comment in self.submission_comments:
                if comment.text.startswith("Submitted"):
                    text = comment.text.split(' ')
                    if len(text) > 1:
                        try:
                            fmt = "%m/%d"
                            date = datetime.strptime(text[1], fmt)
                            self.submission_date = date.replace(year=datetime_date.today().year)
                            self.logger.info("{} submitted at {}".format(self.get_name(), self.submission_date))
                            return self.submission_date
                        except ValueError:
                            self.logger.error("Manual submission date for {} is {}, not in mm/dd format".format(self.get_name(), text[1]))
            return None
        else:
            self.submission_date = utils.convert_date(self.submission.get('submitted_at'))
            return self.submission_date

    def get_graded_date(self):
        if (self.is_graded()):
            return utils.convert_date(self.submission.get('graded_at'))
        else:
            return None

    def is_missing(self):
        #now = datetime.today().astimezone(pytz.timezone('US/Pacific'))
        #due = self.is_due(now)[0]
        marked_as_missing = self.submission.get('missing')
        graded_as_zero = self.is_graded() and self.get_raw_score() == 0 and self.get_attempts() == 0
        submitted = self.is_submitted()
        #print("{} {} {}".format(self.get_course_name(), self.get_name(), graded_as_zero))
        return (marked_as_missing and not submitted) or graded_as_zero

    def is_late(self):
        return self.submission.get('late') and self.get_score() == 0

    def get_group(self):
        return self.group


class Announcement(NamedTuple):
    course: str
    title: str
    message: str
    date: datetime

class SubmissionStatus(Enum):
    Submitted = 1
    Not_Submitted = 2
    Marked = 3
    Missing = 4
    Late = 5
    Low_Score = 6
    External = 7
    Being_Marked = 8
    Has_Comment = 9


class AssignmentStatus():
    def __init__(self, assignment):
        self.a = assignment
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

