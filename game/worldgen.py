"""Procedural world generation — adapter over the `worldbuilder` library.

The map is an infinite dungeon divided into ``CHUNK_SIZE x CHUNK_SIZE``
chunks, with the origin (0, 0) at the centre of chunk (0, 0).  Each chunk is
generated **deterministically** from a seed derived from
``(floor, chunk_x, chunk_y)`` (djb2 hash — stable across runs/platforms), so
the same coordinates always yield the same layout.

Per chunk:

* layout  —— ``worldbuilder.generate_dungeon_bsp`` (BSP rooms + corridors,
  guaranteed connected inside the chunk);
* borders —— all four border midpoints are carved open and L-corridored to
  the nearest room, so adjacent chunks always connect;
* centre  —— the chunk centre cell is carved floor and connected to the
  nearest room (the player may spawn there);
* spawns  —— weighted tables built with ``worldbuilder.LootTable``
  (monsters weighted by inverse HP, items uniform);
* elites  —— ``worldbuilder.NameGenerator`` epithets on boosted monsters;
* stairs  —— exactly one stairs tile per chunk, in the room farthest from
  the chunk centre.

``materialize_chunk`` writes only tiles that do not already exist in
``world.map_data``, preserving the original no-overwrite semantics (a tile
the player has modified is never reset).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Optional

import worldbuilder as wb


# ---------------------------------------------------------------------------
# Chunk coordinate maths
# ---------------------------------------------------------------------------

def chunk_index(coord: int, chunk_size: int) -> int:
    """Chunk index of a world coordinate (floor division, origin-centred)."""
    return (coord + chunk_size // 2) // chunk_size


def chunk_origin(index: int, chunk_size: int) -> int:
    """Minimum world coordinate covered by ``index``."""
    return index * chunk_size - chunk_size // 2


def stable_seed(*parts) -> int:
    """djb2 hash over parts (ints hashed directly, strings via UTF-8 bytes).

    Deterministic across runs/platforms — no reliance on ``hash()``.
    """
    h = 5381
    for p in parts:
        if isinstance(p, str):
            for b in p.encode("utf-8"):
                h = ((h * 33) + b) & 0xFFFFFFFF
        else:
            h = ((h * 33) + int(p)) & 0xFFFFFFFF
    return h


# ---------------------------------------------------------------------------
# Layout container
# ---------------------------------------------------------------------------

@dataclass
class ChunkLayout:
    """Pure data for one chunk: grid + spawn overlays (no mutable state)."""

    cx: int
    cy: int
    size: int
    grid: list[list[int]]                      # [row=y][col=x], 1=floor 0=wall
    # spawn overlays keyed by GRID coords (col, row):
    # {"monster": {...}} / {"item": {...}} / {"door": True} / {"merchant": True}
    spawns: dict[tuple[int, int], dict] = field(default_factory=dict)
    stairs: Optional[tuple[int, int]] = None   # world coords
    def is_floor(self, gx: int, gy: int) -> bool:
        """World-coord floor test."""
        ox = chunk_origin(self.cx, self.size)
        oy = chunk_origin(self.cy, self.size)
        col, row = gx - ox, gy - oy
        if 0 <= row < self.size and 0 <= col < self.size:
            return bool(self.grid[row][col])
        return False


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class WorldGenerator:
    """Builds and caches chunk layouts for a :class:`game.world.GameWorld`."""

    def __init__(self, world):
        self.world = world
        cfg = world.config
        self.chunk_size: int = int(cfg.get("CHUNK_SIZE", 20))
        self.gen_chance_item: float = float(cfg.get("GEN_CHANCE_ITEM", 0.10))
        self.gen_chance_monster: float = float(cfg.get("GEN_CHANCE_MONSTER", 0.15))
        self.gen_chance_door: float = float(cfg.get("GEN_CHANCE_DOOR", 0.02))
        self.gen_chance_merchant: float = float(cfg.get("GEN_CHANCE_MERCHANT", 0.03))
        self.elite_chance: float = float(cfg.get("ELITE_CHANCE", 0.08))
        self.elite_mult: float = float(cfg.get("ELITE_STAT_MULT", 1.5))
        self.elite_min_floor: int = int(cfg.get("ELITE_MIN_FLOOR", 3))
        name_style = str(cfg.get("NAME_STYLE", "fantasy"))
        self._namegen = wb.NameGenerator(
            style=name_style, seed=stable_seed(0x5EED, "magic-tower")
        )
        self._cache: dict[tuple[int, int, int], ChunkLayout] = {}
        self._cache_limit: int = 64

    # ---- public API ----

    def clear_cache(self):
        """Drop all cached layouts (called on floor change)."""
        self._cache.clear()

    def layout_for(self, cx: int, cy: int) -> ChunkLayout:
        """Return the (cached) layout of chunk (cx, cy) on the current floor."""
        key = (self.world.current_floor, cx, cy)
        layout = self._cache.get(key)
        if layout is None:
            layout = self._build(cx, cy)
            if len(self._cache) >= self._cache_limit:
                # Simple bounded cache: drop the oldest inserted entry.
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = layout
        return layout

    def materialize_chunk(self, cx: int, cy: int) -> int:
        """Write missing tiles of chunk (cx, cy) into ``world.map_data``.

        Existing keys are never overwritten.  Returns the number of tiles
        written.
        """
        layout = self.layout_for(cx, cy)
        map_data = self.world.map_data
        tiles = self.world.config["TILES"]
        size = layout.size
        ox = chunk_origin(cx, size)
        oy = chunk_origin(cy, size)

        written = 0
        for row in range(size):
            gy = oy + row
            for col in range(size):
                gx = ox + col
                key = f"{gx},{gy}"
                if key in map_data:
                    continue
                if layout.grid[row][col]:
                    tile = {
                        "type": "floor",
                        "char": tiles["FLOOR"],
                        "x": gx,
                        "y": gy,
                    }
                    feats = layout.spawns.get((col, row))
                    if feats:
                        tile.update(feats)
                        if feats.get("door"):
                            tile["char"] = tiles["DOOR"]
                        elif feats.get("stairs"):
                            tile["char"] = tiles["STAIRS"]
                        elif feats.get("merchant"):
                            tile["char"] = tiles["MERCHANT"]
                else:
                    tile = {"type": "wall", "char": tiles["WALL"], "x": gx, "y": gy}
                map_data[key] = tile
                written += 1
        return written

    def elite_name(self, base_name: str) -> str:
        """A generated epithet, e.g. ``Goblin「Vorwyn」``."""
        epithet = self._namegen.generate(1)[0]
        return f"{base_name}「{epithet}」"

    # ---- internals ----

    def _build(self, cx: int, cy: int) -> ChunkLayout:
        size = self.chunk_size
        floor = self.world.current_floor
        seed = stable_seed(floor, cx, cy)
        rng = random.Random(seed)

        layout = ChunkLayout(cx=cx, cy=cy, size=size, grid=[])

        # --- 1. BSP dungeon layout (rooms + corridors, connected) ---
        bsp = wb.generate_dungeon_bsp(size, size, seed=seed)
        rooms = list(bsp["rooms"])
        grid = [[1 if bsp["grid"][r][c] else 0 for c in range(size)]
                for r in range(size)]

        if not rooms:
            # Degenerate chunk (BSP found no room): open cavern fallback so
            # the map stays playable.
            grid = [[1] * size for _ in range(size)]

        # --- 2. connectivity: chunk centre + four border midpoints ---
        centre = (size // 2, size // 2)
        anchors = [centre,
                   (0, size // 2), (size - 1, size // 2),
                   (size // 2, 0), (size // 2, size - 1)]
        keep_clear = {centre}   # spawn point + escape corridors stay empty
        for ax, ay in anchors:
            grid[ay][ax] = 1
            if rooms:
                target = self._nearest_room(rooms, ax, ay)
                keep_clear.update(
                    self._carve_l(grid, ax, ay, target[0], target[1]))

        layout.grid = grid

        # --- 3. population ---
        floor_cells = [
            (c, r) for r in range(size) for c in range(size) if grid[r][c]
        ]
        # Never spawn on the centre cell or its escape corridors: the
        # player may spawn at the centre, and a monster/door there could
        # seal them in.
        floor_cells = [cell for cell in floor_cells if cell not in keep_clear]

        monster_table = self._monster_table(seed)
        item_table = self._item_table(seed)

        n_monster = int(round(len(floor_cells) * self.gen_chance_monster))
        n_item = int(round(len(floor_cells) * self.gen_chance_item))
        n_door = int(round(len(floor_cells) * self.gen_chance_door))
        n_merchant = int(round(len(floor_cells) * self.gen_chance_merchant))

        spawns: dict[tuple[int, int], dict] = {}

        # Monsters & items via weighted loot tables (bulk rolls).
        if monster_table is not None and n_monster > 0:
            picks = monster_table.roll(n_monster)
            for name in picks:
                cell = self._take_cell(rng, floor_cells, spawns)
                if cell is None:
                    break
                spawns[cell] = {"monster": self._make_monster(name, rng)}
        if item_table is not None and n_item > 0:
            for name in item_table.roll(n_item):
                cell = self._take_cell(rng, floor_cells, spawns)
                if cell is None:
                    break
                spawns[cell] = {"item": self._make_item(name)}

        # Doors & merchants: uniform random placement.
        for _ in range(n_door):
            cell = self._take_cell(rng, floor_cells, spawns)
            if cell is None:
                break
            spawns[cell] = {"door": True}
        for _ in range(n_merchant):
            cell = self._take_cell(rng, floor_cells, spawns)
            if cell is None:
                break
            spawns[cell] = {"merchant": True}

        layout.spawns = spawns

        # --- 4. stairs: room farthest from the chunk centre ---
        if rooms:
            far = max(rooms, key=lambda rm: self._dist2(
                (rm["cx"], rm["cy"]), centre))
            stairs_cell = (far["cx"], far["cy"])
            if grid[stairs_cell[1]][stairs_cell[0]] and stairs_cell != centre:
                spawns[stairs_cell] = {"stairs": True}
                gx = chunk_origin(cx, size) + stairs_cell[0]
                gy = chunk_origin(cy, size) + stairs_cell[1]
                layout.stairs = (gx, gy)

        return layout

    # ---- spawn tables ----

    def _monster_table(self, seed: int) -> Optional[wb.LootTable]:
        """Weighted monster table: rarer (higher HP) monsters weigh less."""
        pool = self._monster_pool()
        if not pool:
            return None
        entries = [(m["name"], max(1.0, 1000.0 / max(1, m["hp"])), (1, 1))
                   for m in pool]
        return wb.LootTable(entries, seed=seed)

    def _item_table(self, seed: int) -> Optional[wb.LootTable]:
        items = list(self.world.config.get("ITEM_TYPES", []))
        if not items:
            return None
        entries = [(it["name"], 1.0, (1, 1)) for it in items]
        return wb.LootTable(entries, seed=seed)

    def _monster_pool(self) -> list[dict]:
        """Monster templates available on the current floor (tier gating)."""
        pool = list(self.world.config.get("MONSTER_TYPES", []))
        floor = self.world.current_floor
        if floor == 1:
            pool = pool[:2]
        elif floor <= 5:
            pool = pool[:3]
        return pool

    def _make_monster(self, name: str, rng: random.Random) -> dict:
        template = next(
            (m for m in self._monster_pool() if m["name"] == name), None
        )
        if template is None:
            template = {"char": "?", "name": name, "hp": 1, "attack": 1,
                        "defense": 0, "exp": 0, "gold": 0}
        monster = {**template}
        mult = self.world.monster_multiplier()
        monster["hp"] = int(monster["hp"] * mult)
        monster["attack"] = int(monster["attack"] * mult)
        monster["defense"] = int(monster["defense"] * mult)
        monster["exp"] = int(monster["exp"] * mult)
        monster["gold"] = int(monster["gold"] * mult)
        monster["current_hp"] = monster["hp"]

        # Elite roll: deeper floors only.
        if (self.world.current_floor >= self.elite_min_floor
                and rng.random() < self.elite_chance):
            monster["name"] = self.elite_name(template["name"])
            monster["hp"] = int(monster["hp"] * self.elite_mult)
            monster["attack"] = int(monster["attack"] * self.elite_mult)
            monster["defense"] = int(monster["defense"] * self.elite_mult)
            monster["exp"] = int(monster["exp"] * 2)
            monster["gold"] = int(monster["gold"] * 2)
            monster["current_hp"] = monster["hp"]
            monster["elite"] = True
            monster["char"] = str(template.get("char", "?")).upper()
        return monster

    def _make_item(self, name: str) -> dict:
        template = next(
            (it for it in self.world.config.get("ITEM_TYPES", [])
             if it["name"] == name), None
        )
        return {**template} if template else {
            "char": "?", "name": name, "type": "misc", "value": 0}

    # ---- small helpers ----

    @staticmethod
    def _nearest_room(rooms: list[dict], gx: int, gy: int) -> tuple[int, int]:
        nearest = min(rooms, key=lambda rm: (rm["cx"] - gx) ** 2
                      + (rm["cy"] - gy) ** 2)
        return nearest["cx"], nearest["cy"]

    @staticmethod
    def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    @staticmethod
    def _carve_l(grid: list[list[int]], x1: int, y1: int, x2: int,
                 y2: int) -> list[tuple[int, int]]:
        """Carve an L-shaped corridor (horizontal first, then vertical).

        Returns the list of carved cells so callers can keep them clear.
        """
        carved = []
        step = 1 if x2 >= x1 else -1
        for x in range(x1, x2 + step, step):
            grid[y1][x] = 1
            carved.append((x, y1))
        step = 1 if y2 >= y1 else -1
        for y in range(y1, y2 + step, step):
            grid[y][x2] = 1
            carved.append((x2, y))
        return carved

    @staticmethod
    def _take_cell(rng: random.Random, cells: list, taken: dict):
        """Pick a random unused cell; returns None when exhausted."""
        for _ in range(20):
            cell = rng.choice(cells)
            if cell not in taken:
                return cell
        for cell in cells:
            if cell not in taken:
                return cell
        return None
