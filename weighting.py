from dataclasses import dataclass
from datetime import datetime
import logging
import pytz

@dataclass
class AssignmentWeighting:
    course: str
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
        self.courses = courses
        self.logger = logging.getLogger(__name__)
        self.logger.info("Weighting init")
        for course in courses.values():
            if course.is_valid:
                assignment_group = []
                groups = course.assignment_groups()
                for g in groups:
                    w = g.group_weight
                    if w == 0:
                        w = 100
                    if w == 100:
                        unweighted = True
                    self.assignment_weightings[g.id] = AssignmentWeighting(course.name, g.name, w, 0, 0)
                    assignment_group.append(g.id)
                    self.logger.info("{}({}) {} {} {}%".format(course.name, course.id, g.name, g.id, w))
                self.assignment_groups[course.id] = assignment_group

    # Re-calculate weightings in case some some weights are not yet in use
    def update(self, assignments, end_date):
        for gid in self.assignment_weightings:
            self.assignment_weightings[gid].score = 0
            self.assignment_weightings[gid].max_score = 0
        course_groups = {}

        self.logger.info("Weighting first pass")
        for id, assignment in assignments.items():
            course_id = assignment.course_id
            group_id = assignment.get_group()
            valid_group = group_id in self.assignment_groups[assignment.course_id]
            self.logger.info(" {}[{}] = {} ({})".format(assignment.get_course_name(), group_id, assignment.get_name(), id))
            self.logger.info(" - Checking assignment")
            self.logger.info("   - valid assignment: {}".format(assignment.is_valid))
            self.logger.info("   - valid group: {}".format(valid_group))
            self.logger.info("   - graded: {}".format(assignment.is_graded()))
            self.logger.info("   - score: {}".format(assignment.get_score()))
            if valid_group:
                if not course_id in course_groups:
                    course_groups[course_id] = []
                course_group = course_groups[course_id]
                if group_id not in course_group:
                    course_group.append(group_id)
                if assignment.is_graded():
                    self.assignment_weightings[group_id].max_score += assignment.get_points_possible()
                    self.assignment_weightings[group_id].score += assignment.get_raw_score()
                    self.logger.info("   - group score: {}/{}".format(self.assignment_weightings[group_id].score, self.assignment_weightings[group_id].max_score))

        self.logger.info("Weighting second pass")
        for course_id in course_groups:
            groups = course_groups[course_id]
            self.logger.info("course_groups[{}] = {}".format(course_id, groups))
            if len(groups) == 1:
                self.assignment_weightings[groups[0]].weighting = 100
            total_weighting = 0
            total_score = 0
            for gid in groups:
                self.logger.info("- {} {}".format(self.assignment_weightings[gid].course, self.assignment_weightings[gid].name))
                self.logger.info("   - score: {}".format(self.assignment_weightings[gid].score))
                self.logger.info("   - max score: {}".format(self.assignment_weightings[gid].max_score))
                self.logger.info("   - weighting: {}".format(self.assignment_weightings[gid].weighting))
                total_weighting += self.assignment_weightings[gid].weighting
                if self.assignment_weightings[gid].max_score > 0:
                    total_score +=  self.assignment_weightings[gid].weighting * 100 * self.assignment_weightings[gid].score / self.assignment_weightings[gid].max_score
            self.weighting_totals[course_id] = total_weighting
            self.score_totals[course_id] = total_score

    def includes_assignment(self, assignment):
        group_id = assignment.get_group()
        return group_id in self.assignment_weightings

    def gain(self, assignment):
        possible_gain = 0
        gid = assignment.group
        if gid in self.assignment_weightings:
            if self.assignment_weightings[gid].weighting == 100:
                possible_gain = self.unweighted_gain(assignment)
            else:
                possible_gain = self.weighted_gain(assignment)
        else:
            self.logger.warn("Assignment group not known {}[{}] = {}".format(assignment.get_course_name(), gid, assignment.get_name()))
        self.logger.info("   - possible gain: {}".format(possible_gain))
        return possible_gain

    def unweighted_gain(self, assignment):
        max_score = 0
        self.logger.info(" - Calculating unweighted gain: {}".format(assignment.get_name()))
        groups = self.assignment_groups[assignment.course_id]
        for group in groups:
            max_score += self.assignment_weightings[group].max_score
            self.logger.info(" - {} {}".format(self.assignment_weightings[group].max_score, max_score))
        self.logger.info(" - calculation {}/{}".format(assignment.get_points_dropped(), max_score))
        return round(100*assignment.get_points_dropped()/max_score)

    def weighted_gain(self, assignment):
        gid = assignment.group
        possible_gain = 0
        self.logger.info(" {}[{}] = {}".format(assignment.get_course_name(), gid, assignment.get_name()))
        self.logger.info(" - Calculating weighted gain")
        course_id = assignment.course_id
        score = self.assignment_weightings[gid].score
        max_score = self.assignment_weightings[gid].max_score
        weighting = self.assignment_weightings[gid].weighting
        weighting_total = self.weighting_totals[course_id]
        self.logger.info("   - graded: {}".format(assignment.is_graded()))
        self.logger.info("   - group score: {}".format(score))
        self.logger.info("   - group max score: {}".format(max_score))
        self.logger.info("   - group weighting: {}".format(weighting))
        self.logger.info("   - group weighting total: {}".format(weighting_total))
        self.logger.info("   - assignment points possible: {}".format(assignment.get_points_possible()))
        if assignment.is_graded():
            self.logger.info("   - assignment points dropped: {}".format(assignment.get_points_dropped()))
            dropped = (100 * assignment.get_points_dropped()) / max_score
            possible_gain = weighting * dropped / weighting_total
        elif max_score > 0:
            current_pct = (100 * (score)) / (max_score)
            new_pct = (100 * (score + assignment.get_points_possible())) / (max_score + assignment.get_points_possible())
            possible_gain = ((new_pct - current_pct) * weighting) / weighting_total
        else:
            self.logger.info("   - assignment group has no entries")
            current_score = self.score_totals[course_id]/weighting_total
            weighting_total = weighting_total + weighting
            new_score = (self.score_totals[course_id] + weighting * 100) / weighting_total
            possible_gain = new_score - current_score
        return round(possible_gain)
