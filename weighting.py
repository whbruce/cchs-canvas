from dataclasses import dataclass
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
        self.logger = logging.getLogger(__name__)
        for _, course in courses.items():
            if course.is_valid:
                assignment_group = []
                groups = course.assignment_groups()
                for g in groups:
                    w = g.group_weight
                    self.assignment_weightings[g.id] = AssignmentWeighting(course.name, g.name, w, 0, 0)
                    assignment_group.append(g.id)
                    self.logger.info("{}({}) {} {}%".format(course.name, g.name, g.id, w))
                self.assignment_groups[course.id] = assignment_group

    # Re-calculate weightings in case some some weights are not yet in use
    def update(self, assignments, end_date):
        for gid in self.assignment_weightings:
            self.assignment_weightings[gid].score = 0
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
                total_score +=  self.assignment_weightings[gid].weighting * 100 * self.assignment_weightings[gid].score / self.assignment_weightings[gid].max_score
            self.weighting_totals[course_id] = total_weighting
            self.score_totals[course_id] = total_score

    def includes_assignment(self, assignment):
        group_id = assignment.get_group()
        return group_id in self.assignment_weightings

    def gain(self, assignment):
        gid = assignment.group
        possible_gain = 0
        if gid in self.assignment_weightings:
                course_id = assignment.course_id
                score = self.assignment_weightings[gid].score
                max_score = self.assignment_weightings[gid].max_score
                weighting = self.assignment_weightings[gid].weighting
                weighting_total = self.weighting_totals[course_id]
                self.logger.info(" {}[{}] = {}".format(assignment.get_course_name(), gid, assignment.get_name()))
                self.logger.info(" - Calculating gain")
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
                    return int(possible_gain + 0.5)
                elif max_score > 0:
                    current_pct = (100 * (score)) / (max_score)
                    new_pct = (100 * (score + assignment.get_points_possible())) / (max_score + assignment.get_points_possible())
                    possible_gain = ((new_pct - current_pct) * weighting) / weighting_total
        return int(possible_gain + 0.5)

