import logging
import utils
from assignment import Assignment

graded_courses = ["History", "Spanish", "Chemistry", "Algebra", "Geometry", "Geo/Trig", "English", "Theology", "Biology", "Physics", "Computer",
                  "Government", "Financing", "Ceramics", "Wellness", "PE", "Support" ]

class Course:
    def __init__(self, course):
        self.raw = course
        self.is_valid = False
        self.id = self.raw.id
        self.is_honors = "Honors" in self.raw.name or "AP" in self.raw.name
        self.logger = logging.getLogger(__name__)
        self.term = self.raw.term["name"].split(' ')[0]
        name = course if isinstance(course, str) else course.name
        for short_name in graded_courses:
            if short_name in name:
                self.name = short_name
                self.is_valid = True
        if "Service" in name:
            self.name = "Service"

    def is_current(self, date):
        return utils.convert_date(self.raw.term["end_at"]) > date

    def get_assignments(self, user, get_invalid=False):
        assignments = {}
        if self.is_valid or get_invalid:
            self.logger.info("Loading {} assignments".format(self.name))
            raw_assignments = self.raw.get_assignments(order_by="due_at", include=["submission"])
            for a in raw_assignments:
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
