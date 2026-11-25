"""Tkinter floating capsule and scrollable session drawer UI."""

import threading
import tkinter as tk
from tkinter import Menu, simpledialog

from .config import MAX_DISCOVER_SESSIONS, fmt_tok
from .monitor import MonitorCore
from .platform_utils import bind_mouse_wheel, enforce_window_topmost, get_ui_fonts


class FloatingWidget:
    def __init__(self, root):
        self.root = root
        self.running = True
        self.core = MonitorCore()
        self.expanded = False
        self.active_idx = 0
        self.sessions = []
        self.latest_data = {"connected": False}
        self.current_category = self.core.config.get("current_category", "ALL")

        self.sans_font, self.mono_font = get_ui_fonts()

        self.bg_color = "#16161a"
        self.border_color = "#3b82f6"
        self.text_primary = "#f0f0f4"
        self.text_dim = "#9090a2"
        self.text_warn = "#f59e0b"
        self.text_danger = "#ef4444"
        self.text_green = "#22c55e"

        self.root.configure(bg=self.border_color)
        sw = self.root.winfo_screenwidth()
        self.capsule_w, self.capsule_h = 520, 68
        init_x, init_y = max(10, (sw - self.capsule_w) // 2), 35
        self.root.geometry(f"{self.capsule_w}x{self.capsule_h}+{init_x}+{init_y}")

        self.main_frame = tk.Frame(self.root, bg=self.bg_color, padx=6, pady=2)
        self.main_frame.pack(fill="both", expand=True, padx=1, pady=1)

        def _lbl(p, txt, font=None, fg=self.text_primary, side="left", px=0, cursor=None):
            f = font or (self.sans_font, 9)
            l = tk.Label(p, text=txt, font=f, bg=self.bg_color, fg=fg, cursor=cursor or "")
            l.pack(side=side, padx=px)
            return l

        # Row 1: session name + ctx + quota
        self.compact_row = tk.Frame(self.main_frame, bg=self.bg_color)
        self.compact_row.pack(fill="x")
        self.lbl_category = _lbl(
            self.compact_row,
            f"[{self.current_category}]",
            (self.sans_font, 8, "bold"),
            "#38bdf8",
            px=(2, 2),
            cursor="hand2",
        )
        self.lbl_category.bind("<Button-1>", lambda e: self.cycle_category())
        self.lbl_page = _lbl(self.compact_row, "[--/--]", (self.sans_font, 9, "bold"), self.text_dim, px=(2, 4))
        self.btn_prev = _lbl(self.compact_row, "<", (self.mono_font, 10, "bold"), "#60a5fa", px=2, cursor="hand2")
        self.btn_prev.bind("<Button-1>", lambda e: self.cycle_session(-1))
        self.lbl_session = _lbl(
            self.compact_row, "Connecting Antigravity...", (self.sans_font, 9, "bold"), px=4
        )
        self.btn_next = _lbl(self.compact_row, ">", (self.mono_font, 10, "bold"), "#60a5fa", px=2, cursor="hand2")
        self.btn_next.bind("<Button-1>", lambda e: self.cycle_session(1))
        _lbl(self.compact_row, "|", fg="#383848", px=4)
        self.lbl_reset = _lbl(self.compact_row, "Reset: --", (self.sans_font, 8), self.text_dim, side="right", px=(2, 4))
        self.lbl_quota = _lbl(
            self.compact_row, "Quota: --%", (self.sans_font, 9, "bold"), self.text_green, side="right", px=(4, 2)
        )

        # Row 2: steps + responses + refresh
        self.detail_row = tk.Frame(self.main_frame, bg=self.bg_color)
        self.detail_row.pack(fill="x", pady=(1, 0))
        self.lbl_steps = _lbl(self.detail_row, "Steps: --", (self.sans_font, 8), self.text_dim)
        _lbl(self.detail_row, "|", (self.sans_font, 8), "#383848", px=6)
        self.lbl_responses = _lbl(self.detail_row, "Responses: --", (self.sans_font, 8), self.text_dim)
        _lbl(self.detail_row, "|", (self.sans_font, 8), "#383848", px=6)
        self.lbl_refresh_hint = _lbl(
            self.detail_row, "[Refresh]", (self.sans_font, 8, "bold"), "#60a5fa", cursor="hand2"
        )
        self.lbl_refresh_hint.bind("<Button-1>", lambda e: self.trigger_refresh())
        self.lbl_refresh_hint.bind("<Button-3>", self.show_context_menu)

        # Drawer
        self.drawer_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        self.drawer_tab_bar = tk.Frame(self.drawer_frame, bg=self.bg_color)
        self.drawer_tab_bar.pack(fill="x", pady=(2, 4))

        self.tab_ide = tk.Label(
            self.drawer_tab_bar, text="IDE (--)", font=(self.sans_font, 8, "bold"), cursor="hand2", padx=6, pady=2
        )
        self.tab_ide.pack(side="left", padx=(2, 4))
        self.tab_ide.bind("<Button-1>", lambda e: self.switch_category("IDE"))

        self.tab_cli = tk.Label(
            self.drawer_tab_bar, text="CLI (--)", font=(self.sans_font, 8, "bold"), cursor="hand2", padx=6, pady=2
        )
        self.tab_cli.pack(side="left", padx=4)
        self.tab_cli.bind("<Button-1>", lambda e: self.switch_category("CLI"))

        self.tab_all = tk.Label(
            self.drawer_tab_bar, text="ALL (--)", font=(self.sans_font, 8, "bold"), cursor="hand2", padx=6, pady=2
        )
        self.tab_all.pack(side="left", padx=4)
        self.tab_all.bind("<Button-1>", lambda e: self.switch_category("ALL"))

        self.drawer_canvas = tk.Canvas(self.drawer_frame, bg=self.bg_color, highlightthickness=0, bd=0)
        self.list_container = tk.Frame(self.drawer_canvas, bg=self.bg_color)
        self.canvas_window = self.drawer_canvas.create_window((0, 0), window=self.list_container, anchor="nw")
        self.list_container.bind(
            "<Configure>", lambda e: self.drawer_canvas.configure(scrollregion=self.drawer_canvas.bbox("all"))
        )
        self.drawer_canvas.bind(
            "<Configure>", lambda e: self.drawer_canvas.itemconfig(self.canvas_window, width=e.width)
        )
        self.drawer_canvas.pack(fill="both", expand=True, pady=(2, 0))

        self._drag_start_x = self._drag_start_y = 0
        bind_widgets = [
            self.main_frame,
            self.compact_row,
            self.detail_row,
            self.lbl_page,
            self.lbl_session,
            self.lbl_quota,
            self.lbl_reset,
            self.lbl_steps,
            self.lbl_responses,
        ]
        for w in bind_widgets:
            w.bind("<Button-1>", self.on_drag_start)
            w.bind("<B1-Motion>", self.on_drag_motion)
            w.bind("<Button-3>", self.show_context_menu)
            w.bind("<Double-Button-1>", lambda e: self.toggle_expand())
            bind_mouse_wheel(w, self.cycle_session)

        try:
            self.root.overrideredirect(True)
        except Exception:
            pass
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        self.root.deiconify()
        self.root.lift()
        self._schedule_topmost()

        self.menu = Menu(
            self.root,
            tearoff=0,
            bg="#222228",
            fg="#ffffff",
            activebackground="#3b82f6",
            activeforeground="#ffffff",
            selectcolor="#38bdf8",
        )
        self.menu.add_command(label="Refresh", command=self.trigger_refresh)
        self.menu.add_command(label="Toggle Drawer", command=self.toggle_expand)
        self.menu.add_command(label="Pin / Unpin Current", command=self.toggle_pin_current)
        self.menu.add_command(label="Rename Current", command=self.prompt_rename_current)
        self.var_filter_cli = tk.BooleanVar(value=bool(self.core.config.get("filter_short_cli", True)))
        min_steps = int(self.core.config.get("min_cli_steps", 10))
        self.menu.add_checkbutton(
            label=f"Filter Short CLI (<{min_steps} steps)",
            variable=self.var_filter_cli,
            command=self.toggle_filter_short_cli,
        )
        self.menu.add_separator()
        self.menu.add_command(label="Reset Position", command=self.reset_position)
        self.menu.add_command(label="Exit", command=self.on_exit)

        self.root.after(300, self.trigger_refresh)

    def _schedule_topmost(self):
        enforce_window_topmost(self.root)
        if self.running:
            self.root.after(3000, self._schedule_topmost)

    def toggle_filter_short_cli(self):
        self.core.set_filter_short_cli(self.var_filter_cli.get())
        self.active_idx = 0
        self.trigger_refresh()

    def cycle_category(self):
        order = ["ALL", "IDE", "CLI"]
        cur = self.current_category if self.current_category in order else "ALL"
        nxt = order[(order.index(cur) + 1) % len(order)]
        self.switch_category(nxt)

    def switch_category(self, cat):
        self.current_category = cat
        self.core.config["current_category"] = cat
        self.core.save_config()
        self.lbl_category.config(text=f"[{cat}]")
        self.active_idx = 0
        self.render_compact_row()
        if self.expanded:
            self.rebuild_drawer()

    def on_exit(self):
        self.running = False
        self.root.destroy()

    def reset_position(self):
        sw = self.root.winfo_screenwidth()
        init_x = max(10, (sw - self.capsule_w) // 2)
        self.root.geometry(f"+{init_x}+35")

    def prompt_rename_current(self):
        carousel = self.get_carousel_sessions()
        if not carousel or self.active_idx >= len(carousel):
            return
        curr = carousel[self.active_idx]
        new_name = simpledialog.askstring(
            "Rename Session", f"Alias for session:\n({curr.summary})", initialvalue=curr.summary
        )
        if new_name is not None:
            self.core.set_alias(curr.cid, new_name)
            curr.summary = new_name.strip() if new_name.strip() else curr.cid[:8]
            self.render_compact_row()
            if self.expanded:
                self.rebuild_drawer()

    def toggle_pin_current(self):
        carousel = self.get_carousel_sessions()
        if carousel and self.active_idx < len(carousel):
            curr = carousel[self.active_idx]
            self.core.toggle_pin(curr.cid)
            curr.is_pinned = curr.cid in self.core.pinned_ids
            self.render_compact_row()
            if self.expanded:
                self.rebuild_drawer()

    def cycle_session(self, direction):
        carousel = self.get_carousel_sessions()
        if not carousel:
            return
        self.active_idx = (self.active_idx + direction) % len(carousel)
        self.render_compact_row()

    def get_carousel_sessions(self):
        if not self.sessions:
            return []
        filtered = self.sessions
        if self.current_category == "IDE":
            filtered = [s for s in self.sessions if not getattr(s, "is_cli", False)]
        elif self.current_category == "CLI":
            filtered = [s for s in self.sessions if getattr(s, "is_cli", False)]
        pinned = [s for s in filtered if s.is_pinned]
        return pinned if pinned else filtered[:20]

    def _scroll_drawer(self, steps):
        self.drawer_canvas.yview_scroll(steps, "units")
        return "break"

    def on_drag_start(self, event):
        self._drag_start_x = event.x_root - self.root.winfo_x()
        self._drag_start_y = event.y_root - self.root.winfo_y()

    def on_drag_motion(self, event):
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def show_context_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def toggle_expand(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.drawer_frame.pack(fill="both", expand=True)
            self.rebuild_drawer()
            self.drawer_canvas.yview_moveto(0)
        else:
            self.drawer_frame.pack_forget()
            self.root.geometry(f"{self.capsule_w}x{self.capsule_h}")

    def rebuild_drawer(self):
        ide_list = [s for s in self.sessions if not getattr(s, "is_cli", False)]
        cli_list = [s for s in self.sessions if getattr(s, "is_cli", False)]
        all_list = self.sessions

        for lbl, txt, cat in (
            (self.tab_ide, f"IDE ({len(ide_list)})", "IDE"),
            (self.tab_cli, f"CLI ({len(cli_list)})", "CLI"),
            (self.tab_all, f"ALL ({len(all_list)})", "ALL"),
        ):
            is_active = self.current_category == cat
            lbl.config(
                text=txt,
                fg="#ffffff" if is_active else self.text_dim,
                bg="#2563eb" if is_active else "#1c1c24",
            )

        for widget in self.list_container.winfo_children():
            widget.destroy()

        cur_items = ide_list if self.current_category == "IDE" else (cli_list if self.current_category == "CLI" else all_list)

        if not cur_items:
            lbl = tk.Label(
                self.list_container,
                text=f"No {self.current_category} sessions",
                font=(self.sans_font, 8),
                bg=self.bg_color,
                fg=self.text_dim,
            )
            lbl.pack(anchor="w", padx=6, pady=4)
            self.root.geometry(f"{self.capsule_w + 40}x{self.capsule_h + 70}")
            return

        bind_mouse_wheel(self.drawer_canvas, self._scroll_drawer)
        bind_mouse_wheel(self.list_container, self._scroll_drawer)

        for s in cur_items[:MAX_DISCOVER_SESSIONS]:
            row = tk.Frame(self.list_container, bg=self.bg_color)
            row.pack(fill="x", pady=1)
            bind_mouse_wheel(row, self._scroll_drawer)

            pin_text, pin_fg = ("[x]", "#38bdf8") if s.is_pinned else ("[ ]", self.text_dim)
            btn_pin = tk.Label(
                row, text=pin_text, font=(self.mono_font, 8, "bold"), bg=self.bg_color, fg=pin_fg, cursor="hand2"
            )
            btn_pin.pack(side="left", padx=(2, 4))
            btn_pin.bind("<Button-1>", lambda e, cid=s.cid: self.on_drawer_pin_toggle(cid))
            bind_mouse_wheel(btn_pin, self._scroll_drawer)

            pct_color = self.text_danger if s.ctx_pct >= 80 else (self.text_warn if s.ctx_pct >= 60 else self.text_primary)
            short_title = s.summary[:26] + (".." if len(s.summary) > 26 else "")
            tok_k = fmt_tok(s.tokens)
            lim_k = f"{int(s.limit / 1000)}k"

            text_desc = f"{short_title} ({s.model_tag} {lim_k}) - {tok_k}/{lim_k} ({s.ctx_pct:.1f}%)"
            lbl_desc = tk.Label(
                row, text=text_desc, font=(self.sans_font, 8), bg=self.bg_color, fg=pct_color, cursor="hand2", anchor="w"
            )
            lbl_desc.pack(side="left", fill="x", expand=True)
            lbl_desc.bind("<Button-1>", lambda e, cid=s.cid: self.on_select_session_from_drawer(cid))
            bind_mouse_wheel(lbl_desc, self._scroll_drawer)

        self.list_container.update_idletasks()
        self.drawer_canvas.configure(scrollregion=self.drawer_canvas.bbox("all"))

        total_items = min(len(cur_items), MAX_DISCOVER_SESSIONS)
        drawer_h = max(70, min(360, total_items * 26 + 42))
        self.root.geometry(f"{self.capsule_w + 40}x{self.capsule_h + drawer_h}")

    def on_drawer_pin_toggle(self, cid):
        self.core.toggle_pin(cid)
        for s in self.sessions:
            s.is_pinned = s.cid in self.core.pinned_ids
        self.rebuild_drawer()
        self.render_compact_row()

    def on_select_session_from_drawer(self, cid):
        carousel = self.get_carousel_sessions()
        for idx, s in enumerate(carousel):
            if s.cid == cid:
                self.active_idx = idx
                self.render_compact_row()
                return

        sel_s = next((s for s in self.sessions if s.cid == cid), None)
        if sel_s:
            if not sel_s.is_pinned:
                self.core.toggle_pin(cid)
                sel_s.is_pinned = True
                self.rebuild_drawer()
            carousel = self.get_carousel_sessions()
            for c_idx, cs in enumerate(carousel):
                if cs.cid == sel_s.cid:
                    self.active_idx = c_idx
                    break
            self.render_compact_row()

    def render_compact_row(self):
        q_pct = self.latest_data.get("quota_pct", 100.0)
        q_color = self.text_green if q_pct >= 50 else (self.text_warn if q_pct >= 20 else self.text_danger)
        self.lbl_quota.config(text=f"Quota: {q_pct:.0f}%", fg=q_color)
        self.lbl_reset.config(text=f"Reset: {self.latest_data.get('reset_str', '--')}")

        if not self.latest_data.get("connected"):
            self.lbl_page.config(text="[--/--]")
            self.lbl_session.config(text="Connecting...", fg=self.text_warn)

        carousel = self.get_carousel_sessions()
        if not carousel:
            self.lbl_page.config(text="[0/0]")
            self.lbl_session.config(text="Idle (No Session)", fg=self.text_dim)
            self.lbl_steps.config(text="Steps: --")
            self.lbl_responses.config(text="Responses: --")
            return

        if self.active_idx >= len(carousel):
            self.active_idx = 0

        curr = carousel[self.active_idx]
        total = len(carousel)
        pin_mark = "PIN " if curr.is_pinned else ""
        self.lbl_page.config(text=f"[{pin_mark}{self.active_idx + 1}/{total}]")

        title = curr.summary[:20] + (".." if len(curr.summary) > 20 else "")
        tok_str = fmt_tok(curr.tokens)
        lim_str = f"{int(curr.limit / 1000)}k"
        color = self.text_danger if curr.ctx_pct >= 80 else (self.text_warn if curr.ctx_pct >= 60 else self.text_primary)

        self.lbl_session.config(text=f"{title} ({curr.model_tag}): {tok_str}/{lim_str} {curr.ctx_pct:.1f}%", fg=color)
        self.lbl_steps.config(text=f"Steps: {curr.step_count}")

        if curr.planner_response_count < 0:
            self.lbl_responses.config(text="Responses: ...", fg=self.text_dim)
            threading.Thread(target=self._load_pr_count, args=(curr,), daemon=True).start()
        else:
            self.lbl_responses.config(text=f"Responses: {curr.planner_response_count}", fg=self.text_dim)

    def _load_pr_count(self, session):
        count = self.core.count_planner_responses(session.cid)
        session.planner_response_count = count

        def _update():
            carousel = self.get_carousel_sessions()
            if carousel and self.active_idx < len(carousel) and carousel[self.active_idx].cid == session.cid:
                self.lbl_responses.config(text=f"Responses: {count}", fg=self.text_dim)

        self.root.after(0, _update)

    def update_ui(self, data):
        self.latest_data = data
        self.sessions = data.get("sessions", [])
        self.render_compact_row()
        if self.expanded:
            self.rebuild_drawer()

    def trigger_refresh(self):
        self.lbl_responses.config(text="Responses: ...", fg=self.text_dim)
        threading.Thread(
            target=lambda: self.root.after(0, self.update_ui, self.core.fetch_all()), daemon=True
        ).start()
