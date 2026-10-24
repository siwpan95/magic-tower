# Changelog

本项目所有值得注意的变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.1.0] - 2026-10-24

### Added

- **地图打印（按 `P`）**：新增 `game/map_print.py`，把当前视野导出为
  **ASCII（控制台）+ `.xlsx` + `.png`** 三件套，输出到 `output/`。
  - `.xlsx` 采用 **`cordis-table-app` 的 Map 表格式**（一格一单元格、实色填充 = 地形），
    因此可以直接交给该项目的渲染管线出图：
    `node src/map_cli.mjs render --xlsx map.xlsx --sheet Map --out map.png --px 24 --grid`
    （Cordis Node 宿主 → JSON-RPC stdio 桥 → Python/OpenPyXL → Pillow）。
  - 检测不到 Node / cordis-table-app 时自动降级到 `render_png_local()`（同一调色板，
    像素完全一致）。`CORDIS_TABLE_APP` 环境变量可指定该项目路径。
  - 调色板前 11 个键沿用 cordis-table-app 的 ARGB（`stone/floor/door/stair/lava/…`），
    仅新增 `player`、`void` 两个扩展键，`readMap` / `exportDonjon` 仍能读懂导出的表。
  - **不修改世界状态**：未生成的区域导出为 `void`，不会触发惰性生成。
- **怪物图鉴大幅扩充：4 → 40 种**（`tools/gen_bestiary.py`）。
  - 数据来源为 `D:\projects\RolePlayer` 的 SRD 语料：`_srd_pull/monsters/*.json`
    （334 只，含 CR/XP/HP/AC）取数值，`_cn_src/monsters_cn_2025.json` 取官方中文译名。
  - 数值按 CR 线性映射（**经实跑重标定**）：`hp=30+55·cr`、`atk=8+9·cr`、`def=2+4·cr`、
    `exp=12+55·cr`、`gold=5+16·cr`；原有 4 只（史莱姆/哥布林/骷髅兵/兽人）统一走曲线
    （旧手调值已移除，消除离群点）。首版斜率（174/25/13）过陡且无深度门，任意层都能刷出
    高阶种：1 层怪防御即 ≥ 玩家攻击，每刀固定 1 点伤害，挂机 120 步 0 击杀。
  - 新增 `min_floor`（深度门，`1+int(cr·2.2)`，12 档铺到 1~45 层：
    1/2/3/5/7/9/12/14/18/23/36/45）与 `cr` 两列，`monsters` 表从 7 列扩展到 9 列；
    `data_loader` 按需读取（缺列时回退到旧的「取前 N 个」分档）。
  - 梯度：1 层 7 种（史莱姆/巨鼠/狗头人/哥布林/巨蝙蝠/怯魔/闪现犬，最强哥布林 44/10/3）
    → 45 层解锁终局（深狱炼魔、远古白龙，1130/188/82）。
- 新增 `tools/ui_playtest.py`：真实 Tk 窗口实跑脚本，用 `event_generate` 走真实
  `<KeyPress>` → `_on_key` → `move_player` 路径（不直接改世界），撞墙自动换方向，
  抓窗口截图并统计重绘耗时。
- 新增 `tools/depth_audit.py`（**深层平推审计**）：复用 `balance_sim` 的无头模拟
  （真实 GameWorld + 真实 AutoPlayer），按深度采样「实测玩家战力 × 当层最强解锁模板」
  的对决数据（战比 = 它刀数 / 你刀数）。4 seed × 6000 步实测：
  - 怪物封顶点 **F45**（深狱炼魔/远古白龙 1130/188/82），此后遭遇面冻结在顶层种 + 精英；
  - **F46 起进入碾压区**（战比 ≥ 8，F46 即 83x）；F6 起战比 ≥ 65x；
    精英（×1.5）战比全程 ≥ 6.3x，深层不构成威胁；
  - F106 起玩家 DEF（1007）超过顶层种 ATK（188），每刀受 1 点固定伤害且一刀秒杀；
  - 玩家战力（ATK+DEF）斜率：封顶前 21.1/层、封顶后 17.8/层，成长未随怪物封顶停摆；
  - 4 seed 到达 F232/233/233/234（中位 233），深层平均 21 步/层、3 击杀/层。
- 新增 `MONSTER_DEPTH_BIAS`、`FLOOR_MONSTER_MULT`、`MAP_EXPORT_RADIUS`、
  `MAP_EXPORT_PX` 四个常量（`config.py` 与 xlsx `constants` 表同步）。
- 测试：`test_worldgen.py` 从 12 组扩至 14 组（新增 `test_13_spawn_not_boxed_in`
  出生点四向畅通、`test_14_difficulty_curve` 楼层倍率线性），共 61 条断言。

### Changed

