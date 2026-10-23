"""Game engine constants (screen size, tiles, generation params).

Content data (monsters, items, skills, shop, player_base) is loaded from
data/game_data.xlsx via game/data_loader.py at runtime.
"""

from __future__ import annotations

# Screen / map dimensions
SCREEN_WIDTH: int = 41   # odd so player is centred
SCREEN_HEIGHT: int = 21
VIEW_RADIUS: int = 10    # how far around player to generate
CLEANUP_RADIUS: int = 30 # beyond this distance, tiles are discarded
                         # (>= CHUNK_SIZE + screen half-width, so on-screen
                         #  tiles are never recycled between frames)

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

# Chunked infinite dungeon (worldbuilder BSP)
CHUNK_SIZE: int = 20          # tiles per chunk; (0,0) is chunk (0,0) centre

# Elite monsters (generated epithet + stat boost), deeper floors only
ELITE_MIN_FLOOR: int = 3
ELITE_CHANCE: float = 0.08
ELITE_STAT_MULT: float = 1.5
NAME_STYLE: str = "fantasy"   # worldbuilder NameGenerator style

# Generation probabilities (applied on floor tiles inside a chunk)
# Stairs are guaranteed once per chunk (farthest room from chunk centre),
# so there is no per-tile stairs chance any more.
GEN_CHANCE_ITEM: float = 0.10
GEN_CHANCE_MONSTER: float = 0.15
GEN_CHANCE_DOOR: float = 0.02
GEN_CHANCE_MERCHANT: float = 0.03

# Auto-play configuration
AUTO_MOVE_DELAY_MS: int = 200  # milliseconds between auto moves
AUTO_MOVE_DELAY_FAST_MS: int = 50  # faster delay for exploration-only moves
