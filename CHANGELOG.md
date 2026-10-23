# Changelog

本项目所有值得注意的变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 完整重写 `README.md`：项目简介、特性、快速开始（含打包）、操作说明、玩法系统、项目结构、数据表结构、测试与路线图。
- `README.en.md` 由 Gitee 模板占位文本替换为真实英文说明（与中文版内容对齐）。
- **引入 `worldbuilder` 依赖（PyPI 1.0.0，siwpan/procgen）重构地图生成**：
  - 新增 `game/worldgen.py` 适配层：普通层改为**分块 BSP 地牢**（`CHUNK_SIZE=20`，原点居中），
    房间 + 走廊由 `worldbuilder.generate_dungeon_bsp` 生成；四边中点开口互接相邻块，
    块中心及逃生走廊设为净空区（出生点永不被封死）；每块在离块心最远的房间放一个楼梯。
  - 怪物/道具改用 `worldbuilder.LootTable` 加权掉落（怪物按 HP 倒数加权，道具等权）；
    种子为 `(楼层, 块坐标)` 的 djb2 哈希，**同坐标跨进程生成结果一致**。
  - 新增精英怪物：3 层起每块约 8% 概率，`worldbuilder.NameGenerator` 生成称号
    （如 `Orc「Zyorzyavyn」`），全属性 ×1.5、经验金币翻倍、字符大写；Boss 亦获得随机称号。
  - `data/game_data.xlsx` constants 表同步新增 `CHUNK_SIZE` / `ELITE_MIN_FLOOR` /
    `ELITE_CHANCE` / `ELITE_STAT_MULT` / `NAME_STYLE`，移除 `GEN_CHANCE_STAIRS`。
- 新增 `test_worldgen.py`（12 组用例）：分块坐标数学、依赖可用性、生成确定性、
  块内/跨块连通性（BFS）、每块单楼梯、加权表产物校验、精英规则、**不覆盖语义**、
  Boss 称号、楼层怪物分档、存读档往返、挂机 AI 无头回归。
- `.gitignore` 补充 `.venv/`、`venv/`（此前虚拟环境会被误提交）。

### Changed

- `CLEANUP_RADIUS` 15 → 30（≥ 块尺寸 + 屏幕半宽，避免同屏地块被回收后每帧重建）。
- `game/world.py`：删除逐格噪声生成 `_generate_tile` 与 `random.choice` 抽样，
  改为经 `WorldGenerator` 按块惰性生成；存档格式不变（旧存档可读，新区块按新算法生成）。
- `requirements.txt` 增加 `worldbuilder>=1.0.0`。

### Fixed

- 打包章节不再引用仓库内不存在的 `*.spec`（该文件含本机绝对路径，从未入库且被 `.gitignore` 忽略），
  改为给出等价的 `pyinstaller` 命令行与 `pyi-makespec` 生成方式。
- 修复挂机 AI `_explore_or_seek` 的 `UnboundLocalError`：HP ≤ 65% 时 `monster_targets`
  未赋值即被引用（旧代码下挂机必崩，UI 回调异常被静默吞掉）。
- 修复挂机 AI 满血主动啃高危怪的问题：新增 `_fight_is_safe` 整场战斗期望伤害模型
  （与 `_scan_safe_monster` 同口径，阈值 35% 当前 HP），寻怪/相邻接战/绝望走位均改为
  风险感知；`_any_valid_move` 不再优先踩怪。
- 无头挂机模拟（8 轮 × 8000 步）：修复前 30 步内必死/必崩，修复后 5 轮存活打到 16 楼。

## [1.0.0] - 2026-08-27

### Added

- 首个发行版：Windows 可执行程序（PyInstaller，Python 3.14）。
- 发布面：gitee [siwpan/magic-tower](https://gitee.com/siwpan/magic-tower) release `v1.0.0`（魔塔 v1.0.0）。