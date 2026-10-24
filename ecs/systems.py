"""ECS systems: movement, combat, pickup, stairs, interaction."""

from __future__ import annotations

from ecs.components import Fighter, Item, Merchant, Position, Player, Renderable, Stairs


class MovementSystem:
    """Handles player movement with collision detection."""

    def update(self, world, dx: int, dy: int):
        """Try to move player by (dx, dy). Returns True if moved."""
        from game.world import GameWorld
        assert isinstance(world, GameWorld)

        player_eid = world.player_entity
        if player_eid is None:
            return False
        pos = world.get_component(player_eid, Position)
        if pos is None:
            return False

        target_x = pos.x + dx
        target_y = pos.y + dy

        # Check what's at the target tile
        tile = world.get_tile(target_x, target_y)

        # Wall check
        if tile is None or tile.get("type") == "wall":
            world.add_log("Blocked by wall.", "action")
            return False

        # Door
        if tile.get("door"):
            if world.player_data["keys"] > 0:
                world.player_data["keys"] -= 1
                tile["door"] = False
                tile["char"] = world.config["TILES"]["FLOOR"]
                world.add_log(
                    f"Opened door. Keys left: {world.player_data['keys']}",
                    "action",
                )
            else:
                world.add_log("Door is locked. Need a key.", "action")
                return False

        # Merchant
        if tile.get("merchant"):
            self._interact_merchant(world, tile)
            return False

        # Monster -> combat
        if tile.get("monster"):
            CombatSystem.fight(world, tile, target_x, target_y)
            return False  # combat handles movement after kill

        # Item -> pickup
        if tile.get("item"):
            PickupSystem.pickup(world, tile, target_x, target_y)

        # Stairs -> descend
        if tile.get("stairs"):
            StairSystem.descend(world)
            return False

        # Regeneration per move
        hp_regen = world.player_data.get("hp_regen", 0)
        if hp_regen > 0:
            heal = int(world.player_data["max_hp"] * hp_regen)
            if heal > 0:
                world.player_data["hp"] = min(
                    world.player_data["max_hp"],
                    world.player_data["hp"] + heal,
                )
                world.add_log(f"Regenerated {heal} HP.", "heal")

        # Actually move
        pos.x = target_x
        pos.y = target_y
        # Sync canonical position back to player_data (used by boss room, stairs, etc.)
        world.player_data["x"] = target_x
        world.player_data["y"] = target_y
        world.trigger("player_moved", (target_x, target_y))
        return True

    @staticmethod
    def _interact_merchant(world, tile):
        world.add_log("Met the Mysterious Merchant!", "shop")
        world.open_shop = True
        # Remove merchant from tile so we don't loop on it
        del tile["merchant"]


