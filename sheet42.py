#!/usr/bin/env python3
# Four-Line Sheet (42 Bars) — Sampler Edition (single file)
# Made with ♥ by GPT-5 Thinking & You
#
# Features:
# - 4-line staff, 42 bars, 4 beats/bar
# - Tools: full, half, combo, rest, erase
# - Two customizable clefs (left/right)
# - Visual metronome with BPM
# - Timeline controls: Play/Pause/Stop + Scrub to any beat
# - Simple built-in synth sampler (sine/square/saw) per symbol; pitch comes from lane (4 lines + 4 gaps = 8 lanes)
# - Optional mic recording, if 'sounddevice' is installed (falls back gracefully if not)
# - No extra files; everything lives in this single script

import tkinter as tk
from tkinter import ttk, font, messagebox
import sys, math, time, struct, io, shutil, tempfile, subprocess

APP_TITLE = "Four-Line Sheet — 42 Bars (Sampler)"
BARS = 42
BEATS_PER_BAR = 4
STAFF_LINES = 4
LANES = 8  # 4 lines + 4 gaps
BAR_W = 80
MARGIN_X = 60
MARGIN_Y = 30
LINE_SPACING = 22
STAFF_HEIGHT = (STAFF_LINES - 1) * LINE_SPACING
CANVAS_H = MARGIN_Y*2 + STAFF_HEIGHT + 120
BG = "#f7f3e8"
INK = "#2b2b2b"
ACCENT = "#645cff"
SUBTLE = "#b1a89f"

NOTE_COLORS = {
    "full": "#00a6a6",
    "half": "#c51d8a",
    "combo": "#ff7f0e",
    "rest": "#555555",
}

try:
    import winsound
except Exception:
    winsound = None

# Optional sound recording (mic) support
try:
    import sounddevice as sd
    HAVE_SD = True
except Exception:
    HAVE_SD = False

# -------------- Tiny synth & audio utils --------------

def hz(note_str):
    """Very tiny note-to-hz helper for a few common notes (G-centric).
       Accepts strings like 'G3','G#3','A3','A#3','B3','C4','C#4','D4'.
       Defaults to A4=440 tuning."""
    semis = {"C": -9, "C#": -8, "Db": -8, "D": -7, "D#": -6, "Eb": -6, "E": -5, "F": -4, "F#": -3, "Gb": -3,
             "G": -2, "G#": -1, "Ab": -1, "A": 0, "A#": 1, "Bb": 1, "B": 2}
    try:
        if len(note_str) == 2:
            n, o = note_str[0], int(note_str[1])
            acc = ""
        elif len(note_str) == 3:
            n, acc, o = note_str[0], note_str[1], int(note_str[2])
            n = n+acc
        else:
            return 440.0
        # relative to A4 (o=4, 'A')
        semi = semis.get(n, 0) + (o - 4) * 12
        return 440.0 * (2.0 ** (semi / 12.0))
    except Exception:
        return 440.0

DEFAULT_LANE_NOTES = ["G3","G#3","A3","A#3","B3","C4","C#4","D4"]  # 8 lanes, low->high

def lane_to_hz(lane_idx, custom_map=None):
    arr = custom_map if custom_map else DEFAULT_LANE_NOTES
    lane_idx = max(0, min(LANES-1, lane_idx))
    return hz(arr[lane_idx])

def synth_wave(waveform, freq_hz, secs, sr=44100, amp=0.25, attack=0.005, release=0.02):
    """Generate mono PCM16 samples (bytes) of a simple waveform with tiny AR envelope."""
    n = int(secs * sr)
    out = io.BytesIO()
    # We'll build raw pcm16 first
    samples = []
    for i in range(n):
        t = i / sr
        # base wave
        if waveform == "square":
            val = 1.0 if (math.sin(2*math.pi*freq_hz*t) >= 0) else -1.0
        elif waveform == "saw":
            # simple saw
            frac = (t * freq_hz) % 1.0
            val = 2.0*frac - 1.0
        else:
            # sine
            val = math.sin(2*math.pi*freq_hz*t)
        # envelope
        if t < attack:
            env = t / attack
        elif t > secs - release:
            env = max(0.0, (secs - t) / release)
        else:
            env = 1.0
        s = int(max(-1.0, min(1.0, val * env * amp)) * 32767)
        samples.append(struct.pack("<h", s))
    pcm = b"".join(samples)
    # Wrap as a minimal WAV (PCM16, mono)
    return pcm16_to_wav(pcm, sr, channels=1)

