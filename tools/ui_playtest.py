"""Drive a real Tk window and screenshot it — hands-on verification.

The window is a genuine ``GameUI``; inputs go through ``event_generate`` so the
real ``<KeyPress>`` → ``_on_key`` → ``world.move_player`` path runs exactly as a
human's would (no direct world mutation).

Usage:
    E:/Python314/python.exe tools/ui_playtest.py [--moves 120] [--shots 6]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUTDIR = os.path.join(ROOT, "output", "playtest")


def grab(win, path):
    """Screenshot the Tk toplevel. Returns the output path or None."""
    win.update_idletasks()
    win.update()
    try:
        from PIL import ImageGrab
        x = win.winfo_rootx()
        y = win.winfo_rooty()
        w = win.winfo_width()
        h = win.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
        return path
    except Exception as exc:              # pragma: no cover
        print(f"  [shot] FAILED {path}: {exc}")
        return None


def snapshot_state(world):
    p = world.player_data
    return {
        "floor": world.current_floor,
        "hp": f"{p.get('hp')}/{p.get('max_hp')}",
        "level": p.get("level"),
        "gold": p.get("gold"),
        "pos": (p.get("x"), p.get("y")),
        "tiles": len(world.map_data),
        "alive": world.running,
    }


KEYS = ["Right", "Right", "Down", "Down", "Left", "Up"]

# A human never holds one direction into a wall for 50 frames.  When a step
# does not move the player, rotate to the next direction — otherwise the run
# wedges in a corner and the test measures nothing.
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]
DIR_KEYS = {0: "Right", 1: "Down", 2: "Left", 3: "Up"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--moves", type=int, default=150)
    ap.add_argument("--shots", type=int, default=6)
    ap.add_argument("--keydelay", type=float, default=0.012)
    args = ap.parse_args()

    os.makedirs(OUTDIR, exist_ok=True)

    import tkinter as tk
    from game.world import GameWorld
    from ui.tkinter_ui import GameUI

    world = GameWorld()
    world.generate_initial_map()

    root = tk.Tk()
    root.title("Magic Tower — playtest")
    ui = GameUI(root, world)
    root.geometry("1240x760+40+40")
    root.update()

    print("=" * 66)
    print("UI PLAYTEST — real Tk window, keyboard events only")
    print("=" * 66)
    start = snapshot_state(world)
    print(f"  start   {start}")

    shots = []
    frames = []
    shot_every = max(1, args.moves // max(1, args.shots))
    t0 = time.perf_counter()

    def dirty_cells(ui):
        """How many grid slots actually changed on the last frame."""
        return sum(1 for row in ui._cell_state for s in row if s is not None)

    di = 0
    dirty = []
    for i in range(args.moves):
        if not world.running:
            print(f"  died at move {i}")
            break

        before = (world.player_data.get("x"), world.player_data.get("y"))
        key = DIR_KEYS[di]
        # Snapshot the paint cache so we can count truly-changed cells.
        prev = [row[:] for row in ui._cell_state]
        ft0 = time.perf_counter()
        root.event_generate(f"<KeyPress-{key}>")
        root.update_idletasks()
        frames.append((time.perf_counter() - ft0) * 1000)
        dirty.append(sum(1 for r_old, r_new in zip(prev, ui._cell_state)
                         for a, b in zip(r_old, r_new) if a != b))
        after = (world.player_data.get("x"), world.player_data.get("y"))
        if after == before:
            # blocked: try the next direction (feels like a person probing)
            di = (di + 1) % 4

        if i % shot_every == 0 or i == args.moves - 1:
            p = os.path.join(OUTDIR, f"shot_{len(shots):02d}.png")
            if grab(root, p):
                shots.append(p)
                print(f"  move {i:>3} {snapshot_state(world)}  -> {os.path.basename(p)}")

    elapsed = time.perf_counter() - t0
    end = snapshot_state(world)
    print(f"  (keyboard segment end: {end})")

    # --- press P: the new map printing ---
    t_p = time.perf_counter()
    root.event_generate("<KeyPress-p>")
    root.update()
    p_time = time.perf_counter() - t_p
    p_shot = os.path.join(OUTDIR, "after_print.png")
    grab(root, p_shot)
    shots.append(p_shot)

    # --- space: auto-play toggle ---
    root.event_generate("<KeyPress-space>")
    root.update()
    auto_on = world.auto_play
    time.sleep(0.8)
    root.update()
    auto_shot = os.path.join(OUTDIR, "autoplay.png")
    grab(root, auto_shot)
    shots.append(auto_shot)
    root.event_generate("<KeyPress-space>")   # toggle off
    root.update()

    # --- auto-play endurance segment: let the bot actually PLAY the game
    #     through the real UI (real rendering + real event loop), not just
    #     walk into walls.  Verifies feel end-to-end: fights, loot, shops,
    #     descending, boss floors. ---
    print("-" * 66)
    print("AUTO-PLAY ENDURANCE — bot plays through the real UI")
    world.config["AUTO_MOVE_DELAY_MS"] = 15      # 200 ms/tick is unwatchable
    kills = {"n": 0, "boss": 0}
    _orig_log = world.add_log

    def _counting_log(message, msg_type="system"):
        if message.startswith("Defeated"):
            kills["n"] += 1
        elif message.startswith("DEFEATED BOSS"):
            kills["boss"] += 1
        _orig_log(message, msg_type)

    world.add_log = _counting_log
    root.event_generate("<KeyPress-space>")       # auto on
    root.update()
    t_auto = time.perf_counter()
    auto_moves = 0
    last_pos = None
    last_floor = world.current_floor
    floor_log = []
    while time.perf_counter() - t_auto < 45 and world.running:
        root.update()
        time.sleep(0.004)
        pos = (world.player_data.get("x"), world.player_data.get("y"))
        if pos != last_pos:
            auto_moves += 1
            last_pos = pos
        if world.current_floor != last_floor:
            floor_log.append((world.current_floor,
                              round(time.perf_counter() - t_auto, 1)))
            last_floor = world.current_floor
            p = os.path.join(OUTDIR, f"auto_f{world.current_floor:02d}.png")
            grab(root, p)
            shots.append(p)
    root.event_generate("<KeyPress-space>")       # auto off
    root.update()
    auto_elapsed = time.perf_counter() - t_auto
    print(f"  auto    {auto_moves} moves in {auto_elapsed:.1f}s, "
          f"floor {world.current_floor}, kills {kills['n']}, "
          f"bosses {kills['boss']}, alive={world.running}")
    print(f"  floors  {floor_log}")
    world.add_log = _orig_log

    print("-" * 66)
    print(f"  FINAL   {snapshot_state(world)}")
    print(f"  moves   {args.moves} in {elapsed:.2f}s "
          f"({args.moves / elapsed:.1f} moves/s)")
    if frames:
        fs = sorted(frames)
        avg = sum(fs) / len(fs)
        med = fs[len(fs) // 2]
        p95 = fs[int(len(fs) * 0.95) - 1]
        print(f"  frame   avg {avg:6.2f} ms   median {med:6.2f} ms   "
              f"p95 {p95:6.2f} ms   max {max(fs):6.2f} ms   (n={len(fs)})")
        print(f"  fps     ~{1000 / avg:.0f} avg / ~{1000 / med:.0f} median "
              f"  (60 fps budget = 16.7 ms)")
    if dirty:
        ds = sorted(dirty)
        full = sum(1 for d in dirty if d > 400)
        print(f"  dirty   median {ds[len(ds) // 2]} cells   max {ds[-1]}   "
              f"full-viewport repaints {full}/{len(dirty)} "
              f"(camera recentre)")
    print(f"  P key   map export took {p_time:.2f}s (incl. render)")
    print(f"  auto    toggle -> auto_play={auto_on}")
    print(f"  shots   {len(shots)} -> {OUTDIR}")

    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
