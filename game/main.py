
#!/usr/bin/env python3
import asyncio
import base64
import pygame
import random
import json
import math
import re
import sys
from pathlib import Path

pygame.mixer.pre_init(44100, -16, 2, 512)
pygame.init()
pygame.joystick.init()

# Do not initialize SDL_mixer at import time on WebAssembly.
# Pygbag/browser audio becomes available after the display is created and
# the browser's media-engagement gate has been satisfied.
AUDIO_OK = False

WIDTH, HEIGHT = 1280, 800
FPS = 60
TITLE = "Bloody Math: Algebra Quest v1.6.0"

BG = (10, 10, 16)
PANEL = (22, 22, 32)
PANEL2 = (30, 30, 44)
WHITE = (238, 238, 242)
MUTED = (166, 166, 184)
RED = (225, 48, 58)
DARK_RED = (120, 24, 32)
CYAN = (48, 208, 220)
YELLOW = (238, 196, 58)
GREEN = (68, 206, 126)
ORANGE = (236, 136, 60)
PURPLE = (168, 92, 220)
BLUE = (78, 132, 235)

window = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption(TITLE)
screen = pygame.Surface((WIDTH, HEIGHT)).convert()
clock = pygame.time.Clock()
ACTIVE_PROGRESS = None

def available_resolutions():
    common = [
        (1280, 720), (1280, 800), (1366, 768), (1440, 900),
        (1600, 900), (1680, 1050), (1920, 1080), (1920, 1200),
        (2560, 1440), (2560, 1600), (3840, 2160)
    ]
    try:
        supported = pygame.display.list_modes()
        if supported == -1:
            supported = []
        supported = set(tuple(m) for m in supported)
        desktop = pygame.display.get_desktop_sizes()
        desktop = desktop[0] if desktop else (WIDTH, HEIGHT)
        opts = [r for r in common if (not supported or r in supported)]
        if tuple(desktop) not in opts:
            opts.append(tuple(desktop))
        opts = sorted(set(opts), key=lambda r: (r[0]*r[1], r[0], r[1]))
        return opts
    except Exception:
        return common

def display_resolution(settings):
    res = settings.get("fullscreen_resolution", [1920, 1080])
    try:
        return max(640, int(res[0])), max(480, int(res[1]))
    except Exception:
        return 1920, 1080

def apply_display_mode(progress):
    global window
    settings = ensure_settings(progress)
    fullscreen = bool(settings.get("fullscreen", False))
    try:
        if fullscreen:
            rw, rh = display_resolution(settings)
            window = pygame.display.set_mode((rw, rh), pygame.FULLSCREEN)
        else:
            # A standard decorated, resizable Linux window. The desktop window
            # manager supplies minimize/maximize/close buttons.
            size = settings.get("window_size", [1280, 800])
            ww = max(720, int(size[0]))
            wh = max(500, int(size[1]))
            window = pygame.display.set_mode((ww, wh), pygame.RESIZABLE)
    except Exception:
        settings["fullscreen"] = False
        settings["window_size"] = [1280, 800]
        window = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
    pygame.display.set_caption(TITLE)

def current_viewport():
    settings = ensure_settings(ACTIVE_PROGRESS) if ACTIVE_PROGRESS else {"scaling_mode":"FILL"}
    display = pygame.display.get_surface()
    ww, wh = display.get_size()
    mode = str(settings.get("scaling_mode", "FILL")).upper()
    if mode == "FIT":
        scale = min(ww / WIDTH, wh / HEIGHT)
        sw, sh = max(1, int(WIDTH * scale)), max(1, int(HEIGHT * scale))
        ox, oy = (ww - sw)//2, (wh - sh)//2
        return ox, oy, sw, sh
    return 0, 0, ww, wh

def present():
    display = pygame.display.get_surface()
    ox, oy, sw, sh = current_viewport()
    if (sw, sh) == (WIDTH, HEIGHT) and (ox, oy) == (0, 0):
        display.blit(screen, (0, 0))
    else:
        display.fill((0, 0, 0))
        scaled = pygame.transform.smoothscale(screen, (sw, sh))
        display.blit(scaled, (ox, oy))
    pygame.display.flip()

def logical_pos(pos):
    mx, my = pos
    ox, oy, sw, sh = current_viewport()
    if sw <= 0 or sh <= 0:
        return (-9999, -9999)
    if mx < ox or my < oy or mx >= ox+sw or my >= oy+sh:
        return (-9999, -9999)
    lx = int((mx - ox) * WIDTH / sw)
    ly = int((my - oy) * HEIGHT / sh)
    return (lx, ly)

def logical_mouse_pos():
    return logical_pos(pygame.mouse.get_pos())

def toggle_fullscreen(progress):
    settings = ensure_settings(progress)
    if not settings.get("fullscreen", False):
        try:
            ww, wh = pygame.display.get_surface().get_size()
            settings["window_size"] = [ww, wh]
        except Exception:
            pass
    settings["fullscreen"] = not bool(settings.get("fullscreen", False))
    apply_display_mode(progress)
    save_progress(progress)
    play_sfx("select")

FONT = pygame.font.Font(None, 34)
SMALL = pygame.font.Font(None, 26)
TINY = pygame.font.Font(None, 21)
BIG = pygame.font.Font(None, 58)
HUGE = pygame.font.Font(None, 82)

SAVE_DIR = Path.home() / ".local" / "share" / "bloody-math"
SAVE_FILE = SAVE_DIR / "progress.json"

AUDIO_DIR = Path(__file__).parent / "audio"
DIFFICULTIES = ["Easy", "Medium", "Hard", "Expert", "College Beast"]
SYMBOLS = ["^", "(", ")", "+", "-", "*", "/", "=", "<", ">", "!=", ",", ".", "sqrt(", "pi"]

SOUNDS = {}
WEB_SOUNDS = {}
WEB_AUDIO_READY = False
AUDIO_UNLOCKED = False
WEB_AUDIO_EVENT_CALLBACK = None

def ensure_settings(progress):
    settings = progress.setdefault("settings", {})
    settings.setdefault("music_volume", 0.35)
    settings.setdefault("sfx_volume", 0.55)
    settings.setdefault("difficulty", "Medium")
    settings.setdefault("fullscreen", False)
    settings.setdefault("fullscreen_resolution", [1920, 1080])
    settings.setdefault("window_size", [1280, 800])
    settings.setdefault("scaling_mode", "FILL")
    return settings

def apply_audio_settings(progress):
    settings = ensure_settings(progress)
    if sys.platform == "emscripten":
        try:
            music = WEB_SOUNDS.get("music")
            if music is not None:
                music.volume = float(settings["music_volume"])
            for name, sound in WEB_SOUNDS.items():
                if name != "music":
                    sound.volume = float(settings["sfx_volume"])
        except Exception:
            pass
        return
    if not AUDIO_OK:
        return
    try:
        pygame.mixer.music.set_volume(float(settings["music_volume"]))
        for sound in SOUNDS.values():
            sound.set_volume(float(settings["sfx_volume"]))
    except Exception:
        pass

def _web_audio_element(filename, volume, loop=False):
    if sys.platform != "emscripten":
        return None
    try:
        from js import document
        audio = document.createElement("audio")
        # /audio is copied to the GitHub Pages web root by the workflow.
        # Relative URL keeps this working under /bloody-math/ as well.
        audio.src = f"audio/{filename}"
        audio.preload = "auto"
        audio.loop = loop
        audio.volume = float(volume)
        audio.style.display = "none"
        document.body.appendChild(audio)
        return audio
    except Exception:
        return None

def _web_user_gesture(event=None):
    """Run directly from a DOM gesture so Edge grants media playback."""
    global AUDIO_UNLOCKED
    if sys.platform != "emscripten":
        return
    try:
        settings = ensure_settings(ACTIVE_PROGRESS)
        music = WEB_SOUNDS.get("music")
        if music is not None:
            music.volume = float(settings["music_volume"])
            music.currentTime = 0
            music.play()
            AUDIO_UNLOCKED = True
    except Exception:
        pass

def init_web_audio(progress):
    global WEB_AUDIO_READY, WEB_AUDIO_EVENT_CALLBACK
    if sys.platform != "emscripten":
        return False
    if WEB_AUDIO_READY:
        return True
    try:
        settings = ensure_settings(progress)
        for name in ("move", "world_move", "select", "correct", "wrong", "hint", "boss", "victory"):
            audio = _web_audio_element(
                f"{name}.ogg",
                settings["sfx_volume"],
                False
            )
            if audio is not None:
                WEB_SOUNDS[name] = audio

        music = _web_audio_element(
            "bloody_math_theme.ogg",
            settings["music_volume"],
            True
        )
        if music is not None:
            WEB_SOUNDS["music"] = music

        WEB_AUDIO_READY = bool(WEB_SOUNDS)

        # IMPORTANT: pygame's event queue reaches Python after the browser's
        # transient user-activation window. Register directly with Pygbag's
        # DOM EventTarget so Edge/Chrome sees play() inside the real gesture.
        if WEB_AUDIO_READY and WEB_AUDIO_EVENT_CALLBACK is None:
            import platform
            WEB_AUDIO_EVENT_CALLBACK = _web_user_gesture
            platform.EventTarget.addEventListener(None, "pointerdown", WEB_AUDIO_EVENT_CALLBACK)
            platform.EventTarget.addEventListener(None, "keydown", WEB_AUDIO_EVENT_CALLBACK)

        return WEB_AUDIO_READY
    except Exception:
        WEB_AUDIO_READY = False
        return False

def _web_play(audio, volume=None):
    if audio is None:
        return False
    try:
        if volume is not None:
            audio.volume = float(volume)
        audio.currentTime = 0
        result = audio.play()
        return True
    except Exception:
        return False

def init_audio(progress):
    global AUDIO_OK
    if sys.platform == "emscripten":
        # Browser audio is handled by native HTMLAudio elements. The first
        # call is made from a real browser input event, satisfying autoplay rules.
        return init_web_audio(progress)

    try:
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        AUDIO_OK = True
    except Exception:
        AUDIO_OK = False
        return False

    for name in ("move", "world_move", "select", "correct", "wrong", "hint", "boss", "victory"):
        if name in SOUNDS:
            continue
        p = AUDIO_DIR / f"{name}.ogg"
        if p.exists():
            try:
                SOUNDS[name] = pygame.mixer.Sound(str(p))
            except Exception:
                pass

    apply_audio_settings(progress)

    theme = AUDIO_DIR / "bloody_math_theme.ogg"
    if theme.exists():
        try:
            pygame.mixer.music.load(str(theme))
            pygame.mixer.music.set_volume(float(ensure_settings(progress)["music_volume"]))
            pygame.mixer.music.play(-1)
        except Exception:
            pass

    return True

def unlock_audio(progress=None):
    global AUDIO_UNLOCKED
    progress = progress or ACTIVE_PROGRESS
    if progress is None:
        return

    if sys.platform == "emscripten":
        if init_web_audio(progress):
            settings = ensure_settings(progress)
            music = WEB_SOUNDS.get("music")
            if music is not None:
                _web_play(music, settings["music_volume"])
            AUDIO_UNLOCKED = True
        return

    if not AUDIO_UNLOCKED:
        init_audio(progress)
    AUDIO_UNLOCKED = AUDIO_OK

def get_events():
    events = pygame.event.get()
    if not AUDIO_UNLOCKED:
        for e in events:
            if e.type in (
                pygame.MOUSEBUTTONDOWN,
                pygame.MOUSEBUTTONUP,
                pygame.KEYDOWN,
                pygame.JOYBUTTONDOWN,
                pygame.FINGERDOWN,
            ):
                unlock_audio()
                break
    return events