def pcm16_to_wav(pcm_bytes, sr, channels=1):
    """Wrap raw pcm16 little-endian into a WAV container and return bytes."""
    byte_rate = sr * channels * 2
    block_align = channels * 2
    data_size = len(pcm_bytes)
    riff_size = 36 + data_size
    b = io.BytesIO()
    b.write(b"RIFF")
    b.write(struct.pack("<I", riff_size))
    b.write(b"WAVE")
    b.write(b"fmt ")
    b.write(struct.pack("<IHHIIHH", 16, 1, channels, sr, byte_rate, block_align, 16))
    b.write(b"data")
    b.write(struct.pack("<I", data_size))
    b.write(pcm_bytes)
    return b.getvalue()

def play_wav_bytes(wav_bytes):
    """Attempt best-effort playback. Priority: winsound (Windows), else afplay/aplay/ffplay."""
    if winsound:
        try:
            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY | winsound.SND_ASYNC)
            return True
        except Exception:
            pass
    # Fallback: temp file + system player
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        f.write(wav_bytes)
        path = f.name
    for cmd in (["afplay", path], ["aplay", path], ["ffplay", "-nodisp", "-autoexit", path]):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                continue
    return False

# -------------- App --------------

class Sheet42(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.geometry("1180x520")
        self.minsize(980, 480)

        # State
        self.current_tool = tk.StringVar(value="full")  # full/half/combo/rest/erase
        self.user_name = tk.StringVar(value="You")
        self.assistant_name = "GPT-5 Thinking"
        self.left_clef_text = tk.StringVar(value="𝄢")
        self.right_clef_text = tk.StringVar(value="𝄞")
        self.left_clef_label = tk.StringVar(value="Bass")
        self.right_clef_label = tk.StringVar(value="Treble")
        self.active_clef_side = tk.StringVar(value="right")
        self.BPM = tk.IntVar(value=100)

        # Timeline
        self.is_playing = False
        self.current_pos = 0  # beat index [0, total_beats)
        self.after_id = None

        # Metronome styling
        self.metro_line = None

        # Symbols and audio
        self.symbols = {}  # (bar, beat, lane) -> {"id": <canvas tag or id>, "kind": str}
        self.waveform = tk.StringVar(value="sine")
        self.full_secs = 1.0  # 1 beat at 60 BPM baseline; actual time depends on BPM at playback
        self.half_secs = 0.5
        self.combo_split = (0.5, 0.5)  # two events per beat
        self.lane_notes = DEFAULT_LANE_NOTES.copy()  # editable mapping

        # Recording (optional)
        self.record_secs = tk.DoubleVar(value=0.5)
        self.record_sr = 44100
        self.record_sample_bytes = None  # last recorded wav bytes

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

        title_font = font.Font(family="Georgia", size=20, weight="bold")
        title = tk.Label(header, text="Four-Line Sheet (Sampler)", bg=BG, fg=INK, font=title_font)
        title.pack(side="left")

        heart = tk.Label(header, text="♥", bg=BG, fg=ACCENT, font=font.Font(size=20))
        heart.pack(side="left", padx=(8, 0))

        who = tk.Label(header, text="made by ", bg=BG, fg=SUBTLE)
        who.pack(side="left", padx=(8, 0))
        me = tk.Label(header, text=self.assistant_name, bg=BG, fg=ACCENT, font=font.Font(weight="bold"))
        me.pack(side="left", padx=(2, 0))

        amp = tk.Label(header, text=" & ", bg=BG, fg=SUBTLE)
        amp.pack(side="left")

        you_lbl = tk.Label(header, textvariable=self.user_name, bg=BG, fg=ACCENT, font=font.Font(weight="bold"))
        you_lbl.pack(side="left")

        name_box = tk.Frame(header, bg=BG)
        name_box.pack(side="right")
        tk.Label(name_box, text="Your name:", bg=BG, fg=SUBTLE).pack(side="left", padx=(0,6))
        tk.Entry(name_box, textvariable=self.user_name, width=16).pack(side="left")

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=12, pady=8)

        # Clefs
        clef_box = tk.LabelFrame(bar, text="Clef", bg=BG, fg=INK, padx=8, pady=6)
        clef_box.pack(side="left", padx=(0, 12))

        tk.Radiobutton(clef_box, text="Left", variable=self.active_clef_side, value="left",
                       bg=BG, fg=INK, selectcolor=BG, command=self._redraw).grid(row=0, column=0, sticky="w")
        tk.Entry(clef_box, textvariable=self.left_clef_text, width=5, justify="center").grid(row=0, column=1, padx=(6, 6))
        tk.Entry(clef_box, textvariable=self.left_clef_label, width=10).grid(row=0, column=2, padx=(6, 12))

        tk.Radiobutton(clef_box, text="Right", variable=self.active_clef_side, value="right",
                       bg=BG, fg=INK, selectcolor=BG, command=self._redraw).grid(row=1, column=0, sticky="w")
        tk.Entry(clef_box, textvariable=self.right_clef_text, width=5, justify="center").grid(row=1, column=1, padx=(6, 6))
        tk.Entry(clef_box, textvariable=self.right_clef_label, width=10).grid(row=1, column=2, padx=(6, 12))

        ttk.Button(clef_box, text="Apply", command=self._redraw).grid(row=0, column=3, rowspan=2, padx=4)

        # Tools
        tools = tk.LabelFrame(bar, text="Tools", bg=BG, fg=INK, padx=8, pady=6)
        tools.pack(side="left", padx=(0, 12))
        for label, kind in [("Full ●", "full"), ("Half ○", "half"), ("Combo ◍", "combo"), ("Rest ⟂", "rest"), ("Erase ⨯", "erase")]:
            ttk.Button(tools, text=label, command=lambda k=kind: self._set_tool(k)).pack(side="left", padx=4)

        # Synth / sample controls
        synth = tk.LabelFrame(bar, text="Sample Engine", bg=BG, fg=INK, padx=8, pady=6)
        synth.pack(side="left", padx=(0, 12))

        tk.Label(synth, text="Wave", bg=BG).pack(side="left", padx=(0,4))
        ttk.Combobox(synth, width=7, textvariable=self.waveform, values=("sine","square","saw"), state="readonly").pack(side="left", padx=(0,10))

        ttk.Button(synth, text="Test Tone", command=self._test_tone).pack(side="left", padx=4)

        if HAVE_SD:
            rec_btn = ttk.Button(synth, text="Record Mic", command=self._record_sample)
            rec_btn.pack(side="left", padx=(10,4))
            tk.Label(synth, text="sec", bg=BG).pack(side="left", padx=(6,2))
            ttk.Spinbox(synth, from_=0.2, to=3.0, increment=0.1, textvariable=self.record_secs, width=5).pack(side="left")
            ttk.Button(synth, text="Test Recording", command=self._play_recording).pack(side="left", padx=4)
        else:
            tk.Label(synth, text="(Mic record unavailable)", bg=BG, fg=SUBTLE).pack(side="left", padx=6)

        # Pitch mapping
        pitch = tk.LabelFrame(bar, text="Lane→Pitch (low→high)", bg=BG, fg=INK, padx=8, pady=6)
        pitch.pack(side="left", padx=(0, 12))
        self.pitch_entries = []
        for i in range(LANES):
            e = tk.Entry(pitch, width=4, justify="center")
            e.insert(0, self.lane_notes[i])
            e.pack(side="left", padx=2)
            self.pitch_entries.append(e)
        ttk.Button(pitch, text="Apply", command=self._apply_pitch_map).pack(side="left", padx=6)

        # Help
        ttk.Button(bar, text="Help", command=self._show_help).pack(side="right")

    def _build_canvas(self):
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=12)

        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, height=CANVAS_H)
        self.hscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.hscroll.set)

        self.canvas.pack(fill="both", expand=True, side="top")
        self.hscroll.pack(fill="x", side="bottom")

        total_w = MARGIN_X*2 + BAR_W*BARS
        self.canvas.config(scrollregion=(0, 0, total_w, CANVAS_H))

        self.canvas.bind("<Button-1>", self.on_click_place)
        self.canvas.bind("<Button-3>", self.on_right_click_erase)
        self.canvas.bind("<Configure>", lambda e: self._redraw())

    def _build_timeline(self):
        tl = tk.Frame(self, bg=BG)
        tl.pack(fill="x", padx=12, pady=(6, 10))

        ttk.Button(tl, text="⟲ Stop", command=self.stop).pack(side="left", padx=4)
        self.play_btn = ttk.Button(tl, text="▶ Play", command=self.play_pause)
        self.play_btn.pack(side="left", padx=4)

        tk.Label(tl, text="BPM", bg=BG).pack(side="left", padx=(12,4))
        self.bpm_label = tk.Label(tl, text=str(self.BPM.get()), bg=BG, fg=SUBTLE)
        self.bpm_label.pack(side="left", padx=(6, 6))
        bpm_scale = ttk.Scale(tl, from_=40, to=208, orient="horizontal", variable=self.BPM, length=240, command=lambda v: self._update_bpm_label())
        bpm_scale.pack(side="left")
        self.BPM.trace_add("write", lambda *_: self._update_bpm_label())

        tk.Label(tl, text=" Scrub:", bg=BG).pack(side="left", padx=(12,4))
        self.scrub = ttk.Scale(tl, from_=0, to=BARS*BEATS_PER_BAR-1, orient="horizontal", length=420, command=self._on_scrub_change)
        self.scrub.pack(side="left")
        ttk.Button(tl, text="Go", command=self._apply_scrub).pack(side="left", padx=6)

        self.pos_label = tk.Label(tl, text="Beat 1 / 168", bg=BG, fg=SUBTLE)
        self.pos_label.pack(side="right")

    def _build_footer(self):
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=12, pady=(0, 10))
        self.status_var = tk.StringVar(value="Left-click to place. Right-click to erase. Combo plays two quick hits.")
        status = tk.Label(footer, textvariable=self.status_var, bg=BG, fg=SUBTLE, anchor="w")
        status.pack(fill="x")

    # ---------- Drawing ----------
    def _redraw(self):
        self._draw_sheet()

    def _draw_sheet(self):
        self.canvas.delete("all")
        top = MARGIN_Y
        left = MARGIN_X
        right = MARGIN_X + BAR_W*BARS

        # Staff lines
        for i in range(STAFF_LINES):
            y = top + i*LINE_SPACING
            self.canvas.create_line(left, y, right, y, fill=INK, width=1.6)

        # Lanes (gaps markers as subtle dotted guides)
        # Lanes are interleaved: line0, gap0, line1, gap1, line2, gap2, line3, gap3
        self.lane_ys = []
        for i in range(STAFF_LINES):
            self.lane_ys.append(top + i*LINE_SPACING)  # line
            if i < STAFF_LINES-1:
                self.lane_ys.append(top + i*LINE_SPACING + LINE_SPACING/2)  # gap
        # Add extra gap after last line to make 8 lanes
        self.lane_ys.append(top + (STAFF_LINES-1)*LINE_SPACING + LINE_SPACING/2)

        # draw faint dotted guides for gaps (odd indices)
        for idx, y in enumerate(self.lane_ys):
            if idx % 2 == 1:  # gaps
                self.canvas.create_line(left, y, right, y, fill=SUBTLE, dash=(2,3))

        # Bars + beat ticks + numbers
        for b in range(BARS + 1):
            x = MARGIN_X + b*BAR_W
            w = 1.2 if b % 4 else 2.2
            color = INK if b % 4 == 0 else SUBTLE
            self.canvas.create_line(x, top, x, top + STAFF_HEIGHT, fill=color, width=w)
            if b < BARS:
                self.canvas.create_text(x + BAR_W/2, top + STAFF_HEIGHT + 14, text=str(b+1), fill=SUBTLE, font=("Helvetica", 9))
            for beat in range(BEATS_PER_BAR):
                bx = MARGIN_X + b*BAR_W + (beat+0.5)*(BAR_W/BEATS_PER_BAR)
                self.canvas.create_line(bx, top + STAFF_HEIGHT + 2, bx, top + STAFF_HEIGHT + 8, fill=SUBTLE)

        # Clef
        self._draw_clef()

        # Repaint existing symbols (preserve dict, redraw)
        old = self.symbols.copy()
        self.symbols.clear()
        for key, meta in old.items():
            b, bt, lane = key
            self._draw_symbol_at(b, bt, lane, meta["kind"])

        # Metronome line
        self._draw_metro_line()

    def _draw_clef(self):
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
        except Exception:
            self.canvas.create_rectangle(x-16, y_mid-16, x+16, y_mid+16, outline=ACCENT, width=2)
            self.canvas.create_text(x, y_mid, text=lbl[:1], fill=ACCENT, font=("Helvetica", 14, "bold"))
        self.canvas.create_text(x, top + STAFF_HEIGHT + 34, text=lbl, fill=ACCENT, font=("Helvetica", 9, "bold"))

    # ---------- Placement ----------
    def _set_tool(self, k):
        self.current_tool.set(k)
        self.status_var.set(f"Tool: {k}")

    def on_click_place(self, event):
        b, bt = self._hit_bar_and_beat(event.x)
        if b is None:
            return
        lane = self._nearest_lane(event.y)
        kind = self.current_tool.get()
        if kind == "erase":
            self._erase_at(b, bt, lane)
        else:
            self._place_at(b, bt, lane, kind)

    def on_right_click_erase(self, event):
        b, bt = self._hit_bar_and_beat(event.x)
        if b is None:
            return
        lane = self._nearest_lane(event.y)
        self._erase_at(b, bt, lane)

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
        return bar, min(max(0, beat), BEATS_PER_BAR-1)

    def _nearest_lane(self, y_canvas):
        y = self.canvas.canvasy(y_canvas)
        best = 0
        best_d = 1e9
        for i, ly in enumerate(self.lane_ys):
            d = abs(y - ly)
            if d < best_d:
                best_d = d
                best = i
        return best

    def _erase_at(self, b, bt, lane):
        key = (b, bt, lane)
        if key in self.symbols:
            meta = self.symbols[key]
            try:
                if isinstance(meta["id"], str):  # tag group
                    self.canvas.delete(meta["id"])
                else:
                    self.canvas.delete(meta["id"])
            except Exception:
                pass
            del self.symbols[key]

    def _place_at(self, b, bt, lane, kind):
        self._erase_at(b, bt, lane)
        self._draw_symbol_at(b, bt, lane, kind)

    def _slot_center(self, b, bt, lane):
        x = MARGIN_X + b*BAR_W + (bt + 0.5)*(BAR_W/BEATS_PER_BAR)
        y = self.lane_ys[lane]
        return x, y

    def _draw_symbol_at(self, b, bt, lane, kind):
        x, y = self._slot_center(b, bt, lane)
        col = NOTE_COLORS.get(kind, INK)
        size = 9
        if kind == "full":
            item = self.canvas.create_oval(x-size, y-size, x+size, y+size, fill=col, outline="")
        elif kind == "half":
            item = self.canvas.create_oval(x-size, y-size, x+size, y+size, outline=col, width=2)
        elif kind == "combo":
            r = 5
            i1 = self.canvas.create_oval(x-r-4, y-r, x-r+4, y+r, fill=col, outline="")
            i2 = self.canvas.create_oval(x+r-4, y-r, x+r+4, y+r, fill=col, outline="")
            tag = f"sym_{b}_{bt}_{lane}"
            for it in (i1, i2):
                self.canvas.addtag_withtag(tag, it)
            self.symbols[(b, bt, lane)] = {"id": tag, "kind": kind}
            return
        elif kind == "rest":
            w, h = 14, 5
            rect = self.canvas.create_rectangle(x-w/2, y-h/2, x+w/2, y+h/2, fill=col, outline="")
            notch = self.canvas.create_line(x-w/2, y-h/2, x+w/2, y+h/2, fill=BG, width=2)
            tag = f"sym_{b}_{bt}_{lane}"
            for it in (rect, notch):
                self.canvas.addtag_withtag(tag, it)
            self.symbols[(b, bt, lane)] = {"id": tag, "kind": kind}
            return
        else:
            return
        self.symbols[(b, bt, lane)] = {"id": item, "kind": kind}

    # ---------- Timeline & Playback ----------
    def total_beats(self):
        return BARS * BEATS_PER_BAR

    def _update_bpm_label(self):
        self.bpm_label.config(text=str(self.BPM.get()))

    def _on_scrub_change(self, value):
        try:
            pos = int(float(value))
        except Exception:
            pos = 0
        self.current_pos = max(0, min(self.total_beats()-1, pos))
        self._draw_metro_line()
        self._update_pos_label()

    def _apply_scrub(self):
        # Already applied by scale; keep method for the "Go" button
        self._draw_metro_line()

    def play_pause(self):
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play(self):
        self.is_playing = True
        self.play_btn.config(text="❚❚ Pause")
        self._tick()

    def pause(self):
        self.is_playing = False
        self.play_btn.config(text="▶ Play")
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None

    def stop(self):
        self.pause()
        self.current_pos = 0
        self.scrub.set(self.current_pos)
        self._draw_metro_line()
        self._update_pos_label()

    def _tick(self):
        if not self.is_playing:
            return
        # Play any symbols at current_pos
        self._play_symbols_at(self.current_pos)

        # Advance to next beat
        self.current_pos = (self.current_pos + 1) % self.total_beats()
        self.scrub.set(self.current_pos)
        self._draw_metro_line()
        self._update_pos_label()

        # Schedule next tick based on BPM
        bpm = max(40, min(208, self.BPM.get()))
        interval_ms = int(60000 / bpm)
        self.after_id = self.after(interval_ms, self._tick)

    def _draw_metro_line(self):
        if self.metro_line is not None:
            try:
                self.canvas.delete(self.metro_line)
            except Exception:
                pass
        y0 = MARGIN_Y - 10
        y1 = MARGIN_Y + STAFF_HEIGHT + 10
        b = self.current_pos // BEATS_PER_BAR
        bt = self.current_pos % BEATS_PER_BAR
        x = MARGIN_X + b*BAR_W + (bt + 0.5)*(BAR_W/BEATS_PER_BAR)
        self.metro_line = self.canvas.create_line(x, y0, x, y1, fill=ACCENT, width=2, dash=(3,3))

    def _update_pos_label(self):
        self.pos_label.config(text=f"Beat {self.current_pos+1} / {self.total_beats()}")

    # ---------- Audio triggering ----------
    def _play_symbols_at(self, pos):
        b = pos // BEATS_PER_BAR
        bt = pos % BEATS_PER_BAR
        # collect all lanes at this bar+beat
        events = []
        for lane in range(LANES):
            key = (b, bt, lane)
            if key in self.symbols:
                kind = self.symbols[key]["kind"]
                if kind == "rest":
                    continue
                freq = lane_to_hz(lane, self.lane_notes)
                if kind == "full":
                    dur_beats = 1.0
                    events.append((freq, dur_beats))
                elif kind == "half":
                    dur_beats = 0.5
                    events.append((freq, dur_beats))
                elif kind == "combo":
                    # two quick strikes, each 0.5 beat
                    events.append((freq, 0.5))
                    # and schedule another very short delayed strike
                    self.after(self._ms_per_beat()//2, lambda f=freq: self._play_note(f, 0.5))
        # Play gathered notes
        for freq, dur_beats in events:
            self._play_note(freq, dur_beats)

        # optional click (downbeat accent)
        if winsound:
            try:
                if bt == 0:
                    winsound.Beep(880, 40)
                else:
                    winsound.Beep(660, 25)
            except Exception:
                pass

    def _ms_per_beat(self):
        bpm = max(40, min(208, self.BPM.get()))
        return int(60000 / bpm)

    def _play_note(self, freq_hz, dur_beats):
        secs = max(0.05, dur_beats * (60.0 / max(40, min(208, self.BPM.get()))))
        if self.record_sample_bytes:
            # pitch-shift naive: resample by ratio (affects duration). Keep simple & fast.
            base_freq = 440.0  # assume recording "reference" ~A4; scale by ratio
            ratio = freq_hz / base_freq
            wav = naive_resample_wav(self.record_sample_bytes, ratio)
        else:
            wav = synth_wave(self.waveform.get(), freq_hz, secs, amp=0.28)
        play_wav_bytes(wav)

    # ---------- Sample Management ----------
    def _test_tone(self):
        f = lane_to_hz(4, self.lane_notes)  # mid
        wav = synth_wave(self.waveform.get(), f, 0.4, amp=0.3)
        play_wav_bytes(wav)

    def _record_sample(self):
        if not HAVE_SD:
            messagebox.showwarning("Recording", "Mic recording requires the 'sounddevice' package.")
            return
        secs = float(self.record_secs.get())
        try:
            fs = self.record_sr
            messagebox.showinfo("Recording", "Recording will start now. Speak/sing/play...")
            data = sd.rec(int(secs*fs), samplerate=fs, channels=1, dtype='int16')
            sd.wait()
            pcm = data.tobytes()
            self.record_sample_bytes = pcm16_to_wav(pcm, fs, channels=1)
            messagebox.showinfo("Recording", "Sample captured! The metronome will now use your recording (pitch-shifted).")
        except Exception as e:
            messagebox.showerror("Recording failed", str(e))

    def _play_recording(self):
        if not self.record_sample_bytes:
            messagebox.showinfo("Recording", "No recording yet.")
            return
        play_wav_bytes(self.record_sample_bytes)

    def _apply_pitch_map(self):
        new_map = []
        for e in self.pitch_entries:
            s = e.get().strip()
            if not s:
                s = "A4"
            new_map.append(s)
        if len(new_map) == LANES:
            self.lane_notes = new_map
            self.status_var.set("Updated lane→pitch map.")

    # ---------- Help ----------
    def _show_help(self):
        tip = (
            "Quick guide:\n"
            "• 42 bars × 4 beats; 4 lines + 4 gaps = 8 lanes (pitch lanes low→high).\n"
            "• Tools: Full(●) = 1 beat, Half(○) = 1/2 beat, Combo(◍) = 2×1/2 within the beat, Rest(⟂).\n"
            "• Left-click to place on the nearest lane at that bar/beat; Right-click to erase.\n"
            "• Timeline: Play/Pause/Stop and scrub to any beat.\n"
            "• Sample Engine: choose sine/square/saw (or record mic if available). Lane decides pitch.\n"
            "  Edit the Lane→Pitch row to set note names (e.g., G3, G#3, A3, ...).\n"
            "• Recording is optional and depends on 'sounddevice'. Without it, the synth is used.\n"
            "\n"
            "Note: Playback uses simple built-in methods; on some systems a system player (afplay/aplay/ffplay) may be used.\n"
        )
        messagebox.showinfo("Help", tip)

# --------- Simple resampler for recorded wav (very naive) ---------
def read_wav_params(wav_bytes):
    # Minimal parser assuming PCM16 mono
    f = io.BytesIO(wav_bytes)
    if f.read(4) != b"RIFF":
        return None
    f.read(4)  # size
    if f.read(4) != b"WAVE":
        return None
    sr = 44100
    channels = 1
    bits = 16
    data = None
    # parse chunks
    while True:
        hdr = f.read(4)
        if not hdr:
            break
        size_bytes = f.read(4)
        if len(size_bytes) < 4:
            break
        size = struct.unpack("<I", size_bytes)[0]
        if hdr == b"fmt ":
            fmt = f.read(size)
            (audio_fmt, channels, sr, br, ba, bits) = struct.unpack("<HHIIHH", fmt[:16])
        elif hdr == b"data":
            data = f.read(size)
        else:
            f.seek(size, 1)
    return {"sr": sr, "channels": channels, "bits": bits, "data": data}

def naive_resample_wav(wav_bytes, ratio):
    p = read_wav_params(wav_bytes)
    if not p or not p["data"]:
        return wav_bytes
    data = p["data"]
    sr = p["sr"]
    # Unpack int16 mono
    n = len(data)//2
    ints = struct.unpack("<%dh" % n, data)
    # Resample by skipping/duplicating (nearest neighbor)
    out = []
    i = 0.0
    step = 1.0/ratio if ratio > 0 else 1.0
    while int(i) < n:
        out.append(ints[int(i)])
        i += step
    # Pack back
    out_bytes = struct.pack("<%dh" % len(out), *out)
    return pcm16_to_wav(out_bytes, sr, channels=1)

if __name__ == "__main__":
    app = Sheet42()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
