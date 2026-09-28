"""Rules engine for the Shadow Chase turn loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from .adversarial_ai import Decision, HunterAI
from .astar import PathResult, find_path
from .belief import BeliefState, SensorClue, generate_clue, generate_scan_clue
from .map_graph import CityGraph

GHOST_POLICIES = ("REACTIVE", "CUNNING", "CHAOTIC")

GHOST_POLICY_HELP = {
    "REACTIVE": "Always flees along the road farthest from the Hunter.",
    "CUNNING": "Flees far and dodges the Hunter's belief hot-spots.",
    "CHAOTIC": "35% of turns are pure panic; otherwise it flees.",
}

DIFFICULTIES = ("EASY", "NORMAL", "HARD")

# start_distance: allowed road-distance range between the random start nodes.
# sight_chance / sight_seconds: per-round chance of a fleeting real sighting.
# turn_seconds: shot clock for the optional turn timer (T key in the UI).
DIFFICULTY_CONFIG = {
    "EASY": {
        "rounds": 12, "reveals": {3, 6, 9, 12}, "scans": 3,
        "start_distance": (2, 5), "sight_chance": 0.45, "sight_seconds": 1.0,
        "turn_seconds": 30,
    },
    "NORMAL": {
        "rounds": 12, "reveals": {4, 8, 12}, "scans": 2,
        "start_distance": (4, 8), "sight_chance": 0.25, "sight_seconds": 0.7,
        "turn_seconds": 20,
    },
    "HARD": {
        "rounds": 10, "reveals": {5, 10}, "scans": 1,
        "start_distance": (6, 99), "sight_chance": 0.10, "sight_seconds": 0.5,
        "turn_seconds": 15,
    },
}

DIFFICULTY_HELP = {
    "EASY": "Close start • 3 scans • 12 rounds • frequent reveals",
    "NORMAL": "Balanced start • 2 scans • 12 rounds • reveals on 4/8/12",
    "HARD": "Far start • 1 scan • 10 rounds • rare reveals & sightings",
}


@dataclass
class GameState:
    hunter_node: int = 0
    ghost_node: int = 22
    round_number: int = 1
    max_rounds: int = 12
    status: str = "ACTIVE"
    outcome_message: str = "The city is quiet. Start the first search."
    clue: SensorClue | None = None
    scan_clue: SensorClue | None = None
    decision: Decision | None = None
    path: PathResult | None = None
    history: list[str] = field(default_factory=list)
    score: int = 0
    scan_charges: int = 2
    player_target: int | None = None
    target_source: str = "AI"
    captured_by_accusation: bool = False
    spooked: bool = False
    belief_trace: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class TurnResult:
    round_number: int
    target_label: str
    path_cost: float
    captured: bool
    target_source: str
    sighting: bool = False


class GameEngine:
    """Owns turn order, terminal conditions, and the hidden Ghost policy."""

    ACCUSATION_SCORE = 350

    def __init__(self, seed: int | None = None) -> None:
        self.rng = Random(seed)
        self.graph = CityGraph()
        self.ai = HunterAI(self.graph)
        self.ghost_policy = "REACTIVE"
        self.manual_mode = False
        self.difficulty = "NORMAL"
        self.new_game()

    def new_game(
        self,
        ghost_policy: str | None = None,
        manual_mode: bool | None = None,
        difficulty: str | None = None,
    ) -> None:
        if ghost_policy is not None:
            self.ghost_policy = ghost_policy
        if manual_mode is not None:
            self.manual_mode = manual_mode
        if difficulty is not None:
            self.difficulty = difficulty
        config = DIFFICULTY_CONFIG[self.difficulty]
        self.reveal_rounds = set(config["reveals"])
        self.state = GameState(
            max_rounds=config["rounds"],
            scan_charges=config["scans"],
        )
        self._randomise_starts()
        self.belief = BeliefState(self.graph, forbidden_node=self.state.hunter_node)

    def _randomise_starts(self) -> None:
        """Scatter Hunter and Ghost over the city, separated by difficulty."""
        config = DIFFICULTY_CONFIG[self.difficulty]
        self.state.hunter_node = self.rng.choice(list(self.graph.positions))
        distances = self.graph.shortest_distances(self.state.hunter_node)
        low, high = config["start_distance"]
        pool = [node for node in self.graph.positions if low <= distances[node] <= high]
        if not pool:
            pool = [max(self.graph.positions, key=lambda node: distances[node])]
        self.state.ghost_node = self.rng.choice(pool)

    @property
    def is_reveal_round(self) -> bool:
        return self.state.round_number in self.reveal_rounds and self.state.clue is not None

    def capture_value(self) -> int:
        """Score still on offer for landing on the Ghost this round."""
        return 100 * (self.state.max_rounds - self.state.round_number + 1)

    def advance_round(self, manual_target: int | None = None) -> TurnResult | None:
        """Run one complete Ghost -> clue -> AI -> A* -> Hunter round.

        In manual control mode an explicit target node overrides the AI's
        recommendation, but the AI still thinks and its recommendation stays
        visible for comparison.
        """
        if self.state.status != "ACTIVE":
            return None

        current_round = self.state.round_number
        seen = current_round in self.reveal_rounds or self.state.spooked
        if seen:
            # The Ghost was glimpsed at its current node, so the Hunter's
            # belief collapses there before both sides act.
            self.belief.seed_at(self.state.ghost_node)
        self.state.ghost_node = self._choose_ghost_move(spooked=seen)
        sighting = (
            current_round not in self.reveal_rounds
            and self.rng.random() < DIFFICULTY_CONFIG[self.difficulty]["sight_chance"]
        )
        self.state.clue = generate_clue(self.graph, self.state.ghost_node, self.rng)
        self.belief.predict_ghost_move(self.graph)
        self.belief.update_from_clue(self.graph, self.state.clue, self.state.hunter_node)
        # Track how much probability the final belief puts on the true node.
        self.state.belief_trace.append(self.belief.probabilities.get(self.state.ghost_node, 0.0))
        self.state.decision = self.ai.choose_target(self.state.hunter_node, self.belief)

        if self.manual_mode and manual_target is not None:
            target = manual_target
            self.state.target_source = "PLAYER"
        else:
            target = self.state.decision.target
            self.state.target_source = "AI"
        self.state.player_target = target if self.state.target_source == "PLAYER" else None

        self.state.path = find_path(self.graph, self.state.hunter_node, target)

        if len(self.state.path.path) > 1:
            self.state.hunter_node = self.state.path.path[1]

        captured = self.state.hunter_node == self.state.ghost_node
        target_label = self.graph.labels[target]
        source_tag = "PLAYER" if self.state.target_source == "PLAYER" else "AI"
        self.state.history.insert(
            0,
            f"R{current_round} [{source_tag}]: {target_label}; Hunter -> {self.graph.labels[self.state.hunter_node]}",
        )
        self.state.history = self.state.history[:4]

        if captured:
            self.state.score += self.capture_value()
            self.state.status = "HUNTER_WON"
            self.state.outcome_message = "Capture confirmed! The Hunter cornered the Ghost."
        elif current_round >= self.state.max_rounds:
            self.state.status = "GHOST_WON"
            self.state.outcome_message = "Move limit reached. The Ghost vanished into the city."
        else:
            self.state.round_number += 1
            if seen:
                self.state.outcome_message = "The spooked Ghost fled erratically from its revealed spot."
            elif source_tag == "PLAYER":
                self.state.outcome_message = "You overrode the AI and followed your own lead."
            else:
                self.state.outcome_message = "Analysis complete. The Hunter followed the highlighted route."

        self.state.spooked = sighting

        return TurnResult(
            current_round, target_label, self.state.path.cost, captured,
            self.state.target_source, sighting,
        )

    def use_scan(self, sensor_node: int) -> SensorClue | None:
        """Spend one deep-scan charge for an exact reading from a chosen sensor."""
        if self.state.status != "ACTIVE" or self.state.scan_charges <= 0:
            return None
        if sensor_node not in {sensor.node for sensor in self.graph.sensors}:
            return None
        clue = generate_scan_clue(self.graph, self.state.ghost_node, sensor_node)
        self.state.scan_clue = clue
        self.state.scan_charges -= 1
        self.belief.update_from_clue(self.graph, clue, self.state.hunter_node)
        self.state.history.insert(
            0,
            f"R{self.state.round_number} [SCAN]: deep scan via {clue.sensor.name}",
        )
        self.state.history = self.state.history[:4]
        return clue

    def accuse(self, node: int) -> bool | None:
        """Resolve the Hunter's one-shot exact-node accusation.

        An accusation is refused while the Ghost is visibly manifesting
        (reveal rounds, and the rounds right after a sighting) — a ghost
        you can see must be cornered on the map instead.
        """
        if self.state.status != "ACTIVE":
            return None
        if self.state.round_number in self.reveal_rounds or self.state.spooked:
            self.state.outcome_message = "No accusing a Ghost you can see — corner it on the map instead."
            return None
        if node == self.state.ghost_node:
            self.state.score += self.ACCUSATION_SCORE
            self.state.captured_by_accusation = True
            self.state.status = "HUNTER_WON"
            self.state.outcome_message = f"Correct accusation at {self.graph.labels[node]}! Ghost captured."
            return True
        self.state.status = "GHOST_WON"
        self.state.outcome_message = f"Wrong accusation at {self.graph.labels[node]}. The Ghost escaped."
        return False

    def _choose_ghost_move(self, spooked: bool = False) -> int:
        """Dispatch the configured Ghost evasive policy; a spooked Ghost panics."""
        candidates = [node for node, _ in self.graph.neighbors(self.state.ghost_node)]
        panic = self.rng.random() < (0.5 if spooked else 0.0) or (
            self.ghost_policy == "CHAOTIC" and self.rng.random() < 0.35
        )
        if panic:
            return self.rng.choice(candidates)
        distances = self.graph.shortest_distances(self.state.hunter_node)
        if self.ghost_policy == "CUNNING":
            belief = self.belief.probabilities

            def cunning_score(node: int) -> float:
                return distances[node] - 30.0 * belief.get(node, 0.0)

            best = max(cunning_score(node) for node in candidates)
            pool = [node for node in candidates if cunning_score(node) >= best - 1e-9]
            return self.rng.choice(pool)
        furthest_distance = max(distances[node] for node in candidates)
        furthest = [node for node in candidates if distances[node] == furthest_distance]
        return self.rng.choice(furthest)
