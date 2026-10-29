"""Utility functions for the magic tower game."""

from __future__ import annotations

import math
import copy


def calculate_monster_multiplier(floor: int, per_floor: float = 0.10) -> float:
    """Per-floor stat multiplier (linear).

    Historically ``2 ** (floor - 1)`` (floor 20 => 524288x).  Difficulty now
    comes mostly from the depth-gated bestiary (see tools/gen_bestiary.py), so
    this only needs a gentle nudge.
    """
    return 1.0 + per_floor * (floor - 1)


def calculate_exp_to_next(level: int, exp_base: int = 100) -> int:
    """EXP needed for next level: base * level^1.5"""
    return int(exp_base * math.pow(level, 1.5))


# ---- Skill definitions with actual effect functions ----

ALL_SKILLS: list[dict] = [
    {
        "id": 1, "name": "Vitality Boost",
        "desc": "Max HP +20, heal +20",
        "max_level": 5,
        "effect": lambda p: (_set(p, "max_hp", p.max_hp + 20),
                             _set(p, "hp", p.hp + 20)),
    },
    {
        "id": 2, "name": "Attack Boost",
        "desc": "ATK +5",
        "max_level": 5,
        "effect": lambda p: _set(p, "attack", p.attack + 5),
    },
    {
        "id": 3, "name": "Defense Boost",
        "desc": "DEF +3",
        "max_level": 5,
        "effect": lambda p: _set(p, "defense", p.defense + 3),
    },
    {
        "id": 4, "name": "Life Steal",
        "desc": "Heal 10% of damage dealt",
        "max_level": 3,
        "effect": lambda p: _set(p, "life_steal",
                                  getattr(p, "life_steal", 0) + 0.1),
    },
    {
        "id": 5, "name": "Critical Hit",
        "desc": "10% chance double damage",
        "max_level": 3,
        "effect": lambda p: _set(p, "crit_chance",
                                  getattr(p, "crit_chance", 0) + 0.1),
    },
    {
        "id": 6, "name": "Damage Reduction",
        "desc": "Reduce all damage by 2 (min 1)",
        "max_level": 5,
        "effect": lambda p: _set(p, "dmg_reduction",
                                  getattr(p, "dmg_reduction", 0) + 2),
    },
    {
        "id": 7, "name": "EXP Absorption",
        "desc": "+20% EXP gain",
        "max_level": 3,
        "effect": lambda p: _set(p, "exp_bonus",
                                  getattr(p, "exp_bonus", 0) + 0.2),
    },
    {
        "id": 8, "name": "Berserker",
        "desc": "+50% ATK when HP < 30%",
        "max_level": 1,
        "effect": lambda p: setattr(p, "berserk", True),
    },
    {
        "id": 9, "name": "Toughness",
        "desc": "20% chance halve incoming damage",
        "max_level": 2,
        "effect": lambda p: _set(p, "toughness", 0.2 * (
            1 + getattr(p, "_toughness_stack", 0))),
    },
    {
        "id": 10, "name": "Regeneration",
        "desc": "Heal 2% Max HP per turn",
        "max_level": 3,
        "effect": lambda p: _set(p, "hp_regen",
                                  getattr(p, "hp_regen", 0) + 0.02),
    },
]


def _set(obj, attr, val):
    """Helper: set attribute on object and return None."""
    setattr(obj, attr, val)


def apply_skill_effect(player_data: dict, skill_def: dict):
    """Apply a skill's effect to player data dict."""
    fn = skill_def["effect"]
    fn(player_data)


def deep_copy_shop_items(items: list[dict]) -> list[dict]:
    """Deep copy shop items list."""
    return copy.deepcopy(items)
