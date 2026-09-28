"""Small, explainable hybrid Expectimax/Minimax decision layer."""

from __future__ import annotations

from dataclasses import dataclass

from .belief import BeliefState
from .map_graph import CityGraph


@dataclass(frozen=True)
class Decision:
    target: int
    score: float
    depth: int
    evaluated_states: int
    pruned_branches: int
    candidates: list[tuple[int, float]]


class HunterAI:
    """Selects a target zone, then leaves concrete movement to A*."""

    def __init__(self, graph: CityGraph, search_depth: int = 2) -> None:
        self.graph = graph
        self.search_depth = search_depth
        self.evaluated_states = 0
        self.pruned_branches = 0

    def choose_target(self, hunter_node: int, belief: BeliefState) -> Decision:
        """Evaluate likely zones with weighted chance and hostile responses.

        The outer sum is Expectimax: plausible hidden positions are weighted by
        their belief probability. For each hypothesis, the Ghost picks its most
        evasive adjacent response (Minimax). Alpha-beta bounds prune local
        replies that are already clearly worse than the best target discovered.
        """
        self.evaluated_states = 0
        self.pruned_branches = 0
        hypotheses = belief.top(8)
        candidate_nodes = [node for node, _ in belief.top(7)]
        if hunter_node not in candidate_nodes:
            candidate_nodes.append(hunter_node)

        best_target = candidate_nodes[0]
        best_score = float("-inf")
        alpha = float("-inf")
        scores: list[tuple[int, float]] = []

        for target in candidate_nodes:
            expected_score = 0.0
            total_probability = sum(probability for _, probability in hypotheses)
            for ghost_node, probability in hypotheses:
                response_score = self._ghost_min_value(
                    hunter_node, target, ghost_node, belief, alpha
                )
                expected_score += probability * response_score
            expected_score /= total_probability or 1.0
            scores.append((target, expected_score))
            if expected_score > best_score:
                best_target, best_score = target, expected_score
                alpha = max(alpha, best_score)

        scores.sort(key=lambda item: item[1], reverse=True)
        return Decision(
            target=best_target,
            score=best_score,
            depth=self.search_depth,
            evaluated_states=self.evaluated_states,
            pruned_branches=self.pruned_branches,
            candidates=scores,
        )

    def _ghost_min_value(
        self,
        hunter_node: int,
        target: int,
        ghost_node: int,
        belief: BeliefState,
        alpha: float,
    ) -> float:
        responses = [node for node, _ in self.graph.neighbors(ghost_node)]
        worst_response = float("inf")
        target_travel = self.graph.distance(hunter_node, target)
        for response in responses:
            self.evaluated_states += 1
            separation = self.graph.distance(target, response)
            confidence = belief.probabilities.get(response, 0.0) * 100
            capture_bonus = 70 if target == response else 0
            value = confidence * 1.2 + capture_bonus - separation * 3.8 - target_travel * 1.5
            worst_response = min(worst_response, value)
            # Simplified alpha-beta cutoff: a hostile reply already well below
            # the best root choice cannot improve this target's standing.
            if worst_response < alpha - 18:
                self.pruned_branches += max(0, len(responses) - responses.index(response) - 1)
                break
        return worst_response
