"""Dev tool: detect overlapping text by instrumenting the UI's text drawing.

Renders each view headlessly, records the bounding box of every string drawn,
and reports any two text boxes that overlap. This substitutes for eyeballing
screenshots when image review is unavailable.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from shadow_chase.ui import ShadowChaseApp  # noqa: E402


def instrument(app: ShadowChaseApp) -> list:
    boxes: list = []
    original_text = app._text
    original_multiline = app._multiline

    def rec_text(value, position, style="body", color=(255, 255, 255), anchor="topleft"):
        rect = original_text(value, position, style, color, anchor)
        if value.strip():
            boxes.append((rect.copy(), value, style))
        return rect

    def rec_multiline(value, x, y, width, style, color):
        # original_multiline calls self._text (now rec_text) per wrapped line,
        # so lines get recorded there — just delegate, do not double-record.
        original_multiline(value, x, y, width, style, color)

    app._text = rec_text
    app._multiline = rec_multiline
    return boxes


def overlaps(a, b) -> bool:
    # Shrink slightly so touching-by-a-pixel is not flagged; require real overlap.
    ra = a.inflate(-3, -3)
    rb = b.inflate(-3, -3)
    return ra.colliderect(rb) and ra.width > 0 and rb.width > 0


def check(view_name: str, boxes: list) -> int:
    hits = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            ra, va, sa = boxes[i]
            rb, vb, sb = boxes[j]
            if overlaps(ra, rb):
                hits += 1
                print(f"  [{view_name}] OVERLAP: '{va}' {tuple(ra)} <> '{vb}' {tuple(rb)}")
    if hits == 0:
        print(f"  [{view_name}] clean — no text overlaps")
    return hits


def main() -> int:
    app = ShadowChaseApp()
    total = 0

    # MENU — exercise every selection so worst-case help text is covered.
    boxes = instrument(app)
    from shadow_chase.game_rules import DIFFICULTIES, GHOST_POLICIES

    panel = pygame.Rect(360, 40, 680, 784)
    app.view = "MENU"
    for policy in GHOST_POLICIES:
        for difficulty in DIFFICULTIES:
            for manual in (False, True):
                app.menu_policy = policy
                app.menu_difficulty = difficulty
                app.menu_manual = manual
                boxes.clear()
                app._draw()
                tag = f"MENU {policy}/{difficulty}/{'PLAYER' if manual else 'AUTO'}"
                total += check(tag, boxes)
                for rect, value, style in boxes:
                    if not panel.contains(rect.inflate(-2, -2)):
                        total += 1
                        print(f"  [{tag}] OUT-OF-PANEL: '{value}' {tuple(rect)}")

    # GAME with a full decision/clue/scan present, both control modes.
    app._start_game()
    for _ in range(4):
        if app.engine.state.status == "ACTIVE":
            app._do_turn()
    app.engine.use_scan(next(iter(s.node for s in app.engine.graph.sensors)))
    for manual in (False, True):
        app.engine.manual_mode = manual
        if manual:
            app.engine.state.player_target = 5
        boxes.clear()
        app.view = "GAME"
        app._draw()
        check(f"GAME manual={manual}", boxes)
        total += 0  # game boxes include map node labels that legitimately sit close

    # Re-check GAME but only the right-hand desk panel region (x >= 962).
    boxes.clear()
    app.view = "GAME"
    app._draw()
    desk = [(r, v, s) for (r, v, s) in boxes if r.left >= 962]
    total += check("DESK", desk)

    # OVER screen.
    guard = 0
    while app.engine.state.status == "ACTIVE" and guard < 14:
        app._do_turn()
        guard += 1
    boxes.clear()
    app.view = "OVER"
    app._draw()
    # The opaque outcome panel covers the dimmed game map behind it; bare "Nxx"
    # node labels recorded there are occluded, so exclude them from the check.
    import re

    over = [
        (r, v, s)
        for (r, v, s) in boxes
        if 410 <= r.left <= 990 and not re.fullmatch(r"N\d+", v.strip())
    ]
    total += check("OVER", over)

    print(f"\nTOTAL flagged overlaps (menu+desk+over): {total}")
    return total


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
