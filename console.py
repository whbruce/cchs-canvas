import argparse
from datetime import datetime
from ccanvas import Reporter
from ccanvas import SubmissionStatus

def mm_dd(date):
    if (date):
        return date.strftime("%m/%d")    
    else:
        return "??/??"

parser = argparse.ArgumentParser(description='Query Canvas')
parser.add_argument('--date', type=datetime.fromisoformat, default=datetime.today(), help='date in ISO format')
parser.add_argument('--all', action="store_true", help='check for missing assignments')
parser.add_argument('--md', action="store_true", help='output in Markdown')
parser.add_argument('--csv', action="store_true", help='output in CSV')
args = parser.parse_args()
reporter = Reporter()
print("=== Assignments due on %s ====" % (mm_dd(args.date)))
status_list = reporter.run_daily_submission_report(args.date)
for status in status_list:
    state = status.status.name + " (%d%%)" % (status.score) if status.status == SubmissionStatus.Marked else status.status.name
    print("%-8s: %-20.20s [%s]" % (status.course, status.name, state))        
print("\n==== Grades ====")
scores = reporter.get_course_scores()
for score in scores:
    print("%-8s: %d" % (score.course, score.score))
status_list = reporter.run_assignment_report(SubmissionStatus.Missing)
print("\n==== Missing assignments ====")
for status in status_list:
    print("%-8s: %-20.20s %s" % (status.course, status.name, mm_dd(status.due_date)))
print("\n==== Assignments with low score ====")
status_list = reporter.run_assignment_report(SubmissionStatus.Low_Score)
for status in status_list:
    print("%-8s: %-20.20s %s [%d%%]" % (status.course, status.name, mm_dd(status.due_date), status.score))
print("\n==== Late assignments waiting to be marked ====")
status_list = reporter.run_assignment_report(SubmissionStatus.Late)
for status in status_list:
    print("%-8s: %-20.20s %s %s" % (status.course, status.name, mm_dd(status.due_date), mm_dd(status.submission_date)))

