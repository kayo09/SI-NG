#!/usr/bin/env python3
# Four-Line Sheet (42 Bars) — minimal, single-file Tk app
# Now with beat sampling (in-built synth or mic when available) + timeline scrubbing
# Made with ♥ by GPT-5 Thinking & You

import tkinter as tk
from tkinter import ttk, font, messagebox
import sys, math, time, struct, io, os, tempfile, subprocess, threading
import wave

APP_TITLE = "Four-Line Sheet — 42 Bars (Sampler)"
BARS = 42
BEATS_PER_BAR = 4
STAFF_LINES = 4
BAR_W = 80
MARGIN_X = 60
MARGIN_Y = 30
LINE_SPACING = 22  # distance between the 4 staff lines
STAFF_HEIGHT = (STAFF_LINES - 1) * LINE_SPACING
CANVAS_H = MARGIN_Y*2 + STAFF_HEIGHT + 110  # extra for timeline + footer
BG = "#f7f3e8"        # parchment-ish
INK = "#2b2b2b"
ACCENT = "#645cff"    # soft purple
SUBTLE = "#b1a89f"

NOTE_COLORS = {
    "full": "#00a6a6",   # teal
    "half": "#c51d8a",   # magenta
    "combo": "#ff7f0e",  # orange
    "rest": "#555555",   # gray
}

# Optional audio libs
try:
    import winsound  # Windows beeps and PlaySound
except Exception:
    winsound = None

try:
    import simpleaudio as sa  # if user has it, great
except Exception:
    sa = None

# Optional mic libraries for "recorded vocal"
_sounddevice = None
try:
    import sounddevice as _sounddevice
except Exception:
    try:
        import pyaudio as _sounddevice  # fallback API; we'll wrap differently
    except Exception:
        _sounddevice = None


# ---------------- Audio helpers ----------------

def _sine(t, freq): return math.sin(2*math.pi*freq*t)
def _square(t, freq): return 1.0 if _sine(t, freq) >= 0 else -1.0
def _saw(t, freq): 
    f = (t*freq) % 1.0
    return 2.0*f - 1.0
def _triangle(t, freq):
    return 2.0*abs(_saw(t, freq)) - 1.0

WAV_FORMS = {
    "sine": _sine,
    "square": _square,
    "saw": _saw,
    "triangle": _triangle,
    "click": None,  # special
}

def synth_wave_bytes(waveform="click", freq=880.0, dur_ms=120, volume=0.6, sr=44100):
    """Return 16-bit mono WAV bytes for a short tone/click."""
    n_samples = max(1, int(sr * (dur_ms/1000.0)))
    frames = bytearray()
    if waveform == "click":
        # short decaying noise burst
        import random
        for i in range(n_samples):
            env = math.exp(-6.0 * i / n_samples)  # fast decay
            v = (random.random()*2 - 1) * env * volume
            val = max(-1.0, min(1.0, v))
            frames += struct.pack("<h", int(val * 32767))
    else:
        osc = WAV_FORMS.get(waveform, _sine)
        for i in range(n_samples):
            t = i / sr
            env = 1.0
            # quick fade to avoid clicks
            if i < 32:
                env *= i/32.0
            if i > n_samples-32:
                env *= (n_samples - i)/32.0
            v = osc(t, freq) * volume * env
            val = max(-1.0, min(1.0, v))
            frames += struct.pack("<h", int(val * 32767))
    # build wav
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))
    return bio.getvalue()

def write_wav_to_temp(wav_bytes, name_hint="sample"):
    fd, path = tempfile.mkstemp(prefix=f"{name_hint}_", suffix=".wav")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(wav_bytes)
    return path

