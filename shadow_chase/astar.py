"""A* search for routes over the Shadow Chase weighted city graph."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush

from .map_graph import CityGraph


@dataclass(frozen=True)
class PathResult:
    path: list[int]
    cost: float
    explored: int


def find_path(graph: CityGraph, start: int, goal: int) -> PathResult:
    """Return the lowest-cost route using an admissible city-distance heuristic."""
    frontier: list[tuple[float, int]] = [(graph.heuristic(start, goal), start)]
    came_from: dict[int, int | None] = {start: None}
    cost_so_far: dict[int, float] = {start: 0}
    explored = 0

    while frontier:
        _, current = heappop(frontier)
        explored += 1
        if current == goal:
            path: list[int] = []
            while current is not None:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return PathResult(path, cost_so_far[goal], explored)

        for neighbor, weight in graph.neighbors(current):
            candidate_cost = cost_so_far[current] + weight
            if candidate_cost < cost_so_far.get(neighbor, float("inf")):
                cost_so_far[neighbor] = candidate_cost
                came_from[neighbor] = current
                priority = candidate_cost + graph.heuristic(neighbor, goal)
                heappush(frontier, (priority, neighbor))

    raise ValueError(f"No route exists from {start} to {goal}.")
