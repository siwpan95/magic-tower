"""Harvest stop-motion promo material from a headless magic-tower run.

Drives the real GameWorld with the real AutoPlayer (same loop as
tools/balance_sim.py) and records, on a set of "hero floors", a per-step
snapshot of the explored region (terrain grid + glyphs + live monsters with
HP + player stats).  After the run each hero floor's explored area is unioned
into one map, written as a cordis-table-app Map workbook and rendered through
cordis' own CLI — so every hero map in the film is a genuine "printed map".

Outputs (all under output/promo/):
  harvest.json    per-hero-floor step snapshots, player stats, kill events
  maps/floor_XXX.xlsx + .png   cordis-rendered hero maps (union of explored)
  bestiary.json   40 monsters (name/char/hp/atk/def/min_floor) for the wall
  audit.json      depth_audit rows + summary (data scene, 4-seed median)

Usage:
    E:/Python314/python.exe tools/harvest_promo.py [--steps 8000] [--seed 7]
        [--out output/promo] [--radius 16]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from game.map_print import (MapSnapshot, write_xlsx, render_with_cordis,  # noqa: E402
                            snapshot)
from tools.depth_audit import audit, collect, summarize  # noqa: E402

HERO_FLOORS = (1, 5, 18, 20, 45, 90, 100)  # 18/90 = boss floors (interval 18)
# terrain glyphs (ASCII_OF values) — anything else in `chars` is an entity
TERRAIN_GLYPHS = set("#.=> ")

# terrain key <-> single-char code (compact per-step storage in harvest.json)
TERRAIN_CODE = {
    "stone": "#", "floor": ".", "trap": "x", "secret": "E", "lava": "B",
    "grass": "*", "sand": "M", "door": "=", "stair": ">", "player": "@",
    "void": " ",
}
CODE_TERRAIN = {v: k for k, v in TERRAIN_CODE.items()}


# --------------------------------------------------------------------------- #
# simulation (mirrors tools/balance_sim.py so the film shows the real bot)
# --------------------------------------------------------------------------- #
def simulate(steps: int, seed: int, radius: int, hero_floors: set[int],
             progress_every: int = 500) -> dict:
    from game.world import GameWorld
    from game.auto_player import AutoPlayer

    random.seed(seed)
    world = GameWorld()
    world.generate_initial_map()
    bot = AutoPlayer(world)

    kills = collections.Counter()
    kill_events = []          # (floor, step_on_floor, name, elite)
    _orig_add_log = world.add_log

    def _counting_add_log(message, msg_type="system"):
        if message.startswith("Defeated") or message.startswith("DEFEATED BOSS"):
            kills[world.current_floor] += 1
            kill_events.append({
                "floor": world.current_floor,
                "step": steps_on_floor[world.current_floor],
                "msg": message,
            })
        _orig_add_log(message, msg_type)

    world.add_log = _counting_add_log

    steps_on_floor = collections.Counter()
    floors: dict[int, list[dict]] = collections.defaultdict(list)
    final_floor = world.current_floor

    def record_step():
        snap = snapshot(world, radius=radius)
        # live monsters inside the window (tiles carry the mutable dict)
        monsters = []
        for row in range(snap.rows):
            for col in range(snap.cols):
                tile = world.map_data.get(f"{snap.ox + col},{snap.oy + row}")
                mon = (tile or {}).get("monster")
                if mon:
                    monsters.append({
                        "x": snap.ox + col, "y": snap.oy + row,
                        "col": col, "row": row,
                        "name": mon.get("name", "?"),
                        "char": mon.get("char", "x"),
                        "hp": int(mon.get("current_hp", mon.get("hp", 0))),
                        "max_hp": int(mon.get("hp", 0)),
                        "elite": bool(mon.get("elite")),
                        "boss": bool(mon.get("isBoss")),
                    })
        pd = world.player_data
        floors[world.current_floor].append({
            "step": steps_on_floor[world.current_floor],
            "grid": ["".join(TERRAIN_CODE[k] for k in r) for r in snap.grid],
            "chars": ["".join(r) for r in snap.chars],
            "ox": snap.ox, "oy": snap.oy,
            "player": {"x": pd.get("x", 0), "y": pd.get("y", 0),
                       "hp": int(pd.get("hp", 0)), "max_hp": int(pd.get("max_hp", 0)),
                       "atk": int(pd.get("attack", 0)), "def": int(pd.get("defense", 0)),
                       "level": int(pd.get("level", 1)), "gold": int(pd.get("gold", 0))},
            "monsters": monsters,
        })

    for step in range(steps):
        if world.game_over:
            break
        world.ensure_visible_tiles_generated()

        inv = world.player_data.get("inventory", [])
        for i in range(len(inv) - 1, -1, -1):
            if i >= len(world.player_data.get("inventory", [])):
                continue
            if bot.should_use_inventory_item(world.player_data["inventory"][i]):
                world.use_inventory_item(i)

        move = bot.get_next_move()
        if move:
            world.move_player(*move)

        if world.open_shop:
            world.open_shop = False
            for item in bot.auto_shop():
                ok, _ = world.buy_item(item["id"])
                if not ok:
                    break

        if world.player_data.get("skill_points", 0) > 0:
            sk = world.get_available_skills(3)
            if sk:
                pick = bot.auto_learn_skill(sk)
                world.learn_skill(pick if pick else sk[0])

        f = world.current_floor
        steps_on_floor[f] += 1
        # hero floors always; plus the tail (last 12% of the step budget) so
        # the floor the run actually ends on gets a printed map too
        if f in hero_floors or step >= steps * 0.88:
            record_step()
        if step % progress_every == 0:
            print("  step %d  floor %d  (recorded floors: %s)"
                  % (step, f, sorted(floors)), flush=True)

    final_floor = world.current_floor
    pd = world.player_data
    # keep hero floors + the final floor; drop the other tail recordings
    keep = {f: v for f, v in floors.items()
            if f in hero_floors or f == final_floor}
    return {
        "seed": seed,
        "steps": steps,
        "died": bool(world.game_over),
        "floor_reached": final_floor,
        "kills": {str(k): v for k, v in sorted(kills.items())},
        "kill_events": kill_events,
        "player_final": {"atk": pd["attack"], "def": pd["defense"],
                         "hp": pd["hp"], "max_hp": pd["max_hp"],
                         "level": pd["level"], "gold": pd["gold"]},
        "floors": {str(k): v for k, v in keep.items()},
    }


# --------------------------------------------------------------------------- #
# hero maps: union of every explored tile on the floor -> cordis render
# --------------------------------------------------------------------------- #
def union_floor_map(floor_steps: list[dict]) -> MapSnapshot:
    terrain: dict[tuple[int, int], str] = {}
    glyph: dict[tuple[int, int], str] = {}
    for st in floor_steps:
        for r, row in enumerate(st["grid"]):
            for c, code in enumerate(row):
                x, y = st["ox"] + c, st["oy"] + r
                key = CODE_TERRAIN.get(code, "void")
                if key == "void":
                    continue
                # last sighting wins: the map shows the floor as it was left
                # (killed monsters drop their tile key, so they vanish here)
                terrain[(x, y)] = key
                g = st["chars"][r][c]
                if g not in TERRAIN_GLYPHS:  # entity glyph (monster letter, @, ...)
                    glyph[(x, y)] = g
                else:
                    glyph.pop((x, y), None)
    xs = [p[0] for p in terrain]
    ys = [p[1] for p in terrain]
    ox, oy = min(xs), min(ys)
    cols, rows = max(xs) - ox + 1, max(ys) - oy + 1
    grid = [["stone"] * cols for _ in range(rows)]
    chars = [["#"] * cols for _ in range(rows)]
    from game.map_print import ASCII_OF
    for (x, y), key in terrain.items():
        grid[y - oy][x - ox] = key
        chars[y - oy][x - ox] = ASCII_OF.get(key, "#")
    for (x, y), g in glyph.items():
        chars[y - oy][x - ox] = g
    snap = MapSnapshot(grid=grid, chars=chars, ox=ox, oy=oy,
                       cols=cols, rows=rows, floor=0)
    return snap


def render_hero_maps(harvest: dict, outdir: str, px: int) -> list[dict]:
    from game.map_print import PALETTE
    maps_dir = os.path.join(outdir, "maps")
    os.makedirs(maps_dir, exist_ok=True)
    results = []
    for fstr, steps in sorted(harvest["floors"].items(), key=lambda kv: int(kv[0])):
        floor = int(fstr)
        snap = union_floor_map(steps)
        snap.floor = floor
        name = "floor_%03d" % floor
        xlsx = os.path.join(maps_dir, name + ".xlsx")
        png = os.path.join(maps_dir, name + ".png")
        write_xlsx(snap, xlsx)
        ok = render_with_cordis(xlsx, png, px=px, grid=True)
        renderer = "cordis" if ok else "local"
        if not ok:
            from game.map_print import render_png_local
            render_png_local(snap, png, px=px, grid_lines=True)
        results.append({"floor": floor, "xlsx": xlsx, "png": png,
                        "renderer": renderer, "cols": snap.cols, "rows": snap.rows,
                        "steps": len(steps)})
        print("  [map] F%-4d %2dx%-2d tiles  %s  %s"
              % (floor, snap.cols, snap.rows, renderer, os.path.basename(png)), flush=True)
    return results


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps", type=int, default=8000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--radius", type=int, default=16)
    ap.add_argument("--px", type=int, default=48)
    ap.add_argument("--out", default=os.path.join(ROOT, "output", "promo"))
    ap.add_argument("--no-audit", action="store_true",
                    help="skip the 4-seed depth audit (saves ~1 min)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print("[1/4] headless run (seed %d, %d steps) ..." % (args.seed, args.steps))
    harvest = simulate(args.steps, args.seed, args.radius, set(HERO_FLOORS))
    print("      reached F%s (%d kills)" % (harvest["floor_reached"],
                                            sum(harvest["kills"].values())))

    print("[2/4] rendering hero maps through cordis-table-app ...")
    maps = render_hero_maps(harvest, args.out, args.px)

    print("[3/4] bestiary ...")
    from game.data_loader import GameDataLoader
    loader = GameDataLoader()
    bestiary = loader.load_all().get("MONSTER_TYPES", [])
    with open(os.path.join(args.out, "bestiary.json"), "w", encoding="utf-8") as f:
        json.dump(bestiary, f, ensure_ascii=False, indent=1)
    print("      %d monsters" % len(bestiary))

    print("[4/4] depth audit (4 seeds x %d steps) ..." % 6000)
    audit_json = None
    if not args.no_audit:
        data = collect(6000, [7, 13, 42, 99])
        rows = audit(data, 5)
        summary = summarize(rows, bestiary)
        audit_json = {"rows": rows, "summary": summary}
        with open(os.path.join(args.out, "audit.json"), "w", encoding="utf-8") as f:
            json.dump(audit_json, f, ensure_ascii=False, indent=1)
        print("      cap_floor=%s push_floor=%s"
              % (summary.get("cap_floor"), summary.get("push_floor")))

    harvest["maps"] = maps
    with open(os.path.join(args.out, "harvest.json"), "w", encoding="utf-8") as f:
        json.dump(harvest, f, ensure_ascii=False)
    size = os.path.getsize(os.path.join(args.out, "harvest.json"))
    print("\n[done] output/promo/  (harvest.json %.1f KB)" % (size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
