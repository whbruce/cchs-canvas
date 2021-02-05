import json
from flask import Flask, request
from flask import render_template
from flask_table import Table, Col
from datetime import datetime
import pytz
from typing import NamedTuple
from ccanvas import Reporter
from ccanvas import SubmissionStatus
import markdown
import logging

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

class AssignmentStatusString:
    def __init__(self, a):
        self.course = a.course
        self.name = a.name[0:25]
        self.status = a.status.name
        self.due = mm_dd(a.due_date)
        self.submitted = mm_dd(a.submission_date)
        self.graded = mm_dd(a.graded_date)
        self.score = int(a.possible_gain)
        self.attempts = a.attempts


class AssignmentTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    due = Col('Due')
    score = Col('Gain')

class AssignmentStatusTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    status = Col('Status')

class AssignmentScoreTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    due = Col(' Due ')
    submitted = Col(' Done ')
    graded = Col('Graded')
    attempts = Col('Try')
    score = Col('Gain')

class CourseTable(Table):
    course = Col('Course')
    score = Col('Score')

class AnnouncementTable(Table):
    due = Col('Date')
    course = Col('Course')

def to_string_table(assignments, layout):
    table=[]
    if (layout in [AssignmentScoreTable, AssignmentStatusTable, AssignmentTable]):
        entry_type = AssignmentStatusString
    else:
        entry_type = CourseStatusString
    for a in assignments:
        table.append(entry_type(a))
    return layout(table)

def run_assignment_report(reporter, query):
    table = AssignmentTable
    report = reporter.run_assignment_report(query)
    print(len(report))
    if query == SubmissionStatus.Low_Score:
        table = AssignmentScoreTable
        #report = report[0:12]
    return to_string_table(report, table)

app = Flask(__name__)
with open('config.json') as json_file:
    config = json.load(json_file)

def get_reporter(student):
    student = student.lower()
    api_key = config[student]['key']
    user_id = config[student]['id']
    log_level=logging.getLevelName('ERROR')
    return Reporter(api_key, user_id, None, log_level)

@app.route("/")
def home():
    return render_template('index.html', students = config.keys())

@app.route("/reports", methods=['GET', 'POST'])
def select_report():
    global reporter, student
    student = request.args.get('student').lower()
    api_key = config[student]['key']
    user_id = config[student]['id']
    reporter = Reporter(api_key, user_id)
    return render_template('reports.html')

@app.route("/all")
def all():
    student = request.args.get('student')
    reporter = get_reporter(student)
    reporter.load_assignments()
    scores = to_string_table(reporter.get_course_scores(), CourseTable)
    date = datetime.today().astimezone(pytz.timezone('US/Pacific')).strftime("%m/%d/%y %I:%M %p")
    today = to_string_table(reporter.run_daily_submission_report(datetime.today()), AssignmentStatusTable)
    week = to_string_table(reporter.run_calendar_report(datetime.today()), AssignmentTable)
    missing = run_assignment_report(reporter, SubmissionStatus.Missing)
    missing.no_items = "No missing assignments - nice work!"
    #late = run_assignment_report(reporter, SubmissionStatus.Late)
    #late.no_items = "Everything has been marked!"
    low_score = run_assignment_report(reporter, SubmissionStatus.Low_Score)
    return render_template('all.html', student=student.capitalize(), date=date, scores=scores, today=today, week=week, missing=missing, low_score=low_score)

@app.route("/scores")
def scores():
    print(request.form)
    scores = to_string_table(reporter.get_course_scores(), CourseTable)
    return render_template('scores.html', scores=scores)

@app.route("/today")
def today():
    today = to_string_table(reporter.run_daily_submission_report(datetime.today()), AssignmentStatusTable)
    return render_template('today.html', today=today)

@app.route("/announcements")
def announcements():
    announcements = to_string_table(reporter.get_announcements(), AssignmentStatusTable)
    return render_template('announcements.html', announcements=announcements)

@app.route("/attention")
def attention():
    reporter.reset()
    missing = run_assignment_report(SubmissionStatus.Missing)
    missing.no_items = "No missing assignments - nice work!"
    late = run_assignment_report(SubmissionStatus.Late)
    late.no_items = "Everything has been marked!"
    low_score = run_assignment_report(SubmissionStatus.Low_Score)
    return render_template('attention.html', missing=missing, late=late, low_score=low_score)

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
