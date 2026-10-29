"""Depth audit — 量化「深层平推」：怪物成长在哪里封顶，玩家何时开始碾压。

复用 tools/balance_sim.py 的无头模拟（真实 GameWorld + 真实 AutoPlayer，
不碰任何游戏逻辑），按深度采样「实测玩家战力 × 当层最强解锁模板」的对决数据：

  你一刀 = max(1, 玩家ATK - 怪DEF)        它一刀 = max(1, 怪ATK - 玩家DEF)
  你刀数 = ceil(怪HP / 你一刀)            它刀数 = ceil(玩家HP / 它一刀)
  战比   = 它刀数 / 你刀数（>1 占优，越大越碾压）

口径说明：
- 怪物实例无层倍率（worldgen._make_monster mult=1.0），难度 = min_floor 门 +
  深度权重（强种占比随深度上升）+ 精英 ×1.5。故采样「当层最强模板」即近似
  深层的典型遭遇（权重公式使顶层种在深层占主导）。
- 玩家战力取模拟中**上一层的离场记录**（balance_sim 在换层时存档，即本层
  入场战力），非估计值；技能减伤/防御 buff 不计入，结论偏保守。F1 无上层
  记录，取初始属性。
- 多 seed 取中位数，抗单局波动。

用法：
    E:/Python314/python.exe tools/depth_audit.py [--steps 6000]
        [--seeds 7,13,42,99] [--every 5] [--report output/depth_audit.md]
"""

from __future__ import annotations

import argparse
import collections
import math
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 战比阈值：ttd/ttk（玩家换血比）
VERDICTS = (
    (20.0, "碾压"),
    (8.0, "平推"),
    (2.0, "优势"),
    (0.8, "均势"),
    (0.0, "危险"),
)


def _verdict(margin: float, ttk: int) -> str:
    if ttk <= 2 and margin >= 8:
        return "秒杀+碾压"
    for threshold, label in VERDICTS:
        if margin >= threshold:
            return label
    return "危险"


def strongest_at(monsters: list[dict], floor: int) -> dict:
    """当层 HP 最高的解锁模板（min_floor <= floor）。"""
    pool = [m for m in monsters if int(m.get("min_floor", 1)) <= floor]
    if not pool:
        pool = monsters[:1]
    return max(pool, key=lambda m: int(m.get("hp", 0)))


def duel(player: dict, monster: dict, elite_mult: float = 1.0) -> dict:
    """单挑数值镜像 ecs/systems.py 的伤害公式（不含技能/buff，偏保守）。"""
    m_hp = int(monster["hp"] * elite_mult)
    m_atk = int(monster["attack"] * elite_mult)
    m_def = int(monster["defense"] * elite_mult)
    p_d = max(1, player["attack"] - m_def)
    m_d = max(1, m_atk - player["defense"])
    ttk = math.ceil(m_hp / p_d)
    ttd = math.ceil(player["max_hp"] / m_d)
    return {
        "m_hp": m_hp, "m_atk": m_atk, "m_def": m_def,
        "p_d": p_d, "m_d": m_d, "ttk": ttk, "ttd": ttd,
        "margin": (ttd / ttk) if ttk else float("inf"),
    }


def _player_at_floor(per_floor: dict, floor: int, base: dict) -> dict:
    """本层入场战力 = balance_sim 记录的上一层离场快照。"""
    snap = per_floor.get(floor - 1) or per_floor.get(floor)
    if snap is None:
        return dict(base)
    return {"attack": snap["atk"], "defense": snap["defense"],
            "max_hp": snap["max_hp"], "level": snap["level"]}


def _player_base(world) -> dict:
    from game.world import GameWorld  # noqa: F401  (仅取 base，实例化便宜)
    pb = world._game_data.get("PLAYER_BASE", {})
    return {"attack": int(pb.get("attack", 10)),
            "defense": int(pb.get("defense", 5)),
            "max_hp": int(pb.get("hp", 100)), "level": 1}


def collect(steps: int, seeds: list[int]) -> dict:
    """跑全部 seed，汇总每层的玩家入场战力与推进统计（中位数）。"""
    from tools.balance_sim import run

    monsters = None
    per_floor_stats = collections.defaultdict(list)   # floor -> [snap, ...]
    kills_ml = collections.defaultdict(list)
    turns_ml = collections.defaultdict(list)
    base = None
    reached = []

    for seed in seeds:
        res = run(steps, seed)
        reached.append(res["floor_reached"])
        if monsters is None:
            from game.data_loader import GameDataLoader
            monsters = GameDataLoader().load_all()["MONSTER_TYPES"]
            from game.world import GameWorld
            base = _player_base(GameWorld())
        pf = res["per_floor"]
        for f, snap in pf.items():
            per_floor_stats[f].append(snap)
            kills_ml[f].append(res["kills"].get(f, 0))
        # turns：balance_sim 的 per_floor[f]["turns"] 即本层耗时
        for f, snap in pf.items():
            turns_ml[f].append(snap["turns"])

    return {
        "monsters": monsters,
        "base": base,
        "per_floor": per_floor_stats,
        "kills": kills_ml,
        "turns": turns_ml,
        "reached": reached,
    }


