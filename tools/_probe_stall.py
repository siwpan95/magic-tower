"""Stall forensics: run the bot, then dump why it cannot descend.

Usage:
    E:/Python314/python.exe tools/_probe_stall.py --steps 3000 --seed 7
"""

from __future__ import annotations

import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    random.seed(args.seed)
    from game.world import GameWorld
    from game.auto_player import AutoPlayer

    world = GameWorld()
    world.generate_initial_map()
    bot = AutoPlayer(world)
    trace: list = []

    for step in range(args.steps):
        if world.game_over:
            break
        world.ensure_visible_tiles_generated()
        # mirror the UI auto-play tick (same as tools/balance_sim.py)
        inv = world.player_data.get("inventory", [])
        for i in range(len(inv) - 1, -1, -1):
            if i >= len(world.player_data.get("inventory", [])):
                continue
            if bot.should_use_inventory_item(
                    world.player_data["inventory"][i]):
                world.use_inventory_item(i)
        p0 = world.get_player_position()
        hp0 = world.player_data["hp"]
        move = bot.get_next_move()
        if move:
            world.move_player(*move)
        trace.append((step, p0, move, world.get_player_position(),
                      hp0, world.player_data["hp"]))
        if world.open_shop:
            world.open_shop = False
            for item in bot.auto_shop():
                ok, _ = world.buy_item(item["id"])
                if not ok:
                    break
        if world.player_data.get("skill_points", 0) > 0:
            sk = world.get_available_skills(3)
            if sk:
                world.learn_skill(bot.auto_learn_skill(sk) or sk[0])

    pd = world.player_data
    px, py = world.get_player_position()
    print(f"seed={args.seed} steps={args.steps} game_over={world.game_over} "
          f"floor={world.current_floor} pos=({px},{py})")
    print("---- per-position decision over the oscillation cluster ----")
    st = sorted(
        (abs(t["x"] - px) + abs(t["y"] - py), t["x"], t["y"])
        for t in world.map_data.values() if t.get("stairs"))
    for p in [(-6, -10), (-5, -10), (-4, -10), (-3, -10)]:
        sm = bot._stairs_move(p[0], p[1])
        steps = []
        for d, sx, sy in st[:3]:
            s = bot._bfs_step(p[0], p[1], sx, sy, avoid_monsters=False)
            steps.append(f"({sx},{sy}):{s}")
        print(f"  from {p}: _stairs_move={sm}  thru-steps={steps}")
    print("---- last 60 steps (step, from -> move -> to, hp) ----")
    for s, p0, mv, p1, h0, h1 in trace[-60:]:
        dmg = f" -{h0-h1}hp" if h1 < h0 else ""
        print(f"  s{s:>5} {p0} --{mv}--> {p1}{dmg}")
    print(f"player hp={pd['hp']}/{pd['max_hp']} atk={pd['attack']} "
          f"def={pd['defense']} lvl={pd['level']} gold={pd['gold']} "
          f"keys={pd.get('keys')} skill_points={pd.get('skill_points')}")
    print(f"map tiles={len(world.map_data)} "
          f"explore_ratio={len(world.map_data)/600:.2f}")

    stairs = [(t["x"], t["y"]) for t in world.map_data.values()
              if t.get("stairs")]
    print(f"known stairs: {sorted(stairs)}")
    for sx, sy in sorted(stairs, key=lambda s: abs(s[0]-px)+abs(s[1]-py)):
        d = abs(sx - px) + abs(sy - py)
        p_avoid = bot._bfs_step(px, py, sx, sy, avoid_monsters=True)
        p_thru = bot._bfs_step(px, py, sx, sy, avoid_monsters=False)
        verdict = ""
        if p_thru:
            nx, ny = px + p_thru[0], py + p_thru[1]
            t = world.get_tile(nx, ny)
            m = t.get("monster") if t else None
            if m:
                verdict = (f" first-step monster {m['name']} "
                           f"hp={m['current_hp']} atk={m['attack']} "
                           f"def={m['defense']} "
                           f"safe={bot._fight_is_safe(m)}")
        print(f"  stairs ({sx},{sy}) dist={d} "
              f"avoid={'yes' if p_avoid else 'NO'} "
              f"thru={'yes' if p_thru else 'NO'}{verdict}")

    # what does the bot actually return right now?
    mv = bot.get_next_move()
    print(f"next move now: {mv}  engaged={bot._engaged} "
          f"stuck_frames={bot._stuck_frames}")
    sm = bot._stairs_move(px, py)
    print(f"_stairs_move now: {sm}")
    # replicate _stairs_move's per-stairs decision with full diagnostics
    stairs = []
    for tile in world.map_data.values():
        if tile.get("stairs"):
            tx, ty = tile["x"], tile["y"]
            if (tx, ty) != (px, py):
                stairs.append((abs(tx - px) + abs(ty - py), tx, ty))
    stairs.sort()
    for d, sx, sy in stairs:
        step_a = bot._bfs_step(px, py, sx, sy, avoid_monsters=True)
        step_t = bot._bfs_step(px, py, sx, sy, avoid_monsters=False)
        line = f"  stairs ({sx},{sy}) d={d} avoid={step_a} thru={step_t}"
        if step_t and not step_a:
            blk = bot._path_first_monster(px, py, sx, sy)
            if blk is None:
                line += " blocker=NONE -> should ACCEPT"
            else:
                t = world.get_tile(blk[0], blk[1])
                m = t.get("monster") if t else None
                if m:
                    line += (f" blocker=({blk[0]},{blk[1]}) {m['name']} "
                             f"hp={m['current_hp']} atk={m['attack']} "
                             f"def={m['defense']} "
                             f"safe={bot._fight_is_safe(m)}")
                else:
                    line += f" blocker=({blk[0]},{blk[1]}) no-monster?!"
        print(line)
    # safety verdict on every adjacent monster
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        t = world.get_tile(px + dx, py + dy)
        if t and t.get("monster"):
            m = t["monster"]
            print(f"  adjacent monster ({px+dx},{py+dy}) {m['name']} "
                  f"hp={m['current_hp']}/{m['hp']} atk={m['attack']} "
                  f"def={m['defense']} safe={bot._fight_is_safe(m)}")

    # visible safe monsters?
    vm = bot._find_visible_monsters(px, py)
    print(f"visible safe monsters: {vm}")
    items = [(t["x"], t["y"], t["item"].get("name"))
             for t in world.map_data.values() if t.get("item")]
    print(f"items on floor: {items[:12]}")
    merch = [(t["x"], t["y"]) for t in world.map_data.values()
             if t.get("merchant")]
    print(f"merchants: {merch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
