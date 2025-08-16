#!/usr/bin/env python3
# Four-Line Sheet (42 Bars) — minimal, single-file Tk app
# Made with ♥ by GPT-5 Thinking & You

import tkinter as tk
from tkinter import ttk, font, messagebox
import sys
import math
import time

APP_TITLE = "Four-Line Sheet — 42 Bars"
BARS = 42
BEATS_PER_BAR = 4
STAFF_LINES = 4
BAR_W = 80
MARGIN_X = 60
MARGIN_Y = 30
LINE_SPACING = 22  # distance between the 4 staff lines
STAFF_HEIGHT = (STAFF_LINES - 1) * LINE_SPACING
CANVAS_H = MARGIN_Y*2 + STAFF_HEIGHT + 80  # extra for clef and footer
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

# Try importing winsound for a soft 'tick' (Windows). Otherwise visual-only metronome.
try:
    import winsound
except Exception:
    winsound = None


class Sheet42(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.geometry("1100x420")
        self.minsize(900, 380)

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

        # Map (bar, beat, line_index) -> canvas item id + kind
        self.symbols = {}  # (b, bt, ln) : {"id": int, "kind": str}

        self._build_ui()
        self._draw_sheet()

    # ---------- UI ----------
    def _build_ui(self):
        self._build_header()
        self._build_toolbar()
        self._build_canvas()
        self._build_footer()

    def _build_header(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=12, pady=(10, 0))

        title_font = font.Font(family="Georgia", size=20, weight="bold")
        title = tk.Label(header, text="Four-Line Sheet (42 Bars)", bg=BG, fg=INK, font=title_font)
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

        # Right side: name editor
        name_box = tk.Frame(header, bg=BG)
        name_box.pack(side="right")
        tk.Label(name_box, text="Your name:", bg=BG, fg=SUBTLE).pack(side="left", padx=(0,6))
        tk.Entry(name_box, textvariable=self.user_name, width=16).pack(side="left")

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=12, pady=10)

        # Clef chooser (two options; user can rename/replace glyphs)
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

        self._mk_tool_button(tools, "Full beat ●", "full").pack(side="left", padx=4)
        self._mk_tool_button(tools, "Half beat ○", "half").pack(side="left", padx=4)
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

        # Help
        help_box = tk.Frame(bar, bg=BG)
        help_box.pack(side="right")
        ttk.Button(help_box, text="Help", command=self._show_help).pack(side="right")

    def _mk_tool_button(self, parent, label, kind):
        def set_tool():
            self.current_tool.set(kind)
            # Subtle visual cue by updating title
            self.status_var.set(f"Tool: {label}")
        btn = ttk.Button(parent, text=label, command=set_tool)
        return btn

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

        # Bindings
        self.canvas.bind("<Button-1>", self.on_click_place)
        self.canvas.bind("<Button-3>", self.on_right_click_erase)
        self.canvas.bind("<Configure>", lambda e: self._draw_sheet())

        # moving highlight for metronome
        self.metro_line = None

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

        # Bars
        for b in range(BARS + 1):
            x = MARGIN_X + b*BAR_W
            w = 1.2 if b % 4 else 2.2  # heavier every 4 bars
            color = INK if b % 4 == 0 else SUBTLE
            self.canvas.create_line(x, top, x, top + STAFF_HEIGHT, fill=color, width=w)

            # subtle bar numbers at bottom
            if b < BARS:
                self.canvas.create_text(x + BAR_W/2, top + STAFF_HEIGHT + 14, text=str(b+1), fill=SUBTLE, font=("Helvetica", 9))

            # also tick marks for beats
            for beat in range(BEATS_PER_BAR):
                bx = MARGIN_X + b*BAR_W + (beat+0.5)*(BAR_W/BEATS_PER_BAR)
                self.canvas.create_line(bx, top + STAFF_HEIGHT + 2, bx, top + STAFF_HEIGHT + 8, fill=SUBTLE)

        # Clef
        self._draw_clef()

        # Re-draw any placed symbols
        old = self.symbols.copy()
        self.symbols.clear()
        for (b, bt, ln), meta in old.items():
            self._draw_symbol_at(b, bt, ln, meta["kind"])

        # Metronome line (re-create)
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
            # If glyph unsupported, draw label box
            self.canvas.create_rectangle(x-16, y_mid-16, x+16, y_mid+16, outline=ACCENT, width=2)
            self.canvas.create_text(x, y_mid, text=lbl[:1], fill=ACCENT, font=("Helvetica", 14, "bold"))
        # Label under clef
        self.canvas.create_text(x, top + STAFF_HEIGHT + 34, text=lbl, fill=ACCENT, font=("Helvetica", 9, "bold"))

    def _redraw_clef(self):
        self._draw_sheet()

    # ---------- Placement ----------
    def on_click_place(self, event):
        # Translate click -> (bar, beat, line)
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
        # account for canvas xview
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
        # Remove existing at this slot, then draw
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
            # filled oval
            item = self.canvas.create_oval(x-size, y-size, x+size, y+size, fill=col, outline="")
        elif kind == "half":
            # outlined oval
            item = self.canvas.create_oval(x-size, y-size, x+size, y+size, outline=col, width=2)
        elif kind == "combo":
            # two small dots side-by-side
            r = 6
            item1 = self.canvas.create_oval(x-r-4, y-r, x-r+4, y+r, fill=col, outline="")
            item2 = self.canvas.create_oval(x+r-4, y-r, x+r+4, y+r, fill=col, outline="")
            item = (item1, item2)
        elif kind == "rest":
            # small rectangle + notch
            w, h = 16, 6
            rect = self.canvas.create_rectangle(x-w/2, y-h/2, x+w/2, y+h/2, fill=col, outline="")
            notch = self.canvas.create_line(x-w/2, y-h/2, x+w/2, y+h/2, fill=BG, width=2)
            item = (rect, notch)
        else:
            return

        # store
        if isinstance(item, tuple):
            # group via a hidden tag
            tag = f"sym_{b}_{bt}_{ln}"
            for it in item:
                self.canvas.addtag_withtag(tag, it)
            group_id = self.canvas.create_rectangle(0,0,0,0, outline="", fill="")  # dummy
            self.canvas.addtag_withtag(tag, group_id)
            self.symbols[(b, bt, ln)] = {"id": tag, "kind": kind}
        else:
            self.symbols[(b, bt, ln)] = {"id": item, "kind": kind}

    # ---------- Metronome ----------
    def _draw_metronome_line(self):
        # Delete and recreate at current position
        if self.metro_line is not None:
            try:
                self.canvas.delete(self.metro_line)
            except:
                pass
        y0 = MARGIN_Y - 10
        y1 = MARGIN_Y + STAFF_HEIGHT + 10
        # compute x from metronome_pos
        pos = self.metronome_pos if self.metronome_pos >= 0 else 0
        b = pos // BEATS_PER_BAR
        bt = pos % BEATS_PER_BAR
        x = MARGIN_X + b*BAR_W + (bt + 0.5)*(BAR_W/BEATS_PER_BAR)
        self.metro_line = self.canvas.create_line(x, y0, x, y1, fill=ACCENT, width=2, dash=(3,3))

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

    def _tick_metronome(self):
        if not self.metronome_running:
            return
        # advance
        total_beats = BARS * BEATS_PER_BAR
        self.metronome_pos = (self.metronome_pos + 1) % total_beats
        self._draw_metronome_line()

        # optional click
        if winsound:
            try:
                # downbeat brighter
                if self.metronome_pos % BEATS_PER_BAR == 0:
                    winsound.Beep(880, 60)  # A5 short
                else:
                    winsound.Beep(660, 40)
            except Exception:
                pass  # ignore if beeps fail

        # subtle flash: briefly draw a circle at current beat slot
        b = self.metronome_pos // BEATS_PER_BAR
        bt = self.metronome_pos % BEATS_PER_BAR
        x, y = self._slot_center(b, bt, STAFF_LINES//2)
        flash = self.canvas.create_oval(x-6, y-6, x+6, y+6, outline=ACCENT, width=2)
        self.after(80, lambda: self.canvas.delete(flash))

        # schedule next tick based on BPM (beats = quarter note)
        bpm = max(40, min(208, self.BPM.get()))
        interval_ms = int(60000 / bpm)
        self.metronome_after = self.after(interval_ms, self._tick_metronome)

    # ---------- Misc ----------
    def _show_help(self):
        tip = (
            "Quick guide:\n"
            "• Canvas shows a 4-line staff with 42 bars. Each bar has 4 beats.\n"
            "• Choose a tool, then left-click a beat position to place it on the nearest line.\n"
            "• Right-click a spot to erase at that beat+line.\n"
            "• Use the Clef box to pick between two clefs you can customize (text/glyph + label).\n"
            "• Metronome highlights each beat at the chosen BPM; it also beeps on Windows.\n"
            "\n"
            "This is a visual placeholder — symbols stand in for sounds you may choose elsewhere.\n"
        )
        messagebox.showinfo("Help", tip)


if __name__ == "__main__":
    app = Sheet42()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
