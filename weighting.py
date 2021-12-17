from dataclasses import dataclass
import logging
import pytz

@dataclass
class AssignmentWeighting:
    name: str
    weighting: int
    max_score: int
    score: int


class WeightedScoreCalculator:

    def __init__(self, courses):
        self.assignment_weightings = {}
        self.assignment_groups = {}
        self.weighting_totals = {}
        self.score_totals = {}
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
                        if course.id not in self.equal_weighted_courses:
                            self.equal_weighted_courses.append(course.id)
                    self.assignment_weightings[g.id] = AssignmentWeighting(g.name, w, 0, 0)
                    assignment_group.append(g.id)
                    # print("%s %s %s %d" % (self.course_short_name(c.name), g.name, g.id, w))
                self.assignment_groups[course.id] = assignment_group

    # Re-calculate weightings in case some some weights are not yet in use
    def update(self, assignments, end_date):
        for gid in self.assignment_weightings:
            print
            self.assignment_weightings[gid].max_score = 0
        course_groups = {}

        self.logger.info("Weighting first pass")
        for id, assignment in assignments.items():
            if assignment.get_due_date().astimezone(pytz.timezone('US/Pacific')) < end_date:
                group_id = assignment.get_group()
                self.logger.info(" {}[{}] = {} ({})".format(assignment.get_course_name(), group_id, assignment.get_name(), id))
                self.logger.info(" - Checking assignment")
                self.logger.info("   - valid assignment: {}".format(assignment.is_valid))
                self.logger.info("   - valid group: {}".format(group_id in self.assignment_groups[assignment.course_id]))
                self.logger.info("   - graded: {}".format(assignment.is_graded()))
                self.logger.info("   - score: {}".format(assignment.get_score()))
                if assignment.is_graded() and (group_id in self.assignment_weightings):
                    course_id = assignment.course_id
                    if not course_id in course_groups:
                        course_groups[course_id] = []
                    course_group = course_groups[course_id]
                    if group_id not in course_group:
                        course_group.append(group_id)
                    self.assignment_weightings[group_id].max_score += assignment.get_points_possible()
                    self.assignment_weightings[group_id].score += assignment.get_raw_score()

        self.logger.info("Weighting second pass")
        for course_id in course_groups:
            groups = course_groups[course_id]
            # print("{} {}".format(course_id, groups))
            if len(groups) == 1:
                for gid in self.assignment_groups.get(course_id):
                    self.assignment_weightings[gid].weighting = 100
                if course_id not in self.equal_weighted_courses:
                    self.equal_weighted_courses.append(course_id)
            if course_id in self.equal_weighted_courses:
                points = 0
                for gid in self.assignment_groups.get(course_id):
                    points = points + self.assignment_weightings[gid].max_score
                for gid in self.assignment_groups.get(course_id):
                    self.assignment_weightings[gid].max_score = points
            total_weighting = 0
            total_score = 0
            for gid in groups:
                total_weighting += self.assignment_weightings[gid].weighting
                total_score +=  self.assignment_weightings[gid].weighting * 100 * self.assignment_weightings[gid].score / self.assignment_weightings[gid].max_score
            self.weighting_totals[course_id] = total_weighting
            self.score_totals[course_id] = total_score

    def includes_assignment(self, assignment):
        group_id = assignment.get_group()
        return group_id in self.assignment_weightings

    def missing_gain(self, assignment):
        self.logger.info("Gain: {} [{}] {} {} {}".format(assignment.course_name, assignment.get_name(), assignment.get_points_dropped(), self.assignment_weightings[assignment.group].weighting, self.assignment_weightings[assignment.group].max_score))
        possible_gain = 0
        gid = assignment.group
        if self.assignment_weightings[gid].max_score + assignment.get_points_possible() > 0:
            possible_gain = self.marked_gain(assignment)
            #possible_gain = int((self.assignment_weightings[gid].weighting * assignment.get_points_dropped()) / (self.assignment_weightings[gid].max_score + assignment.get_points_possible()))
        return possible_gain

    def marked_gain(self, assignment):
        gid = assignment.group
        course_id = assignment.course_id
        max_score = self.assignment_weightings[gid].max_score
        weighting = self.assignment_weightings[gid].weighting
        weighting_total = self.weighting_totals[course_id]
        dropped = (100 * assignment.get_points_dropped()) / max_score
        possible_gain = int(weighting * dropped / weighting_total + 0.5)
        return possible_gain