def play_sfx(name):
    try:
        if sys.platform == "emscripten":
            if not WEB_AUDIO_READY and ACTIVE_PROGRESS is not None:
                init_web_audio(ACTIVE_PROGRESS)
            sound = WEB_SOUNDS.get(name)
            if sound is not None:
                _web_play(sound, ensure_settings(ACTIVE_PROGRESS)["sfx_volume"])
            return
        if AUDIO_OK and name in SOUNDS:
            SOUNDS[name].play()
    except Exception:
        pass

def math_key_text(event):
    # Reliable math symbols for common US keyboard layouts.
    shift = bool(event.mod & pygame.KMOD_SHIFT)
    shifted = {
        pygame.K_1:"!", pygame.K_2:"@", pygame.K_3:"#", pygame.K_4:"$",
        pygame.K_5:"%", pygame.K_6:"^", pygame.K_7:"&", pygame.K_8:"*",
        pygame.K_9:"(", pygame.K_0:")", pygame.K_MINUS:"_",
        pygame.K_EQUALS:"+", pygame.K_COMMA:"<", pygame.K_PERIOD:">",
        pygame.K_SLASH:"?", pygame.K_BACKSLASH:"|",
    }
    plain = {
        pygame.K_MINUS:"-", pygame.K_EQUALS:"=", pygame.K_COMMA:",",
        pygame.K_PERIOD:".", pygame.K_SLASH:"/", pygame.K_BACKSLASH:"\\",
    }
    # Numeric keypad support. In browser builds, the keypad can arrive with
    # a different keycode (especially when NumLock is off), while the physical
    # keypad scancode remains identifiable. Handle both key and scancode.
    keypad = {
        pygame.K_KP0:"0", pygame.K_KP1:"1", pygame.K_KP2:"2",
        pygame.K_KP3:"3", pygame.K_KP4:"4", pygame.K_KP5:"5",
        pygame.K_KP6:"6", pygame.K_KP7:"7", pygame.K_KP8:"8",
        pygame.K_KP9:"9", pygame.K_KP_PERIOD:".",
        pygame.K_KP_DIVIDE:"/", pygame.K_KP_MULTIPLY:"*",
        pygame.K_KP_MINUS:"-", pygame.K_KP_PLUS:"+",
    }
    if shift and event.key in shifted:
        return shifted[event.key]
    if event.key in keypad:
        return keypad[event.key]
    try:
        keypad_scancodes = {
            pygame.key.get_scancode_from_key(k): v for k, v in keypad.items()
        }
        if getattr(event, "scancode", -1) in keypad_scancodes:
            return keypad_scancodes[event.scancode]
    except Exception:
        pass
    if event.key in plain:
        return plain[event.key]
    if event.unicode and event.unicode.isprintable():
        return event.unicode
    return ""