class CombatSystem:
    """Handles turn-based combat between player and monster."""

    @staticmethod
    def fight(world, tile: dict, mx: int, my: int):
        monster = tile["monster"]
        # The boss room tags bosses as "isBoss"; some paths used "is_boss".
        # Reading only one of them silently disabled every boss-specific
        # branch below — including marking the boss defeated and spawning the
        # stairs — so a boss floor could never be cleared.
        is_boss = bool(monster.get("is_boss") or monster.get("isBoss"))

        prefix = "powerful " if is_boss else ""
        world.add_log(f"Encountered {prefix}{monster['name']}!", "combat")
        if is_boss:
            world.add_log(
                f"Floor {world.current_floor} BOSS! Must defeat to proceed!",
                "combat",
            )

        pd = world.player_data  # shorthand

        # --- Calculate player damage ---
        p_dmg = max(1, pd["attack"] - monster["defense"])

        # Buff: attack multiplier
        for buff in world.active_buffs:
            if buff["effects"].get("attack_multiplier"):
                p_dmg = int(p_dmg * buff["effects"]["attack_multiplier"])

        # Skill: crit chance
        crit = getattr(pd, "crit_chance", 0) or 0
        if crit and __import__("random").random() < crit:
            p_dmg *= 2
            world.add_log("CRITICAL HIT!", "combat")

        # Skill: berserker (HP < 30%)
        if getattr(pd, "berserk", False) and pd["hp"] / pd["max_hp"] < 0.3:
            p_dmg = int(p_dmg * 1.5)
            world.add_log("BERSERKER activated!", "combat")

        # --- Calculate monster damage ---
        m_dmg = max(1, monster["attack"] - pd["defense"])
        for buff in world.active_buffs:
            if buff["effects"].get("defense_multiplier"):
                m_dmg = max(1, int(m_dmg / buff["effects"]["defense_multiplier"]))

        # Skill: damage reduction
        dr = getattr(pd, "dmg_reduction", 0) or 0
        if dr:
            m_dmg = max(1, m_dmg - dr)

        # Skill: toughness
        tough = getattr(pd, "toughness", None)
        rng = __import__("random")
        if tough and rng.random() < tough:
            m_dmg = max(1, int(m_dmg * 0.5))
            world.add_log("Toughness reduced damage!", "combat")

        # --- Deal damage ---
        monster["current_hp"] -= p_dmg
        world.add_log(
            f"You dealt {p_dmg} damage to {monster['name']}.", "combat"
        )

        # Life steal
        ls = getattr(pd, "life_steal", 0) or 0
        if ls:
            heal = int(p_dmg * ls)
            if heal > 0:
                pd["hp"] = min(pd["max_hp"], pd["hp"] + heal)
                world.add_log(f"Life steal healed {heal} HP.", "heal")

        # --- Check monster death ---
        if monster["current_hp"] <= 0:
            # Reward
            exp_gain = monster["exp"]
            gold_gain = monster["gold"]

            # Buff multipliers for reward
            for b in world.active_buffs:
                if b["effects"].get("exp_multiplier"):
                    exp_gain = int(exp_gain * b["effects"]["exp_multiplier"])
                if b["effects"].get("gold_multiplier"):
                    gold_gain = int(gold_gain * b["effects"]["gold_multiplier"])

            # Skill: exp bonus
            eb = getattr(pd, "exp_bonus", 0) or 0
            if eb:
                exp_gain = int(exp_gain * (1 + eb))

            world.gain_exp(exp_gain)
            world.gain_gold(gold_gain)

            if is_boss:
                world.add_log(
                    f"DEFEATED BOSS {monster['name']}!", "combat"
                )
                world.add_log("Stairs to next floor appeared!", "system")
                world.boss_defeated = True
                # Spawn stairs at boss room exit
                world._spawn_stairs_at_boss_room(mx, my)
            else:
                world.add_log(f"Defeated {monster['name']}!", "combat")

            # Consume buffs
            world.consume_buffs()

            # Remove monster from tile
            del tile["monster"]

            # Move player to monster's position
            player_pos = world.get_component(world.player_entity, Position)
            if player_pos:
                player_pos.x = mx
                player_pos.y = my
                world.player_data["x"] = mx
                world.player_data["y"] = my

        else:
            # Monster counter-attacks
            pd["hp"] -= m_dmg
            world.add_log(
                f"{monster['name']} dealt {m_dmg} damage to you.", "combat"
            )

            if pd["hp"] <= 0:
                pd["hp"] = 0
                world.add_log("You have been DEFEATED! Game Over.", "combat")
                world.game_over = True


class PickupSystem:
    """Handles item pickup."""

    @staticmethod
    def pickup(world, tile: dict, ix: int, iy: int):
        item = tile["item"]
        pd = world.player_data
        itype = item["type"]
        value = item.get("value", 0)

        world.add_log(f"Found {item['name']}!", "item")

        if itype == "heal":
            pd["hp"] = min(pd["max_hp"], pd["hp"] + value)
            world.add_log(f"Restored {value} HP.", "item")
        elif itype == "attack":
            pd["attack"] += value
            world.add_log(f"ATK increased by {value}.", "item")
        elif itype == "defense":
            pd["defense"] += value
            world.add_log(f"DEF increased by {value}.", "item")
        elif itype == "gold":
            world.gain_gold(value)
        elif itype == "key":
            pd["keys"] += value
            world.add_log(f"Got {value} key(s).", "item")

        # Remove item from tile
        del tile["item"]


class StairSystem:
    """Handles floor transitions via stairs."""

    @staticmethod
    def descend(world):
        cfg = world.config
        interval = cfg["BOSS_FLOOR_INTERVAL"]

        # Boss floor guard
        if world.current_floor % interval == 0 and not world.boss_defeated:
            world.add_log(
                "Defeat this floor's BOSS before proceeding!", "warning"
            )
            return

        world.current_floor += 1
        mult = world.monster_multiplier()
        world.add_log(f"Entered Floor {world.current_floor}.", "system")
        world.add_log(
            f"WARNING: Monsters are now {mult}x stronger!", "warning"
        )

        # Clear map, reset state
        world.map_data.clear()
        world.boss_defeated = False
        world.boss_floor_shown = False

        # Reset shop stock each floor
        from game.utils import deep_copy_shop_items
        world.shop_items = deep_copy_shop_items(cfg["SHOP_ITEMS"])

        # Reset player position
        pos = world.get_component(world.player_entity, Position)
        if pos:
            pos.x = 0
            pos.y = 0
        world.player_data["x"] = 0
        world.player_data["y"] = 0

        world.generate_area_around(0, 0)
        world.ensure_player_on_floor()
