import sys
import os
import math
from typing import Optional
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from game.world import GameWorld
from game.auto_player import AutoPlayer
import game.config as cfg


class GameUI:
    """Main game UI using tkinter Canvas for map + info panels."""

    CELL_SIZE = 24
    COLORS = {
        "bg": "#000000",
        "wall": "#808080",
        "floor": "#404040",
        "player": "#ffdd00",
        "monster": "#ff4444",
        "boss": "#ff0000",
        "item": "#44ff44",
        "merchant": "#ffcc00",
        "door": "#d2691e",
        "stairs": "#9370db",
        "text": "#c0c0c0",
        "text_dim": "#666666",
    }

    def __init__(self, master: tk.Tk, world: GameWorld):
        self.master = master
        self.world = world
        self.cell_size = self.CELL_SIZE

        # Auto-play
        self.auto_player = AutoPlayer(world)
        self._auto_job_id: Optional[str] = None
        self._auto_pending_skill: bool = False
        self._auto_pending_shop: bool = False

        # Hover tracking
        self._hover_tile: Optional[tuple[int, int]] = None

        # Modal state: "shop", "skill", or None
        self._modal: Optional[str] = None

        # Reused canvas item pool (see _draw_map): created once per size.
        self._cell_pool: Optional[list] = None
        self._cell_pool_size: Optional[tuple[int, int]] = None
        self._cell_state: list = []      # last painted appearance per slot
        self._cell_bg_tag: list = []     # per-slot tag for the background rect
        self._cell_fg_tag: list = []     # per-slot tag for the glyph
        self._inv_sig: Optional[tuple] = None   # skip unchanged inventory
        self._log_count: int = -1               # skip unchanged log
        self._cam: tuple = (None, None)         # dead-zoned camera centre
        self._cam_floor: Optional[int] = None   # forces a recentre on floor change
        self._cell_font = ("Consolas", max(8, int(self.CELL_SIZE * 0.65)), "bold")

        self._setup_ui()
        self._bind_events()
        self._draw()

    # ================================================================
    #  UI LAYOUT
    # ================================================================

    def _setup_ui(self):
        self.master.title("Python Magic Tower - ECS Edition")
        self.master.configure(bg="#1a1a1a")
        self.master.resizable(False, False)
        self.master.protocol("WM_DELETE_WINDOW", self._on_closing)

        cs = self.cell_size
        map_w = self.world.config.get("SCREEN_WIDTH", 41) * cs
        map_h = self.world.config.get("SCREEN_HEIGHT", 21) * cs
        panel_w = 280
        bottom_h = 52
        padding = 16

        # --- Main horizontal split ---
        main_frame = ttk.Frame(self.master)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # --- Left: Canvas (game map) ---
        canvas_frame = ttk.Frame(main_frame, width=map_w, height=map_h)
        canvas_frame.pack(side=tk.LEFT, fill=tk.NONE)
        canvas_frame.pack_propagate(False)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg=self.COLORS["bg"],
            width=map_w,
            height=map_h,
            highlightthickness=0,
        )
        self.canvas.pack()

        # --- Right: Scrollable info panel stack ---
        right_panel = ttk.Frame(main_frame, width=panel_w)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(8, 0))
        right_panel.pack_propagate(False)

        # Scrollable wrapper for right panel content
        r_canvas = tk.Canvas(right_panel, bg="#1a1a1a", highlightthickness=0, width=panel_w)
        r_scroll = ttk.Scrollbar(right_panel, orient=tk.VERTICAL, command=r_canvas.yview)
        self._right_inner = tk.Frame(r_canvas, bg="#1a1a1a")

        self._right_inner.bind("<Configure>",
            lambda e: r_canvas.configure(scrollregion=r_canvas.bbox("all")))
        r_canvas.create_window((0, 0), window=self._right_inner, anchor="nw", width=panel_w-4)
        r_canvas.configure(yscrollcommand=r_scroll.set)

        r_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        r_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Mousewheel scrolling for right panel
        def _on_mousewheel(event):
            r_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        r_canvas.bind("<Enter>", lambda e: r_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        r_canvas.bind("<Leave>", lambda e: r_canvas.unbind_all("<MouseWheel>"))

        self._build_info_panels(self._right_inner)

        # --- Bottom progress bar + controls ---
        bottom_frame = tk.Frame(self.master, bg="#111111", height=40)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(2, 0))
        bottom_frame.pack_propagate(False)

        # Auto-play toggle button (left side)
        self.auto_btn = tk.Button(
            bottom_frame, text="⚡ 挂机 OFF", font=("Segoe UI", 9, "bold"),
            bg="#333333", fg="#888888", padx=8, pady=1,
            relief=tk.FLAT, activebackground="#555555", activeforeground="#ffffff",
            command=self._toggle_auto_play,
        )
        self.auto_btn.pack(side=tk.LEFT, padx=(4, 8))

        # Progress bar frame (center)
        progress_frame = tk.Frame(bottom_frame, bg="#111111")
        progress_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.progress_var = tk.DoubleVar(value=0.0)
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Game.Horizontal.TProgressbar",
            background="#8b0000",
            troughcolor="#222222",
            bordercolor="#111111",
            lightcolor="#8b0000",
            darkcolor="#8b0000",
        )
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=1.0,
            mode="determinate",
            style="Game.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill=tk.X, expand=True)

        self.progress_label = tk.Label(
            progress_frame, text="", bg="#111111", fg="#888888",
            font=("Segoe UI", 8),
        )
        self.progress_label.pack()

        # Speed label (right side)
        self.speed_label = tk.Label(
            bottom_frame, text="200ms", bg="#111111", fg="#666666",
            font=("Consolas", 8), width=6,
        )
        self.speed_label.pack(side=tk.RIGHT, padx=4)

        # --- Bottom hover bar ---
        self.hover_var = tk.StringVar(value="")
        self.hover_label = tk.Label(
            self.master, textvariable=self.hover_var,
            bg="#1a1a1a", fg="#aaaaaa", font=("Consolas", 9),
            anchor="w", padx=10, height=1,
        )
        self.hover_label.pack(side=tk.BOTTOM, fill=tk.X, padx=8)

        # Set exact window size: map + panel + hover bar
        win_w = map_w + panel_w + padding + 8
        win_h = map_h + bottom_h + padding + 8
        self.master.geometry(f"{win_w}x{win_h}")

    def _build_info_panels(self, parent):
        style = ttk.Style()
        style.configure("Game.TLabel", background="#111111", foreground="#cccccc")
        style.configure("Title.TLabel", background="#111111", foreground="#8b0000",
                        font=("Segoe UI", 11, "bold"))
        style.configure("Highlight.TLabel", background="#111111", foreground="#ff9900")

        # ---- Player Status Panel ----
        status_frm = tk.LabelFrame(parent, text=" Player Status ", fg="#8b0000",
                                   bg="#111111", font=("Segoe UI", 10, "bold"))
        status_frm.pack(fill=tk.X, pady=(0, 4))
        self.status_labels: dict[str, tk.Label] = {}
        fields = [
            ("level",     "Level"),
            ("hp",        "HP"),
            ("exp",       "EXP"),
            ("skill_pts", "Skill Pts"),
            ("gold",      "Gold"),
            ("attack",    "ATK"),
            ("defense",   "DEF"),
            ("floor",     "Floor"),
            ("keys",      "Keys"),
            ("mult",      "Monster Mult."),
            ("next_boss", "Next BOSS"),
        ]
        for key, label in fields:
            row = tk.Frame(status_frm, bg="#111111")
            row.pack(fill=tk.X, padx=5, pady=1)
            tk.Label(row, text=f"{label}:", anchor="w", width=12,
                     bg="#111111", fg="#888888").pack(side=tk.LEFT)
            self.status_labels[key] = tk.Label(
                row, text="-", anchor="e", bg="#111111", fg="#f0f0f0"
            )
            self.status_labels[key].pack(side=tk.RIGHT)

        # ---- Inventory Panel ----
        inv_frm = tk.LabelFrame(parent, text=" Inventory ", fg="#8b0000",
                                bg="#111111", font=("Segoe UI", 10, "bold"))
        inv_frm.pack(fill=tk.X, pady=(0, 4))
        self._inv_inner = tk.Frame(inv_frm, bg="#111111")
        self._inv_inner.pack(fill=tk.X, padx=3, pady=3)
        self.inv_label = tk.Label(self._inv_inner, text="Empty", justify=tk.LEFT,
                                  bg="#111111", fg="#888888", font=("Segoe UI", 8))
        self.inv_label.pack(fill=tk.X)

        # ---- Skills Panel ----
        skills_frm = tk.LabelFrame(parent, text=" Passive Skills ", fg="#8b0000",
                                   bg="#111111", font=("Segoe UI", 10, "bold"))
        skills_frm.pack(fill=tk.X, pady=(0, 4))
        self.skills_label = tk.Label(skills_frm, text="None", justify=tk.LEFT,
                                     bg="#111111", fg="#cccccc")
        self.skills_label.pack(anchor="w", padx=5, pady=3)

        # ---- Buffs Panel ----
        buffs_frm = tk.LabelFrame(parent, text=" Active Buffs ", fg="#8b0000",
                                   bg="#111111", font=("Segoe UI", 10, "bold"))
        buffs_frm.pack(fill=tk.X, pady=(0, 4))
        self.buffs_label = tk.Label(buffs_frm, text="None", justify=tk.LEFT,
                                    bg="#111111", fg="#cccccc")
        self.buffs_label.pack(anchor="w", padx=5, pady=3)

        # ---- Boss floor warning label ----
        self.boss_warning = tk.Label(
            parent, text="", bg="#220000", fg="#ff4444",
            font=("Segoe UI", 10, "bold"), wraplength=260,
            padx=5, pady=3,
        )

        # ---- Game Log ----
        log_frm = tk.LabelFrame(parent, text=" Game Log ", fg="#8b0000",
                                bg="#111111", font=("Segoe UI", 10, "bold"))
        log_frm.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        log_scroll = ttk.Scrollbar(log_frm)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(
            log_frm, height=10, state=tk.DISABLED,
            wrap=tk.WORD, bg="#0a0a0a", fg="#cccccc",
            font=("Consolas", 9), insertwidth=0,
            yscrollcommand=log_scroll.set,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        log_scroll.config(command=self.log_text.yview)

        # Configure log color tags
        tag_colors = {
            "system": "#cccccc", "combat": "#ff6666", "item": "#66ff66",
            "action": "#6666ff", "warning": "#ff9900", "exp": "#ffcc00",
            "level": "#00ccff",   "skill": "#cc66ff",  "heal": "#00ff99",
            "gold": "#ffcc00",   "shop": "#ff9900", "buff": "#9370db",
        }
        for tag, color in tag_colors.items():
            self.log_text.tag_config(tag, foreground=color)

        # ---- Legend ----
        legend_frm = tk.LabelFrame(parent, text=" Legend ", fg="#8b0000",
                                   bg="#111111", font=("Segoe UI", 10, "bold"))
        legend_frm.pack(fill=tk.X)
        legend_items = [
            ("@", self.COLORS["player"], "You"),
            ("#", self.COLORS["wall"], "Wall"),
            (".", self.COLORS["floor"], "Floor"),
            ("g/o/T/D", self.COLORS["monster"], "Monsters"),
            ("B", self.COLORS["boss"], "BOSS"),
            ("M", self.COLORS["merchant"], "Merchant"),
            ("+!*$k", self.COLORS["item"], "Items"),
            ("=", self.COLORS["door"], "Door"),
            (">", self.COLORS["stairs"], "Stairs"),
        ]
        for ch, color, name in legend_items:
            row = tk.Frame(legend_frm, bg="#111111")
            row.pack(fill=tk.X, padx=5)
            tk.Label(row, text=f" {ch} ", bg="#111111", fg=color,
                     font=("Consolas", 9, "bold")).pack(side=tk.LEFT)
            tk.Label(row, text=name, bg="#111111", fg="#888888",
                     font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(5, 0))

    # ================================================================
    #  EVENT BINDINGS
    # ================================================================

    def _bind_events(self):
        self.master.bind("<KeyPress>", self._on_key)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_hover)
        # ESC to close modals
        self.master.bind("<Escape>", self._on_esc)
        # Ctrl+S: manual save; Ctrl+L: manual load
        self.master.bind("<Control-s>", lambda e: self._manual_save())
        self.master.bind("<Control-S>", lambda e: self._manual_save())
        self.master.bind("<Control-l>", lambda e: self._manual_load())
        self.master.bind("<Control-L>", lambda e: self._manual_load())

    def _on_key(self, event):
        # Space: toggle auto-play (always works)
        if event.keysym == "space":
            self._toggle_auto_play()
            return

        # P: print / export the current map (ASCII + xlsx + PNG)
        if event.keysym in ("p", "P"):
            self._print_map()
            return

        # Speed control during auto-play
        if event.keysym == "plus" or event.keysym == "equal":
            self._change_speed()
            return
        if event.keysym == "minus":
            self._change_speed()
            return

        if not self.world.running or self._modal or self.world.auto_play:
            return
        key_map = {
            "Up": (0, -1), "w": (0, -1), "W": (0, -1),
            "Down": (0, 1),  "s": (0, 1),  "S": (0, 1),
            "Left": (-1, 0), "a": (-1, 0), "A": (-1, 0),
            "Right": (1, 0),  "d": (1, 0),  "D": (1, 0),
        }
        if key := key_map.get(event.keysym):
            self.world.move_player(*key)
            self._check_skill_points()
            self._draw()

    def _on_click(self, event):
        if not self.world.running or self._modal or self.world.auto_play:
            return
        gx = event.x // self.cell_size
        gy = event.y // self.cell_size
        x1, y1, x2, y2 = self._view_bounds()
        # gx/gy are *screen* cells; the player position is a *world* cell.
        # Comparing them directly made every click resolve to one fixed
        # direction; translate to world coordinates first.
        ax, ay = x1 + gx, y1 + gy
        px, py = self.world.get_player_position()
        ddx, ddy = ax - px, ay - py
        dx = max(-1, min(1, ddx)) if abs(ddx) > abs(ddy) else 0
        dy = max(-1, min(1, ddy)) if abs(ddy) >= abs(ddx) else 0
        # Only allow single-step moves via click (or diagonal if exactly diagonal)
        if dx == 0 and dy == 0:
            return
        self.world.move_player(dx, dy)
        self._check_skill_points()
        self._draw()

    def _on_hover(self, event):
        gx = event.x // self.cell_size
        gy = event.y // self.cell_size
        x1, y1, x2, y2 = self._view_bounds()
        ax, ay = x1 + gx, y1 + gy
        tile = self.world.get_tile(ax, ay)
        if tile:
            parts = []
            if tile.get("monster"):
                m = tile["monster"]
                parts.append(f"[{m['name']}] HP:{m['current_hp']}/{m['hp']} "
                             f"ATK:{m['attack']} DEF:{m['defense']}")
                if m.get("isBoss"):
                    parts.append("*** BOSS ***")
            elif tile.get("item"):
                it = tile["item"]
                parts.append(f"[{it['name']}] Type:{it['type']} Value:{it.get('value','?')}")
            elif tile.get("merchant"):
                parts.append("[Mysterious Merchant] Click adjacent to trade.")
            elif tile.get("door"):
                parts.append("[Locked Door] Need a key.")
            elif tile.get("stairs"):
                parts.append("[Stairs] Go to next floor.")
            elif tile["type"] == "wall":
                parts.append("[Wall]")
            else:
                parts.append("[Floor]")
            self.hover_var.set(f"({ax}, {ay}): {' | '.join(parts)}")
        else:
            self.hover_var.set(f"({ax}, {ay}): Unknown")

    def _on_esc(self, event):
        if self._modal == "shop":
            self._close_shop()
        elif self._modal == "skill":
            self._close_skill_select()

    # ================================================================
    #  AUTO-PLAY (挂机放置)
    # ================================================================

    def _toggle_auto_play(self):
        """Toggle auto-play mode on/off."""
        if self.world.auto_play:
            self._stop_auto_play()
        else:
            self._start_auto_play()

    def _start_auto_play(self):
        """Enable auto-play and begin the game loop."""
        # Close any open modals silently
        if self._modal:
            self._close_modal_silent()

        self.world.auto_play = True
        self.world.running = True
        self._update_auto_btn(on=True)
        self._auto_use_inventory()

        if self.world.player_data.get("skill_points", 0) > 0:
            self._auto_resolve_skill()
        else:
            self._schedule_auto_tick()

    def _stop_auto_play(self):
        """Disable auto-play."""
        self.world.auto_play = False
        if self._auto_job_id:
            self.master.after_cancel(self._auto_job_id)
            self._auto_job_id = None
        self._update_auto_btn(on=False)
        self._draw()

    def _update_auto_btn(self, *, on: bool):
        """Update button appearance for auto-play state."""
        if on:
            self.auto_btn.config(
                text="⏸ 挂机 ON", bg="#8b0000", fg="#ffffff",
                activebackground="#aa0000",
            )
        else:
            self.auto_btn.config(
                text="⚡ 挂机 OFF", bg="#333333", fg="#888888",
                activebackground="#555555",
            )

    def _close_modal_silent(self):
        """Destroy any open modal without side-effects."""
        for attr in ("_shop_dialog", "_skill_dialog"):
            dlg = getattr(self, attr, None)
            if dlg:
                try:
                    dlg.destroy()
                except Exception:
                    pass
        self._modal = None

    def _schedule_auto_tick(self):
        if not self.world.auto_play:
            return
        if self._auto_job_id:
            self.master.after_cancel(self._auto_job_id)
        delay = self.world.config.get("AUTO_MOVE_DELAY_MS", 200)
        self._auto_job_id = self.master.after(delay, self._auto_play_tick)

    def _auto_play_tick(self):
        """One tick of auto-play."""
        if not self.world.auto_play:
            return
        if self.world.game_over:
            self._handle_auto_game_over()
            return

        self._auto_use_inventory()

        move = self.auto_player.get_next_move()
        if move:
            self.world.move_player(*move)

        self._draw()

        if self.world.open_shop:
            self.world.open_shop = False
            self._auto_resolve_shop()
            return

        if self.world.game_over:
            self._handle_auto_game_over()
            return

        if self.world.player_data.get("skill_points", 0) > 0:
            self._auto_resolve_skill()
        else:
            self._schedule_auto_tick()

    def _auto_resolve_skill(self):
        """Auto-pick skills without any popups."""
        available = self.world.get_available_skills(3)
        if not available:
            self.world.player_data["skill_points"] = 0
            self._schedule_auto_tick()
            return

        chosen = self.auto_player.auto_learn_skill(available)
        self.world.learn_skill(chosen)
        self._draw()

        if self.world.player_data.get("skill_points", 0) > 0:
            self._auto_job_id = self.master.after(100, self._auto_resolve_skill)
        else:
            self._schedule_auto_tick()

    def _auto_resolve_shop(self):
        """Auto-buy from shop without any popups."""
        bought = False
        for item in self.auto_player.auto_shop():
            success, _ = self.world.buy_item(item["id"])
            if success:
                bought = True
            if not self.world.auto_play:
                break
        self._draw()
        self._schedule_auto_tick()

    def _auto_use_inventory(self):
        inv: list[dict] = self.world.player_data.get("inventory", [])
        if not inv:
            return
        for i in range(len(inv) - 1, -1, -1):
            if i >= len(self.world.player_data.get("inventory", [])):
                continue
            item = self.world.player_data["inventory"][i]
            if self.auto_player.should_use_inventory_item(item):
                self.world.use_inventory_item(i)

    def _handle_auto_game_over(self):
        """Seamless auto-restart — never stops the auto-play loop."""
        if not self.world.auto_play:
            return

        # Create fresh world while keeping auto_play ON
        self.world = GameWorld()
        self.auto_player = AutoPlayer(self.world)
        self.world.auto_play = True
        self.world.running = True
        self._modal = None

        # Reset speed display if needed
        self.speed_label.config(text=f"{self.world.config.get('AUTO_MOVE_DELAY_MS', 200)}ms")

        self._draw()
        self._schedule_auto_tick()

    def _change_speed(self):
        """Cycle through auto-play speed levels."""
        if not self.world.auto_play:
            return
        current = self.world.config.get("AUTO_MOVE_DELAY_MS", 200)
        speeds = [400, 200, 100, 50, 10]
        try:
            idx = speeds.index(current)
            next_idx = (idx + 1) % len(speeds)
        except ValueError:
            next_idx = 0
        new_speed = speeds[next_idx]
        self.world.config["AUTO_MOVE_DELAY_MS"] = new_speed
        self.speed_label.config(text=f"{new_speed}ms")

    # ================================================================
    #  SYSTEM TRAY
    # ================================================================

    def _setup_tray(self):
        """Create and start the system tray icon (runs in background thread)."""
        try:
            from PIL import Image, ImageDraw
            import pystray
            from pystray import MenuItem, Icon

            # Build a simple 64x64 RGBA icon
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rectangle([12, 12, 52, 52], fill=(139, 0, 0, 255))
            d.text((22, 16), "T", fill=(255, 255, 255, 255))

            def _restore(icon, item):
                self.master.after(0, self._restore_from_tray)

            def _toggle_auto(icon, item):
                self.master.after(0, self._toggle_auto_play)

            def _save(icon, item):
                self.master.after(0, lambda: (self.world.save_game(),
                                              messagebox.showinfo("存档", "游戏已保存")))

            def _save_exit(icon, item):
                self.master.after(0, self._exit_and_save)

            menu = pystray.Menu(
                MenuItem("恢复窗口", _restore),
                MenuItem("切换挂机", _toggle_auto),
                pystray.Menu.SEPARATOR,
                MenuItem("保存进度", _save),
                MenuItem("退出并存档", _save_exit),
            )
            self._tray_icon = Icon("Town", img, "Magic Tower", menu)
            self._tray_icon.run_detached()
        except Exception as e:
            print(f"[Tray] init failed: {e}")
            self._tray_icon = None

    def _hide_to_tray(self):
        """Hide main window and show tray icon."""
        self.master.withdraw()
        if not getattr(self, "_tray_icon", None):
            self._setup_tray()
        elif not self._tray_icon.visible:
            self._setup_tray()

    def _restore_from_tray(self):
        """Restore window from tray (called from tray menu or after tray icon stop)."""
        self.master.deiconify()
        self.master.lift()
        self.master.focus_force()
        if getattr(self, "_tray_icon", None):
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None

    def _exit_and_save(self):
        """Save game, stop tray, then destroy window."""
        self.world.save_game()
        if getattr(self, "_tray_icon", None):
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.master.destroy()

    def _on_closing(self):
        """Window X button: minimize to tray instead of closing."""
        # Auto-save before hiding
        self.world.save_game()
        self._hide_to_tray()

    # ================================================================
    #  MANUAL SAVE / LOAD
    # ================================================================

    def _manual_save(self):
        """Ctrl+S: manual save."""
        ok = self.world.save_game()
        if ok:
            self.world.add_log("手动存档成功", "system")
            self._draw()
        else:
            messagebox.showerror("存档失败", "无法写入存档文件。")

    def _print_map(self):
        """P: print the map to console and export xlsx + PNG."""
        try:
            from game.map_print import export_map
        except Exception as exc:  # pragma: no cover - import guard
            messagebox.showerror("地图导出失败", f"无法加载 map_print：{exc}")
            return

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            res = export_map(self.world, outdir=os.path.join(root, "output"),
                             quiet=True)
        except Exception as exc:
            messagebox.showerror("地图导出失败", str(exc))
            return

        # No console dump here: the GUI already reports the export in its log
        # panel (and ``export_map`` prints only when run from the CLI).
        self.world.add_log(
            f"地图已导出 {res['cols']}x{res['rows']}（{res['engine']}）"
            f"-> output/{os.path.basename(res['png'])}", "system")
        self._draw()

    def _manual_load(self):
        """Ctrl+L: prompt load game."""
        if self.world.auto_play:
            messagebox.showwarning("提示", "请先停止挂机再读档。")
            return
        if not GameWorld.save_exists():
            messagebox.showinfo("无存档", "未找到存档文件。")
            return
        if messagebox.askyesno("读档", "读档将覆盖当前进度，是否继续？"):
            new_world = GameWorld.load_game()
            if new_world:
                self.world = new_world
                self.auto_player = AutoPlayer(new_world)
                self.world.running = True
                self._modal = None
                self._draw()
                self.world.add_log("读档成功", "system")
                self._draw()
            else:
                messagebox.showerror("读档失败", "无法加载存档文件。")

    # ================================================================
    #  RENDERING
    # ================================================================

    def _draw(self):
        self._draw_map()
        self._update_status()
        self._update_inventory()
        self._update_skills()
        self._update_buffs()
        self._update_log()
        self._update_boss_warning()
        self._update_progress()

        # Auto-open shop modal if flag is set
        if self.world.open_shop:
            self.world.open_shop = False
            if self.world.auto_play:
                self._auto_resolve_shop()
            else:
                self._show_shop_modal()

        # Check game over
        if self.world.game_over:
            self._show_game_over()

    def _view_bounds(self):
        """Camera box, recentred only when the player leaves the dead zone.

        The viewport used to be pinned to the player, so *every* step scrolled
        it and dirtied all 861 cells (~90 ms/turn).  With a dead zone most
        steps only repaint the two cells the player swapped between; the
        occasional recentre costs one full frame but happens once every
        ``CAMERA_DEADZONE`` steps of straight-line travel.
        """
        px, py = self.world.get_player_position()
        hw = self.world.config.get("SCREEN_WIDTH", 41) // 2
        hh = self.world.config.get("SCREEN_HEIGHT", 21) // 2
        dz = int(self.world.config.get("CAMERA_DEADZONE", 4))
        cx, cy = self._cam
        floor = self.world.current_floor
        if (cx is None or self._cam_floor != floor
                or abs(px - cx) > dz or abs(py - cy) > dz):
            cx, cy = px, py
            self._cam = (cx, cy)
            self._cam_floor = floor
        return (cx - hw, cy - hh, cx + hw, cy + hh)

    def _draw_map(self):
        """Render the visible map area on the Canvas.

        Perf: the canvas is a fixed-size grid, so items are created **once**
        and then mutated via ``itemconfigure``.  Rebuilding them every frame
        (``delete("all")`` + ~4300 ``create_*`` calls) cost ~135 ms per redraw
        (~7 fps).  Reusing them keeps a redraw in the low single-digit ms.
        """
        x1, y1, x2, y2 = self._view_bounds()
        self.world.ensure_visible_tiles_generated((x1, y1, x2, y2))

        cs = self.cell_size
        cols = x2 - x1 + 1
        rows = y2 - y1 + 1
        px, py = self.world.get_player_position()

        # (Re)build the item pool only when the visible size changes.
        if self._cell_pool is None or self._cell_pool_size != (cols, rows):
            self.canvas.delete("all")
            self._cell_pool = []
            self._cell_state = []
            self._cell_bg_tag = []
            self._cell_fg_tag = []
            for j in range(rows):
                row_items, row_state, bg_tags, fg_tags = [], [], [], []
                for i in range(cols):
                    sx, sy = i * cs, j * cs
                    bg_tag = f"c{j}_{i}b"
                    fg_tag = f"c{j}_{i}f"
                    # Outline-less on purpose: 861 outlined rects cost ~20 ms
                    # per full repaint.  The grid is a static overlay instead.
                    rect = self.canvas.create_rectangle(
                        sx, sy, sx + cs, sy + cs,
                        fill=self.COLORS["floor"], outline="", width=0,
                        tags=(bg_tag,))
                    text = self.canvas.create_text(
                        sx + cs // 2, sy + cs // 2, text="",
                        fill=self.COLORS["text"],
                        font=self._cell_font, tags=(fg_tag,),
                        state=tk.HIDDEN)
                    row_items.append((rect, text))
                    row_state.append(None)
                    bg_tags.append(bg_tag)
                    fg_tags.append(fg_tag)
                self._cell_pool.append(row_items)
                self._cell_state.append(row_state)
                self._cell_bg_tag.append(bg_tags)
                self._cell_fg_tag.append(fg_tags)
            # Static grid: cols+1 / rows+1 lines instead of a stroke per cell.
            for i in range(cols + 1):
                self.canvas.create_line(
                    i * cs, 0, i * cs, rows * cs,
                    fill="#2b2b2b", tags=("grid",))
            for j in range(rows + 1):
                self.canvas.create_line(
                    0, j * cs, cols * cs, j * cs,
                    fill="#2b2b2b", tags=("grid",))
            self._cell_pool_size = (cols, rows)

        pending = []
        for j, y in enumerate(range(y1, y2 + 1)):
            for i, x in enumerate(range(x1, x2 + 1)):
                tile = self.world.get_tile(x, y)

                if x == px and y == py:
                    pending.append(("#202020", "@", self.COLORS["player"], i, j))
                    continue

                if tile is None:
                    pending.append(("#111111", " ", self.COLORS["text"], i, j))
                    continue

                ttype = tile.get("type", "floor")

                if ttype == "wall":
                    char, color = "#", self.COLORS["wall"]
                elif tile.get("monster"):
                    m = tile["monster"]
                    color = (self.COLORS["boss"] if m.get("isBoss")
                             else self.COLORS["monster"])
                    char = m["char"]
                elif tile.get("merchant"):
                    char, color = "M", self.COLORS["merchant"]
                elif tile.get("item"):
                    char, color = tile["item"]["char"], self.COLORS["item"]
                elif tile.get("door"):
                    char, color = "=", self.COLORS["door"]
                elif tile.get("stairs"):
                    char, color = ">", self.COLORS["stairs"]
                else:
                    char, color = ".", self.COLORS["floor"]

                pending.append((self._bg_for(char), char, self._fg_for(char, color), i, j))

        self._flush(pending)

    def _flush(self, pending: list):
        """Push a frame's cell changes to Tcl in a handful of calls.

        Cells are bucketed by appearance; each bucket gets a transient shared
        tag which is then configured in one ``itemconfigure`` call.  A full
        viewport scroll (every cell dirty) costs ~15 calls instead of 8600
        individual ones — 130 ms down to a few ms.

        Note: Tk only accepts a *single* tag or id here, and a space-joined
        tag string is NOT split (it silently matches nothing), hence the
        temporary group tag.
        """
        if not pending:
            return

        groups: dict[tuple, list[str]] = {}
        bgs: dict[str, list[str]] = {}
        state = self._cell_state
        for bg, char, color, i, j in pending:
            key = (bg, char, color)
            if state[j][i] == key:
                continue
            state[j][i] = key
            groups.setdefault(key, []).append(self._cell_fg_tag[j][i])
            bgs.setdefault(bg, []).append(self._cell_bg_tag[j][i])

        canvas = self.canvas
        tk_call = canvas.tk.call
        w = canvas._w

        def bulk(group: str, tags: list[str], *opts):
            canvas.tk.call(w, "addtag", group, "withtag", " || ".join(tags))
            try:
                tk_call(w, "itemconfigure", group, *opts)
            finally:
                canvas.dtag("all", group)

        for n, ((bg, char, color), tags) in enumerate(groups.items()):
            # Blank cells (unexplored void) hide their glyph so Tk skips it.
            st = tk.HIDDEN if char == " " else tk.NORMAL
            bulk(f"_fg{n}", tags, "-text", char, "-fill", color, "-state", st)
        for n, (bg, tags) in enumerate(bgs.items()):
            bulk(f"_bg{n}", tags, "-fill", bg)

    def _bg_for(self, char: str) -> str:
        """Background tint behind a glyph.

        Walls and floors are painted with their own body colour (they *are*
        the background); entities sit on a dark tile so their glyph pops.
        """
        if char == "#":
            return self.COLORS["wall"]
        if char == ".":
            return self.COLORS["floor"]
        return "#202020"

    def _fg_for(self, char: str, color: str) -> str:
        """Glyph colour, kept legible against the tile behind it.

        Floor and wall were previously drawn in their own body colour, which
        made the glyph invisible (dark grey on dark grey); bump them to
        dedicated, readable tones.
        """
        if char == "#":
            return "#1a1a1a"
        if char == ".":
            return "#6f6f6f"
        return color

    # ================================================================
    #  STATUS PANEL UPDATE
    # ================================================================

    def _update_status(self):
        pd = self.world.player_data
        w = self.world
        labels = self.status_labels

        labels["level"].config(text=str(pd["level"]))
        labels["hp"].config(text=f'{pd["hp"]}/{pd["max_hp"]}')
        labels["exp"].config(text=f'{pd["exp"]}/{pd["exp_to_next"]}')
        labels["skill_pts"].config(text=str(pd["skill_points"]))
        labels["gold"].config(text=str(pd["gold"]))
        labels["attack"].config(text=str(pd["attack"]))
        labels["defense"].config(text=str(pd["defense"]))
        labels["floor"].config(text=str(w.current_floor))
        labels["keys"].config(text=str(pd["keys"]))
        mult = w.monster_multiplier()
        labels["mult"].config(text=f"{mult:.2f}x")
        next_boss = math.ceil(w.current_floor / cfg.BOSS_FLOOR_INTERVAL) * cfg.BOSS_FLOOR_INTERVAL
        labels["next_boss"].config(text=f"Floor {next_boss}")

    def _update_inventory(self):
        """Rebuild inventory panel with Use buttons (only when it changed).

        Rebuilding the widget tree every frame cost ~7 ms of Tk layout work
        for a panel that usually does not change between moves.
        """
        inv: list[dict] = self.world.player_data.get("inventory", [])
        sig = tuple((it.get("name"), it.get("desc"), it.get("type")) for it in inv)
        if sig == self._inv_sig:
            return
        self._inv_sig = sig

        # Clear old widgets
        for w in self._inv_inner.winfo_children():
            w.destroy()

        if not inv:
            self.inv_label = tk.Label(self._inv_inner, text="Empty", justify=tk.LEFT,
                                      bg="#111111", fg="#888888", font=("Segoe UI", 8))
            self.inv_label.pack(fill=tk.X)
            return

        for i, item in enumerate(inv):
            row = tk.Frame(self._inv_inner, bg="#222222")
            row.pack(fill=tk.X, pady=1)

            info = tk.Frame(row, bg="#222222")
            info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

            itype = item.get("type", "")
            color = {"consumable": "#00ff99", "permanent": "#ffcc00",
                     "key": "#66ff66", "buff": "#9370db"}.get(itype, "#cccccc")

            tk.Label(info, text=item["name"], bg="#222222", fg=color,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            tk.Label(info, text=item.get("desc", ""), bg="#222222", fg="#888888",
                     font=("Segoe UI", 7)).pack(anchor="w")

            btn = tk.Button(row, text="Use", font=("Segoe UI", 7, "bold"),
                           bg="#8b0000", fg="white", padx=4, pady=0,
                           command=lambda idx=i: self._do_use_inventory(idx))
            btn.pack(side=tk.RIGHT, padx=4)

        self._inv_inner.update_idletasks()

    def _do_use_inventory(self, index: int):
        success, msg = self.world.use_inventory_item(index)
        if success:
            self._draw()
        else:
            self.world.add_log(msg, "warning")
            self._draw()

    def _update_skills(self):
        if not self.world.learned_skills:
            self.skills_label.config(text="None")
            return
        lines = [f"★ {s['name']} Lv.{s['level']}/{s['max_level']}"
                 for s in self.world.learned_skills]
        self.skills_label.config(text="\n".join(lines))

    def _update_buffs(self):
        buffs = self.world.active_buffs
        if not buffs:
            self.buffs_label.config(text="None")
            return
        lines = []
        for b in buffs:
            eff = b["effects"]
            desc = ""
            if eff.get("attack_multiplier"):
                desc = f"ATK x{eff['attack_multiplier']}"
            elif eff.get("defense_multiplier"):
                desc = f"DEF x{eff['defense_multiplier']}"
            elif eff.get("exp_multiplier"):
                desc = f"EXP x{eff['exp_multiplier']}"
            elif eff.get("gold_multiplier"):
                desc = f"Gold x{eff['gold_multiplier']}"
            lines.append(f"{b['name']}: {desc} ({b['duration']} fights left)")
        self.buffs_label.config(text="\n".join(lines))

    def _update_log(self):
        """Repaint the log only when new lines arrived."""
        entries = self.world.log_entries
        if len(entries) == self._log_count:
            return
        self._log_count = len(entries)

        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        for msg, mtype in entries:
            self.log_text.insert(tk.END, f"{msg}\n", mtype)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _update_boss_warning(self):
        if self.world.current_floor % cfg.BOSS_FLOOR_INTERVAL == 0:
            self.boss_warning.config(
                text=f"⚠ FLOOR {self.world.current_floor} — BOSS ROOM!\n"
                     f"Defeat the BOSS to proceed!"
            )
            self.boss_warning.pack(fill=tk.X, pady=(0, 5))
        else:
            self.boss_warning.pack_forget()

    def _update_progress(self):
        self.world.update_progress()
        self.progress_var.set(self.world.progress_value)
        self.progress_label.config(text=self.world.progress_text)

    # ================================================================
    #  MODALS
    # ================================================================

    def _check_skill_points(self):
        pd = self.world.player_data
        if pd["skill_points"] > 0:
            self._show_skill_modal()

    def _show_skill_modal(self):
        """Open skill selection dialog."""
        available = self.world.get_available_skills(3)
        if not available:
            return

        self._modal = "skill"
        self.world.running = False

        dialog = tk.Toplevel(self.master)
        dialog.title("Choose Passive Skill")
        dialog.geometry("500x400")
        dialog.configure(bg="#111111")
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_skill_select(dialog))

        pts_label = tk.Label(
            dialog, text=f"You have {self.world.player_data['skill_points']} skill point(s)",
            bg="#111111", fg="#ff9900", font=("Segoe UI", 11, "bold"),
        )
        pts_label.pack(pady=10)

        btn_frame = tk.Frame(dialog, bg="#111111")
        btn_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=10)

        for skill_def in available:
            learned = next(
                (ls for ls in self.world.learned_skills if ls["id"] == skill_def["id"]),
                None,
            )
            cur_lv = learned["level"] if learned else 0

            frm = tk.Frame(btn_frame, bg="#222222", cursor="hand2",
                          highlightbackground="#444444", highlightthickness=1)
            frm.pack(fill=tk.X, pady=5)
            frm.bind("<Button-1>", lambda e, sd=skill_def, d=dialog: self._pick_skill(sd, d))

            tk.Label(frm, text=skill_def["name"], bg="#222222", fg="#ff9900",
                     font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
            tk.Label(frm, text=skill_def["desc"], bg="#222222", fg="#aaaaaa",
                     font=("Segoe UI", 9)).pack(anchor="w", padx=10)
            tk.Label(frm, text=f"Current Level: {cur_lv}/{skill_def['max_level']}",
                     bg="#222222", fg="#888888", font=("Segoe UI", 9)).pack(
                         anchor="w", padx=10, pady=(0, 8)
                     )

        close_btn = tk.Button(dialog, text="Skip (ESC)", command=lambda: self._close_skill_select(dialog),
                              bg="#333333", fg="#cccccc")
        close_btn.pack(pady=5)

        self._skill_dialog = dialog

    def _pick_skill(self, skill_def, dialog):
        self.world.learn_skill(skill_def)
        self._close_skill_select(dialog)
        # If still has points, show again
        if self.world.player_data["skill_points"] > 0:
            self.master.after(200, self._show_skill_modal)
        else:
            self.world.running = True
            self._draw()

    def _close_skill_select(self, dialog=None):
        dlg = getattr(self, "_skill_dialog", None) or dialog
        if dlg:
            try:
                dlg.destroy()
            except Exception:
                pass
        self._modal = None
        self.world.running = True

    # ---- Shop Modal ----

    def _show_shop_modal(self):
        self._modal = "shop"
        self.world.running = False

        dialog = tk.Toplevel(self.master)
        dialog.title("Mysterious Merchant")
        dialog.geometry("450x550")
        dialog.configure(bg="#111111")
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_shop())

        # Gold display
        gold_lbl = tk.Label(
            dialog, text=f"Your Gold: {self.world.player_data['gold']}",
            bg="#222222", fg="#ffcc00", font=("Segoe UI", 12, "bold"),
            padx=10, pady=5,
        )
        gold_lbl.pack(fill=tk.X, padx=20, pady=(15, 5))

        # Scrollable item list
        canvas_frame = tk.Frame(dialog, bg="#111111")
        canvas_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=5)

        scroll = ttk.Scrollbar(canvas_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        item_canvas = tk.Canvas(canvas_frame, bg="#111111", highlightthickness=0,
                                 yscrollcommand=scroll.set)
        item_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=item_canvas.yview)

        inner_frame = tk.Frame(item_canvas, bg="#111111")
        item_canvas.create_window((0, 0), window=inner_frame, anchor="nw")
        inner_frame.bind("<Configure>", lambda e: item_canvas.configure(scrollregion=item_canvas.bbox("all")))

        for item in self.world.shop_items:
            if item["stock"] <= 0:
                continue

            can_afford = self.world.player_data["gold"] >= item["price"]

            item_row = tk.Frame(inner_frame, bg="#222222", padx=10, pady=8)
            item_row.pack(fill=tk.X, pady=3)

            info = tk.Frame(item_row, bg="#222222")
            info.pack(side=tk.LEFT, fill=tk.X, expand=True)

            tk.Label(info, text=item["name"], bg="#222222", fg="#ffcc00",
                     font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(info, text=item["desc"], bg="#222222", fg="#aaaaaa",
                     font=("Segoe UI", 8)).pack(anchor="w")
            tk.Label(info, text=f"Price: {item['price']}g  |  Stock: {item['stock']}",
                     bg="#222222", fg="#888888", font=("Segoe UI", 8)).pack(anchor="w")

            buy_btn = tk.Button(
                item_row, text="Buy", command=lambda iid=item["id"]: self._do_buy(iid, dialog),
                state=tk.NORMAL if can_afford else tk.DISABLED,
                bg="#444444" if can_afford else "#222222",
                fg="#cccccc" if can_afford else "#555555",
            )
            buy_btn.pack(side=tk.RIGHT, anchor="center", padx=5)

        exit_btn = tk.Button(dialog, text="Leave Shop", command=self._close_shop,
                             bg="#8b0000", fg="white", font=("Segoe UI", 10, "bold"))
        exit_btn.pack(pady=10)

        self._shop_dialog = dialog

    def _do_buy(self, item_id: int, dialog):
        success, msg = self.world.buy_item(item_id)
        if success:
            self.world.add_log(msg, "shop")
            # Refresh gold label & rebuild shop
            dialog.destroy()
            self._show_shop_modal()
        else:
            self.world.add_log(msg, "warning")
            messagebox.showwarning("Cannot Buy", msg)

    def _close_shop(self):
        if hasattr(self, "_shop_dialog") and self._shop_dialog:
            try:
                self._shop_dialog.destroy()
            except Exception:
                pass
        self._modal = None
        self.world.running = True
        self._draw()

    # ---- Game Over ----

    def _show_game_over(self):
        self.world.running = False
        # Auto-play never shows dialogs — seamless restart
        if self.world.auto_play:
            self._handle_auto_game_over()
            return
        result = messagebox.askyesno(
            "Game Over",
            f"You were defeated on Floor {self.world.current_floor}.\n\n"
            f"Final Level: {self.world.player_data['level']}\n"
            f"Restart?",
        )
        if result:
            self._restart_game()
        else:
            self.master.quit()

    def _restart_game(self):
        """Re-create the world. Preserves auto-play state if active."""
        was_auto = self.world.auto_play
        if self._auto_job_id:
            self.master.after_cancel(self._auto_job_id)
            self._auto_job_id = None

        # Destroy lingering modals
        self._close_modal_silent()

        self.world = GameWorld()
        self.auto_player = AutoPlayer(self.world)
        self._modal = None

        if was_auto:
            self.world.auto_play = True
            self.world.running = True
        else:
            self._update_auto_btn(on=False)
            self.speed_label.config(text="200ms")
            if "AUTO_MOVE_DELAY_MS" in self.world.config:
                self.world.config["AUTO_MOVE_DELAY_MS"] = 200

        self._draw()


def main():
    import tkinter.messagebox as msgbox

    root = tk.Tk()
    root.withdraw()  # hide while building
    root.title("Python Magic Tower - ECS Edition")

    # Check for existing save
    world = None
    if GameWorld.save_exists():
        try:
            ok = msgbox.askyesno(
                "发现存档",
                "检测到已有存档，是否加载？\n\n"
                "是：加载存档继续游戏\n"
                "否：开始新游戏（原有存档将被覆盖）",
            )
            if ok:
                loaded = GameWorld.load_game()
                if loaded:
                    world = loaded
                else:
                    msgbox.showerror("读档失败", "无法加载存档，将开始新游戏。")
                    world = GameWorld()
            else:
                world = GameWorld()
        except KeyboardInterrupt:
            raise  # let the top-level handler deal with it
        except Exception as e:
            print(f"Load prompt error: {e}")
            world = GameWorld()
    else:
        world = GameWorld()

    app = GameUI(root, world)

    # Center the window (geometry already set in _setup_ui)
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"+{x}+{y}")
    root.deiconify()  # show centered

    try:
        root.mainloop()
    finally:
        # Auto-save when mainloop exits (window closed)
        try:
            world.save_game()
        except Exception:
            pass


if __name__ == "__main__":
    main()
