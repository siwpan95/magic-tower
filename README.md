> 仓库：<https://gitee.com/siwpan/magic-tower> ｜ 许可：MIT-0（MIT No Attribution）（见 [LICENSE](LICENSE)）

# 魔塔 · Python ECS 版（Magic Tower）

一个用 **Python + Tkinter** 写的魔塔类爬塔 Roguelike：地图**程序化无限生成**，战斗/捡取/下楼等逻辑全部走 **ECS 架构**，
界面为 Tkinter 手绘网格（支持鼠标点击与悬停查看），内置 **全自动挂机 AI**，可一键打包成 Windows 单文件 exe。

> 起源：把一份单文件网页版「魔塔」（`oldtown.html`）用 Python 重构成多模块工程，ECS 架构 + Tkinter 图形界面 + 鼠标互动。

---

## 特性一览

- **ECS 内核**：实体只是自增 ID，数据挂组件（Component），行为交给系统（System），逻辑与渲染彻底解耦。
- **无限楼层**：以玩家为中心按需生成（`VIEW_RADIUS=10`），远处地块自动回收（`CLEANUP_RADIUS=15`）；楼层越高怪物属性按 `2^(楼层-1)` 翻倍。
- **完整养成线**：战斗 → 经验/金币 → 升级（+10 最大 HP / +2 攻 / +1 防 / +1 技能点）→ 三选一技能 → Buff → 商店消费。
- **Boss 层**：每 18 层生成一间 7×7 的 Boss 房，击败「Demon Lord」才刷出下层楼梯。
- **挂机 AI**：`AutoPlayer` 探索优先、BFS 寻路、可打怪判断、循环检测与强制脱困；5 档速度（400/200/100/50/10 ms）。
- **系统托盘**：可最小化到托盘后台挂机，托盘菜单支持切换挂机、保存、退出存档。
- **数据驱动**：怪物、道具、Boss、商店、技能、引擎常量全部写在 `data/game_data.xlsx`，改表即改游戏，无需改代码。

---

## 快速开始

### 环境要求

- Python **3.10+**（已实测 3.13 / 3.14；发行版 exe 由 Python 3.14 打包）
- Tkinter（Python 官方发行版自带，无需额外安装）

### 安装与运行

```bash
# 1) 克隆
git clone https://gitee.com/siwpan/magic-tower.git
cd magic-tower

# 2) 装依赖（建议先建虚拟环境）
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 3) 运行
python main.py
```

依赖只有三个：`openpyxl`（读 Excel 数据表）、`Pillow` + `pystray`（系统托盘图标）。

### 打包成 exe

```bash
pyinstaller magic-tower.spec        # 窗口版（console=False）
pyinstaller magic-tower-dbg.spec    # 调试版（带控制台输出）
```

产物输出到 `dist/`。

---

## 操作说明

| 操作 | 说明 |
| --- | --- |
| `↑ ↓ ← →` / `W A S D` | 移动一格 |
| 鼠标左键点击地图 | 向点击方向走一格（单步） |
| 鼠标悬停格子 | 底部状态条显示该格怪物/道具/门/楼梯详情 |
| `空格` | 开关**挂机模式** |
| `+` / `-` | 挂机时循环切换速度档（400→200→100→50→10 ms） |
| `Ctrl + S` / `Ctrl + L` | 手动存档 / 读档 |
| `Esc` | 关闭技能、商店等弹窗 |
| 关闭窗口 | 自动存档并退出 |

其他：右键信息面板可滚动；遇到商人自动弹出商店；升级时弹出技能三选一。

---

## 玩法与系统

- **战斗**：`伤害 = max(1, 攻击 - 防御)`，技能可叠加暴击、狂暴（HP<30% 时 1.5 倍）、减伤、坚韧、吸血等效果。
- **道具**：治疗药水、武器（+攻）、护甲（+防）、钥匙、宝石（金币），踩到即拾取。
- **门**：消耗 1 把钥匙开启；无钥匙则提示拦截。
- **商人**：随机出现在地图上（生成概率 3%），点击相邻格进入商店，可购买永久属性提升、治疗、钥匙与限时 Buff。
- **技能**：`ALL_SKILLS` 中随机三选一，可重复升级至 `max_level`；技能效果由 Excel 行编译成函数（`add_attr` / `add_attr_pair` / `set_flag` 等）。
- **Buff**：带持续回合数，每步消耗 1 回合，作用于攻防倍率等。
- **存档**：`town_save.json`（项目根目录）。启动时检测到存档会询问是否继续；关闭窗口自动保存。

