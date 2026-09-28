"""Noisy sensor clues and a compact Bayesian-style belief filter."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from random import Random

from .map_graph import CityGraph, Sensor


@dataclass(frozen=True)
class SensorClue:
    sensor: Sensor
    strength: str
    estimated_distance: float
    message: str


class BeliefState:
    """Probability mass over the Ghost's currently possible intersections."""

    def __init__(self, graph: CityGraph, forbidden_node: int | None = None) -> None:
        allowed = [node for node in graph.positions if node != forbidden_node]
        initial_probability = 1 / len(allowed)
        self.probabilities = {
            node: (initial_probability if node in allowed else 0.0)
            for node in graph.positions
        }

    def predict_ghost_move(self, graph: CityGraph) -> None:
        """Spread each belief mass over the Ghost's legal adjacent moves."""
        predicted = {node: 0.0 for node in graph.positions}
        for node, probability in self.probabilities.items():
            neighbors = list(graph.neighbors(node))
            if not neighbors:
                predicted[node] += probability
                continue
            share = probability / len(neighbors)
            for neighbor, _ in neighbors:
                predicted[neighbor] += share
        self.probabilities = predicted

    def update_from_clue(self, graph: CityGraph, clue: SensorClue, hunter_node: int) -> None:
        """Reweight candidate locations by their fit to a noisy sensor reading."""
        sigma = {"STRONG": 1.25, "MEDIUM": 2.2, "FAINT": 3.2, "SCAN": 0.85}[clue.strength]
        weighted: dict[int, float] = {}
        for node, prior in self.probabilities.items():
            sensor_distance = graph.distance(node, clue.sensor.node)
            difference = sensor_distance - clue.estimated_distance
            likelihood = 0.03 + exp(-(difference * difference) / (2 * sigma * sigma))
            weighted[node] = prior * likelihood
        weighted[hunter_node] = 0.0
        self.probabilities = weighted
        self._normalise()

    def _normalise(self) -> None:
        total = sum(self.probabilities.values())
        if total <= 0:
            equal = 1 / len(self.probabilities)
            self.probabilities = {node: equal for node in self.probabilities}
            return
        self.probabilities = {
            node: probability / total for node, probability in self.probabilities.items()
        }

    def seed_at(self, node: int) -> None:
        """Collapse the belief onto one observed node (the Ghost was seen)."""
        self.probabilities = {n: (1.0 if n == node else 0.0) for n in self.probabilities}

    def top(self, count: int = 6) -> list[tuple[int, float]]:
        return sorted(self.probabilities.items(), key=lambda item: item[1], reverse=True)[:count]


def generate_clue(graph: CityGraph, ghost_node: int, rng: Random) -> SensorClue:
    """Generate a deliberately imprecise clue from the closest sensor station."""
    nearest_sensor = min(graph.sensors, key=lambda sensor: graph.distance(ghost_node, sensor.node))
    actual_distance = graph.distance(ghost_node, nearest_sensor.node)
    noisy_distance = max(0.0, actual_distance + rng.choice((-1.0, 0.0, 0.0, 1.0)))
    if noisy_distance <= 2:
        strength = "STRONG"
        phrase = "A sharp echo"
    elif noisy_distance <= 5:
        strength = "MEDIUM"
        phrase = "A scattered noise"
    else:
        strength = "FAINT"
        phrase = "A distant whisper"
    message = f"{phrase} reached {nearest_sensor.name} in {nearest_sensor.district}."
    return SensorClue(nearest_sensor, strength, noisy_distance, message)


def generate_scan_clue(graph: CityGraph, ghost_node: int, sensor_node: int) -> SensorClue:
    """Deep-scan reading: an exact road distance from one chosen sensor station."""
    sensor = next(sensor for sensor in graph.sensors if sensor.node == sensor_node)
    exact_distance = graph.distance(ghost_node, sensor_node)
    message = (
        f"Deep scan locked {sensor.name} in {sensor.district}: "
        f"exact road distance {exact_distance:.0f}."
    )
    return SensorClue(sensor, "SCAN", exact_distance, message)
