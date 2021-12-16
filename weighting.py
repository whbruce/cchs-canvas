import logging
from typing import NamedTuple
import pytz

class CourseGroup(NamedTuple):
    course_id: int


class WeightedScoreCalculator:

    def __init__(self, courses):
        self.group_max = {}
        self.weightings = {}
        self.assignment_groups = {}
        self.equal_weighted_courses = []
        self.logger = logging.getLogger(__name__)
        for _, course in courses.items():
            if course.is_valid:
                assignment_group = []
                groups = course.assignment_groups()
                for g in groups:
                    w = g.group_weight
                    if w == 0:
                        w = 100
                        self.equal_weighted_courses.append(course.id)
                    self.weightings[g.id] = w
                    assignment_group.append(g.id)
                    # print("%s %s %s %d" % (self.course_short_name(c.name), g.name, g.id, w))
                self.assignment_groups[course.id] = assignment_group
        for w in self.weightings:
            self.group_max[w] = 0


    # Re-calculate weightings in case some some weights are not yet in use
    def update(self, assignments, end_date):
        for w in self.weightings:
            self.group_max[w] = 0
        course_groups = {}

        self.logger.info("Weighting first pass")
        for id, assignment in assignments.items():
            if assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date:
                group_id = assignment.get_group()
                self.logger.info(" {}[{}] = {} ({})".format(assignment.get_course_name(), group_id, assignment.get_name(), id))
                self.logger.info(" - Checking assignment")
                self.logger.info("   - valid assignment: {}".format(assignment.is_valid))
                self.logger.info("   - valid group: {}".format(group_id in self.group_max))
                self.logger.info("   - graded: {}".format(assignment.is_graded()))
                self.logger.info("   - score: {}".format(assignment.get_score()))
                if assignment.is_graded() and (group_id in self.group_max):
                    course_id = assignment.course_id
                    if not course_id in course_groups:
                        course_groups[course_id] = []
                    course_group = course_groups[course_id]
                    if group_id not in course_group:
                        course_group.append(group_id)
                    self.group_max[group_id] = self.group_max[group_id] + assignment.get_points_possible()

        self.logger.info("Weighting second pass")
        for course_id in course_groups:
            group = course_groups[course_id]
            # print("{} {}".format(course_id, group))
            if len(group) == 1:
                for w in self.assignment_groups.get(course_id):
                    self.weightings[w] = 100
                if course_id not in self.equal_weighted_courses:
                    self.equal_weighted_courses.append(course_id)
            if course_id in self.equal_weighted_courses:
                points = 0
                for i in self.assignment_groups.get(course_id):
                    points = points + self.group_max[i]
                for i in self.assignment_groups.get(course_id):
                    self.group_max[i] = points

    def includes_assignment(self, assignment):
        group_id = assignment.get_group()
        return group_id in self.group_max

    def missing_gain(self, assignment):
        self.logger.info("Gain: {} [{}] {} {} {}".format(assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.weightings[assignment.group], self.group_max[assignment.group]))
        possible_gain = 0
        if self.group_max[assignment.group] + assignment.get_points_possible() > 0:
            possible_gain = int((self.weightings[assignment.group] * assignment.get_points_dropped()) / (self.group_max[assignment.group] + assignment.get_points_possible()))
        return possible_gain

    def marked_gain(self, assignment):
        possible_gain = int((self.weightings[assignment.group] * assignment.get_points_dropped()) / self.group_max[assignment.group])
        return possible_gain

