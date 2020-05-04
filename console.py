import argparse
from datetime import datetime
from ccanvas import Reporter
from ccanvas import SubmissionStatus

parser = argparse.ArgumentParser(description='Query Canvas')
parser.add_argument('--date', type=datetime.fromisoformat, default=datetime.today(), help='date in ISO format')
parser.add_argument('--all', action="store_true", help='check for missing assignments')
parser.add_argument('--md', action="store_true", help='output in Markdown')
parser.add_argument('--csv', action="store_true", help='output in CSV')
args = parser.parse_args()
reporter = Reporter()
if args.all:
    status_list = reporter.run_assignment_report(SubmissionStatus.Missing)
    print("==== Missing assignments ====")
    for status in status_list:
        state = status.status.name + " (%d%%)" % (status.score) if status.status == SubmissionStatus.Low_Score else status.status.name
        print("%-8s: %-20.20s %s [%s]" % (status.course, status.name, status.due_date.strftime("%m/%d"), state))
    print("==== Late assignments waiting to be marked ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Late)
    for status in status_list:
        state = status.status.name + " (%d%%)" % (status.score) if status.status == SubmissionStatus.Low_Score else status.status.name
        print("%-8s: %-20.20s %s [%s]" % (status.course, status.name, status.due_date.strftime("%m/%d"), state))
    print("==== Assignments with low score ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Low_Score)
    for status in status_list:
        state = status.status.name + " (%d%%)" % (status.score) if status.status == SubmissionStatus.Low_Score else status.status.name
        print("%-8s: %-20.20s %s [%s]" % (status.course, status.name, status.due_date.strftime("%m/%d"), state))
else:
    print("Checking assignments for", args.date.strftime("%m/%d"))
    status_list = reporter.run_daily_submission_report(args.date)
    for status in status_list:
        state = status.status.name + " (%d%%)" % (status.score) if status.status == SubmissionStatus.Marked else status.status.name
        print("%-8s: %-20.20s [%s]" % (status.course, status.name, state))        
