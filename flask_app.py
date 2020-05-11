from flask import Flask
from flask import render_template
from flask_table import Table, Col
from datetime import datetime
from typing import NamedTuple
from ccanvas import Reporter
from ccanvas import SubmissionStatus

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
        self.date = mm_dd(a.due_date)
        self.score = str(int(a.score + 0.5)) + "%"

class AssignmentTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    date = Col('Due Date')

class AssignmentStatusTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    status = Col('Status')

class AssignmentScoreTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    score = Col('Score')

class CourseTable(Table):
    course = Col('Course')
    score = Col('Score')

class AnnouncementTable(Table):
    date = Col('Date')
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

def run_assignment_report(query):
    table = AssignmentScoreTable if query == SubmissionStatus.Low_Score  else AssignmentTable
    return to_string_table(reporter.run_assignment_report(query), table)

app = Flask(__name__)
reporter = Reporter()

@app.route("/")
def home():
    return render_template('index.html')

@app.route("/scores")
def scores():
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
    late = run_assignment_report(SubmissionStatus.Late)    
    low_score = run_assignment_report(SubmissionStatus.Low_Score)    
    return render_template('attention.html', missing=missing, late=late, low_score=low_score)

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
