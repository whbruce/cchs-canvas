import sys
import argparse
import json
from datetime import datetime
from ccanvas import Reporter
from ccanvas import SubmissionStatus
import logging

def mm_dd(date):
    if (date):
        return date.strftime("%m/%d")
    else:
        return "??/??"

parser = argparse.ArgumentParser(description='Query Canvas')
parser.add_argument('--student', type=str.lower, required=True, choices={"alex", "nina"}, help='student first name')
parser.add_argument('--date', type=datetime.fromisoformat, default=datetime.today(), help='date in ISO format')
parser.add_argument('--low', action="store_true", help='list assigmnents with low scores')
parser.add_argument('--missing', action="store_true", help='list missing assigmnents')
parser.add_argument('--attention', action="store_true", help='list assigments needing attention')
parser.add_argument('--calendar', action="store_true", help='list forthcoming assignments')
parser.add_argument('--all', action="store_true", help='check for missing assignments')
parser.add_argument('--grades', action="store_true", help='list course scores')
parser.add_argument('--submissions', action="store_true", help='create submission time report')
parser.add_argument('--announcements', action="store_true", help='list announcements')
parser.add_argument('--loglevel', choices={'debug', 'info', 'warning', 'error', 'critical'}, default='error', help="Set the logging level")
args = parser.parse_args()

with open('config.json') as json_file:
    config = json.load(json_file)
api_key = config[args.student]['key']
user_id = config[args.student]['id']

#logger = logging.getLogger('myLogger')
#level = logging.getLevelName('DEBUG')
#logging.setLevel(level)
log_level=logging.getLevelName(args.loglevel.upper())
reporter = Reporter(api_key, user_id, log_level)
reporter.load_assignments()
if (args.announcements):
    print("=== Announcements for %s ====" % (mm_dd(args.date)))
    get_announcements = reporter.get_announcements()
    for a in get_announcements:
        print("%-8.8s: %s" % (a.course, a.title))
    print("\n")
elif args.grades:
    print("\n==== Grades ====")
    scores = reporter.get_course_scores()
    for score in scores:
        print("%-10s: %3d" % (score.course, score.score))
elif args.low:
    print("\n==== Assignments with low score ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Low_Score)
    for status in status_list:
        print("%-10s: %-25.25s %s %s %d [%d%%]" % (status.course, status.name, mm_dd(status.due_date), mm_dd(status.submission_date), status.attempts, status.possible_gain))
elif args.missing:
    print("\n==== Missing assignments ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Missing)
    for status in status_list:
        print("%-8s: %-25.25s %s" % (status.course, status.name, mm_dd(status.due_date)))
elif args.attention:
    print("\n==== Missing assignments ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Missing)
    for status in status_list:
        print("%-8s: %-25.25s %s" % (status.course, status.name, mm_dd(status.due_date)))
    print("\n==== Assignments with low score ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Low_Score)
    for status in status_list[0:15]:
        print("%-8s: %-25.25s %s [%d]" % (status.course, status.name, mm_dd(status.due_date), status.possible_gain))
    print("\n==== Late assignments waiting to be marked ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Late)
    for status in status_list:
        print("%-8s: %-25.25s %s %s" % (status.course, status.name, mm_dd(status.due_date), mm_dd(status.submission_date)))
elif args.calendar:
    status_list = reporter.run_calendar_report(datetime.today())
    for status in status_list:
        print("%-9s: %-25.25s %s %d" % (status.course, status.name, mm_dd(status.due_date), status.possible_gain))
elif args.submissions:
    reporter.run_submission_report()
elif args.all:
    print("\n=== To-day ====")
    status_list = reporter.run_daily_submission_report(args.date)
    for status in status_list:
        state = status.status.name + " (%d%%)" % (status.score) if status.status == SubmissionStatus.Marked else status.status.name
        print("%-8s: %-25.25s [%s]" % (status.course, status.name, state))
    print("\n=== This week ====")
    status_list = reporter.run_calendar_report(args.date)
    for status in status_list:
        print("%-9s: %-25.25s %s %d" % (status.course, status.name, mm_dd(status.due_date), status.possible_gain))
    print("\n==== Missing assignments ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Missing)
    for status in status_list:
        print("%-8s: %-25.25s %s" % (status.course, status.name, mm_dd(status.due_date)))
    print("\n==== Assignments with low score ====")
    status_list = reporter.run_assignment_report(SubmissionStatus.Low_Score)
    for status in status_list[0:15]:
        print("%-8s: %-25.25s %s [%d]" % (status.course, status.name, mm_dd(status.due_date), status.possible_gain))
    print("\n==== Grades ====")
    scores = reporter.get_course_scores()
    for score in scores:
        print("%-10s: %3d" % (score.course, score.score))
else:
    print("\n=== Assignments due on %s ====" % (mm_dd(args.date)))
    status_list = reporter.run_daily_submission_report(args.date)
    for status in status_list:
        state = status.status.name + " (%d%%)" % (status.score) if status.status == SubmissionStatus.Marked else status.status.name
        print("%-8s: %-25.25s [%s]" % (status.course, status.name, state))

