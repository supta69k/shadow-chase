"""Fixed weighted city graph used by Shadow Chase."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import hypot
from typing import Iterable


@dataclass(frozen=True)
class Sensor:
    node: int
    name: str
    district: str


class CityGraph:
    """A small connected city graph with road lengths as edge weights."""

    def __init__(self) -> None:
        self.positions: dict[int, tuple[int, int]] = {
            0: (115, 235), 1: (270, 215), 2: (430, 238), 3: (600, 220), 4: (770, 242),
            5: (160, 340), 6: (320, 325), 7: (480, 345), 8: (640, 325), 9: (820, 348),
            10: (100, 448), 11: (260, 430), 12: (430, 455), 13: (590, 430), 14: (750, 458),
            15: (175, 560), 16: (340, 545), 17: (510, 575), 18: (670, 550), 19: (835, 580),
            20: (115, 665), 21: (300, 670), 22: (500, 695), 23: (720, 670), 24: (875, 685),
        }
        self.labels = {node: f"N{node + 1:02}" for node in self.positions}
        self.districts = {
            **{node: "NORTH" for node in range(0, 5)},
            **{node: "MIDTOWN" for node in range(5, 10)},
            **{node: "CENTRAL" for node in range(10, 15)},
            **{node: "OLD TOWN" for node in range(15, 20)},
            **{node: "HARBOR" for node in range(20, 25)},
        }
        self.sensors = (
            Sensor(1, "North Relay", "NORTH"),
            Sensor(8, "Midtown Mic", "MIDTOWN"),
            Sensor(13, "Central Array", "CENTRAL"),
            Sensor(16, "Old Town Echo", "OLD TOWN"),
            Sensor(23, "Harbor Beacon", "HARBOR"),
        )
        roads = (
            (0, 1), (1, 2), (2, 3), (3, 4),
            (5, 6), (6, 7), (7, 8), (8, 9),
            (10, 11), (11, 12), (12, 13), (13, 14),
            (15, 16), (16, 17), (17, 18), (18, 19),
            (20, 21), (21, 22), (22, 23), (23, 24),
            (0, 5), (1, 6), (2, 7), (3, 8), (4, 9),
            (5, 10), (6, 11), (7, 12), (8, 13), (9, 14),
            (10, 15), (11, 16), (12, 17), (13, 18), (14, 19),
            (15, 20), (16, 21), (17, 22), (18, 23), (19, 24),
            (6, 10), (8, 14), (12, 16), (13, 17), (18, 24),
        )
        self.adjacency: dict[int, dict[int, int]] = {node: {} for node in self.positions}
        for first, second in roads:
            weight = self._road_weight(first, second)
            self.adjacency[first][second] = weight
            self.adjacency[second][first] = weight
        self._distance_cache: dict[int, dict[int, float]] = {}

    def _road_weight(self, first: int, second: int) -> int:
        x1, y1 = self.positions[first]
        x2, y2 = self.positions[second]
        return max(1, round(hypot(x2 - x1, y2 - y1) / 88))

    def neighbors(self, node: int) -> Iterable[tuple[int, int]]:
        return self.adjacency[node].items()

    def edge_cost(self, first: int, second: int) -> int:
        return self.adjacency[first][second]

    def heuristic(self, first: int, second: int) -> float:
        """Admissible straight-line estimate for the weighted city roads."""
        x1, y1 = self.positions[first]
        x2, y2 = self.positions[second]
        return hypot(x2 - x1, y2 - y1) / 88

    def shortest_distances(self, source: int) -> dict[int, float]:
        if source in self._distance_cache:
            return self._distance_cache[source]
        distances = {node: float("inf") for node in self.positions}
        distances[source] = 0
        queue: list[tuple[float, int]] = [(0, source)]
        while queue:
            cost, node = heappop(queue)
            if cost != distances[node]:
                continue
            for neighbor, weight in self.neighbors(node):
                candidate = cost + weight
                if candidate < distances[neighbor]:
                    distances[neighbor] = candidate
                    heappush(queue, (candidate, neighbor))
        self._distance_cache[source] = distances
        return distances

    def distance(self, first: int, second: int) -> float:
        return self.shortest_distances(first)[second]
