import unittest

from shadow_chase.astar import find_path
from shadow_chase.belief import BeliefState, generate_clue
from shadow_chase.game_rules import GHOST_POLICIES, GameEngine
from shadow_chase.map_graph import CityGraph


class ShadowChaseCoreTests(unittest.TestCase):
    def test_weighted_graph_is_connected(self) -> None:
        graph = CityGraph()
        distances = graph.shortest_distances(0)
        self.assertEqual(len(distances), 25)
        self.assertTrue(all(distance < float("inf") for distance in distances.values()))

    def test_astar_reaches_goal_with_valid_weight(self) -> None:
        graph = CityGraph()
        result = find_path(graph, 0, 24)
        self.assertEqual(result.path[0], 0)
        self.assertEqual(result.path[-1], 24)
        self.assertEqual(result.cost, graph.distance(0, 24))

    def test_belief_remains_normalised_after_noisy_clue(self) -> None:
        graph = CityGraph()
        belief = BeliefState(graph, forbidden_node=0)
        clue = generate_clue(graph, ghost_node=18, rng=__import__("random").Random(4))
        belief.predict_ghost_move(graph)
        belief.update_from_clue(graph, clue, hunter_node=0)
        self.assertAlmostEqual(sum(belief.probabilities.values()), 1.0)
        self.assertEqual(belief.probabilities[0], 0.0)

    def test_turn_runs_full_ai_pipeline(self) -> None:
        engine = GameEngine(seed=3)
        result = engine.advance_round()
        self.assertIsNotNone(result)
        self.assertIsNotNone(engine.state.clue)
        self.assertIsNotNone(engine.state.decision)
        self.assertIsNotNone(engine.state.path)
        self.assertGreaterEqual(engine.state.decision.evaluated_states, 1)

    def test_ghost_policies_move_along_roads(self) -> None:
        for policy in GHOST_POLICIES:
            engine = GameEngine(seed=11)
            engine.ghost_policy = policy
            for _ in range(8):
                candidates = [node for node, _ in engine.graph.neighbors(engine.state.ghost_node)]
                moved = engine._choose_ghost_move()
                self.assertIn(moved, candidates)
                engine.state.ghost_node = moved

    def test_scan_spends_charge_and_sharpens_belief(self) -> None:
        engine = GameEngine(seed=5)
        engine.state.ghost_node = 7
        clue = engine.use_scan(8)
        self.assertIsNotNone(clue)
        self.assertEqual(clue.strength, "SCAN")
        self.assertEqual(engine.state.scan_charges, 1)
        self.assertAlmostEqual(sum(engine.belief.probabilities.values()), 1.0)
        self.assertGreater(engine.belief.probabilities[7], 0.08)
        engine.use_scan(13)
        self.assertEqual(engine.state.scan_charges, 0)
        self.assertIsNone(engine.use_scan(16))

    def test_manual_target_overrides_ai_recommendation(self) -> None:
        engine = GameEngine(seed=2)
        engine.manual_mode = True
        result = engine.advance_round(manual_target=24)
        self.assertEqual(result.target_source, "PLAYER")
        self.assertEqual(engine.state.path.path[-1], 24)

    def test_correct_accusation_scores_and_wins(self) -> None:
        engine = GameEngine(seed=9)
        self.assertTrue(engine.accuse(engine.state.ghost_node))
        self.assertEqual(engine.state.status, "HUNTER_WON")
        self.assertGreaterEqual(engine.state.score, engine.ACCUSATION_SCORE)

    def test_wrong_accusation_loses_with_zero_score(self) -> None:
        engine = GameEngine(seed=9)
        wrong = (engine.state.ghost_node + 1) % 25
        self.assertFalse(engine.accuse(wrong))
        self.assertEqual(engine.state.status, "GHOST_WON")
        self.assertEqual(engine.state.score, 0)

    def test_landing_capture_scores_bounty(self) -> None:
        engine = GameEngine(seed=4)
        engine.manual_mode = True
        engine.state.hunter_node = 11
        engine.state.ghost_node = 12
        engine._choose_ghost_move = lambda spooked=False: 12  # ghost holds still for this test
        result = engine.advance_round(manual_target=12)
        self.assertTrue(result.captured)
        self.assertEqual(engine.state.score, engine.capture_value())

    def test_start_positions_are_random_and_far_enough(self) -> None:
        ghost_starts = set()
        for seed in range(8):
            engine = GameEngine(seed=seed)
            hunter = engine.state.hunter_node
            ghost = engine.state.ghost_node
            self.assertNotEqual(hunter, ghost)
            distance = engine.graph.distance(hunter, ghost)
            self.assertGreaterEqual(distance, 4)  # NORMAL keeps them apart
            ghost_starts.add(ghost)
        self.assertGreater(len(ghost_starts), 1)  # not the same node every game

    def test_difficulty_config_applies(self) -> None:
        for difficulty, rounds, scans in (("EASY", 12, 3), ("NORMAL", 12, 2), ("HARD", 10, 1)):
            engine = GameEngine(seed=1)
            engine.new_game(difficulty=difficulty)
            self.assertEqual(engine.difficulty, difficulty)
            self.assertEqual(engine.state.max_rounds, rounds)
            self.assertEqual(engine.state.scan_charges, scans)
            self.assertTrue(engine.reveal_rounds)

    def test_start_distance_respects_difficulty(self) -> None:
        for seed in range(12):
            easy = GameEngine(seed=seed)
            easy.new_game(difficulty="EASY")
            easy_distance = easy.graph.distance(easy.state.hunter_node, easy.state.ghost_node)
            self.assertGreaterEqual(easy_distance, 2)
            self.assertLessEqual(easy_distance, 5)
            hard = GameEngine(seed=seed)
            hard.new_game(difficulty="HARD")
            hard_distance = hard.graph.distance(hard.state.hunter_node, hard.state.ghost_node)
            self.assertGreaterEqual(hard_distance, 6)

    def test_turn_reports_sighting_flag(self) -> None:
        engine = GameEngine(seed=15)
        result = engine.advance_round()
        self.assertIsInstance(result.sighting, bool)

    def test_belief_seed_collapses_distribution(self) -> None:
        graph = CityGraph()
        belief = BeliefState(graph, forbidden_node=0)
        belief.seed_at(7)
        self.assertEqual(belief.probabilities[7], 1.0)
        self.assertAlmostEqual(sum(belief.probabilities.values()), 1.0)

    def test_reveal_round_seeds_belief_at_seen_node(self) -> None:
        engine = GameEngine(seed=3)
        engine.state.round_number = min(engine.reveal_rounds)
        seen = engine.state.ghost_node
        engine.advance_round()
        neighbours = [node for node, _ in engine.graph.neighbors(seen)]
        support = sum(engine.belief.probabilities[node] for node in neighbours)
        self.assertAlmostEqual(support, 1.0)  # all mass fled from the seen node

    def test_accuse_refused_while_ghost_visible(self) -> None:
        engine = GameEngine(seed=6)
        engine.state.round_number = min(engine.reveal_rounds)
        self.assertIsNone(engine.accuse(engine.state.ghost_node))
        self.assertEqual(engine.state.status, "ACTIVE")
        engine.state.round_number = 1
        engine.state.spooked = True
        self.assertIsNone(engine.accuse(engine.state.ghost_node))
        self.assertEqual(engine.state.status, "ACTIVE")

    def test_accuse_still_works_when_hidden(self) -> None:
        engine = GameEngine(seed=6)
        self.assertTrue(engine.accuse(engine.state.ghost_node))
        self.assertEqual(engine.state.status, "HUNTER_WON")

    def test_spooked_move_stays_legal(self) -> None:
        engine = GameEngine(seed=8)
        for _ in range(30):
            candidates = [node for node, _ in engine.graph.neighbors(engine.state.ghost_node)]
            move = engine._choose_ghost_move(spooked=True)
            self.assertIn(move, candidates)
            engine.state.ghost_node = move

    def test_belief_trace_records_true_node_confidence(self) -> None:
        engine = GameEngine(seed=21)
        engine.advance_round()
        self.assertEqual(len(engine.state.belief_trace), 1)
        value = engine.state.belief_trace[0]
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_record_best_tracks_new_records(self) -> None:
        import tempfile
        from pathlib import Path

        from shadow_chase.persistence import load_best, record_best

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "best.json"
            is_new, _ = record_best(path, "EASY", 500, "C")
            self.assertTrue(is_new)
            is_new, _ = record_best(path, "EASY", 300, "D")
            self.assertFalse(is_new)  # lower score is not a new record
            is_new, data = record_best(path, "EASY", 900, "A")
            self.assertTrue(is_new)
            self.assertEqual(data["EASY"]["score"], 900)
            self.assertEqual(load_best(path)["EASY"]["rank"], "A")


if __name__ == "__main__":
    unittest.main()
