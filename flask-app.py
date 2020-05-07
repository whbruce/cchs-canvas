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


class AssignmentStatusString:
    def __init__(self, a):
        self.course = a.course
        self.name = a.name
        self.status = a.status.name
        self.date = mm_dd(a.due_date)

class AssigmentTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    date = Col('Due Date')

class AssigmentStatusTable(Table):
    course = Col('Course')
    name = Col('Assignment')
    status = Col('Status')

def to_string_table(assignments, clazz):
    table=[]
    for a in assignments:
        table.append(AssignmentStatusString(a))
    return clazz(table)

app = Flask(__name__)

@app.route("/")
def home():
#    reporter = Reporter()
#    scores = ScoreTable(reporter.get_course_scores())
#    today = to_string_table(reporter.run_daily_submission_report(datetime.today()), AssigmentStatusTable)
#    missing = to_string_table(reporter.run_assignment_report(SubmissionStatus.Missing), AssigmentTable)
#    late = to_string_table(reporter.run_assignment_report(SubmissionStatus.Late), AssigmentTable)    
#    return render_template('index.html', scores=scores, today=today, missing=missing, late=late)
    return render_template('index.html')

@app.route("/today")
def today():
    reporter = Reporter()
#    scores = ScoreTable(reporter.get_course_scores())
    today = to_string_table(reporter.run_daily_submission_report(datetime.today()), AssigmentStatusTable)
 #   missing = to_string_table(reporter.run_assignment_report(SubmissionStatus.Missing), AssigmentTable)
 #   late = to_string_table(reporter.run_assignment_report(SubmissionStatus.Late), AssigmentTable)    
    return render_template('today.html', today=today)

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
