"""Headless balance simulation — drive the real world with the real AutoPlayer.

No Tk, no rendering.  Reports per-floor player growth, kill efficiency and
survival, so monster curves can be calibrated against actual play instead of
guesswork.

Usage:
    E:/Python314/python.exe tools/balance_sim.py [--steps 4000] [--seed 7]
"""

from __future__ import annotations

import argparse
import collections
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def run(steps: int, seed: int) -> dict:
    random.seed(seed)
    from game.world import GameWorld
    from game.auto_player import AutoPlayer

    world = GameWorld()
    world.generate_initial_map()
    bot = AutoPlayer(world)

    # world.log_entries is capped at 50, so an index into it is not stable —
    # wrap add_log instead to count kills reliably.
    _orig_add_log = world.add_log

    def _counting_add_log(message, msg_type="system"):
        if message.startswith("Defeated") or message.startswith("DEFEATED BOSS"):
            kills[world.current_floor] += 1
        _orig_add_log(message, msg_type)

    world.add_log = _counting_add_log

    kills = collections.Counter()
    floors_seen = collections.OrderedDict()
    deaths = 0
    turns_on_floor = collections.Counter()
    hp_at_floor_entry = {}
    hit_turns = 0            # turns where the player took a counter-attack
    dmg_taken = 0
    first_floor_hp_low = None

    last_floor = world.current_floor
    hp_at_floor_entry[last_floor] = world.player_data["hp"]
    log_seen = 0

    for step in range(steps):
        if world.game_over:
            deaths += 1
            break
        # The UI does this every frame; without it only the spawn chunk exists
        # and the bot is trapped in a 20x20 box (measured: 63 unique tiles).
        world.ensure_visible_tiles_generated()

        # --- mirror ui/tkinter_ui.py::_auto_play_tick so the sim measures
        # --- the same bot the player actually gets ---
        # potions/permanents (a Weapon picked up on the floor is equipped
        # immediately in the real game; without this the sim player walks
        # around at base stats while the UI player gears up every floor)
        inv = world.player_data.get("inventory", [])
        for i in range(len(inv) - 1, -1, -1):
            if i >= len(world.player_data.get("inventory", [])):
                continue
            if bot.should_use_inventory_item(
                    world.player_data["inventory"][i]):
                world.use_inventory_item(i)

        before_hp = world.player_data["hp"]
        move = bot.get_next_move()
        if move:
            world.move_player(*move)
        after_hp = world.player_data["hp"]
        if after_hp < before_hp:
            hit_turns += 1
            dmg_taken += before_hp - after_hp

        # stepping on a merchant opens the shop; the UI resolves it without
        # a popup, so the bot's gold actually buys gear here too
        if world.open_shop:
            world.open_shop = False
            for item in bot.auto_shop():
                ok, _ = world.buy_item(item["id"])
                if not ok:
                    break

        # auto-learn skills so growth is not blocked on a modal
        if world.player_data.get("skill_points", 0) > 0:
            sk = world.get_available_skills(3)
            if sk:
                pick = bot.auto_learn_skill(sk)
                if pick:
                    world.learn_skill(pick)
                else:
                    world.learn_skill(sk[0])

        f = world.current_floor
        turns_on_floor[f] += 1
        if f != last_floor:
            floors_seen[last_floor] = dict(
                turns=turns_on_floor[last_floor],
                atk=world.player_data["attack"],
                defense=world.player_data["defense"],
                max_hp=world.player_data["max_hp"],
                level=world.player_data["level"],
                gold=world.player_data["gold"],
            )
            last_floor = f
            hp_at_floor_entry[f] = world.player_data["hp"]
            turns_on_floor[f] = 0

    pd = world.player_data
    floors_seen[world.current_floor] = dict(
        turns=turns_on_floor[world.current_floor],
        atk=pd["attack"], defense=pd["defense"], max_hp=pd["max_hp"],
        level=pd["level"], gold=pd["gold"],
    )

    return {
        "seed": seed,
        "steps": steps,
        "died": bool(world.game_over),
        "floor_reached": world.current_floor,
        "kills": dict(kills),
        "player": dict(atk=pd["attack"], defense=pd["defense"],
                       hp=pd["hp"], max_hp=pd["max_hp"],
                       level=pd["level"], gold=pd["gold"], exp=pd["exp"]),
        "per_floor": floors_seen,
        "dmg_per_hit": (dmg_taken / hit_turns) if hit_turns else 0.0,
        "hit_rate": hit_turns / max(1, steps),
    }


def duel_report(world, floors=(1, 5, 10, 20)):
    """For each floor: how many turns to kill the *median* monster there."""
    src = world._game_data["MONSTER_TYPES"]
    p = world.player_data
    rows = []
    for f in floors:
        pool = [m for m in src if int(m.get("min_floor", 1)) <= f]
        mult = world.monster_multiplier.__wrapped__ if False else None
        # monster_multiplier depends on world.current_floor; compute directly
        from game.utils import calculate_monster_multiplier
        mm = calculate_monster_multiplier(f)
        est_atk = p["attack"] + 10 * 2 * (f - 1)      # ~2 weapon pickups/floor
        est_def = p["defense"] + 8 * 2 * (f - 1)
        est_hp = p["max_hp"] + 10 * (f - 1) * 2
        worst = None
        for m in pool[-6:]:                      # strongest unlocked tier
            hp = m["hp"] * mm
            p_d = max(1, est_atk - m["defense"] * mm)
            m_d = max(1, m["attack"] * mm - est_def)
            tk = math.ceil(hp / p_d)
            td = math.ceil(est_hp / m_d)
            rows.append((f, m["name"], round(hp), round(p_d), round(m_d), tk, td,
                         "必死" if tk > td else ("险胜" if tk > td * 0.7 else "可杀")))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    res = run(args.steps, args.seed)
    print("=" * 72)
    print(f"BALANCE SIM  seed={res['seed']}  steps={res['steps']}")
    print("=" * 72)
    print(f"  died={res['died']}  floor reached={res['floor_reached']}  "
          f"player={res['player']}")
    print(f"  kills per floor: {res['kills']}")
    print(f"  avg damage per counter-attack={res['dmg_per_hit']:.1f}  "
          f"hit rate={res['hit_rate']:.2f}")
    print("  per floor (turns spent / atk / def / max_hp / lvl / gold):")
    for f, d in res["per_floor"].items():
        print(f"    F{f:<3} turns={d['turns']:<5} atk={d['atk']:<5} "
              f"def={d['defense']:<4} hp={d['max_hp']:<6} "
              f"lvl={d['level']:<4} gold={d['gold']}")

    from game.world import GameWorld
    w = GameWorld()
    print("  duel estimate on the strongest unlocked tier per floor")
    print("    floor monster              mHP  你伤害 它伤害 你刀数 它刀数 结论")
    for f, name, hp, pd_, md, tk, td, v in duel_report(w):
        print(f"    F{f:<4} {name:<18} {hp:<6} {pd_:<6} {md:<6} {tk:<6} {td:<6} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
