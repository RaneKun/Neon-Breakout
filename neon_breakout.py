"""
Neon Breakout
=============

A retro neon-themed brick breaker built with Python and Pygame.

Features 10 hand-tuned stages with escalating difficulty, a per-stage
time limit that triggers a difficulty spike, rare randomly-spawned
power-ups, unbreakable "wall" bricks that force patient play, multi-hit
bricks, particle effects, procedurally generated sound and music (no
external audio assets required), a full button-driven menu, a pause
system, persistent high scores and progress, and a resizable /
windowed-fullscreen-safe display that renders at a sharper internal
resolution the larger the window or monitor is.

Controls
--------
    Move paddle       Left/Right arrows or A/D, or move the mouse
    Launch ball        SPACE or Left Mouse Click
    Pause              P, ESC, or click the pause icon (top-left)
    Show/hide mouse    Ctrl or Alt (cursor auto-hides when a stage starts,
                       and auto-shows/hides on pause/unpause)
    Restart            R (on Game Over / Victory screen)
    Mute (quick)       M
    Quit               ESC (from main menu) or close window

Requirements
------------
    Python 3.9+, pygame, numpy
"""

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # must be set before `import pygame`

import json
import math
import random
import sys
import uuid

import numpy as np
import pygame
import pygame.gfxdraw

# --------------------------------------------------------------------------
# DEBUGGING CONFIGURATION
# --------------------------------------------------------------------------
DEBUG = True  # Set to False to disable console debug print statements


def log(msg):
    """Helper function to print debug messages only when DEBUG is enabled.
    Wrapped defensively: when launched as a .pyw (pythonw.exe), there is no
    console at all and sys.stdout/stderr can be None, which would otherwise
    make ANY print() call crash the game before a window ever appears."""
    if DEBUG:
        try:
            print(f"[DEBUG] {msg}")
        except Exception:
            pass


# --------------------------------------------------------------------------
# PERSISTENCE (config + high scores)
# Loaded before the window is created so the saved fullscreen preference
# applies on startup. Stored in the OS's per-user app data folder (not next
# to the script, which may not be writable once packaged).
# --------------------------------------------------------------------------
APP_NAME = "NeonBreakout"


def _app_data_dir():
    try:
        if sys.platform.startswith("win"):
            base = (
                os.environ.get("LOCALAPPDATA")
                or os.environ.get("APPDATA")
                or os.path.expanduser("~")
            )
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support")
        else:
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        path = os.path.join(base, APP_NAME)
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        return (
            os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
        )


BASE_DIR = _app_data_dir()
CONFIG_FILE = os.path.join(BASE_DIR, "neon_breakout_config.json")
HIGHSCORE_FILE = os.path.join(BASE_DIR, "neon_breakout_scores.json")
MAX_HIGHSCORES = 10

