#!/usr/bin/env python3
"""
FlowCast Studio — gui.py
=========================
Premium GUI for the FlowCast documentation-to-recording pipeline.

Workflow
────────
1. Paste MDX documentation into the left panel.
2. The right panel auto-previews extracted steps and instructions.
3. Select theme (Light / Dark) and optionally a single step to record.
4. Click "Record Workflow" — FlowCast runs in a subprocess; its output
   streams live into the Log panel.
5. When complete, GIFs and videos appear in output/recordings/<slug>/.

Architecture
────────────
FlowcastStudioApp (CTk window)
├── HeaderBar              app branding + global controls
├── BodyFrame (grid)
│   ├── LeftPanel          MDX input textarea + action buttons
│   └── RightPanel (grid)
│       ├── PreviewFrame   extracted-step cards (scrollable)
│       └── LogFrame       live recording log (read-only textbox)
└── FooterBar              theme selector · step picker · record button
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

# ── Resolve project root so relative imports work whether run directly
#    or from any working directory ────────────────────────────────────
_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(_ROOT))

from src.mdx_parser import extract_step_summary, preprocess_mdx, preprocess_to_temp

# ── Palette (Obsidian/Slate — matches TraceFlow) ─────────────────────
_BG            = "#0D1117"
_SURFACE       = "#161B22"
_ELEVATED      = "#1C2128"
_BORDER        = "#21262D"
_BORDER_BRIGHT = "#30363D"
_ACCENT        = "#4D9DE0"
_ACCENT_HOV    = "#79B8FF"
_ACCENT_DIM    = "#162033"
_TEXT_PRI      = "#F0F6FC"
_TEXT_SEC      = "#8B949E"
_TEXT_DIM      = "#484F58"
_SUCCESS       = "#3FB950"
_ERROR_RED     = "#F85149"
_WARN          = "#D29922"
_BTN_SEC       = "#1C2128"
_BTN_SEC_HOV   = "#2D333B"

_PYTHON = str(_ROOT / ".venv" / "bin" / "python3")
_MAIN   = str(_ROOT / "main.py")


# ═══════════════════════════════════════════════════════════════════════
#  StepCard — one step in the preview panel
# ═══════════════════════════════════════════════════════════════════════

class StepCard(ctk.CTkFrame):
    """Compact collapsible card showing a step title and its instructions."""

    def __init__(self, master, *, number: int, title: str, items: list[str], **kw):
        kw.setdefault("corner_radius", 8)
        kw.setdefault("fg_color", _ELEVATED)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", _BORDER)
        super().__init__(master, **kw)

        self._expanded = True

        # ── Header row ────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        hdr.pack(fill="x", padx=10, pady=(8, 2))

        ctk.CTkLabel(
            hdr,
            text=f"Step {number}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=_ACCENT,
            width=44,
            anchor="w",
        ).pack(side="left")

        self._title_lbl = ctk.CTkLabel(
            hdr,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=_TEXT_PRI,
            anchor="w",
            wraplength=240,
            justify="left",
        )
        self._title_lbl.pack(side="left", fill="x", expand=True)

        self._toggle_btn = ctk.CTkButton(
            hdr,
            text="▾",
            width=22, height=22,
            corner_radius=4,
            fg_color="transparent",
            hover_color=_BORDER,
            text_color=_TEXT_DIM,
            font=ctk.CTkFont(size=11),
            command=self._toggle,
            cursor="hand2",
        )
        self._toggle_btn.pack(side="right")

        # ── Items ─────────────────────────────────────────────────
        self._items_frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self._items_frame.pack(fill="x", padx=10, pady=(0, 8))

        for item in items:
            row = ctk.CTkFrame(self._items_frame, fg_color="transparent", corner_radius=0)
            row.pack(fill="x", pady=1)

            ctk.CTkLabel(
                row,
                text="○",
                font=ctk.CTkFont(size=11),
                text_color=_TEXT_DIM,
                width=16,
            ).pack(side="left")

            ctk.CTkLabel(
                row,
                text=item,
                font=ctk.CTkFont(size=11),
                text_color=_TEXT_SEC,
                anchor="w",
                justify="left",
                wraplength=274,
            ).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._items_frame.pack(fill="x", padx=10, pady=(0, 8))
            self._toggle_btn.configure(text="▾")
        else:
            self._items_frame.pack_forget()
            self._toggle_btn.configure(text="▸")


# ═══════════════════════════════════════════════════════════════════════
#  FlowcastStudioApp — main window
# ═══════════════════════════════════════════════════════════════════════

class FlowcastStudioApp(ctk.CTk):
    """FlowCast Studio — MDX input → step preview → GIF recording."""

    _W = 1020
    _H = 700

    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ── State ──────────────────────────────────────────────────
        self._process:          subprocess.Popen | None = None
        self._tmp_file:         Path | None             = None
        self._recording_active: bool                    = False
        self._step_options:     list[str]               = ["All Steps"]
        self._preview_after_id: str | None              = None
        # Resume state — populated when the user manually stops a recording
        self._stopped_by_user:  bool                    = False
        self._last_step_num:    int                     = 1   # step being recorded when stopped

        # ── Window ─────────────────────────────────────────────────
        self.title("FlowCast Studio")
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - self._W) // 2
        y  = (sh - self._H) // 2
        self.geometry(f"{self._W}x{self._H}+{x}+{y}")
        self.resizable(True, True)
        self.minsize(780, 520)
        self.configure(fg_color=_BG)

        self._build_ui()

        # Paste sample hint
        self._set_placeholder()

    # ══════════════════════════════════════════════════════════════
    #  UI construction
    # ══════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        """Construct the full widget hierarchy."""
        # Main grid: header | body | footer
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_body()
        self._build_footer()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color=_SURFACE,
                           border_width=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)

        # Logo text
        ctk.CTkLabel(
            bar,
            text="⬡  FlowCast Studio",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=_TEXT_PRI,
        ).pack(side="left", padx=20)

        ctk.CTkLabel(
            bar,
            text="MDX Documentation → Screen Recording",
            font=ctk.CTkFont(size=12),
            text_color=_TEXT_DIM,
        ).pack(side="left", padx=(0, 20))

        # Right-side: output-dir picker
        ctk.CTkLabel(
            bar, text="Output:",
            font=ctk.CTkFont(size=11),
            text_color=_TEXT_SEC,
        ).pack(side="right", padx=(0, 4))

        self._output_entry = ctk.CTkEntry(
            bar,
            placeholder_text="output/recordings/",
            width=200, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=_ELEVATED,
            border_color=_BORDER,
            text_color=_TEXT_PRI,
        )
        self._output_entry.pack(side="right", padx=(0, 4))

        ctk.CTkButton(
            bar,
            text="⌂",
            width=28, height=28,
            corner_radius=6,
            fg_color=_BTN_SEC,
            hover_color=_BTN_SEC_HOV,
            text_color=_TEXT_SEC,
            command=self._browse_output_dir,
            cursor="hand2",
        ).pack(side="right", padx=(0, 16))

    # ── Body ──────────────────────────────────────────────────────────────────

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, corner_radius=0, fg_color=_BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=0)  # fixed-width divider
        body.grid_columnconfigure(2, weight=2)

        self._build_input_panel(body)
        # Vertical divider
        ctk.CTkFrame(body, width=1, corner_radius=0, fg_color=_BORDER).grid(
            row=0, column=1, sticky="ns", pady=8
        )
        self._build_right_panel(body)

    def _build_input_panel(self, parent) -> None:
        """Left: MDX textarea + action buttons."""
        panel = ctk.CTkFrame(parent, corner_radius=0, fg_color=_BG)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # Label row
        lbl_row = ctk.CTkFrame(panel, fg_color="transparent", corner_radius=0)
        lbl_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            lbl_row,
            text="PASTE MDX DOCUMENTATION",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=_TEXT_DIM,
            anchor="w",
        ).pack(side="left")

        # Small action buttons
        for label, cmd, tip in [
            ("Clear",  self._clear_input,   "Clear input"),
            ("Copy cleaned MD", self._copy_cleaned, "Copy preprocessed markdown"),
        ]:
            ctk.CTkButton(
                lbl_row,
                text=label,
                font=ctk.CTkFont(size=11),
                width=106, height=22,
                corner_radius=5,
                fg_color=_BTN_SEC,
                hover_color=_BTN_SEC_HOV,
                text_color=_TEXT_SEC,
                command=cmd,
                cursor="hand2",
            ).pack(side="right", padx=(4, 0))

        # MDX textarea
        self._input_box = ctk.CTkTextbox(
            panel,
            font=ctk.CTkFont(family="Menlo" if sys.platform == "darwin" else "Consolas",
                              size=12),
            fg_color=_SURFACE,
            border_color=_BORDER,
            border_width=1,
            corner_radius=8,
            text_color=_TEXT_PRI,
            scrollbar_button_color=_BORDER,
            scrollbar_button_hover_color=_BORDER_BRIGHT,
            wrap="none",
        )
        self._input_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        # Live-preview trigger
        self._input_box.bind("<KeyRelease>", self._schedule_preview)
        self._input_box.bind("<<Paste>>",    self._on_paste)

    def _build_right_panel(self, parent) -> None:
        """Right: collapsible step preview (top) + scrolling log (bottom)."""
        panel = ctk.CTkFrame(parent, corner_radius=0, fg_color=_BG)
        panel.grid(row=0, column=2, sticky="nsew")
        panel.grid_rowconfigure(0, weight=3)
        panel.grid_rowconfigure(1, weight=0)  # separator
        panel.grid_rowconfigure(2, weight=2)
        panel.grid_columnconfigure(0, weight=1)

        self._build_preview_frame(panel)

        ctk.CTkFrame(panel, height=1, corner_radius=0, fg_color=_BORDER).grid(
            row=1, column=0, sticky="ew", padx=8
        )

        self._build_log_frame(panel)

    def _build_preview_frame(self, parent) -> None:
        """Extracted-step cards, scrollable."""
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color=_BG)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Label row
        lbl_row = ctk.CTkFrame(frame, fg_color="transparent", corner_radius=0)
        lbl_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            lbl_row,
            text="EXTRACTED STEPS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=_TEXT_DIM,
            anchor="w",
        ).pack(side="left")

        self._step_count_lbl = ctk.CTkLabel(
            lbl_row,
            text="",
            font=ctk.CTkFont(size=10),
            text_color=_ACCENT,
            anchor="e",
        )
        self._step_count_lbl.pack(side="right")

        self._preview_scroll = ctk.CTkScrollableFrame(
            frame,
            corner_radius=8,
            fg_color=_SURFACE,
            border_width=1,
            border_color=_BORDER,
            scrollbar_button_color=_BORDER,
            scrollbar_button_hover_color=_BORDER_BRIGHT,
        )
        self._preview_scroll.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))

        # Placeholder label
        self._preview_placeholder = ctk.CTkLabel(
            self._preview_scroll,
            text="Paste MDX above to\npreview extracted steps.",
            font=ctk.CTkFont(size=12),
            text_color=_TEXT_DIM,
            justify="center",
        )
        self._preview_placeholder.pack(expand=True, pady=32)

    def _build_log_frame(self, parent) -> None:
        """Live recording log (read-only textbox)."""
        frame = ctk.CTkFrame(parent, corner_radius=0, fg_color=_BG)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Label row
        lbl_row = ctk.CTkFrame(frame, fg_color="transparent", corner_radius=0)
        lbl_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 4))

        ctk.CTkLabel(
            lbl_row,
            text="LOG",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=_TEXT_DIM,
            anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            lbl_row,
            text="Clear",
            font=ctk.CTkFont(size=10),
            width=40, height=18,
            corner_radius=4,
            fg_color="transparent",
            hover_color=_BTN_SEC,
            text_color=_TEXT_DIM,
            command=self._clear_log,
            cursor="hand2",
        ).pack(side="right")

        self._log_box = ctk.CTkTextbox(
            frame,
            font=ctk.CTkFont(
                family="Menlo" if sys.platform == "darwin" else "Consolas",
                size=11,
            ),
            fg_color=_SURFACE,
            border_color=_BORDER,
            border_width=1,
            corner_radius=8,
            text_color=_TEXT_SEC,
            state="disabled",
            scrollbar_button_color=_BORDER,
            scrollbar_button_hover_color=_BORDER_BRIGHT,
        )
        self._log_box.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

    # ── Footer ────────────────────────────────────────────────────────────────

    def _build_footer(self) -> None:
        bar = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color=_SURFACE,
                           border_width=0)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(3, weight=1)

        # Theme segmented button
        ctk.CTkLabel(
            bar, text="Theme",
            font=ctk.CTkFont(size=11),
            text_color=_TEXT_SEC,
        ).grid(row=0, column=0, padx=(16, 4), pady=18)

        self._theme_seg = ctk.CTkSegmentedButton(
            bar,
            values=["Light", "Dark"],
            font=ctk.CTkFont(size=12),
            height=30,
            selected_color=_ACCENT,
            selected_hover_color=_ACCENT_HOV,
            unselected_color=_BTN_SEC,
            unselected_hover_color=_BTN_SEC_HOV,
            fg_color=_ELEVATED,
            text_color=_TEXT_PRI,
            command=self._on_theme_change,
        )
        self._theme_seg.set("Light")
        self._theme_seg.grid(row=0, column=1, padx=(0, 16), pady=18)

        # Separator
        ctk.CTkFrame(bar, width=1, height=30, fg_color=_BORDER).grid(
            row=0, column=2, pady=14
        )

        # Step picker label
        ctk.CTkLabel(
            bar, text="Record",
            font=ctk.CTkFont(size=11),
            text_color=_TEXT_SEC,
        ).grid(row=0, column=4, padx=(16, 4), pady=18)

        self._step_menu = ctk.CTkOptionMenu(
            bar,
            values=["All Steps"],
            font=ctk.CTkFont(size=12),
            width=140, height=30,
            fg_color=_ELEVATED,
            button_color=_BORDER,
            button_hover_color=_BORDER_BRIGHT,
            text_color=_TEXT_PRI,
            dropdown_fg_color=_ELEVATED,
            dropdown_text_color=_TEXT_PRI,
            dropdown_hover_color=_BORDER_BRIGHT,
        )
        self._step_menu.grid(row=0, column=5, padx=(0, 16), pady=18)

        # ── Button area — swaps between "Record" and "Restart + Continue" ──
        self._btn_area = ctk.CTkFrame(bar, fg_color="transparent", corner_radius=0)
        self._btn_area.grid(row=0, column=6, padx=(0, 16), pady=11)

        # Record / Stop button (visible by default)
        self._record_btn = ctk.CTkButton(
            self._btn_area,
            text="  🎬  Record Workflow  ",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            corner_radius=10,
            fg_color=_ACCENT,
            hover_color=_ACCENT_HOV,
            text_color="#FFFFFF",
            command=self._on_record_click,
            cursor="hand2",
        )
        self._record_btn.pack(side="left")

        # Restart button (hidden until recording is stopped by user)
        self._restart_btn = ctk.CTkButton(
            self._btn_area,
            text="↩  Restart",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            width=130,
            corner_radius=10,
            fg_color=_BTN_SEC,
            hover_color=_BTN_SEC_HOV,
            text_color=_TEXT_PRI,
            command=self._on_restart_click,
            cursor="hand2",
        )

        # Continue button (hidden until recording is stopped by user)
        self._continue_btn = ctk.CTkButton(
            self._btn_area,
            text="▶  Continue",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            width=180,
            corner_radius=10,
            fg_color=_SUCCESS,
            hover_color="#2da142",
            text_color="#FFFFFF",
            command=self._on_continue_click,
            cursor="hand2",
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  Live preview
    # ══════════════════════════════════════════════════════════════════════════

    def _schedule_preview(self, _e=None) -> None:
        """Debounce preview rebuild — fire 350 ms after last keystroke."""
        if self._preview_after_id:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(350, self._refresh_preview)

    def _on_paste(self, _e=None) -> None:
        """Immediate preview rebuild after a paste event."""
        self.after(50, self._refresh_preview)

    def _refresh_preview(self) -> None:
        """Rebuild the step-card preview from the current input content."""
        content = self._get_input()
        if not content or content == self._PLACEHOLDER:
            self._clear_preview_cards()
            return

        theme = "dark" if self._theme_seg.get() == "Dark" else "light"
        try:
            steps = extract_step_summary(content, theme)
        except Exception as exc:
            self._log(f"[preview error] {exc}")
            return

        self._clear_preview_cards()

        if not steps:
            self._preview_placeholder = ctk.CTkLabel(
                self._preview_scroll,
                text="No ## Step sections found.\nCheck the MDX format.",
                font=ctk.CTkFont(size=12),
                text_color=_WARN,
                justify="center",
            )
            self._preview_placeholder.pack(expand=True, pady=32)
            self._step_count_lbl.configure(text="0 steps")
            self._update_step_menu([])
            return

        # Update step menu
        self._step_count_lbl.configure(text=f"{len(steps)} step{'s' if len(steps)!=1 else ''} found")
        self._update_step_menu(steps)

        for i, step in enumerate(steps, 1):
            card = StepCard(
                self._preview_scroll,
                number=i,
                title=step["title"],
                items=step["items"],
            )
            card.pack(fill="x", padx=8, pady=(4, 0))

    def _clear_preview_cards(self) -> None:
        for w in self._preview_scroll.winfo_children():
            w.destroy()

    def _update_step_menu(self, steps: list[dict]) -> None:
        options = ["All Steps"] + [
            f"Step {i}: {s['title'][:28]}…" if len(s['title']) > 28
            else f"Step {i}: {s['title']}"
            for i, s in enumerate(steps, 1)
        ]
        self._step_menu.configure(values=options)
        self._step_menu.set("All Steps")

    # ══════════════════════════════════════════════════════════════════════════
    #  Recording
    # ══════════════════════════════════════════════════════════════════════════

    def _on_record_click(self) -> None:
        if self._recording_active:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        """Pre-process MDX, write a temp file, and launch FlowCast."""
        content = self._get_input()
        if not content or content == self._PLACEHOLDER:
            self._log("[studio] No MDX content — paste a workflow first.")
            return

        theme = "dark" if self._theme_seg.get() == "Dark" else "light"
        self._log(f"[studio] Pre-processing MDX (theme: {theme}) …")

        try:
            cleaned = preprocess_mdx(content, theme)
            self._log(
                f"[studio] Extracted {len(re.findall(chr(35)*2 + r' Step', cleaned))} steps."
            )
            self._log("[studio] Cleaned markdown:\n" + "─" * 40)
            for line in cleaned.splitlines()[:20]:
                self._log("  " + line)
            if cleaned.count("\n") > 20:
                self._log("  … (truncated)")
            self._log("─" * 40)
        except Exception as exc:
            self._log(f"[studio] Pre-processing failed: {exc}")
            return

        try:
            self._tmp_file = preprocess_to_temp(content, theme)
            self._log(f"[studio] Temp file: {self._tmp_file}")
        except Exception as exc:
            self._log(f"[studio] Could not write temp file: {exc}")
            return

        # Build subprocess command
        cmd = [_PYTHON, _MAIN, str(self._tmp_file)]

        step_choice = self._step_menu.get()
        if step_choice != "All Steps":
            m = re.search(r"Step\s+(\d+)", step_choice)
            if m:
                cmd += ["--step", m.group(1)]
                self._log(f"[studio] Recording step {m.group(1)} only.")

        # Override output dir if user set one
        out_text = self._output_entry.get().strip()
        # (FlowCast currently doesn't take --output flag, but the temp file
        #  is named after the slug derived from its stem. We leave this for now.)

        self._stopped_by_user = False
        self._last_step_num   = 1
        self._launch_subprocess(cmd)

    def _stream_output(self) -> None:
        """Background thread: relay subprocess stdout to the log panel.

        Also parses ``── Step N:`` markers so we always know which step
        was active if the user presses Stop.
        """
        assert self._process is not None
        _step_re = re.compile(r'── Step\s+(\d+)\s*:', re.IGNORECASE)
        for line in iter(self._process.stdout.readline, ""):
            m = _step_re.search(line)
            if m:
                self._last_step_num = int(m.group(1))
            self.after(0, lambda l=line: self._log(l.rstrip()))
        self._process.wait()
        self.after(0, self._on_recording_finished)

    def _stop_recording(self) -> None:
        if self._process:
            self._stopped_by_user = True   # distinguish user-stop from natural end
            self._process.terminate()
            self._log(f"[studio] Recording stopped by user at Step {self._last_step_num}.")

    def _on_recording_finished(self) -> None:
        rc = self._process.returncode if self._process else -1
        self._recording_active = False
        self._process = None

        if self._stopped_by_user:
            # Keep _tmp_file alive — Continue will reuse it.
            self._log(
                f"[studio] Stopped at Step {self._last_step_num}.  "
                f"Use Restart or Continue below."
            )
            self._show_resume_controls()
        else:
            # Natural completion or error — clean up and reset normally.
            self._delete_tmp()
            if rc == 0:
                self._log("[studio] ✓ Recording complete (exit 0).")
            else:
                self._log(f"[studio] ⚠ Process exited with code {rc}.")
            self._show_record_btn()

    # ── Resume-control helpers ────────────────────────────────────────────────

    def _show_resume_controls(self) -> None:
        """Swap the record button out for Restart + Continue buttons."""
        self._record_btn.pack_forget()
        self._continue_btn.configure(
            text=f"▶  Continue from Step {self._last_step_num}",
        )
        self._restart_btn.pack(side="left", padx=(0, 6))
        self._continue_btn.pack(side="left")

    def _hide_resume_controls(self) -> None:
        """Remove Restart + Continue and put the record button back."""
        self._restart_btn.pack_forget()
        self._continue_btn.pack_forget()
        self._show_record_btn()

    def _show_record_btn(self) -> None:
        """Ensure the main record button is visible and in its idle state."""
        self._record_btn.pack_forget()   # re-pack so it comes first
        self._record_btn.configure(
            text="  🎬  Record Workflow  ",
            fg_color=_ACCENT,
            hover_color=_ACCENT_HOV,
        )
        self._record_btn.pack(side="left")

    def _on_restart_click(self) -> None:
        """Discard current position and record from Step 1."""
        self._hide_resume_controls()
        self._stopped_by_user = False
        self._last_step_num   = 1
        self._delete_tmp()          # force fresh pre-process
        self._start_recording()

    def _on_continue_click(self) -> None:
        """Resume recording from the step that was active when Stop was pressed."""
        step_num = self._last_step_num
        self._hide_resume_controls()
        self._stopped_by_user = False

        if self._tmp_file is None or not self._tmp_file.exists():
            # Temp file was lost — fall back to a fresh run from that step
            self._log(f"[studio] Temp file gone, re-preprocessing for Step {step_num} …")
            self._start_recording_from(step_num)
            return

        # Build command with the preserved temp file + --from-step N
        cmd = [_PYTHON, _MAIN, str(self._tmp_file), "--from-step", str(step_num)]
        self._log(f"[studio] Continuing from Step {step_num} …")
        self._launch_subprocess(cmd)

    def _start_recording_from(self, from_step: int) -> None:
        """Pre-process MDX fresh and start recording from *from_step*."""
        content = self._get_input()
        if not content or content == self._PLACEHOLDER:
            self._log("[studio] No content to re-process.")
            return
        theme = "dark" if self._theme_seg.get() == "Dark" else "light"
        try:
            self._tmp_file = preprocess_to_temp(content, theme)
        except Exception as exc:
            self._log(f"[studio] Pre-process failed: {exc}")
            return
        cmd = [_PYTHON, _MAIN, str(self._tmp_file), "--from-step", str(from_step)]
        self._launch_subprocess(cmd)

    def _launch_subprocess(self, cmd: list[str]) -> None:
        """Spawn *cmd* as a FlowCast subprocess and start streaming its output."""
        self._log(f"[studio] Launching: {' '.join(Path(c).name for c in cmd[-4:])}")
        try:
            self._process = subprocess.Popen(
                cmd,
                cwd=str(_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except FileNotFoundError:
            self._log(f"[studio] Python not found: {_PYTHON}")
            return

        self._recording_active = True
        self._record_btn.pack_forget()
        self._record_btn.configure(
            text="  ⏹  Stop Recording  ",
            fg_color=_ERROR_RED,
            hover_color="#c0392b",
        )
        self._record_btn.pack(side="left")
        threading.Thread(target=self._stream_output, daemon=True).start()

    def _delete_tmp(self) -> None:
        """Delete the temporary workflow file if it still exists."""
        if self._tmp_file and self._tmp_file.exists():
            try:
                self._tmp_file.unlink()
            except OSError:
                pass
        self._tmp_file = None

    # ══════════════════════════════════════════════════════════════════════════
    #  Input helpers
    # ══════════════════════════════════════════════════════════════════════════

    _PLACEHOLDER = (
        "# Paste your MDX documentation here…\n\n"
        "Example:\n\n"
        "---\n"
        "title: 'Quick Start: Build an Automation'\n"
        "---\n\n"
        "## Step 1: Create the project\n\n"
        "1. Open WSO2 Integrator.\n"
        "2. Select **Create**.\n"
        "3. Set **Integration Name** to `Hello_World`.\n"
    )

    def _set_placeholder(self) -> None:
        self._input_box.insert("1.0", self._PLACEHOLDER)
        self._input_box.configure(text_color=_TEXT_DIM)

    def _get_input(self) -> str:
        return self._input_box.get("1.0", "end-1c")

    def _clear_input(self) -> None:
        self._input_box.delete("1.0", "end")
        self._input_box.configure(text_color=_TEXT_PRI)
        self._clear_preview_cards()
        self._step_count_lbl.configure(text="")
        self._update_step_menu([])

    def _copy_cleaned(self) -> None:
        content = self._get_input()
        if not content:
            return
        theme = "dark" if self._theme_seg.get() == "Dark" else "light"
        try:
            cleaned = preprocess_mdx(content, theme)
            self.clipboard_clear()
            self.clipboard_append(cleaned)
            self._log("[studio] Cleaned markdown copied to clipboard.")
        except Exception as exc:
            self._log(f"[studio] Copy failed: {exc}")

    # ── First-type: clear placeholder ────────────────────────────────────────

    def _ensure_real_text(self) -> None:
        """Remove the dimmed placeholder on first real keystroke."""
        if self._get_input() == self._PLACEHOLDER:
            self._input_box.delete("1.0", "end")
            self._input_box.configure(text_color=_TEXT_PRI)

    # ══════════════════════════════════════════════════════════════════════════
    #  Log helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _log(self, msg: str) -> None:
        """Append a line to the log panel and scroll to bottom."""
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    #  Controls
    # ══════════════════════════════════════════════════════════════════════════

    def _on_theme_change(self, value: str) -> None:
        """Re-run preview when theme changes (GIF variant changes)."""
        self._refresh_preview()

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select Output Directory")
        if path:
            self._output_entry.delete(0, "end")
            self._output_entry.insert(0, path)


# ═══════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    app = FlowcastStudioApp()
    app.mainloop()


if __name__ == "__main__":
    main()
