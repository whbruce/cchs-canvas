import time
import json
from flask import Flask, request
from flask import render_template
from flask_table import Table, Col, LinkCol
from datetime import datetime
import pytz
from typing import NamedTuple
from reporter import Reporter
from assignment import Assignment, AssignmentStatus, SubmissionStatus
import logging

class ReporterFactory(object):
    students = {}
    instances = {}
    current_student = None

    @staticmethod
    def get_students():
        if not ReporterFactory.students:
            with open('config.json') as json_file:
                ReporterFactory.students = json.load(json_file)
        return ReporterFactory.students.keys()

    @staticmethod
    def create(student):
        if not student in ReporterFactory.instances:
            ReporterFactory.get_students()
            student = student.lower()
            api_key = ReporterFactory.students[student]['key']
            user_id = ReporterFactory.students[student]['id']
            ReporterFactory.current_student = student
            ReporterFactory.instances[student] = Reporter(api_key, user_id, term="Spring_2022")
        return ReporterFactory.instances[student]

    @staticmethod
    def get():
        if ReporterFactory.current_student:
            return ReporterFactory.instances[ReporterFactory.current_student]
        else:
            return None

def mm_dd(date):
    if (date):
        return date.strftime("%m/%d")
    else:
        return "??/??"

class ScoreTable(Table):
    course = Col('Course')
    score = Col('Score')

class CourseStatusString:
    def __init__(self, c):
        self.course = c.course
        self.score = c.score
        self.wpoints = int(100*c.wpoints)/100
        self.upoints = int(100*c.upoints)/100

class AssignmentStatusString:
    def __init__(self, a):
        self.course = a.course
        self.id = a.id
        self.name = a.name[0:25]
        self.status = a.status.name
        self.due = mm_dd(a.due_date)
        self.submitted = mm_dd(a.submission_date)
        self.graded = mm_dd(a.graded_date)
        self.score = int(a.possible_gain)
        self.attempts = a.attempts
        self.possible_gain = a.possible_gain

class CommentStatusString:
    def __init__(self, c):
        self.author = c.author
        self.date = mm_dd(c.date)
        self.text = c.text

class AssignmentTable(Table):
    course = Col('Course')
    name = LinkCol('Name', 'single_item',
                   url_kwargs=dict(assignment_id='id'), attr='name')
    due = Col('Due')
    score = Col('Gain')

class AssignmentStatusTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    status = Col('Status')
    possible_gain = Col('Gain')

class AssignmentScoreTable(Table):
    course = Col('Course')
    name = LinkCol('Name', 'single_item',
                   url_kwargs=dict(assignment_id='id'), attr='name')
    due = Col(' Due ')
    submitted = Col(' Done ')
    graded = Col('Graded')
    attempts = Col('Try')
    score = Col('Gain')

class CourseTable(Table):
    course = Col('Course')
    score = Col('Score')
    wpoints = Col('WGPA')
    upoints = Col('UGPA')

class AnnouncementTable(Table):
    due = Col('Date')
    course = Col('Course')

class CommentTable(Table):
    author = Col('Author')
    date = Col('Date')
    text = Col('Comment')

def to_string_table(assignments, layout):
    table_entries = {
        AssignmentScoreTable  : AssignmentStatusString,
        AssignmentStatusTable : AssignmentStatusString,
        AssignmentTable       : AssignmentStatusString,
        CourseTable           : CourseStatusString,
        AnnouncementTable     : CommentStatusString,
        CommentTable          : CommentStatusString
    }
    table_entry = table_entries[layout]
    table=[]
    for assignment in assignments:
        table.append(table_entry(assignment))
    return layout(table)

def run_assignment_report(reporter, query, min_gain):
    table = AssignmentTable
    report = reporter.run_assignment_report(query, min_gain)
    return to_string_table(report, table)

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

@app.route("/")
def home():
    return render_template('index.html', students = ReporterFactory.get_students())

@app.route('/assignment/<int:assignment_id>')
def single_item(assignment_id):
    reporter = ReporterFactory.get()
    assignment = reporter.get_assignment(assignment_id)
    comments = to_string_table(assignment.submission_comments, CommentTable)
    comments.no_items = "No comments"
    return render_template('assignment.html', assignment = AssignmentStatus(assignment), comments = comments)

@app.route("/all")
def all():
    start_time = time.time()
    student = request.args.get('student')
    low_min_gain = int(request.args.get('min_gain'))
    missing_min_gain = int(request.args.get('include_zero_scores') is None)
    reporter = ReporterFactory.create(student)
    reporter.load_assignments()
    scores_list = reporter.get_course_scores()
    scores = to_string_table(scores_list, CourseTable)
    date = datetime.today().astimezone(pytz.timezone('US/Pacific')).strftime("%m/%d/%y %I:%M %p")
    today_list = reporter.run_daily_submission_report(datetime.today())
    today = to_string_table(today_list, AssignmentStatusTable)
    week = to_string_table(reporter.run_calendar_report(datetime.today()), AssignmentTable)
    missing = run_assignment_report(reporter, SubmissionStatus.Missing, missing_min_gain)
    missing.no_items = "No missing assignments - nice work!"
    low_score = run_assignment_report(reporter, SubmissionStatus.Low_Score, low_min_gain)
    being_marked = run_assignment_report(reporter, SubmissionStatus.Being_Marked, 0)
    wgpa = scores_list[-1].wpoints if scores_list else 0
    ugpa = scores_list[-1].upoints if scores_list else 0
    summary = {
        "todo":         len(today.items),
        "wgpa":         wgpa,
        "ugpa":         ugpa,
        "service":      reporter.get_remaining_service_hours(),
        "time":         int(time.time() - start_time + 0.5),
        "missing":      len(missing.items),
        "low":          len(low_score.items),
        "being_marked": len(being_marked.items)
    }

    return render_template('all.html', student=student.capitalize(), date=date, summary=summary, scores=scores, today=today, week=week, missing=missing, low_score=low_score, being_marked=being_marked)



if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
