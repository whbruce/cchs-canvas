import json
from flask import Flask, request
from flask import render_template
from flask_table import Table, Col, LinkCol
from datetime import datetime
import pytz
from typing import NamedTuple
from ccanvas import Reporter, Assignment, AssignmentStatus, SubmissionStatus
import markdown
import logging

class ReporterFactory(object):
    instances = {}
    current_student = None

    @staticmethod
    def create(student):
        if not student in ReporterFactory.instances:
            with open('config.json') as json_file:
                config = json.load(json_file)
            student = student.lower()
            api_key = config[student]['key']
            user_id = config[student]['id']
            log_level=logging.getLevelName('ERROR')
            ReporterFactory.current_student = student
            ReporterFactory.instances[student] = Reporter(api_key, user_id, None, log_level)
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
        self.points = int(100*c.points)/100

class AssignmentStatusString:
    def __init__(self, a):
        self.course_id = a.course_id
        self.course = a.course
        self.id = a.id
        self.name = a.name[0:25]
        self.status = a.status.name
        self.due = mm_dd(a.due_date)
        self.submitted = mm_dd(a.submission_date)
        self.graded = mm_dd(a.graded_date)
        self.score = int(a.possible_gain)
        self.attempts = a.attempts

class CommentStatusString:
    def __init__(self, c):
        self.author = c.author
        self.date = mm_dd(c.date)
        self.text = c.text

class AssignmentTable(Table):
    course = Col('Course')
    #name = Col('Assignment')
    name = LinkCol('Name', 'single_item',
                   url_kwargs=dict(course_id='course_id', assignment_id='id'), attr='name')
    due = Col('Due')
    score = Col('Gain')

class AssignmentStatusTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    status = Col('Status')

class AssignmentScoreTable(Table):
    course = Col('Course')
    #name = Col('Assignment')
    name = LinkCol('Name', 'single_item',
                   url_kwargs=dict(course_id='course_id', assignment_id='id'), attr='name')
    due = Col(' Due ')
    submitted = Col(' Done ')
    graded = Col('Graded')
    attempts = Col('Try')
    score = Col('Gain')

class CourseTable(Table):
    course = Col('Course')
    score = Col('Score')
    points = Col('GPA')

class AnnouncementTable(Table):
    due = Col('Date')
    course = Col('Course')

class CommentTable(Table):
    author = Col('Author')
    date = Col('Date')
    text = Col('Comment')

def to_string_table(assignments, layout):
    table=[]
    if (layout in [AssignmentScoreTable, AssignmentStatusTable, AssignmentTable]):
        entry_type = AssignmentStatusString
    elif layout == CourseTable:
        entry_type = CourseStatusString
    else:
        entry_type = CommentStatusString
    for a in assignments:
        table.append(entry_type(a))
    return layout(table)

def run_assignment_report(reporter, query, min_score):
    table = AssignmentTable
    report = reporter.run_assignment_report(query, min_score)
    return to_string_table(report, table), len(report)

app = Flask(__name__)

@app.route("/")
def home():
    with open('config.json') as json_file:
        config = json.load(json_file)
    return render_template('index.html', students = config.keys())

@app.route('/assignment/<int:course_id>/<int:assignment_id>')
def single_item(course_id, assignment_id):
    reporter = ReporterFactory.get()
    assignment = reporter.get_assignment(course_id, assignment_id)
    comments = to_string_table(assignment.submission_comments, CommentTable)
    comments.no_items = "No comments"
    return render_template('assignment.html', assignment = AssignmentStatus(assignment), comments = comments)

@app.route("/all")
def all():
    student = request.args.get('student')
    reporter = ReporterFactory.create(student)
    reporter.load_assignments()
    summary = {}
    scores_list = reporter.get_course_scores()
    scores = to_string_table(scores_list, CourseTable)
    date = datetime.today().astimezone(pytz.timezone('US/Pacific')).strftime("%m/%d/%y %I:%M %p")
    today_list = reporter.run_daily_submission_report(datetime.today())
    today = to_string_table(today_list, AssignmentStatusTable)
    week = to_string_table(reporter.run_calendar_report(datetime.today()), AssignmentTable)
    todo = 0
    for assignment in today_list:
        if assignment.status == SubmissionStatus.Not_Submitted:
            todo+=1
    summary["todo"] = todo
    missing, summary["missing"] = run_assignment_report(reporter, SubmissionStatus.Missing, 1)
    missing.no_items = "No missing assignments - nice work!"
    low_score, summary["low"] = run_assignment_report(reporter, SubmissionStatus.Low_Score, 2)
    being_marked, summary["being_marked"] = run_assignment_report(reporter, SubmissionStatus.Being_Marked, 0)
    summary["gpa"] = scores_list[len(scores_list)-1].points
    #late = run_assignment_report(reporter, SubmissionStatus.Late)
    #late.no_items = "Everything has been marked!"
    return render_template('all.html', student=student.capitalize(), date=date, summary=summary, scores=scores, today=today, week=week, missing=missing, low_score=low_score, being_marked=being_marked)



if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
