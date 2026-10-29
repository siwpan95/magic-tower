"""Expand Magic Tower's bestiary from RolePlayer's SRD corpus.

Source of truth for *numbers*: ``D:\\projects\\RolePlayer\\_srd_pull\\monsters\\*.json``
(334 SRD monsters with CR / XP / HP / AC / ability scores).
Source of truth for *names*: ``_cn_src\\monsters_cn_2025.json`` (official CN glossary).

Mapping (tuned so the four existing monsters keep their identity):

    hp        = 30 + 174 * cr          # Slime .125->52, Goblin .25->73,
                                       # Skeleton .5->117, Orc 1->204
    attack    =  8 + 25  * cr
    defense   =  2 + 13  * cr
    exp       = 15 + 75  * cr
    gold      =  5 + 22  * cr
    min_floor = 1 + 1.15 * cr          # CR1->3F CR5->8F CR10->15F CR20->25F

Run from the repo root:
    .venv/Scripts/python.exe tools/gen_bestiary.py [--write]
Without ``--write`` it only prints the table (dry run).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROLEPLAYER = r"D:\projects\RolePlayer"
SRD_GLOB = os.path.join(ROLEPLAYER, "_srd_pull", "monsters", "*.json")
CN_GLOSSARY = os.path.join(ROLEPLAYER, "_cn_src", "monsters_cn_2025.json")
XLSX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "game_data.xlsx")

# (SRD english name, glyph, cn fallback) —— 手选，覆盖 CR 0 → 20 的完整梯度
BESTIARY = [
    # --- CR 0.125-0.25 : 一层 =====================
    ("Giant Rat",            "r", "巨鼠"),
    ("Kobold",               "k", "狗头人"),
    ("Goblin",               "g", "哥布林"),          # 原有
    ("Giant Bat",            "b", "巨蝙蝠"),
    ("Dretch",               "d", "怯魔"),
    ("Blink Dog",            "B", "闪现犬"),
    # --- CR 0.5-1 : 二~三层 =======================
    ("Slime",                "s", "史莱姆"),          # 原有（非 SRD，保留）
    ("Gnoll",                "n", "豺狼人"),
    ("Hobgoblin",            "h", "大地精"),
    ("Skeleton",             "S", "骷髅兵"),          # 原有
    ("Ghoul",                "G", "食尸鬼"),
    ("Giant Spider",         "p", "巨蜘蛛"),
    ("Dire Wolf",            "w", "凶狼"),
    # --- CR 2-3 : 四~六层 =========================
    ("Orc",                  "o", "兽人"),            # 原有
    ("Ogre",                 "O", "食人魔"),
    ("Gargoyle",             "y", "石像鬼"),
    ("Ghast",                "q", "妖鬼"),
    ("Minotaur",             "T", "牛头人"),
    ("Mummy",                "m", "木乃伊"),
    ("Basilisk",             "Y", "石化蜥蜴"),
    # --- CR 4-5 : 七~十层 =========================
    ("Ettin",                "E", "双头巨人"),
    ("Werewolf, Wolf Form",  "W", "狼人"),
    ("Ghost",                "Z", "幽灵"),
    ("Flesh Golem",          "F", "肉魔像"),
    ("Hill Giant",           "H", "山丘巨人"),
    ("Night Hag",            "N", "夜鬼婆"),
    # --- CR 6-8 : 十一~十五层 =====================
    ("Medusa",               "M", "美杜莎"),
    ("Wyvern",               "v", "双足飞龙"),
    ("Chimera",              "C", "奇美拉"),
    ("Hydra",                "D", "多头蛇"),
    ("Frost Giant",          "I", "霜巨人"),
    ("Young Green Dragon",   "K", "幼年绿龙"),
    # --- CR 10-16 : 十六层以上 ====================
    ("Aboleth",              "A", "底栖魔鱼"),
    ("Stone Golem",          "L", "石魔像"),
    ("Young Red Dragon",     "R", "幼年红龙"),
    ("Iron Golem",           "J", "铁魔像"),
    ("Marilith",             "X", "六臂蛇魔"),
    ("Adult Blue Dragon",    "U", "成年蓝龙"),
    # --- CR 20+ : 终局 ============================
    ("Pit Fiend",            "P", "深狱炼魔"),
    ("Ancient White Dragon", "V", "远古白龙"),
]

# 不走 SRD 的原创/沿用条目：name, glyph, cn, cr（等价难度）, 沿用值(可选)
#
# 沿用值已全部移除：旧的手调数值（骷髅兵 100/22/10、兽人 180/35/18）比同 CR
# 的曲线高出一大截，是曲线里的离群点——玩家按曲线成长时会被这两只卡死。
# 现在 40 只怪统一走 curve()，只在 CR 上体现差异。
MANUAL = [
    ("Slime", "s", "史莱姆", 0.125, None),
    ("Goblin", "g", "哥布林", 0.25, None),
    ("Skeleton", "S", "骷髅兵", 0.5, None),
    ("Orc", "o", "兽人", 2.0, None),
]

# 单数中文名（词典里多为复数/词条名，如 "Skeletons" -> "骷髅们"，这里显式指定，
# 避免把玩家看的名字写成复数）。词条名的中文仍来自 RolePlayer 的官方译名词典。
SINGULAR_ZH = {
    "Giant Rat": "巨鼠",
    "Kobold": "狗头人",
    "Goblin": "哥布林",
    "Giant Bat": "巨蝙蝠",
    "Dretch": "怯魔",
    "Blink Dog": "闪现犬",
    "Slime": "史莱姆",
    "Gnoll": "豺狼人",
    "Hobgoblin": "大地精",
    "Skeleton": "骷髅兵",
    "Ghoul": "食尸鬼",
    "Giant Spider": "巨蜘蛛",
    "Dire Wolf": "凶狼",
    "Orc": "兽人",
    "Ogre": "食人魔",
    "Gargoyle": "石像鬼",
    "Ghast": "妖鬼",
    "Minotaur": "牛头人",
    "Mummy": "木乃伊",
    "Basilisk": "石化蜥蜴",
    "Ettin": "双头巨人",
    "Werewolf, Wolf Form": "狼人",
    "Ghost": "幽灵",
    "Flesh Golem": "肉魔像",
    "Hill Giant": "山丘巨人",
    "Night Hag": "夜鬼婆",
    "Medusa": "美杜莎",
    "Wyvern": "双足飞龙",
    "Chimera": "奇美拉",
    "Hydra": "多头蛇",
    "Frost Giant": "霜巨人",
    "Young Green Dragon": "幼年绿龙",
    "Aboleth": "底栖魔鱼",
    "Stone Golem": "石魔像",
    "Young Red Dragon": "幼年红龙",
    "Iron Golem": "铁魔像",
    "Marilith": "六臂蛇魔",
    "Adult Blue Dragon": "成年蓝龙",
    "Pit Fiend": "深狱炼魔",
    "Ancient White Dragon": "远古白龙",
}


def curve(cr: float) -> dict:
    """Map a SRD challenge rating onto this game's stat block.

    Calibrated against measured play (see ``tools/balance_sim.py``), not by
    feel.  Target: killing a tier-appropriate monster costs ~20-25 % of max
    HP and takes ~4-6 exchanges.

    The old curve (``30 + 174*cr`` HP, ``2 + 13*cr`` DEF) put CR 0.25 monsters
    at 74 HP / 5 DEF on floor 1 — a 10 ATK player needed 15 hits and took 108
    damage back, i.e. every floor-1 fight was lethal.  Defence is the killer:
    it scales against the player's attack, so 13/CR pushed damage into the
    ``max(1, ...)`` floor and fights became unwinnable rather than hard.

    Slope reference: the player is expected to gain ~+10 ATK / +8 DEF per
    floor from pickups and levels, so monster DEF climbs at 4/CR (CR 20 = 82
    vs an expected ~200 ATK) keeping the exchange ratio roughly constant.
    """
    return {
        "hp": int(round(30 + 55 * cr)),
        "attack": int(round(8 + 9 * cr)),
        "defense": int(round(2 + 4 * cr)),
        "exp": int(round(12 + 55 * cr)),
        "gold": int(round(5 + 16 * cr)),
        # 深度门：CR 决定该怪最早出现在几层。2.2*cr 把 40 只怪铺到 1~45 层，
        # 每层下楼都有新面孔，同时避免 CR1（凶狼）在 2 层就出现——那时玩家
        # 只有 14 点攻击，会被它的防御压到每刀 1 点。
        "min_floor": max(1, 1 + int(cr * 2.2)),
    }


def load_srd() -> dict:
    out = {}
    for path in glob.glob(SRD_GLOB):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        out[d.get("name", "")] = d
    return out


def load_cn() -> dict:
    try:
        with open(CN_GLOSSARY, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def build() -> list:
    srd = load_srd()
    cn = load_cn()
    manual = {name: (glyph, zh, cr, fixed) for name, glyph, zh, cr, fixed in MANUAL}

    rows, seen, missing = [], set(), []
    for english, glyph, fallback in BESTIARY:
        if english in seen:
            continue
        seen.add(english)

        if english in manual:
            m_glyph, zh, cr, fixed = manual[english]
            glyph = m_glyph
            stats = dict(fixed) if fixed else curve(cr)
        else:
            rec = srd.get(english)
            if not rec:
                missing.append(english)
                continue
            cr = float(rec.get("challenge_rating") or 0)
            stats = curve(cr)

        zh = SINGULAR_ZH.get(english) or fallback
        official = cn.get(english) or cn.get(english + "s") or ""
        rows.append({
            "char": glyph,
            "name": f"{zh} {english}",
            "zh": zh,
            "official": official,
            "cr": cr,
            **{k: stats[k] for k in ("hp", "attack", "defense", "exp", "gold", "min_floor")},
        })

    rows.sort(key=lambda r: (r["min_floor"], r["cr"], r["name"]))
    return rows, missing


def write_xlsx(rows: list) -> None:
    from openpyxl import load_workbook
    from openpyxl.styles import Font

    wb = load_workbook(XLSX)
    if "monsters" in wb.sheetnames:
        del wb["monsters"]
    ws = wb.create_sheet("monsters", 2)

    header = ["char", "name", "hp", "attack", "defense", "exp", "gold",
              "min_floor", "cr"]
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([row["char"], row["name"], row["hp"], row["attack"],
                   row["defense"], row["exp"], row["gold"],
                   row["min_floor"], row["cr"]])
    for col, width in zip("ABCDEFGHI", (8, 26, 8, 10, 10, 8, 8, 12, 8)):
        ws.column_dimensions[col].width = width
    wb.save(XLSX)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write data/game_data.xlsx")
    args = ap.parse_args()

    rows, missing = build()
    print(f"{'glyph':<6}{'name':<26}{'hp':>5}{'atk':>5}{'def':>5}"
          f"{'exp':>6}{'gold':>6}{'floor':>7}{'cr':>6}")
    for r in rows:
        print(f"{r['char']:<6}{r['name']:<26}{r['hp']:>5}{r['attack']:>5}"
              f"{r['defense']:>5}{r['exp']:>6}{r['gold']:>6}"
              f"{r['min_floor']:>7}{r['cr']:>6}")
    print(f"\n{len(rows)} monsters across floors "
          f"{min(r['min_floor'] for r in rows)}-{max(r['min_floor'] for r in rows)}")
    if missing:
        print("MISSING in SRD:", missing)

    if args.write:
        write_xlsx(rows)
        print(f"written -> {XLSX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