async def difficulty_select(progress, automatic=False):
    if automatic:
        return "Auto"
    settings = ensure_settings(progress)
    idx = DIFFICULTIES.index(settings.get("difficulty", "Medium")) if settings.get("difficulty") in DIFFICULTIES else 1
    while True:
        # Five difficulty cards: 3 on the first row, 2 centered on the second.
        rects=[]
        for i in range(len(DIFFICULTIES)):
            if i < 3:
                rects.append(pygame.Rect(90+i*400,285,360,78))
            else:
                rects.append(pygame.Rect(290+(i-3)*400,425,360,78))
        back_rect=pygame.Rect(WIDTH//2-100,650,200,46)
        for e in get_events():
            if e.type == pygame.QUIT:
                return None
            if e.type == pygame.MOUSEMOTION:
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        if idx != i: play_sfx("move")
                        idx=i; break
            if e.type == pygame.MOUSEBUTTONDOWN and e.button==1:
                if back_rect.collidepoint(logical_pos(e.pos)):
                    play_sfx("select"); return None
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        idx=i
                        settings["difficulty"]=DIFFICULTIES[idx]
                        save_progress(progress); play_sfx("select")
                        return DIFFICULTIES[idx]
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
                    idx = (idx - 1) % len(DIFFICULTIES); play_sfx("move")
                elif e.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s):
                    idx = (idx + 1) % len(DIFFICULTIES); play_sfx("move")
                elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                    settings["difficulty"] = DIFFICULTIES[idx]
                    save_progress(progress); play_sfx("select")
                    return DIFFICULTIES[idx]
                elif e.key == pygame.K_ESCAPE:
                    return None
        draw_background()
        header("DIFFICULTY")
        draw_text("SELECT DIFFICULTY", BIG, WHITE, WIDTH//2, 150, center=True)
        desc = {
            "Easy":"Smaller values and simpler calculations.",
            "Medium":"Balanced college practice.",
            "Hard":"Larger values and tougher calculations.",
            "Expert":"Maximum numerical difficulty for exam prep.",
            "College Beast":"Long multi-step college-style equations. Bring your scratch paper.",
        }
        for i,name in enumerate(DIFFICULTIES):
            button(rects[i],name.upper(),i==idx)
            draw_wrapped(desc[name],TINY,MUTED,rects[i].x,rects[i].bottom+12,rects[i].w)
        draw_text("College Beast adds multi-step problems; Challenge Mode climbs to it at the end.", SMALL, CYAN, WIDTH//2, 585, center=True)
        button(back_rect,"BACK",False)
        draw_text("Mouse / Arrow keys / WASD supported", TINY, MUTED, WIDTH//2, 720, center=True)
        present(); clock.tick(FPS); await asyncio.sleep(0)

def scaled_randint(lo, hi, difficulty):
    if difficulty == "Easy":
        if lo < 0 < hi:
            lo = int(math.ceil(lo * 0.6))
            hi = int(math.floor(hi * 0.6))
        elif lo >= 0:
            hi = max(lo, lo + max(1, int((hi-lo)*0.55)))
    elif difficulty == "Hard":
        if lo < 0: lo = int(lo * 1.35)
        if hi > 0: hi = int(math.ceil(hi * 1.35))
    elif difficulty == "Expert":
        if lo < 0: lo = int(lo * 1.65)
        if hi > 0: hi = int(math.ceil(hi * 1.65))
    elif difficulty == "College Beast":
        if lo < 0: lo = int(lo * 2.0)
        if hi > 0: hi = int(math.ceil(hi * 2.0))
    if lo > hi:
        lo, hi = hi, lo
    return random.randint(lo, hi)

def challenge_difficulty(qnum, total):
    ratio = (qnum-1) / max(1, total-1)
    if ratio < .20: return "Easy"
    if ratio < .40: return "Medium"
    if ratio < .65: return "Hard"
    if ratio < .85: return "Expert"
    return "College Beast"


WORLD_DATA = [
    ("World 1", "Algebra Foundations", [
        "Real Numbers: Algebra Essentials",
        "Exponents and Scientific Notation",
        "Radicals and Rational Exponents",
        "Polynomials",
        "Factoring Polynomials",
        "Rational Expressions",
    ]),
    ("World 2", "Equations and Inequalities", [
        "The Rectangular Coordinate System and Graphs",
        "Linear Equations in One Variable",
        "Models and Applications",
        "Complex Numbers",
        "Quadratic Equations",
        "Other Types of Equations",
        "Linear Inequalities and Absolute Value Inequalities",
    ]),
    ("World 3", "Functions", [
        "Functions and Function Notation",
        "Domain and Range",
        "Rates of Change and Behavior of Graphs",
        "Composition of Functions",
        "Transformation of Functions",
        "Inverse Functions",
    ]),
    ("World 4", "Polynomial and Rational Functions", [
        "Quadratic Functions",
        "Power Functions and Polynomial Functions",
        "Graphs of Polynomial Functions",
        "Dividing Polynomials",
        "Zeros of Polynomials",
        "Rational Functions",
    ]),
    ("World 5", "Exponential and Logarithmic Functions", [
        "Exponential Functions",
        "Graphs of Exponential Functions",
        "Logarithmic Functions",
        "Graphs of Logarithmic Functions",
        "Logarithmic Properties",
        "Exponential and Logarithmic Equations",
        "Exponential and Logarithmic Models",
    ]),
    ("World 6", "Systems of Equations", [
        "Systems of Linear Equations: Two Variables",
        "Systems of Linear Equations: Three Variables",
        "Systems of Nonlinear Equations and Inequalities: Two Variables",
    ]),
    ("World 7", "Conic Sections", [
        "Circles",
        "The Ellipse",
        "The Hyperbola",
        "The Parabola",
    ]),
    ("World 8", "Sequences and Series", [
        "Sequences and Their Notations",
        "Arithmetic Sequences",
        "Geometric Sequences",
        "Series and Their Notations",
    ]),
]

ALL_TOPICS = [t for _, _, topics in WORLD_DATA for t in topics]

def load_progress():
    default = {
        "topics": {},
        "world_bosses": {},
        "total_correct": 0,
        "total_attempts": 0,
        "best_combo": 0,
        "settings": {
            "music_volume": 0.35,
            "sfx_volume": 0.55,
            "difficulty": "Medium",
            "fullscreen": False,
            "fullscreen_resolution": [1920, 1080],
            "window_size": [1280, 800],
            "scaling_mode": "FILL",
        },
    }
    try:
        if SAVE_FILE.exists():
            data = json.loads(SAVE_FILE.read_text())
            for k, v in default.items():
                data.setdefault(k, v)
            return data
    except Exception:
        pass
    return default

def save_progress(progress):
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        SAVE_FILE.write_text(json.dumps(progress, indent=2))
    except Exception:
        pass

def topic_stats(progress, topic):
    rec = progress["topics"].setdefault(topic, {"correct": 0, "attempts": 0, "best_combo": 0})
    return rec

def pct(correct, attempts):
    return 0 if attempts == 0 else int(round(correct * 100 / attempts))

def draw_text(text, font, color, x, y, center=False):
    surf = font.render(str(text), True, color)
    rect = surf.get_rect()
    if center:
        rect.center = (x, y)
    else:
        rect.topleft = (x, y)
    screen.blit(surf, rect)
    return rect

def wrap_text(text, font, max_width):
    words = str(text).split()
    lines, line = [], ""
    for word in words:
        test = word if not line else line + " " + word
        if font.size(test)[0] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines

def draw_wrapped(text, font, color, x, y, max_width, line_h=None):
    line_h = line_h or font.get_linesize() + 3
    for line in wrap_text(text, font, max_width):
        draw_text(line, font, color, x, y)
        y += line_h
    return y

def button(rect, label, selected=False, enabled=True):
    hovered = enabled and rect.collidepoint(logical_mouse_pos())
    active = selected or hovered
    color = RED if active else PANEL2
    if not enabled:
        color = (42, 42, 48)
    pygame.draw.rect(screen, color, rect, border_radius=8)
    pygame.draw.rect(screen, WHITE if active else (82, 82, 98), rect, 2, border_radius=8)
    draw_text(label, SMALL, WHITE if enabled else MUTED, rect.centerx, rect.centery, center=True)

def normalize(s):
    s = s.strip().lower().replace(" ", "")
    s = s.replace("^2", "²")
    s = s.replace("−", "-")
    return s

def num_eq(user, answer, tol=1e-6):
    try:
        return abs(float(user) - float(answer)) <= tol
    except Exception:
        return normalize(user) == normalize(str(answer))

def unordered_pair_eq(user, pair):
    nums = re.findall(r"-?\d+(?:\.\d+)?", user)
    if len(nums) < 2:
        return False
    vals = [float(nums[0]), float(nums[1])]
    return all(any(abs(v - p) < 1e-6 for v in vals) for p in pair)

class Problem:
    def __init__(self, prompt, answer, steps, hint="", checker=None, display_answer=None):
        self.prompt = prompt
        self.answer = str(answer)
        self.steps = steps
        self.hint = hint or (steps[0] if steps else "Work one step at a time.")
        self.checker = checker
        self.display_answer = display_answer or self.answer

    def check(self, user):
        if self.checker:
            return self.checker(user)
        return num_eq(user, self.answer)

def lesson_for(topic):
    lessons = {
        "Real Numbers: Algebra Essentials": ("Real numbers include rational and irrational numbers.", [
            "Follow the order of operations: grouping, exponents, multiplication/division, addition/subtraction.",
            "Use absolute value as distance from zero.",
            "Combine like terms only when variable parts match."
        ]),
        "Exponents and Scientific Notation": ("Exponents describe repeated multiplication.", [
            "Product rule: x^a · x^b = x^(a+b).",
            "Quotient rule: x^a / x^b = x^(a-b).",
            "Scientific notation has the form a × 10^n where 1 ≤ |a| < 10."
        ]),
        "Radicals and Rational Exponents": ("Radicals and rational exponents describe roots.", [
            "sqrt(a^2) = |a| for real a.",
            "a^(m/n) = n-th root of a^m.",
            "Simplify perfect-square factors whenever possible."
        ]),
        "Polynomials": ("A polynomial is a sum of terms with nonnegative integer exponents.", [
            "Combine like terms.",
            "When multiplying, distribute every term.",
            "The degree is the greatest exponent after simplification."
        ]),
        "Factoring Polynomials": ("Factoring reverses multiplication.", [
            "Always check for a greatest common factor first.",
            "For x^2 + bx + c, find two numbers that multiply to c and add to b.",
            "Difference of squares: a^2 - b^2 = (a-b)(a+b)."
        ]),
        "Rational Expressions": ("A rational expression is a quotient of polynomials.", [
            "Factor numerator and denominator.",
            "Cancel common factors, not individual terms.",
            "State restrictions from the original denominator."
        ]),
        "The Rectangular Coordinate System and Graphs": ("Points are written as ordered pairs (x, y).", [
            "Move x units horizontally, then y units vertically.",
            "Slope measures vertical change over horizontal change.",
            "Intercepts occur where a graph crosses an axis."
        ]),
        "Linear Equations in One Variable": ("Solve by isolating the variable.", [
            "Undo addition or subtraction first.",
            "Undo multiplication or division next.",
            "Perform the same operation on both sides."
        ]),
        "Models and Applications": ("Translate a real situation into an equation.", [
            "Define the unknown variable.",
            "Write an equation that matches the relationships.",
            "Solve and interpret the result with units."
        ]),
        "Complex Numbers": ("Complex numbers use i, where i^2 = -1.", [
            "Write answers in a + bi form.",
            "Combine real parts and imaginary parts separately.",
            "Powers of i repeat every four powers."
        ]),
        "Quadratic Equations": ("Quadratic equations contain a squared variable.", [
            "Set the equation equal to zero.",
            "Try factoring first.",
            "Otherwise use completing the square or the quadratic formula."
        ]),
        "Other Types of Equations": ("Some equations require substitution or special algebraic structure.", [
            "Identify the repeating expression.",
            "Substitute a temporary variable when useful.",
            "Check solutions in the original equation."
        ]),
        "Linear Inequalities and Absolute Value Inequalities": ("Inequalities describe ranges of values.", [
            "Solve like an equation.",
            "Reverse the inequality when multiplying or dividing by a negative.",
            "Absolute value inequalities often split into two cases."
        ]),
        "Functions and Function Notation": ("A function assigns exactly one output to each input.", [
            "f(x) is another name for the output.",
            "To evaluate f(a), replace x with a.",
            "A vertical line test checks whether a graph is a function."
        ]),
        "Domain and Range": ("Domain is the set of inputs; range is the set of outputs.", [
            "Exclude denominator values that make division by zero.",
            "For even roots, require the radicand to be nonnegative.",
            "Read graph endpoints carefully using open/closed notation."
        ]),
        "Rates of Change and Behavior of Graphs": ("Average rate of change is slope between two points.", [
            "Use [f(b)-f(a)]/(b-a).",
            "Increasing graphs rise left to right.",
            "Decreasing graphs fall left to right."
        ]),
        "Composition of Functions": ("Composition means putting one function inside another.", [
            "(f ∘ g)(x) = f(g(x)).",
            "Evaluate the inside function first.",
            "Then substitute that result into the outside function."
        ]),
        "Transformation of Functions": ("Transformations move or reshape a parent graph.", [
            "f(x)+k shifts vertically.",
            "f(x-h) shifts horizontally.",
            "A negative outside reflects across the x-axis."
        ]),
        "Inverse Functions": ("An inverse reverses a function.", [
            "Replace f(x) with y.",
            "Swap x and y.",
            "Solve for y, then rename it f^-1(x)."
        ]),
        "Quadratic Functions": ("Quadratic functions graph as parabolas.", [
            "Vertex form: a(x-h)^2+k has vertex (h,k).",
            "The sign of a controls opening direction.",
            "The axis of symmetry is x = h."
        ]),
        "Power Functions and Polynomial Functions": ("Power functions have the form kx^p.", [
            "Even powers are symmetric about the y-axis.",
            "Odd powers are symmetric about the origin.",
            "Leading terms control end behavior."
        ]),
        "Graphs of Polynomial Functions": ("Polynomial graphs are continuous and shaped by degree and zeros.", [
            "Zeros are x-intercepts.",
            "Multiplicity affects whether the graph crosses or touches.",
            "End behavior follows the leading term."
        ]),
        "Dividing Polynomials": ("Polynomial division works like numerical long division.", [
            "Divide leading terms.",
            "Multiply and subtract.",
            "Repeat until the remainder degree is smaller."
        ]),
        "Zeros of Polynomials": ("Zeros are input values where f(x)=0.", [
            "Factor when possible.",
            "Use the Rational Zero Theorem for candidates.",
            "A zero r corresponds to factor (x-r)."
        ]),
        "Rational Functions": ("Rational functions are quotients of polynomials.", [
            "Denominator zeros are excluded from the domain.",
            "Uncancelled denominator zeros create vertical asymptotes.",
            "Compare degrees to determine horizontal behavior."
        ]),
        "Exponential Functions": ("Exponential functions have a variable in the exponent.", [
            "For b>1, b^x grows.",
            "For 0<b<1, b^x decays.",
            "The y-intercept of b^x is (0,1)."
        ]),
        "Graphs of Exponential Functions": ("Exponential graphs approach a horizontal asymptote.", [
            "y=b^x has asymptote y=0.",
            "Vertical shifts move the asymptote.",
            "Horizontal shifts move key points."
        ]),
        "Logarithmic Functions": ("Logarithms are inverses of exponential functions.", [
            "log_b(x)=y means b^y=x.",
            "The input of a logarithm must be positive.",
            "log_b(1)=0."
        ]),
        "Graphs of Logarithmic Functions": ("Logarithmic graphs are inverse reflections of exponentials.", [
            "y=log_b(x) has vertical asymptote x=0.",
            "It passes through (1,0).",
            "Transformations shift the asymptote and graph."
        ]),
        "Logarithmic Properties": ("Log properties expand or condense expressions.", [
            "log(MN)=log M+log N.",
            "log(M/N)=log M-log N.",
            "log(M^p)=p log M."
        ]),
        "Exponential and Logarithmic Equations": ("Use inverse operations to solve exponential and logarithmic equations.", [
            "Rewrite with a common base when possible.",
            "Otherwise apply logarithms.",
            "For logs, verify that every argument remains positive."
        ]),
        "Exponential and Logarithmic Models": ("Exponential models describe growth and decay.", [
            "A common model is A=A0(1+r)^t.",
            "Growth uses r>0; decay uses a factor below 1.",
            "Interpret the result with correct units."
        ]),
        "Systems of Linear Equations: Two Variables": ("A solution satisfies both equations.", [
            "Use substitution, elimination, or graphing.",
            "Elimination works well when coefficients can cancel.",
            "Check the ordered pair in both equations."
        ]),
        "Systems of Linear Equations: Three Variables": ("A three-variable system seeks an ordered triple.", [
            "Eliminate one variable from two pairs of equations.",
            "Solve the resulting two-variable system.",
            "Back-substitute to find the third variable."
        ]),
        "Systems of Nonlinear Equations and Inequalities: Two Variables": ("Nonlinear systems can intersect at multiple points.", [
            "Use substitution when one equation is easy to solve for a variable.",
            "Graphing shows intersection points visually.",
            "For inequalities, test regions and respect boundary types."
        ]),
        "Circles": ("A circle is all points a fixed distance from a center.", [
            "Standard form: (x-h)^2+(y-k)^2=r^2.",
            "Center is (h,k).",
            "Radius is r."
        ]),
        "The Ellipse": ("An ellipse has two focal directions and two axis lengths.", [
            "Standard form centers at (h,k).",
            "The larger denominator lies under the major-axis variable.",
            "Vertices lie along the major axis."
        ]),
        "The Hyperbola": ("A hyperbola has two separate branches.", [
            "One squared term is positive and one is negative.",
            "The positive term identifies the transverse axis.",
            "Asymptotes guide the graph."
        ]),
        "The Parabola": ("A parabola is the set of points equidistant from a focus and directrix.", [
            "(x-h)^2=4p(y-k) opens vertically.",
            "(y-k)^2=4p(x-h) opens horizontally.",
            "The sign of p determines direction."
        ]),
        "Sequences and Their Notations": ("A sequence is an ordered list of terms.", [
            "a_n denotes the nth term.",
            "Explicit formulas calculate a term directly.",
            "Recursive formulas use earlier terms."
        ]),
        "Arithmetic Sequences": ("Arithmetic sequences have a constant difference.", [
            "a_n=a_1+(n-1)d.",
            "d is the common difference.",
            "Subtract consecutive terms to find d."
        ]),
        "Geometric Sequences": ("Geometric sequences have a constant ratio.", [
            "a_n=a_1 r^(n-1).",
            "r is the common ratio.",
            "Divide consecutive terms to find r."
        ]),
        "Series and Their Notations": ("A series is the sum of sequence terms.", [
            "Arithmetic sum: S_n=n(a_1+a_n)/2.",
            "Geometric sum: S_n=a_1(1-r^n)/(1-r), r≠1.",
            "Sigma notation compactly represents repeated addition."
        ]),
    }
    return lessons.get(topic, ("Study the core definition and connect each algebraic step to a property.", [
        "Read the expression carefully.",
        "Apply one valid transformation at a time.",
        "Check your result in the original problem."
    ]))

def make_problem(topic, difficulty="Medium"):
    r = random
    rr = lambda lo, hi: scaled_randint(lo, hi, difficulty)

    # COLLEGE BEAST: deliberately longer, multi-step problems modeled after
    # the kind of algebra work that requires several transformations.
    if difficulty == "College Beast":
        if topic == "Linear Equations in One Variable":
            for _ in range(50):
                x = r.randint(-8, 8) or 5
                d = r.choice([2, 3, 4, 5, 6])
                a = r.choice([2, 3, 4, 5, 7, 8])
                b = r.randint(-15, 15)
                while (a*x + b) % d != 0:
                    b += 1
                c = r.randint(-6, 6)
                e = r.choice([1, 2, 3, 4])
                f = (a*x + b)//d + c - e*x
                if abs(f) <= 40:
                    lhs = f"({a}x {b:+})/{d} {c:+}"
                    rhs = f"{e}x {f:+}"
                    steps = [
                        f"Start with {lhs} = {rhs}.",
                        f"Multiply every term by {d}: {a}x {b:+} {d*c:+} = {d*e}x {d*f:+}.",
                        f"Combine constants: {a}x {b + d*c:+} = {d*e}x {d*f:+}.",
                        "Move x-terms to one side and constants to the other.",
                        f"Divide by the remaining coefficient to get x={x}."
                    ]
                    return Problem(f"Solve the multi-step equation: {lhs} = {rhs}. Enter x.", x, steps)

        if topic == "Rational Expressions":
            a = r.randint(2, 9)
            b = r.randint(1, 8)
            target = r.choice([n for n in range(-8, 13) if n != a])
            c = target + a + b
            prompt = f"Solve: (x^2-{a*a})/(x-{a}) + {b} = {c}. State the solution."
            steps = [
                f"Factor the numerator: x^2-{a*a}=(x-{a})(x+{a}).",
                f"Cancel the common factor x-{a}, keeping the restriction x≠{a}.",
                f"Now solve x+{a}+{b}={c}.",
                f"Subtract {a}+{b}: x={target}.",
                f"Check the restriction: {target}≠{a}, so the solution is valid."
            ]
            return Problem(prompt, target, steps)

        if topic == "Functions and Function Notation":
            a,b,c,d,e,f = [r.choice([-4,-3,-2,2,3,4]) for _ in range(6)]
            x = r.randint(-4,4)
            fx = a*x+b
            gx = c*fx+d
            ans = e*gx+f
            return Problem(
                f"Given f(x)={a}x{b:+}, g(x)={c}x{d:+}, and h(x)={e}x{f:+}, find h(g(f({x}))).",
                ans,
                [
                    f"First evaluate f({x})={a}({x}){b:+}={fx}.",
                    f"Then evaluate g({fx})={c}({fx}){d:+}={gx}.",
                    f"Finally evaluate h({gx})={e}({gx}){f:+}={ans}.",
                    f"Therefore h(g(f({x})))={ans}."
                ]
            )

        if topic == "Composition of Functions":
            a,b,c,d,e,f = [r.choice([-4,-3,-2,2,3,4]) for _ in range(6)]
            x = r.randint(-4,4)
            hx = e*x+f
            gx = c*hx+d
            ans = a*gx+b
            return Problem(
                f"Let f(x)={a}x{b:+}, g(x)={c}x{d:+}, h(x)={e}x{f:+}. Find (f∘g∘h)({x}).",
                ans,
                [
                    f"Start inside: h({x})={e}({x}){f:+}={hx}.",
                    f"Next: g({hx})={c}({hx}){d:+}={gx}.",
                    f"Finally: f({gx})={a}({gx}){b:+}={ans}.",
                    f"So (f∘g∘h)({x})={ans}."
                ]
            )

        if topic == "Systems of Linear Equations: Three Variables":
            x,y,z = [r.randint(-4,4) for _ in range(3)]
            rows=[]
            while len(rows)<3:
                coeff=[r.choice([-3,-2,-1,1,2,3]) for _ in range(3)]
                if coeff not in [row[:3] for row in rows]:
                    rows.append(coeff+[coeff[0]*x+coeff[1]*y+coeff[2]*z])
            (a,b,c,e),(d,g,h,j),(k,l,m,n)=rows
            prompt=(f"Solve the system: {a}x{b:+}y{c:+}z={e}; "
                    f"{d}x{g:+}y{h:+}z={j}; {k}x{l:+}y{m:+}z={n}. Enter (x,y,z).")
            disp=f"({x},{y},{z})"
            steps=[
                "Use elimination to eliminate one variable from two pairs of equations.",
                "Solve the resulting two-variable system.",
                f"Substitute back to recover z={z}.",
                f"Then x={x} and y={y}.",
                f"Solution: ({x},{y},{z}). Check all three original equations."
            ]
            return Problem(prompt, disp, steps, checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

        if topic == "Quadratic Equations":
            p = r.randint(-9,9)
            q = r.randint(-9,9)
            while q == p:
                q = r.randint(-9,9)
            b = -(p+q)
            c = p*q
            k = r.choice([2,3,4])
            prompt = f"Solve: {k}(x^2 {b:+}x {c:+})/{k} = 0. Enter both roots."
            pair=sorted([p,q])
            disp=f"{pair[0]}, {pair[1]}"
            steps=[
                f"Cancel the common factor {k} from both sides.",
                f"You get x^2 {b:+}x {c:+}=0.",
                f"Factor: (x-{p})(x-{q})=0.",
                f"Set each factor equal to zero: x={p} or x={q}.",
                f"Enter both roots: {disp}."
            ]
            return Problem(prompt, disp, steps, checker=lambda u: unordered_pair_eq(u,pair), display_answer=disp)

        if topic == "Linear Inequalities and Absolute Value Inequalities":
            x=r.randint(-6,6)
            d=r.choice([2,3,4,5])
            a=r.choice([2,3,4,5])
            b=r.randint(-12,12)
            boundary = x
            c = (a*boundary+b)/d
            if not c.is_integer():
                # Regenerate through a divisible construction.
                c = (a*boundary+b)//d
            prompt=f"Solve: ({a}x {b:+})/{d} > {c:g}. Enter the solution set as x>number."
            ans=f"x>{boundary}"
            steps=[
                f"Multiply both sides by {d} (positive, so the inequality direction stays the same).",
                f"Then {a}x {b:+} > {int(c*d)}.",
                f"Move {b:+} to the other side and divide by {a}.",
                f"Solution: {ans}."
            ]
            return Problem(prompt, ans, steps, checker=lambda u: normalize(u)==normalize(ans), display_answer=ans)

        if topic == "Exponential and Logarithmic Equations":
            base=r.choice([2,3,5])
            target_x=r.randint(2,5)
            shift=r.choice([-3,-2,-1,1,2,3])
            exponent=target_x+shift
            rhs=base**exponent
            prompt=f"Solve: {base}^(x {shift:+}) = {rhs}. Enter x."
            steps=[
                f"Rewrite {rhs} as a power of {base}: {rhs}={base}^{exponent}.",
                f"Set exponents equal: x {shift:+}={exponent}.",
                f"Solve: x={target_x}."
            ]
            return Problem(prompt,target_x,steps)

        if topic == "Factoring Polynomials":
            p=r.randint(-9,9) or 3
            q=r.randint(-9,9) or -4
            b=p+q; c=p*q
            prompt=f"Factor completely: x^2 {b:+}x {c:+} + 0x. Enter the factored form."
            disp=f"(x{p:+})(x{q:+})"
            return Problem(prompt,disp,[
                f"Find two numbers whose product is {c} and sum is {b}.",
                f"Those numbers are {p} and {q}.",
                f"Factor: {disp}."
            ],checker=lambda u: normalize(u) in {normalize(disp),normalize(f'(x{q:+})(x{p:+})')},display_answer=disp)

        # Other topics keep their existing generator, but with Beast-sized values.

    if topic == "Real Numbers: Algebra Essentials":
        a,b,c = rr(2,9), rr(2,9), rr(2,6)
        ans = a + b*c
        return Problem(f"Evaluate: {a} + {b}({c})", ans,
                       [f"Multiply first: {b}({c}) = {b*c}.", f"Add: {a} + {b*c} = {ans}."])

    if topic == "Exponents and Scientific Notation":
        a,b = rr(2,6), rr(2,6)
        ans = a+b
        return Problem(f"Simplify the exponent: x^{a} · x^{b} = x^?", ans,
                       ["Use the product rule for equal bases.", f"Add exponents: {a}+{b}={ans}."])

    if topic == "Radicals and Rational Exponents":
        n = r.choice([4,9,16,25,36,49,64,81,100,121,144])
        ans = int(math.isqrt(n))
        return Problem(f"Simplify: sqrt({n})", ans,
                       [f"Find the positive number whose square is {n}.", f"{ans}^2 = {n}."])

    if topic == "Polynomials":
        a,b,c,d = [rr(-8,8) for _ in range(4)]
        ans1, ans0 = a+c, b+d
        prompt = f"Combine like terms: ({a}x {b:+}) + ({c}x {d:+}). Enter as ax+b."
        disp = f"{ans1}x{ans0:+}"
        return Problem(prompt, disp,
                       [f"Combine x-terms: {a}+{c}={ans1}.", f"Combine constants: {b}+{d}={ans0}.", f"Result: {disp}."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Factoring Polynomials":
        p,q = rr(-7,7), rr(-7,7)
        while p == 0 or q == 0:
            p,q = rr(-7,7), rr(-7,7)
        b,c = p+q, p*q
        disp = f"(x{p:+})(x{q:+})"
        prompt = f"Factor: x^2 {b:+}x {c:+}. Enter (x+a)(x+b)."
        def ck(u):
            s=normalize(u)
            return s in {normalize(disp), normalize(f"(x{q:+})(x{p:+})")}
        return Problem(prompt, disp,
                       [f"Find two numbers that multiply to {c} and add to {b}.",
                        f"Those numbers are {p} and {q}.", f"Factorization: {disp}."],
                       checker=ck, display_answer=disp)

    if topic == "Rational Expressions":
        a = rr(2,9)
        prompt = f"Simplify: (x^2-{a*a})/(x-{a}), x ≠ {a}. Enter the simplified expression."
        disp = f"x+{a}"
        return Problem(prompt, disp,
                       [f"Factor the numerator: x^2-{a*a}=(x-{a})(x+{a}).",
                        f"Cancel the common factor x-{a}.", f"Result: x+{a}, with x≠{a}."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "The Rectangular Coordinate System and Graphs":
        x1,y1 = rr(-5,2), rr(-5,2)
        dx = r.choice([1,2,3,4])
        m = rr(-4,4)
        x2 = x1+dx
        y2 = y1+m*dx
        return Problem(f"Find the slope through ({x1},{y1}) and ({x2},{y2}).", m,
                       [f"m=(y2-y1)/(x2-x1).", f"m=({y2}-{y1})/({x2}-{x1})={m}."])

    if topic == "Linear Equations in One Variable":
        x = rr(-9,9)
        a = r.choice([2,3,4,5,6,7])
        b = rr(-12,12)
        c = a*x+b
        return Problem(f"Solve: {a}x {b:+} = {c}", x,
                       [f"Subtract {b} from both sides: {a}x = {c-b}.", f"Divide by {a}: x = {x}."])

    if topic == "Models and Applications":
        price = rr(3,12)
        qty = rr(4,15)
        total = price*qty
        return Problem(f"A student buys {qty} notebooks for ${total}. What is the price per notebook?", price,
                       [f"Let p be the price of one notebook.", f"{qty}p={total}.", f"p={total}/{qty}={price}."])

    if topic == "Complex Numbers":
        a,b,c,d = [rr(-7,7) for _ in range(4)]
        rr,ii = a+c,b+d
        disp=f"{rr}{ii:+}i"
        return Problem(f"Add: ({a}{b:+}i)+({c}{d:+}i). Enter a+bi.", disp,
                       [f"Real parts: {a}+{c}={rr}.", f"Imaginary parts: {b}+{d}={ii}.", f"Result: {disp}."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Quadratic Equations":
        p,q = rr(-8,8), rr(-8,8)
        while p==q:
            q=rr(-8,8)
        b = -(p+q); c=p*q
        pair=sorted([p,q])
        disp=f"{pair[0]}, {pair[1]}"
        return Problem(f"Solve: x^2 {b:+}x {c:+} = 0. Enter both roots.", disp,
                       [f"Factor using roots {p} and {q}.", f"(x-{p})(x-{q})=0.", f"x={p} or x={q}."],
                       checker=lambda u: unordered_pair_eq(u,pair), display_answer=disp)

    if topic == "Other Types of Equations":
        x = rr(2,8)
        n=x*x
        return Problem(f"Solve for the positive solution: x^2 = {n}", x,
                       ["Take the square root of both sides.", f"The positive solution is x={x}."])

    if topic == "Linear Inequalities and Absolute Value Inequalities":
        a=r.choice([2,3,4,5]); x=rr(-4,8); b=rr(-8,8); c=a*x+b
        ans=f"x>{x}"
        prompt=f"Solve: {a}x {b:+} > {c}. Enter x>number."
        return Problem(prompt, ans,
                       [f"Subtract {b}: {a}x > {c-b}.", f"Divide by {a}: x > {x}."],
                       checker=lambda u: normalize(u)==normalize(ans), display_answer=ans)

    if topic == "Functions and Function Notation":
        a,b,x=rr(2,6),rr(-8,8),rr(-5,7)
        ans=a*x+b
        return Problem(f"If f(x)={a}x {b:+}, find f({x}).", ans,
                       [f"Substitute x={x}.", f"f({x})={a}({x}){b:+}={ans}."])

    if topic == "Domain and Range":
        a=rr(-6,6)
        ans=f"x!={a}"
        prompt=f"Find the domain restriction of f(x)=1/(x{(-a):+}). Enter x!=number."
        return Problem(prompt, ans,
                       [f"The denominator cannot equal zero.", f"x{(-a):+}=0 gives x={a}.", f"Domain restriction: x≠{a}."],
                       checker=lambda u: normalize(u).replace("≠","!=")==normalize(ans), display_answer=f"x ≠ {a}")

    if topic == "Rates of Change and Behavior of Graphs":
        a,b=rr(-4,5),rr(-7,7)
        x1,x2=rr(-3,1),rr(2,6)
        y1,y2=a*x1+b,a*x2+b
        return Problem(f"Average rate of change from x={x1} to x={x2} for f(x)={a}x{b:+}?", a,
                       [f"f({x1})={y1}, f({x2})={y2}.", f"({y2}-{y1})/({x2}-{x1})={a}."])

    if topic == "Composition of Functions":
        a,b,c,d,x=[rr(1,5),rr(-5,5),rr(1,4),rr(-5,5),rr(-3,4)]
        gx=c*x+d
        ans=a*gx+b
        return Problem(f"f(x)={a}x{b:+}, g(x)={c}x{d:+}. Find (f∘g)({x}).", ans,
                       [f"First g({x})={c}({x}){d:+}={gx}.", f"Then f({gx})={a}({gx}){b:+}={ans}."])

    if topic == "Transformation of Functions":
        h,k=rr(-5,5),rr(-5,5)
        disp=f"({h},{k})"
        prompt=f"For y=(x{(-h):+})^2 {k:+}, enter the vertex as (h,k)."
        return Problem(prompt, disp,
                       [f"Compare with y=(x-h)^2+k.", f"h={h}, k={k}.", f"Vertex: ({h},{k})."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Inverse Functions":
        a=r.choice([2,3,4,5]); b=rr(-7,7)
        disp=f"(x{(-b):+})/{a}"
        prompt=f"Find f^-1(x) if f(x)={a}x{b:+}. Enter (x-b)/a form."
        return Problem(prompt, disp,
                       ["Write y=f(x) and swap x and y.", f"x={a}y{b:+}.", f"Solve for y: y=(x{(-b):+})/{a}."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Quadratic Functions":
        h,k=rr(-5,5),rr(-5,5)
        disp=f"({h},{k})"
        return Problem(f"Find the vertex of y=(x{(-h):+})^2 {k:+}.", disp,
                       ["Use vertex form y=a(x-h)^2+k.", f"Vertex = ({h},{k})."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Power Functions and Polynomial Functions":
        n=r.choice([2,4,6,3,5,7])
        ans="even" if n%2==0 else "odd"
        return Problem(f"Classify f(x)=x^{n} as even or odd.", ans,
                       [f"The exponent {n} is {'even' if n%2==0 else 'odd'}.", f"So the function is {ans}."],
                       checker=lambda u: normalize(u)==ans, display_answer=ans)

    if topic == "Graphs of Polynomial Functions":
        mult=r.choice([1,2,3,4])
        ans="crosses" if mult%2 else "touches"
        return Problem(f"A zero has multiplicity {mult}. Does the graph cross or touch the x-axis?", ans,
                       ["Odd multiplicity crosses the axis; even multiplicity touches and turns.", f"Multiplicity {mult} means it {ans}."],
                       checker=lambda u: ans in normalize(u), display_answer=ans)

    if topic == "Dividing Polynomials":
        a=rr(2,7); b=rr(-6,6)
        # (x+b)(x+a) / (x+a) = x+b
        disp=f"x{b:+}"
        return Problem(f"Divide: (x^2 {(a+b):+}x {(a*b):+})/(x{a:+}). Enter quotient.", disp,
                       [f"The numerator factors as (x{a:+})(x{b:+}).", f"Cancel/divide by (x{a:+}).", f"Quotient: {disp}."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Zeros of Polynomials":
        z=rr(-8,8)
        b=-z
        return Problem(f"Find the zero of f(x)=x{b:+}.", z,
                       [f"Set x{b:+}=0.", f"x={z}."])

    if topic == "Rational Functions":
        a=rr(-6,6)
        return Problem(f"Find the vertical asymptote of f(x)=1/(x{(-a):+}). Enter x=number.", f"x={a}",
                       [f"Set denominator equal to zero: x{(-a):+}=0.", f"Vertical asymptote: x={a}."],
                       checker=lambda u: normalize(u)==normalize(f"x={a}"), display_answer=f"x = {a}")

    if topic == "Exponential Functions":
        b=r.choice([2,3,4,5]); x=rr(2,5); ans=b**x
        return Problem(f"Evaluate: {b}^{x}", ans,
                       [f"Multiply {b} by itself {x} times.", f"Result: {ans}."])

    if topic == "Graphs of Exponential Functions":
        k=rr(-6,6)
        return Problem(f"What is the horizontal asymptote of y=2^x {k:+}? Enter y=number.", f"y={k}",
                       ["The parent y=2^x has asymptote y=0.", f"A vertical shift by {k} moves it to y={k}."],
                       checker=lambda u: normalize(u)==normalize(f"y={k}"), display_answer=f"y = {k}")

    if topic == "Logarithmic Functions":
        b=r.choice([2,3,4,5]); p=rr(1,4); n=b**p
        return Problem(f"Evaluate: log base {b} of {n}", p,
                       [f"Ask: {b} raised to what power equals {n}?", f"{b}^{p}={n}, so the log equals {p}."])

    if topic == "Graphs of Logarithmic Functions":
        h=rr(-5,5)
        return Problem(f"Find the vertical asymptote of y=log(x{(-h):+}). Enter x=number.", f"x={h}",
                       [f"The logarithm input approaches zero at x={h}.", f"Vertical asymptote: x={h}."],
                       checker=lambda u: normalize(u)==normalize(f"x={h}"), display_answer=f"x = {h}")

    if topic == "Logarithmic Properties":
        p=rr(2,8)
        disp=f"{p}log(x)"
        return Problem(f"Expand: log(x^{p}).", disp,
                       ["Use the power property: log(M^p)=p log(M).", f"Result: {p}log(x)."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Exponential and Logarithmic Equations":
        b=r.choice([2,3,4,5]); x=rr(1,5); n=b**x
        return Problem(f"Solve: {b}^x = {n}", x,
                       [f"Recognize {n} as a power of {b}.", f"{b}^{x}={n}, so x={x}."])

    if topic == "Exponential and Logarithmic Models":
        p=r.choice([100,200,500,1000]); rate=r.choice([0.05,0.10,0.20]); years=2
        ans=round(p*((1+rate)**years),2)
        return Problem(f"${p} grows by {int(rate*100)}% per year for {years} years. Final amount?", ans,
                       [f"Use A=P(1+r)^t.", f"A={p}(1+{rate})^{years}.", f"A={ans:.2f}."])

    if topic == "Systems of Linear Equations: Two Variables":
        x,y=rr(-5,5),rr(-5,5)
        a,b,c,d=[rr(1,5) for _ in range(4)]
        while a*d==b*c:
            d=rr(1,5)
        e=a*x+b*y; f=c*x+d*y
        disp=f"({x},{y})"
        return Problem(f"Solve: {a}x+{b}y={e}; {c}x+{d}y={f}. Enter (x,y).", disp,
                       ["Use elimination or substitution.", f"The equations intersect at ({x},{y}).", "Check the pair in both equations."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Systems of Linear Equations: Three Variables":
        x,y,z=[rr(-3,3) for _ in range(3)]
        s=x+y+z
        disp=f"({x},{y},{z})"
        prompt=f"Solve: x+y+z={s}; x-y={x-y}; z={z}. Enter (x,y,z)."
        return Problem(prompt, disp,
                       [f"From z={z}, substitute into the first equation.", f"Use x-y={x-y} with x+y={s-z}.", f"Solution: {disp}."],
                       checker=lambda u: normalize(u)==normalize(disp), display_answer=disp)

    if topic == "Systems of Nonlinear Equations and Inequalities: Two Variables":
        a=rr(1,5)
        pair=[-a,a]
        return Problem(f"Find the x-values where y=x^2 and y={a*a}. Enter both x-values.", f"{-a}, {a}",
                       [f"Set x^2={a*a}.", f"x=±{a}.", f"Intersections occur at x={-a} and x={a}."],
                       checker=lambda u: unordered_pair_eq(u,pair), display_answer=f"{-a}, {a}")

    if topic == "Circles":
        h,k,radius=rr(-5,5),rr(-5,5),rr(2,7)
        disp=f"({h},{k}), r={radius}"
        return Problem(f"For (x{(-h):+})^2+(y{(-k):+})^2={radius**2}, enter center and radius.", disp,
                       [f"Compare with (x-h)^2+(y-k)^2=r^2.", f"Center=({h},{k}), radius={radius}."],
                       checker=lambda u: str(h) in u and str(k) in u and str(radius) in u, display_answer=disp)

    if topic == "The Ellipse":
        a,b=r.choice([(5,3),(6,4),(7,2),(8,5)])
        return Problem(f"For x^2/{a*a}+y^2/{b*b}=1, what is the semi-major axis length?", max(a,b),
                       ["The larger denominator corresponds to the major axis.", f"sqrt({max(a*a,b*b)})={max(a,b)}."])

    if topic == "The Hyperbola":
        orient=r.choice(["horizontal","vertical"])
        if orient=="horizontal":
            prompt="For x^2/9 - y^2/4 = 1, is the transverse axis horizontal or vertical?"
        else:
            prompt="For y^2/9 - x^2/4 = 1, is the transverse axis horizontal or vertical?"
        return Problem(prompt, orient,
                       ["The positive squared term identifies the transverse axis.", f"Therefore it is {orient}."],
                       checker=lambda u: orient in normalize(u), display_answer=orient)

    if topic == "The Parabola":
        p=r.choice([-3,-2,2,3])
        direction="up" if p>0 else "down"
        return Problem(f"For x^2={4*p}y, which direction does the parabola open?", direction,
                       [f"Compare with x^2=4py, so p={p}.", f"Since p is {'positive' if p>0 else 'negative'}, it opens {direction}."],
                       checker=lambda u: direction in normalize(u), display_answer=direction)

    if topic == "Sequences and Their Notations":
        a1,d,n=rr(1,10),rr(1,7),rr(4,10)
        ans=a1+(n-1)*d
        return Problem(f"Sequence starts {a1}, {a1+d}, {a1+2*d}, ... Find a_{n}.", ans,
                       [f"This is arithmetic with d={d}.", f"a_{n}={a1}+({n}-1)({d})={ans}."])

    if topic == "Arithmetic Sequences":
        a1,d,n=rr(-5,10),rr(-5,7),rr(5,12)
        ans=a1+(n-1)*d
        return Problem(f"Arithmetic sequence: a1={a1}, d={d}. Find a_{n}.", ans,
                       [f"Use a_n=a_1+(n-1)d.", f"a_{n}={a1}+({n}-1)({d})={ans}."])

    if topic == "Geometric Sequences":
        a1,rn,n=rr(1,5),r.choice([2,3,4]),rr(4,7)
        ans=a1*(rn**(n-1))
        return Problem(f"Geometric sequence: a1={a1}, r={rn}. Find a_{n}.", ans,
                       [f"Use a_n=a_1 r^(n-1).", f"a_{n}={a1}({rn})^{n-1}={ans}."])

    if topic == "Series and Their Notations":
        a1,d,n=rr(1,8),rr(1,5),rr(4,10)
        an=a1+(n-1)*d
        ans=n*(a1+an)//2
        return Problem(f"Find the sum of the first {n} terms: a1={a1}, d={d}.", ans,
                       [f"First find a_n={an}.", f"Use S_n=n(a_1+a_n)/2.", f"S_{n}={n}({a1}+{an})/2={ans}."])

    return Problem("What is 2 + 2?", 4, ["Add the two numbers.", "2+2=4."])

def starfield():
    random.seed(1337)
    return [(random.randrange(WIDTH), random.randrange(HEIGHT), random.choice([1,1,1,2])) for _ in range(110)]

STARS = starfield()
random.seed()

def draw_background():
    screen.fill(BG)
    for x,y,s in STARS:
        pygame.draw.circle(screen, (72,72,88), (x,y), s)

def header(subtitle=""):
    pygame.draw.rect(screen, PANEL, (0,0,WIDTH,84))
    draw_text("BLOODY MATH", BIG, RED, 30, 18)
    draw_text("ALGEBRA QUEST", SMALL, WHITE, 315, 35)
    if subtitle:
        # Right-align the subtitle so it never gets clipped at the screen edge.
        subtitle_surf = SMALL.render(str(subtitle), True, MUTED)
        subtitle_rect = subtitle_surf.get_rect()
        subtitle_rect.topright = (WIDTH - 30, 35)
        screen.blit(subtitle_surf, subtitle_rect)
    pygame.draw.line(screen, DARK_RED, (0,83), (WIDTH,83), 2)

async def main_menu(progress):
    items=["START GAME","LEARN MODE","PRACTICE MODE","CHALLENGE MODE","PROGRESS","SETTINGS","QUIT"]
    idx=0
    while True:
        rects=[pygame.Rect(WIDTH//2-190,275+i*62,380,48) for i in range(len(items))]
        for e in get_events():
            if e.type==pygame.VIDEORESIZE and not ensure_settings(progress).get("fullscreen",False):
                ensure_settings(progress)["window_size"]=[max(720,e.w),max(500,e.h)]
                save_progress(progress)
            if e.type==pygame.QUIT: return "quit"
            if e.type==pygame.MOUSEMOTION:
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        if idx != i: play_sfx("move")
                        idx=i
                        break
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        idx=i; play_sfx("select")
                        sel=items[idx]
                        if sel=="QUIT": return "quit"
                        if sel=="PROGRESS": await progress_screen(progress)
                        elif sel=="SETTINGS": await settings_screen(progress)
                        elif sel=="START GAME": return ("worlds","guided")
                        elif sel=="LEARN MODE": return ("worlds","learn")
                        elif sel=="PRACTICE MODE": return ("worlds","practice")
                        elif sel=="CHALLENGE MODE": return ("worlds","challenge")
                        break
            if e.type==pygame.KEYDOWN:
                if e.key==pygame.K_F11:
                    toggle_fullscreen(progress)
                    continue
                if e.key in (pygame.K_UP,pygame.K_w):
                    idx=(idx-1)%len(items); play_sfx("move")
                elif e.key in (pygame.K_DOWN,pygame.K_s):
                    idx=(idx+1)%len(items); play_sfx("move")
                elif e.key in (pygame.K_RETURN,pygame.K_SPACE):
                    play_sfx("select")
                    sel=items[idx]
                    if sel=="QUIT": return "quit"
                    if sel=="PROGRESS": await progress_screen(progress)
                    elif sel=="SETTINGS": await settings_screen(progress)
                    elif sel=="START GAME": return ("worlds","guided")
                    elif sel=="LEARN MODE": return ("worlds","learn")
                    elif sel=="PRACTICE MODE": return ("worlds","practice")
                    elif sel=="CHALLENGE MODE": return ("worlds","challenge")
                elif e.key==pygame.K_ESCAPE: return "quit"
        draw_background()
        draw_text("BLOODY MATH", HUGE, RED, WIDTH//2, 105, center=True)
        draw_text("ALGEBRA QUEST", BIG, WHITE, WIDTH//2, 175, center=True)
        draw_text("Complete Math 105 Edition", SMALL, CYAN, WIDTH//2, 220, center=True)
        for i,item in enumerate(items):
            button(rects[i],item,i==idx)
        acc=pct(progress["total_correct"],progress["total_attempts"])
        draw_text(f"TOTAL ACCURACY  {acc}%   |   BEST COMBO  {progress['best_combo']}", TINY, MUTED, WIDTH//2, 744, center=True)
        present(); clock.tick(FPS); await asyncio.sleep(0)

async def world_select(progress, mode):
    idx=0
    while True:
        rects=[pygame.Rect(46,178+i*68,760,52) for i in range(len(WORLD_DATA))]
        back_rect=pygame.Rect(1000,600,170,48)
        for e in get_events():
            if e.type==pygame.VIDEORESIZE and not ensure_settings(progress).get("fullscreen",False):
                ensure_settings(progress)["window_size"]=[max(720,e.w),max(500,e.h)]
                save_progress(progress)
            if e.type==pygame.QUIT: return None
            if e.type==pygame.MOUSEMOTION:
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        if idx != i: play_sfx("world_move")
                        idx=i
                        break
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                if back_rect.collidepoint(logical_pos(e.pos)):
                    play_sfx("select"); return None
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        idx=i; play_sfx("select")
                        await topic_select(progress,idx,mode)
                        break
            if e.type==pygame.KEYDOWN:
                if e.key==pygame.K_F11:
                    toggle_fullscreen(progress)
                    continue
                if e.key in (pygame.K_UP,pygame.K_w): idx=(idx-1)%len(WORLD_DATA); play_sfx("world_move")
                elif e.key in (pygame.K_DOWN,pygame.K_s): idx=(idx+1)%len(WORLD_DATA); play_sfx("world_move")
                elif e.key==pygame.K_ESCAPE: return None
                elif e.key in (pygame.K_RETURN,pygame.K_SPACE):
                    play_sfx("select"); await topic_select(progress, idx, mode)
        draw_background(); header(mode.upper()+" MODE")
        draw_text("SELECT WORLD", BIG, WHITE, 46, 112)
        for i,(wn,name,topics) in enumerate(WORLD_DATA):
            rect=rects[i]
            hovered=rect.collidepoint(logical_mouse_pos())
            pygame.draw.rect(screen, RED if (i==idx or hovered) else PANEL2, rect, border_radius=8)
            draw_text(f"{wn} — {name}", SMALL, WHITE, 62, rect.y+8)
            attempts=sum(progress["topics"].get(t,{}).get("attempts",0) for t in topics)
            correct=sum(progress["topics"].get(t,{}).get("correct",0) for t in topics)
            mastery=pct(correct,attempts)
            draw_text(f"{mastery}% mastery", TINY, CYAN if attempts else MUTED, 650, rect.y+17)
        pygame.draw.rect(screen,PANEL,(840,145,390,520),border_radius=10)
        draw_text("CAMPAIGN", FONT, YELLOW, 865,170)
        draw_wrapped("Every world contains lessons, generated practice problems, and a mixed World Review / Boss Challenge.", SMALL, WHITE, 865,215,335)
        draw_text("Controls", FONT, CYAN, 865,350)
        draw_text("Mouse Click  Select", SMALL, WHITE,865,395)
        draw_text("↑ ↓ / WASD  Select", SMALL, WHITE,865,430)
        draw_text("ENTER  Open", SMALL, WHITE,865,465)
        button(back_rect,"BACK",False)
        present(); clock.tick(FPS); await asyncio.sleep(0)

async def topic_select(progress, world_idx, mode):
    wn,name,topics=WORLD_DATA[world_idx]
    entries=topics+["WORLD REVIEW","BOSS CHALLENGE"]
    idx=0
    async def activate(index):
        nonlocal idx
        idx=index
        play_sfx("select")
        if idx < len(topics):
            topic=topics[idx]
            if mode=="learn":
                await lesson_screen(topic)
            else:
                diff = "Auto" if mode=="challenge" else await difficulty_select(progress)
                if diff:
                    await session(progress, topic, mode, diff)
        elif entries[idx]=="WORLD REVIEW":
            diff = await difficulty_select(progress)
            if diff:
                await mixed_session(progress, topics, "practice", 10, f"{wn} Review", selected_difficulty=diff)
        else:
            play_sfx("boss")
            await mixed_session(progress, topics, "challenge", 12, f"{wn} Boss Challenge", boss=True, world_key=wn, selected_difficulty="Auto")
    while True:
        rects=[pygame.Rect(46,165+i*48,900,40) for i in range(len(entries))]
        back_rect=pygame.Rect(1000,560,180,48)
        for e in get_events():
            if e.type==pygame.VIDEORESIZE and not ensure_settings(progress).get("fullscreen",False):
                ensure_settings(progress)["window_size"]=[max(720,e.w),max(500,e.h)]
                save_progress(progress)
            if e.type==pygame.QUIT:return None
            if e.type==pygame.MOUSEMOTION:
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        if idx != i: play_sfx("move")
                        idx=i
                        break
            if e.type==pygame.MOUSEBUTTONUP and e.button==1:
                if back_rect.collidepoint(logical_pos(e.pos)):
                    play_sfx("select"); return None
                for i,r in enumerate(rects):
                    if r.collidepoint(logical_pos(e.pos)):
                        await activate(i)
                        break
            if e.type==pygame.KEYDOWN:
                if e.key==pygame.K_F11:
                    toggle_fullscreen(progress)
                    continue
                if e.key in (pygame.K_UP,pygame.K_w):idx=(idx-1)%len(entries); play_sfx("move")
                elif e.key in (pygame.K_DOWN,pygame.K_s):idx=(idx+1)%len(entries); play_sfx("move")
                elif e.key==pygame.K_ESCAPE:return None
                elif e.key in (pygame.K_RETURN,pygame.K_SPACE):
                    await activate(idx)
        draw_background();header(f"{wn.upper()} — {name}")
        draw_text("SELECT TOPIC", BIG, WHITE, 46,110)
        for i,label in enumerate(entries):
            rect=rects[i]
            hover=rect.collidepoint(logical_mouse_pos())
            pygame.draw.rect(screen, RED if (i==idx or hover) else PANEL2, rect, border_radius=7)
            color=YELLOW if label in ("WORLD REVIEW","BOSS CHALLENGE") else WHITE
            draw_text(label, TINY if len(label)>46 else SMALL, color, 60, rect.y+7)
            if i<len(topics):
                rec=progress["topics"].get(label,{"correct":0,"attempts":0})
                draw_text(f"{pct(rec['correct'],rec['attempts'])}%", TINY, CYAN if rec["attempts"] else MUTED, 885,rect.y+11)
        pygame.draw.rect(screen,PANEL,(980,155,250,430),border_radius=10)
        draw_text("MODE", FONT, CYAN,1000,178)
        draw_text(mode.upper(),FONT,YELLOW,1000,220)
        draw_wrapped("Learn explains concepts. Guided gives hints. Practice builds mastery. Challenge rewards accuracy and combos.", TINY, WHITE,1000,275,200)
        button(back_rect,"BACK",False)
        present();clock.tick(FPS); await asyncio.sleep(0)

async def lesson_screen(topic):
    intro,steps=lesson_for(topic)
    while True:
        continue_rect=pygame.Rect(WIDTH//2-150,710,300,44)
        for e in get_events():
            if e.type==pygame.QUIT:return
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1 and continue_rect.collidepoint(logical_pos(e.pos)):
                play_sfx("select"); return
            if e.type==pygame.KEYDOWN and e.key in (pygame.K_ESCAPE,pygame.K_RETURN,pygame.K_SPACE):return
        draw_background();header("LEARN MODE")
        draw_wrapped(topic, BIG, WHITE,50,112,1180)
        pygame.draw.rect(screen,PANEL,(50,195,1180,500),border_radius=12)
        y=225
        y=draw_wrapped(intro,FONT,CYAN,80,y,1120)+25
        draw_text("KEY IDEAS",FONT,YELLOW,80,y);y+=48
        for i,s in enumerate(steps,1):
            draw_text(f"{i}.",FONT,RED,85,y)
            y=draw_wrapped(s,SMALL,WHITE,125,y+3,1050)+22
        button(continue_rect,"CONTINUE",False)
        present();clock.tick(FPS); await asyncio.sleep(0)

async def session(progress, topic, mode, selected_difficulty="Medium"):
    total=5 if mode=="guided" else 10
    lives=3 if mode=="challenge" else 999
    score=0;combo=0
    for qnum in range(1,total+1):
        difficulty = challenge_difficulty(qnum,total) if mode=="challenge" else selected_difficulty
        p=make_problem(topic,difficulty)
        result=await problem_screen(topic,p,mode,qnum,total,lives,score,combo,difficulty=difficulty)
        if result=="quit":break
        correct=result["correct"]
        used_hint=result["used_hint"]
        rec=topic_stats(progress,topic)
        rec["attempts"]+=1;progress["total_attempts"]+=1
        if correct:
            rec["correct"]+=1;progress["total_correct"]+=1
            combo+=1
            gain=100 + combo*20 - (30 if used_hint else 0)
            score+=max(20,gain)
            rec["best_combo"]=max(rec.get("best_combo",0),combo)
            progress["best_combo"]=max(progress["best_combo"],combo)
        else:
            combo=0
            if mode=="challenge":
                lives-=1
        save_progress(progress)
        if mode=="challenge" and lives<=0:break
    await result_screen(topic,score,combo,lives if mode=="challenge" else None)

async def mixed_session(progress, topics, mode, total, title, boss=False, world_key=None, selected_difficulty="Medium"):
    lives=5 if boss else 999
    score=0;combo=0
    for qnum in range(1,total+1):
        topic=random.choice(topics)
        difficulty = challenge_difficulty(qnum,total) if mode=="challenge" else selected_difficulty
        p=make_problem(topic,difficulty)
        result=await problem_screen(topic,p,mode,qnum,total,lives,score,combo,boss_title=title,difficulty=difficulty)
        if result=="quit":break
        rec=topic_stats(progress,topic);rec["attempts"]+=1;progress["total_attempts"]+=1
        if result["correct"]:
            rec["correct"]+=1;progress["total_correct"]+=1
            combo+=1;score+=100+combo*25
            rec["best_combo"]=max(rec.get("best_combo",0),combo)
            progress["best_combo"]=max(progress["best_combo"],combo)
        else:
            combo=0
            if boss:lives-=1
        save_progress(progress)
        if boss and lives<=0:break
    if boss and world_key and lives>0:
        progress["world_bosses"][world_key]=True;save_progress(progress)
    await result_screen(title,score,combo,lives if boss else None,boss=boss)

async def problem_screen(topic,p,mode,qnum,total,lives,score,combo,boss_title=None,difficulty="Medium"):
    typed=""
    feedback=""
    used_hint=False
    show_steps=False
    submitted=False
    correct=False
    while True:
        symbol_rects=[]
        sx, sy = 80, 520
        for i,sym in enumerate(SYMBOLS):
            row=i//8; col=i%8
            symbol_rects.append((pygame.Rect(sx+col*105, sy+row*50, 94, 40), sym))

        for e in get_events():
            if e.type==pygame.QUIT:return {"correct":False,"used_hint":used_hint}
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1 and not submitted:
                for rect,sym in symbol_rects:
                    if rect.collidepoint(logical_pos(e.pos)):
                        if len(typed)+len(sym)<=72:
                            typed += sym
                            play_sfx("move")
                        break
            if e.type==pygame.KEYDOWN:
                if e.key==pygame.K_F11 and ACTIVE_PROGRESS is not None:
                    toggle_fullscreen(ACTIVE_PROGRESS)
                    continue
                if e.key==pygame.K_ESCAPE:return "quit"
                if e.key==pygame.K_BACKSPACE and not submitted:
                    typed=typed[:-1]
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if submitted:
                        play_sfx("select")
                        return {"correct":correct,"used_hint":used_hint}
                    if typed.strip():
                        correct=p.check(typed)
                        submitted=True
                        feedback="CORRECT!" if correct else "NOT QUITE"
                        play_sfx("correct" if correct else "wrong")
                elif e.key==pygame.K_h and not submitted and mode in ("guided","practice"):
                    used_hint=True;feedback="HINT: "+p.hint; play_sfx("hint")
                elif e.key==pygame.K_s and submitted:
                    show_steps=True
                elif not submitted and len(typed)<72:
                    ch=math_key_text(e)
                    if ch:
                        typed += ch
        draw_background();header((boss_title or mode.upper()))
        draw_text(f"QUESTION {qnum}/{total}",SMALL,CYAN,45,112)
        draw_text(f"DIFFICULTY {difficulty.upper()}",SMALL,ORANGE,250,112)
        draw_text(f"SCORE {score}",SMALL,YELLOW,1075,112)
        if mode=="challenge" or boss_title:
            draw_text(f"LIVES {lives}",SMALL,RED,945,112)
        draw_text(f"COMBO x{combo}",SMALL,GREEN,800,112)
        pygame.draw.rect(screen,PANEL,(45,155,1190,250),border_radius=12)
        draw_text(topic,TINY,MUTED,70,175)
        draw_wrapped(p.prompt,FONT,WHITE,70,220,1120,40)

        pygame.draw.rect(screen,PANEL2,(80,430,1120,60),border_radius=8)
        draw_text("ANSWER:",SMALL,CYAN,100,449)
        draw_text(typed+"|" if not submitted else typed,FONT,WHITE,230,444)

        if not submitted:
            draw_text("MATH SYMBOLS — CLICK TO INSERT", SMALL, YELLOW, 80, 492)
            pygame.draw.rect(screen,PANEL,(64,510,865,115),border_radius=10)
            for rect,sym in symbol_rects:
                hover=rect.collidepoint(logical_mouse_pos())
                pygame.draw.rect(screen,RED if hover else PANEL2,rect,border_radius=6)
                pygame.draw.rect(screen,WHITE if hover else (100,100,118),rect,2,border_radius=6)
                draw_text(sym,SMALL,WHITE,rect.centerx,rect.centery,center=True)
            draw_text("Keyboard shortcuts also work",TINY,CYAN,960,530)
            draw_text("Shift+6 = ^",TINY,WHITE,960,560)
            draw_text("Use buttons if your layout",TINY,MUTED,960,590)
            draw_text("does not type a symbol.",TINY,MUTED,960,615)

        if feedback:
            color=GREEN if correct else (YELLOW if feedback.startswith("HINT") else RED)
            draw_wrapped(feedback,SMALL,color,80,535,1120)

        if submitted:
            draw_text("Answer:",SMALL,MUTED,80,585)
            draw_text(p.display_answer,FONT,GREEN,175,578)
            if show_steps:
                y=630
                for i,st in enumerate(p.steps,1):
                    draw_text(f"{i}.",TINY,CYAN,85,y)
                    y=draw_wrapped(st,TINY,WHITE,115,y,1065,26)
            else:
                draw_text("Press S to show solution steps.",TINY,MUTED,80,635)
            draw_text("Press ENTER for next question",TINY,MUTED,WIDTH//2,750,center=True)
        else:
            hinttxt="H = Hint   " if mode in ("guided","practice") else ""
            draw_text(hinttxt+"ENTER = Submit   ESC = Exit",TINY,MUTED,WIDTH//2,735,center=True)
        present();clock.tick(FPS); await asyncio.sleep(0)

async def result_screen(title,score,combo,lives=None,boss=False):
    play_sfx("victory" if (not boss or (lives and lives>0)) else "wrong")
    while True:
        continue_rect=pygame.Rect(WIDTH//2-170,590,340,50)
        for e in get_events():
            if e.type==pygame.QUIT:return
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1 and continue_rect.collidepoint(logical_pos(e.pos)):
                play_sfx("select"); return
            if e.type==pygame.KEYDOWN and e.key==pygame.K_F11 and ACTIVE_PROGRESS is not None:
                toggle_fullscreen(ACTIVE_PROGRESS)
                continue
            if e.type==pygame.KEYDOWN and e.key in (pygame.K_RETURN,pygame.K_SPACE,pygame.K_ESCAPE):return
        draw_background()
        draw_text("BOSS CLEARED!" if boss and lives and lives>0 else ("SESSION COMPLETE" if not boss else "BOSS RETREAT"),BIG,GREEN if (not boss or (lives and lives>0)) else RED,WIDTH//2,180,center=True)
        draw_wrapped(title,FONT,WHITE,200,250,880)
        draw_text(f"SCORE  {score}",BIG,YELLOW,WIDTH//2,380,center=True)
        draw_text(f"FINAL COMBO  x{combo}",FONT,CYAN,WIDTH//2,445,center=True)
        if lives is not None: draw_text(f"LIVES LEFT  {max(0,lives)}",FONT,RED,WIDTH//2,490,center=True)
        button(continue_rect,"CONTINUE",False)
        present();clock.tick(FPS); await asyncio.sleep(0)

async def progress_screen(progress):
    wi=0
    while True:
        left_rect=pygame.Rect(430,730,80,42)
        right_rect=pygame.Rect(770,730,80,42)
        back_rect=pygame.Rect(555,730,170,42)
        for e in get_events():
            if e.type==pygame.VIDEORESIZE and not ensure_settings(progress).get("fullscreen",False):
                ensure_settings(progress)["window_size"]=[max(720,e.w),max(500,e.h)]
                save_progress(progress)
            if e.type==pygame.QUIT:return
            if e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
                if left_rect.collidepoint(logical_pos(e.pos)): wi=(wi-1)%len(WORLD_DATA); play_sfx("move")
                elif right_rect.collidepoint(logical_pos(e.pos)): wi=(wi+1)%len(WORLD_DATA); play_sfx("move")
                elif back_rect.collidepoint(logical_pos(e.pos)): play_sfx("select"); return
            if e.type==pygame.KEYDOWN:
                if e.key==pygame.K_F11:
                    toggle_fullscreen(progress)
                    continue
                if e.key in (pygame.K_LEFT,pygame.K_a):wi=(wi-1)%len(WORLD_DATA); play_sfx("move")
                elif e.key in (pygame.K_RIGHT,pygame.K_d):wi=(wi+1)%len(WORLD_DATA); play_sfx("move")
                elif e.key==pygame.K_ESCAPE:return
        draw_background();header("PROGRESS")
        wn,name,topics=WORLD_DATA[wi]
        draw_text(f"{wn} — {name}",BIG,WHITE,45,110)
        y=180
        for t in topics:
            rec=progress["topics"].get(t,{"correct":0,"attempts":0})
            mastery=pct(rec["correct"],rec["attempts"])
            draw_text(t,TINY,WHITE,65,y)
            pygame.draw.rect(screen,(48,48,62),(720,y+2,360,18),border_radius=5)
            pygame.draw.rect(screen,CYAN,(720,y+2,int(360*mastery/100),18),border_radius=5)
            draw_text(f"{mastery}%",TINY,YELLOW,1095,y)
            y+=55
        boss=progress["world_bosses"].get(wn,False)
        draw_text("BOSS CLEARED" if boss else "BOSS NOT CLEARED",SMALL,GREEN if boss else MUTED,65,700)
        button(left_rect,"<",False)
        button(back_rect,"BACK",False)
        button(right_rect,">",False)
        present();clock.tick(FPS); await asyncio.sleep(0)


async def settings_screen(progress):
    settings = ensure_settings(progress)
    items = ["MUSIC VOLUME", "SFX VOLUME", "DISPLAY MODE", "FULLSCREEN RESOLUTION", "SCALING", "BACK"]
    idx = 0

    def cycle_resolution(direction):
        opts = available_resolutions()
        current = tuple(display_resolution(settings))
        if current in opts:
            i = opts.index(current)
        else:
            i = 0
        i = (i + direction) % len(opts)
        settings["fullscreen_resolution"] = [opts[i][0], opts[i][1]]
        if settings.get("fullscreen", False):
            apply_display_mode(progress)
        save_progress(progress)
        play_sfx("move")

    while True:
        row_y = [190, 280, 370, 460, 550]
        row_rects=[pygame.Rect(70,y-14,1140,68) for y in row_y]
        minus_rects=[pygame.Rect(330,row_y[i]-3,52,42) for i in range(2)]
        plus_rects=[pygame.Rect(1125,row_y[i]-3,52,42) for i in range(2)]
        display_rect=pygame.Rect(420,row_y[2]-3,620,42)
        res_minus=pygame.Rect(420,row_y[3]-3,52,42)
        res_value=pygame.Rect(485,row_y[3]-3,490,42)
        res_plus=pygame.Rect(988,row_y[3]-3,52,42)
        scale_rect=pygame.Rect(420,row_y[4]-3,620,42)
        back_rect=pygame.Rect(480,655,320,50)

        for e in get_events():
            if e.type == pygame.QUIT:
                return

            if e.type == pygame.VIDEORESIZE and not settings.get("fullscreen", False):
                settings["window_size"]=[max(720,e.w),max(500,e.h)]
                save_progress(progress)

            if e.type == pygame.MOUSEMOTION:
                lp = logical_pos(e.pos)
                if back_rect.collidepoint(lp):
                    idx=5
                else:
                    for i,r in enumerate(row_rects):
                        if r.collidepoint(lp):
                            idx=i
                            break

            if e.type == pygame.MOUSEBUTTONDOWN and e.button==1:
                lp = logical_pos(e.pos)
                if back_rect.collidepoint(lp):
                    play_sfx("select"); save_progress(progress); return

                for i in range(2):
                    key="music_volume" if i==0 else "sfx_volume"
                    if minus_rects[i].collidepoint(lp):
                        idx=i
                        settings[key]=max(0.0,round(float(settings[key])-0.05,2))
                        apply_audio_settings(progress); play_sfx("move"); save_progress(progress)
                    elif plus_rects[i].collidepoint(lp):
                        idx=i
                        settings[key]=min(1.0,round(float(settings[key])+0.05,2))
                        apply_audio_settings(progress); play_sfx("move"); save_progress(progress)

                if display_rect.collidepoint(lp) or row_rects[2].collidepoint(lp):
                    idx=2
                    toggle_fullscreen(progress)

                if res_minus.collidepoint(lp):
                    idx=3; cycle_resolution(-1)
                elif res_plus.collidepoint(lp):
                    idx=3; cycle_resolution(1)

                if scale_rect.collidepoint(lp) or row_rects[4].collidepoint(lp):
                    idx=4
                    settings["scaling_mode"] = "FIT" if settings.get("scaling_mode","FILL")=="FILL" else "FILL"
                    save_progress(progress); play_sfx("select")

            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_F11:
                    toggle_fullscreen(progress)
                    continue
                if e.key in (pygame.K_UP, pygame.K_w):
                    idx=(idx-1)%len(items); play_sfx("move")
                elif e.key in (pygame.K_DOWN, pygame.K_s):
                    idx=(idx+1)%len(items); play_sfx("move")
                elif e.key in (pygame.K_LEFT, pygame.K_a):
                    if idx < 2:
                        key="music_volume" if idx==0 else "sfx_volume"
                        settings[key]=max(0.0,round(float(settings[key])-0.05,2))
                        apply_audio_settings(progress); save_progress(progress)
                    elif idx==2:
                        settings["fullscreen"]=False
                        apply_display_mode(progress); save_progress(progress); play_sfx("select")
                    elif idx==3:
                        cycle_resolution(-1)
                    elif idx==4:
                        settings["scaling_mode"]="FIT"
                        save_progress(progress); play_sfx("select")
                elif e.key in (pygame.K_RIGHT, pygame.K_d):
                    if idx < 2:
                        key="music_volume" if idx==0 else "sfx_volume"
                        settings[key]=min(1.0,round(float(settings[key])+0.05,2))
                        apply_audio_settings(progress); play_sfx("move"); save_progress(progress)
                    elif idx==2:
                        settings["fullscreen"]=True
                        apply_display_mode(progress); save_progress(progress); play_sfx("select")
                    elif idx==3:
                        cycle_resolution(1)
                    elif idx==4:
                        settings["scaling_mode"]="FILL"
                        save_progress(progress); play_sfx("select")
                elif e.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if idx==2:
                        toggle_fullscreen(progress)
                    elif idx==3:
                        cycle_resolution(1)
                    elif idx==4:
                        settings["scaling_mode"]="FIT" if settings.get("scaling_mode","FILL")=="FILL" else "FILL"
                        save_progress(progress); play_sfx("select")
                    elif idx==5:
                        play_sfx("select"); save_progress(progress); return
                elif e.key == pygame.K_ESCAPE:
                    save_progress(progress); return

        draw_background()
        header("SETTINGS")
        draw_text("GAME SETTINGS", BIG, WHITE, 80, 105)

        vals=[float(settings["music_volume"]), float(settings["sfx_volume"])]
        labels=["MUSIC VOLUME","SFX VOLUME"]
        for i,label in enumerate(labels):
            y=row_y[i]
            if idx==i or row_rects[i].collidepoint(logical_mouse_pos()):
                pygame.draw.rect(screen,RED,row_rects[i],3,border_radius=10)
            draw_text(label,FONT,WHITE,100,y)
            button(minus_rects[i],"-",False)
            pygame.draw.rect(screen,(48,48,62),(420,y+7,620,26),border_radius=7)
            pygame.draw.rect(screen,CYAN if i==0 else YELLOW,(420,y+7,int(620*vals[i]),26),border_radius=7)
            button(plus_rects[i],"+",False)
            draw_text(f"{int(vals[i]*100)}%",FONT,WHITE,1060,y)

        # Display mode
        y=row_y[2]
        if idx==2 or row_rects[2].collidepoint(logical_mouse_pos()):
            pygame.draw.rect(screen,RED,row_rects[2],3,border_radius=10)
        draw_text("DISPLAY MODE",FONT,WHITE,100,y)
        mode_text="FULLSCREEN" if settings.get("fullscreen",False) else "WINDOWED"
        pygame.draw.rect(screen,PANEL2,display_rect,border_radius=7)
        pygame.draw.rect(screen,CYAN if idx==2 else (95,95,112),display_rect,2,border_radius=7)
        draw_text(mode_text,FONT,CYAN if idx==2 else WHITE,display_rect.centerx,display_rect.centery,center=True)

        # Resolution
        y=row_y[3]
        if idx==3 or row_rects[3].collidepoint(logical_mouse_pos()):
            pygame.draw.rect(screen,RED,row_rects[3],3,border_radius=10)
        draw_text("FULLSCREEN RESOLUTION",FONT,WHITE,100,y)
        button(res_minus,"<",False)
        rw,rh=display_resolution(settings)
        pygame.draw.rect(screen,PANEL2,res_value,border_radius=7)
        pygame.draw.rect(screen,CYAN if idx==3 else (95,95,112),res_value,2,border_radius=7)
        draw_text(f"{rw} x {rh}",FONT,WHITE,res_value.centerx,res_value.centery,center=True)
        button(res_plus,">",False)

        # Scaling
        y=row_y[4]
        if idx==4 or row_rects[4].collidepoint(logical_mouse_pos()):
            pygame.draw.rect(screen,RED,row_rects[4],3,border_radius=10)
        draw_text("SCALING",FONT,WHITE,100,y)
        scale_text=str(settings.get("scaling_mode","FILL")).upper()
        pygame.draw.rect(screen,PANEL2,scale_rect,border_radius=7)
        pygame.draw.rect(screen,CYAN if idx==4 else (95,95,112),scale_rect,2,border_radius=7)
        draw_text(scale_text,FONT,CYAN if idx==4 else WHITE,scale_rect.centerx,scale_rect.centery,center=True)

        button(back_rect,"BACK",idx==5)
        draw_text("FILL = entire screen   |   FIT = preserve aspect ratio   |   F11 toggles fullscreen",
                  TINY,MUTED,WIDTH//2,735,center=True)
        present()
        clock.tick(FPS); await asyncio.sleep(0)


async def info_screen(title,lines):
    while True:
        for e in get_events():
            if e.type==pygame.QUIT:return
            if e.type==pygame.KEYDOWN:return
        draw_background();header(title)
        y=160
        for line in lines:
            y=draw_wrapped(line,FONT,WHITE,90,y,1100)+28
        draw_text("Press any key to return",TINY,MUTED,WIDTH//2,740,center=True)
        present();clock.tick(FPS); await asyncio.sleep(0)

async def run():
    global ACTIVE_PROGRESS
    progress=load_progress()
    ACTIVE_PROGRESS=progress
    ensure_settings(progress)
    apply_display_mode(progress)
    if sys.platform == "emscripten":
        init_web_audio(progress)
    else:
        init_audio(progress)
    while True:
        result=await main_menu(progress)
        if result=="quit":break
        if isinstance(result,tuple) and result[0]=="worlds":
            await world_select(progress,result[1])
        save_progress(progress)
    pygame.quit()

if __name__=="__main__":
    asyncio.run(run())