DEFAULT_CONFIG = {
    "max_stage_reached": 1,
    "game_completed": False,
    "bgm_on": True,
    "sfx_on": True,
    "fullscreen": False,
    # Remembered windowed (non-fullscreen) geometry so the player doesn't have
    # to re-drag/resize the window every launch. window_x/y stay None until
    # the player has actually moved the window at least once.
    "window_w": 1000,
    "window_h": 700,
    "window_x": None,
    "window_y": None,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        log(f"Failed to save config: {e}")


def load_highscores():
    try:
        with open(HIGHSCORE_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            cleaned = []
            for e in data:
                if isinstance(e, dict) and "score" in e and "stage" in e:
                    e.setdefault("endless", False)  # older saves predate this field
                    cleaned.append(e)
            cleaned.sort(key=lambda e: e["score"], reverse=True)
            return cleaned[:MAX_HIGHSCORES]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def save_highscore(score, stage, endless=False, run_id=None):
    """Append/update a score, keep the top MAX_HIGHSCORES, write to disk. Returns the
    updated list. When `run_id` is given, any existing entry for that same run is
    replaced rather than duplicated - this lets us persist the score continuously
    while a run is still in progress (see Game._autosave_tick) without spamming the
    high score list with one entry per autosave tick."""
    scores = load_highscores()
    if run_id is not None:
        scores = [e for e in scores if e.get("run_id") != run_id]
    entry = {"score": score, "stage": stage, "endless": endless}
    if run_id is not None:
        entry["run_id"] = run_id
    scores.append(entry)
    scores.sort(key=lambda e: e["score"], reverse=True)
    scores = scores[:MAX_HIGHSCORES]
    try:
        with open(HIGHSCORE_FILE, "w") as f:
            json.dump(scores, f, indent=2)
        log(f"High scores saved to {HIGHSCORE_FILE}")
    except OSError as e:
        log(f"Failed to save high scores: {e}")
    return scores


CONFIG = load_config()

# --------------------------------------------------------------------------
# WINDOWS DPI AWARENESS - must happen before pygame touches the display
# --------------------------------------------------------------------------
# On a display scaled above 100%, Windows otherwise treats this process as
# DPI-unaware and virtualizes the window - a borderless fullscreen window
# then reports the correct native size but doesn't actually fill the screen.
# Declaring DPI awareness up front makes Windows use real pixel dimensions.
if sys.platform.startswith("win"):
    try:
        import ctypes

        try:
            # Per-Monitor DPI aware (best - correct across multi-monitor setups
            # with different scaling per monitor). Needs Windows 8.1+.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            # Fall back to System DPI aware (Vista+) if Per-Monitor isn't available.
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception as e:
        log(f"Could not set Windows DPI awareness: {e}")

# --------------------------------------------------------------------------
# SETUP
# --------------------------------------------------------------------------
pygame.init()

SOUND_ENABLED = True
try:
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
except pygame.error:
    SOUND_ENABLED = False

SFX_ON = bool(CONFIG.get("sfx_on", True))
BGM_ON = bool(CONFIG.get("bgm_on", True))

# ---- Resolution ----------------------------------------------------------
# Everything draws onto a "logical" surface that's then scaled to fill the
# real window. DESIGN_W/H is the resolution every layout constant is authored
# for; WIDTH/HEIGHT is the current logical resolution and can grow (capped at
# MAX_LOGICAL_* for glow-rendering performance) so bigger windows render
# sharper instead of just stretching a fixed small image. For stability the
# resolution only changes at safe checkpoints (new stage / restart / stage
# select - see Game.load_stage), not on every resize event mid-stage.
DESIGN_W, DESIGN_H = 1000, 700
MAX_LOGICAL_W, MAX_LOGICAL_H = 1920, 1344
MIN_WINDOW_H = 640
MIN_WINDOW_W = round(MIN_WINDOW_H * DESIGN_W / DESIGN_H)  # keep the design aspect ratio

WIDTH, HEIGHT = DESIGN_W, DESIGN_H
SCALE = 1.0
PENDING_RESOLUTION = (WIDTH, HEIGHT)  # updated on resize/fullscreen; applied at the next checkpoint

screen = pygame.Surface((WIDTH, HEIGHT))  # everything is drawn onto this
window = None  # the real OS window - created by apply_fullscreen() below

# NOTE: an earlier version used pygame._sdl2.video.Window to reposition the window
# after a fullscreen switch. That experimental API caused hard native crashes (no
# traceback, uncatchable) when toggling fullscreen on some systems, so it's been
# removed - positioning now goes through the SDL_VIDEO_WINDOW_POS env var hint
# (see apply_fullscreen) using only the classic pygame.display.set_mode() call.


def _native_desktop_size():
    """Get the monitor's real desktop resolution."""
    try:
        sizes = pygame.display.get_desktop_sizes()
        if sizes:
            return sizes[0]
    except Exception as e:
        log(f"get_desktop_sizes() failed: {e}")
    try:
        info = pygame.display.Info()
        return (info.current_w, info.current_h)
    except Exception:
        return (1280, 720)


def _clamped_windowed_size():
    w = max(MIN_WINDOW_W, CONFIG.get("window_w") or DESIGN_W)
    h = max(MIN_WINDOW_H, CONFIG.get("window_h") or DESIGN_H)
    return w, h


def _set_window_pos_hint(x, y):
    """Set (or clear, if x/y is None) the SDL_VIDEO_WINDOW_POS env var that SDL consults
    when a window is (re)created, so the next pygame.display.set_mode() call places the
    window at a specific screen position instead of wherever the OS defaults to."""
    if x is None or y is None:
        os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
    else:
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{int(x)},{int(y)}"


def _clamped_saved_position(w, h):
    """Return the saved windowed-mode position clamped so it can never end up off-screen
    (e.g. if the game was last closed on a monitor that's no longer connected), or
    (None, None) if no position has been saved yet."""
    x, y = CONFIG.get("window_x"), CONFIG.get("window_y")
    if x is None or y is None:
        return None, None
    dw, dh = _native_desktop_size()
    x = min(max(0, x), max(0, dw - w))
    y = min(max(0, y), max(0, dh - h))
    return x, y


_last_fullscreen_toggle_time = 0.0
_FULLSCREEN_DEBOUNCE = 0.35  # seconds - ignores rapid repeat clicks that can race SDL mode changes
_suppress_resize_until = 0.0  # ignore VIDEORESIZE events for a moment after a fullscreen toggle


def set_cursor_locked(locked):
    """Hide+confine (locked=True) or show+free (locked=False) the OS cursor together.

    set_grab() physically confines the cursor to the window - without it, fast
    mouse movement during play can let the cursor slip past the window edge,
    which freezes pygame.mouse.get_pos() and makes the paddle stop responding."""
    pygame.mouse.set_visible(not locked)
    pygame.event.set_grab(locked)


def apply_fullscreen(on):
    """Switch between a resizable window (restored to its last size/position) and
    a borderless fullscreen window sized to the monitor's native resolution.

    NOTE: pygame._sdl2.video.Window was tried twice here (for the mode switch itself,
    then just for repositioning) and both times caused hard, uncatchable native crashes
    when toggling fullscreen on. The fix is to never touch it: fully tear down and
    recreate the display subsystem (display.quit() + .init()) before every switch, so
    set_mode() always creates a genuinely new window and SDL_VIDEO_WINDOW_POS is honored
    with no repositioning call needed. Every step below is wrapped so a failure can
    never leave `window` as None - it always ends in some valid state."""
    global window

    try:
        pygame.display.quit()
        pygame.display.init()

        if on:
            size = _native_desktop_size()
            _set_window_pos_hint(0, 0)
            window = pygame.display.set_mode(size, pygame.NOFRAME)
        else:
            w, h = _clamped_windowed_size()
            x, y = _clamped_saved_position(w, h)
            _set_window_pos_hint(x, y)  # clears the hint if no position was saved yet
            window = pygame.display.set_mode((w, h), pygame.RESIZABLE)

        pygame.display.set_caption("NEON BREAKOUT")
        try:
            pygame.display.set_icon(build_app_icon())  # display.init() drops the prior icon
        except Exception as e:
            log(f"Could not reset window icon after display re-init: {e}")
    except Exception as e:
        log(f"apply_fullscreen({on}) failed entirely ({e}); forcing a safe windowed fallback.")
        try:
            window = pygame.display.set_mode((DESIGN_W, DESIGN_H), pygame.RESIZABLE)
        except Exception as e2:
            log(f"Even the safe windowed fallback failed: {e2}")

    if window is not None:
        global PENDING_RESOLUTION, _suppress_resize_until
        PENDING_RESOLUTION = window.get_size()
        _suppress_resize_until = pygame.time.get_ticks() / 1000.0 + 0.5
        log(f"Fullscreen set to {on}. Window size: {window.get_size()}")


def toggle_fullscreen():
    global _last_fullscreen_toggle_time
    now = pygame.time.get_ticks() / 1000.0
    if now - _last_fullscreen_toggle_time < _FULLSCREEN_DEBOUNCE:
        log("Fullscreen toggle ignored (debounced - clicked too rapidly).")
        return
    _last_fullscreen_toggle_time = now
    CONFIG["fullscreen"] = not CONFIG["fullscreen"]
    apply_fullscreen(CONFIG["fullscreen"])
    save_config(CONFIG)


def build_app_icon(size=64):
    """Procedurally draw the neon-brick-breaker icon used for the window and
    taskbar, with zero external image files needed."""
    icon = pygame.Surface((size, size), pygame.SRCALPHA)
    icon.fill((8, 8, 18, 255))
    pygame.draw.rect(
        icon, (60, 240, 255), (size * 0.12, size * 0.66, size * 0.76, size * 0.12), border_radius=3
    )
    for cx, cy, col in [
        (0.28, 0.30, (255, 235, 60)),
        (0.5, 0.42, (255, 70, 230)),
        (0.72, 0.30, (80, 255, 140)),
    ]:
        pygame.draw.circle(icon, col, (int(size * cx), int(size * cy)), max(2, int(size * 0.09)))
    pygame.draw.circle(
        icon, (255, 235, 60), (int(size * 0.5), int(size * 0.85)), max(2, int(size * 0.07))
    )
    return icon


apply_fullscreen(CONFIG.get("fullscreen", False))
try:
    pygame.display.set_icon(build_app_icon())
except Exception as e:
    log(f"Could not set window icon: {e}")

clock = pygame.time.Clock()
FPS = 60


FONT_BIG = pygame.font.SysFont("consolas", 64, bold=True)
FONT_MED = pygame.font.SysFont("consolas", 34, bold=True)
FONT_SMALL = pygame.font.SysFont("consolas", 20, bold=True)
FONT_TINY = pygame.font.SysFont("consolas", 15)

# ---- Neon color palette -----------------------------------------------
BG_COLOR = (8, 8, 18)
BG_COLOR2 = (14, 10, 28)
GRID_LINE = (28, 22, 48)

CYAN = (60, 240, 255)
MAGENTA = (255, 70, 230)
YELLOW = (255, 235, 60)
GREEN = (80, 255, 140)
ORANGE = (255, 150, 50)
RED = (255, 70, 90)
PURPLE = (170, 90, 255)
BLUE = (80, 150, 255)
WHITE = (240, 240, 255)
GRAY = (120, 125, 140)

HP_COLORS = {1: CYAN, 2: YELLOW, 3: ORANGE, 4: RED}

POWERUP_INFO = {
    # key: (letter, color, rarity_weight) - weighted toward the "special" ones
    # now that powerups spawn randomly on a timer instead of falling from
    # nearly every broken brick (which is what made them feel too common).
    "widen": ("W", GREEN, 4),
    "multiball": ("M", MAGENTA, 6),
    "slow": ("S", BLUE, 5),
    "life": ("+", WHITE, 5),
    "shrink": ("-", RED, 4),
    "fast": ("F", ORANGE, 5),
}
POWERUP_KEYS = list(POWERUP_INFO.keys())
POWERUP_WEIGHTS = [POWERUP_INFO[k][2] for k in POWERUP_KEYS]
GOOD_POWERUPS = {"widen", "multiball", "life"}

# --------------------------------------------------------------------------
# SOUND ENGINE (procedurally synthesized - no external audio files needed)
# --------------------------------------------------------------------------
SAMPLE_RATE = 44100


def midi_to_freq(m):
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


def _tone_array(freq, duration, wave="square", volume=0.35, fade=True):
    n = max(1, int(SAMPLE_RATE * duration))
    t = np.linspace(0, duration, n, False)
    if wave == "square":
        data = np.sign(np.sin(2 * np.pi * freq * t))
    elif wave == "saw":
        data = 2 * (t * freq - np.floor(0.5 + t * freq))
    elif wave == "tri":
        data = 2 * np.abs(2 * (t * freq - np.floor(t * freq + 0.5))) - 1
    elif wave == "noise":
        data = np.random.uniform(-1, 1, n)
    else:
        data = np.sin(2 * np.pi * freq * t)
    if fade:
        fl = max(1, int(n * 0.25))
        data[-fl:] *= np.linspace(1, 0, fl)
    return data * volume


def _sweep_array(f_start, f_end, duration, wave="square", volume=0.35):
    n = max(1, int(SAMPLE_RATE * duration))
    t = np.linspace(0, duration, n, False)
    freq_t = np.linspace(f_start, f_end, n)
    phase = np.cumsum(2 * np.pi * freq_t / SAMPLE_RATE)
    data = np.sign(np.sin(phase)) if wave == "square" else np.sin(phase)
    fl = max(1, int(n * 0.3))
    data[-fl:] *= np.linspace(1, 0, fl)
    return data * volume


def _to_sound(data):
    audio = np.clip(data, -1, 1)
    audio = (audio * 32767).astype(np.int16)
    stereo = np.ascontiguousarray(np.column_stack([audio, audio]))
    return pygame.sndarray.make_sound(stereo)


def _arpeggio_sound(freqs, note_dur=0.09, wave="square", volume=0.3):
    parts = [_tone_array(f, note_dur, wave, volume) for f in freqs]
    return _to_sound(np.concatenate(parts))


def _build_sounds():
    return {
        "wall": _to_sound(_tone_array(220, 0.05, "square", 0.22)),
        "paddle": _to_sound(_tone_array(330, 0.06, "square", 0.28)),
        "corner_hit": _to_sound(_sweep_array(500, 950, 0.09, "square", 0.34)),
        "launch": _to_sound(_tone_array(600, 0.08, "square", 0.3)),
        "brick_hit": _to_sound(_tone_array(520, 0.05, "square", 0.22)),
        "brick_break": _to_sound(_sweep_array(700, 260, 0.12, "square", 0.3)),
        "powerup_good": _to_sound(_sweep_array(400, 950, 0.18, "square", 0.35)),
        "powerup_bad": _to_sound(_sweep_array(500, 180, 0.18, "square", 0.3)),
        "life_lost": _to_sound(_sweep_array(420, 110, 0.35, "saw", 0.35)),
        "ui_click": _to_sound(_tone_array(440, 0.05, "square", 0.22)),
        "stage_clear": _arpeggio_sound([523, 659, 784, 1047], 0.09, "square", 0.32),
        "victory": _arpeggio_sound([523, 659, 784, 1047, 1319], 0.12, "square", 0.34),
        "game_over": _to_sound(_sweep_array(320, 55, 0.6, "saw", 0.4)),
        "timeout": _to_sound(_sweep_array(200, 650, 0.4, "saw", 0.32)),
        "laser_charge": _to_sound(_sweep_array(180, 420, 0.5, "sine", 0.22)),
        "laser_fire": _to_sound(_sweep_array(900, 120, 0.22, "saw", 0.4)),
        "laser_hit": _to_sound(_sweep_array(500, 90, 0.4, "saw", 0.42)),
        "countdown_tick": _to_sound(_tone_array(660, 0.09, "square", 0.28)),
        "countdown_go": _arpeggio_sound([660, 988], 0.1, "square", 0.32),
    }


# ---- Generative background music ----------------------------------------
# ~2 minutes of "modern-retro" synthwave/chiptune style music: kick/hat/snare,
# a driving bassline, and an arpeggiated lead, structured into distinct
# sections (intro / verse / chorus / breakdown / bridge / finale / outro) so
# it keeps evolving instead of looping a short phrase every few seconds.
MUSIC_BPM = 128
STEP_DUR = 60.0 / MUSIC_BPM / 4.0  # length of one 16th note
BAR_DUR = STEP_DUR * 16

# Am - F - C - G chord progression (MIDI note numbers)
CHORDS = [
    [57, 60, 64],  # Am
    [53, 57, 60],  # F
    [60, 64, 67],  # C
    [55, 59, 62],  # G
]
ROOTS = [45, 41, 48, 43]  # bass roots (one octave below the chord root)

KICK_4ONFLOOR = [0, 4, 8, 12]
KICK_8TH = [0, 2, 4, 6, 8, 10, 12, 14]
KICK_HALFTIME = [0, 8]
HAT_OFFBEAT = [2, 6, 10, 14]
HAT_8TH = [0, 2, 4, 6, 8, 10, 12, 14]
HAT_SPARSE = [0, 8]
SNARE_BACKBEAT = [4, 12]
BASS_QUARTER = [0, 4, 8, 12]
BASS_SYNC = [0, 3, 6, 8, 11, 14]
BASS_EIGHTH = [0, 2, 4, 6, 8, 10, 12, 14]

VERSE_LEAD = [
    [(2, 0, 0), (6, 1, 0), (10, 2, 0), (14, 1, 0)],
    [(0, 0, 0), (4, 2, 0), (8, 1, 0), (12, 0, 12)],
    [(2, 1, 0), (6, 0, 0), (10, 2, 0), (14, 0, 0)],
    [(0, 2, 0), (4, 1, 0), (8, 0, 0), (12, 2, 0)],
]
CHORUS_LEAD = [
    [(0, 0, 0), (2, 1, 0), (4, 2, 0), (6, 1, 0), (8, 0, 12), (10, 1, 0), (12, 2, 0), (14, 1, 0)],
    [(0, 0, 0), (2, 2, 0), (4, 1, 0), (6, 0, 0), (8, 2, 12), (10, 0, 0), (12, 1, 0), (14, 2, 0)],
    [(0, 1, 0), (2, 0, 0), (4, 2, 0), (6, 0, 0), (8, 1, 12), (10, 2, 0), (12, 0, 0), (14, 1, 0)],
    [(0, 2, 0), (2, 1, 0), (4, 0, 0), (6, 2, 0), (8, 0, 12), (10, 1, 0), (12, 2, 0), (14, 0, 0)],
]
VERSEB_LEAD = [
    [(0, 0, 0), (3, 1, 0), (7, 2, 0), (11, 1, 0), (14, 0, 12)],
    [(0, 0, 0), (3, 2, 0), (7, 1, 0), (11, 0, 0), (14, 2, 12)],
    [(0, 1, 0), (3, 0, 0), (7, 2, 0), (11, 0, 0), (14, 1, 0)],
    [(0, 2, 0), (3, 1, 0), (7, 0, 0), (11, 2, 0), (14, 0, 12)],
]
BREAKDOWN_LEAD = [
    [(0, 0, 12), (4, 1, 12), (8, 2, 12), (12, 1, 12)],
    [(0, 0, 12), (4, 2, 12), (8, 1, 12), (12, 0, 24)],
    [(0, 1, 12), (4, 0, 12), (8, 2, 12), (12, 0, 12)],
    [(0, 2, 12), (4, 1, 12), (8, 0, 12), (12, 2, 12)],
]
CHORUSB_LEAD = [
    [(0, 0, 0), (2, 2, 0), (4, 1, 0), (6, 2, 0), (8, 0, 12), (10, 2, 0), (12, 1, 0), (14, 0, 12)],
    [(0, 1, 0), (2, 0, 0), (4, 2, 0), (6, 1, 0), (8, 2, 12), (10, 0, 0), (12, 2, 0), (14, 1, 0)],
    [(0, 2, 0), (2, 1, 0), (4, 0, 0), (6, 1, 0), (8, 1, 12), (10, 2, 0), (12, 0, 0), (14, 2, 0)],
    [(0, 0, 0), (2, 2, 0), (4, 0, 0), (6, 2, 0), (8, 1, 12), (10, 0, 0), (12, 1, 0), (14, 2, 0)],
]
BRIDGE_LEAD = [
    [(0, 0, 0), (8, 1, 0)],
    [(0, 0, 0), (8, 2, 0)],
    [(0, 1, 0), (8, 0, 0)],
    [(0, 2, 0), (8, 1, 12)],
]
FINALE_LEAD = [
    [(0, 0, 0), (2, 1, 0), (4, 2, 0), (6, 0, 12), (8, 1, 0), (10, 2, 0), (12, 0, 0), (14, 1, 12)],
    [(0, 0, 0), (2, 2, 0), (4, 1, 0), (6, 0, 12), (8, 2, 0), (10, 1, 0), (12, 0, 0), (14, 2, 12)],
    [(0, 1, 0), (2, 0, 0), (4, 2, 0), (6, 1, 12), (8, 0, 0), (10, 2, 0), (12, 1, 0), (14, 0, 12)],
    [(0, 2, 0), (2, 1, 0), (4, 0, 0), (6, 2, 12), (8, 1, 0), (10, 0, 0), (12, 2, 0), (14, 1, 12)],
]


def _note(freq, dur, wave="square", vol=0.16, attack=0.006, release=0.03):
    n = max(1, int(SAMPLE_RATE * dur))
    t = np.linspace(0, dur, n, False)
    if wave == "square":
        data = np.sign(np.sin(2 * np.pi * freq * t))
    elif wave == "saw":
        data = 2 * (t * freq - np.floor(0.5 + t * freq))
    elif wave == "tri":
        data = 2 * np.abs(2 * (t * freq - np.floor(t * freq + 0.5))) - 1
    else:
        data = np.sin(2 * np.pi * freq * t)
    a = min(n, max(1, int(n * attack / dur))) if dur > 0 else 1
    r = min(max(0, n - a), max(1, int(n * release / dur))) if dur > 0 else 0
    env = np.ones(n)
    env[:a] = np.linspace(0, 1, a)
    if r > 0:
        env[-r:] = np.linspace(1, 0, r)
    return data * env * vol


def _kick(vol=0.42, dur=0.16):
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, False)
    freq_env = np.linspace(150, 45, n)
    phase = np.cumsum(2 * np.pi * freq_env / SAMPLE_RATE)
    data = np.sin(phase)
    amp = np.exp(-t * 16)
    return data * amp * vol


def _hat(vol=0.12, dur=0.045):
    n = int(SAMPLE_RATE * dur)
    data = np.random.uniform(-1, 1, n)
    amp = np.exp(-np.linspace(0, 1, n) * 13)
    return data * amp * vol


def _snare(vol=0.24, dur=0.09):
    n = int(SAMPLE_RATE * dur)
    noise = np.random.uniform(-1, 1, n)
    amp = np.exp(-np.linspace(0, 1, n) * 10)
    tone = _note(190, dur, "tri", vol * 0.5)
    return noise * amp * vol * 0.7 + tone[:n]


def _mix_into(buf, start_sample, sound):
    if start_sample >= len(buf) or len(sound) == 0:
        return
    end = start_sample + len(sound)
    if end > len(buf):
        sound = sound[: len(buf) - start_sample]
        end = len(buf)
    buf[start_sample:end] += sound


def _make_section(
    bars,
    *,
    kick_steps=None,
    hat_steps=None,
    snare_steps=None,
    bass_steps=None,
    lead_notes=None,
    pad=False,
    lead_wave="square",
    bass_wave="square",
    lead_vol=0.14,
    bass_vol=0.15,
    pad_vol=0.045,
    kick_vol=0.4,
    hat_vol=0.11,
    snare_vol=0.22,
    lead_octave=0,
    chords=None,
    roots=None,
):
    chords = chords or CHORDS
    roots = roots or ROOTS
    total_samples = int(bars * BAR_DUR * SAMPLE_RATE)
    buf = np.zeros(total_samples + SAMPLE_RATE)  # small tail pad for envelope releases
    for bar_i in range(bars):
        chord = chords[bar_i % len(chords)]
        root = roots[bar_i % len(roots)]
        bar_start = int(bar_i * BAR_DUR * SAMPLE_RATE)
        if pad:
            chord_wave = sum(
                _note(midi_to_freq(t), BAR_DUR * 0.96, "sine", pad_vol, attack=0.25, release=0.5)
                for t in chord
            )
            _mix_into(buf, bar_start, chord_wave)
        if kick_steps:
            for step in kick_steps:
                _mix_into(buf, bar_start + int(step * STEP_DUR * SAMPLE_RATE), _kick(kick_vol))
        if snare_steps:
            for step in snare_steps:
                _mix_into(buf, bar_start + int(step * STEP_DUR * SAMPLE_RATE), _snare(snare_vol))
        if hat_steps:
            for step in hat_steps:
                _mix_into(buf, bar_start + int(step * STEP_DUR * SAMPLE_RATE), _hat(hat_vol))
        if bass_steps:
            freq = midi_to_freq(root)
            for step in bass_steps:
                _mix_into(
                    buf,
                    bar_start + int(step * STEP_DUR * SAMPLE_RATE),
                    _note(freq, STEP_DUR * 1.9, bass_wave, bass_vol, attack=0.004, release=0.05),
                )
        if lead_notes:
            pattern = (
                lead_notes[bar_i % len(lead_notes)]
                if isinstance(lead_notes[0], list)
                else lead_notes
            )
            for step, degree, extra in pattern:
                tone = chord[degree % len(chord)] + 12 * lead_octave + extra
                freq = midi_to_freq(tone)
                _mix_into(
                    buf,
                    bar_start + int(step * STEP_DUR * SAMPLE_RATE),
                    _note(freq, STEP_DUR * 1.4, lead_wave, lead_vol, attack=0.003, release=0.04),
                )
    return buf[:total_samples]


def _build_music_track():
    parts = [
        _make_section(
            4,
            pad=True,
            bass_steps=BASS_QUARTER,
            hat_steps=HAT_SPARSE,
            bass_vol=0.09,
            hat_vol=0.05,
            pad_vol=0.04,
        ),
        _make_section(
            8,
            kick_steps=KICK_4ONFLOOR,
            hat_steps=HAT_OFFBEAT,
            bass_steps=BASS_SYNC,
            lead_notes=VERSE_LEAD,
            pad=True,
            pad_vol=0.03,
            lead_vol=0.13,
            bass_vol=0.13,
            kick_vol=0.32,
            hat_vol=0.08,
        ),
        _make_section(
            8,
            kick_steps=KICK_8TH,
            hat_steps=HAT_8TH,
            snare_steps=SNARE_BACKBEAT,
            bass_steps=BASS_EIGHTH,
            lead_notes=CHORUS_LEAD,
            lead_vol=0.16,
            bass_vol=0.15,
            kick_vol=0.4,
            hat_vol=0.1,
            snare_vol=0.2,
        ),
        _make_section(
            8,
            kick_steps=KICK_4ONFLOOR,
            hat_steps=HAT_OFFBEAT,
            snare_steps=SNARE_BACKBEAT,
            bass_steps=BASS_SYNC,
            lead_notes=VERSEB_LEAD,
            pad=True,
            pad_vol=0.03,
            lead_vol=0.13,
            bass_vol=0.13,
            kick_vol=0.34,
            hat_vol=0.08,
            snare_vol=0.15,
        ),
        _make_section(
            8,
            hat_steps=HAT_SPARSE,
            lead_notes=BREAKDOWN_LEAD,
            pad=True,
            lead_wave="tri",
            pad_vol=0.05,
            lead_vol=0.15,
            hat_vol=0.05,
        ),
        _make_section(
            8,
            kick_steps=KICK_8TH,
            hat_steps=HAT_8TH,
            snare_steps=SNARE_BACKBEAT,
            bass_steps=BASS_EIGHTH,
            lead_notes=CHORUSB_LEAD,
            lead_vol=0.16,
            bass_vol=0.15,
            kick_vol=0.4,
            hat_vol=0.1,
            snare_vol=0.2,
        ),
        _make_section(
            8,
            kick_steps=KICK_HALFTIME,
            hat_steps=HAT_SPARSE,
            bass_steps=[0, 8],
            lead_notes=BRIDGE_LEAD,
            pad=True,
            lead_wave="tri",
            pad_vol=0.05,
            lead_vol=0.14,
            bass_vol=0.12,
            kick_vol=0.28,
            hat_vol=0.05,
            chords=[CHORDS[2], CHORDS[3], CHORDS[0], CHORDS[1]],
            roots=[ROOTS[2], ROOTS[3], ROOTS[0], ROOTS[1]],
        ),
        _make_section(
            8,
            kick_steps=KICK_8TH,
            hat_steps=HAT_8TH,
            snare_steps=SNARE_BACKBEAT,
            bass_steps=BASS_EIGHTH,
            lead_notes=FINALE_LEAD,
            lead_vol=0.18,
            bass_vol=0.16,
            kick_vol=0.44,
            hat_vol=0.11,
            snare_vol=0.22,
        ),
        _make_section(
            4,
            pad=True,
            bass_steps=BASS_QUARTER,
            hat_steps=HAT_SPARSE,
            bass_vol=0.08,
            hat_vol=0.04,
            pad_vol=0.035,
        ),
    ]
    track = np.concatenate(parts)
    return _to_sound(track)


SOUNDS = {}
MUSIC_CHANNEL = None
if SOUND_ENABLED:
    try:
        SOUNDS = _build_sounds()
        music_sound = _build_music_track()
        MUSIC_CHANNEL = music_sound.play(loops=-1)
        if MUSIC_CHANNEL:
            MUSIC_CHANNEL.set_volume(0.35 if BGM_ON else 0.0)
    except Exception as e:
        SOUND_ENABLED = False
        log(f"Sound engine failed to initialize: {e}")


def play_sound(name):
    if not SOUND_ENABLED or not SFX_ON:
        return
    snd = SOUNDS.get(name)
    if snd:
        snd.play()


def set_sfx(on):
    global SFX_ON
    SFX_ON = on
    CONFIG["sfx_on"] = on
    save_config(CONFIG)
    log(f"SFX set to {on}")


def set_bgm(on):
    global BGM_ON
    BGM_ON = on
    CONFIG["bgm_on"] = on
    if MUSIC_CHANNEL:
        MUSIC_CHANNEL.set_volume(0.35 if on else 0.0)
    save_config(CONFIG)
    log(f"BGM set to {on}")


def quick_toggle_mute():
    turn_on = not (SFX_ON or BGM_ON)
    set_sfx(turn_on)
    set_bgm(turn_on)


def present(shake_offset=(0, 0)):
    """Scale the fixed logical `screen` surface to whatever size the real window is
    (resizable window or borderless fullscreen) and flip it. This is what lets the
    game be freely resized or full-screened without any drawing code needing to change."""
    win_w, win_h = window.get_size()
    if win_w <= 0 or win_h <= 0:
        return  # window is mid-transition (e.g. toggling fullscreen) - skip this frame
    window.fill((0, 0, 0))
    scaled = pygame.transform.smoothscale(screen, (win_w, win_h))
    window.blit(scaled, shake_offset)
    pygame.display.flip()


# --------------------------------------------------------------------------
# GLOW HELPERS
# --------------------------------------------------------------------------


def draw_aa_circle(surface, color, pos, radius):
    """Anti-aliased filled circle. Plain pygame.draw.circle has a hard, jagged (aliased)
    edge - barely visible at small logical sizes, but once the logical `screen` surface
    gets smoothscaled up to fill a large window/monitor (see present()), those jagged
    edges get magnified right along with everything else and look noticeably rough.
    pygame.gfxdraw's filled_circle + aacircle combo draws a filled circle with a smooth,
    anti-aliased outline instead, which reads much cleaner once scaled up. Works fine on
    surfaces with per-pixel alpha (SRCALPHA), which most of the callers here use."""
    x, y = int(round(pos[0])), int(round(pos[1]))
    r = max(1, int(round(radius)))
    pygame.gfxdraw.filled_circle(surface, x, y, r, color)
    pygame.gfxdraw.aacircle(surface, x, y, r, color)


def draw_glow_rect(surface, rect, color, layers=5, expand=3, base_alpha=55, radius=5):
    """Cheap soft-glow effect for rectangles (paddle, bricks)."""
    pad = layers * expand
    glow = pygame.Surface((rect.width + pad * 2, rect.height + pad * 2), pygame.SRCALPHA)
    cx, cy = glow.get_width() // 2, glow.get_height() // 2
    for i in range(layers, 0, -1):
        alpha = int(base_alpha * (i / layers))
        w = rect.width + i * expand * 2
        h = rect.height + i * expand * 2
        r = pygame.Rect(0, 0, w, h)
        r.center = (cx, cy)
        pygame.draw.rect(glow, (*color, alpha), r, border_radius=radius + i)
    surface.blit(glow, (rect.centerx - cx, rect.centery - cy))
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    inner = rect.inflate(-rect.width * 0.5, -rect.height * 0.5)
    if inner.width > 2 and inner.height > 2:
        pygame.draw.rect(surface, (255, 255, 255), inner, border_radius=2)


def draw_glow_circle(surface, pos, radius, color, layers=4, expand=3, base_alpha=70):
    pad = layers * expand
    size = int((radius + pad) * 2)
    glow = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size // 2
    for i in range(layers, 0, -1):
        alpha = int(base_alpha * (i / layers))
        draw_aa_circle(glow, (*color, alpha), (c, c), radius + i * expand)
    surface.blit(glow, (pos[0] - c, pos[1] - c))
    draw_aa_circle(surface, color, pos, radius)
    draw_aa_circle(surface, WHITE, pos, max(1, radius - 3))


def draw_text_center(surface, text, font, color, center, glow=None):
    if glow:
        glow_surf = font.render(text, True, glow)
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            r = glow_surf.get_rect(center=(center[0] + dx, center[1] + dy))
            surface.blit(glow_surf, r)
    surf = font.render(text, True, color)
    rect = surf.get_rect(center=center)
    surface.blit(surf, rect)


def _heartbeat_pulse(t):
    """0..1 intensity tracing a two-beat 'lub-dub' heartbeat rhythm on a ~1s cycle."""
    cycle = t % 1.0

    def bump(center, width):
        d = abs(cycle - center)
        return max(0.0, 1.0 - d / width)

    return min(1.0, max(bump(0.05, 0.09), bump(0.28, 0.09) * 0.7))


def heartbeat_color(t, dim=(90, 20, 25), bright=(255, 90, 100)):
    """Lerp between a dim and bright red following _heartbeat_pulse - used to make the
    LIVES label blink like a heartbeat monitor when the player is down to their last chance."""
    k = _heartbeat_pulse(t)
    return tuple(int(dim[i] + (bright[i] - dim[i]) * k) for i in range(3))


# --------------------------------------------------------------------------
# UI BUTTONS (used by the menu, pause screen, high scores, and stage select)
# --------------------------------------------------------------------------
class Button:
    def __init__(self, rect, label, enabled=True):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.enabled = enabled

    def draw(self, surface, font=FONT_SMALL, hover=False):
        if not self.enabled:
            base, border, text_color = (22, 22, 30), (70, 70, 85), GRAY
        elif hover:
            base, border, text_color = (55, 55, 90), CYAN, WHITE
        else:
            base, border, text_color = (32, 32, 52), (90, 90, 130), WHITE
        pygame.draw.rect(surface, base, self.rect, border_radius=8)
        pygame.draw.rect(surface, border, self.rect, 2, border_radius=8)
        draw_text_center(surface, self.label, font, text_color, self.rect.center)

    def hit(self, pos):
        return self.enabled and self.rect.collidepoint(pos)


# --------------------------------------------------------------------------
# PARTICLES (visual juice on brick break / wall hits / timeout fire bursts)
# --------------------------------------------------------------------------
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size")

    def __init__(self, x, y, color):
        self.x, self.y = x, y
        angle = random.uniform(0, math.tau)
        speed = random.uniform(1.5, 5.5)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.life = self.max_life = random.uniform(0.25, 0.55)
        self.color = color
        self.size = random.uniform(2, 4)

    def update(self, dt):
        self.x += self.vx
        self.y += self.vy
        self.vy += 6 * dt  # slight gravity
        self.life -= dt
        return self.life > 0

    def draw(self, surface):
        alpha = max(0, int(255 * (self.life / self.max_life)))
        s = pygame.Surface((int(self.size * 2) + 2, int(self.size * 2) + 2), pygame.SRCALPHA)
        draw_aa_circle(
            s, (*self.color, alpha), (int(self.size) + 1, int(self.size) + 1), int(self.size)
        )
        surface.blit(s, (self.x - self.size - 1, self.y - self.size - 1))


# --------------------------------------------------------------------------
# GAME OBJECTS
# --------------------------------------------------------------------------
PADDLE_Y = HEIGHT - 50
PADDLE_H = 16
PADDLE_W_NORMAL = 110
PADDLE_W_WIDE = 165
PADDLE_W_SHRUNK = 70
PADDLE_SPEED = 11
PADDLE_CORNER_ZONE = 10  # pixels from either edge that count as a "corner" hit
MAX_LIVES = 6


class Paddle:
    def __init__(self):
        self.width = PADDLE_W_NORMAL
        self.height = PADDLE_H
        self.x = WIDTH // 2 - self.width // 2
        self.y = PADDLE_Y
        self.color = CYAN
        self.wide_timer = 0.0
        self.shrink_timer = 0.0
        self.speed = PADDLE_SPEED

    @property
    def rect(self):
        return pygame.Rect(int(self.x), self.y, self.width, self.height)

    def apply_width(self):
        # Handle smooth transition between normal, wide, and shrunk sizes
        if self.wide_timer > 0:
            target = PADDLE_W_WIDE
        elif self.shrink_timer > 0:
            target = PADDLE_W_SHRUNK
        else:
            target = PADDLE_W_NORMAL
        if self.width != target:
            center = self.x + self.width / 2
            self.width += (target - self.width) * 0.25
            if abs(self.width - target) < 1:
                self.width = target
            self.x = center - self.width / 2

    def update(self, dt, keys, mouse_dx, mouse_control):
        if self.wide_timer > 0:
            self.wide_timer -= dt
        if self.shrink_timer > 0:
            self.shrink_timer -= dt
        self.apply_width()

        moved = False
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.x -= self.speed
            moved = True
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.x += self.speed
            moved = True
        if mouse_control and not moved:
            self.x = mouse_dx - self.width / 2
        self.x = max(10, min(WIDTH - 10 - self.width, self.x))

    def grant_wide(self):
        self.wide_timer = 9.0
        self.shrink_timer = 0.0

    def grant_shrink(self):
        self.shrink_timer = 7.0
        self.wide_timer = 0.0

    def draw(self, surface):
        color = GREEN if self.wide_timer > 0 else (RED if self.shrink_timer > 0 else CYAN)
        draw_glow_rect(surface, self.rect, color, radius=8)


BALL_RADIUS = 8
BASE_BALL_SPEED = 6.5


class Ball:
    def __init__(self, x, y, speed, angle=None, stuck=False):
        self.x, self.y = x, y
        self.radius = BALL_RADIUS
        self.base_speed = speed
        self.speed_mult = 1.0
        if angle is None:
            angle = random.uniform(-0.6, 0.6) - math.pi / 2  # mostly upward
        self.dx = math.cos(angle)
        self.dy = math.sin(angle)
        self.stuck = stuck
        self.slow_timer = 0.0
        self.fast_timer = 0.0
        self.trail = []

    @property
    def speed(self):
        mult = 1.0
        if self.slow_timer > 0:
            mult *= 0.6
        if self.fast_timer > 0:
            mult *= 1.55
        return self.base_speed * mult

    def launch_from(self, paddle):
        self.stuck = False
        # Calculate launch angle based on where the ball sits on the paddle
        offset = (self.x - (paddle.x + paddle.width / 2)) / (paddle.width / 2)
        angle = -math.pi / 2 + offset * 0.9
        self.dx = math.cos(angle)
        self.dy = math.sin(angle)

    def update_timers_and_trail(self, dt, paddle):
        """Advance timers and (if stuck) pin position to the paddle. Does NOT move a free ball -
        actual movement is done in discrete move() steps by the caller so it can sub-step for
        collision safety at high speed."""
        if self.slow_timer > 0:
            self.slow_timer -= dt
        if self.fast_timer > 0:
            self.fast_timer -= dt

        if self.stuck:
            self.x = paddle.x + paddle.width / 2
            self.y = paddle.y - self.radius - 2
            return

        self.trail.append((self.x, self.y))
        if len(self.trail) > 8:
            self.trail.pop(0)

    def move(self, dist):
        """Move the ball `dist` pixels along its current direction and resolve wall collisions.
        Returns True if it bounced off a wall (so the caller can trigger a sound/particle)."""
        self.x += self.dx * dist
        self.y += self.dy * dist

        bounced = False
        if self.x - self.radius <= 0:
            self.x = self.radius
            self.dx = abs(self.dx)
            bounced = True
        elif self.x + self.radius >= WIDTH:
            self.x = WIDTH - self.radius
            self.dx = -abs(self.dx)
            bounced = True
        if self.y - self.radius <= 0:
            self.y = self.radius
            self.dy = abs(self.dy)
            bounced = True
        return bounced

    def rect(self):
        return pygame.Rect(
            int(self.x - self.radius), int(self.y - self.radius), self.radius * 2, self.radius * 2
        )

    def draw(self, surface):
        for i, (tx, ty) in enumerate(self.trail):
            alpha = int(90 * (i / max(1, len(self.trail))))
            s = pygame.Surface((self.radius * 2, self.radius * 2), pygame.SRCALPHA)
            draw_aa_circle(s, (*YELLOW, alpha), (self.radius, self.radius), self.radius - 2)
            surface.blit(s, (tx - self.radius, ty - self.radius))
        color = BLUE if self.slow_timer > 0 else (ORANGE if self.fast_timer > 0 else YELLOW)
        draw_glow_circle(surface, (int(self.x), int(self.y)), self.radius, color)


class Brick:
    def __init__(self, x, y, w, h, hp, unbreakable=False):
        self.rect = pygame.Rect(x, y, w, h)
        self.hp = hp
        self.max_hp = hp
        self.unbreakable = unbreakable
        self.alive = True
        self.hit_flash = 0.0

    def hit(self):
        if self.unbreakable:
            self.hit_flash = 0.15
            return False
        self.hp -= 1
        self.hit_flash = 0.15
        if self.hp <= 0:
            self.alive = False
            return True
        return False

    def color(self):
        if self.unbreakable:
            return (90, 95, 110)
        return HP_COLORS.get(min(self.hp, 4), RED)

    def update(self, dt):
        if self.hit_flash > 0:
            self.hit_flash -= dt

    def draw(self, surface):
        col = self.color()
        if self.hit_flash > 0:
            col = tuple(min(255, c + 90) for c in col)
        draw_glow_rect(surface, self.rect, col, layers=3, expand=2, base_alpha=40, radius=3)
        if self.unbreakable:
            pygame.draw.line(surface, (150, 150, 165), self.rect.topleft, self.rect.bottomright, 1)
            pygame.draw.line(surface, (150, 150, 165), self.rect.bottomleft, self.rect.topright, 1)


class PowerUp:
    """Now spawned at random points on screen on a timer (see Game.spawn_random_powerup),
    rather than dropping from almost every broken brick. Expires (disappears) if not
    caught in time, whether or not it has reached the bottom of the screen."""

    LIFESPAN = 9.0

    def __init__(self, x, y, kind):
        self.x, self.y = x, y
        self.kind = kind
        self.letter, self.color, _ = POWERUP_INFO[kind]
        self.vy = 2.6
        self.lifespan = PowerUp.LIFESPAN

    def update(self, dt):
        self.y += self.vy
        self.lifespan -= dt

    @property
    def expired(self):
        return self.lifespan <= 0

    def rect(self):
        half = POWERUP_SIZE // 2
        return pygame.Rect(int(self.x - half), int(self.y - half), POWERUP_SIZE, POWERUP_SIZE)

    def draw(self, surface):
        if self.lifespan < 1.5 and int(self.lifespan * 8) % 2 == 0:
            return  # blink right before expiring
        r = self.rect()
        draw_glow_rect(surface, r, self.color, layers=4, expand=2, base_alpha=70, radius=14)
        draw_text_center(surface, self.letter, FONT_SMALL, (10, 10, 15), r.center)


POWERUP_SIZE = 28
LASER_WIDTH_DESIGN = 90  # design-resolution width; actual width scales with SCALE at spawn time


class Laser:
    """A telegraphed hazard: flashes a warning band at the bottom of the screen for
    WARNING_DURATION seconds (giving the player time to move out of the way), then fires
    a full-height beam for FIRE_DURATION seconds. If the paddle is still in its path when
    it fires, it costs a life (see Game.update)."""

    WARNING_DURATION = 3.0
    FIRE_DURATION = 0.45

    def __init__(self, x, width):
        self.x = x
        self.width = width
        self.timer = 0.0
        self.state = "warning"
        self.hit_applied = False

    def update(self, dt):
        self.timer += dt
        if self.state == "warning" and self.timer >= Laser.WARNING_DURATION:
            self.state = "firing"
            self.timer = 0.0
        elif self.state == "firing" and self.timer >= Laser.FIRE_DURATION:
            self.state = "done"

    def rect(self):
        return pygame.Rect(int(self.x - self.width / 2), 0, int(self.width), HEIGHT)

    def draw(self, surface):
        half = self.width / 2
        if self.state == "warning":
            # Pulsing warning band near the bottom of the screen, where the danger is.
            pulse = 0.35 + 0.65 * abs(math.sin(self.timer * 6))
            band_h = round(150 * SCALE)
            band = pygame.Surface((int(self.width), band_h), pygame.SRCALPHA)
            alpha = int(120 * pulse)
            band.fill((255, 60, 60, alpha))
            pygame.draw.rect(
                band,
                (255, 160, 60, min(255, alpha + 60)),
                band.get_rect(),
                width=max(1, round(3 * SCALE)),
            )
            surface.blit(band, (self.x - half, HEIGHT - band_h))
            if pulse > 0.7:
                draw_text_center(
                    surface,
                    "!",
                    FONT_MED,
                    (255, 220, 60),
                    (self.x, HEIGHT - band_h + round(24 * SCALE)),
                )
        elif self.state == "firing":
            fade = 1.0 - (self.timer / Laser.FIRE_DURATION)
            beam = pygame.Surface((int(self.width), HEIGHT), pygame.SRCALPHA)
            beam.fill((255, 230, 200, int(90 * fade)))
            core_w = max(2, int(self.width * 0.35))
            core = pygame.Rect((self.width - core_w) / 2, 0, core_w, HEIGHT)
            pygame.draw.rect(beam, (255, 255, 255, int(220 * fade)), core)
            surface.blit(beam, (self.x - half, 0))


# --------------------------------------------------------------------------
# STAGE / LEVEL DESIGN
# --------------------------------------------------------------------------
BRICK_TOP = 70
BRICK_GAP = 6
BRICK_H = 24
COLS = 14
MARGIN_X = 40


def recompute_scaled_constants(new_w, new_h):
    """Re-derive every pixel-based layout constant (paddle, ball, bricks, power-ups,
    fonts) for a new logical resolution. Only called at safe checkpoints (see
    Game.load_stage) - never mid-collision-detection - since it changes sizes that
    live game objects were built against."""
    global WIDTH, HEIGHT, SCALE, screen
    global PADDLE_Y, PADDLE_H, PADDLE_W_NORMAL, PADDLE_W_WIDE, PADDLE_W_SHRUNK, PADDLE_SPEED, PADDLE_CORNER_ZONE
    global BALL_RADIUS, BASE_BALL_SPEED
    global BRICK_TOP, BRICK_GAP, BRICK_H, MARGIN_X
    global POWERUP_SIZE
    global FONT_BIG, FONT_MED, FONT_SMALL, FONT_TINY

    new_w = max(DESIGN_W, min(new_w, MAX_LOGICAL_W))
    new_h = max(DESIGN_H, min(new_h, MAX_LOGICAL_H))
    # keep the design aspect ratio (10:7) regardless of the window's actual shape
    if new_w / new_h > DESIGN_W / DESIGN_H:
        new_w = round(new_h * DESIGN_W / DESIGN_H)
    else:
        new_h = round(new_w * DESIGN_H / DESIGN_W)

    if (new_w, new_h) == (WIDTH, HEIGHT):
        return False

    WIDTH, HEIGHT = new_w, new_h
    SCALE = WIDTH / DESIGN_W
    screen = pygame.Surface((WIDTH, HEIGHT))

    PADDLE_H = round(16 * SCALE)
    PADDLE_W_NORMAL = round(110 * SCALE)
    PADDLE_W_WIDE = round(165 * SCALE)
    PADDLE_W_SHRUNK = round(70 * SCALE)
    PADDLE_Y = HEIGHT - round(50 * SCALE)
    PADDLE_SPEED = 11 * SCALE
    PADDLE_CORNER_ZONE = round(10 * SCALE)

    BALL_RADIUS = round(8 * SCALE)
    BASE_BALL_SPEED = 6.5 * SCALE

    BRICK_TOP = round(70 * SCALE)
    BRICK_GAP = round(6 * SCALE)
    BRICK_H = round(24 * SCALE)
    MARGIN_X = round(40 * SCALE)

    POWERUP_SIZE = round(28 * SCALE)

    FONT_BIG = pygame.font.SysFont("consolas", round(64 * SCALE), bold=True)
    FONT_MED = pygame.font.SysFont("consolas", round(34 * SCALE), bold=True)
    FONT_SMALL = pygame.font.SysFont("consolas", max(10, round(20 * SCALE)), bold=True)
    FONT_TINY = pygame.font.SysFont("consolas", max(9, round(15 * SCALE)))

    log(f"Logical resolution changed to {WIDTH}x{HEIGHT} (scale {SCALE:.2f}x).")
    return True


def stage_config(stage):
    """Returns dict of tuning knobs for a given stage (1-indexed)."""
    return {
        "rows": min(4 + (stage - 1) // 2, 9),
        "hp_max": min(1 + (stage - 1) // 3, 4),
        "unbreak_chance": max(0.0, (stage - 3) * 0.025) if stage >= 3 else 0.0,
        # Ball gets noticeably faster every stage now - by the late stages a "fast" pickup
        # is a genuine gamble and "slow" becomes the appealing choice, rather than just a
        # flat multiplier on a mild base curve. (A further small bump can be added once per
        # stage if the player runs out of time - see Game.trigger_timeout_effect.)
        "ball_speed": BASE_BALL_SPEED + (stage - 1) * 0.72 * SCALE,
        # Per-stage time limit before the timeout difficulty spike kicks in. Increased a lot
        # across the board to offset the added speed/laser pressure - still gentle at first
        # and drops off more steeply later, just from a much more forgiving starting point.
        "time_limit": max(40, round(95 - 1.67 * ((stage - 1) ** 1.3))),
        "pattern": [
            "full",
            "checker",
            "pyramid",
            "diamond",
            "curtain",
            "checker",
            "pyramid",
            "diamond",
            "curtain",
            "fortress",
        ][(stage - 1) % 10],
    }


def pattern_alive(pattern, row, col, rows, cols):
    """Decide whether a grid cell should contain a brick, based on pattern shape."""
    mid = (cols - 1) / 2
    if pattern == "full":
        return True
    if pattern == "checker":
        return (row + col) % 2 == 0
    if pattern == "pyramid":
        span = int((row + 1) * (cols / (2 * rows)))
        return abs(col - mid) <= span
    if pattern == "diamond":
        half = rows / 2
        dist_r = abs(row - half)
        span = (rows / 2 - dist_r) * (cols / rows)
        return abs(col - mid) <= span
    if pattern == "curtain":
        return not (row % 3 == 1 and col % 4 == 2)
    if pattern == "fortress":
        border = row == 0 or row == rows - 1 or col == 0 or col == cols - 1
        return border or (row + col) % 2 == 0
    return True


def build_bricks(stage):
    cfg = stage_config(stage)
    rows, cols = cfg["rows"], COLS
    usable_w = WIDTH - MARGIN_X * 2
    brick_w = (usable_w - BRICK_GAP * (cols - 1)) / cols
    bricks = []
    rng = random.Random(stage * 7919 + 13)  # deterministic per-stage layout

    for row in range(rows):
        for col in range(cols):
            if not pattern_alive(cfg["pattern"], row, col, rows, cols):
                continue
            x = MARGIN_X + col * (brick_w + BRICK_GAP)
            y = BRICK_TOP + row * (BRICK_H + BRICK_GAP)
            hp = rng.randint(1, cfg["hp_max"])
            unbreakable = rng.random() < cfg["unbreak_chance"] and row != rows - 1
            b = Brick(x, y, brick_w, BRICK_H, hp, unbreakable)
            bricks.append(b)
    return bricks, cfg


# --------------------------------------------------------------------------
# ENDLESS MODE (unlocked after all 10 stages are cleared - see Game.start_endless).
# Reuses the same difficulty curve as the numbered stages but keeps scaling past
# Stage 10 forever, and picks a random brick pattern each level instead of the
# fixed 10-stage cycle - never the same pattern twice in a row.
# --------------------------------------------------------------------------
ENDLESS_PATTERNS = ["full", "checker", "pyramid", "diamond", "curtain", "fortress"]


def endless_stage_config(stage, last_pattern):
    """Same tuning curve as stage_config, extended past Stage 10 forever, but with
    a randomly chosen (never-repeating-consecutively) brick pattern."""
    choices = [p for p in ENDLESS_PATTERNS if p != last_pattern] or ENDLESS_PATTERNS
    return {
        "rows": min(4 + (stage - 1) // 2, 9),
        "hp_max": min(1 + (stage - 1) // 3, 4),
        "unbreak_chance": min(0.35, max(0.0, (stage - 3) * 0.025)),
        "ball_speed": BASE_BALL_SPEED + (stage - 1) * 0.72 * SCALE,
        "time_limit": 120,
        "pattern": random.choice(choices),
    }


def build_endless_bricks(stage, last_pattern):
    cfg = endless_stage_config(stage, last_pattern)
    rows, cols = cfg["rows"], COLS
    usable_w = WIDTH - MARGIN_X * 2
    brick_w = (usable_w - BRICK_GAP * (cols - 1)) / cols
    bricks = []
    rng = random.Random()  # true randomness each level (unlike the deterministic per-stage seed)

    for row in range(rows):
        for col in range(cols):
            if not pattern_alive(cfg["pattern"], row, col, rows, cols):
                continue
            x = MARGIN_X + col * (brick_w + BRICK_GAP)
            y = BRICK_TOP + row * (BRICK_H + BRICK_GAP)
            hp = rng.randint(1, cfg["hp_max"])
            unbreakable = rng.random() < cfg["unbreak_chance"] and row != rows - 1
            b = Brick(x, y, brick_w, BRICK_H, hp, unbreakable)
            bricks.append(b)
    return bricks, cfg


# --------------------------------------------------------------------------
# MAIN GAME
# --------------------------------------------------------------------------
STATE_MENU = "menu"
STATE_HIGHSCORES = "highscores"
STATE_STAGE_SELECT = "stage_select"
STATE_READY = "ready"
STATE_PLAY = "play"
STATE_STAGE_CLEAR = "stage_clear"
STATE_PAUSED = "paused"
STATE_GAME_OVER = "game_over"
STATE_VICTORY = "victory"

TOTAL_STAGES = 10


def update_progress(stage_cleared):
    """Persist max stage reached / full-completion flag (unlocks Stage Select)."""
    changed = False
    if stage_cleared > CONFIG.get("max_stage_reached", 1):
        CONFIG["max_stage_reached"] = stage_cleared
        changed = True
    if stage_cleared >= TOTAL_STAGES and not CONFIG.get("game_completed", False):
        CONFIG["game_completed"] = True
        changed = True
    if changed:
        save_config(CONFIG)
        log(
            f"Progress saved: max_stage_reached={CONFIG['max_stage_reached']}, "
            f"game_completed={CONFIG['game_completed']}"
        )


class Game:
    def __init__(self):
        self.state = STATE_MENU
        self.pre_pause_state = STATE_READY
        self.stars = [
            (random.randint(0, WIDTH), random.randint(0, HEIGHT), random.uniform(0.3, 1.2))
            for _ in range(90)
        ]
        self.highscores = load_highscores()
        self.is_new_best = False
        self.highscore_rank = None
        self.mouse_logical = (0, 0)
        self._geometry_dirty = False
        self._geometry_save_accum = 0.0
        self._score_finalized = False
        self._run_id = None
        self._last_autosaved_score = 0
        self._autosave_accum = 0.0
        self.endless = False
        self._last_endless_pattern = None
        self.resume_cooldown = 0.0
        self.score = 0
        self.stage = 1
        log("Game initialized, entering menu state.")
        self.reset_full()
        self.state = STATE_MENU  # start on the menu, not straight into READY

    def _begin_new_run(self):
        """Closes out whatever run was previously in progress (saving it if it hadn't
        already been saved via death/victory/quit) and resets autosave tracking for
        the run about to start."""
        self.finalize_score()
        self._score_finalized = False
        self._run_id = uuid.uuid4().hex
        self._last_autosaved_score = 0
        self._autosave_accum = 0.0

    def reset_full(self):
        self._begin_new_run()
        self.stage = 1
        self.endless = False
        self.score = 0
        self.lives = 4  # 3 hearts shown at start (hearts displayed = lives - 1)
        self.paddle = Paddle()
        self.balls = []
        self.bricks = []
        self.powerups = []
        self.particles = []
        self.lasers = []
        self.ready_timer = 0.0
        self.stage_clear_bonus = 0
        self.mouse_control_active = False
        self.is_new_best = False
        self.highscore_rank = None
        log(f"Full reset called. Starting Stage {self.stage}.")
        self.load_stage(self.stage)

    def start_at_stage(self, stage):
        """Used by Stage Select / Continue to jump straight into any stage."""
        self._begin_new_run()
        self.stage = stage
        self.score = 0
        self.lives = 4  # 3 hearts shown at start (hearts displayed = lives - 1)
        self.particles = []
        self.powerups = []
        self.lasers = []
        self.is_new_best = False
        self.highscore_rank = None
        self.load_stage(stage)
        log(f"Starting directly at Stage {stage}.")

    def continue_game(self):
        """Continue button: start a fresh run (score/lives reset) but from the player's
        best-ever progress (CONFIG['max_stage_reached']), not from stage 1. Playing an
        earlier stage via Start never lowers that recorded best - see update_progress()."""
        target = CONFIG.get("max_stage_reached", 1)
        self.start_at_stage(target)
        log(f"Continuing from Stage {target} (best progress so far).")

    def start_endless(self):
        """ENDLESS MODE: unlocked once all 10 stages have been cleared. Keeps scaling
        difficulty past Stage 10 forever, with a randomly chosen brick pattern each
        level that never repeats twice in a row (see build_endless_bricks)."""
        self._begin_new_run()
        self.endless = True
        self._last_endless_pattern = None
        self.stage = TOTAL_STAGES + 1
        self.score = 0
        self.lives = 4  # 3 hearts shown at start (hearts displayed = lives - 1)
        self.particles = []
        self.powerups = []
        self.lasers = []
        self.is_new_best = False
        self.highscore_rank = None
        self.load_stage(self.stage)
        log("Starting Endless Mode.")

    def _maybe_apply_pending_resolution(self):
        """Pick up a resolution change queued by a window resize/fullscreen toggle.
        Only called from safe checkpoints (new stage / restart / stage select) so we
        never resize while mid-collision against already-placed bricks."""
        if recompute_scaled_constants(*PENDING_RESOLUTION):
            self.stars = [
                (random.randint(0, WIDTH), random.randint(0, HEIGHT), random.uniform(0.3, 1.2))
                for _ in range(90)
            ]

    def load_stage(self, stage):
        self._maybe_apply_pending_resolution()
        self.resume_cooldown = 0.0
        if self.endless:
            self.bricks, self.cfg = build_endless_bricks(stage, self._last_endless_pattern)
            self._last_endless_pattern = self.cfg["pattern"]
        else:
            self.bricks, self.cfg = build_bricks(stage)
        self.paddle = Paddle()
        self.powerups.clear()
        self.particles.clear()
        self.stage_speed_mult = 1.0
        speed = self.cfg["ball_speed"]
        b = Ball(
            self.paddle.x + self.paddle.width / 2,
            self.paddle.y - BALL_RADIUS - 2,
            speed,
            stuck=True,
        )
        self.balls = [b]
        self.ready_timer = 1.2
        self.stage_time_left = self.cfg["time_limit"]
        self.time_expired = False
        self.shake_time_left = 0.0
        self.shake_duration_total = 0.0
        self.shake_magnitude = 0.0
        self._fire_spawn_accum = 0.0
        self.powerup_spawn_timer = random.uniform(5.0, 8.0)
        self.lasers = []
        self.laser_spawn_timer = random.uniform(4.0, 7.0)  # used once overtime begins
        self.paddle_still_timer = 0.0
        self._last_paddle_x = None
        self.state = STATE_READY
        self.pre_pause_state = STATE_READY
        set_cursor_locked(
            True
        )  # hidden+confined automatically when a stage begins; Ctrl/Alt frees it
        log(
            f"Stage {stage} loaded. Pattern: {self.cfg['pattern']}, Rows: {self.cfg['rows']}, "
            f"Time limit: {self.cfg['time_limit']}s, Ball speed: {self.cfg['ball_speed']:.2f}, "
            f"Total bricks: {len([br for br in self.bricks if br.alive])}"
        )

    # ---------------- spawning / effects ----------------
    def spawn_particles(self, x, y, color, n=14):
        for _ in range(n):
            self.particles.append(Particle(x, y, color))

    def spawn_random_powerup(self):
        if self.time_expired:
            # During overtime, only positive power-ups are allowed - no piling a
            # negative one (slow ball / shrunk paddle) on top of the difficulty spike.
            pool = [k for k in POWERUP_KEYS if k not in ("slow", "shrink")]
        else:
            pool = list(POWERUP_KEYS)
        if self.lives >= MAX_LIVES:
            pool = [k for k in pool if k != "life"]
        if not pool:
            return
        weights = [POWERUP_INFO[k][2] for k in pool]
        kind = random.choices(pool, weights=weights, k=1)[0]
        x = random.uniform(60, WIDTH - 60)
        y = random.uniform(90, 160)
        self.powerups.append(PowerUp(x, y, kind))
        log(
            f"Random powerup '{kind}' spawned at ({x:.0f}, {y:.0f}).{'  (overtime - positive only)' if self.time_expired else ''}"
        )

    def spawn_laser(self, target_x, reason=""):
        if len(self.lasers) >= 3:
            return  # don't let warnings pile up indefinitely
        width = LASER_WIDTH_DESIGN * SCALE
        x = max(width / 2 + 10, min(WIDTH - width / 2 - 10, target_x))
        self.lasers.append(Laser(x, width))
        play_sound("laser_charge")
        log(f"Laser warning spawned at x={x:.0f} (reason: {reason}).")

    def trigger_shake(self, duration, magnitude):
        self.shake_time_left = duration
        self.shake_duration_total = duration
        self.shake_magnitude = magnitude

    def trigger_timeout_effect(self):
        """Called once, the moment a stage's time limit hits 0: earthquake-style screen
        shake, fire particle bursts, and a small permanent (for the rest of the stage)
        ball speed increase to ramp up the difficulty. The shake/fire then continue at a
        lower ambient level for as long as the stage is still in progress (see update())."""
        self.trigger_shake(duration=0.6, magnitude=16)
        for b in self.balls:
            b.base_speed *= 1.08
        self.stage_speed_mult *= 1.08
        for _ in range(4):
            fx = random.uniform(60, WIDTH - 60)
            fy = random.uniform(100, HEIGHT - 150)
            self.spawn_particles(fx, fy, random.choice([RED, ORANGE, YELLOW]), 10)
        play_sound("timeout")
        log(
            "Stage time limit reached! Difficulty spike triggered - shake and fire will "
            "continue at a lower level until the stage is cleared."
        )

    def maybe_drop_powerup(self, brick):
        # Bricks no longer drop power-ups directly (see spawn_random_powerup) - kept as a
        # harmless no-op in case anything still calls it.
        pass

    def apply_powerup(self, kind):
        log(f"Applying power-up: {kind}")
        if kind == "widen":
            self.paddle.grant_wide()
        elif kind == "shrink":
            self.paddle.grant_shrink()
        elif kind == "multiball":
            origin_x = self.paddle.x + self.paddle.width / 2
            origin_y = self.paddle.y - BALL_RADIUS - 2
            speed = (
                self.balls[0].base_speed
                if self.balls
                else self.cfg["ball_speed"] * self.stage_speed_mult
            )
            spread_angles = [-math.pi / 2 - 0.55, -math.pi / 2, -math.pi / 2 + 0.55]
            for angle in spread_angles:
                self.balls.append(Ball(origin_x, origin_y, speed, angle=angle, stuck=False))
            for b in self.balls:
                if b.stuck:
                    b.launch_from(
                        self.paddle
                    )  # don't waste the powerup on a ball that hasn't launched
            self.spawn_particles(origin_x, origin_y, MAGENTA, 16)
            log(
                f"Multi-ball activated: 3 new balls launched from the paddle. Total balls: {len(self.balls)}"
            )
        elif kind == "slow":
            for b in self.balls:
                b.slow_timer = 6.0
                b.fast_timer = 0.0
            log("Slow powerup applied to all active balls.")
        elif kind == "fast":
            for b in self.balls:
                b.fast_timer = 5.0
                b.slow_timer = 0.0
            log("Fast powerup applied to all active balls.")
        elif kind == "life":
            self.lives = min(self.lives + 1, MAX_LIVES)
            log(f"Extra life gained. Lives: {self.lives}")

    # ---------------- collisions ----------------
    def resolve_ball_brick(self, ball, brick):
        br = ball.rect()
        rect = brick.rect

        # Determine the minimum overlap to figure out which side was hit
        overlap_l = br.right - rect.left
        overlap_r = rect.right - br.left
        overlap_t = br.bottom - rect.top
        overlap_b = rect.bottom - br.top
        min_overlap = min(overlap_l, overlap_r, overlap_t, overlap_b)

        # Push the ball fully clear of the brick along the resolved axis so it can never
        # still be overlapping (and therefore immediately re-collide with) the same brick
        # on the next substep/frame.
        if min_overlap in (overlap_l, overlap_r):
            ball.dx = -ball.dx  # Horizontal bounce
            if min_overlap == overlap_l:
                ball.x = rect.left - ball.radius - 0.5
            else:
                ball.x = rect.right + ball.radius + 0.5
        else:
            ball.dy = -ball.dy  # Vertical bounce
            if min_overlap == overlap_t:
                ball.y = rect.top - ball.radius - 0.5
            else:
                ball.y = rect.bottom + ball.radius + 0.5

        broke = brick.hit()
        color = brick.color()
        self.spawn_particles(rect.centerx, rect.centery, color, 10 if broke else 5)

        if broke:
            self.score += 10 * brick.max_hp * self.stage_score_mult()
            play_sound("brick_break")
            log(f"Brick destroyed at ({rect.x}, {rect.y}). New score: {self.score}")
        else:
            self.score += 2
            play_sound("brick_hit")
            log(f"Brick hit (not destroyed) at ({rect.x}, {rect.y}). HP left: {brick.hp}")

    def stage_score_mult(self):
        return 1 + (self.stage - 1) * 0.15

    def finalize_score(self):
        """Call any time a run ends or is abandoned (game over, victory, quitting,
        restarting, or returning to the menu mid-run) to persist the score for good.
        Idempotent per run - safe to call more than once (e.g. both on death and on a
        subsequent quit)."""
        if self._score_finalized or self.score <= 0:
            return
        self._score_finalized = True
        prior_best = self.highscores[0]["score"] if self.highscores else 0
        self.is_new_best = self.score > prior_best
        self.highscores = save_highscore(self.score, self.stage, endless=self.endless, run_id=self._run_id)
        self.highscore_rank = next(
            (
                i
                for i, e in enumerate(self.highscores)
                if e["score"] == self.score and e["stage"] == self.stage
            ),
            None,
        )

    def _autosave_tick(self, dt):
        """Persists the current run's score to disk every few seconds while it's still
        in progress, so a hard crash or forced kill doesn't lose it - not just the
        explicit end-of-run/quit paths that finalize_score() already covers."""
        if self._score_finalized or self.score <= 0 or self.score == self._last_autosaved_score:
            return
        self._autosave_accum += dt
        if self._autosave_accum < 3.0:
            return
        self._autosave_accum = 0.0
        self._last_autosaved_score = self.score
        self.highscores = save_highscore(self.score, self.stage, endless=self.endless, run_id=self._run_id)

    # ---------------- pause ----------------
    def toggle_pause(self):
        if self.state in (STATE_PLAY, STATE_READY):
            self.pre_pause_state = self.state
            self.state = STATE_PAUSED
            set_cursor_locked(False)
            play_sound("ui_click")
        elif self.state == STATE_PAUSED:
            self.state = self.pre_pause_state
            set_cursor_locked(True)
            self.resume_cooldown = 3.0
            play_sound("countdown_tick")
            return

    def restart_stage(self):
        log(f"Restarting Stage {self.stage} from the pause menu.")
        self.load_stage(self.stage)

    # ---------------- update ----------------
    def update(self, dt, keys, mouse_pos, mouse_moved):
        self._autosave_tick(dt)
        self.mouse_logical = mouse_pos
        if mouse_moved:
            self.mouse_control_active = True
        if keys[pygame.K_LEFT] or keys[pygame.K_RIGHT] or keys[pygame.K_a] or keys[pygame.K_d]:
            self.mouse_control_active = False

        if (
            self.state not in (STATE_PLAY, STATE_READY, STATE_PAUSED)
            and not pygame.mouse.get_visible()
        ):
            set_cursor_locked(False)

        for p in self.particles[:]:
            if not p.update(dt):
                self.particles.remove(p)

        # Shake decays every frame regardless of state, so a shake mid-decay when the
        # game ends doesn't freeze and render forever on the Game Over screen.
        if self.shake_time_left > 0:
            self.shake_time_left = max(0.0, self.shake_time_left - dt)

        if self.resume_cooldown > 0 and self.state in (STATE_PLAY, STATE_READY):
            prev_ceil = math.ceil(self.resume_cooldown)
            self.resume_cooldown = max(0.0, self.resume_cooldown - dt)
            new_ceil = math.ceil(self.resume_cooldown)
            if self.resume_cooldown <= 0:
                play_sound("countdown_go")
            elif new_ceil != prev_ceil:
                play_sound("countdown_tick")
            return

        if self.state == STATE_READY:
            self.paddle.update(dt, keys, mouse_pos[0], self.mouse_control_active)
            for b in self.balls:
                b.update_timers_and_trail(dt, self.paddle)
            self.ready_timer -= dt
            if self.ready_timer <= 0:
                self.state = STATE_PLAY
                log("Ready timer finished. Transitioning to PLAY state.")
            return

        if self.state != STATE_PLAY:
            return

        self.paddle.update(dt, keys, mouse_pos[0], self.mouse_control_active)

        # ---- AFK detection: camping in one spot to cheese an easy brick column ----
        if self._last_paddle_x is not None and abs(self.paddle.x - self._last_paddle_x) < 0.5:
            self.paddle_still_timer += dt
        else:
            self.paddle_still_timer = 0.0
        self._last_paddle_x = self.paddle.x
        if self.paddle_still_timer >= 6.0:
            self.spawn_laser(self.paddle.x + self.paddle.width / 2, reason="afk")
            self.paddle_still_timer = 0.0

        # ---- stage timer / difficulty spike ----
        if not self.time_expired:
            self.stage_time_left -= dt
            if self.stage_time_left <= 0:
                self.stage_time_left = 0
                self.time_expired = True
                self.trigger_timeout_effect()

        if self.time_expired:
            # Sustained tremor + ambient fire particles for the REST of the stage,
            # not just a brief moment after the timer runs out.
            self._fire_spawn_accum += dt
            if self._fire_spawn_accum >= 0.45:
                self._fire_spawn_accum = 0.0
                fx = random.uniform(40, WIDTH - 40)
                fy = random.uniform(90, HEIGHT - 140)
                self.spawn_particles(fx, fy, random.choice([RED, ORANGE, YELLOW]), 5)

            # ---- random laser beams to keep overtime tense ----
            self.laser_spawn_timer -= dt
            if self.laser_spawn_timer <= 0:
                width = LASER_WIDTH_DESIGN * SCALE
                x = random.uniform(width / 2 + 20, WIDTH - width / 2 - 20)
                self.spawn_laser(x, reason="overtime")
                self.laser_spawn_timer = random.uniform(4.0, 7.0)

        # ---- laser update / collision ----
        for laser in self.lasers[:]:
            was_warning = laser.state == "warning"
            laser.update(dt)
            if was_warning and laser.state == "firing":
                play_sound("laser_fire")
                self.trigger_shake(duration=0.15, magnitude=6)
            if laser.state == "firing" and not laser.hit_applied:
                if laser.rect().colliderect(self.paddle.rect):
                    laser.hit_applied = True
                    self.lives -= 1
                    play_sound("laser_hit")
                    self.spawn_particles(
                        self.paddle.x + self.paddle.width / 2, self.paddle.y, RED, 20
                    )
                    self.trigger_shake(duration=0.35, magnitude=12)
                    log(f"Laser hit the paddle! Lives: {self.lives}")
                    if self.lives <= 0:
                        self.state = STATE_GAME_OVER
                        play_sound("game_over")
                        self.finalize_score()
                        log("Game Over triggered by laser hit.")
                        return
            if laser.state == "done":
                self.lasers.remove(laser)

        # ---- random powerup spawning ----
        self.powerup_spawn_timer -= dt
        if self.powerup_spawn_timer <= 0:
            self.spawn_random_powerup()
            self.powerup_spawn_timer = random.uniform(6.0, 11.0)

        for b in self.balls[:]:
            b.update_timers_and_trail(dt, self.paddle)
            if b.stuck:
                continue

            # Sub-step movement so a fast ball (high stage + "fast" powerup) can never tunnel
            # through a brick or the paddle within a single frame.
            total_dist = b.speed
            steps = max(1, int(total_dist // max(1, b.radius)) + 1)
            step_dist = total_dist / steps

            ball_removed = False
            for _ in range(steps):
                if b.move(step_dist):
                    play_sound("wall")

                # paddle collision
                if (
                    b.dy > 0
                    and b.rect().colliderect(self.paddle.rect)
                    and b.y < self.paddle.y + self.paddle.height
                ):
                    b.y = self.paddle.y - b.radius - 1
                    b.launch_from(self.paddle)
                    paddle_left = self.paddle.x
                    paddle_right = self.paddle.x + self.paddle.width
                    is_corner_hit = (b.x - paddle_left <= PADDLE_CORNER_ZONE) or (
                        paddle_right - b.x <= PADDLE_CORNER_ZONE
                    )
                    if is_corner_hit:
                        b.fast_timer = max(b.fast_timer, 1.2)  # brief smash-boost
                        self.spawn_particles(b.x, b.y, YELLOW, 12)
                        play_sound("corner_hit")
                        log("Ball hit the paddle's corner - speed boost applied.")
                    else:
                        self.spawn_particles(b.x, b.y, CYAN, 6)
                        play_sound("paddle")
                    log("Ball bounced off paddle.")
                    break

                # brick collision: resolve against the NEAREST colliding brick (by center distance),
                # not just the first one in list order, so corner overlaps bounce correctly.
                hit_brick = None
                hit_dist_sq = None
                for brick in self.bricks:
                    if brick.alive and b.rect().colliderect(brick.rect):
                        dxc = b.x - brick.rect.centerx
                        dyc = b.y - brick.rect.centery
                        d2 = dxc * dxc + dyc * dyc
                        if hit_brick is None or d2 < hit_dist_sq:
                            hit_brick = brick
                            hit_dist_sq = d2
                if hit_brick:
                    self.resolve_ball_brick(b, hit_brick)
                    break

                # fell below screen
                if b.y - b.radius > HEIGHT:
                    self.balls.remove(b)
                    ball_removed = True
                    log("Ball fell below the screen and was removed.")
                    break

            if ball_removed:
                continue

        for brick in self.bricks:
            brick.update(dt)
        self.bricks = [br for br in self.bricks if br.alive or br.unbreakable]

        for pu in self.powerups[:]:
            pu.update(dt)
            if pu.rect().colliderect(self.paddle.rect):
                self.apply_powerup(pu.kind)
                self.powerups.remove(pu)
                self.spawn_particles(pu.x, pu.y, pu.color, 12)
                play_sound("powerup_good" if pu.kind in GOOD_POWERUPS else "powerup_bad")
                log(f"Powerup collected by paddle.")
            elif pu.y > HEIGHT or pu.expired:
                self.powerups.remove(pu)
                log(f"Powerup '{pu.kind}' expired/missed.")

        if not self.balls:
            self.lives -= 1
            play_sound("life_lost")
            log(f"All balls lost. Lives reduced to {self.lives}")
            if self.lives <= 0:
                self.state = STATE_GAME_OVER
                play_sound("game_over")
                self.finalize_score()
                log("Game Over triggered.")
            else:
                self.paddle = Paddle()
                speed = self.cfg["ball_speed"] * self.stage_speed_mult
                b = Ball(
                    self.paddle.x + self.paddle.width / 2,
                    self.paddle.y - BALL_RADIUS - 2,
                    speed,
                    stuck=True,
                )
                self.balls = [b]
                self.powerups.clear()
                self.ready_timer = 1.0
                self.state = STATE_READY
                log("Respawning ball. Returning to READY state.")
            return

        # Check if all breakable bricks are gone
        if all((not br.alive) or br.unbreakable for br in self.bricks) or not any(
            (not br.unbreakable) for br in self.bricks
        ):
            self.stage_clear_bonus = 250 * self.stage + self.lives * 40
            self.score += self.stage_clear_bonus
            self.state = STATE_STAGE_CLEAR
            play_sound("stage_clear")
            if not self.endless:
                update_progress(self.stage)
            log(f"Stage {self.stage} cleared! Bonus: {self.stage_clear_bonus}")

    def next_stage(self):
        self.stage += 1
        if self.endless:
            log(f"Advancing to Endless Level {self.stage - TOTAL_STAGES}...")
            self.load_stage(self.stage)
            return
        if self.stage > TOTAL_STAGES:
            self.state = STATE_VICTORY
            play_sound("victory")
            self.finalize_score()
            log("Victory! All stages cleared.")
        else:
            log(f"Advancing to Stage {self.stage}...")
            self.load_stage(self.stage)

    # ---------------- drawing ----------------
    def draw_background(self):
        screen.fill(BG_COLOR)
        for i in range(0, HEIGHT, 40):
            pygame.draw.line(screen, GRID_LINE, (0, i), (WIDTH, i), 1)
        for i in range(0, WIDTH, 40):
            pygame.draw.line(screen, GRID_LINE, (i, 0), (i, HEIGHT), 1)
        for sx, sy, b in self.stars:
            c = int(90 + 90 * b)
            pygame.draw.circle(screen, (c, c, c + 20), (sx, sy), 1)

    def pause_rect(self):
        s = SCALE
        return pygame.Rect(round(14 * s), round(8 * s), round(30 * s), round(30 * s))

    def draw_pause_button(self):
        rect = self.pause_rect()
        hover = rect.collidepoint(self.mouse_logical)
        bg = (55, 55, 90) if hover else (28, 28, 45)
        pygame.draw.rect(screen, bg, rect, border_radius=6)
        pygame.draw.rect(screen, CYAN, rect, 2, border_radius=6)
        cx, cy = rect.center
        s = SCALE
        if self.state == STATE_PAUSED:
            pygame.draw.polygon(
                screen,
                WHITE,
                [(cx - 5 * s, cy - 8 * s), (cx - 5 * s, cy + 8 * s), (cx + 8 * s, cy)],
            )
        else:
            pygame.draw.rect(screen, WHITE, (rect.x + 8 * s, rect.y + 6 * s, 5 * s, 18 * s))
            pygame.draw.rect(screen, WHITE, (rect.x + 17 * s, rect.y + 6 * s, 5 * s, 18 * s))

    def draw_hud(self):
        s = SCALE
        draw_text_center(
            screen, f"SCORE {self.score}", FONT_SMALL, CYAN, (round(150 * s), round(20 * s))
        )
        stage_hud_text = (
            f"ENDLESS - LVL {self.stage - TOTAL_STAGES}"
            if self.endless
            else f"STAGE {self.stage}/{TOTAL_STAGES}"
        )
        draw_text_center(
            screen,
            stage_hud_text,
            FONT_SMALL,
            MAGENTA,
            (WIDTH // 2, round(20 * s)),
        )
        hearts_shown = max(0, self.lives - 1)
        lives_txt = ("LIVES " + "♥ " * hearts_shown).strip()
        lives_color = heartbeat_color(pygame.time.get_ticks() / 1000.0) if hearts_shown == 0 else RED
        draw_text_center(
            screen, lives_txt, FONT_SMALL, lives_color, (WIDTH - round(110 * s), round(20 * s))
        )

        if self.time_expired:
            draw_text_center(screen, "OVERTIME", FONT_SMALL, RED, (WIDTH // 2, round(45 * s)))
        else:
            mm = int(self.stage_time_left) // 60
            ss = int(self.stage_time_left) % 60
            color = RED if self.stage_time_left < 10 else WHITE
            draw_text_center(
                screen, f"{mm:02d}:{ss:02d}", FONT_SMALL, color, (WIDTH // 2, round(45 * s))
            )

        # active effect indicators - duration is appended directly onto each tag
        # (e.g. "WIDE 4.3s") so it shows right next to the boost it belongs to.
        tags = []
        if self.paddle.wide_timer > 0:
            tags.append((f"WIDE {self.paddle.wide_timer:.1f}s", GREEN))
        if self.paddle.shrink_timer > 0:
            tags.append((f"SHRUNK {self.paddle.shrink_timer:.1f}s", RED))
        slow_left = max((b.slow_timer for b in self.balls if b.slow_timer > 0), default=0.0)
        if slow_left > 0:
            tags.append((f"SLOW {slow_left:.1f}s", BLUE))
        fast_left = max((b.fast_timer for b in self.balls if b.fast_timer > 0), default=0.0)
        if fast_left > 0:
            tags.append((f"FAST {fast_left:.1f}s", ORANGE))
        if len(self.balls) > 1:
            tags.append((f"x{len(self.balls)} BALLS", MAGENTA))
        if not SFX_ON:
            tags.append(("SFX OFF", GRAY))
        if not BGM_ON:
            tags.append(("BGM OFF", GRAY))
        for i, (t, c) in enumerate(tags):
            draw_text_center(screen, t, FONT_TINY, c, (round((95 + i * 110) * s), round(70 * s)))

    def draw_play_elements(self):
        for brick in self.bricks:
            brick.draw(screen)
        for pu in self.powerups:
            pu.draw(screen)
        self.paddle.draw(screen)
        for b in self.balls:
            b.draw(screen)
        for p in self.particles:
            p.draw(screen)
        for laser in self.lasers:
            laser.draw(screen)

    def draw_buttons(self, buttons):
        for _action, btn in buttons:
            hover = btn.rect.collidepoint(self.mouse_logical)
            btn.draw(screen, hover=hover)

    # ---------------- menu / submenu button layouts ----------------
    def build_menu_buttons(self):
        s = SCALE
        buttons = []
        start_rect = pygame.Rect(0, 0, round(300 * s), round(46 * s))
        start_rect.center = (WIDTH // 2, round(165 * s))
        buttons.append(("start", Button(start_rect, "START")))

        max_stage = CONFIG.get("max_stage_reached", 1)
        continue_rect = pygame.Rect(0, 0, round(300 * s), round(46 * s))
        continue_rect.center = (WIDTH // 2, round(220 * s))
        continue_label = f"CONTINUE (STAGE {max_stage})" if max_stage > 1 else "CONTINUE"
        buttons.append(("continue", Button(continue_rect, continue_label, enabled=max_stage > 1)))

        stage_select_rect = pygame.Rect(0, 0, round(300 * s), round(46 * s))
        stage_select_rect.center = (WIDTH // 2, round(275 * s))
        buttons.append(
            (
                "stage_select",
                Button(stage_select_rect, "STAGE SELECT", enabled=CONFIG.get("game_completed", False)),
            )
        )

        w, h = round(260 * s), round(54 * s)
        gap_x, gap_y = round(20 * s), round(14 * s)
        col_x = [WIDTH // 2 - w - gap_x // 2, WIDTH // 2 + gap_x // 2]
        row0_y = round(312 * s)
        row1_y = row0_y + h + gap_y
        row2_y = row1_y + h + gap_y

        r = pygame.Rect(col_x[0], row0_y, w, h)
        buttons.append(("highscores", Button(r, "CHECK HIGH SCORE")))
        r = pygame.Rect(col_x[1], row0_y, w, h)
        buttons.append(
            ("endless", Button(r, "ENDLESS MODE", enabled=CONFIG.get("game_completed", False)))
        )

        r = pygame.Rect(col_x[0], row1_y, w, h)
        buttons.append(
            ("fullscreen", Button(r, f"FULLSCREEN: {'ON' if CONFIG.get('fullscreen') else 'OFF'}"))
        )
        r = pygame.Rect(col_x[1], row1_y, w, h)
        buttons.append(("bgm", Button(r, f"BGM: {'ON' if BGM_ON else 'OFF'}")))

        r = pygame.Rect(col_x[0], row2_y, w, h)
        buttons.append(("sfx", Button(r, f"SOUND: {'ON' if SFX_ON else 'OFF'}")))
        r = pygame.Rect(col_x[1], row2_y, w, h)
        buttons.append(("quit", Button(r, "QUIT")))

        return buttons

    def build_highscores_buttons(self):
        s = SCALE
        back_r = pygame.Rect(0, 0, round(200 * s), round(50 * s))
        back_r.center = (WIDTH // 2, HEIGHT - round(70 * s))
        return [("back", Button(back_r, "BACK"))]

    def build_stage_select_buttons(self):
        s = SCALE
        buttons = []
        cols = 5
        btn_w, btn_h = round(140 * s), round(80 * s)
        gap = round(20 * s)
        total_w = cols * btn_w + (cols - 1) * gap
        start_x = WIDTH // 2 - total_w // 2
        start_y = round(220 * s)
        unlocked = CONFIG.get("game_completed", False)
        for i in range(TOTAL_STAGES):
            col, row = i % cols, i // cols
            r = pygame.Rect(
                start_x + col * (btn_w + gap), start_y + row * (btn_h + gap), btn_w, btn_h
            )
            buttons.append((f"stage_{i + 1}", Button(r, f"STAGE {i + 1}", enabled=unlocked)))
        back_r = pygame.Rect(0, 0, round(200 * s), round(50 * s))
        back_r.center = (WIDTH // 2, start_y + 2 * (btn_h + gap) + round(40 * s))
        buttons.append(("back", Button(back_r, "BACK")))
        return buttons

    def build_pause_buttons(self):
        s = SCALE
        buttons = []
        w, h = round(260 * s), round(50 * s)
        gap_x, gap_y = round(20 * s), round(12 * s)

        resume_r = pygame.Rect(0, 0, round(320 * s), round(54 * s))
        resume_r.center = (WIDTH // 2, round(150 * s))
        buttons.append(("resume", Button(resume_r, "RESUME")))

        col_x = [WIDTH // 2 - w - gap_x // 2, WIDTH // 2 + gap_x // 2]
        y0 = round(210 * s)
        row_y = [y0, y0 + h + gap_y, y0 + 2 * (h + gap_y)]

        r = pygame.Rect(col_x[0], row_y[0], w, h)
        buttons.append(("restart_stage", Button(r, "RESTART STAGE")))
        r = pygame.Rect(col_x[1], row_y[0], w, h)
        buttons.append(("sfx", Button(r, f"SOUND: {'ON' if SFX_ON else 'OFF'}")))

        r = pygame.Rect(col_x[0], row_y[1], w, h)
        buttons.append(
            ("fullscreen", Button(r, f"FULLSCREEN: {'ON' if CONFIG.get('fullscreen') else 'OFF'}"))
        )
        r = pygame.Rect(col_x[1], row_y[1], w, h)
        buttons.append(("bgm", Button(r, f"BGM: {'ON' if BGM_ON else 'OFF'}")))

        main_menu_r = pygame.Rect(0, 0, round(320 * s), round(54 * s))
        main_menu_r.center = (WIDTH // 2, row_y[2] + h // 2)
        buttons.append(("main_menu", Button(main_menu_r, "MAIN MENU")))

        return buttons

    def draw(self):
        self.draw_background()
        s = SCALE

        if self.state == STATE_MENU:
            draw_text_center(
                screen,
                "NEON BREAKOUT",
                FONT_BIG,
                CYAN,
                (WIDTH // 2, round(70 * s)),
                glow=(0, 60, 70),
            )
            draw_text_center(
                screen,
                "10 stages. Rare power-ups. Patience required.",
                FONT_SMALL,
                WHITE,
                (WIDTH // 2, round(118 * s)),
            )
            self.draw_buttons(self.build_menu_buttons())
            draw_text_center(
                screen,
                "Arrows/A-D or Mouse to move  •  SPACE/Click to launch  •  P/ESC to pause",
                FONT_TINY,
                GRAY,
                (WIDTH // 2, round(532 * s)),
            )
            draw_text_center(
                screen,
                "Ctrl / Alt shows or hides the mouse cursor during play",
                FONT_TINY,
                GRAY,
                (WIDTH // 2, round(554 * s)),
            )
            draw_text_center(
                screen,
                "made with ♥ by Rane Kun",
                FONT_TINY,
                GRAY,
                (WIDTH // 2, HEIGHT - round(24 * s)),
            )

        elif self.state == STATE_HIGHSCORES:
            draw_text_center(
                screen, "HIGH SCORES", FONT_BIG, CYAN, (WIDTH // 2, round(90 * s)), glow=(0, 60, 70)
            )
            if self.highscores:
                for i, entry in enumerate(self.highscores[:8]):
                    if entry.get("endless"):
                        loop_num = max(1, entry["stage"] - TOTAL_STAGES)
                        stage_label = f"Endless (loop {loop_num})"
                    else:
                        stage_label = f"Stage {entry['stage']}"
                    line = f"{i + 1}.  {entry['score']}  -  {stage_label}"
                    draw_text_center(
                        screen, line, FONT_SMALL, WHITE, (WIDTH // 2, round((170 + i * 38) * s))
                    )
            else:
                draw_text_center(
                    screen,
                    "No scores yet - go play!",
                    FONT_SMALL,
                    GRAY,
                    (WIDTH // 2, round(200 * s)),
                )
            self.draw_buttons(self.build_highscores_buttons())

        elif self.state == STATE_STAGE_SELECT:
            draw_text_center(
                screen,
                "STAGE SELECT",
                FONT_BIG,
                CYAN,
                (WIDTH // 2, round(100 * s)),
                glow=(0, 60, 70),
            )
            if not CONFIG.get("game_completed", False):
                draw_text_center(
                    screen,
                    "Clear all 10 stages to unlock",
                    FONT_SMALL,
                    GRAY,
                    (WIDTH // 2, round(160 * s)),
                )
            self.draw_buttons(self.build_stage_select_buttons())

        elif self.state in (STATE_READY, STATE_PLAY, STATE_PAUSED):
            self.draw_play_elements()
            self.draw_hud()
            self.draw_pause_button()
            if self.state == STATE_READY:
                ready_label = (
                    f"ENDLESS - LEVEL {self.stage - TOTAL_STAGES}"
                    if self.endless
                    else f"STAGE {self.stage}"
                )
                draw_text_center(
                    screen,
                    ready_label,
                    FONT_MED,
                    YELLOW,
                    (WIDTH // 2, HEIGHT // 2 - round(20 * s)),
                )
                draw_text_center(
                    screen,
                    "Get Ready! SPACE / Click to launch",
                    FONT_SMALL,
                    WHITE,
                    (WIDTH // 2, HEIGHT // 2 + round(25 * s)),
                )
            if self.state == STATE_PAUSED:
                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 170))
                screen.blit(overlay, (0, 0))
                draw_text_center(screen, "PAUSED", FONT_BIG, CYAN, (WIDTH // 2, round(88 * s)))
                self.draw_buttons(self.build_pause_buttons())
            elif self.resume_cooldown > 0:
                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 130))
                screen.blit(overlay, (0, 0))
                count = max(1, math.ceil(self.resume_cooldown))
                draw_text_center(
                    screen,
                    str(count),
                    FONT_BIG,
                    CYAN,
                    (WIDTH // 2, HEIGHT // 2),
                    glow=(0, 60, 70),
                )
                draw_text_center(
                    screen,
                    "Get ready to move...",
                    FONT_SMALL,
                    WHITE,
                    (WIDTH // 2, HEIGHT // 2 + round(60 * s)),
                )

        elif self.state == STATE_STAGE_CLEAR:
            self.draw_play_elements()
            self.draw_hud()
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            screen.blit(overlay, (0, 0))
            clear_title = (
                f"ENDLESS LEVEL {self.stage - TOTAL_STAGES} CLEAR!"
                if self.endless
                else f"STAGE {self.stage} CLEAR!"
            )
            draw_text_center(
                screen,
                clear_title,
                FONT_BIG,
                GREEN,
                (WIDTH // 2, HEIGHT // 2 - round(50 * s)),
                glow=(0, 60, 20),
            )
            draw_text_center(
                screen,
                f"+{self.stage_clear_bonus} bonus",
                FONT_MED,
                YELLOW,
                (WIDTH // 2, HEIGHT // 2 + round(10 * s)),
            )
            if self.endless:
                nxt = "Press SPACE / Click for next level"
            else:
                nxt = (
                    "Press SPACE / Click for next stage"
                    if self.stage < TOTAL_STAGES
                    else "Press SPACE / Click to finish"
                )
            draw_text_center(
                screen, nxt, FONT_SMALL, WHITE, (WIDTH // 2, HEIGHT // 2 + round(60 * s))
            )

        elif self.state == STATE_GAME_OVER:
            draw_text_center(
                screen,
                "GAME OVER",
                FONT_BIG,
                RED,
                (WIDTH // 2, HEIGHT // 2 - round(60 * s)),
                glow=(70, 0, 10),
            )
            draw_text_center(
                screen,
                f"Final Score: {self.score}",
                FONT_MED,
                WHITE,
                (WIDTH // 2, HEIGHT // 2 + round(5 * s)),
            )
            reached_label = (
                f"Reached Endless Level {self.stage - TOTAL_STAGES}"
                if self.endless
                else f"Reached Stage {self.stage}"
            )
            draw_text_center(
                screen,
                reached_label,
                FONT_SMALL,
                MAGENTA,
                (WIDTH // 2, HEIGHT // 2 + round(45 * s)),
            )
            if self.is_new_best:
                draw_text_center(
                    screen,
                    "NEW HIGH SCORE!",
                    FONT_SMALL,
                    YELLOW,
                    (WIDTH // 2, HEIGHT // 2 + round(75 * s)),
                )
            elif self.highscore_rank is not None:
                draw_text_center(
                    screen,
                    f"Rank #{self.highscore_rank + 1} high score",
                    FONT_TINY,
                    CYAN,
                    (WIDTH // 2, HEIGHT // 2 + round(75 * s)),
                )
            draw_text_center(
                screen,
                "R = restart   ESC = main menu",
                FONT_SMALL,
                YELLOW,
                (WIDTH // 2, HEIGHT // 2 + round(110 * s)),
            )

        elif self.state == STATE_VICTORY:
            draw_text_center(
                screen,
                "YOU CLEARED ALL 10 STAGES!",
                FONT_MED,
                GREEN,
                (WIDTH // 2, HEIGHT // 2 - round(60 * s)),
                glow=(0, 60, 20),
            )
            draw_text_center(
                screen,
                f"Final Score: {self.score}",
                FONT_BIG,
                YELLOW,
                (WIDTH // 2, HEIGHT // 2 + round(10 * s)),
            )
            if self.is_new_best:
                draw_text_center(
                    screen,
                    "NEW HIGH SCORE!",
                    FONT_SMALL,
                    YELLOW,
                    (WIDTH // 2, HEIGHT // 2 + round(55 * s)),
                )
            draw_text_center(
                screen,
                "R = play again   ESC = main menu",
                FONT_SMALL,
                WHITE,
                (WIDTH // 2, HEIGHT // 2 + round(90 * s)),
            )

    # ---------------- input ----------------
    def handle_launch(self):
        if self.resume_cooldown > 0:
            return
        if self.state in (STATE_READY, STATE_PLAY):
            launched_any = False
            for b in self.balls:
                if b.stuck:
                    b.launch_from(self.paddle)
                    launched_any = True
            if launched_any:
                play_sound("launch")
                log("Ball launched by player.")
                if self.state == STATE_READY:
                    # Skip the "Get Ready" pause (up to 1.2s) - the player already
                    # launched, so there's nothing left to wait for.
                    self.ready_timer = 0.0
                    self.state = STATE_PLAY
                    log("Launch during Ready - skipping straight to Play.")
        elif self.state == STATE_MENU:
            self.reset_full()
            play_sound("ui_click")
            log("Game started from menu via SPACE.")
        elif self.state == STATE_STAGE_CLEAR:
            play_sound("ui_click")
            self.next_stage()

    def quit_game(self):
        self.finalize_score()
        if getattr(self, "_geometry_dirty", False):
            save_config(CONFIG)
        log("Quitting.")
        pygame.quit()
        sys.exit()

    def handle_menu_action(self, action):
        if action == "start":
            self.reset_full()
        elif action == "continue":
            if CONFIG.get("max_stage_reached", 1) > 1:
                self.continue_game()
        elif action == "highscores":
            self.state = STATE_HIGHSCORES
        elif action == "fullscreen":
            toggle_fullscreen()
        elif action == "bgm":
            set_bgm(not BGM_ON)
        elif action == "sfx":
            set_sfx(not SFX_ON)
        elif action == "stage_select":
            if CONFIG.get("game_completed", False):
                self.state = STATE_STAGE_SELECT
        elif action == "endless":
            if CONFIG.get("game_completed", False):
                self.start_endless()
        elif action == "quit":
            self.quit_game()
        play_sound("ui_click")

    def handle_keydown(self, key):
        if key == pygame.K_ESCAPE:
            if self.state == STATE_MENU:
                self.quit_game()
            elif self.state in (STATE_HIGHSCORES, STATE_STAGE_SELECT):
                self.state = STATE_MENU
                play_sound("ui_click")
            elif self.state in (STATE_PLAY, STATE_READY, STATE_PAUSED):
                self.toggle_pause()
            elif self.state in (STATE_GAME_OVER, STATE_VICTORY, STATE_STAGE_CLEAR):
                self.finalize_score()
                self.state = STATE_MENU
                play_sound("ui_click")
            return
        if key == pygame.K_SPACE:
            self.handle_launch()
        if key == pygame.K_p and self.state in (STATE_PLAY, STATE_PAUSED, STATE_READY):
            self.toggle_pause()
        if key == pygame.K_r and self.state in (STATE_GAME_OVER, STATE_VICTORY):
            log("Restart requested.")
            if self.endless:
                self.start_endless()
            else:
                self.reset_full()
        if key == pygame.K_m:
            quick_toggle_mute()
        if key in (pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_LALT, pygame.K_RALT):
            if self.state in (STATE_PLAY, STATE_READY, STATE_PAUSED):
                currently_visible = pygame.mouse.get_visible()
                set_cursor_locked(currently_visible)  # visible -> lock it; hidden -> free it
                log(
                    f"Cursor toggled via Ctrl/Alt: now {'hidden+locked' if currently_visible else 'shown+free'}"
                )

    def handle_mouse_click(self, pos):
        if self.state == STATE_MENU:
            for action, btn in self.build_menu_buttons():
                if btn.hit(pos):
                    self.handle_menu_action(action)
                    return
            return

        if self.state == STATE_HIGHSCORES:
            for action, btn in self.build_highscores_buttons():
                if btn.hit(pos):
                    self.state = STATE_MENU
                    play_sound("ui_click")
                    return
            return

        if self.state == STATE_STAGE_SELECT:
            for action, btn in self.build_stage_select_buttons():
                if btn.hit(pos):
                    if action == "back":
                        self.state = STATE_MENU
                    elif action.startswith("stage_"):
                        self.start_at_stage(int(action.split("_")[1]))
                    play_sound("ui_click")
                    return
            return

        if self.state == STATE_PAUSED:
            for action, btn in self.build_pause_buttons():
                if btn.hit(pos):
                    if action == "resume":
                        self.toggle_pause()  # also re-hides the cursor
                    elif action == "main_menu":
                        self.finalize_score()
                        self.state = STATE_MENU
                        play_sound("ui_click")
                    elif action == "restart_stage":
                        self.restart_stage()
                        play_sound("ui_click")
                    else:
                        self.handle_menu_action(
                            action
                        )  # fullscreen / bgm / sfx / stage_select / quit
                    return
            return

        if self.state in (STATE_READY, STATE_PLAY) and self.pause_rect().collidepoint(pos):
            self.toggle_pause()
            return

        if self.state == STATE_STAGE_CLEAR:
            play_sound("ui_click")
            self.next_stage()
            return

        self.handle_launch()

    # ---------------- main loop ----------------
    def run(self):
        global window, PENDING_RESOLUTION
        last_mouse_x = 0
        mouse_pos = (0, 0)
        while True:
            dt = clock.tick(FPS) / 1000.0
            try:
                win_w, win_h = window.get_size()
                raw_mouse = pygame.mouse.get_pos()
                if win_w > 0 and win_h > 0:
                    mouse_pos = (raw_mouse[0] * WIDTH / win_w, raw_mouse[1] * HEIGHT / win_h)
                # else: window is mid-transition (e.g. fullscreen toggling) - keep last mouse_pos
                mouse_moved = mouse_pos[0] != last_mouse_x
                last_mouse_x = mouse_pos[0]

                now = pygame.time.get_ticks() / 1000.0
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        log("Window close event detected, quitting.")
                        self.quit_game()
                    elif event.type == pygame.KEYDOWN:
                        self.handle_keydown(event.key)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self.handle_mouse_click(mouse_pos)
                    elif event.type == pygame.VIDEORESIZE:
                        # Ignore resize events for a moment after a fullscreen toggle - SDL can
                        # synthesize one as part of that transition, and reacting to it here would
                        # call set_mode() again while the SDL2 Window object is mid-transition.
                        if not CONFIG.get("fullscreen", False) and now >= _suppress_resize_until:
                            new_w = max(MIN_WINDOW_W, event.w)
                            new_h = max(MIN_WINDOW_H, event.h)
                            window = pygame.display.set_mode((new_w, new_h), pygame.RESIZABLE)
                            CONFIG["window_w"], CONFIG["window_h"] = new_w, new_h
                            PENDING_RESOLUTION = (new_w, new_h)
                            self._geometry_dirty = True
                    elif hasattr(pygame, "WINDOWMOVED") and event.type == pygame.WINDOWMOVED:
                        if not CONFIG.get("fullscreen", False) and now >= _suppress_resize_until:
                            CONFIG["window_x"], CONFIG["window_y"] = event.x, event.y
                            self._geometry_dirty = True

                if self._geometry_dirty:
                    self._geometry_save_accum += dt
                    if self._geometry_save_accum > 1.5:
                        save_config(CONFIG)
                        self._geometry_dirty = False
                        self._geometry_save_accum = 0.0

                keys = pygame.key.get_pressed()
                self.update(dt, keys, mouse_pos, mouse_moved)
                self.draw()

                shake_offset = (0, 0)
                amt = 0.0
                if self.shake_time_left > 0:
                    frac = self.shake_time_left / max(0.001, self.shake_duration_total)
                    amt = self.shake_magnitude * frac
                if self.time_expired and self.state == STATE_PLAY:
                    amt = max(amt, 3.5)  # gentle ongoing tremor for the rest of the stage
                if amt > 0:
                    shake_offset = (
                        random.randint(-int(amt), int(amt)),
                        random.randint(-int(amt), int(amt)),
                    )
                present(shake_offset)
            except SystemExit:
                raise
            except Exception:
                # Last-resort safety net: log the full traceback but never let one bad frame
                # take the whole game down. If `window` ended up in a bad state, recover it.
                import traceback

                log("Unexpected error in main loop:\n" + traceback.format_exc())
                if window is None:
                    try:
                        window = pygame.display.set_mode((DESIGN_W, DESIGN_H), pygame.RESIZABLE)
                    except Exception:
                        pass


if __name__ == "__main__":
    log("--- NEON BREAKOUT STARTED ---")
    Game().run()
