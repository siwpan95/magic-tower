"""Death forensics: replay a balance run and dump the last N steps before death.

Usage:
    E:/Python314/python.exe tools/_probe_death.py --steps 6000 --seed 7 --window 30
"""

from __future__ import annotations

import argparse
import collections
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--window", type=int, default=30)
    args = ap.parse_args()

    random.seed(args.seed)
    from game.world import GameWorld
    from game.auto_player import AutoPlayer

    world = GameWorld()
    world.generate_initial_map()
    bot = AutoPlayer(world)

    ring: collections.deque = collections.deque(maxlen=args.window)
    floor_turns = collections.Counter()

    for step in range(args.steps):
        if world.game_over:
            break
        world.ensure_visible_tiles_generated()
        px, py = world.get_player_position()
        pd = world.player_data
        # snapshot adjacent monsters
        adj = []
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            t = world.get_tile(px + dx, py + dy)
            if t and t.get("monster"):
                m = t["monster"]
                adj.append((dx, dy, m.get("name"), m.get("current_hp"),
                            m.get("attack"), m.get("defense")))
        ring.append({
            "step": step, "floor": world.current_floor,
            "pos": (px, py), "hp": pd["hp"], "max_hp": pd["max_hp"],
            "atk": pd["attack"], "def": pd["defense"],
            "gold": pd["gold"], "adj": adj,
        })
        move = bot.get_next_move()
        src = "?"
        if move:
            world.move_player(*move)
        floor_turns[world.current_floor] += 1

    print(f"seed={args.seed} steps={args.steps} game_over={world.game_over} "
          f"floor={world.current_floor}")
    print(f"player={world.player_data}")
    print(f"turns per floor={dict(floor_turns)}")
    print("---- last steps ----")
    for r in ring:
        line = (f"s{r['step']:>5} F{r['floor']:<3} pos={r['pos']} "
                f"hp={r['hp']}/{r['max_hp']} atk={r['atk']} def={r['def']}")
        if r["adj"]:
            line += "  adj=" + ";".join(
                f"({dx},{dy}){n} hp={hp} atk={a} def={d}"
                for dx, dy, n, hp, a, d in r["adj"])
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
