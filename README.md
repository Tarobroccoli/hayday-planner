# Hay Day Planner

Personal, fan-made production planner for Hay Day. One HTML file, works offline and on a phone.

- **Money mode**: linear program for the most coins per hour from your farm (fields, machines, slots,
  animals, trees, roadside shop, barn/silo) at your check-in interval. Shows a whole-number plan per
  check-in as a repeating cycle, what to sell, and which upgrade pays most (LP shadow prices).
- **Quest mode**: pick what a quest/order needs. Shows what to plant and make at each check-in, the
  rest of the farm's money tasks (orange), when it will be ready, a food web, and whether the reward
  beats the coins you lose.
- Thai / English toggle.

Open `hayday_planner.html` in a browser. Farm settings are saved in that browser.

## Rebuild

Python 3 with pandas, openpyxl, scipy and Pillow.

```bash
# product data (cached in raw/ and fandom_api/)
python scripts/fetch_fandom.py hayday_merged_clean.xlsx raw/fandom            # MediaWiki API -> raw/fandom/pages.json
python scripts/parse_fandom.py raw/fandom/pages.json fandom_api                 # -> fandom_api/*.csv
python scripts/build_v2.py hayday_merged_clean.xlsx hayday_merged_v2.xlsx fandom_api raw/hayday_info_production-data.json
python scripts/build_merged.py hayday_merged_v2.xlsx fandom_api raw/hayday_info_production-data.json
python scripts/chain_economics.py fandom_api raw/hayday_info_production-data.json verified_in_game.csv chain_economics.csv 39
python scripts/add_chain_sheet.py hayday_merged_v2.xlsx chain_economics.csv 39

# planners (command line)
python scripts/planner.py fandom_api raw/hayday_info_production-data.json verified_in_game.csv farm_profile.json --checkin 60 120 240
python scripts/quest.py   fandom_api raw/hayday_info_production-data.json verified_in_game.csv farm_profile.json quest_example.json

# the HTML page (engine = web/engine.js, UI = web/planner_template.html)
python scripts/export_web.py fandom_api raw/hayday_info_production-data.json verified_in_game.csv \
    farm_profile.json icons/icon_manifest.csv web/planner_template.html hayday_planner.html
```

Flat-colour icon set (`scripts/xkcd_icons.py` also draws xkcd-style wobbly outlines without `--no-lines`):

```bash
python scripts/xkcd_icons.py icons icons_flat --color flat --ncolors 6 --no-lines
```

Edit `farm_profile.json` for your own farm. `verified_in_game.csv` holds values checked in the game;
they win over every other source.

## Layout

| Path | What |
|---|---|
| `hayday_planner.html` | the built app |
| `web/` | JS engine (simplex LP, quest simulation) and page template |
| `scripts/` | data fetch/merge, Python planners, HTML export |
| `fandom_api/` | products, recipes, usage parsed from the Fandom wiki API |
| `raw/` | cached API responses |
| `hayday_merged_v2.xlsx` | merged product table with sources, conflicts and notes |
| `icons/` | product icons (256 px) with `icon_manifest.csv` |
| `icons_flat/` | the same icons redrawn as flat colour art (6 colours, no outlines) |
| `plans/` | example planner outputs |

## Model assumptions

Steady-state rates; trees give 3 fruit per harvest; seeds are free (a field nets +1 crop); barn/silo only
checks what one visit brings in; mine, fishing and other tool-based items are left out.

## Sources and credits

- Prices and XP: [hayday.info](https://hayday.info) (checked against the live site, 2026-10).
- Recipes, times, levels: [Hay Day Wiki](https://hayday.fandom.com) via the MediaWiki API, content under CC BY-SA.
- Hay Day, its names and all icon artwork are © Supercell. This is an unofficial fan project, not
  affiliated with or endorsed by Supercell.
