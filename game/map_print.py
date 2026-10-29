"""Map printing — render the live world grid to ASCII, ``.xlsx`` and PNG.

Cross-project reuse
-------------------
The ``.xlsx`` is written in **cordis-table-app's** Map-sheet format: one cell
per tile, solid fill colour = terrain.  That means the PNG can be produced by
*that* project's own renderer::

    node src/map_cli.mjs render --xlsx map.xlsx --sheet Map --out map.png --px 24 --grid

which is exactly what :func:`render_with_cordis` shells out to (Node host ->
JSON-RPC stdio bridge -> Python/OpenPyXL worker -> Pillow).  When Node or
cordis-table-app is unavailable we fall back to :func:`render_png_local`, a
Pillow renderer driven by the *same* palette, so both paths are pixel-identical.

Palette compatibility: every terrain key except ``player`` and ``void`` is a
documented cordis-table-app key, so ``readMap`` / ``exportDonjon`` still
understand the sheet; ``player``/``void`` are Magic Tower extensions that PNG
rendering handles fine (unknown fills render by raw RGB).

Nothing here mutates the world: ungenerated tiles are exported as ``void``
rather than being lazily materialised, so printing a map cannot advance or
perturb the dungeon.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from . import config as cfg

# --------------------------------------------------------------------------- #
# Palette (ARGB).  Keys marked "cordis" are cordis-table-app terrain keys.
# --------------------------------------------------------------------------- #
PALETTE = {
    "stone":    "FF3A3A3A",  # cordis  — 墙 / 未开凿
    "floor":    "FFF2E2C0",  # cordis  — 房间地板
    "corr":     "FFD9C9A0",  # cordis  — 走廊（保留以兼容导入）
    "door":     "FF8B5A2B",  # cordis  — 门
    "stair":    "FF9ACD32",  # cordis  — 楼梯
    "trap":     "FFB22222",  # cordis  — 借用为「普通怪物」
    "lava":     "FFB3471F",  # cordis  — 借用为「BOSS」
    "secret":   "FF6A5ACD",  # cordis  — 借用为「精英怪物」
    "grass":    "FF7CA64B",  # cordis  — 借用为「道具」
    "sand":     "FFE6D98A",  # cordis  — 借用为「商人」
    "player":   "FFFDD700",  # MT ext  — 玩家所在格（金黄）
    "void":     "FF101010",  # MT ext  — 尚未生成的区域
}

# terrain key -> 控制台字符（缺省回退到 stone）
ASCII_OF = {
    "stone": "#",
    "floor": ".",
    "corr": ".",
    "door": "=",
    "stair": ">",
    "trap": "x",
    "lava": "B",
    "secret": "E",
    "grass": "*",
    "sand": "M",
    "player": "@",
    "void": " ",
}

LEGEND = [
    ("player", "@", "玩家"),
    ("stone", "#", "墙"),
    ("floor", ".", "地板"),
    ("door", "=", "门"),
    ("stair", ">", "楼梯（下楼）"),
    ("trap", "x", "怪物"),
    ("secret", "E", "精英怪物（称号 + 属性加成）"),
    ("lava", "B", "BOSS"),
    ("grass", "*", "道具"),
    ("sand", "M", "商人"),
    ("void", " ", "未生成区域"),
]

CORDIS_ROOT = os.environ.get("CORDIS_TABLE_APP") or r"D:\projects\cordis-table-app"


@dataclass
class MapSnapshot:
    """A rectangular, world-anchored view of the already-generated map."""

    grid: list          # [row][col] -> terrain key
    chars: list         # [row][col] -> display char (monster glyphs preserved)
    ox: int             # world x of column 0
    oy: int             # world y of row 0
    cols: int
    rows: int
    player: Optional[tuple] = None   # (col, row) in grid space
    floor: int = 1

    def key_at(self, col: int, row: int) -> str:
        return self.grid[row][col]


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #

def terrain_of(tile: dict) -> str:
    """Classify a world tile into a palette key."""
    if not tile:
        return "void"
    if tile.get("type") == "wall":
        return "stone"

    mon = tile.get("monster")
    if mon:
        if mon.get("isBoss"):
            return "lava"
        if mon.get("elite"):
            return "secret"
        return "trap"

    if tile.get("stairs"):
        return "stair"
    if tile.get("door"):
        return "door"
    if tile.get("merchant"):
        return "sand"
    if tile.get("item"):
        return "grass"
    return "floor"


def char_of(tile: dict, terrain: str) -> str:
    """Display glyph for the ASCII rendering."""
    if not tile:
        return ASCII_OF["void"]
    mon = tile.get("monster")
    if mon:
        if mon.get("isBoss"):
            return "B"
        if mon.get("elite"):
            return "E"
        return str(mon.get("char") or "x")
    if tile.get("stairs"):
        return ">"
    if tile.get("door"):
        return "="
    if tile.get("merchant"):
        return "M"
    if tile.get("item"):
        return "*"
    return ASCII_OF.get(terrain, "?")


def snapshot(world, radius: Optional[int] = None) -> MapSnapshot:
    """Capture the region around the player without mutating the world."""
    r = int(radius if radius is not None else cfg.MAP_EXPORT_RADIUS)
    ptx = int(world.player_data.get("x", 0))
    pty = int(world.player_data.get("y", 0))
    ox, oy = ptx - r, pty - r
    cols = rows = 2 * r + 1

    grid, chars = [], []
    for row in range(rows):
        g_row, c_row = [], []
        for col in range(cols):
            tile = world.map_data.get(f"{ox + col},{oy + row}")
            terrain = terrain_of(tile)
            g_row.append(terrain)
            c_row.append(char_of(tile, terrain))
        grid.append(g_row)
        chars.append(c_row)

    snap = MapSnapshot(grid=grid, chars=chars, ox=ox, oy=oy,
                       cols=cols, rows=rows,
                       floor=int(getattr(world, "current_floor", 1)))
    snap.grid[rows // 2][cols // 2] = "player"
    snap.chars[rows // 2][cols // 2] = "@"
    snap.player = (cols // 2, rows // 2)
    return snap


def to_ascii(snap: MapSnapshot, title: Optional[str] = None) -> str:
    """Console rendering of a snapshot."""
    head = title or f"Floor {snap.floor}"
    lines = [f"{head}  [{snap.cols}x{snap.rows}] origin=({snap.ox},{snap.oy})",
             "+" + "-" * snap.cols + "+"]
    for row in snap.chars:
        lines.append("|" + "".join(row) + "|")
    lines.append("+" + "-" * snap.cols + "+")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# xlsx (cordis-table-app Map-sheet format)
# --------------------------------------------------------------------------- #

def _rgb(argb: str) -> tuple:
    h = argb.lstrip("#")
    if len(h) == 8:
        h = h[2:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def write_xlsx(snap: MapSnapshot, path: str, sheet: str = "Map",
               legend: bool = True) -> str:
    """Write the snapshot as a cordis-table-app compatible Map workbook."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = sheet

    for row in range(snap.rows):
        for col in range(snap.cols):
            key = snap.grid[row][col]
            cell = ws.cell(row=row + 1, column=col + 1)
            cell.fill = PatternFill("solid", start_color=PALETTE[key])
            glyph = snap.chars[row][col]
            if glyph.strip() and glyph not in (".", "#"):
                cell.value = glyph
                cell.alignment = Alignment(horizontal="center", vertical="center")

    for col in range(1, snap.cols + 1):
        ws.column_dimensions[get_column_letter(col)].width = 2.4
    for row in range(1, snap.rows + 1):
        ws.row_dimensions[row].height = 14.0

    if legend:
        ls = wb.create_sheet("Legend")
        ls.append(["terrain", "glyph", "meaning", "ARGB"])
        for c in range(1, 5):
            ls.cell(row=1, column=c).font = Font(bold=True)
        for key, glyph, meaning in LEGEND:
            ls.append([key, glyph, meaning, PALETTE[key]])
            ls.cell(row=ls.max_row, column=4).fill = PatternFill(
                "solid", start_color=PALETTE[key])
        ls.column_dimensions["A"].width = 12
        ls.column_dimensions["B"].width = 8
        ls.column_dimensions["C"].width = 34
        ls.column_dimensions["D"].width = 12

    wb.save(path)
    return path