- **难度曲线重做**：`monster_multiplier()` 由 `2**(floor-1)`（20 层 = 524288 倍）
  改为线性 `1 + 0.10·(floor-1)`（20 层 = 2.9 倍）。原指数倍率与新增的 CR 梯度叠加，
  造成 20 层平均怪血 ~9×10⁷、任何一局都会被秒；现在难度主要来自**物种随深度升级**
  （1 层打哥布林 44/10/3、20 层打多头蛇 470/80/34、45 层打深狱炼魔 1130/188/82），
  按生成权重表计算的期望平均怪血 F1 41 → F20 125 → F45 180，曲线平滑。
- 同层内按深度偏移权重 `(hp/max_hp)² × floor × 4.0`，深层不再被弱怪淹没：
  5 层主力变为兽人（140/26/10），20 层变为多头蛇（470/80/34）。
- `calculate_monster_multiplier()` 与 `monster_multiplier()` 统一（同一公式）；
  状态栏倍数显示改为两位小数（`2.90x`）。
- **UI 重绘重构**（手感修复）：canvas item 只创建一次并按外观分组批量 `itemconfigure`，
  替换原先每帧 `delete("all")` + 4300 次 `create_*`；背包/日志面板加内容签名缓存。
  实测完整 `_draw` 15.5 ms → 5.3 ms，单步移动 135 ms → ~22 ms（约 7 → 45 步/秒）。
- `_cleanup_distant_tiles` 只在玩家位置变化时执行（之前在每次重绘都扫全表，
  每帧解析 27 万次字符串坐标）。
- `CLEANUP_RADIUS` 15 → 30（≥ 块尺寸 + 屏幕半宽，避免同屏地块被回收后每帧重建）。
- `game/world.py`：删除逐格噪声生成 `_generate_tile` 与 `random.choice` 抽样，
  改为经 `WorldGenerator` 按块惰性生成；存档格式不变（旧存档可读，新区块按新算法生成）。
- `requirements.txt` 增加 `worldbuilder>=1.0.0`。
- 完整重写 `README.md`：项目简介、特性、快速开始（含打包）、操作说明、玩法系统、项目结构、数据表结构、测试与路线图。
- `README.en.md` 由 Gitee 模板占位文本替换为真实英文说明（与中文版内容对齐）。

### Fixed

- **出生点被三面墙围死**：BSP 的 L 形逃生走廊可能让块心只剩一个出口，开局即「关柜子」。
  改为块心 3×3 强制凿空并纳入净空区（不刷怪），保证四向可走且第一步无伏击。
- **实跑 UI 验证手感（`tools/ui_playtest.py`）**：真实 Tk 窗口 + `event_generate`
  键盘事件端到端计时。实测单步帧耗时中位 8.3 ms（~120 fps）、p95 77 ms（跨相机死区的
  整帧重绘）、脏格中位 2 格；自动战斗段 722 步 / 46 s 从 1 层打到 **29 层**，
  122 击杀、1 个 Boss，全程存活，截图 35 张存于 `output/playtest/`。
- **挂机 AI 自杀与卡死（本轮实跑暴露的三连坑，均有复现脚本佐证）**：
  - 寻怪 BFS 默认 `avoid_monsters=False`，去「安全怪」的最短路会**穿过未评估的精英怪**：
    bot 走到精英邻格后每回合重复撞它，满血 5 回合死亡（seed 7 / 5 层精英食人魔
    210 HP / 39 ATK vs 120 HP / 24 ATK）。改为寻路全程 `avoid_monsters=True`，
    目标格本身仍可达（目标判定先于怪物墙判定）。
  - `_force_breakout` 不排除怪物格：卡死挣脱时会盲撞不安全的怪。改为只允许撞
    `_fight_is_safe` 通过的怪。
  - **BFS 首步振荡**：每 tick 只重算首步，相邻两格的首步互相矛盾时 bot 在两格间
    永久往返（实测 5 层 5810 步卡死，楼梯就在 16 格外且唯一堵路的精英**可杀**）。
    新增**路线承诺**（`_route`/`_bfs_path`/`_follow_route`）：一次规划整条路径并缓存，
    被 divert（捡物/开打/换层）才重新规划。
  - 下楼规划重写（`_stairs_move`）：遍历**所有**已知楼梯（原来只看最近的一个）；
    穿怪路线检查**整条路径上第一只怪**是否可杀（原来只查第一步）；全部被不可战胜的怪
    堵住时返回 None，让 bot 转去务农/捡装备/购物变强，而不是在门口空转。
  - 新增 `tools/_probe_death.py` / `tools/_probe_stall.py`：死亡/卡死现场取证脚本
    （死亡前 N 步全状态、楼梯逐条通路判定、路线决策复现）。
- **Boss 永不死亡**：`world.py` 写 `isBoss`、`ecs/systems.py` 读 `is_boss`，
  击杀判定永不触发（Boss 层成死局）。改为双写 + 兼容读取。