### 默认数值（来自 `data/game_data.xlsx`）

| 类别 | 内容 |
| --- | --- |
| 怪物 | Slime(30/8/2)、Goblin(60/14/5)、Skeleton(100/22/10)、Orc(180/35/18) |
| Boss | Demon Lord（2000 HP / 120 攻 / 60 防） |
| 道具 | Health Potion(+30)、Weapon(攻+10)、Armor(防+8)、Key、Gem(金+50) |
| 初始属性 | HP 100 / 攻 10 / 防 5 |
| 升级经验 | `exp_to_next = 100 × 等级^1.5` |

---

## 项目结构

```
magic-tower/
├── main.py                 # 入口：拉起 Tkinter UI
├── ecs/                    # ECS 内核
│   ├── entity.py           #   EntityManager：实体 ID 分配
│   ├── components.py       #   Position / Renderable / Fighter / Player / Item / Stairs / Merchant
│   └── systems.py          #   Movement / Combat / Pickup / Stair System
├── game/
│   ├── world.py            # GameWorld：ECS 容器 + 地图生成 + 玩家状态 + 事件总线 + 存档
│   ├── config.py           # 引擎常量（屏幕/瓦片/生成概率/挂机延时）
│   ├── data_loader.py      # 读取 data/game_data.xlsx，编译技能效果
│   ├── auto_player.py      # 挂机 AI（探索优先 + BFS 寻路 + 循环检测）
│   └── utils.py            # 楼层倍率、升级经验、技能效果应用
├── ui/
│   └── tkinter_ui.py       # Tkinter 界面：地图绘制、信息面板、弹窗、托盘
├── data/game_data.xlsx     # 全部游戏数值（改这里即可调整平衡性）
├── test_excel_loader.py    # 数据表加载测试
├── test_integration.py     # 模块导入与核心逻辑集成测试
└── magic-tower.spec / magic-tower-dbg.spec   # PyInstaller 打包配置
```

**分层约定**：`ecs/` 只管实体与系统，`game/` 管世界状态与规则，`ui/` 只做渲染与输入；
UI 通过 `GameWorld.trigger/on` 的事件总线拿通知，不直接改写内部状态。

---

## 数据表结构（`data/game_data.xlsx`）

| 工作表 | 主要列 | 说明 |
| --- | --- | --- |
| `constants` | key / value / value_type | 覆盖 `config.py` 的同名引擎常量 |
| `tiles` | key / char | 墙、地板、门、楼梯、玩家、商人字符 |
| `monsters` | char / name / hp / attack / defense / exp / gold | 普通怪物 |
| `boss` | 同上 | Boss 模板 |
| `items` | char / name / type / value | 地面道具 |
| `player_base` | hp / attack / defense | 初始属性 |
| `shop_items` | id / name / desc / price / stock / type / effect_* 等 | 商店商品（永久属性、治疗、钥匙、Buff） |
| `skills` | id / name / desc / max_level / effect_type / target_attr / value … | 技能与效果编译参数 |

改完表重启游戏即生效；字段缺失时回落到 `config.py` 的默认值。

---

## 测试

```bash
python test_excel_loader.py    # 校验 Excel 数据加载结果
python test_integration.py     # 校验模块导入与核心逻辑
```

---

## 路线图（TODO）

- [ ] 更多怪物/技能/道具与分支build
- [ ] 楼层主题与特殊房间（陷阱、宝箱房）
- [ ] 存档多槽位 + 存档版本迁移
- [ ] 界面皮肤/字体缩放与高清素材
- [ ] Linux/macOS 打包产物

---

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

## 贡献

1. Fork 本仓库
2. 新建 `feat/xxx` 分支
3. 提交代码（数值调整请同步更新 `data/game_data.xlsx` 与 CHANGELOG）
4. 发起 Pull Request

## 许可

MIT-0（MIT No Attribution）—— 可自由使用、修改、分发，无需署名。详见 [LICENSE](LICENSE)。
