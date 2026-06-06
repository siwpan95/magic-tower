"""Game engine constants (screen size, tiles, generation params).

Content data (monsters, items, skills, shop, player_base) is loaded from
data/game_data.xlsx via game/data_loader.py at runtime.
"""

from __future__ import annotations

# Screen / map dimensions
SCREEN_WIDTH: int = 41   # odd so player is centred
SCREEN_HEIGHT: int = 21
VIEW_RADIUS: int = 10    # how far around player to generate
CLEANUP_RADIUS: int = 15 # beyond this distance, tiles are discarded

# Tile characters
TILES = {
    "WALL": "#",
    "FLOOR": ".",
    "DOOR": "=",
    "STAIRS": ">",
    "PLAYER": "@",
    "MERCHANT": "M",
}

# Leveling
EXP_BASE: int = 100  # exp_to_next = EXP_BASE * level^1.5

# Floor mechanics
BOSS_FLOOR_INTERVAL: int = 18
BOSS_ROOM_SIZE: int = 7

# Generation probabilities (applied sequentially on floor tiles)
GEN_CHANCE_ITEM: float = 0.10
GEN_CHANCE_MONSTER: float = 0.15
GEN_CHANCE_DOOR: float = 0.02
GEN_CHANCE_STAIRS: float = 0.01
GEN_CHANCE_MERCHANT: float = 0.03

# Auto-play configuration
AUTO_MOVE_DELAY_MS: int = 200  # milliseconds between auto moves
AUTO_MOVE_DELAY_FAST_MS: int = 50  # faster delay for exploration-only moves