- **Boss 层每 chunk 重建竞技场**：新 Boss + 重置 `boss_defeated` + 传送玩家，
  Boss 永远打不完。改为每层一座竞技场（`_boss_arena_floor` 守卫）。
- **Boss 数值不可打**：旧模板 × 层倍率让 18 层 Boss 达 5400 HP / 162 DEF，
  玩家每刀 1 点。改为从该层最强小怪推导（`BOSS_HP_MULT=1.3` / `BOSS_ATK_MULT=1.6` /
  `BOSS_DEF_MULT=1.45`），实测 18 层 Boss 11 刀 / 失血 ~72%，真正可打。
- **字形全不显示**：text item 创建时为 `state=tk.HIDDEN`，`_flush` 从未切回 `NORMAL`。
- **点击移动方向永远错误**：`_on_click` 把屏幕格坐标当世界坐标相减，点任何位置都只
  往上/左走；改用 `_view_bounds()` 换算。`_on_hover` 同样修复。
- **相机死区**：视口不再每步严格居中（861 格全脏 → 11 fps），玩家离中心超过
  `CAMERA_DEADZONE=4` 格才整体重居中，普通帧只重绘 2 格；矩形描边改 `width=0` +
  64 条静态网格线（再省 ~20 ms/帧）。
- `_print_map` 移除调试残留 `print(res["ascii"])`（日志面板已有输出）。
- 无头模拟与 UI 行为对齐：`tools/balance_sim.py` 的 step 循环原来不调用
  `ensure_visible_tiles_generated`（bot 被困在 20×20 出生块）、不用物品、不购物、
  击杀统计受 50 条日志上限影响——全部修正，并改为包一层 `add_log` 计数。
  修正后 4 个 seed × 6000 步全部无死亡、打到 232~234 层。
- **地图字符不可见**：重构后地板/墙的字符与自身背景同色（深灰叠深灰），
  整屏只剩玩家和实体可见。新增 `_fg_for()`，墙用 `#1a1a1a`、地板用 `#6f6f6f`。
- `_flush` 批量配置：Tk 的 `itemconfigure` 只接受**单个** tag/id，空格拼接的 tag 串
  会静默匹配不到任何 item；改用「临时组 tag + `withtag "a || b"` 并集」的形式。
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
- 打包章节不再引用仓库内不存在的 `*.spec`（该文件含本机绝对路径，从未入库且被 `.gitignore` 忽略），
  改为给出等价的 `pyinstaller` 命令行与 `pyi-makespec` 生成方式。
- 修复挂机 AI `_explore_or_seek` 的 `UnboundLocalError`：HP ≤ 65% 时 `monster_targets`
  未赋值即被引用（旧代码下挂机必崩，UI 回调异常被静默吞掉）。
- 修复挂机 AI 满血主动啃高危怪的问题：新增 `_fight_is_safe` 整场战斗期望伤害模型
  （与 `_scan_safe_monster` 同口径，阈值 35% 当前 HP），寻怪/相邻接战/绝望走位均改为
  风险感知；`_any_valid_move` 不再优先踩怪。
- 无头挂机模拟（8 轮 × 8000 步）：修复前 30 步内必死/必崩，修复后 5 轮存活打到 16 楼。
- **README 测试章节补环境要求 + 过期数值校正**：测试必须用**装齐 `requirements.txt`
  的解释器**运行（缺 `worldbuilder` 时 `test_worldgen.py` 因 `ModuleNotFoundError`
  整体失败，表现为「一跑就全挂」而非代码回归；本机开发环境 `E:\Python314`）；
  修正两处过期描述——楼层倍率 `2^(楼层-1)` → 线性 `1 + 0.10·(楼层-1)`，
  默认数值表改为 40 模板 + Boss 由当层最强小怪推导（模板值仅作空池回退）。
- **PyInstaller onefile 冻结后自动存档静默丢失**：`_save_path()` 用 `__file__` 反推
  项目根目录，冻结环境下 `__file__` 落在一次性临时目录 `_MEIPASS` 内，`town_save.json`
  每次重启即被清掉（v1.0.0 同款缺陷，冒烟测试暴露）。改为 `sys.frozen` 时存到
  **exe 同级目录**（`sys.executable` 所在目录），源码运行行为不变。
- 打包命令补 `--add-data "data/game_data.xlsx;data"`（此前 CLI 打包漏掉数据文件，
  exe 启动即 `FileNotFoundError`；v1.0.0 靠含 datas 的 `.spec` 才带上）。

## [1.0.0] - 2026-08-27

### Added

- 首个发行版：Windows 可执行程序（PyInstaller，Python 3.14）。
- 发布面：gitee [siwpan/magic-tower](https://gitee.com/siwpan/magic-tower) release `v1.0.0`（魔塔 v1.0.0）。
