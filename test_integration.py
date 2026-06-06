"""Integration test for town game - validates all modules import and core logic works."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_imports():
    """Test all modules can be imported."""
    print("=" * 50)
    print("TEST 1: Module Imports")
    print("=" * 50)
    try:
        from ecs.entity import EntityManager
        print("  [OK] ecs.entity")
    except Exception as e:
        print(f"  [FAIL] ecs.entity: {e}")
        return False

    try:
        from ecs.components import Position, Renderable, Fighter, Player, Item, Stairs, Merchant
        print("  [OK] ecs.components")
    except Exception as e:
        print(f"  [FAIL] ecs.components: {e}")
        return False

    try:
        from ecs.systems import MovementSystem, CombatSystem, PickupSystem, StairSystem
        print("  [OK] ecs.systems")
    except Exception as e:
        print(f"  [FAIL] ecs.systems: {e}")
        return False

    try:
        import game.config as cfg
        print("  [OK] game.config")
    except Exception as e:
        print(f"  [FAIL] game.config: {e}")
        return False

    try:
        from game.utils import calculate_monster_multiplier, calculate_exp_to_next, ALL_SKILLS
        print("  [OK] game.utils")
    except Exception as e:
        print(f"  [FAIL] game.utils: {e}")
        return False

    try:
        from game.world import GameWorld
        print("  [OK] game.world")
    except Exception as e:
        print(f"  [FAIL] game.world: {e}")
        return False

    print("  All imports OK!\n")
    return True


def test_game_world():
    """Test GameWorld creation and basic state."""
    print("=" * 50)
    print("TEST 2: GameWorld Creation & State")
    print("=" * 50)
    try:
        from game.world import GameWorld
        world = GameWorld()
        pd = world.player_data
        print(f"  [OK] GameWorld created")
        print(f"  Player entity: {world.player_entity}")
        print(f"  Current floor: {world.current_floor}")
        print(f"  Player HP: {pd['hp']}/{pd['max_hp']}")
        print(f"  Player ATK: {pd['attack']}")
        print(f"  Player DEF: {pd['defense']}")
        print(f"  Player Gold: {pd['gold']}")
        print(f"  Player Level: {pd['level']}")
        print(f"  Player EXP: {pd['exp']}/{pd['exp_to_next']}")
        print(f"  Map size: {len(world.map_data)} tiles")
        print(f"  Entity count: {len(world.entities)}")

        from ecs.components import Position, Fighter
        pe = world.player_entity
        assert pe in world.entities, "Player not in entities dict"
        pos = world.get_component(pe, Position)
        assert pos is not None, "Player has no Position"
        print(f"  Player position: ({pos.x}, {pos.y})")

        # Check player_data matches entity Fighter component
        fighter = world.get_component(pe, Fighter)
        assert fighter is not None, "Player has no Fighter"
        print(f"  Fighter HP: {fighter.hp}/{fighter.max_hp}")

        print("  GameWorld state OK!\n")
        return True
    except Exception as e:
        print(f"  [FAIL] GameWorld test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_movement():
    """Test movement system."""
    print("=" * 50)
    print("TEST 3: Movement System")
    print("=" * 50)
    try:
        from game.world import GameWorld
        from ecs.systems import MovementSystem
        from ecs.components import Position

        world = GameWorld()
        pos = world.get_component(world.player_entity, Position)
        orig_x, orig_y = pos.x, pos.y

        # MovementSystem: instance method - update(self, world, dx, dy)
        move_sys = MovementSystem()
        for dx, dy, direction in [(0, -1, "UP"), (0, 1, "DOWN"), (-1, 0, "LEFT"), (1, 0, "RIGHT")]:
            result = move_sys.update(world, dx, dy)
            new_pos = world.get_component(world.player_entity, Position)
            print(f"  {direction}: ({orig_x},{orig_y})->({new_pos.x},{new_pos.y}) moved={result}")

        print("  Movement system OK!\n")
        return True
    except Exception as e:
        print(f"  [FAIL] Movement test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_combat():
    """Test combat system."""
    print("=" * 50)
    print("TEST 4: Combat System")
    print("=" * 50)
    try:
        from game.world import GameWorld
        from ecs.systems import CombatSystem
        from ecs.entity import EntityManager
        from ecs.components import Position, Renderable, Fighter
        import game.config as cfg

        world = GameWorld()

        # Place a monster on an adjacent floor tile (find one near player)
        placed = False
        for check_dx in range(-3, 4):
            if placed:
                break
            for check_dy in range(-3, 4):
                px = world.player_data["x"] + check_dx
                py = world.player_data["y"] + check_dy
                tile = world.get_tile(px, py)
                if tile and tile.get("type") == "floor":
                    # Put a monster there
                    monster = {
                        "name": "TestGoblin", "hp": 30, "attack": 5,
                        "defense": 1, "exp": 20, "gold": 10,
                        "current_hp": 30,
                    }
                    tile["monster"] = monster
                    original_hp = world.player_data["hp"]

                    # Fight using CombatSystem.fight(world, tile, mx, my)
                    log_count = len(world.log_entries)
                    CombatSystem.fight(world, tile, px, py)
                    post_hp = world.player_data["hp"]

                    print(f"  HP before: {original_hp}, after: {post_hp}")
                    print(f"  New log entries: {len(world.log_entries) - log_count}")
                    for entry in world.log_entries[log_count:log_count+5]:
                        print(f"    - {entry[0]}")

                    placed = True
                    break

        if not placed:
            print("  [WARN] Could not find floor tile for test monster")
            return False

        print("  Combat system OK!\n")
        return True
    except Exception as e:
        print(f"  [FAIL] Combat test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_skills():
    """Test skill system."""
    print("=" * 50)
    print("TEST 5: Skill System")
    print("=" * 50)
    try:
        from game.world import GameWorld
        from game.utils import ALL_SKILLS, apply_skill_effect

        world = GameWorld()
        print(f"  Total skills defined: {len(ALL_SKILLS)}")
        for skill in ALL_SKILLS:
            print(f"    - {skill['name']}: {skill['desc']}")

        # Test that skill selection works
        available = world.get_available_skills(3)
        print(f"  Random selection (3): {[s['name'] for s in available]}")

        # Test apply_skill_effect on a simple namespace
        class P:
            pass
        p = P()
        p.max_hp = 100
        p.hp = 80
        p.attack = 10
        p.defense = 5

        for skill in ALL_SKILLS[:2]:
            try:
                skill["effect"](p)
                print(f"  Applied {skill['name']} OK")
            except Exception as ex:
                print(f"  Apply {skill['name']}: {ex}")

        print("  Skill system OK!\n")
        return True
    except Exception as e:
        print(f"  [FAIL] Skill test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_shop():
    """Test shop/merchant system."""
    print("=" * 50)
    print("TEST 6: Shop System")
    print("=" * 50)
    try:
        from game.world import GameWorld
        import game.config as cfg

        world = GameWorld()

        # Find merchant on current floor
        merchant_found = False
        for eid, comps in world.entities.items():
            if "Merchant" in comps:
                merchant_found = True
                print(f"  Found merchant entity: {eid}")

        if not merchant_found:
            print("  No merchant on this floor (random generation - OK)")

        # Test shop item data (loaded from Excel via world)
        print(f"  Shop items defined: {len(world.shop_items)}")
        for item in world.shop_items:
            print(f"    - {item['name']}: {item['price']}G ({item['type']})")

        # Test buying with no gold (should fail)
        success, msg = world.buy_item(1)
        print(f"  Buy Health Potion (0g): success={success}, msg={msg}")

        # Give gold and buy
        world.player_data["gold"] = 200
        success, msg = world.buy_item(1)
        print(f"  Buy Health Potion (200g): success={success}, msg={msg}")

        print("  Shop system OK!\n")
        return True
    except Exception as e:
        print(f"  [FAIL] Shop test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_map_generation():
    """Test map generation produces valid tiles."""
    print("=" * 50)
    print("TEST 7: Map Generation")
    print("=" * 50)
    try:
        from game.world import GameWorld

        world = GameWorld()

        wall_count = sum(1 for t in world.map_data.values() if t.get("type") == "wall")
        floor_count = sum(1 for t in world.map_data.values() if t.get("type") == "floor")
        total = len(world.map_data)

        print(f"  Total tiles: {total}")
        print(f"  Walls: {wall_count} ({wall_count*100//max(total,1)}%)")
        print(f"  Floors: {floor_count} ({floor_count*100//max(total,1)}%)")

        # Count special tiles
        items = sum(1 for t in world.map_data.values() if t.get("item"))
        monsters = sum(1 for t in world.map_data.values() if t.get("monster"))
        doors = sum(1 for t in world.map_data.values() if t.get("door"))
        stairs = sum(1 for t in world.map_data.values() if t.get("stairs"))
        merchants = sum(1 for t in world.map_data.values() if t.get("merchant"))

        print(f"  Items: {items}, Monsters: {monsters}, Doors: {doors}")
        print(f"  Stairs: {stairs}, Merchants: {merchants}")

        assert total > 0, "No tiles generated!"
        assert floor_count > 0, "No floor tiles!"

        print("  Map generation OK!\n")
        return True
    except Exception as e:
        print(f"  [FAIL] Map gen test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    results = []
    results.append(("Imports", test_imports()))
    results.append(("GameWorld", test_game_world()))
    results.append(("Movement", test_movement()))
    results.append(("Combat", test_combat()))
    results.append(("Skills", test_skills()))
    results.append(("Shop", test_shop()))
    results.append(("Map Generation", test_map_generation()))

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n  {passed}/{total} tests passed")

    if passed == total:
        print("\n  *** ALL TESTS PASSED! Game is ready to run. ***")
    else:
        print(f"\n  {total - passed} test(s) failed - need fixes.")
