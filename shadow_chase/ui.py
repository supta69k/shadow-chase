"""Pygame presentation layer for Shadow Chase."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, pi, sin
from random import Random

import pygame

from .game_rules import (
    DIFFICULTIES,
    DIFFICULTY_CONFIG,
    DIFFICULTY_HELP,
    GHOST_POLICIES,
    GHOST_POLICY_HELP,
    GameEngine,
)
from .persistence import load_best, record_best

Color = tuple[int, int, int]

# Spooky séance palette: near-black voids, spectral teal, candle amber, ghost violet.
BACK: Color = (8, 7, 18)
PANEL: Color = (18, 16, 36)
PANEL_ALT: Color = (26, 22, 48)
GRID: Color = (22, 20, 42)
TEXT: Color = (231, 226, 240)
MUTED: Color = (150, 146, 178)
DIM: Color = (96, 92, 128)
CYAN: Color = (96, 226, 214)      # spectral ghost-light (primary accent)
GREEN: Color = (126, 240, 150)    # hunter's lantern
PURPLE: Color = (188, 120, 255)   # the ghost
PINK: Color = (255, 96, 150)      # danger / blood
GOLD: Color = (255, 182, 92)      # candlelight
RED: Color = (255, 84, 84)

CLUE_COLORS = {"STRONG": CYAN, "MEDIUM": GOLD, "FAINT": MUTED, "SCAN": PINK}
RANKS = ((900, "S"), (600, "A"), (400, "B"), (200, "C"), (1, "D"))


def _lerp(first: float, second: float, t: float) -> float:
    return first + (second - first) * t


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def _scale(color: Color, factor: float) -> Color:
    return tuple(min(255, int(channel * factor)) for channel in color)


@dataclass(frozen=True)
class Button:
    label: str
    rect: pygame.Rect
    key: str
    enabled: bool = True


class ShadowChaseApp:
    WIDTH = 1400
    HEIGHT = 860

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Shadow Chase - AI Pursuit Demo")
        self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
        self.clock = pygame.time.Clock()
        self.engine = GameEngine()
        self.running = True
        self.view = "MENU"
        self.time = 0.0
        self.fade = 1.0
        self.pending: str | None = None  # None | "ACCUSE" | "SCAN"
        self.fx_rng = Random(99)
        rng = Random(31)
        self.stars = [
            (rng.randrange(self.WIDTH), rng.randrange(self.HEIGHT), rng.randrange(1, 3))
            for _ in range(130)
        ]
        # Ambient drifting motes for atmosphere (fireflies / dust in the fog).
        self.embers = [
            {
                "x": rng.uniform(0, self.WIDTH),
                "y": rng.uniform(0, self.HEIGHT),
                "speed": rng.uniform(6, 22),
                "sway": rng.uniform(0.4, 1.4),
                "phase": rng.uniform(0, 6.28),
                "size": rng.uniform(1.2, 2.8),
                "color": rng.choice([CYAN, PURPLE, GOLD, GREEN]),
            }
            for _ in range(46)
        ]
        # Spooky display faces for headings + a clean serif for body legibility.
        title_face = "chiller,blackadderitc,impact,arial"
        head_face = "georgia,constantia,timesnewroman,serif"
        self.fonts = {
            "title": pygame.font.SysFont("chiller,impact,arialblack", 42),
            "hero": pygame.font.SysFont("chiller,impact,arialblack", 84),
            "heading": pygame.font.SysFont(head_face, 21, bold=True),
            "body": pygame.font.SysFont(head_face, 16),
            "small": pygame.font.SysFont(head_face, 14),
            "label": pygame.font.SysFont("georgia,constantia,arial", 15, bold=True),
            "node": pygame.font.SysFont("arial", 12, bold=True),
            "mono": pygame.font.SysFont("consolas", 16, bold=True),
            "mono_small": pygame.font.SysFont("consolas", 13, bold=True),
        }
        self.menu_policy = "REACTIVE"
        self.menu_manual = False
        self.menu_difficulty = "NORMAL"
        self.sighting_until = 0.0
        self.timer_enabled = False
        self.turn_deadline = 0.0
        self.best = load_best()
        self.new_record = False
        self.particles: list[dict] = []
        self.pings: list[dict] = []
        self.shake = 0.0
        self.hunter_anim: dict | None = None
        self.bar_cache: dict[int, float] = {}
        self._glow_cache: dict[tuple, pygame.Surface] = {}
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self.muted = False
        self.ambient = None
        self._music_channel = None
        self._build_sounds()
        self._build_vignette()
        self._build_backdrop()
        # Reusable overlays: allocating fullscreen surfaces per frame
        # eventually exhausts memory.
        self._fade_overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        self._dim_overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        self._dim_overlay.fill((2, 5, 15, 185))

    # ------------------------------------------------------------------ setup

    def _build_sounds(self) -> None:
        """Synthesise a tiny UI sound kit; every failure stays silent."""
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            import array
            import math

            rate = 22050

            def tone(freqs: list[int], duration: float, volume: float) -> pygame.mixer.Sound:
                samples = array.array("h")
                steps = int(rate * duration)
                phase = 0.0
                for index in range(steps):
                    freq = freqs[min(index * len(freqs) // steps, len(freqs) - 1)]
                    phase += 2 * pi * freq / rate
                    envelope = min(1.0, index / 300.0) * max(0.0, 1 - index / steps) ** 1.4
                    samples.append(int(32767 * volume * envelope * sin(phase)))
                return pygame.mixer.Sound(buffer=samples.tobytes())

            self.sounds = {
                "click": tone([660], 0.06, 0.22),
                "move": tone([320], 0.08, 0.15),
                "clue": tone([520, 784], 0.20, 0.28),
                "scan": tone([880, 1175, 880], 0.28, 0.26),
                "sight": tone([988, 1319, 988], 0.25, 0.28),
                "capture": tone([523, 659, 784, 1047, 1319], 0.6, 0.34),
                "lose": tone([420, 311, 233], 0.7, 0.30),
                "target": tone([440, 554], 0.10, 0.20),
            }
            # Ambient background music intentionally disabled — interaction SFX only.
            self.ambient = None
        except Exception:
            self.sounds = {}
            self.ambient = None

    def _build_ambient(self, rate: int):
        """A seamless 6-second tense drone: detuned low sines + a slow heartbeat."""
        try:
            import array

            length = 6.0
            steps = int(rate * length)
            samples = array.array("h")
            beat_period = 1.2  # 5 whole beats across the 6s loop -> seamless
            for index in range(steps):
                t = index / rate
                # Uneasy detuned drone (whole cycles across the loop).
                tremolo = 0.82 + 0.18 * sin(2 * pi * t / 3.0)
                drone = (
                    0.16 * sin(2 * pi * 55.0 * t)
                    + 0.11 * sin(2 * pi * 82.5 * t)
                    + 0.05 * sin(2 * pi * 110.0 * t)
                ) * tremolo
                # Soft double heartbeat.
                beat_t = t % beat_period
                thump = 0.0
                for onset in (0.0, 0.18):
                    dt = beat_t - onset
                    if 0 <= dt < 0.16:
                        thump += 0.5 * sin(2 * pi * 46 * dt) * (1 - dt / 0.16) ** 2
                value = max(-1.0, min(1.0, (drone + thump) * 0.6))
                samples.append(int(32767 * 0.5 * value))
            return pygame.mixer.Sound(buffer=samples.tobytes())
        except Exception:
            return None

    def _update_music(self) -> None:
        """Keep the ambient drone looping unless muted; safe if audio is absent."""
        if not getattr(self, "ambient", None):
            return
        try:
            channel = getattr(self, "_music_channel", None)
            if self.muted:
                if channel and channel.get_busy():
                    channel.stop()
                    self._music_channel = None
                return
            if channel is None or not channel.get_busy():
                self._music_channel = self.ambient.play(loops=-1)
                if self._music_channel:
                    self._music_channel.set_volume(0.55)
        except Exception:
            pass

    def _build_vignette(self) -> None:
        surface = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        for inset in range(0, 220, 4):
            alpha = int(38 * (1 - inset / 220))
            pygame.draw.rect(
                surface,
                (1, 2, 10, alpha),
                pygame.Rect(inset, inset, self.WIDTH - 2 * inset, self.HEIGHT - 2 * inset),
                width=4,
                border_radius=24,
            )
        self._vignette = surface

    def _build_backdrop(self) -> None:
        """A painted night-sky backdrop: gradient, a glowing moon, ground fog."""
        surface = pygame.Surface((self.WIDTH, self.HEIGHT))
        top = (10, 8, 30)
        bottom = (26, 14, 46)
        for y in range(self.HEIGHT):
            t = y / self.HEIGHT
            surface.fill(
                (
                    int(_lerp(top[0], bottom[0], t)),
                    int(_lerp(top[1], bottom[1], t)),
                    int(_lerp(top[2], bottom[2], t)),
                ),
                pygame.Rect(0, y, self.WIDTH, 1),
            )
        # Big soft moon, upper right.
        moon_center = (1180, 150)
        for radius in range(150, 0, -6):
            alpha = int(52 * (1 - radius / 150) ** 2)
            glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow, (150, 170, 220, alpha), (radius, radius), radius)
            surface.blit(glow, glow.get_rect(center=moon_center))
        pygame.draw.circle(surface, (222, 230, 246), moon_center, 62)
        pygame.draw.circle(surface, (206, 214, 234), (1200, 132), 12)
        pygame.draw.circle(surface, (208, 216, 236), (1160, 172), 8)
        pygame.draw.circle(surface, (210, 218, 238), (1198, 182), 6)
        # Ground fog band along the bottom.
        fog = pygame.Surface((self.WIDTH, 240), pygame.SRCALPHA)
        for y in range(240):
            alpha = int(70 * (y / 240))
            pygame.draw.line(fog, (70, 60, 120, alpha), (0, y), (self.WIDTH, y))
        surface.blit(fog, (0, self.HEIGHT - 240))
        # A jagged skyline silhouette to sell the "haunted city" theme.
        skyline_rng = Random(7)
        x = -20
        base_y = self.HEIGHT - 150
        while x < self.WIDTH + 20:
            width = skyline_rng.randint(46, 110)
            height = skyline_rng.randint(40, 150)
            pygame.draw.rect(surface, (14, 12, 30), pygame.Rect(x, base_y - height, width, height + 200))
            for _ in range(skyline_rng.randint(1, 4)):
                wx = x + skyline_rng.randint(8, max(9, width - 14))
                wy = base_y - height + skyline_rng.randint(10, max(11, height - 10))
                if skyline_rng.random() < 0.5:
                    pygame.draw.rect(surface, (255, 206, 120), pygame.Rect(wx, wy, 5, 6))
            x += width + skyline_rng.randint(-6, 10)
        self._backdrop = surface

    def _play(self, name: str) -> None:
        sound = self.sounds.get(name)
        if sound and not self.muted:
            try:
                sound.play()
            except Exception:
                pass

    # ------------------------------------------------------------------- loop

    def run(self) -> None:
        while self.running:
            delta = min(self.clock.tick(60) / 1000.0, 0.05)
            self.time += delta
            self._update(delta)
            self._handle_events()
            self._draw()
            pygame.display.flip()
        pygame.quit()

    def _update(self, delta: float) -> None:
        self.fade = max(0.0, self.fade - delta * 2.4)
        self.shake = max(0.0, self.shake - 42 * delta)
        for ember in self.embers:
            ember["y"] -= ember["speed"] * delta
            if ember["y"] < -6:
                ember["y"] = self.HEIGHT + 6
                ember["x"] = self.fx_rng.uniform(0, self.WIDTH)
        if self.hunter_anim:
            self.hunter_anim["t"] += delta / self.hunter_anim["dur"]
            if self.hunter_anim["t"] >= 1:
                self.hunter_anim = None
        for particle in self.particles[:]:
            particle["pos"] += particle["vel"] * delta
            particle["vel"] *= 0.94
            particle["life"] -= delta
            if particle["life"] <= 0:
                self.particles.remove(particle)
        for ping in self.pings[:]:
            ping["t"] += delta / ping["dur"]
            if ping["t"] >= 1:
                self.pings.remove(ping)
        # Animated belief bars ease toward the live distribution.
        top = self.engine.belief.top(6)
        max_probability = top[0][1] if top else 1.0
        alive = {node for node, _ in top}
        for node, probability in top:
            target = probability / max(max_probability, 0.01)
            current = self.bar_cache.get(node, target * 0.15)
            self.bar_cache[node] = _lerp(current, target, min(1.0, delta * 9))
        for node in [node for node in self.bar_cache if node not in alive]:
            self.bar_cache[node] *= 1 - min(1.0, delta * 9)
            if self.bar_cache[node] < 0.01:
                del self.bar_cache[node]
        # Optional shot clock: run the turn automatically when time runs out.
        if (
            self.timer_enabled and self.turn_deadline > 0
            and self.view == "GAME" and self.engine.state.status == "ACTIVE"
            and self.time >= self.turn_deadline
        ):
            self._do_turn()

    # ----------------------------------------------------------------- events

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_click(event.pos)

    def _handle_key(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            if self.view == "GAME" and self.pending:
                self.pending = None
            else:
                self._change_view("MENU")
        elif self.view == "MENU":
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                self._start_game()
            elif key in (pygame.K_1, pygame.K_2, pygame.K_3):
                self.menu_policy = GHOST_POLICIES[key - pygame.K_1]
                self._play("click")
            elif key in (pygame.K_4, pygame.K_5, pygame.K_6):
                self.menu_difficulty = DIFFICULTIES[key - pygame.K_4]
                self._play("click")
            elif key == pygame.K_t:
                self.timer_enabled = not self.timer_enabled
                self._play("click")
            elif key == pygame.K_m:
                self.menu_manual = not self.menu_manual
                self._play("click")
        elif self.view == "OVER":
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                self._start_game()
        elif self.view == "GAME":
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                self._do_turn()
            elif key == pygame.K_a:
                self.pending = None if self.pending == "ACCUSE" else "ACCUSE"
                self._play("click")
            elif key == pygame.K_s:
                self.pending = None if self.pending == "SCAN" else "SCAN"
                self._play("click")
            elif key == pygame.K_m:
                self._toggle_mode()
            elif key == pygame.K_t:
                self.timer_enabled = not self.timer_enabled
                if self.timer_enabled:
                    self.turn_deadline = self.time + self._turn_seconds()
                else:
                    self.turn_deadline = 0.0
                self._play("click")
            elif key == pygame.K_r:
                self._start_game()
            elif key == pygame.K_n:
                self.muted = not self.muted

    def _handle_click(self, position: tuple[int, int]) -> None:
        if self.view == "MENU":
            self._menu_click(position)
            return
        if self.view == "OVER":
            for button in self._outcome_buttons():
                if button.rect.collidepoint(position):
                    if button.key == "again":
                        self._start_game()
                    elif button.key == "menu":
                        self._change_view("MENU")
                    return
            return
        if self.view != "GAME":
            return
        for button in self._buttons():
            if button.enabled and button.rect.collidepoint(position):
                self._press(button.key)
                return
        for chip in self._header_buttons():
            if chip.rect.collidepoint(position):
                self._press(chip.key)
                return
        if self._mode_chip_hit(position):
            return

        node = self._node_at(position)
        if self.pending == "ACCUSE":
            if node is not None:
                self._do_accuse(node)
            return
        if self.pending == "SCAN":
            if node is not None and node in {s.node for s in self.engine.graph.sensors}:
                self._do_scan(node)
            else:
                self.pending = None
            return
        if node is not None and self.engine.manual_mode:
            if self.engine.state.player_target != node:
                self.engine.state.player_target = node
                self._play("target")

    def _press(self, key: str) -> None:
        if key == "turn":
            self._do_turn()
        elif key == "accuse":
            self.pending = None if self.pending == "ACCUSE" else "ACCUSE"
            self._play("click")
        elif key == "scan":
            if self.engine.state.scan_charges > 0:
                self.pending = None if self.pending == "SCAN" else "SCAN"
                self._play("click")
        elif key == "mode":
            self._toggle_mode()
        elif key == "reset":
            self._start_game()
        elif key == "sound":
            self.muted = not self.muted
            self._play("click")

    def _mode_chip_hit(self, position: tuple[int, int]) -> bool:
        auto, player = self._mode_chips()
        if auto.collidepoint(position) or player.collidepoint(position):
            self._toggle_mode()
            return True
        return False

    def _toggle_mode(self) -> None:
        self.engine.manual_mode = not self.engine.manual_mode
        self.engine.state.player_target = None
        self._play("click")

    def _change_view(self, view: str) -> None:
        self.view = view
        self.pending = None
        self.fade = 1.0

    def _start_game(self) -> None:
        self.engine.new_game(
            ghost_policy=self.menu_policy,
            manual_mode=self.menu_manual,
            difficulty=self.menu_difficulty,
        )
        self.pending = None
        self.hunter_anim = None
        self.sighting_until = 0.0
        self.new_record = False
        self.particles.clear()
        self.pings.clear()
        self.bar_cache.clear()
        self._change_view("GAME")
        if self.timer_enabled:
            self.turn_deadline = self.time + self._turn_seconds()
        self._play("click")

    # ------------------------------------------------------------ turn actions

    def _do_turn(self) -> None:
        engine = self.engine
        if engine.state.status != "ACTIVE":
            return
        previous = engine.graph.positions[engine.state.hunter_node]
        manual_target = (
            engine.state.player_target if engine.manual_mode else None
        )
        result = engine.advance_round(manual_target)
        if result is None:
            return
        new = engine.graph.positions[engine.state.hunter_node]
        if new != previous:
            self.hunter_anim = {"from": pygame.Vector2(previous), "to": pygame.Vector2(new), "t": 0.0, "dur": 0.5}
        if engine.state.clue:
            sensor_pos = engine.graph.positions[engine.state.clue.sensor.node]
            self.pings.append({"pos": pygame.Vector2(sensor_pos), "t": 0.0, "dur": 0.75, "color": CLUE_COLORS[engine.state.clue.strength]})
        if result.captured:
            self._burst(new, (GREEN, CYAN, PURPLE), 46)
            self.shake = 15
            self._play("capture")
        elif engine.state.status == "GHOST_WON":
            self._burst(new, (RED, PURPLE, (60, 40, 90)), 40)
            self.shake = 11
            self._play("lose")
        elif result.sighting:
            ghost_pos = engine.graph.positions[engine.state.ghost_node]
            seconds = DIFFICULTY_CONFIG[engine.difficulty]["sight_seconds"]
            self.sighting_until = self.time + seconds
            self.pings.append({"pos": pygame.Vector2(ghost_pos), "t": 0.0, "dur": 0.8, "color": PURPLE})
            self._burst(ghost_pos, (PURPLE, PINK, CYAN), 22, speed=(30, 150), life=(0.4, 0.9))
            self._play("sight")
        else:
            self._burst(new, (GREEN, CYAN), 10, speed=(24, 90), life=(0.25, 0.5))
            self._play("clue" if result.round_number in engine.reveal_rounds else "move")
        if self.timer_enabled and engine.state.status == "ACTIVE":
            self.turn_deadline = self.time + self._turn_seconds()

    def _turn_seconds(self) -> int:
        return DIFFICULTY_CONFIG[self.engine.difficulty]["turn_seconds"]

    def _record_best(self) -> None:
        state = self.engine.state
        if state.score <= 0:
            self.new_record = False
            return
        is_new, self.best = record_best(
            None, self.engine.difficulty, state.score, self._rank(state.score)
        )
        self.new_record = is_new

    def _do_accuse(self, node: int) -> None:
        engine = self.engine
        self.pending = None
        correct = engine.accuse(node)
        if correct is None:
            # Accusation refused: the Ghost is currently visible.
            self._play("move")
            return
        position = engine.graph.positions[node]
        if correct:
            self._burst(position, (GREEN, GOLD, CYAN), 46)
            self.shake = 12
            self._play("capture")
        else:
            self._burst(position, (RED, PINK, PURPLE), 44)
            self.shake = 13
            self._play("lose")

    def _do_scan(self, node: int) -> None:
        self.pending = None
        clue = self.engine.use_scan(node)
        if clue:
            position = self.engine.graph.positions[node]
            self.pings.append({"pos": pygame.Vector2(position), "t": 0.0, "dur": 0.9, "color": PINK})
            self._burst(position, (PINK, CYAN), 14, speed=(20, 110), life=(0.3, 0.6))
            self._play("scan")

    # ------------------------------------------------------------------- fx

    def _burst(
        self,
        position: tuple[int, int],
        colors: tuple[Color, ...],
        count: int = 26,
        speed: tuple[float, float] = (40, 240),
        life: tuple[float, float] = (0.4, 1.1),
    ) -> None:
        for _ in range(count):
            angle = self.fx_rng.uniform(0, 2 * pi)
            pace = self.fx_rng.uniform(*speed)
            self.particles.append(
                {
                    "pos": pygame.Vector2(position),
                    "vel": pygame.Vector2(cos(angle) * pace, sin(angle) * pace),
                    "life": self.fx_rng.uniform(*life),
                    "max": 0.0,
                    "color": self.fx_rng.choice(colors),
                    "size": self.fx_rng.uniform(1.6, 3.6),
                }
            )
        for particle in self.particles:
            particle["max"] = particle["max"] or particle["life"]

    def _glow(self, color: Color, radius: int) -> pygame.Surface:
        key = (color, radius)
        if key not in self._glow_cache:
            size = radius * 2
            surface = pygame.Surface((size, size), pygame.SRCALPHA)
            steps = max(4, radius)
            for step in range(steps, 0, -1):
                alpha = int(88 * (1 - step / steps) ** 2)
                pygame.draw.circle(surface, (*color, alpha), (radius, radius), step)
            self._glow_cache[key] = surface
        return self._glow_cache[key]

    def _blit_glow(self, position: tuple[float, float], color: Color, radius: int) -> None:
        surface = self._glow(color, radius)
        self.screen.blit(surface, surface.get_rect(center=(round(position[0]), round(position[1]))))

    def _shake_offset(self) -> tuple[int, int]:
        if self.shake <= 0.2:
            return (0, 0)
        return (
            int(sin(self.time * 71) * self.shake),
            int(cos(self.time * 58) * self.shake),
        )

    # ----------------------------------------------------------------- input helpers

    def _node_at(self, position: tuple[int, int]) -> int | None:
        for node, map_position in self.engine.graph.positions.items():
            if pygame.Vector2(position).distance_to(map_position) < 23:
                return node
        return None

    def _buttons(self) -> tuple[Button, ...]:
        charges = self.engine.state.scan_charges
        return (
            Button("END TURN", pygame.Rect(965, 778, 130, 42), "turn"),
            Button("ACCUSE", pygame.Rect(1105, 778, 110, 42), "accuse"),
            Button(f"SCAN [{charges}]", pygame.Rect(1225, 778, 115, 42), "scan", enabled=charges > 0),
        )

    def _header_buttons(self) -> tuple[Button, ...]:
        return (
            Button("SOUND: ON" if not self.muted else "SOUND: OFF", pygame.Rect(1240, 30, 102, 26), "sound"),
            Button("NEW GAME", pygame.Rect(1240, 62, 102, 26), "reset"),
        )

    def _mode_chips(self) -> tuple[pygame.Rect, pygame.Rect]:
        return pygame.Rect(988, 162, 174, 32), pygame.Rect(1174, 162, 174, 32)

    def _outcome_buttons(self) -> tuple[Button, Button]:
        return (
            Button("PLAY AGAIN", pygame.Rect(475, 566, 220, 50), "again"),
            Button("MENU", pygame.Rect(715, 566, 220, 50), "menu"),
        )

    # ------------------------------------------------------------------ draw

    def _draw(self) -> None:
        self.screen.blit(self._backdrop, (0, 0))
        self._draw_stars()
        self._draw_ambient()
        if self.view == "MENU":
            self._draw_menu()
        elif self.view == "GAME":
            self._draw_game()
            if self.engine.state.status != "ACTIVE":
                self._record_best()
                self._change_view("OVER")
        else:
            self._draw_game(dim=True)
            self._draw_outcome()
        if self.view != "OVER" and self.fade > 0.01:
            self._fade_overlay.fill((2, 4, 12, int(self.fade * 255)))
            self.screen.blit(self._fade_overlay, (0, 0))
        self.screen.blit(self._vignette, (0, 0))

    def _draw_stars(self) -> None:
        for x, y, radius in self.stars:
            if y > self.HEIGHT - 170:
                continue
            brightness = 70 + int(70 * (sin(self.time * 1.7 + x * 0.05) + 1) / 2)
            pygame.draw.circle(
                self.screen,
                (brightness, brightness, min(255, brightness + 40)),
                (x, y),
                radius,
            )

    def _draw_ambient(self) -> None:
        for ember in self.embers:
            x = ember["x"] + sin(self.time * ember["sway"] + ember["phase"]) * 14
            twinkle = 0.45 + 0.55 * (sin(self.time * 2.4 + ember["phase"]) + 1) / 2
            # Glow keyed on the ember's fixed base colour so the cache stays bounded.
            self._blit_glow((x, ember["y"]), ember["color"], int(ember["size"] * 4))
            pygame.draw.circle(
                self.screen,
                _scale(ember["color"], twinkle),
                (round(x), round(ember["y"])),
                max(1, round(ember["size"])),
            )

    def _panel(
        self,
        rect: pygame.Rect,
        color: Color = PANEL,
        border: Color | None = None,
        radius: int = 18,
        brackets: bool = False,
    ) -> None:
        # Drop shadow for depth.
        pygame.draw.rect(self.screen, (3, 5, 14), rect.move(0, 5), border_radius=radius)
        # Base fill.
        pygame.draw.rect(self.screen, color, rect, border_radius=radius)
        # Glossy top highlight (rounded on top corners only).
        gloss_h = max(8, int(rect.height * 0.42))
        pygame.draw.rect(
            self.screen,
            _scale(color, 1.32),
            pygame.Rect(rect.x, rect.y, rect.width, gloss_h),
            border_top_left_radius=radius,
            border_top_right_radius=radius,
        )
        # Re-lay the body below the gloss so it fades to the darker base.
        pygame.draw.rect(
            self.screen,
            color,
            pygame.Rect(rect.x, rect.y + gloss_h, rect.width, rect.height - gloss_h),
            border_bottom_left_radius=radius,
            border_bottom_right_radius=radius,
        )
        if border:
            pygame.draw.rect(self.screen, border, rect, width=2, border_radius=radius)
            if brackets:
                self._corner_brackets(rect, border)

    def _corner_brackets(self, rect: pygame.Rect, color: Color, size: int = 16) -> None:
        inset = 6
        corners = (
            ((rect.left + inset, rect.top + inset), (1, 1)),
            ((rect.right - inset, rect.top + inset), (-1, 1)),
            ((rect.left + inset, rect.bottom - inset), (1, -1)),
            ((rect.right - inset, rect.bottom - inset), (-1, -1)),
        )
        for (cx, cy), (dx, dy) in corners:
            pygame.draw.line(self.screen, color, (cx, cy), (cx + dx * size, cy), 3)
            pygame.draw.line(self.screen, color, (cx, cy), (cx, cy + dy * size), 3)

    def _glass_surface(self, size: tuple[int, int], tint: Color, alpha: int, radius: int) -> pygame.Surface:
        """Cached translucent 'frosted glass' card: tint + top gloss, rounded."""
        key = ("glass", size, tint, alpha, radius)
        if key not in self._glow_cache:
            width, height = size
            surf = pygame.Surface(size, pygame.SRCALPHA)
            pygame.draw.rect(surf, (*tint, alpha), surf.get_rect(), border_radius=radius)
            # Diagonal sheen band across the upper third.
            gloss = pygame.Surface(size, pygame.SRCALPHA)
            pygame.draw.rect(
                gloss, (255, 255, 255, 22),
                pygame.Rect(0, 0, width, int(height * 0.42)),
                border_top_left_radius=radius, border_top_right_radius=radius,
            )
            surf.blit(gloss, (0, 0))
            # Faint inner top hairline for the glass edge.
            pygame.draw.line(surf, (255, 255, 255, 40), (radius, 2), (width - radius, 2), 1)
            self._glow_cache[key] = surf
        return self._glow_cache[key]

    def _glass_panel(
        self,
        rect: pygame.Rect,
        tint: Color = (26, 40, 78),
        border: Color = (150, 180, 240),
        radius: int = 20,
        alpha: int = 168,
        accent: Color | None = None,
    ) -> None:
        # Soft drop shadow.
        shadow = self._glass_surface((rect.width + 16, rect.height + 16), (0, 0, 0), 90, radius + 4)
        self.screen.blit(shadow, (rect.x - 8, rect.y - 2))
        # Opaque body (kept solid so nothing bleeds through and text stays crisp).
        self.screen.blit(self._glass_surface((rect.width, rect.height), tint, 255, radius), rect.topleft)
        # Hairline light border.
        pygame.draw.rect(self.screen, border, rect, width=1, border_radius=radius)
        # A slim accent strip along the top for a modern app-card feel.
        if accent:
            pygame.draw.line(self.screen, accent, (rect.x + radius, rect.y + 1), (rect.right - radius, rect.y + 1), 2)

    def _iso_node(self, center: tuple[float, float], radius: int, top: Color, ring: Color, height: int = 7) -> None:
        """A little extruded 3D chip: shadow, side wall, glossy top face."""
        cx, cy = round(center[0]), round(center[1])
        # Contact shadow.
        shadow = self._glass_surface((radius * 3, radius), (0, 0, 0), 90, radius)
        self.screen.blit(shadow, shadow.get_rect(center=(cx, cy + height + 4)))
        # Side wall (extrusion).
        pygame.draw.circle(self.screen, _scale(top, 0.45), (cx, cy + height), radius)
        pygame.draw.rect(self.screen, _scale(top, 0.45), pygame.Rect(cx - radius, cy, radius * 2, height))
        # Top face.
        pygame.draw.circle(self.screen, top, (cx, cy), radius)
        pygame.draw.circle(self.screen, _scale(top, 1.4), (cx - radius // 3, cy - radius // 3), max(2, radius // 3))
        pygame.draw.circle(self.screen, ring, (cx, cy), radius, width=2)

    def _text(self, value: str, position: tuple[int, int], style: str = "body", color: Color = TEXT, anchor: str = "topleft") -> pygame.Rect:
        surface = self.fonts[style].render(value, True, color)
        rect = surface.get_rect()
        setattr(rect, anchor, position)
        self.screen.blit(surface, rect)
        return rect

    def _multiline(self, value: str, x: int, y: int, width: int, style: str, color: Color) -> None:
        words = value.split()
        line = ""
        line_height = self.fonts[style].get_linesize()
        for word in words:
            candidate = f"{line} {word}".strip()
            if self.fonts[style].size(candidate)[0] > width and line:
                self._text(line, (x, y), style, color)
                y += line_height
                line = word
            else:
                line = candidate
        if line:
            self._text(line, (x, y), style, color)

    def _draw_button(self, button: Button, active: bool = False, border_color: Color | None = None) -> None:
        hovered = button.enabled and button.rect.collidepoint(pygame.mouse.get_pos())
        rect = button.rect.inflate(6, 6) if (hovered and button.enabled) else button.rect
        if active:
            fill = (34, 118, 150) if hovered else (26, 100, 128)
        elif not button.enabled:
            fill = (30, 38, 60)
        else:
            fill = (52, 72, 118) if hovered else (40, 56, 94)
        border = border_color or (CYAN if active or hovered else (96, 122, 170))
        if hovered and button.enabled:
            self._blit_glow(rect.center, border, 34)
        self._panel(rect, fill, border, radius=13)
        label_color = TEXT if button.enabled else (95, 110, 140)
        self._text(button.label, rect.center, "small", label_color, "center")

    # ------------------------------------------------------------------ menu

    def _menu_click(self, position: tuple[int, int]) -> None:
        for index, rect in enumerate(getattr(self, "menu_rects_behaviour", [])):
            if rect.collidepoint(position):
                self.menu_policy = GHOST_POLICIES[index]
                self._play("click")
                return
        for index, rect in enumerate(getattr(self, "menu_rects_difficulty", [])):
            if rect.collidepoint(position):
                self.menu_difficulty = DIFFICULTIES[index]
                self._play("click")
                return
        for index, rect in enumerate(getattr(self, "menu_rects_mode", [])):
            if rect.collidepoint(position):
                self.menu_manual = index == 1
                self._play("click")
                return
        if pygame.Rect(540, 612, 320, 58).collidepoint(position):
            self._start_game()

    def _draw_menu(self) -> None:
        self._blit_glow((700, 430), (40, 40, 90), 130)
        panel = pygame.Rect(360, 40, 680, 784)
        self._glass_panel(panel, (20, 30, 64), (140, 170, 235), radius=26, accent=CYAN)
        cx = panel.centerx

        # --- Title block ---
        pulse = 0.82 + 0.18 * sin(self.time * 2.2)
        self._blit_glow((cx, 108), CYAN, 82)
        self._text("SHADOW CHASE", (cx, 106), "hero", _scale(CYAN, pulse), "center")
        self._text("A GHOST-HUNT MYSTERY", (cx, 172), "heading", GOLD, "center")

        # --- Animated chase strip ---
        chase_y = 214
        progress = (self.time * 0.35) % 1.0
        hunter_x = _lerp(cx - 210, cx + 210, progress)
        ghost_x = _lerp(cx - 210, cx + 210, min(1.0, progress + 0.18))
        pygame.draw.line(self.screen, (34, 52, 88), (cx - 220, chase_y), (cx + 220, chase_y), 3)
        if (self.time * 0.9) % 1.6 > 0.7:
            self._blit_glow((ghost_x, chase_y), PURPLE, 22)
            pygame.draw.circle(self.screen, PURPLE, (round(ghost_x), chase_y), 8)
        else:
            self._text("?", (ghost_x, chase_y - 8), "heading", PURPLE, "center")
        self._blit_glow((hunter_x, chase_y), GREEN, 20)
        pygame.draw.circle(self.screen, GREEN, (round(hunter_x), chase_y), 7)
        self._text("HUNTER", (cx - 220, chase_y + 14), "small", GREEN, "topleft")
        self._text("GHOST", (cx + 220, chase_y + 14), "small", PURPLE, "topright")

        mouse = pygame.mouse.get_pos()

        def selector(label: str, y: int, options, selected_value, accent: Color, tags):
            self._text(label, (cx, y), "label", GOLD, "center")
            chip_w, gap = 190, 14
            total = len(options) * chip_w + (len(options) - 1) * gap
            start_x = cx - total // 2
            rects = []
            for i, opt in enumerate(options):
                rect = pygame.Rect(start_x + i * (chip_w + gap), y + 24, chip_w, 44)
                rects.append(rect)
                selected = opt == selected_value
                hovered = rect.collidepoint(mouse)
                fill = (34, 66, 90) if selected else PANEL_ALT
                border = accent if selected else ((78, 104, 152) if hovered else (58, 78, 120))
                self._panel(rect, fill, border, radius=11)
                self._text(tags[i], rect.center, "small", TEXT if selected else MUTED, "center")
            return rects

        # --- Ghost behaviour ---
        self.menu_rects_behaviour = selector(
            "GHOST BEHAVIOUR", 268, GHOST_POLICIES, self.menu_policy, CYAN,
            [f"{i + 1}  {p}" for i, p in enumerate(GHOST_POLICIES)],
        )
        self._text(GHOST_POLICY_HELP[self.menu_policy], (cx, 344), "small", MUTED, "center")

        # --- Difficulty ---
        self.menu_rects_difficulty = selector(
            "DIFFICULTY", 384, DIFFICULTIES, self.menu_difficulty, GOLD,
            [f"{i + 4}  {d}" for i, d in enumerate(DIFFICULTIES)],
        )
        self._text(DIFFICULTY_HELP[self.menu_difficulty], (cx, 460), "small", MUTED, "center")

        # --- Control mode ---
        self.menu_rects_mode = selector(
            "CONTROL MODE", 500, (False, True), self.menu_manual, GREEN, ["AI AUTO", "PLAYER"],
        )
        mode_help = (
            "Watch the full AI pipeline drive the hunt every round."
            if not self.menu_manual
            else "You pick the Hunter's target; the AI still advises."
        )
        self._text(mode_help, (cx, 576), "small", MUTED, "center")

        # --- Start + footer ---
        self._draw_button(Button("START THE HUNT", pygame.Rect(cx - 160, 612, 320, 58), "start"), active=True)
        best_parts = []
        for difficulty in DIFFICULTIES:
            entry = self.best.get(difficulty)
            best_parts.append(f"{difficulty} {entry['score']} ({entry['rank']})" if entry else f"{difficulty} —")
        self._text("BEST   " + "    ".join(best_parts), (cx, 696), "small", GOLD, "center")
        timer_state = "ON" if self.timer_enabled else "OFF"
        self._text(f"1/2/3 behaviour   4/5/6 difficulty   M control   T timer: {timer_state}", (cx, 736), "small", MUTED, "center")
        self._text("Noisy clues • Belief states • Minimax / Expectimax • A*", (cx, 762), "small", DIM, "center")

    # ------------------------------------------------------------------ game

    def _draw_game(self, dim: bool = False) -> None:
        self._draw_header()
        self._draw_map()
        self._draw_ai_panel()
        self._draw_footer()
        if dim:
            self.screen.blit(self._dim_overlay, (0, 0))

    def _draw_header(self) -> None:
        self._glass_panel(pygame.Rect(28, 22, 1344, 78), (24, 38, 76), (120, 150, 210), accent=CYAN)
        self._text("SHADOW CHASE", (58, 46), "title", CYAN, "midleft")
        self._text("THE GHOST-HUNT  •  belief-driven AI pursuit", (60, 78), "small", MUTED)

        state = self.engine.state
        # Bounty coin badge.
        bounty = self.engine.capture_value() if state.status == "ACTIVE" else state.score
        bounty_color = GOLD if state.status == "ACTIVE" else GREEN
        self._blit_glow((712, 60), bounty_color, 30)
        pygame.draw.circle(self.screen, _scale(bounty_color, 0.4), (712, 60), 21)
        pygame.draw.circle(self.screen, bounty_color, (712, 60), 21, width=2)
        self._text("$", (712, 58), "label", bounty_color, "center")
        self._text("BOUNTY", (742, 40), "small", MUTED)
        self._text(f"+{bounty}", (742, 56), "mono", bounty_color)

        self._text(f"ROUND {state.round_number:02} / {state.max_rounds:02}", (880, 28), "heading", TEXT)
        pip_width, pip_gap = 17, 4
        for index in range(state.max_rounds):
            rect = pygame.Rect(880 + index * (pip_width + pip_gap), 54, pip_width, 10)
            done = index < state.round_number - 1
            reveal = (index + 1) in self.engine.reveal_rounds
            if done:
                color = GOLD if reveal else CYAN
            else:
                color = (58, 48, 34) if reveal else (34, 48, 78)
            pygame.draw.rect(self.screen, color, rect, border_radius=4)
        if self.engine.is_reveal_round:
            reveal, reveal_color = "REVEAL ROUND", PURPLE
        elif state.spooked:
            reveal, reveal_color = "GHOST SPOOKED", PINK
        else:
            reveal, reveal_color = "GHOST HIDDEN", MUTED
        self._text(reveal, (880, 74), "small", reveal_color)
        if self.timer_enabled and state.status == "ACTIVE" and self.turn_deadline > 0:
            seconds = self._turn_seconds()
            remaining = max(0.0, self.turn_deadline - self.time)
            fraction = min(1.0, remaining / max(seconds, 1))
            pygame.draw.rect(self.screen, (30, 42, 68), pygame.Rect(880, 86, 240, 6), border_radius=3)
            fill_color = CYAN if fraction > 0.5 else (GOLD if fraction > 0.25 else RED)
            pygame.draw.rect(
                self.screen, fill_color, pygame.Rect(880, 86, max(3, int(240 * fraction)), 6), border_radius=3
            )
            self._text(f"auto in {int(remaining) + 1}s", (1130, 82), "small", MUTED)
        pulse_alpha = 110 + int(90 * sin(self.time * 5))
        pygame.draw.circle(
            self.screen,
            _scale(PURPLE, pulse_alpha / 200),
            (1104, 36),
            7,
        )
        for button in self._header_buttons():
            self._draw_button(button, border_color=(70, 96, 140))

    def _draw_map(self) -> None:
        offset_x, offset_y = self._shake_offset()
        self._glass_panel(pygame.Rect(28, 120, 910, 620), (16, 28, 60), (90, 130, 200), accent=CYAN, alpha=150)
        inner = pygame.Rect(28, 120, 910, 620)
        clip = self.screen.get_clip()
        self.screen.set_clip(inner.inflate(-4, -4))

        for gx in range(inner.left + 45, inner.right, 45):
            pygame.draw.line(self.screen, GRID, (gx, inner.top + 8), (gx, inner.bottom - 8))
        for gy in range(inner.top + 45, inner.bottom, 45):
            pygame.draw.line(self.screen, GRID, (inner.left + 8, gy), (inner.right - 8, gy))

        self._text("THE HAUNTED CITY", (54 + offset_x, 143 + offset_y), "heading", TEXT)
        hover_node = self._node_at(pygame.mouse.get_pos())
        graph = self.engine.graph
        state = self.engine.state
        if self.engine.manual_mode and state.status == "ACTIVE" and self.pending is None:
            if state.decision and state.player_target != state.decision.target:
                suggestion = f"AI suggests {graph.labels[state.decision.target]} — click a node to set YOUR target"
            else:
                suggestion = "click a node to set YOUR target"
            self._text(suggestion, (54 + offset_x, 170 + offset_y), "small", GOLD)
        else:
            self._text("weighted intersections • flowing line is the A* route", (54 + offset_x, 170 + offset_y), "small", MUTED)

        # District bands.
        districts = (("NORTH", 190), ("MIDTOWN", 295), ("CENTRAL", 405), ("OLD TOWN", 520), ("HARBOR", 635))
        for district, y in districts:
            self._text(district, (54 + offset_x, y + offset_y), "small", (104, 130, 177))

        # Belief heat halos.
        top = self.engine.belief.top(10)
        max_probability = top[0][1] if top else 1.0
        for node, probability in top:
            if probability < 0.02 or probability < max_probability * 0.06:
                continue
            strength = probability / max(max_probability, 0.01)
            radius = int(24 + 30 * strength)
            position = (graph.positions[node][0] + offset_x, graph.positions[node][1] + offset_y)
            self._blit_glow(position, _scale(PURPLE, 0.8), radius)

        # Roads as raised ribbons: a dark underside plus a bright top edge.
        route = state.path.path if state.path else []
        route_edges = {frozenset((route[i], route[i + 1])) for i in range(len(route) - 1)}
        for node, neighbors in graph.adjacency.items():
            for neighbor, _ in neighbors.items():
                if node >= neighbor:
                    continue
                first = pygame.Vector2(graph.positions[node]) + (offset_x, offset_y)
                second = pygame.Vector2(graph.positions[neighbor]) + (offset_x, offset_y)
                on_route = frozenset((node, neighbor)) in route_edges
                # Underside (shadow) gives the road a sense of thickness.
                pygame.draw.line(self.screen, (7, 12, 26), first + (0, 4), second + (0, 4), 8 if on_route else 5)
                if on_route:
                    pygame.draw.line(self.screen, (18, 96, 128), first, second, 7)
                    self._flow_line(first, second, CYAN)
                else:
                    pygame.draw.line(self.screen, (52, 78, 122), first, second, 4)
                    pygame.draw.line(self.screen, (74, 104, 154), first + (0, -1), second + (0, -1), 1)

        # Sensor distance rings: the clue means "the Ghost is somewhere on this ring".
        if state.status == "ACTIVE":
            if state.clue:
                self._clue_ring(state.clue, offset_x, offset_y, exact=False)
            if state.scan_clue:
                self._clue_ring(state.scan_clue, offset_x, offset_y, exact=True)

        # Sensor stations.
        sensor_nodes = {sensor.node for sensor in graph.sensors}
        for sensor in graph.sensors:
            position = pygame.Vector2(graph.positions[sensor.node]) + (offset_x, offset_y)
            active = self.pending == "SCAN"
            ring_color = GOLD if active else (74, 104, 158)
            ring_radius = 19 + int(2.5 * sin(self.time * 3 + sensor.node))
            pygame.draw.circle(self.screen, ring_color, (round(position.x), round(position.y)), ring_radius, width=2)
            pygame.draw.circle(self.screen, GOLD if active else (90, 140, 200), (round(position.x), round(position.y)), 4)
            if active:
                self._blit_glow(position, GOLD, 30)

        # Route target ring.
        target = None
        if state.decision and state.status == "ACTIVE":
            target = state.player_target if self.engine.manual_mode and state.player_target is not None else state.decision.target
        if target is not None:
            position = pygame.Vector2(graph.positions[target]) + (offset_x, offset_y)
            color = GOLD if (self.engine.manual_mode and state.player_target == target) else (91, 225, 246)
            ring_radius = 24 + int(3.5 * sin(self.time * 4))
            pygame.draw.circle(self.screen, color, (round(position.x), round(position.y)), ring_radius, width=2)
            pygame.draw.circle(self.screen, color, (round(position.x), round(position.y)), ring_radius + 5, width=1)

        # Intersections as little extruded 3D chips.
        for node, (x, y) in graph.positions.items():
            position = (x + offset_x, y + offset_y)
            in_route = node in route
            if node == hover_node and state.status == "ACTIVE":
                top, ring = (44, 66, 108), GOLD
            elif in_route:
                top, ring = (26, 74, 96), CYAN
            else:
                top, ring = (24, 40, 74), (74, 104, 158)
            self._iso_node(position, 14, top, ring)
            self._text(graph.labels[node], (position[0], position[1] + 30), "small", CYAN if in_route else MUTED, "center")

        # Particles and sensor pings.
        for particle in self.particles:
            alpha = max(0.0, particle["life"] / particle["max"])
            position = particle["pos"] + (offset_x, offset_y)
            color = _scale(particle["color"], 0.25 + 0.75 * alpha)
            pygame.draw.circle(self.screen, color, (round(position.x), round(position.y)), max(1, round(particle["size"] * alpha + 0.6)))
        for ping in self.pings:
            position = ping["pos"] + (offset_x, offset_y)
            alpha = (1 - ping["t"]) ** 1.4
            for share in (1.0, 0.55):
                radius = int((18 + ping["t"] * 54) * share)
                pygame.draw.circle(
                    self.screen,
                    _scale(ping["color"], 0.25 + 0.75 * alpha),
                    (round(position.x), round(position.y)),
                    radius,
                    width=2,
                )

        self._draw_hunter(offset_x, offset_y)
        if self.engine.is_reveal_round:
            self._draw_ghost(offset_x, offset_y)
        elif self.time < self.sighting_until and self.engine.state.status == "ACTIVE":
            self._draw_ghost(offset_x, offset_y)
            banner = "GHOST SIGHTED!  it will not stay visible..."
            surface = self.fonts["heading"].render(banner, True, PURPLE)
            pill = surface.get_rect(center=(483 + offset_x, 712 + offset_y)).inflate(24, 10)
            pygame.draw.rect(self.screen, (12, 20, 42), pill, border_radius=12)
            pygame.draw.rect(self.screen, PURPLE, pill, width=1, border_radius=12)
            self.screen.blit(surface, surface.get_rect(center=pill.center))

        if self.pending in ("ACCUSE", "SCAN"):
            banner = (
                "ACCUSATION MODE: click the node where you think the Ghost hides"
                if self.pending == "ACCUSE"
                else "DEEP SCAN: click a gold sensor ring for an exact distance reading"
            )
            color = PINK if self.pending == "ACCUSE" else GOLD
            surface = self.fonts["heading"].render(banner, True, color)
            pill = surface.get_rect(center=(483 + offset_x, 712 + offset_y)).inflate(24, 10)
            pygame.draw.rect(self.screen, (12, 20, 42), pill, border_radius=12)
            pygame.draw.rect(self.screen, color, pill, width=1, border_radius=12)
            self.screen.blit(surface, surface.get_rect(center=pill.center))

        self.screen.set_clip(clip)
        self._draw_tooltip(hover_node)

    def _clue_ring(self, clue, offset_x: int, offset_y: int, exact: bool) -> None:
        """Draw the distance ring a sensor clue implies around its station."""
        graph = self.engine.graph
        center = pygame.Vector2(graph.positions[clue.sensor.node]) + (offset_x, offset_y)
        radius = int(clue.estimated_distance * 78)
        color = CLUE_COLORS[clue.strength]
        if exact:
            pygame.draw.circle(self.screen, color, (round(center.x), round(center.y)), radius, 2)
        else:
            pygame.draw.circle(self.screen, _scale(color, 0.6), (round(center.x), round(center.y)), radius, 2)
            pygame.draw.circle(self.screen, _scale(color, 0.25), (round(center.x), round(center.y)), radius + 12, 1)
            pygame.draw.circle(self.screen, _scale(color, 0.25), (round(center.x), round(center.y)), max(12, radius - 12), 1)
        label = ("EXACT" if exact else clue.strength) + f" ≈ {clue.estimated_distance:.0f}"
        if exact:
            # Place the scan label below the ring so it can't collide with the
            # noisy-clue label that sits above its own ring.
            label_y = min(724, round(center.y + radius + 6))
        else:
            label_y = max(192, round(center.y - radius - 8))
        self._text(label, (round(center.x), label_y), "small", color, "center")

    def _flow_line(self, start: pygame.Vector2, end: pygame.Vector2, color: Color) -> None:
        distance = start.distance_to(end)
        if distance < 1:
            return
        direction = (end - start) / distance
        dash, gap = 11, 15
        period = dash + gap
        offset = (self.time * 62) % period
        travelled = offset
        while travelled < distance:
            a = start + direction * travelled
            b = start + direction * min(travelled + dash, distance)
            pygame.draw.line(self.screen, color, a, b, 3)
            travelled += period

    def _draw_hunter(self, offset_x: int, offset_y: int) -> None:
        graph = self.engine.graph
        if self.hunter_anim:
            t = _ease(min(1.0, self.hunter_anim["t"]))
            position = self.hunter_anim["from"].lerp(self.hunter_anim["to"], t) + (offset_x, offset_y)
        else:
            position = pygame.Vector2(graph.positions[self.engine.state.hunter_node]) + (offset_x, offset_y)
        bob = sin(self.time * 4) * 1.5
        cx, cy = round(position.x), round(position.y + bob)
        self._blit_glow((cx, cy), GREEN, 32)
        # Detective badge: a shield-ish disc with a magnifier glint.
        pygame.draw.circle(self.screen, (16, 58, 40), (cx, cy), 18)
        pygame.draw.circle(self.screen, GREEN, (cx, cy), 18, width=3)
        pygame.draw.circle(self.screen, _scale(GREEN, 1.25), (cx - 5, cy - 6), 5)
        self._text("H", (cx, cy + 1), "node", (12, 30, 20), "center")

        route = self.engine.state.path.path if self.engine.state.path else []
        here = self.engine.state.hunter_node
        if here in route and route.index(here) + 1 < len(route) and self.engine.state.status == "ACTIVE":
            a = pygame.Vector2(graph.positions[route[route.index(here)]]) + (offset_x, offset_y)
            b = pygame.Vector2(graph.positions[route[route.index(here) + 1]]) + (offset_x, offset_y)
            direction = (b - a)
            length = direction.length()
            if length > 1:
                direction = direction / length
                angle = atan2(direction.y, direction.x)
                for stage in range(2):
                    progress = ((self.time * 1.1 + stage * 0.5) % 1.0)
                    base = a + direction * (14 + (length - 28) * progress)
                    tip = base + direction * 9
                    left = base + direction.rotate(130) * 6
                    right = base + direction.rotate(-130) * 6
                    pygame.draw.polygon(self.screen, CYAN, [tip, left, right])

    def _draw_ghost(self, offset_x: int, offset_y: int) -> None:
        position = pygame.Vector2(self.engine.graph.positions[self.engine.state.ghost_node]) + (offset_x, offset_y)
        bob = sin(self.time * 3.2) * 2.5
        x, y = round(position.x), round(position.y + bob)
        self._blit_glow((x, y), PURPLE, 36)
        # Rounded ghostly body with a wavy skirt.
        pygame.draw.circle(self.screen, (238, 214, 255), (x, y - 4), 13)
        pygame.draw.rect(self.screen, (238, 214, 255), (x - 13, y - 4, 26, 13))
        skirt_phase = self.time * 6
        for i, wave_x in enumerate((x - 9, x, x + 9)):
            wobble = int(2 * sin(skirt_phase + i))
            pygame.draw.circle(self.screen, (238, 214, 255), (wave_x, y + 9 + wobble), 5)
        # Eyes.
        pygame.draw.circle(self.screen, PURPLE, (x - 5, y - 6), 3)
        pygame.draw.circle(self.screen, PURPLE, (x + 5, y - 6), 3)

    def _draw_tooltip(self, hover_node: int | None) -> None:
        if hover_node is None or self.engine.state.status != "ACTIVE":
            return
        graph = self.engine.graph
        lines = [f"{graph.labels[hover_node]} • {graph.districts[hover_node]}"]
        probability = self.engine.belief.probabilities.get(hover_node, 0.0)
        lines.append(f"belief {probability * 100:4.1f}%")
        sensor = next((s for s in graph.sensors if s.node == hover_node), None)
        if sensor:
            lines.append(f"sensor: {sensor.name}")
        if self.engine.state.decision and hover_node == self.engine.state.decision.target:
            lines.append("AI target")
        if self.engine.manual_mode and hover_node == self.engine.state.player_target:
            lines.append("your target")
        mouse = pygame.mouse.get_pos()
        width = max(self.fonts["small"].size(line)[0] for line in lines) + 22
        height = len(lines) * 18 + 12
        rect = pygame.Rect(mouse[0] + 16, mouse[1] + 14, width, height)
        rect.clamp_ip(pygame.Rect(0, 0, self.WIDTH, self.HEIGHT))
        self._panel(rect, (10, 18, 38), CYAN)
        for index, line in enumerate(lines):
            self._text(line, (rect.x + 11, rect.y + 7 + index * 18), "small", TEXT)

    # ------------------------------------------------------------- right panel

    def _draw_ai_panel(self) -> None:
        engine = self.engine
        state = engine.state
        graph = engine.graph
        self._glass_panel(pygame.Rect(962, 120, 410, 620), (30, 24, 62), (150, 120, 210), accent=PURPLE, alpha=160)
        self._text("THE DETECTIVE'S DESK", (988, 130), "heading", PURPLE)

        auto_chip, player_chip = self._mode_chips()
        for rect, label, selected in ((auto_chip, "AI AUTO", not engine.manual_mode), (player_chip, "PLAYER", engine.manual_mode)):
            fill = (30, 62, 84) if selected else PANEL_ALT
            border = GREEN if selected else (58, 78, 120)
            self._panel(rect, fill, border, radius=12)
            self._text(label, rect.center, "small", TEXT if selected else MUTED, "center")
        self._text("[M] switch", (1350, 138), "small", DIM, "topright")

        clue = state.clue
        self._panel(pygame.Rect(980, 204, 372, 96), PANEL_ALT, radius=14)
        self._text("LATEST WHISPER", (996, 214), "label", GOLD)
        self._text("sensor clue", (1338, 216), "small", DIM, "topright")
        if clue:
            color = CLUE_COLORS[clue.strength]
            self._text(f"{clue.strength} • {clue.sensor.name}", (996, 238), "heading", color)
            self._multiline(clue.message, 996, 264, 340, "small", TEXT)
        else:
            self._text("Awaiting the first Ghost movement...", (996, 244), "body", MUTED)
        if state.scan_clue:
            self._panel(pygame.Rect(980, 306, 372, 44), (34, 24, 52), PINK, radius=12)
            self._text("DEEP SCAN", (996, 314), "small", PINK)
            self._text(
                f"exact {state.scan_clue.estimated_distance:.0f} from {state.scan_clue.sensor.name}",
                (996, 331), "small", TEXT,
            )

        self._text("WHERE'S THE GHOST?", (988, 364), "label", GOLD)
        self._text("belief", (1338, 366), "small", DIM, "topright")
        top = engine.belief.top(6)
        max_probability = top[0][1] if top else 1.0
        for index, (node, probability) in enumerate(top):
            y = 390 + index * 27
            self._text(graph.labels[node], (988, y), "small", TEXT)
            bar_rect = pygame.Rect(1050, y + 3, 206, 12)
            pygame.draw.rect(self.screen, (36, 34, 60), bar_rect, border_radius=6)
            fraction = self.bar_cache.get(node, probability / max(max_probability, 0.01))
            fill_width = max(3, int(206 * min(1.0, fraction)))
            fill_rect = pygame.Rect(1050, y + 3, fill_width, 12)
            pygame.draw.rect(self.screen, CYAN if index == 0 else (108, 96, 190), fill_rect, border_radius=6)
            pygame.draw.rect(self.screen, _scale(CYAN if index == 0 else (108, 96, 190), 1.35), (1050, y + 3, min(6, fill_width), 12), border_radius=3)
            self._text(f"{probability * 100:4.1f}%", (1350, y), "mono_small", TEXT, "topright")

        self._panel(pygame.Rect(980, 556, 372, 116), PANEL_ALT, radius=14)
        self._text("THE HUNCH", (996, 566), "label", GOLD)
        self._text("target + A* route", (1338, 568), "small", DIM, "topright")
        if state.decision:
            ai_target = engine.graph.labels[state.decision.target]
            if state.target_source == "PLAYER":
                player_label = engine.graph.labels[state.player_target] if state.player_target is not None else "?"
                self._text(f"YOUR TARGET: {player_label}", (996, 590), "heading", GOLD)
                self._text(f"AI suggested {ai_target} (score {state.decision.score:.1f})", (996, 614), "small", MUTED)
            else:
                self._text(f"AI TARGET: {ai_target} • {engine.graph.districts[state.decision.target]}", (996, 590), "heading", GREEN)
                self._text(f"search depth {state.decision.depth} • score {state.decision.score:.1f}", (996, 614), "small", TEXT)
            self._text(f"evaluated {state.decision.evaluated_states}   pruned {state.decision.pruned_branches}", (996, 634), "mono_small", DIM)
            route = " → ".join(engine.graph.labels[node] for node in state.path.path) if state.path else ""
            self._multiline(route, 996, 652, 344, "mono_small", CYAN)
        else:
            self._text("Belief, adversarial target, and A*", (996, 594), "small", MUTED)
            self._text("route appear after the next turn.", (996, 612), "small", MUTED)

        self._text("CASE FILE", (988, 686), "label", GOLD)
        for index, entry in enumerate(state.history[:3]):
            self._text(entry, (988, 706 + index * 15), "mono_small", DIM)

    def _draw_footer(self) -> None:
        self._glass_panel(pygame.Rect(28, 760, 1344, 76), (24, 38, 76), (120, 150, 210), accent=CYAN)
        state = self.engine.state
        self._text(state.outcome_message, (55, 780), "body", TEXT)
        hints = "Enter: end turn   A: accuse   S: deep scan   M: control mode   T: turn timer   N: sound   R: new game   Esc: title"
        self._text(hints, (55, 808), "small", MUTED)
        for button in self._buttons():
            border = None
            if button.key == "accuse" and self.pending == "ACCUSE":
                border = PINK
            elif button.key == "scan" and self.pending == "SCAN":
                border = GOLD
            self._draw_button(button, button.key == "turn", border_color=border)

    # ----------------------------------------------------------------- outcome

    def _rank(self, score: int) -> str:
        for threshold, rank in RANKS:
            if score >= threshold:
                return rank
        return "F"

    def _draw_outcome(self) -> None:
        state = self.engine.state
        hunter_won = state.status == "HUNTER_WON"
        color = GREEN if hunter_won else PURPLE
        title = "HUNTER WINS" if hunter_won else "GHOST ESCAPED"
        self._blit_glow((700, 280), color, 120)
        self._glass_panel(pygame.Rect(410, 225, 580, 440), (20, 32, 62), _scale(color, 0.9), radius=24, alpha=180, accent=color)
        self._text(title, (700, 276), "hero", color, "center")
        score_line = f"SCORE {state.score}  •  RANK {self._rank(state.score)}"
        if self.new_record:
            score_line += "  •  NEW BEST!"
        self._text(score_line, (700, 330), "mono", GOLD, "center")
        self._draw_belief_chart(470, 378, 460, 72)
        self._multiline(state.outcome_message, 470, 460, 460, "body", TEXT)
        stats = [
            f"rounds survived: {min(state.round_number, state.max_rounds)} / {state.max_rounds}",
            f"deep scans remaining: {state.scan_charges}",
        ]
        if state.decision:
            stats.append(
                f"last AI target: {self.engine.graph.labels[state.decision.target]} • pruned {state.decision.pruned_branches}"
            )
        for index, line in enumerate(stats):
            self._text(line, (700, 500 + index * 21), "small", MUTED, "center")
        for index, button in enumerate(self._outcome_buttons()):
            self._draw_button(button, active=(index == 0))
        self._text("Enter: play again   Esc: menu", (700, 634), "small", MUTED, "center")

    def _draw_belief_chart(self, x: int, y: int, width: int, height: int) -> None:
        """Line chart: how much probability the AI put on the Ghost's true node."""
        trace = self.engine.state.belief_trace
        self._text("AI BELIEF ON THE TRUE GHOST NODE", (x + width // 2, y - 16), "small", GOLD, "center")
        pygame.draw.rect(self.screen, (12, 20, 40), pygame.Rect(x, y, width, height), border_radius=8)
        base_y = y + height
        pygame.draw.line(self.screen, (44, 62, 98), (x + 6, y + height // 2), (x + width - 6, y + height // 2), 1)
        if not trace:
            self._text("no rounds played", (x + width // 2, y + height // 2), "small", DIM, "center")
            return
        span = max(len(trace) - 1, 1)
        points = []
        for index, probability in enumerate(trace):
            point_x = x + 10 + (width - 20) * (index / span)
            point_y = base_y - 8 - (height - 16) * min(1.0, probability)
            points.append((point_x, point_y))
        if len(points) > 1:
            pygame.draw.lines(self.screen, CYAN, False, points, 2)
        for index, (point_x, point_y) in enumerate(points):
            reveal = (index + 1) in self.engine.reveal_rounds
            pygame.draw.circle(self.screen, GOLD if reveal else CYAN, (round(point_x), round(point_y)), 4)
