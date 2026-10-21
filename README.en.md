# Magic Tower (Python / ECS Edition)

> Repo: <https://gitee.com/siwpan/magic-tower> ｜ License: MIT-0 (MIT No Attribution) — see [LICENSE](LICENSE)

A magic-tower style roguelike written in **Python + Tkinter**: procedurally generated infinite floors,
gameplay logic built on an **ECS architecture**, Tkinter-drawn grid UI with mouse interaction,
a built-in **auto-play AI**, and one-command packaging into a single-file Windows exe.

Originally a rewrite of a single-file HTML magic tower (`oldtown.html`) into a multi-module Python
project: ECS architecture + Tkinter GUI + mouse interaction.

## Features

- **ECS core** — entities are plain IDs, data lives in components, behaviour lives in systems.
- **Infinite floors** — tiles are generated around the player (`VIEW_RADIUS=10`) and recycled when far away
  (`CLEANUP_RADIUS=15`); monster stats scale by `2^(floor-1)`.
- **Progression** — combat → EXP/gold → level up (+10 max HP / +2 ATK / +1 DEF / +1 skill point)
  → pick 1 of 3 skills → buffs → shop.
- **Boss floors** — every 18th floor spawns a 7×7 boss room; defeat the Demon Lord to reveal the stairs.
- **Auto-play AI** — exploration-first, BFS pathfinding, fight-or-skip evaluation, loop detection with
  forced breakout; 5 speed levels (400/200/100/50/10 ms).
- **System tray** — hide to tray and keep idling; tray menu toggles auto-play, saves, and exits.
- **Data-driven** — monsters, items, boss, shop, skills and engine constants all live in
  `data/game_data.xlsx`; tune the spreadsheet, not the code.

## Quick start

```bash
git clone https://gitee.com/siwpan/magic-tower.git
cd magic-tower

python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python main.py
```

Requirements: Python 3.10+ (tested on 3.13/3.14), Tkinter (bundled with CPython), plus
`openpyxl`, `Pillow`, `pystray`.

Build the Windows exe:

```bash
pip install pyinstaller

pyinstaller --noconsole --onefile --name magic-tower main.py   # windowed
pyinstaller --onefile --name magic-tower-dbg main.py           # with console (debug)
```

Output goes to `dist/` (git-ignored). The `*.spec` files contain machine-specific absolute paths and
are **not committed** — regenerate one with
`pyi-makespec --noconsole --onefile --name magic-tower main.py` if you need pinned build options.

## Controls

| Input | Action |
| --- | --- |
| Arrow keys / `WASD` | Move one tile |
| Left click on map | Step toward the clicked tile |
| Hover a tile | Show monster / item / door / stairs details in the status bar |
| `Space` | Toggle auto-play |
| `+` / `-` | Cycle auto-play speed (400→200→100→50→10 ms) |
| `Ctrl+S` / `Ctrl+L` | Save / load manually |
| `Esc` | Close modals |
| Close window | Auto-save and exit |

## Project layout

```
main.py                 entry point
ecs/                    entity manager, components, systems (movement/combat/pickup/stairs)
game/                   GameWorld (ECS container, map generation, state, events, save),
                        config, Excel data loader, auto-play AI, utils
ui/tkinter_ui.py        Tkinter UI: map rendering, info panels, modals, tray icon
data/game_data.xlsx     all game numbers (balance tweaks go here)
test_excel_loader.py    Excel loading test
test_integration.py     import + core logic integration test
```

`build/`, `dist/` and local `*.spec` files are git-ignored and not committed.

## Data sheets (`data/game_data.xlsx`)

`constants`, `tiles`, `monsters`, `boss`, `items`, `player_base`, `shop_items`, `skills`.
Values in `constants` override the same-named engine constants in `game/config.py`; missing entries
fall back to code defaults.

## Tests

```bash
python test_excel_loader.py
python test_integration.py
```

## Contributing

1. Fork the repo
2. Create a `feat/xxx` branch
3. Commit (update `data/game_data.xlsx` and CHANGELOG for balance changes)
4. Open a Pull Request

## License

MIT-0 (MIT No Attribution) — use, modify and distribute freely, no attribution required. See [LICENSE](LICENSE).
