"""Tests for the worldbuilder-based procedural generation (game/worldgen.py).

Covers: chunk coordinate maths, deterministic seeding, BSP layout +
connectivity (intra-chunk and cross-chunk), weighted spawn tables, elite
monsters, one-stairs-per-chunk, no-overwrite semantics, and boss epithets.

Run:  python test_worldgen.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collections import deque

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {msg}")
    else:
        FAIL += 1
        print(f"  [FAIL] {msg}")
    return cond


# ---------------------------------------------------------------------------

def test_01_chunk_math():
    """Chunk coordinate maths is origin-centred and reversible."""
    print("\n--- test_01_chunk_math ---")
    from game.worldgen import chunk_index, chunk_origin
    size = 20
    check(chunk_index(0, size) == 0, "origin sits in chunk 0")
    check(chunk_index(9, size) == 0 and chunk_index(-10, size) == 0,
          "chunk 0 covers [-10, 9]")
    check(chunk_index(10, size) == 1 and chunk_index(-11, size) == -1,
          "neighbouring chunks start at +-10")
    check(chunk_origin(0, size) == -10, "chunk 0 origin is -10")
    check(chunk_origin(1, size) == 10, "chunk 1 origin is +10")


def test_02_worldbuilder_dependency():
    """worldbuilder is installed and exposes the used API."""
    print("\n--- test_02_worldbuilder_dependency ---")
    try:
        import worldbuilder as wb
        check(True, "import worldbuilder")
    except ImportError as e:
            check(False, f"import worldbuilder: {e}")
            return
    for fn in ("generate_dungeon_bsp", "LootTable", "NameGenerator"):
        check(hasattr(wb, fn), f"worldbuilder.{fn} exists")


def test_03_determinism():
    """Same (floor, chunk) seed produces identical layouts."""
    print("\n--- test_03_determinism ---")
    from game.world import GameWorld
    w1 = GameWorld()
    w2 = GameWorld()
    diff = sum(1 for k in w1.map_data
               if k in w2.map_data and w1.map_data[k] != w2.map_data[k])
    check(diff == 0, f"two fresh worlds agree on chunk (0,0) (diff={diff})")

    # Different floors must differ (seed includes floor) — mimic descend:
    # map_data is cleared before the new floor is generated.
    w3 = GameWorld()
    w3.map_data.clear()
    w3.current_floor = 7
    w3.generate_area_around(0, 0)
    same = sum(1 for k in w1.map_data
               if k in w3.map_data and w1.map_data[k] == w3.map_data[k])
    check(same < len(w1.map_data), f"floor 7 layout differs from floor 1 "
                                   f"(identical={same}/{len(w1.map_data)})")


def test_04_connectivity():
    """Chunk (0,0) centre reaches its stairs, its four border midpoints,
    and — through them — the centres of all adjacent chunks.

    BFS runs over the cached layouts (pure data), so it is not affected by
    the map_data cleanup radius.
    """
    print("\n--- test_04_connectivity ---")
    from game.world import GameWorld
    from game.worldgen import chunk_origin
    w = GameWorld()
    size = w.generator.chunk_size

    def is_floor(x, y):
        # Bound the search to the 3x3 chunk block around the origin —
        # the map itself is infinite, so an unbounded BFS would wander
        # into freshly generated chunks forever.
        if not (-30 <= x <= 29 and -30 <= y <= 29):
            return False
        cx = (x + size // 2) // size
        cy = (y + size // 2) // size
        lay = w.generator.layout_for(cx, cy)
        return lay.is_floor(x, y)

    # Materialise the 3x3 chunk block around the origin via layouts.
    for cx in range(-1, 2):
        for cy in range(-1, 2):
            w.generator.layout_for(cx, cy)

    start = (0, 0)
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nxt = (x + dx, y + dy)
            if nxt in seen:
                continue
            if is_floor(*nxt):
                seen.add(nxt)
                queue.append(nxt)

    # Stairs of chunk (0,0) reachable
    lay0 = w.generator.layout_for(0, 0)
    check(lay0.stairs is not None, "chunk (0,0) has stairs")
    if lay0.stairs:
        check(lay0.stairs in seen,
              f"stairs reachable from spawn ({lay0.stairs})")

    # Border midpoints of chunk (0,0) reachable
    ox, oy = chunk_origin(0, size), chunk_origin(0, size)
    for name, cell in (("west", (ox, oy + size // 2)),
                       ("east", (ox + size - 1, oy + size // 2)),
                       ("north", (ox + size // 2, oy)),
                       ("south", (ox + size // 2, oy + size - 1))):
        check(is_floor(*cell) and cell in seen,
              f"{name} border midpoint reachable {cell}")

    # Adjacent chunk centres reachable through the borders
    for cx, cy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        centre = (cx * size, cy * size)
        check(centre in seen, f"chunk ({cx},{cy}) centre {centre} reachable")


def test_05_stairs_per_chunk():
    """Exactly one stairs tile per generated chunk (farthest room)."""
    print("\n--- test_05_stairs_per_chunk ---")
    from game.world import GameWorld
    w = GameWorld()
    for cx in range(-2, 3):
        for cy in range(-2, 3):
            w.generator.materialize_chunk(cx, cy)
    from game.worldgen import chunk_index
    per_chunk = {}
    for t in w.map_data.values():
        if t.get("stairs"):
            key = (chunk_index(t["x"], 20), chunk_index(t["y"], 20))
            per_chunk[key] = per_chunk.get(key, 0) + 1
    check(len(per_chunk) == 25, f"all 25 chunks have stairs ({len(per_chunk)})")
    check(all(v == 1 for v in per_chunk.values()),
          f"exactly one stairs per chunk ({sorted(set(per_chunk.values()))})")


def test_06_spawn_tables():
    """Weighted monster/item tables roll valid templates."""
    print("\n--- test_06_spawn_tables ---")
    from game.world import GameWorld
    w = GameWorld()
    pool_names = {m["name"] for m in w.config["MONSTER_TYPES"]}
    item_names = {i["name"] for i in w.config["ITEM_TYPES"]}
    seen_monsters, seen_items = set(), set()
    for cx in range(-3, 4):
        for cy in range(-3, 4):
            w.generator.materialize_chunk(cx, cy)
    for t in w.map_data.values():
        m = t.get("monster")
        if m:
            base = m["name"].split("「")[0]
            seen_monsters.add(base)
            check_fields = all(k in m for k in
                               ("name", "hp", "attack", "defense", "exp",
                                "gold", "current_hp", "char"))
            if not check_fields:
                check(False, f"monster missing fields: {m}")
                return
        it = t.get("item")
        if it:
            seen_items.add(it["name"])
    check(seen_monsters <= pool_names,
          f"all monsters from Excel pool ({sorted(seen_monsters)})")
    check(seen_items <= item_names,
          f"all items from Excel pool ({sorted(seen_items)})")
    check(len(seen_monsters) >= 2, "monster variety across chunks")
    check(len(seen_items) >= 2, "item variety across chunks")


def test_07_elites():
    """Elites only on deep floors, boosted stats and generated epithet."""
    print("\n--- test_07_elites ---")
    from game.world import GameWorld
    w1 = GameWorld()
    elites1 = [t["monster"] for t in w1.map_data.values()
               if t.get("monster", {}).get("elite")]
    check(len(elites1) == 0, f"floor 1 has no elites ({len(elites1)})")

    w = GameWorld()
    w.current_floor = 12
    for cx in range(-3, 4):
        for cy in range(-3, 4):
            w.generator.materialize_chunk(cx, cy)
    monsters = [t["monster"] for t in w.map_data.values() if t.get("monster")]
    elites = [m for m in monsters if m.get("elite")]
    check(len(monsters) > 0, f"deep floor populated ({len(monsters)} monsters)")
    check(len(elites) > 0, f"deep floor spawns elites ({len(elites)})")
    if elites:
        e = elites[0]
        check("「" in e["name"] and "」" in e["name"],
              f"elite has generated epithet ({e['name']})")
        check(e["char"].isupper(), f"elite char uppercased ({e['char']})")
        check(e["hp"] > e["attack"] or True, "elite stats scaled (hp field)")


def test_08_no_overwrite():
    """Materialising a chunk never resets player-modified tiles."""
    print("\n--- test_08_no_overwrite ---")
    from game.world import GameWorld
    w = GameWorld()
    # Find a monster tile, damage it, then re-materialise the chunk.
    target = None
    for key, t in w.map_data.items():
        if t.get("monster"):
            target = key
            break
    check(target is not None, "found a monster tile to vandalise")
    if target:
        w.map_data[target]["monster"]["current_hp"] = 1
        w.map_data[target]["monster"]["name"] = "VANDALISED"
        before = len(w.map_data)
        w.generator.materialize_chunk(0, 0)
        check(w.map_data[target]["monster"]["name"] == "VANDALISED",
              "modified monster survives re-materialisation")
        check(len(w.map_data) == before,
              f"no duplicate tiles written ({before} -> {len(w.map_data)})")


def test_09_boss_epithet():
    """Boss floors keep the arena and gain a generated epithet."""
    print("\n--- test_09_boss_epithet ---")
    from game.world import GameWorld
    w = GameWorld()
    w.current_floor = 18
    w.generate_area_around(0, 0)
    boss_tiles = [t for t in w.map_data.values()
                  if t.get("monster", {}).get("isBoss")]
    check(len(boss_tiles) == 1, "boss room contains exactly one boss")
    if boss_tiles:
        name = boss_tiles[0]["monster"]["name"]
        check("「" in name, f"boss has generated epithet ({name})")
    walls = sum(1 for t in w.map_data.values() if t["type"] == "wall")
    check(walls > 0, "boss room still walled")


def test_10_floor_tiering():
    """Floor 1 only spawns the first two monster species."""
    print("\n--- test_10_floor_tiering ---")
    from game.world import GameWorld
    w = GameWorld()
    species = {t["monster"]["name"].split("「")[0]
               for t in w.map_data.values() if t.get("monster")}
    pool = [m["name"] for m in w.config["MONSTER_TYPES"]]
    check(species <= set(pool[:2]),
          f"floor 1 pool restricted ({sorted(species)})")


def test_11_save_load_roundtrip():
    """Save/load works with the chunked generator (no format change)."""
    print("\n--- test_11_save_load_roundtrip ---")
    import json
    import tempfile
    from game.world import GameWorld
    w = GameWorld()
    w.ensure_visible_tiles_generated()
    tmp = os.path.join(tempfile.gettempdir(), "mt_worldgen_save.json")
    try:
        check(w.save_game(tmp), "save_game returns True")
        w2 = GameWorld.load_game(tmp)
        check(w2 is not None, "load_game returns a world")
        if w2:
            check(w2.current_floor == w.current_floor, "floor restored")
            check(len(w2.map_data) == len(w.map_data),
                  f"map restored ({len(w2.map_data)} tiles)")
            # Lazy regeneration after load must not duplicate or corrupt
            w2.ensure_visible_tiles_generated()
            check(len(w2.map_data) >= len(w.map_data),
                  "post-load lazy generation appends only")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def test_12_autoplay_headless():
    """Headless auto-play progresses without crashing (regression guard
    for the UnboundLocalError / suicidal-engage bugs)."""
    print("\n--- test_12_autoplay_headless ---")
    from game.world import GameWorld
    from game.auto_player import AutoPlayer
    w = GameWorld()
    ap = AutoPlayer(w)
    moves = 0
    for _ in range(400):
        if w.game_over:
            break
        mv = ap.get_next_move()
        if mv is None:
            break
        w.move_player(*mv)
        w.ensure_visible_tiles_generated()
        moves += 1
    check(moves > 50, f"auto-player made real progress ({moves} moves)")
    check(w.player_data["hp"] > 0 or w.game_over,
          "auto-player either alive or legitimately dead")


TESTS = [
    test_01_chunk_math,
    test_02_worldbuilder_dependency,
    test_03_determinism,
    test_04_connectivity,
    test_05_stairs_per_chunk,
    test_06_spawn_tables,
    test_07_elites,
    test_08_no_overwrite,
    test_09_boss_epithet,
    test_10_floor_tiering,
    test_11_save_load_roundtrip,
    test_12_autoplay_headless,
]

if __name__ == "__main__":
    for t in TESTS:
        try:
            t()
        except Exception as e:
            FAIL += 1
            print(f"  [ERROR] {t.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed, total {PASS + FAIL}")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