class AudioOut:
    """Tiny audio dispatcher; uses simpleaudio if present, else winsound, else system player."""
    def __init__(self):
        self.backend = "none"
        if sa is not None:
            self.backend = "simpleaudio"
        elif winsound is not None and os.name == "nt":
            self.backend = "winsound"
        else:
            # Try detect a system player
            for cand in (["afplay"], ["aplay", "-q"], ["paplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
                if self._which(cand[0]):
                    self.backend = "system:" + cand[0]
                    self._system_cmd = cand
                    break

    def _which(self, exe):
        for p in os.environ.get("PATH", "").split(os.pathsep):
            try:
                full = os.path.join(p, exe)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    return full
            except Exception:
                pass
        return None

    def play_wav_bytes(self, wav_bytes):
        if self.backend == "simpleaudio":
            try:
                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    sample_rate = wf.getframerate()
                    width = wf.getsampwidth()
                    channels = wf.getnchannels()
                play_obj = sa.play_buffer(frames, channels, width, sample_rate)
                return
            except Exception:
                pass
        if self.backend == "winsound":
            try:
                path = write_wav_to_temp(wav_bytes, "play")
                winsound.PlaySound(path, winsound.SND_ASYNC)
                threading.Timer(5.0, lambda: safe_remove(path)).start()
                return
            except Exception:
                pass
        if self.backend.startswith("system:"):
            try:
                path = write_wav_to_temp(wav_bytes, "play")
                subprocess.Popen(self._system_cmd + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                threading.Timer(5.0, lambda: safe_remove(path)).start()
                return
            except Exception:
                pass
        return

def safe_remove(path):
    try:
        os.remove(path)
    except Exception:
        pass


# ---------------- App ----------------

class Sheet42(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.geometry("1180x520")
        self.minsize(960, 440)

        # State
        self.current_tool = tk.StringVar(value="full")  # full/half/combo/rest/erase
        self.user_name = tk.StringVar(value="You")
        self.assistant_name = "GPT-5 Thinking"
        self.left_clef_text = tk.StringVar(value="𝄢")  # Bass clef by default
        self.right_clef_text = tk.StringVar(value="𝄞") # Treble clef by default
        self.left_clef_label = tk.StringVar(value="Bass")
        self.right_clef_label = tk.StringVar(value="Treble")
        self.active_clef_side = tk.StringVar(value="right")  # pick left/right option
        self.BPM = tk.IntVar(value=90)
        self.metronome_running = False
        self.metronome_after = None
        self.metronome_pos = -1  # beat index across entire sheet
        self.scrub_var = tk.IntVar(value=0)  # timeline scrubber
        self.total_beats = BARS * BEATS_PER_BAR

        # Symbols placed: (bar, beat, line_index) -> {"id": tag/int, "kind": str}
        self.symbols = {}

        # Audio + samples per symbol kind
        self.audio = AudioOut()
        self.samples = {}  # kind -> wav_bytes
        self._init_default_samples()

        self._build_ui()
        self._draw_sheet()

    # ---------- UI ----------
    def _build_ui(self):
        self._build_header()
        self._build_toolbar()
        self._build_canvas()
        self._build_timeline()
        self._build_footer()

    def _build_header(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=12, pady=(10, 0))

        title_font = font.Font(family="Georgia", size=18, weight="bold")
        title = tk.Label(header, text="Four-Line Sheet (42 Bars) — Sampler", bg=BG, fg=INK, font=title_font)
        title.pack(side="left")

        heart = tk.Label(header, text="♥", bg=BG, fg=ACCENT, font=font.Font(size=18))
        heart.pack(side="left", padx=(8, 0))

        who = tk.Label(header, text="made by ", bg=BG, fg=SUBTLE)
        who.pack(side="left", padx=(8, 0))
        me = tk.Label(header, text=self.assistant_name, bg=BG, fg=ACCENT, font=font.Font(weight="bold"))
        me.pack(side="left", padx=(2, 0))

        amp = tk.Label(header, text=" & ", bg=BG, fg=SUBTLE)
        amp.pack(side="left")

        you_lbl = tk.Label(header, textvariable=self.user_name, bg=BG, fg=ACCENT, font=font.Font(weight="bold"))
        you_lbl.pack(side="left")

        # Right side: name editor
        name_box = tk.Frame(header, bg=BG)
        name_box.pack(side="right")
        tk.Label(name_box, text="Your name:", bg=BG, fg=SUBTLE).pack(side="left", padx=(0,6))
        tk.Entry(name_box, textvariable=self.user_name, width=16).pack(side="left")

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=12, pady=10)

        # Clef chooser
        clef_box = tk.LabelFrame(bar, text="Clef", bg=BG, fg=INK, padx=8, pady=6)
        clef_box.pack(side="left", padx=(0, 12))

        tk.Radiobutton(clef_box, text="Left", variable=self.active_clef_side, value="left", bg=BG, fg=INK, selectcolor=BG, command=self._redraw_clef).grid(row=0, column=0, sticky="w")
        tk.Entry(clef_box, textvariable=self.left_clef_text, width=5, justify="center").grid(row=0, column=1, padx=(6, 6))
        tk.Entry(clef_box, textvariable=self.left_clef_label, width=10).grid(row=0, column=2, padx=(6, 12))

        tk.Radiobutton(clef_box, text="Right", variable=self.active_clef_side, value="right", bg=BG, fg=INK, selectcolor=BG, command=self._redraw_clef).grid(row=1, column=0, sticky="w")
        tk.Entry(clef_box, textvariable=self.right_clef_text, width=5, justify="center").grid(row=1, column=1, padx=(6, 6))
        tk.Entry(clef_box, textvariable=self.right_clef_label, width=10).grid(row=1, column=2, padx=(6, 12))

        ttk.Button(clef_box, text="Apply", command=self._redraw_clef).grid(row=0, column=3, rowspan=2, padx=4)

        # Tool buttons
        tools = tk.LabelFrame(bar, text="Tools", bg=BG, fg=INK, padx=8, pady=6)
        tools.pack(side="left", padx=(0, 12))

        self._mk_tool_button(tools, "Full ●", "full").pack(side="left", padx=4)
        self._mk_tool_button(tools, "Half ○", "half").pack(side="left", padx=4)
        self._mk_tool_button(tools, "Combo ◍", "combo").pack(side="left", padx=4)
        self._mk_tool_button(tools, "Rest ⟂", "rest").pack(side="left", padx=4)
        self._mk_tool_button(tools, "Erase ⨯", "erase").pack(side="left", padx=4)

        # Metronome
        metro = tk.LabelFrame(bar, text="Metronome", bg=BG, fg=INK, padx=8, pady=6)
        metro.pack(side="left", padx=(0, 12))

        tk.Label(metro, text="BPM", bg=BG).pack(side="left", padx=(0,6))
        bpm_scale = ttk.Scale(metro, from_=40, to=208, orient="horizontal", variable=self.BPM, length=180)
        bpm_scale.pack(side="left")
        self.bpm_label = tk.Label(metro, text="90", bg=BG, fg=SUBTLE)
        self.bpm_label.pack(side="left", padx=(6, 6))
        self.BPM.trace_add("write", lambda *_: self.bpm_label.config(text=str(self.BPM.get())))

        self.metro_btn = ttk.Button(metro, text="Start", command=self.toggle_metronome)
        self.metro_btn.pack(side="left", padx=6)

        # Sampler
        sampler = tk.LabelFrame(bar, text="Sample (Synth or Mic)", bg=BG, fg=INK, padx=8, pady=6)
        sampler.pack(side="left", padx=(0, 12))

        self.sample_target = tk.StringVar(value="full")  # which symbol kind to set
        ttk.Combobox(sampler, values=["full","half","combo","rest"], textvariable=self.sample_target, width=7, state="readonly").grid(row=0, column=0, padx=4)

        self.waveform = tk.StringVar(value="click")
        ttk.Combobox(sampler, values=["click","sine","square","triangle","saw"], textvariable=self.waveform, width=8, state="readonly").grid(row=0, column=1, padx=4)

        self.freq_var = tk.IntVar(value=880)
        self.dur_var = tk.IntVar(value=120)
        self.vol_var = tk.DoubleVar(value=0.6)
        tk.Label(sampler, text="Hz", bg=BG).grid(row=0, column=2, padx=(6,0))
        tk.Entry(sampler, textvariable=self.freq_var, width=6).grid(row=0, column=3, padx=4)
        tk.Label(sampler, text="ms", bg=BG).grid(row=0, column=4, padx=(6,0))
        tk.Entry(sampler, textvariable=self.dur_var, width=5).grid(row=0, column=5, padx=4)

        ttk.Button(sampler, text="Generate", command=self.generate_sample).grid(row=0, column=6, padx=4)
        ttk.Button(sampler, text="Preview", command=self.preview_sample).grid(row=0, column=7, padx=4)

        ttk.Separator(sampler, orient="vertical").grid(row=0, column=8, sticky="ns", padx=6)

        ttk.Button(sampler, text="Record Mic", command=self.record_mic).grid(row=0, column=9, padx=4)

        # Help
        help_box = tk.Frame(bar, bg=BG)
        help_box.pack(side="right")
        ttk.Button(help_box, text="Help", command=self._show_help).pack(side="right")

    def _mk_tool_button(self, parent, label, kind):
        def set_tool():
            self.current_tool.set(kind)
            self.status_var.set(f"Tool: {label}")
        btn = ttk.Button(parent, text=label, command=set_tool)
        return btn

    def _build_canvas(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=12)

        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, height=CANVAS_H-80)
        self.hscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.hscroll.set)

        self.canvas.pack(fill="both", expand=True, side="top")
        self.hscroll.pack(fill="x", side="bottom")

        total_w = MARGIN_X*2 + BAR_W*BARS
        self.canvas.config(scrollregion=(0, 0, total_w, CANVAS_H))

        # Bindings
        self.canvas.bind("<Button-1>", self.on_click_place)
        self.canvas.bind("<Button-3>", self.on_right_click_erase)
        self.canvas.bind("<Configure>", lambda e: self._draw_sheet())

        self.metro_line = None

    def _build_timeline(self):
        tl = tk.Frame(self, bg=BG)
        tl.pack(fill="x", padx=12, pady=(0, 4))

        ttk.Separator(tl, orient="horizontal").pack(fill="x", pady=(2,8))

        left = tk.Frame(tl, bg=BG)
        left.pack(side="left")
        ttk.Button(left, text="⟲ Rewind", command=lambda: self.scrub_to(0)).pack(side="left", padx=4)
        ttk.Button(left, text="◀ Bar", command=lambda: self.scrub_by(-BEATS_PER_BAR)).pack(side="left", padx=4)
        ttk.Button(left, text="Beat ◀", command=lambda: self.scrub_by(-1)).pack(side="left", padx=4)
        ttk.Button(left, text="Beat ▶", command=lambda: self.scrub_by(1)).pack(side="left", padx=4)
        ttk.Button(left, text="Bar ▶", command=lambda: self.scrub_by(BEATS_PER_BAR)).pack(side="left", padx=4)

        mid = tk.Frame(tl, bg=BG)
        mid.pack(side="left", padx=12)
        self.scrub = ttk.Scale(mid, from_=0, to=self.total_beats-1, orient="horizontal", length=520, variable=self.scrub_var, command=self._on_scrub)
        self.scrub.pack(side="left")
        self.scrub_label = tk.Label(mid, text="0 / {}".format(self.total_beats-1), bg=BG, fg=SUBTLE)
        self.scrub_label.pack(side="left", padx=6)

        right = tk.Frame(tl, bg=BG)
        right.pack(side="right")
        ttk.Button(right, text="Play From Here", command=self.play_from_scrub).pack(side="left", padx=4)

    def _build_footer(self):
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=12, pady=(6, 10))
        self.status_var = tk.StringVar(value="Click to place symbols. Right-click to erase.")
        status = tk.Label(footer, textvariable=self.status_var, bg=BG, fg=SUBTLE, anchor="w")
        status.pack(fill="x")

    # ---------- Drawing ----------
    def _draw_sheet(self):
        self.canvas.delete("all")

        # Staff lines
        top = MARGIN_Y
        left = MARGIN_X
        right = MARGIN_X + BAR_W*BARS
        for i in range(STAFF_LINES):
            y = top + i*LINE_SPACING
            self.canvas.create_line(left, y, right, y, fill=INK, width=1.6)

        # Bars and beats
        for b in range(BARS + 1):
            x = MARGIN_X + b*BAR_W
            w = 1.2 if b % 4 else 2.2  # heavier every 4 bars
            color = INK if b % 4 == 0 else SUBTLE
            self.canvas.create_line(x, top, x, top + STAFF_HEIGHT, fill=color, width=w)

            if b < BARS:
                self.canvas.create_text(x + BAR_W/2, top + STAFF_HEIGHT + 14, text=str(b+1), fill=SUBTLE, font=("Helvetica", 9))

            for beat in range(BEATS_PER_BAR):
                bx = MARGIN_X + b*BAR_W + (beat+0.5)*(BAR_W/BEATS_PER_BAR)
                self.canvas.create_line(bx, top + STAFF_HEIGHT + 2, bx, top + STAFF_HEIGHT + 8, fill=SUBTLE)

        # Clef
        self._draw_clef()

        # Re-draw placed symbols
        old = self.symbols.copy()
        self.symbols.clear()
        for (b, bt, ln), meta in old.items():
            self._draw_symbol_at(b, bt, ln, meta["kind"])

        # Metronome line & place at current position
        self._draw_metronome_line()

    def _draw_clef(self):
        # Place active clef symbol near the start
        top = MARGIN_Y
        y_mid = top + STAFF_HEIGHT/2
        x = MARGIN_X - 30
        if self.active_clef_side.get() == "left":
            txt = self.left_clef_text.get().strip() or "𝄢"
            lbl = self.left_clef_label.get().strip() or "Bass"
        else:
            txt = self.right_clef_text.get().strip() or "𝄞"
            lbl = self.right_clef_label.get().strip() or "Treble"
        try:
            self.canvas.create_text(x, y_mid, text=txt, fill=ACCENT, font=("Georgia", 28, "bold"))
        except:
            self.canvas.create_rectangle(x-16, y_mid-16, x+16, y_mid+16, outline=ACCENT, width=2)
            self.canvas.create_text(x, y_mid, text=lbl[:1], fill=ACCENT, font=("Helvetica", 14, "bold"))
        self.canvas.create_text(x, top + STAFF_HEIGHT + 34, text=lbl, fill=ACCENT, font=("Helvetica", 9, "bold"))

    def _redraw_clef(self):
        self._draw_sheet()

    # ---------- Placement ----------
    def on_click_place(self, event):
        b, bt = self._hit_bar_and_beat(event.x)
        if b is None:
            return
        ln = self._nearest_line_index(event.y)
        kind = self.current_tool.get()
        if kind == "erase":
            self._erase_at(b, bt, ln)
        else:
            self._place_at(b, bt, ln, kind)

    def on_right_click_erase(self, event):
        b, bt = self._hit_bar_and_beat(event.x)
        if b is None:
            return
        ln = self._nearest_line_index(event.y)
        self._erase_at(b, bt, ln)

    def _hit_bar_and_beat(self, x_canvas):
        x = self.canvas.canvasx(x_canvas)
        area_left = MARGIN_X
        area_right = MARGIN_X + BAR_W*BARS
        if x < area_left or x > area_right:
            return None, None
        rel = x - MARGIN_X
        bar = int(rel // BAR_W)
        within = rel - bar*BAR_W
        beat_w = BAR_W / BEATS_PER_BAR
        beat = int(within // beat_w)
        beat = min(max(0, beat), BEATS_PER_BAR-1)
        return bar, beat

    def _nearest_line_index(self, y_canvas):
        y = self.canvas.canvasy(y_canvas)
        top = MARGIN_Y
        idx = 0
        best_d = 10**9
        for i in range(STAFF_LINES):
            ly = top + i*LINE_SPACING
            d = abs(y - ly)
            if d < best_d:
                best_d = d
                idx = i
        return idx

    def _erase_at(self, b, bt, ln):
        key = (b, bt, ln)
        if key in self.symbols:
            self.canvas.delete(self.symbols[key]["id"])
            del self.symbols[key]

    def _place_at(self, b, bt, ln, kind):
        self._erase_at(b, bt, ln)
        self._draw_symbol_at(b, bt, ln, kind)

    def _slot_center(self, b, bt, ln):
        x = MARGIN_X + b*BAR_W + (bt + 0.5)*(BAR_W/BEATS_PER_BAR)
        y = MARGIN_Y + ln*LINE_SPACING
        return x, y

    def _draw_symbol_at(self, b, bt, ln, kind):
        x, y = self._slot_center(b, bt, ln)
        col = NOTE_COLORS.get(kind, INK)
        size = 10

        if kind == "full":
            item = self.canvas.create_oval(x-size, y-size, x+size, y+size, fill=col, outline="")
        elif kind == "half":
            item = self.canvas.create_oval(x-size, y-size, x+size, y+size, outline=col, width=2)
        elif kind == "combo":
            r = 6
            item1 = self.canvas.create_oval(x-r-4, y-r, x-r+4, y+r, fill=col, outline="")
            item2 = self.canvas.create_oval(x+r-4, y-r, x+r+4, y+r, fill=col, outline="")
            item = (item1, item2)
        elif kind == "rest":
            w, h = 16, 6
            rect = self.canvas.create_rectangle(x-w/2, y-h/2, x+w/2, y+h/2, fill=col, outline="")
            notch = self.canvas.create_line(x-w/2, y-h/2, x+w/2, y+h/2, fill=BG, width=2)
            item = (rect, notch)
        else:
            return

        if isinstance(item, tuple):
            tag = f"sym_{b}_{bt}_{ln}"
            for it in item:
                self.canvas.addtag_withtag(tag, it)
            group_id = self.canvas.create_rectangle(0,0,0,0, outline="", fill="")
            self.canvas.addtag_withtag(tag, group_id)
            self.symbols[(b, bt, ln)] = {"id": tag, "kind": kind}
        else:
            self.symbols[(b, bt, ln)] = {"id": item, "kind": kind}

    # ---------- Timeline / Scrubbing ----------
    def _draw_metronome_line(self):
        if self.metro_line is not None:
            try:
                self.canvas.delete(self.metro_line)
            except:
                pass
        y0 = MARGIN_Y - 10
        y1 = MARGIN_Y + STAFF_HEIGHT + 10
        pos = self.metronome_pos if self.metronome_pos >= 0 else 0
        b = pos // BEATS_PER_BAR
        bt = pos % BEATS_PER_BAR
        x = MARGIN_X + b*BAR_W + (bt + 0.5)*(BAR_W/BEATS_PER_BAR)
        self.metro_line = self.canvas.create_line(x, y0, x, y1, fill=ACCENT, width=2, dash=(3,3))

    def scrub_to(self, new_pos):
        new_pos = max(0, min(self.total_beats-1, new_pos))
        self.metronome_pos = new_pos
        self.scrub_var.set(new_pos)
        self._draw_metronome_line()
        self._ensure_line_visible()

    def scrub_by(self, delta):
        self.scrub_to((self.metronome_pos if self.metronome_pos >= 0 else 0) + delta)

    def _on_scrub(self, *args):
        self.metronome_pos = int(float(self.scrub_var.get()))
        self._draw_metronome_line()
        self.scrub_label.config(text="{} / {}".format(self.metronome_pos, self.total_beats-1))
        self._ensure_line_visible()

    def _ensure_line_visible(self):
        if self.metro_line is None: return
        coords = self.canvas.coords(self.metro_line)
        if not coords: return
        x = coords[0]
        vx0, vx1 = self.canvas.xview()
        total_w = MARGIN_X*2 + BAR_W*BARS
        view_left = vx0 * total_w
        view_right = vx1 * total_w
        margin = 40
        if x < view_left + margin:
            new_left = max(0, (x - 200) / total_w)
            self.canvas.xview_moveto(new_left)
        elif x > view_right - margin:
            new_left = max(0, (x - (view_right - view_left) + 200) / total_w)
            self.canvas.xview_moveto(new_left)

    def play_from_scrub(self):
        self.metronome_pos = int(float(self.scrub_var.get())) - 1  # will advance on next tick
        self._draw_metronome_line()
        if not self.metronome_running:
            self._start_metronome()

    # ---------- Metronome ----------
    def toggle_metronome(self):
        if self.metronome_running:
            self._stop_metronome()
        else:
            self._start_metronome()

    def _start_metronome(self):
        if self.metronome_running:
            return
        self.metronome_running = True
        self.metro_btn.config(text="Stop")
        self._tick_metronome()

    def _stop_metronome(self):
        self.metronome_running = False
        self.metro_btn.config(text="Start")
        if self.metronome_after:
            self.after_cancel(self.metronome_after)
            self.metronome_after = None

    def _current_symbol_kind_for_pos(self, pos):
        # Prioritize: combo > full > half > rest ; if none return None
        b = pos // BEATS_PER_BAR
        bt = pos % BEATS_PER_BAR
        found = []
        for ln in range(STAFF_LINES):
            key = (b, bt, ln)
            if key in self.symbols:
                found.append(self.symbols[key]["kind"])
        if not found:
            return None
        for preferred in ("combo","full","half","rest"):
            if preferred in found:
                return preferred
        return found[0]

    def _tick_metronome(self):
        if not self.metronome_running:
            return

        # advance
        self.metronome_pos = (self.metronome_pos + 1) % self.total_beats
        self.scrub_var.set(self.metronome_pos)
        self.scrub_label.config(text="{} / {}".format(self.metronome_pos, self.total_beats-1))
        self._draw_metronome_line()
        self._ensure_line_visible()

        # play sample for this beat (placeholder sound defined by symbol kind)
        kind = self._current_symbol_kind_for_pos(self.metronome_pos)
        if kind is None:
            if (self.metronome_pos % BEATS_PER_BAR) == 0:
                self._play_click(downbeat=True)
        else:
            self._play_kind(kind)

        # subtle flash: circle at current beat slot
        b = self.metronome_pos // BEATS_PER_BAR
        bt = self.metronome_pos % BEATS_PER_BAR
        x, y = self._slot_center(b, bt, STAFF_LINES//2)
        flash = self.canvas.create_oval(x-6, y-6, x+6, y+6, outline=ACCENT, width=2)
        self.after(80, lambda: self.canvas.delete(flash))

        # schedule next tick
        bpm = max(40, min(208, self.BPM.get()))
        interval_ms = int(60000 / bpm)
        self.metronome_after = self.after(interval_ms, self._tick_metronome)

    def _play_click(self, downbeat=False):
        hz = 1200 if downbeat else 900
        wav = synth_wave_bytes("click", hz, dur_ms=60, volume=0.6)
        self.audio.play_wav_bytes(wav)

    def _play_kind(self, kind):
        wav = self.samples.get(kind)
        if wav:
            self.audio.play_wav_bytes(wav)

    # ---------- Samples ----------
    def _init_default_samples(self):
        self.samples["full"]  = synth_wave_bytes("sine",     660, 120, 0.55)
        self.samples["half"]  = synth_wave_bytes("triangle", 520, 110, 0.55)
        self.samples["combo"] = synth_wave_bytes("square",   800, 130, 0.55)
        self.samples["rest"]  = synth_wave_bytes("click",    300,  40, 0.10)

    def generate_sample(self):
        try:
            wf = self.waveform.get()
            hz = float(self.freq_var.get())
            ms = int(self.dur_var.get())
            ms = max(20, min(1500, ms))
        except Exception:
            messagebox.showerror("Sample", "Invalid synth settings.")
            return
        wav = synth_wave_bytes(wf, hz, ms, 0.6)
        target = self.sample_target.get()
        self.samples[target] = wav
        self.status_var.set(f"Set {target} sample: {wf}, {int(hz)} Hz, {ms} ms")
        self.audio.play_wav_bytes(wav)

    def preview_sample(self):
        target = self.sample_target.get()
        wav = self.samples.get(target)
        if wav:
            self.audio.play_wav_bytes(wav)
        else:
            messagebox.showinfo("Sample", f"No sample set for {target}.")

    def record_mic(self):
        dur_ms = max(100, min(3000, self.dur_var.get()))
        target = self.sample_target.get()

        if _sounddevice is None:
            messagebox.showinfo("Mic record", "Mic recording needs 'sounddevice' or 'pyaudio' installed.\n\nExample:\n  pip install sounddevice\n\nWe'll keep it optional to avoid bloat.")
            return

        def _record_thread():
            try:
                sr = 44100
                frames = int(sr * (dur_ms/1000.0))
                if 'sounddevice' in str(_sounddevice):
                    import sounddevice as sd
                    data = sd.rec(frames, samplerate=sr, channels=1, dtype="int16")
                    sd.wait()
                    pcm = data.tobytes()
                else:
                    import pyaudio
                    p = pyaudio.PyAudio()
                    stream = p.open(format=pyaudio.paInt16, channels=1, rate=sr, input=True, frames_per_buffer=1024)
                    buf = bytearray()
                    to_read = frames
                    while to_read > 0:
                        chunk = min(1024, to_read)
                        buf.extend(stream.read(chunk))
                        to_read -= chunk
                    stream.stop_stream(); stream.close(); p.terminate()
                    pcm = bytes(buf)

                bio = io.BytesIO()
                with wave.open(bio, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sr)
                    wf.writeframes(pcm)
                wav = bio.getvalue()
                self.samples[target] = wav
                self.status_var.set(f"Recorded mic sample for {target} ({dur_ms} ms).")
                self.audio.play_wav_bytes(wav)
            except Exception as e:
                messagebox.showerror("Mic record", f"Failed to record mic: {e}")

        threading.Thread(target=_record_thread, daemon=True).start()

    # ---------- Misc ----------
    def _show_help(self):
        tip = (
            "Quick guide:\n"
            "• 4-line staff with 42 bars. Each bar has 4 beats.\n"
            "• Tools: Full ●, Half ○, Combo ◍, Rest ⟂, Erase ⨯. Left-click to place, right-click to erase.\n"
            "• Clef box: choose between two customizable clefs (text/glyph + label).\n"
            "• Metronome: Start/Stop at chosen BPM. It moves a timeline line.\n"
            "• Timeline scrubbing: drag the slider or use the buttons (Beat/Bar, Rewind). 'Play From Here' starts at the slider.\n"
            "• Sampler: assign a placeholder sound to each symbol kind via a small in-built synth (click/sine/square/triangle/saw),\n"
            "  or use 'Record Mic' (optional; needs 'sounddevice' or 'pyaudio').\n"
            "Notes:\n"
            "• This is intentionally lightweight and single-file. Audio backends are best-effort.\n"
            "• On some systems you may need 'simpleaudio' or a system player (afplay/aplay)."
        )
        messagebox.showinfo("Help", tip)


if __name__ == "__main__":
    app = Sheet42()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
