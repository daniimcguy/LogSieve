# logfilter_gui.py
from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk, messagebox

from logfilter_engine import (
    rebuild_compiled_patterns,
    apply_filters_in_memory,
    apply_filters_streaming,
)
from logfilter_io import safe_read_text, safe_write_text, open_in_vscode


class LogFilterGUI(tk.Tk):
    def __init__(self, input_file: str):
        super().__init__()
        self.title("Log Filter (INCLUDE / EXCLUDE)")
        self.geometry("1120x600")

        # ---- Dark theme colors ----
        self.bg = "#1e1e1e"
        self.fg = "#d4d4d4"
        self.panel = "#252526"
        self.border = "#3c3c3c"
        self.button = "#333333"
        self.select = "#094771"

        self.configure(bg=self.bg)

        # ttk styles
        style = ttk.Style(self)
        style.theme_use("default")

        style.configure(".",
                        background=self.bg,
                        foreground=self.fg,
                        fieldbackground=self.panel)

        style.configure("TFrame", background=self.bg)
        style.configure("TLabelframe", background=self.bg, foreground=self.fg)
        style.configure("TLabelframe.Label", background=self.bg, foreground=self.fg)

        style.configure("TLabel", background=self.bg, foreground=self.fg)
        style.configure("TButton", background=self.button, foreground=self.fg)
        style.map("TButton", background=[("active", "#3e3e40")])

        style.configure("TCheckbutton", background=self.bg, foreground=self.fg)
        style.map("TCheckbutton", background=[("active", self.bg)])

        style.configure("Dark.TEntry", fieldbackground=self.panel, foreground=self.fg)

        # File + content
        self.input_file = os.path.abspath(input_file)
        self.lines = self._load_lines(self.input_file)

        # include/exclude dict items:
        # {"type":"string"|"regex", "value":"...", "label":"...", "enabled": True, "compiled": re.Pattern|None, "regex_error": str|None}
        self.includes = []
        self.excludes = []

        self.case_insensitive = tk.BooleanVar(value=True)
        self.auto_open = tk.BooleanVar(value=True)
        self.auto_apply = tk.BooleanVar(value=True)

        # new options
        self.include_mode = tk.StringVar(value="AND")  # AND / OR
        self.stream_apply = tk.BooleanVar(value=False)  # streaming mode for big files

        # Presets (persistent)
        self.presets = []
        self.preset_file = os.path.join(os.path.dirname(__file__), "keyword_presets.json")
        self._load_presets()

        self._build_ui()
        self._refresh_stats()

        # traces: any option that changes matching should rebuild compiled patterns
        self.case_insensitive.trace_add("write", lambda *_: self._on_matching_option_changed())
        self.include_mode.trace_add("write", lambda *_: self._on_matching_option_changed())

    def _on_matching_option_changed(self):
        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())
        self._refresh_inc_exc_lists()
        if self.auto_apply.get():
            self._apply()
        else:
            self._refresh_stats()

    def _load_lines(self, path: str):
        if not os.path.exists(path):
            messagebox.showerror("File not found", f"File not found:\n{path}")
            self.destroy()
            sys.exit(1)
        text = safe_read_text(path)
        return text.splitlines()

    # ----------------------------
    # Presets persistence
    # ----------------------------
    def _load_presets(self):
        try:
            if os.path.exists(self.preset_file):
                with open(self.preset_file, "r", encoding="utf-8") as f:
                    self.presets = json.load(f)
            else:
                self.presets = []
        except Exception:
            self.presets = []

    def _save_presets(self):
        try:
            with open(self.preset_file, "w", encoding="utf-8") as f:
                json.dump(self.presets, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _edit_selected_preset(self):
        sel = list(self.kw_list.curselection())
        if not sel:
            return
        idx = sel[0]
        if not (0 <= idx < len(self.presets)):
            return

        preset = self.presets[idx]
        self._preset_dialog(mode="edit", preset_index=idx, preset=preset)

    # ----------------------------
    # UI
    # ----------------------------
    def _build_ui(self):
        # Top: file info
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Input file:").pack(anchor="w")
        self.file_entry = ttk.Entry(top, style="Dark.TEntry")
        self.file_entry.insert(0, self.input_file)
        self.file_entry.configure(state="readonly")
        self.file_entry.pack(fill="x", pady=(2, 8))

        opts = ttk.Frame(top)
        opts.pack(fill="x")
        ttk.Checkbutton(opts, text="Case-insensitive", variable=self.case_insensitive).pack(side="left")
        ttk.Checkbutton(opts, text="Auto-open output in VS Code", variable=self.auto_open).pack(side="left", padx=12)
        ttk.Checkbutton(opts, text="Auto-apply after add", variable=self.auto_apply).pack(side="left", padx=12)
        ttk.Checkbutton(opts, text="Streaming apply (big files)", variable=self.stream_apply).pack(side="left", padx=12)

        # Middle: include/exclude/keywords panels
        mid = ttk.Frame(self, padding=(10, 0, 10, 10))
        mid.pack(fill="both", expand=True)

        pan = ttk.PanedWindow(mid, orient="horizontal")
        pan.pack(fill="both", expand=True)

        # Include panel
        inc_frame = ttk.Labelframe(pan, text="INCLUDE", padding=10)
        pan.add(inc_frame, weight=1)

        # include mode radios (AND/OR)
        mode_row = ttk.Frame(inc_frame)
        mode_row.pack(fill="x", pady=(0, 6))
        ttk.Label(mode_row, text="Mode:").pack(side="left")
        ttk.Radiobutton(mode_row, text="AND", value="AND", variable=self.include_mode).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(mode_row, text="OR", value="OR", variable=self.include_mode).pack(side="left", padx=8)

        self.inc_list = tk.Listbox(
            inc_frame, height=10,
            bg=self.panel, fg=self.fg,
            selectbackground=self.select, selectforeground=self.fg,
            highlightbackground=self.border, highlightcolor=self.border,
            relief="flat", borderwidth=1
        )
        self.inc_list.pack(fill="both", expand=True)

        inc_btns = ttk.Frame(inc_frame)
        inc_btns.pack(fill="x", pady=(8, 0))
        ttk.Button(inc_btns, text="Add…", command=lambda: self._add_manual("include")).pack(side="left")
        ttk.Button(inc_btns, text="Add from clipboard", command=lambda: self._add_clipboard("include")).pack(side="left", padx=8)
        ttk.Button(inc_btns, text="Remove selected", command=lambda: self._remove_selected("include")).pack(side="left", padx=8)
        ttk.Button(inc_btns, text="Clear", command=lambda: self._clear("include")).pack(side="left", padx=8)

        # Exclude panel
        exc_frame = ttk.Labelframe(pan, text="EXCLUDE (NOT)", padding=10)
        pan.add(exc_frame, weight=1)

        self.exc_list = tk.Listbox(
            exc_frame, height=10,
            bg=self.panel, fg=self.fg,
            selectbackground=self.select, selectforeground=self.fg,
            highlightbackground=self.border, highlightcolor=self.border,
            relief="flat", borderwidth=1
        )
        self.exc_list.pack(fill="both", expand=True)

        exc_btns = ttk.Frame(exc_frame)
        exc_btns.pack(fill="x", pady=(8, 0))
        ttk.Button(exc_btns, text="Add…", command=lambda: self._add_manual("exclude")).pack(side="left")
        ttk.Button(exc_btns, text="Add from clipboard", command=lambda: self._add_clipboard("exclude")).pack(side="left", padx=8)
        ttk.Button(exc_btns, text="Remove selected", command=lambda: self._remove_selected("exclude")).pack(side="left", padx=8)
        ttk.Button(exc_btns, text="Clear", command=lambda: self._clear("exclude")).pack(side="left", padx=8)

        # Keybinds: Space toggles enable/disable
        self.inc_list.bind("<space>", lambda e: self._toggle_enabled("include"))
        self.exc_list.bind("<space>", lambda e: self._toggle_enabled("exclude"))

        # Drag & drop between INCLUDE and EXCLUDE (Ctrl = copy, else move)
        self.inc_list.bind("<ButtonPress-1>", lambda e: self._drag_start("include", e))
        self.inc_list.bind("<ButtonRelease-1>", lambda e: self._drag_drop(e))
        self.exc_list.bind("<ButtonPress-1>", lambda e: self._drag_start("exclude", e))
        self.exc_list.bind("<ButtonRelease-1>", lambda e: self._drag_drop(e))

        # Keywords (presets) panel
        kw_frame = ttk.Labelframe(pan, text="KEYWORDS (presets) — drag to INCLUDE/EXCLUDE", padding=10)
        pan.add(kw_frame, weight=1)

        self.kw_list = tk.Listbox(
            kw_frame, height=10,
            bg=self.panel, fg=self.fg,
            selectbackground=self.select, selectforeground=self.fg,
            highlightbackground=self.border, highlightcolor=self.border,
            relief="flat", borderwidth=1
        )
        self.kw_list.pack(fill="both", expand=True)

        kw_btns = ttk.Frame(kw_frame)
        kw_btns.pack(fill="x", pady=(8, 0))
        ttk.Button(kw_btns, text="Add New…", command=self._add_preset_dialog).pack(side="left")
        ttk.Button(kw_btns, text="Edit selected…", command=self._edit_selected_preset).pack(side="left", padx=8)
        ttk.Button(kw_btns, text="Delete selected", command=self._delete_selected_preset).pack(side="left", padx=8)
        ttk.Button(kw_btns, text="Refresh", command=self._refresh_presets_list).pack(side="left", padx=8)

        self._refresh_presets_list()

        # Drag & drop + double-click shortcuts for presets
        self.kw_list.bind("<ButtonPress-1>", self._kw_drag_start)
        self.kw_list.bind("<ButtonRelease-1>", self._kw_drag_drop)
        self.kw_list.bind("<Double-Button-1>", self._kw_to_include)
        self.kw_list.bind("<Shift-Double-Button-1>", self._kw_to_exclude)

        # Bottom: actions + stats
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")

        ttk.Button(bottom, text="Apply (write filtered file)", command=self._apply).pack(side="left")
        ttk.Button(bottom, text="Open output", command=self._open_output).pack(side="left", padx=8)
        ttk.Button(bottom, text="Reload input from disk", command=self._reload).pack(side="left", padx=8)
        ttk.Button(bottom, text="Reset all", command=self._reset_all).pack(side="left", padx=8)

        self.stats = ttk.Label(bottom, text="")
        self.stats.pack(side="right")

        # Output path (deterministic)
        base = os.path.basename(self.input_file)
        name, ext = os.path.splitext(base)

        temp_dir = os.path.join(tempfile.gettempdir(), "vscode-logfilter")
        os.makedirs(temp_dir, exist_ok=True)

        # Cleanup old filtered files (older than 24 hours)
        for f in glob.glob(os.path.join(temp_dir, "*")):
            try:
                if os.path.isfile(f) and os.path.getmtime(f) < (time.time() - 24 * 3600):
                    os.remove(f)
            except OSError:
                pass

        self.output_file = os.path.join(temp_dir, f"{name}.filtered{ext}")

    # ----------------------------
    # UI helpers
    # ----------------------------
    def _refresh_stats(self, filtered_count=None, blocking_includes=None):
        total = len(self.lines)
        if filtered_count is None:
            self.stats.configure(text=f"Lines (input): {total}")
            return

        extra = ""
        if blocking_includes:
            extra = "  |  Blocking INCLUDE: " + ", ".join(blocking_includes)
        self.stats.configure(text=f"Lines (input): {total}  |  Lines (output): {filtered_count}{extra}")

    def _prompt_value(self, title):
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("520x150")
        win.transient(self)
        win.grab_set()
        win.configure(bg=self.bg)

        ttk.Label(win, text=title).pack(anchor="w", padx=10, pady=(10, 2))
        entry = ttk.Entry(win, style="Dark.TEntry")
        entry.pack(fill="x", padx=10, pady=(0, 10))
        entry.focus_set()

        value = {"v": None}

        def ok():
            v = entry.get().strip()
            value["v"] = v if v else None
            win.destroy()

        def cancel():
            value["v"] = None
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="OK", command=ok).pack(side="left")
        ttk.Button(btns, text="Cancel", command=cancel).pack(side="left", padx=8)

        self.wait_window(win)
        return value["v"]

    # ----------------------------
    # Include/Exclude operations
    # ----------------------------
    def _add_manual(self, which):
        v = self._prompt_value("Add pattern")
        if not v:
            return
        self._add_value(which, v, item_type="string", label=v)

    def _add_clipboard(self, which):
        try:
            v = self.clipboard_get().strip()
        except tk.TclError:
            v = ""
        if not v:
            messagebox.showwarning("Clipboard empty", "Clipboard is empty.")
            return
        self._add_value(which, v, item_type="string", label=v)

    def _add_value(self, which, v, item_type="string", label=None):
        item = {
            "type": item_type,
            "value": v,
            "label": label if label else v,
            "enabled": True,
        }

        if which == "include":
            self.includes.append(item)
        else:
            self.excludes.append(item)

        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())
        self._refresh_inc_exc_lists()

        if self.auto_apply.get():
            self._apply()

    def _format_item_label(self, it):
        # prefixes:
        # ⏸ disabled
        # ⚠ invalid regex
        prefix = ""
        if not it.get("enabled", True):
            prefix += "⏸ "
        if it.get("type") == "regex" and it.get("regex_error"):
            prefix += "⚠ "
        return f"{prefix}[{it.get('type','string')}] {it.get('label', it.get('value',''))}"

    def _refresh_inc_exc_lists(self):
        self.inc_list.delete(0, "end")
        for it in self.includes:
            self.inc_list.insert("end", self._format_item_label(it))

        self.exc_list.delete(0, "end")
        for it in self.excludes:
            self.exc_list.insert("end", self._format_item_label(it))

    def _remove_selected(self, which):
        if which == "include":
            lb = self.inc_list
            arr = self.includes
        else:
            lb = self.exc_list
            arr = self.excludes

        sel = list(lb.curselection())
        if not sel:
            return

        for idx in reversed(sel):
            if 0 <= idx < len(arr):
                del arr[idx]

        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())
        self._refresh_inc_exc_lists()

        if self.auto_apply.get():
            self._apply()

    def _clear(self, which):
        if which == "include":
            self.includes = []
        else:
            self.excludes = []

        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())
        self._refresh_inc_exc_lists()

        if self.auto_apply.get():
            self._apply()

    def _reset_all(self):
        self.includes = []
        self.excludes = []

        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())
        self._refresh_inc_exc_lists()
        self._apply()

    def _toggle_enabled(self, which):
        lb = self.inc_list if which == "include" else self.exc_list
        arr = self.includes if which == "include" else self.excludes
        sel = list(lb.curselection())
        if not sel:
            return

        for idx in sel:
            if 0 <= idx < len(arr):
                arr[idx]["enabled"] = not arr[idx].get("enabled", True)

        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())
        self._refresh_inc_exc_lists()

        if self.auto_apply.get():
            self._apply()

    # Drag & drop between Include/Exclude
    def _drag_start(self, source, event):
        self._drag_source = source
        lb = self.inc_list if source == "include" else self.exc_list
        idx = lb.nearest(event.y)

        if idx is None:
            self._drag_index = None
            return

        lb.selection_clear(0, "end")
        lb.selection_set(idx)
        self._drag_index = idx

    def _drag_drop(self, event):
        if not hasattr(self, "_drag_source") or not hasattr(self, "_drag_index"):
            return
        if self._drag_index is None:
            return

        x_root = event.x_root
        y_root = event.y_root

        def over_widget(w):
            wx = w.winfo_rootx()
            wy = w.winfo_rooty()
            ww = w.winfo_width()
            wh = w.winfo_height()
            return (wx <= x_root <= wx + ww) and (wy <= y_root <= wy + wh)

        target = None
        if over_widget(self.inc_list):
            target = "include"
        elif over_widget(self.exc_list):
            target = "exclude"
        else:
            return

        source = self._drag_source
        if target == source:
            return

        # Ctrl = copy, else move
        copy = (event.state & 0x0004) != 0

        if source == "include":
            if not (0 <= self._drag_index < len(self.includes)):
                return
            item = dict(self.includes[self._drag_index]) if copy else self.includes.pop(self._drag_index)
            self.excludes.append(item)
        else:
            if not (0 <= self._drag_index < len(self.excludes)):
                return
            item = dict(self.excludes[self._drag_index]) if copy else self.excludes.pop(self._drag_index)
            self.includes.append(item)

        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())
        self._refresh_inc_exc_lists()

        if self.auto_apply.get():
            self._apply()

    # ----------------------------
    # Presets UI
    # ----------------------------
    def _refresh_presets_list(self):
        if not hasattr(self, "kw_list"):
            return
        self.kw_list.delete(0, "end")
        for p in self.presets:
            desc = p.get("desc", "")
            rx = p.get("regex", "")
            self.kw_list.insert("end", f"{desc}  |  {rx}")

    def _add_preset_dialog(self):
        self._preset_dialog(mode="add")

    def _preset_dialog(self, mode="add", preset_index=None, preset=None):
        import re

        win = tk.Toplevel(self)
        win.title("Add Keyword Preset" if mode == "add" else "Edit Keyword Preset")
        win.geometry("720x240")
        win.transient(self)
        win.grab_set()
        win.configure(bg=self.bg)

        ttk.Label(win, text="Description").pack(anchor="w", padx=10, pady=(10, 2))
        desc_entry = ttk.Entry(win, style="Dark.TEntry")
        desc_entry.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Label(win, text="Regex").pack(anchor="w", padx=10, pady=(0, 2))
        rx_entry = ttk.Entry(win, style="Dark.TEntry")
        rx_entry.pack(fill="x", padx=10, pady=(0, 10))

        if mode == "edit" and preset:
            desc_entry.insert(0, preset.get("desc", ""))
            rx_entry.insert(0, preset.get("regex", ""))

        msg = ttk.Label(win, text="")
        msg.pack(anchor="w", padx=10)

        def ok():
            desc = desc_entry.get().strip()
            rx = rx_entry.get().strip()

            if not desc or not rx:
                msg.configure(text="Description and Regex are required.")
                return

            try:
                re.compile(rx)
            except re.error as e:
                msg.configure(text=f"Invalid regex: {e}")
                return

            if mode == "add":
                self.presets.append({"desc": desc, "regex": rx})
            else:
                if preset_index is None or not (0 <= preset_index < len(self.presets)):
                    msg.configure(text="Internal error: invalid preset index.")
                    return
                self.presets[preset_index] = {"desc": desc, "regex": rx}

            self._save_presets()
            self._refresh_presets_list()

            if mode == "edit" and preset_index is not None:
                self.kw_list.selection_clear(0, "end")
                self.kw_list.selection_set(preset_index)
                self.kw_list.see(preset_index)

            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(10, 10))
        ttk.Button(btns, text="Save" if mode == "edit" else "Add", command=ok).pack(side="left")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=8)

        desc_entry.focus_set()
        self.wait_window(win)

    def _delete_selected_preset(self):
        sel = list(self.kw_list.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            if 0 <= idx < len(self.presets):
                del self.presets[idx]
        self._save_presets()
        self._refresh_presets_list()

    def _kw_get_selected_preset(self):
        sel = list(self.kw_list.curselection())
        if not sel:
            return None
        idx = sel[0]
        if not (0 <= idx < len(self.presets)):
            return None
        return self.presets[idx]

    def _kw_to_include(self, _evt=None):
        p = self._kw_get_selected_preset()
        if not p:
            return
        self._add_value("include", p["regex"], item_type="regex", label=p["desc"])

    def _kw_to_exclude(self, _evt=None):
        p = self._kw_get_selected_preset()
        if not p:
            return
        self._add_value("exclude", p["regex"], item_type="regex", label=p["desc"])

    def _kw_drag_start(self, event):
        self._drag_preset_index = self.kw_list.nearest(event.y)

    def _kw_drag_drop(self, event):
        if not hasattr(self, "_drag_preset_index"):
            return
        idx = self._drag_preset_index
        if not (0 <= idx < len(self.presets)):
            return
        p = self.presets[idx]

        x_root = event.x_root
        y_root = event.y_root

        def over_widget(w):
            wx = w.winfo_rootx()
            wy = w.winfo_rooty()
            ww = w.winfo_width()
            wh = w.winfo_height()
            return (wx <= x_root <= wx + ww) and (wy <= y_root <= wy + wh)

        if over_widget(self.inc_list):
            self._add_value("include", p["regex"], item_type="regex", label=p["desc"])
        elif over_widget(self.exc_list):
            self._add_value("exclude", p["regex"], item_type="regex", label=p["desc"])

    # ----------------------------
    # Apply / IO
    # ----------------------------
    def _reload(self):
        self.lines = self._load_lines(self.input_file)
        if self.auto_apply.get():
            self._apply()
        else:
            self._refresh_stats()

    def _apply(self):
        rebuild_compiled_patterns(self.includes, self.excludes, self.case_insensitive.get())

        blocking = []

        if self.stream_apply.get():
            # streaming apply: write output directly, compute blocking via single_counts
            total, out_n, single_counts = apply_filters_streaming(
                self.input_file,
                self.output_file,
                self.includes,
                self.excludes,
                case_insensitive=self.case_insensitive.get(),
                include_mode=self.include_mode.get(),
            )

            # keep input lines count label consistent with loaded view
            # (we still keep self.lines for quick UI, but we report filtered results from streaming pass)
            for idx, c in single_counts.items():
                if c == 0:
                    blocking.append(self.includes[idx].get("label", self.includes[idx].get("value", "")))

            # update stats: show *loaded* total, not streaming total (avoid confusion)
            self._refresh_stats(filtered_count=out_n, blocking_includes=blocking)

        else:
            filtered, single_counts = apply_filters_in_memory(
                self.lines,
                self.includes,
                self.excludes,
                case_insensitive=self.case_insensitive.get(),
                include_mode=self.include_mode.get(),
            )

            # blocking includes = enabled includes with 0 single matches
            for idx, c in single_counts.items():
                if c == 0:
                    blocking.append(self.includes[idx].get("label", self.includes[idx].get("value", "")))

            safe_write_text(self.output_file, "\n".join(filtered) + ("\n" if filtered else ""))
            self._refresh_stats(filtered_count=len(filtered), blocking_includes=blocking)

        if self.auto_open.get():
            open_in_vscode(self.output_file)

    def _open_output(self):
        open_in_vscode(self.output_file)
