"""Dev helper: render the main screens to PNGs without opening a window.

Usage: py -3 scripts/screenshot_preview.py [output_dir]
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_chase.ui import ShadowChaseApp  # noqa: E402


def settle(app: ShadowChaseApp, seconds: float) -> None:
    steps = int(seconds * 60)
    for _ in range(steps):
        app.time += 1 / 60
        app._update(1 / 60)
        app._draw()


def snap(app: ShadowChaseApp, name: str, out_dir: str) -> None:
    path = os.path.join(out_dir, name)
    pygame_image_save = getattr(app.screen, "save", None)
    import pygame

    pygame.image.save(app.screen, path)
    print("saved", path)


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "screens"
    os.makedirs(out_dir, exist_ok=True)
    app = ShadowChaseApp()

    # Menu screen.
    settle(app, 1.2)
    snap(app, "1_menu.png", out_dir)

    # In game: a couple of AI rounds.
    app._start_game()
    settle(app, 0.3)
    app._do_turn()
    settle(app, 0.9)
    app._do_turn()
    settle(app, 0.7)
    snap(app, "2_game_auto.png", out_dir)

    # A ghost sighting flash.
    app.sighting_until = app.time + 5.0
    settle(app, 0.3)
    snap(app, "2b_sighting.png", out_dir)
    app.sighting_until = 0.0

    # Scan pending + ping.
    app.pending = "SCAN"
    settle(app, 0.4)
    snap(app, "3_scan_pending.png", out_dir)
    app.pending = None
    app._do_scan(8)
    settle(app, 0.5)
    snap(app, "4_after_scan.png", out_dir)

    # Reveal round (round 4).
    while app.engine.state.round_number < 4 and app.engine.state.status == "ACTIVE":
        app._do_turn()
    settle(app, 0.8)
    snap(app, "5_reveal_round.png", out_dir)

    # Manual mode with a staged player target.
    app.engine.manual_mode = True
    app.engine.state.player_target = 17
    settle(app, 0.4)
    snap(app, "6_manual_target.png", out_dir)

    # Play out to an ending.
    guard = 0
    while app.engine.state.status == "ACTIVE" and guard < 14:
        app._do_turn()
        guard += 1
    settle(app, 1.0)
    snap(app, "7_outcome.png", out_dir)


if __name__ == "__main__":
    main()
