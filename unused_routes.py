@app.route("/reports", methods=['GET', 'POST'])
def select_report():
    global reporter, student
    student = request.args.get('student').lower()
    api_key = config[student]['key']
    user_id = config[student]['id']
    reporter = Reporter(api_key, user_id)
    return render_template('reports.html')


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
