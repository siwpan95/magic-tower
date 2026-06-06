from dataclasses import dataclass
from typing import Tuple, Optional, Any, Dict

@dataclass
class Position:
    x: int
    y: int

@dataclass
class Renderable:
    char: str  # display character, e.g. '@', 'g', '#'
    color: str  # tkinter颜色，如 'white', 'red'

@dataclass
class Fighter:
    hp: int
    max_hp: int
    attack: int
    defense: int
    exp_reward: int = 0
    gold_reward: int = 0

@dataclass
class Player:
    level: int = 1
    exp: int = 0
    exp_to_next: int = 100
    skill_points: int = 0
    gold: int = 0
    keys: int = 0

@dataclass
class Item:
    item_type: str  # 'potion', 'key', 'scroll'
    effect: Dict[str, Any]  # item effect data

@dataclass
class Stairs:
    leads_to: int  # 目标楼层

@dataclass
class Merchant:
    inventory: list  # 出售物品列表