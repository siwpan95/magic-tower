"""Game world core: ECS container, map generation, player state, events."""

from __future__ import annotations

import json
import math
import os
import random
from typing import Any, Callable, Optional

from ecs.components import (
    Fighter,
    Item,
    Merchant,
    Player,
    Position,
    Renderable,
    Stairs,
)
from ecs.entity import EntityManager
from game import config as cfg
from game.worldgen import WorldGenerator, chunk_index


class GameWorld:
    """Central ECS world holding all entities, components, and game state."""

    def __init__(self):
        # --- Load game content data from Excel ---
        from game.data_loader import GameDataLoader
        _loader = GameDataLoader()
        self._game_data: dict[str, Any] = _loader.load_all()

        # --- ECS storage ---
        self.entities: dict[int, dict] = {}   # eid -> {component_type: instance}
        self.player_entity: Optional[int] = None

        # --- Game state ---
        self.current_floor: int = 1
        self.map_data: dict[str, dict] = {}  # "x,y" -> tile dict
        self.game_over: bool = False
        self.running: bool = True
        self.boss_defeated: bool = False
        self.boss_floor_shown: bool = False
        # Boss floors are a single arena, not one per chunk (see
        # generate_area_around).  Tracks which floor the arena belongs to.
        self._boss_arena_floor: Optional[int] = None
        self.open_shop: bool = False

        # --- Auto-play state ---
        self.auto_play: bool = False

        # --- Progress tracking ---
        self.progress_value: float = 0.0   # 0.0 – 1.0
        self.progress_text: str = ""       # e.g. "Floor 3 · exploring..."

        # --- Player base stats from Excel (fallback to defaults) ---
        _pb = self._game_data.get("PLAYER_BASE", {"hp": 100, "attack": 10, "defense": 5})

        # --- Player data (plain dict for simplicity) ---
        self.player_data: dict[str, Any] = {
            "x": 0, "y": 0,
            "hp": _pb["hp"], "max_hp": _pb["hp"],
            "attack": _pb["attack"], "defense": _pb["defense"],
            "level": 1, "exp": 0,
            "exp_to_next": cfg.EXP_BASE,
            "gold": 0, "skill_points": 0,
            "keys": 0,
            "inventory": [],         # [{name, desc, type, ...}]
        }

        # --- Skills & buffs ---
        self.learned_skills: list[dict] = []   # [{"id", "name", "level"}]
        self.active_buffs: list[dict] = []     # [{"name", "duration", "effects": {...}}]

        # --- Shop (fresh copy from Excel) ---
        from game.utils import deep_copy_shop_items
        self.shop_items: list[dict] = deep_copy_shop_items(
            self._game_data.get("SHOP_ITEMS", [])
        )

        # --- Config reference: engine constants from config.py + content from Excel ---
        self.config: dict[str, Any] = {
            k: v for k, v in vars(cfg).items()
            if not k.startswith("_") and k.isupper()
        }
        self.config.update(self._game_data)  # Excel content data overlays

        # --- Procedural world generation (worldbuilder adapter) ---
        self.generator = WorldGenerator(self)
        self._cleaned_for: Optional[tuple] = None   # last pos we pruned around

        # --- Log ---
        self.log_entries: list[tuple[str, str]] = []  # (message, type)

        # --- Event system ---
        self._handlers: dict[str, list[Callable]] = {}

        # Initialize
        self._init_player_entity()
        self.generate_initial_map()
        self.add_log("Entered the mysterious dungeon. Adventure begins!", "system")
        self.add_log("Defeat monsters for EXP and gold. Level up to learn skills!", "system")
        self.add_log("Find Merchant (M) to buy items!", "system")
        self.add_log("WARNING: Monster stats DOUBLE every floor!", "warning")
        self.add_log("Every 18th floor is a BOSS room. Defeat the boss to proceed!", "warning")

    # ---- Entity / Component API ----

    def create_entity(self) -> int:
        eid = EntityManager.create()
        self.entities[eid] = {}
        return eid

    def add_component(self, eid: int, component):
        """Add a component to an entity."""
        ctype = type(component).__name__
        if eid not in self.entities:
            self.entities[eid] = {}
        self.entities[eid][ctype] = component

    def get_component(self, eid: int, component_cls):
        """Get a specific component type from entity, or None."""
        entity_components = self.entities.get(eid)
        if entity_components is None:
            return None
        return entity_components.get(component_cls.__name__)

    def get_components(self, *component_clz):
        """Yield (eid, tuple_of_components) for entities that have ALL given types."""
        names = [c.__name__ for c in component_clz]
        for eid, comps in self.entities.items():
            if all(n in comps for n in names):
                yield eid, tuple(comps[n] for n in names)

    def remove_entity(self, eid: int):
        self.entities.pop(eid, None)

    # ---- Player shortcuts ----

    def _init_player_entity(self):
        eid = self.create_entity()
        self.player_entity = eid
        self.add_component(eid, Position(x=0, y=0))
        self.add_component(eid, Renderable(char=cfg.TILES["PLAYER"], color="yellow"))
        self.add_component(eid, Fighter(
            hp=self.player_data["hp"],
            max_hp=self.player_data["max_hp"],
            attack=self.player_data["attack"],
            defense=self.player_data["defense"],
        ))
        self.add_component(eid, Player(
            level=1, exp=0, exp_to_next=cfg.EXP_BASE,
            skill_points=0, gold=0, keys=0,
        ))

    def get_player(self):
        return self.player_entity

    def get_player_position(self) -> tuple[int, int]:
        """Read canonical position from ECS Position component."""
        pos = self.get_component(self.player_entity, Position)
        if pos:
            return pos.x, pos.y
        # Fallback during init before component exists
        return self.player_data["x"], self.player_data["y"]

    # ---- Map management ----

    def get_tile(self, x: int, y: int) -> Optional[dict]:
        return self.map_data.get(f"{x},{y}")

    def set_tile(self, x: int, y: int, tile: dict):
        self.map_data[f"{x},{y}"] = tile

    def monster_multiplier(self) -> float:
        """Linear per-floor scaling on top of the CR-based bestiary tiers.

        Was ``2 ** (floor - 1)`` (floor 20 => 524288x), which combined with the
        bestiary's own CR curve produced a double-exponential difficulty wall:
        average monster HP hit ~9e7 by floor 20 and every run ended in a
        one-shot.  Now the multiplier is gentle (1 + 0.10*(floor-1)) because the
        *species mix* already escalates with depth — floor 1 fields Kobolds,
        floor 20 fields Pit Fiends.
        """
        per = float(self.config.get("FLOOR_MONSTER_MULT", cfg.FLOOR_MONSTER_MULT))
        return 1.0 + per * (self.current_floor - 1)

    # ---- Map generation ----

    def generate_initial_map(self):
        """Generate the initial area around player."""
        self.player_data["x"] = 0
        self.player_data["y"] = 0
        self.generator.clear_cache()
        self.generate_area_around(0, 0)
        self.ensure_player_on_floor()

    def generate_area_around(self, cx: int, cy: int):
        """Generate tiles in radius around center.

        Boss floors keep their hand-built arena; every other floor is an
        infinite chunked dungeon produced by the worldbuilder adapter.
        """
        is_boss_floor = self.current_floor % cfg.BOSS_FLOOR_INTERVAL == 0

        if is_boss_floor:
            # One arena per boss floor.  Building a room for *every* chunk
            # that materialised meant: a fresh boss each time, boss_defeated
            # reset to False, and the player teleported to the new room's
            # entry — so the boss could never be cleared and the floor was a
            # dead end.
            if self._boss_arena_floor != self.current_floor:
                self._boss_arena_floor = self.current_floor
                self._generate_boss_room(cx, cy)
            return

        # New floor (or fresh start): drop cached layouts so this floor's
        # deterministic seed space restarts, then materialise around (cx, cy).
        self.generator.clear_cache()
        radius = 5
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                self._ensure_tile(cx + dx, cy + dy)

    def _ensure_tile(self, x: int, y: int):
        """Materialise the chunk containing (x, y) when the tile is missing.

        Existing tiles are never overwritten (no-overwrite semantics), so
        player progress inside a chunk survives lazy regeneration.
        """
        key = f"{x},{y}"
        if key in self.map_data:
            return
        size = self.generator.chunk_size
        self.generator.materialize_chunk(
            chunk_index(x, size), chunk_index(y, size))

    def _generate_boss_room(self, cx: int, cy: int):
        size = cfg.BOSS_ROOM_SIZE
        mult = self.monster_multiplier()

        for dx in range(-size, size + 1):
            for dy in range(-size, size + 1):
                x, y = cx + dx, cy + dy
                key = f"{x},{y}"

                if abs(dx) == size or abs(dy) == size:
                    tile = {"type": "wall", "char": cfg.TILES["WALL"], "x": x, "y": y}
                else:
                    tile = {
                        "type": "floor",
                        "char": cfg.TILES["FLOOR"],
                        "x": x, "y": y,
                    }

                    if dx == 0 and dy == 0:
                        boss = {**self.config.get("BOSS_TEMPLATE", {})}
                        # Scale off the floor's strongest normal monster.  The
                        # old "template x floor multiplier" made the floor-18
                        # boss 5400 HP / 162 DEF against a ~106 ATK player:
                        # damage floored to 1/hit while it dealt 209, so the
                        # boss floor (a hard gate) could never be cleared.
                        ref = self.generator.strongest_unlocked()
                        hp_m = self.config.get("BOSS_HP_MULT", cfg.BOSS_HP_MULT)
                        at_m = self.config.get("BOSS_ATK_MULT", cfg.BOSS_ATK_MULT)
                        df_m = self.config.get("BOSS_DEF_MULT", cfg.BOSS_DEF_MULT)
                        if ref:
                            boss["hp"] = int(ref["hp"] * hp_m)
                            boss["attack"] = int(ref["attack"] * at_m)
                            boss["defense"] = int(ref["defense"] * df_m)
                            boss["exp"] = int(ref.get("exp", 100) * hp_m)
                            boss["gold"] = int(ref.get("gold", 50) * hp_m)
                        else:
                            # No pool (data file without monsters): old behaviour
                            boss["hp"] = int(boss["hp"] * mult)
                            boss["attack"] = int(boss["attack"] * mult)
                            boss["defense"] = int(boss["defense"] * mult)
                        boss["current_hp"] = boss["hp"]
                        # Both spellings: the world/UI side reads "isBoss",
                        # the combat system historically read "is_boss".
                        boss["isBoss"] = True
                        boss["is_boss"] = True
                        # Generated epithet, e.g. "Demon Lord「Vorwyn」"
                        boss["name"] = self.generator.elite_name(
                            boss.get("name", "Demon Lord"))
                        tile["monster"] = boss
                        self.boss_defeated = False

                    # Entry at bottom-center
                    if dx == 0 and dy == size - 1:
                        self.player_data["x"] = x
                        self.player_data["y"] = y
                        # Sync to ECS Position component
                        epos = self.get_component(self.player_entity, Position)
                        if epos:
                            epos.x = x
                            epos.y = y

                    # Exit at top-center (stairs after boss dies)
                    if dx == 0 and dy == -(size - 1):
                        if self.boss_defeated:
                            tile["stairs"] = True
                            tile["type"] = "floor"
                            tile["char"] = cfg.TILES["STAIRS"]
                        else:
                            tile = {"type": "wall", "char": cfg.TILES["WALL"],
                                    "x": x, "y": y}

                self.map_data[key] = tile

        self.boss_floor_shown = True

    def _spawn_stairs_at_boss_room(self, mx: int, my: int):
        """After boss death, place stairs at the room exit."""
        size = cfg.BOSS_ROOM_SIZE
        for dx in range(-(size - 1), size):
            for dy in range(-(size - 1), size):
                if dx == 0 and dy == -(size - 1):
                    key = f"{mx + dx},{my + dy}"
                    tile = self.map_data.get(key)
                    if tile:
                        tile["stairs"] = True
                        tile["type"] = "floor"
                        tile["char"] = cfg.TILES["STAIRS"]
                    return

    def ensure_player_on_floor(self):
        pk = f"{self.player_data['x']},{self.player_data['y']}"
        if pk not in self.map_data or self.map_data[pk].get("type") == "wall":
            self.map_data[pk] = {
                "type": "floor",
                "char": cfg.TILES["FLOOR"],
                "x": self.player_data["x"],
                "y": self.player_data["y"],
            }

    # ---- Visibility helpers for rendering ----

    def get_visible_area(self) -> tuple[int, int, int, int]:
        hw = cfg.SCREEN_WIDTH // 2
        hh = cfg.SCREEN_HEIGHT // 2
        px, py = self.player_data["x"], self.player_data["y"]
        return (px - hw, py - hh, px + hw, py + hh)

    def get_visible_entities(self):
        """Return (eid, (Position, Renderable)) pairs within visible area."""
        x1, y1, x2, y2 = self.get_visible_area()
        result = []
        for eid, (pos, rend) in self.get_components(Position, Renderable):
            if x1 <= pos.x <= x2 and y1 <= pos.y <= y2:
                result.append((eid, (pos, rend)))
        return result

    def ensure_visible_tiles_generated(self, area=None):
        """Generate any tiles within view that don't exist yet.

        ``area`` lets the caller (the UI camera) ask for a box that is offset
        from the player, so a dead-zoned camera never shows ungenerated void.
        """
        x1, y1, x2, y2 = area if area is not None else self.get_visible_area()
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                self._ensure_tile(x, y)
        # Cleanup is O(map_data) with a key parse per tile; only the player
        # moving can push tiles out of range, so skip it on pure redraws.
        pos = (self.player_data["x"], self.player_data["y"])
        if pos != self._cleaned_for:
            self._cleaned_for = pos
            self._cleanup_distant_tiles()

    def _cleanup_distant_tiles(self):
        px, py = self.player_data["x"], self.player_data["y"]
        radius = cfg.CLEANUP_RADIUS
        keys_to_remove = [
            k for k in self.map_data
            if self._tile_distance(k, px, py) > radius
        ]
        for k in keys_to_remove:
            del self.map_data[k]

    def _tile_distance(self, key: str, px: int, py: int) -> float:
        try:
            x, y = key.split(",", 1)
            dx = abs(int(x) - px)
            dy = abs(int(y) - py)
        except (ValueError, IndexError):
            return float("inf")
        return max(dx, dy)

    # ---- Progress tracking ----

    def update_progress(self):
        """Calculate current floor progress (0.0 – 1.0) and a status text."""
        interval = self.config.get("BOSS_FLOOR_INTERVAL", 18)
        is_boss = self.current_floor % interval == 0

        if is_boss:
            # Boss floor: progress = boss defeated? 1.0 : 0.5
            self.progress_value = 1.0 if self.boss_defeated else 0.5
            self.progress_text = (
                f"Floor {self.current_floor} (BOSS) · "
                f"{'BOSS defeated!' if self.boss_defeated else 'Engage the BOSS!'}"
            )
        else:
            # Normal floor: progress based on how many generated tiles contain stairs
            stairs_found = any(t.get("stairs") for t in self.map_data.values())
            # Estimate progress: number of explored tiles / expected tiles
            explored = len(self.map_data)
            # Expected visible tiles ~ (SCREEN_WIDTH) * (SCREEN_HEIGHT) ≈ 800
            expected_max = 800
            tile_progress = min(1.0, explored / expected_max)
            if stairs_found:
                tile_progress = max(tile_progress, 0.85)

            self.progress_value = tile_progress
            self.progress_text = (
                f"Floor {self.current_floor} · "
                f"{'Stairs found!' if stairs_found else 'Exploring...'} "
                f"({explored} tiles)"
            )

    # ---- Event system ----

    def on(self, event_name: str, handler: Callable):
        self._handlers.setdefault(event_name, []).append(handler)

    def trigger(self, event_name: str, data=None):
        for h in self._handlers.get(event_name, []):
            h(data)

    # ---- Player actions ----

    def move_player(self, dx: int, dy: int):
        from ecs.systems import MovementSystem
        MovementSystem().update(self, dx, dy)

    # ---- Experience & Gold ----

    def gain_exp(self, amount: int):
        self.player_data["exp"] += amount
        self.add_log(f"Gained {amount} EXP.", "exp")

        while self.player_data["exp"] >= self.player_data["exp_to_next"]:
            self._level_up()

    def gain_gold(self, amount: int):
        self.player_data["gold"] += amount
        self.add_log(f"Gained {amount} gold.", "gold")

    def _level_up(self):
        pd = self.player_data
        pd["level"] += 1
        pd["exp"] -= pd["exp_to_next"]
        pd["exp_to_next"] = int(cfg.EXP_BASE * math.pow(pd["level"], 1.5))
        pd["max_hp"] += 10
        pd["hp"] = pd["max_hp"]
        pd["attack"] += 2
        pd["defense"] += 1
        pd["skill_points"] += 1

        self.add_log(f"LEVEL UP! Now Lv.{pd['level']}.", "level")
        self.add_log(f"+1 Skill Point (total: {pd['skill_points']})", "level")

    # ---- Skills ----

    def get_available_skills(self, count: int = 3) -> list[dict]:
        """Return random skills that can be learned/upgraded."""
        all_skills = self._game_data.get("ALL_SKILLS", [])
        available = []
        for s in all_skills:
            learned = next(
                (ls for ls in self.learned_skills if ls["id"] == s["id"]), None
            )
            if learned:
                if learned["level"] < s["max_level"]:
                    available.append(s)
            else:
                available.append(s)
        return random.sample(available, min(count, len(available))) if available else []

    def learn_skill(self, skill_def: dict):
        from game.utils import apply_skill_effect
        learned = next((ls for ls in self.learned_skills if ls["id"] == skill_def["id"]), None)
        if learned:
            learned["level"] += 1
            apply_skill_effect(self.player_data, skill_def)
            self.add_log(
                f"{skill_def['name']} upgraded to Lv.{learned['level']}!", "skill"
            )
        else:
            new_skill = {"id": skill_def["id"], "name": skill_def["name"],
                         "level": 1, "max_level": skill_def["max_level"]}
            self.learned_skills.append(new_skill)
            apply_skill_effect(self.player_data, skill_def)
            self.add_log(f"Learned new skill: {skill_def['name']}!", "skill")

        self.player_data["skill_points"] -= 1

    # ---- Buffs ----

    def add_buff(self, name: str, duration: int, effects: dict):
        existing = next((b for b in self.active_buffs if b["name"] == name), None)
        if existing:
            existing["duration"] += duration
        else:
            self.active_buffs.append({"name": name, "duration": duration, "effects": effects})

    def consume_buffs(self):
        expired = []
        for i, buff in enumerate(self.active_buffs):
            buff["duration"] -= 1
            if buff["duration"] <= 0:
                expired.append(i)
                self.add_log(f'Buff "{buff["name"]} faded.', "buff")
        for i in reversed(expired):
            self.active_buffs.pop(i)

    # ---- Shop ----

    def buy_item(self, item_id: int) -> tuple[bool, str]:
        """Attempt to buy shop item. Adds to inventory. Returns (success, message)."""
        item = next((it for it in self.shop_items if it["id"] == item_id), None)
        if not item:
            return False, "Item not found."
        if item["stock"] <= 0:
            return False, "Sold out."
        if self.player_data["gold"] < item["price"]:
            return False, "Not enough gold."

        self.player_data["gold"] -= item["price"]
        item["stock"] -= 1

        # Add to inventory (deep copy so shop stock is independent)
        import copy
        inv_item = {
            "shop_id": item["id"],
            "name": item["name"],
            "desc": item["desc"],
            "type": item["type"],
            "effect_target": item.get("effect_target"),
            "effect_value": item.get("effect_value"),
            "effect_duration": item.get("effect_duration"),
            "permanent_attr": item.get("permanent_attr"),
            "permanent_value": item.get("permanent_value"),
            "heal_value": item.get("heal_value"),
            "key_value": item.get("key_value"),
        }
        self.player_data.setdefault("inventory", []).append(inv_item)

        return True, f"Bought {item['name']}. Added to inventory."

    def use_inventory_item(self, index: int) -> tuple[bool, str]:
        """Use an item from inventory. Returns (success, message)."""
        inv = self.player_data.get("inventory", [])
        if index < 0 or index >= len(inv):
            return False, "Invalid inventory slot."
        item = inv[index]
        itype = item["type"]
        pd = self.player_data

        msg = ""
        if itype == "consumable":
            heal = item.get("heal_value", 50)
            pd["hp"] = min(pd["max_hp"], pd["hp"] + heal)
            msg = f"Used {item['name']}. Restored {heal} HP."
        elif itype == "permanent":
            attr = item.get("permanent_attr", "")
            val = item.get("permanent_value", 0)
            if attr in pd:
                pd[attr] += val
                pd["hp"] = min(pd["max_hp"], pd["hp"])  # sync hp cap
                msg = f"Used {item['name']}. Permanent {attr.upper()} +{val}."
            else:
                msg = f"Used {item['name']}."
        elif itype == "key":
            pd["keys"] += item.get("key_value", 1)
            msg = f"Used {item['name']}. Keys +{item.get('key_value', 1)}."
        elif itype == "buff":
            target = item.get("effect_target", "")
            val = item.get("effect_value", 0)
            dur = item.get("effect_duration", 3)
            eff = {}
            if target == "attack":
                eff = {"attack_multiplier": float(val)}
                self.add_buff(f"{item['name']} (+{val} ATK)", dur, eff)
            elif target == "defense":
                eff = {"defense_multiplier": float(val)}
                self.add_buff(f"{item['name']} (+{val} DEF)", dur, eff)
            msg = f"Used {item['name']}. {target.upper()} +{val} for {dur} fights."
        else:
            msg = f"Used {item['name']}."

        # Remove from inventory
        inv.pop(index)
        self.add_log(msg, "item")
        return True, msg

    # ---- Log ----

    def add_log(self, message: str, msg_type: str = "system"):
        self.log_entries.append((message, msg_type))
        # Keep only last 50 entries
        if len(self.log_entries) > 50:
            self.log_entries = self.log_entries[-50:]

    # ---- Save / Load ----

    @staticmethod
    def _save_path() -> str:
        # Save in the project root directory (next to main.py)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, "town_save.json")

    def save_game(self, path: str = None) -> bool:
        """Save current game state to JSON file. Returns True on success."""
        if path is None:
            path = self._save_path()
        import json

        # Convert log_entries tuples to lists for JSON
        log_serializable = [list(entry) for entry in self.log_entries]

        save_data = {
            "player_data": self.player_data,
            "current_floor": self.current_floor,
            "map_data": self.map_data,
            "learned_skills": self.learned_skills,
            "active_buffs": self.active_buffs,
            "shop_items": self.shop_items,
            "log_entries": log_serializable,
            "auto_play": self.auto_play,
            "boss_defeated": self.boss_defeated,
            "boss_floor_shown": self.boss_floor_shown,
            "game_over": self.game_over,
            "config_overrides": {
                k: v for k, v in self.config.items()
                if k in ("AUTO_MOVE_DELAY_MS",)
            },
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            self.add_log(f"Game saved.", "system")
            return True
        except Exception as e:
            self.add_log(f"Save failed: {e}", "warning")
            return False

    @classmethod
    def load_game(cls, path: str = None):
        """Load game state from JSON file. Returns GameWorld instance or None."""
        if path is None:
            path = cls._save_path()
        import json

        if not os.path.exists(path):
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                save_data = json.load(f)

            # Create a new world (initializes from Excel)
            world = cls()

            # Overwrite with saved state
            world.current_floor = save_data["current_floor"]
            world.map_data = save_data["map_data"]
            world.game_over = False
            world.running = True
            world.boss_defeated = save_data.get("boss_defeated", False)
            world.boss_floor_shown = save_data.get("boss_floor_shown", False)
            world.open_shop = False
            world.auto_play = save_data.get("auto_play", False)

            world.player_data = save_data["player_data"]
            world.learned_skills = save_data["learned_skills"]
            world.active_buffs = save_data["active_buffs"]
            world.shop_items = save_data["shop_items"]
            world.log_entries = [tuple(entry) for entry in save_data["log_entries"]]

            # Config overrides
            for k, v in save_data.get("config_overrides", {}).items():
                world.config[k] = v

            # Update ECS Fighter component
            fighter = world.get_component(world.player_entity, Fighter)
            if fighter:
                fighter.hp = world.player_data["hp"]
                fighter.max_hp = world.player_data["max_hp"]
                fighter.attack = world.player_data["attack"]
                fighter.defense = world.player_data["defense"]

            # Update ECS Player component
            player_comp = world.get_component(world.player_entity, Player)
            if player_comp:
                player_comp.level = world.player_data["level"]
                player_comp.exp = world.player_data["exp"]
                player_comp.exp_to_next = world.player_data["exp_to_next"]
                player_comp.skill_points = world.player_data["skill_points"]
                player_comp.gold = world.player_data["gold"]
                player_comp.keys = world.player_data["keys"]

            # Update ECS Position component
            pos = world.get_component(world.player_entity, Position)
            if pos:
                pos.x = world.player_data["x"]
                pos.y = world.player_data["y"]

            world.add_log("Game loaded.", "system")
            return world

        except Exception as e:
            print(f"Load failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def save_exists(path: str = None) -> bool:
        """Check if a save file exists."""
        if path is None:
            path = GameWorld._save_path()
        return os.path.exists(path)
