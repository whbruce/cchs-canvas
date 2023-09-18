import logging
import utils
from types import SimpleNamespace
from typing import NamedTuple
from assignment import Assignment

graded_courses = ["History", "Spanish", "Chemistry", "Algebra", "Geometry", "Geo/Trig", "Calculus", "English", "Theology", "Biology", "Physics", "Computer",
                  "Government", "Financing", "Law", "Politics", "Ceramics", "Wellness", "PE", "Support", "Advising", "Photography", "Statistics", "STEM",
                  "CINE 260M", "CS 111", "EC 201", "MATH 111",
                  "J 100", "J 350", "MUS 151", "MUS 227",
                  "PPPM 101", "GEOG 208", "LING 201" ]

class CourseScore(NamedTuple):
    course: str
    score: int
    wpoints: float
    upoints: float

class Course:
    def __init__(self, course, enrollment):
        self.raw = course
        self.enrollment=enrollment
        self.is_valid = False
        self.id = self.raw.id
        self.is_honors = "Honors" in self.raw.name or "AP" in self.raw.name
        self.logger = logging.getLogger(__name__)
        self.term = self.raw.term["name"].split(' ')[0]
        self.has_grade = not self.raw.hide_final_grades
        name = course if isinstance(course, str) else course.name
        for short_name in graded_courses:
            if short_name in name:
                self.name = short_name
                self.is_valid = True
        if "Service" in name:
            self.name = "Service"

    def is_current(self, date):
        if self.raw.term["end_at"]:
            return utils.convert_date(self.raw.term["end_at"]) > date
        else:
            return False

    def get_grade_points(self, score):
        table  = [
            (97, 4.30, 4),
            (93, 4.00, 4),
            (90, 3.70, 4),
            (87, 3.30, 3),
            (83, 3.00, 3),
            (80, 2.70, 3),
            (77, 2.30, 2),
            (73, 2.00, 2),
            (70, 1.70, 2),
            (67, 1.30, 1),
            (63, 1.00, 1),
            (60, 0.70, 1),
            (0,  0.0, 0)
        ]
        for entry in table:
            if score >= entry[0]:
                return SimpleNamespace(weighted = entry[1] + (0.5 * self.is_honors), unweighted = entry[2])

    def get_score(self, calculator):
        score=None
        if self.is_valid:
            if self.has_grade:
                score = self.enrollment.grades.get('current_score')
            else:
                score=calculator.score_totals[self.id]/calculator.weighting_totals[self.id]
            if score is not None:
                score = int(score + 0.5)
                grade_points = self.get_grade_points(score)
                name = self.name
                if self.has_grade:
                    name += " *"
                return CourseScore(self.name, score, grade_points.weighted, grade_points.unweighted)
        return score

    def get_assignments(self, user, get_invalid=False):
        assignments = {}
        if self.is_valid or get_invalid:
            raw_assignments = self.raw.get_assignments(order_by="due_at")
            assignment_ids = []
            for a in raw_assignments:
                assignment_ids.append(a.id)
            raw_submissions = self.raw.get_multiple_submissions(assignment_ids=assignment_ids, student_ids=[user.id], include=["submission_comments"])
            submissions = {}
            for s in raw_submissions:
                submissions[s.assignment_id] = s
            for a in raw_assignments:
                submission = submissions[a.id]
                if not hasattr(submission, "score"):
                    setattr(submission, "score", None)
                if not hasattr(submission, "attempt"):
                    setattr(submission, "attempt", 0)
                a.submission = submission
                assignment = Assignment(user, self.name, a)
                self.logger.info("   - name: {}".format(assignment.get_name()))
                self.logger.info("   - last updated: {}".format(a.updated_at))
                self.logger.info("   - submitted: {}".format(assignment.get_submission_date()))
                if assignment.is_valid or get_invalid:
                    assignments[a.id] = assignment
        return assignments


    def assignment_groups(self):
        groups = self.raw.get_assignment_groups()
        filtered_groups = []
        for group in groups:
            valid = True
            for name in ["Attendance", "Imported Assignments", "Extra"]:
                if name in group.name:
                    valid = False
                    break
            if valid:
                filtered_groups.append(group)
        return filtered_groups

    def assignment_group(self, id):
        groups = self.raw.get_assignment_groups()
        for group in groups:
            if group.id == id:
                return group
        return None
