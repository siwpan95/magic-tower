"""Auto-play AI: flexible, exploration-first idle dungeon crawling."""

from __future__ import annotations

import random
from collections import deque
from typing import Optional

# Cardinal offsets
DIRS = [(0, -1), (0, 1), (-1, 0), (1, 0)]


class AutoPlayer:
    """Adaptable AI for fully-automatic play.
    Strategy: explore → scavenge → descend, with risk-aware combat."""

    SKILL_PRIORITY = [
        "Critical Hit", "Attack Boost", "Berserker",
        "Life Steal", "Defense Boost", "Toughness",
        "Damage Reduction", "Regeneration",
        "EXP Absorption", "Vitality Boost",
    ]

    def __init__(self, world):
        self.world = world
        self._tick: int = 0
        self._pos_history: deque[tuple[int, int]] = deque(maxlen=30)
        self._stuck_frames: int = 0
        self._last_direction: Optional[tuple[int, int]] = None
        self._engaged: Optional[tuple[int, int]] = None   # tile we are fighting
        # Committed walk route (tiles ahead of the player, target included).
        # Re-deriving only the *first step* every tick makes adjacent tiles
        # whose BFS first steps contradict each other oscillate forever
        # (measured: floor 5, 5810 steps pacing inside a 4-tile corridor
        # ring while the stairs sat 16 tiles away behind a beatable elite).
        # A whole-path commitment walks monotonically instead.
        self._route: Optional[list[tuple[int, int]]] = None
        self._route_floor: Optional[int] = None

    # ---- Public API ----

    def get_next_move(self) -> Optional[tuple[int, int]]:
        """Return (dx, dy) for the next move.  Never returns None while
        there is a valid adjacent tile — guarantees progress."""
        self._tick += 1
        px, py = self.world.get_player_position()
        self._pos_history.append((px, py))

        # ---- Finish a fight we already started ----
        # A boss exchange takes ~11 turns and does not move the player, which
        # tripped the loop/lock detector below: after 5 identical positions it
        # forced a breakout and the bot walked away from a half-dead boss
        # (measured: the floor-18 boss never died across 4000 steps).  This
        # check runs *before* the stuck logic so standing still — mid-fight —
        # is not mistaken for being stuck, and it keeps swinging while the
        # remaining exchange is still survivable.
        if self._engaged:
            tx, ty = self._engaged
            tile = self.world.get_tile(tx, ty)
            monster = tile.get("monster") if tile else None
            if monster is None:
                self._engaged = None
            else:
                move = (tx - px, ty - py)
                if max(abs(move[0]), abs(move[1])) == 1:
                    m_dmg = max(1, monster["attack"] - self.world.player_data["defense"])
                    turns_left = ((monster["current_hp"] + max(1, self.world.player_data["attack"] - monster["defense"]) - 1)
                                  // max(1, self.world.player_data["attack"] - monster["defense"]))
                    if m_dmg * turns_left < self.world.player_data["hp"]:
                        self._last_direction = move
                        return move
                self._engaged = None

        # ---- Loop detection ----
        if self._is_looping():
            self._stuck_frames += 1
        else:
            self._stuck_frames = max(0, self._stuck_frames - 1)

        # ---- STUCK? Force breakout immediately ----
        if self._stuck_frames > 4:
            move = self._force_breakout(px, py)
            if move:
                self._last_direction = move
                return move

        # ---- Phase 1: react to adjacent tiles ----
        move = self._scan_adjacent(px, py, "item")
        if move:
            self._last_direction = move
            return move

        move = self._scan_safe_monster(px, py)
        if move:
            self._last_direction = move
            return move

        if self.world.player_data.get("keys", 0) > 0:
            move = self._scan_adjacent(px, py, "door")
            if move:
                self._last_direction = move
                return move

        move = self._scan_adjacent(px, py, "merchant")
        if move:
            self._last_direction = move
            return move

        # ---- Phase 2: risk-dependent decision ----
        pd = self.world.player_data
        hp_ratio = pd["hp"] / max(pd["max_hp"], 1)
        explore_ratio = self._exploration_ratio()

        # Low HP -> retreat to stairs if known
        if hp_ratio < 0.2:
            self._route = None      # a retreat overrides any committed walk
            stairs = self._find_nearest_stairs(px, py)
            if stairs:
                path = self._bfs_step(px, py, stairs[0], stairs[1], avoid_monsters=True)
                if path and not self._tile_has_monster(px + path[0], py + path[1]):
                    self._last_direction = path
                    return path

        # ---- Follow a committed route before planning a new one ----
        move = self._follow_route(px, py)
        if move:
            self._last_direction = move
            return move

        # Floor sufficiently explored -> take stairs
        if explore_ratio > 0.6:
            move = self._stairs_move(px, py)
            if move:
                self._last_direction = move
                return move

        # Adjacent stairs as last resort before exploring
        move = self._scan_adjacent(px, py, "stairs")
        if move:
            self._last_direction = move
            return move

        # ---- Phase 3: explore or seek targets ----
        move = self._explore_or_seek(px, py, hp_ratio)
        if move:
            self._last_direction = move
            return move

        # ---- Phase 4: fight an adjacent monster only if the whole
        #      exchange is safe (same risk model as _scan_safe_monster) ----
        for dx, dy in DIRS:
            tile = self.world.get_tile(px + dx, py + dy)
            if tile and tile.get("monster") and self._fight_is_safe(
                    tile["monster"]):
                self._engaged = (px + dx, py + dy)
                self._last_direction = (dx, dy)
                return (dx, dy)

        # ---- Fallback: any valid move ----
        move = self._any_valid_move(px, py)
        if move:
            self._last_direction = move
            return move

        return None

    def _fight_is_safe(self, monster: dict) -> bool:
        """Whole-fight risk model: expected damage over the full exchange
        must stay below 35% of current HP (mirrors _scan_safe_monster)."""
        pd = self.world.player_data
        hp_ratio = pd["hp"] / max(pd["max_hp"], 1)
        if hp_ratio < 0.15:
            return False
        m_dmg = max(1, monster["attack"] - pd["defense"])
        for b in self.world.active_buffs:
            if b["effects"].get("defense_multiplier"):
                m_dmg = max(1, int(m_dmg / b["effects"]["defense_multiplier"]))
        dr = pd.get("dmg_reduction", 0) or 0
        if dr:
            m_dmg = max(1, m_dmg - dr)
        p_dmg = max(1, pd["attack"] - monster["defense"])
        for b in self.world.active_buffs:
            if b["effects"].get("attack_multiplier"):
                p_dmg = int(p_dmg * b["effects"]["attack_multiplier"])
        turns_to_kill = (monster["current_hp"] + p_dmg - 1) // p_dmg
        expected_dmg = m_dmg * max(0, turns_to_kill - 1)

        # Winning the damage race from (near) full health is worth taking even
        # when it costs more than the 35 % comfort budget.  A boss floor is a
        # hard gate and a boss exchange costs ~70 % HP, so the earlier rule
        # made idle play stall forever in front of the boss instead of
        # fighting it.
        turns_to_die = (pd["hp"] + m_dmg - 1) // m_dmg
        if turns_to_kill < turns_to_die and hp_ratio >= 0.8:
            return True

        return expected_dmg <= pd["hp"] * 0.35

    def auto_learn_skill(self, available_skills: list[dict]) -> Optional[dict]:
        """Adaptive skill selection based on current battle state."""
        if not available_skills:
            return None
        pd = self.world.player_data

        # Build dynamic priority — start from static base, then reorder
        priority = list(self.SKILL_PRIORITY)

        hp_ratio = pd["hp"] / max(pd["max_hp"], 1)

        # ---- Low HP: healing & defense first ----
        if hp_ratio < 0.35:
            heal_def = [
                "Regeneration", "Life Steal", "Vitality Boost",
                "Defense Boost", "Toughness", "Damage Reduction",
            ]
            # Move heal/def skills to front, preserving their relative order
            front = [s for s in heal_def if s in priority]
            rest = [s for s in priority if s not in heal_def]
            priority = front + rest

        # ---- Approaching boss floor: defense/survival first ----
        interval = self.world.config.get("BOSS_FLOOR_INTERVAL", 18)
        dist_to_boss = interval - (self.world.current_floor % interval)
        if 0 < dist_to_boss <= 3:
            boss_prep = [
                "Damage Reduction", "Defense Boost", "Toughness",
                "Regeneration", "Life Steal",
            ]
            front = [s for s in boss_prep if s in priority]
            rest = [s for s in priority if s not in boss_prep]
            priority = front + rest

        # ---- Pick the highest-priority available skill ----
        best, best_rank = None, 999
        for skill in available_skills:
            try:
                rank = priority.index(skill["name"])
            except ValueError:
                rank = 999
            if rank < best_rank:
                best_rank, best = rank, skill
        return best or available_skills[0]

    def should_buy_item(self, item: dict) -> bool:
        """Buy if we can afford it and reserve is enough.
        Reserve increases when approaching boss floor."""
        gold = self.world.player_data["gold"]
        if gold < item["price"] or item["stock"] <= 0:
            return False
        # Boss preparation: save more gold when close to boss floor
        interval = self.world.config.get("BOSS_FLOOR_INTERVAL", 18)
        dist_to_boss = interval - (self.world.current_floor % interval)
        if 0 < dist_to_boss <= 3:
            reserve = max(200, gold // 3)
        else:
            reserve = max(80, gold // 5)
        return gold - item["price"] >= reserve

    def should_use_inventory_item(self, item: dict) -> bool:
        pd = self.world.player_data
        itype = item.get("type", "")
        ratio = pd["hp"] / max(pd["max_hp"], 1)

        if itype == "consumable" and ratio < 0.50:
            return True
        if itype == "permanent":
            return True
        if itype == "key" and pd.get("keys", 0) == 0:
            return True
        if itype == "buff":
            interval = self.world.config.get("BOSS_FLOOR_INTERVAL", 18)
            dist_to_boss = interval - (self.world.current_floor % interval)
            if dist_to_boss <= 3:
                return True
        return False

    def auto_shop(self) -> list[dict]:
        purchases = [it for it in self.world.shop_items if self.should_buy_item(it)]
        type_order = {"permanent": 0, "buff": 1, "consumable": 2, "key": 3}
        purchases.sort(
            key=lambda it: (type_order.get(it.get("type", ""), 99), -it["price"])
        )
        return purchases

    # ---- Adjacent scanning ----

    def _scan_adjacent(self, x: int, y: int, feature: str) -> Optional[tuple[int, int]]:
        for dx, dy in DIRS:
            tile = self.world.get_tile(x + dx, y + dy)
            if tile and tile.get("type") != "wall" and tile.get(feature):
                return (dx, dy)
        return None

    def _scan_safe_monster(self, x: int, y: int) -> Optional[tuple[int, int]]:
        """Only engage if the exchange is worth it.

        Delegates to ``_fight_is_safe`` — this used to carry a second,
        hand-copied copy of the risk model (a flat 30 % HP budget), and the
        two drifted apart: a boss that ``_fight_is_safe`` accepted was still
        rejected here, so idle play stood next to the boss forever instead of
        fighting it.  One risk model, one place.
        """
        for dx, dy in DIRS:
            tile = self.world.get_tile(x + dx, y + dy)
            if not tile or not tile.get("monster"):
                continue
            if self._fight_is_safe(tile["monster"]):
                self._engaged = (x + dx, y + dy)
                return (dx, dy)
        return None

    def _tile_has_monster(self, x: int, y: int) -> bool:
        tile = self.world.get_tile(x, y)
        return bool(tile and tile.get("monster"))

    # ---- Exploration / seeking ----

    def _exploration_ratio(self) -> float:
        """How much of the expected floor area has been generated?"""
        explored = len(self.world.map_data)
        return min(1.0, explored / 600.0)

    def _explore_or_seek(
        self, px: int, py: int, hp_ratio: float
    ) -> Optional[tuple[int, int]]:
        """Intelligently choose: explore unknown, seek monster for exp, or seek item."""

        # ---- Farming mode: if HP high, actively seek safe monsters ----
        monster_targets: list = []
        if hp_ratio > 0.65:
            monster_targets = self._find_visible_monsters(px, py)
            for tx, ty in monster_targets:
                move = self._seek(tx, ty)
                if move:
                    return move

        # ---- Seek visible monsters (worth fighting) ----
        if not monster_targets:  # only if not already found above
            monster_targets = self._find_visible_monsters(px, py)
        for tx, ty in monster_targets:
            # avoid_monsters=True: the *target* is a fight we already vetted,
            # but the route there must not cross an unvetted monster tile.
            # With the default False the BFS happily routed the first step
            # through an elite Ogre (210 HP / 39 ATK) on the way to a rat,
            # and the bot suicided into it turn after turn (measured: seed 7,
            # floor 5 — full HP to dead in five exchanges).
            move = self._seek(tx, ty)
            if move:
                return move

        # ---- Seek visible items (avoid walking through monsters) ----
        item_target = self._find_visible_item(px, py)
        if item_target:
            move = self._seek(item_target[0], item_target[1])
            if move:
                return move

        # ---- Explore unknown edges (avoid walking through monsters) ----
        explore = self._find_explore_frontier(px, py)
        if explore:
            move = self._seek(explore[0], explore[1])
            if move:
                return move

        return None

    def _seek(self, tx: int, ty: int) -> Optional[tuple[int, int]]:
        """Commit to a monster-avoiding route toward (tx, ty) and step."""
        px, py = self.world.get_player_position()
        path = self._bfs_path(px, py, tx, ty, avoid_monsters=True)
        if not path:
            return None
        self._set_route(path)
        return self._follow_route(px, py)

    def _find_visible_monsters(
        self, px: int, py: int, radius: int = 10
    ) -> list[tuple[int, int]]:
        """Return positions of visible monsters sorted by distance.

        A monster is only worth seeking when the WHOLE fight is safe:
        expected damage over the full exchange must stay below 35% of
        current HP (same risk model as ``_scan_safe_monster``).
        """
        result = []
        pd = self.world.player_data
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                tx, ty = px + dx, py + dy
                tile = self.world.get_tile(tx, ty)
                if not tile or not tile.get("monster"):
                    continue
                m = tile["monster"]
                # Quick safety: skip if boss and we're too hurt
                if m.get("isBoss") and pd["hp"] / max(pd["max_hp"], 1) < 0.5:
                    continue
                # Whole-fight risk model
                if not self._fight_is_safe(m):
                    continue
                dist = abs(dx) + abs(dy)
                result.append((tx, ty, dist))
        result.sort(key=lambda t: t[2])
        return [(x, y) for x, y, _ in result[:5]]

    def _find_visible_item(self, px: int, py: int, radius: int = 12) -> Optional[tuple[int, int]]:
        best = None
        best_dist = float("inf")
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                tx, ty = px + dx, py + dy
                tile = self.world.get_tile(tx, ty)
                if not tile or not tile.get("item"):
                    continue
                dist = abs(dx) + abs(dy)
                if dist < best_dist:
                    best_dist, best = dist, (tx, ty)
        return best

    def _find_explore_frontier(
        self, px: int, py: int, radius: int = 12
    ) -> Optional[tuple[int, int]]:
        """Find a reachable border tile next to unexplored area."""
        candidates = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if abs(dx) + abs(dy) < 2:
                    continue
                tx, ty = px + dx, py + dy
                tile = self.world.get_tile(tx, ty)
                if not tile or tile.get("type") == "wall":
                    continue
                if tile.get("monster"):
                    continue
                # Check if any neighbor is unexplored
                has_unexplored = any(
                    self.world.get_tile(tx + ndx, ty + ndy) is None
                    for ndx, ndy in DIRS
                )
                if has_unexplored:
                    dist = abs(dx) + abs(dy)
                    candidates.append((tx, ty, dist))
        if not candidates:
            # Fallback: any far reachable floor tile
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if abs(dx) + abs(dy) < 4:
                        continue
                    tx, ty = px + dx, py + dy
                    tile = self.world.get_tile(tx, ty)
                    if tile and tile.get("type") != "wall" and not tile.get("monster"):
                        dist = abs(dx) + abs(dy)
                        candidates.append((tx, ty, dist))
        if not candidates:
            return None
        candidates.sort(key=lambda c: -c[2])  # furthest first
        return (candidates[0][0], candidates[0][1])

    # ---- Pathfinding ----

    def _find_nearest_stairs(
        self, px: int, py: int
    ) -> Optional[tuple[int, int, float]]:
        best_dist = float("inf")
        best = None
        for key, tile in self.world.map_data.items():
            if tile.get("stairs"):
                tx, ty = tile["x"], tile["y"]
                if tx == px and ty == py:
                    continue
                dist = abs(tx - px) + abs(ty - py)
                if dist < best_dist:
                    best_dist, best = dist, (tx, ty, dist)
        return best

    def _stairs_move(self, px: int, py: int) -> Optional[tuple[int, int]]:
        """Best stairs action right now, or None when every route is blocked.

        Nearest stairs first.  A route that walks *around* every monster is
        always preferred.  A route that must cross a monster tile is only
        taken when the fight it commits to is survivable — and the vetting
        looks at the FIRST MONSTER ON THE WHOLE PATH, not just the first
        step: the blocker usually sits several tiles ahead, and checking
        only the first step let the bot stroll into an elite's face, refuse
        the fight, stroll back, and repeat forever (measured: floor 5,
        5810 steps without descending, 1 kill — the floor had weapons,
        armor and merchants the bot never went for).

        When every known stairs sits behind an unbeatable monster this
        returns None, so the caller falls through to farming and loot: the
        bot goes and gets stronger instead of pacing at the door.  Once it
        can win the exchange, the same route opens up by itself.
        """
        stairs = []
        for tile in self.world.map_data.values():
            if tile.get("stairs"):
                tx, ty = tile["x"], tile["y"]
                if (tx, ty) != (px, py):
                    stairs.append((abs(tx - px) + abs(ty - py), tx, ty))
        stairs.sort()

        for _, sx, sy in stairs:
            # Preferred: a route that never touches a monster tile.
            path = self._bfs_path(px, py, sx, sy, avoid_monsters=True)
            if path:
                self._set_route(path)
                return self._follow_route(px, py)
            # Blocked: only fight through a monster we can actually beat.
            path = self._bfs_path(px, py, sx, sy, avoid_monsters=False)
            if not path:
                continue
            blocker = self._path_first_monster(px, py, sx, sy)
            if blocker is None:
                self._set_route(path)
                return self._follow_route(px, py)
            bx, by = blocker
            tile = self.world.get_tile(bx, by)
            if (tile and tile.get("monster")
                    and self._fight_is_safe(tile["monster"])):
                self._set_route(path)
                return self._follow_route(px, py)
        return None

    # ---- route commitment ----

    def _set_route(self, path: list[tuple[int, int]]):
        """Commit to a walk route: ``path`` lists the tiles ahead of the
        player, target included (output of :meth:`_bfs_path`)."""
        self._route = list(path)
        self._route_floor = self.world.current_floor

    def _follow_route(self, px: int, py: int) -> Optional[tuple[int, int]]:
        """Next step along the committed route, or None when it is stale.

        Stale means: floor changed, the player was diverted off the route
        (item pickup, a fight), the route is exhausted, or the next tile is
        no longer walkable.  A monster on the next tile invalidates the
        route — the safety-scanned phases that run before this one already
        had their chance to engage it, so refusing here re-plans around it.
        """
        route = self._route
        if not route or self._route_floor != self.world.current_floor:
            self._route = None
            return None
        # Tiles the player has already walked onto.
        while route and route[0] == (px, py):
            route.pop(0)
        if not route:
            self._route = None
            return None
        nx, ny = route[0]
        if max(abs(nx - px), abs(ny - py)) != 1:
            # Diverted off-route: drop the commitment and re-plan.
            self._route = None
            return None
        tile = self.world.get_tile(nx, ny)
        if not tile or tile.get("type") == "wall" or tile.get("monster"):
            self._route = None
            return None
        return (nx - px, ny - py)

    def _path_first_monster(
        self, sx: int, sy: int, tx: int, ty: int
    ) -> Optional[tuple[int, int]]:
        """First monster tile on the shortest walkable path, or None.

        Monster tiles are passable here (this answers "what would we bump
        into on the way?"), so the reported tile is the fight a through-
        route actually commits to — which may be several tiles ahead of
        the first step.
        """
        path = self._bfs_path(sx, sy, tx, ty, avoid_monsters=False)
        if not path:
            return None
        for x, y in path:
            tile = self.world.get_tile(x, y)
            if tile and tile.get("monster"):
                return (x, y)
        return None

    def _bfs_step(
        self, sx: int, sy: int, tx: int, ty: int,
        max_depth: int = 50, avoid_monsters: bool = False,
    ) -> Optional[tuple[int, int]]:
        """BFS pathfinding. When avoid_monsters=True, treat monster
        tiles as obstacles (don't walk through dangerous fights)."""
        if sx == tx and sy == ty:
            return None

        queue: deque = deque()
        queue.append((sx, sy, None, 0))
        visited: set = {(sx, sy)}

        while queue:
            cx, cy, first_step, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for dx, dy in DIRS:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in visited:
                    continue
                if nx == tx and ny == ty:
                    return first_step if first_step is not None else (dx, dy)

                tile = self.world.get_tile(nx, ny)
                if not tile or tile.get("type") == "wall":
                    continue
                # When avoiding monsters, treat monster tiles as walls
                if avoid_monsters and tile.get("monster"):
                    continue

                visited.add((nx, ny))
                fs = first_step if first_step is not None else (dx, dy)
                queue.append((nx, ny, fs, depth + 1))

        return None

    def _bfs_path(
        self, sx: int, sy: int, tx: int, ty: int,
        max_depth: int = 80, avoid_monsters: bool = False,
    ) -> Optional[list[tuple[int, int]]]:
        """Full walkable path as the list of tiles AFTER the start, target
        included; None when unreachable.  Same traversal rules as
        ``_bfs_step`` — the whole path is what route commitment needs,
        because re-deriving only the first step each tick lets adjacent
        tiles with contradictory first steps oscillate forever."""
        if sx == tx and sy == ty:
            return None

        prev: dict[tuple[int, int], Optional[tuple[int, int]]] = {(sx, sy): None}
        queue: deque = deque([(sx, sy, 0)])

        while queue:
            cx, cy, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for dx, dy in DIRS:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in prev:
                    continue
                if nx == tx and ny == ty:
                    path = [(tx, ty)]
                    cur: Optional[tuple[int, int]] = (cx, cy)
                    while cur is not None:
                        path.append(cur)
                        cur = prev[cur]
                    path.reverse()
                    return path[1:]
                tile = self.world.get_tile(nx, ny)
                if not tile or tile.get("type") == "wall":
                    continue
                if avoid_monsters and tile.get("monster"):
                    continue
                prev[(nx, ny)] = (cx, cy)
                queue.append((nx, ny, depth + 1))

        return None

    # ---- Stuck detection ----

    def _is_looping(self) -> bool:
        """Detect N-position loops (A-B-A-B or A-B-C-A-B-C)."""
        recent = list(self._pos_history)
        n = len(recent)
        if n < 6:
            return False

        # Check for N-position loop: last N == previous N
        for size in (2, 3):
            if n >= size * 2:
                if recent[-size:] == recent[-size * 2:-size]:
                    return True

        return False

    # ---- Breakout when stuck ----

    def _force_breakout(self, px: int, py: int) -> Optional[tuple[int, int]]:
        """When stuck looping, force a move toward ANY new area."""
        # Collect all valid adjacent moves
        valid: list[tuple[int, int]] = []
        for dx, dy in DIRS:
            tile = self.world.get_tile(px + dx, py + dy)
            if not tile or tile.get("type") == "wall":
                continue
            # Never break *into* a fight we cannot win: breakout fires
            # before the safety-scanned phases, so an unvetted monster tile
            # here is a blind step into a lethal exchange.
            if tile.get("monster") and not self._fight_is_safe(tile["monster"]):
                continue
            # Prefer directions that lead to tiles we haven't visited recently
            nx, ny = px + dx, py + dy
            is_new = all(
                (nx, ny) != (hx, hy)
                for hx, hy in list(self._pos_history)[-10:]
            )
            valid.append((dx, dy, is_new))

        if not valid:
            return None
        # Sort: new areas first, then random among them
        valid.sort(key=lambda v: -v[2])
        best = [v for v in valid if v[2]]
        pool = best if best else valid
        dx, dy, _ = random.choice(pool)
        self._stuck_frames = 0  # reset after forcing breakout
        return (dx, dy)

    # ---- Simple fallback: any valid direction ----

    def _any_valid_move(self, px: int, py: int) -> Optional[tuple[int, int]]:
        """Pick any valid adjacent move. No bias — just don't go back into a wall.

        Monster tiles are a last resort: stepping into a fight should only
        happen when there is genuinely nothing else to do.
        """
        candidates: list[tuple[int, int]] = []
        escape: list[tuple[int, int]] = []      # non-monster, but a reversal
        fights: list[tuple[tuple[int, int], dict]] = []
        reverse = (-self._last_direction[0], -self._last_direction[1]) if self._last_direction else None

        for dx, dy in DIRS:
            tile = self.world.get_tile(px + dx, py + dy)
            if not tile or tile.get("type") == "wall":
                continue
            rev = bool(reverse and (dx, dy) == reverse)
            if tile.get("monster"):
                fights.append(((dx, dy), tile["monster"]))
            elif rev:
                # Only avoid exact immediate reversal (not all history)
                escape.append((dx, dy))
            else:
                candidates.append((dx, dy))

        # Dead end guarded by a monster: back out instead of trading blows.
        # The old code returned *any* walkable tile here, so a bot cornered by
        # an unbeatable monster attacked it every turn until it died.
        pool = candidates or escape
        if pool:
            return random.choice(pool)

        # Genuinely boxed in by monsters: fight only a winning exchange,
        # otherwise hold position and wait for the player to take over.
        for move, monster in fights:
            if self._fight_is_safe(monster):
                self._engaged = (px + move[0], py + move[1])
                return move
        return None
