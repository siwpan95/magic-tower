"""Headless self-check for the Magic Tower ECS game logic.

Imports only the non-UI layers (``ecs`` + ``game.world``); the Tkinter UI
(``ui.tkinter_ui``) is never imported, so no window is created.

Checks:
  1. Excel content loading + player/map initialisation.
  2. Movement with collision (blocked by walls, advances onto floors).
  3. Combat rewards and monster removal.
  4. Stair descent advances the floor and regenerates the map.
  5. Pure helpers (EXP curve, floor multiplier).

Run from the project root::

    python selfcheck.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ecs.components import Fighter, Position
from game.utils import calculate_exp_to_next, calculate_monster_multiplier
from game.world import GameWorld


def check_world_init():
    world = GameWorld()
    pd = world.player_data
    if pd["level"] != 1 or pd["exp"] != 0:
        raise AssertionError("player did not start at level 1 / 0 exp")
    if pd["hp"] != pd["max_hp"] or pd["hp"] <= 0:
        raise AssertionError("player HP initialisation is inconsistent")
    if pd["attack"] <= 0 or pd["defense"] <= 0:
        raise AssertionError("player combat stats were not loaded")
    if world.get_tile(0, 0) is None or world.get_tile(0, 0)["type"] != "floor":
        raise AssertionError("player spawn tile is not walkable")
    if len(world.map_data) <= 1:
        raise AssertionError("initial map was not generated")
    if not world.shop_items:
        raise AssertionError("shop data was not loaded from Excel")

    pos = world.get_component(world.player_entity, Position)
    fighter = world.get_component(world.player_entity, Fighter)
    if pos is None or fighter is None:
        raise AssertionError("player ECS components are missing")
    if (pos.x, pos.y) != (pd["x"], pd["y"]):
        raise AssertionError("ECS position out of sync with player_data")


def check_movement_and_collision():
    world = GameWorld()

    # Carve a guaranteed walkable target and step onto it.
    world.set_tile(1, 0, {"type": "floor", "char": ".", "x": 1, "y": 0})
    world.move_player(1, 0)
    if world.get_player_position() != (1, 0):
        raise AssertionError("player did not move onto an open floor tile")
    if world.player_data["x"] != 1 or world.player_data["y"] != 0:
        raise AssertionError("player_data not synced after movement")

    # A wall must block movement and keep both position copies unchanged.
    world.set_tile(2, 0, {"type": "wall", "char": "#", "x": 2, "y": 0})
    world.move_player(1, 0)
    if world.get_player_position() != (1, 0):
        raise AssertionError("player walked through a wall")
    if world.player_data["x"] != 1:
        raise AssertionError("player_data desynced after blocked move")


def check_combat():
    world = GameWorld()
    world.set_tile(1, 0, {
        "type": "floor", "char": "g", "x": 1, "y": 0,
        "monster": {
            "name": "SelfCheck Slime", "hp": 5, "current_hp": 5,
            "attack": 1, "defense": 0, "exp": 20, "gold": 7,
        },
    })
    gold_before = world.player_data["gold"]
    exp_before = world.player_data["exp"]
    world.move_player(1, 0)

    tile = world.get_tile(1, 0)
    if tile.get("monster") is not None:
        raise AssertionError("defeated monster was not removed from the tile")
    if world.player_data["gold"] != gold_before + 7:
        raise AssertionError("combat gold reward was not granted")
    if world.player_data["exp"] <= exp_before:
        raise AssertionError("combat EXP reward was not granted")
    if world.get_player_position() != (1, 0):
        raise AssertionError("player did not step onto the cleared tile")


def check_stairs_progress():
    world = GameWorld()
    world.set_tile(1, 0, {
        "type": "floor", "char": ">", "x": 1, "y": 0, "stairs": True,
    })
    old_floor = world.current_floor
    old_tiles = dict(world.map_data)
    world.move_player(1, 0)

    if world.current_floor != old_floor + 1:
        raise AssertionError("stairs did not advance the floor")
    if len(world.map_data) == 0:
        raise AssertionError("new floor map was not generated")
    if world.get_player_position() != (0, 0):
        raise AssertionError("player position was not reset on the new floor")
    if world.get_tile(0, 0) is None or world.get_tile(0, 0)["type"] != "floor":
        raise AssertionError("new floor spawn tile is not walkable")
    if world.map_data == old_tiles:
        raise AssertionError("map was not regenerated on descent")

    world.current_floor = 3
    if world.monster_multiplier() != 4:
        raise AssertionError("monster multiplier should be 4 on floor 3")


def check_helpers():
    if calculate_monster_multiplier(1) != 1 or \
            calculate_monster_multiplier(4) != 8:
        raise AssertionError("monster multiplier broken")
    if calculate_exp_to_next(1) != 100 or calculate_exp_to_next(2) != 282:
        raise AssertionError("EXP curve broken")
    if calculate_exp_to_next(3) <= calculate_exp_to_next(2):
        raise AssertionError("EXP curve is not increasing")


def main():
    try:
        check_world_init()
        check_movement_and_collision()
        check_combat()
        check_stairs_progress()
        check_helpers()
    except Exception as exc:  # noqa: BLE001 - report, never traceback-crash
        print("FAIL: %s: %s" % (type(exc).__name__, exc))
        return 1
    print("selfcheck ok: Excel data load, ECS player init, movement/collision, "
          "combat rewards, stair floor progression, EXP/multiplier helpers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