# --------------------------------------------------------------------------- #
# PNG rendering
# --------------------------------------------------------------------------- #

def render_png_local(snap: MapSnapshot, out: str, px: int = 24,
                     grid_lines: bool = True) -> str:
    """Pillow fallback renderer — pixel-identical to the cordis pipeline."""
    from PIL import Image, ImageDraw

    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    img = Image.new("RGB", (snap.cols * px, snap.rows * px), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for row in range(snap.rows):
        for col in range(snap.cols):
            color = _rgb(PALETTE[snap.grid[row][col]])
            x0, y0 = col * px, row * px
            draw.rectangle([x0, y0, x0 + px - 1, y0 + px - 1], fill=color)

    if grid_lines:
        line = (150, 150, 150)
        for c in range(snap.cols + 1):
            x = c * px
            draw.line([(x, 0), (x, snap.rows * px)], fill=line, width=1)
        for r in range(snap.rows + 1):
            y = r * px
            draw.line([(0, y), (snap.cols * px, y)], fill=line, width=1)

    img.save(out)
    return out


def render_with_cordis(xlsx: str, out: str, px: int = 24,
                       cordis_root: Optional[str] = None,
                       grid: bool = True, timeout: int = 120) -> bool:
    """Render via cordis-table-app's own CLI. Returns True on success.

    Boots that project's Cordis host (Node) which drives its Python/OpenPyXL
    worker over a JSON-RPC stdio bridge and rasterises the sheet with Pillow.
    """
    root = cordis_root or CORDIS_ROOT
    if not root or not os.path.isdir(root):
        return False
    if not os.path.isfile(os.path.join(root, "src", "map_cli.mjs")):
        return False

    cmd = [
        "node", "src/map_cli.mjs", "render",
        "--xlsx", os.path.abspath(xlsx),
        "--sheet", "Map",
        "--out", os.path.abspath(out),
        "--px", str(int(px)),
    ]
    if grid:
        cmd.append("--grid")

    for exe in ("node", "node.exe"):
        try:
            res = subprocess.run([exe] + cmd[1:], cwd=root, capture_output=True,
                                 text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            continue
        if res.returncode == 0 and os.path.isfile(out):
            return True
    return False


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def export_map(world, outdir: str = "output", radius: Optional[int] = None,
               px: Optional[int] = None, sheet: str = "Map",
               name: str = "magic-tower-map", use_cordis: bool = True,
               cordis_root: Optional[str] = None,
               quiet: bool = False) -> dict:
    """Snapshot -> ASCII (+stdout) -> xlsx -> PNG. Returns a result dict."""
    px = int(px if px is not None else cfg.MAP_EXPORT_PX)
    snap = snapshot(world, radius)
    ascii_art = to_ascii(snap)

    outdir = os.path.abspath(outdir)
    os.makedirs(outdir, exist_ok=True)
    xlsx_path = os.path.join(outdir, f"{name}.xlsx")
    png_path = os.path.join(outdir, f"{name}.png")

    write_xlsx(snap, xlsx_path, sheet=sheet)

    engine = "pillow-local"
    if use_cordis and render_with_cordis(xlsx_path, png_path, px=px,
                                         cordis_root=cordis_root):
        engine = "cordis-table-app"
    else:
        render_png_local(snap, png_path, px=px)

    if not quiet:
        print(ascii_art)
        print(f"[map] xlsx -> {xlsx_path}")
        print(f"[map] png  -> {png_path}  (engine={engine}, {px}px/cell)")

    return {
        "ok": True,
        "ascii": ascii_art,
        "xlsx": xlsx_path,
        "png": png_path,
        "engine": engine,
        "px": px,
        "cols": snap.cols,
        "rows": snap.rows,
        "floor": snap.floor,
    }
