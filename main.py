"""Launch Shadow Chase, a compact adversarial-search Pygame demo."""

from __future__ import annotations

import argparse

from shadow_chase.game_rules import GameEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow Chase Pygame demo")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run one complete AI turn without opening a window.",
    )
    args = parser.parse_args()

    if args.smoke_test:
        engine = GameEngine(seed=7)
        result = engine.advance_round()
        assert result is not None
        print(
            f"Smoke test passed: round {result.round_number}, "
            f"target {result.target_label}, path cost {result.path_cost}."
        )
        return

    from shadow_chase.ui import ShadowChaseApp

    ShadowChaseApp().run()


if __name__ == "__main__":
    main()