def audit(data: dict, every: int) -> list[dict]:
    """按采样深度算对决表；返回行 dict 列表（玩家战力为中位数）。"""
    monsters = data["monsters"]
    base = data["base"]
    max_floor = max(data["per_floor"]) if data["per_floor"] else 1
    rows = []
    for f in range(1, max_floor + 1, every):
        if f == 1:
            # 没有 0 层离场记录，F1 用初始属性（balance_sim 的 per_floor[1]
            # 是 1 层*离场*快照，直接拿来会让 F1 显得过于轻松）
            player = dict(base)
        else:
            snaps = data["per_floor"].get(f - 1) or data["per_floor"].get(f)
            if not snaps:
                continue
            player = {
                "attack": int(statistics.median(s["atk"] for s in snaps)),
                "defense": int(statistics.median(s["defense"] for s in snaps)),
                "max_hp": int(statistics.median(s["max_hp"] for s in snaps)),
                "level": int(statistics.median(s["level"] for s in snaps)),
            }
        m = strongest_at(monsters, f)
        d = duel(player, m)
        de = duel(player, m, elite_mult=1.5)
        rows.append({
            "floor": f,
            "monster": m["name"], "m_hp": d["m_hp"], "m_atk": d["m_atk"],
            "m_def": d["m_def"],
            "player": player,
            "p_d": d["p_d"], "m_d": d["m_d"], "ttk": d["ttk"], "ttd": d["ttd"],
            "margin": d["margin"],
            "elite_margin": de["margin"],
            "kills": int(statistics.median(data["kills"].get(f, [0]))),
            "turns": int(statistics.median(data["turns"].get(f, [0]))),
        })
    return rows


def summarize(rows: list[dict], monsters: list[dict]) -> dict:
    """封顶点 + 平推起点 + 推进耗时趋势。"""
    cap_floor = max(int(m.get("min_floor", 1)) for m in monsters)
    push_floor = None
    for r in rows:
        if r["floor"] > cap_floor and r["margin"] >= 8.0:
            push_floor = r["floor"]
            break
    slope_lo = slope_hi = None
    pre = [r for r in rows if r["floor"] <= min(cap_floor, 20)]
    post = [r for r in rows if r["floor"] > cap_floor]
    if len(pre) >= 2:
        slope_lo = _slope([r["floor"] for r in pre],
                          [r["player"]["attack"] + r["player"]["defense"] for r in pre])
    if len(post) >= 2:
        slope_hi = _slope([r["floor"] for r in post],
                          [r["player"]["attack"] + r["player"]["defense"] for r in post])
    return {"cap_floor": cap_floor, "push_floor": push_floor,
            "power_slope_pre": slope_lo, "power_slope_post": slope_hi}


def _slope(xs: list[int], ys: list[int]) -> float:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def render(rows: list[dict], summary: dict, data: dict,
           steps: int, seeds: list[int]) -> str:
    out = []
    w = out.append
    w("=" * 108)
    w(f"DEPTH AUDIT  seeds={seeds}  steps={steps}/seed  "
      f"reached={sorted(data['reached'])}")
    w("=" * 108)
    w("  深度  最强解锁怪(HP/ATK/DEF)      玩家(ATK/DEF/HP)  你一刀 它一刀 "
      "你刀数 它刀数 战比   精英战比 结论")
    for r in rows:
        p = r["player"]
        w(f"  F{r['floor']:<4} {r['monster']:<14}"
          f"{r['m_hp']:<5}{r['m_atk']:<5}{r['m_def']:<4}   "
          f"{p['attack']:<5}{p['defense']:<5}{p['max_hp']:<6}  "
          f"{r['p_d']:<5} {r['m_d']:<5} {r['ttk']:<5} {r['ttd']:<5} "
          f"{r['margin']:>5.1f}x {r['elite_margin']:>5.1f}x "
          f"{_verdict(r['margin'], r['ttk'])}")
    w("-" * 108)
    w(f"  怪物封顶点：F{summary['cap_floor']}（此后无新模板，遭遇面冻结在顶层种+精英）")
    pf = summary["push_floor"]
    w(f"  平推判定：{'F%d 起战比≥8（玩家碾压）' % pf if pf else '采样范围内未出现战比≥8 的平推区'}")
    if summary["power_slope_pre"] is not None:
        line = (f"  玩家战力(ATK+DEF)斜率：封顶前 "
                f"{summary['power_slope_pre']:.1f}/层")
        if summary["power_slope_post"] is not None:
            line += f"  封顶后 {summary['power_slope_post']:.1f}/层"
        w(line)
    w(f"  到达层数（各 seed 中位 {int(statistics.median(data['reached']))}）："
      f"平均每层推进 "
      f"{int(statistics.median([t for ts in data['turns'].values() for t in ts]))} 步 / "
      f"{int(statistics.median([k for ks in data['kills'].values() for k in ks]))} 击杀")
    return "\n".join(out)


def write_report(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# magic-tower 深层平推审计\n\n```\n" + text + "\n```\n")
    print(f"\n报告已写入 {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--seeds", default="7,13,42,99")
    ap.add_argument("--every", type=int, default=5, help="采样深度间隔")
    ap.add_argument("--report", default="", help="可选：markdown 报告输出路径")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    data = collect(args.steps, seeds)
    rows = audit(data, args.every)
    if not rows:
        print("没有可采样的深度数据（模拟未推进？）")
        return 1
    summary = summarize(rows, data["monsters"])
    text = render(rows, summary, data, args.steps, seeds)
    print(text)
    if args.report:
        write_report(args.report, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
