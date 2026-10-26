Pranjali Vishwakarma
pranjaliv004@gmail.com
Video: TODO
Run: python check.py <path/to/data_pack>

> **Repo name:** the brief asks for `firstname-lastname`. That name is taken by my GitHub profile
> repository (repo names are case-insensitive), so this repo is `pranjali-vishwakarma-aeron`.

# Ridgeline network data checker

`check.py` reads a data pack (`stations.csv`, `data/Sxx.csv`, `gps/Sxx.nmea`) and writes `flags.csv`
into the folder you run it from. Each row is one problem and says `exclude`, `correct` or `keep`.

| File | What it is |
|---|---|
| `check.py`, `checks/`, `config.py` | the checker (all thresholds in `config.py`, each with a reason) |
| `flags.csv` | checker output for the given pack |
| `report.html` / `report.pdf` | one page for the network coordinator |
| `DECISIONS.md` | my reasoning on the five questions |
| `explore/01–07` | the exploration scripts, in the order I investigated |
| `notes/` | my findings and the hand-written `flags_manual.csv` the checker was built to reproduce |
| `tests/` | `make_test_pack.py` (pack with different faults), `compare_manual.py` |
| `ai_logs/` | exports of every AI chat used |

## Setup
```
pip install -r requirements.txt     # pandas, numpy
python check.py ../ridgeline_data_pack
```
The data pack is not in this repo (`.gitignore`).

## How I worked
1. **Explored by hand first** (`explore/01–07`):
   - inventory;
   - timestamps;
   - GPS;
   - impossible and frozen values;
   - neighbour comparisons;
   - sun timing and real events.
2. **Wrote `notes/flags_manual.csv` by hand** from what I concluded: my answer key.
3. **Built the checker in three stages** (A: GPS + timeline, B: values + neighbours + exposure,
   C: events + sun) and compared it against the manual file (`tests/compare_manual.py`).
4. **Tested generalisation** on a modified pack with different faults (`tests/make_test_pack.py`):
   - renamed stations;
   - a flipped longitude;
   - a new pressure step;
   - wind ×2;
   - an RH flatline;
   - a +1 h clock error;
   - blank cells;
   - a missing GPS file.

## What each check does (in pipeline order)

Order matters. Time is fixed first, then values. Anything already flagged as bad is **masked**, so it
cannot distort later checks.

| Stage | Check | Rule | Action |
|---|---|---|---|
| GPS | Checksum / fix | XOR checksum must match; only RMC status `A` is used | — |
| GPS | Position, elevation | median GPS fix vs install sheet (>0.5 km, >50 m); GPS then replaces the sheet | correct |
| GPS | Link noise | bad-checksum rate >3× network median and >1% | keep |
| Timeline | Re-sent data | rows identical to earlier rows (timestamp + all values) | exclude copy |
| Timeline | Logger clock | logger − GPS time, runs of ≥3 lines off by ≥2 min; first bad row = matching timestamp jump | correct (shift) |
| Timeline | Gaps | step >1.5 × interval | exclude (missing, never filled) |
| Limits | Impossible values | physical ranges (RH up to 102%) | exclude |
| Limits | Frozen | same value ≥3 h (temp) / ≥6 h (RH, pressure) | exclude |
| Limits | RH saturation | RH ≥98% for ≥6 h while neighbours are dry, or >102% | exclude |
| Limits | Spikes | temp >6 °C from the median of the readings around it | exclude |
| Neighbours | Pressure step | hourly station − neighbour median; best change point ≥1.5 hPa | correct (offset) |
| Neighbours | Wind scale | log ratio vs neighbours; change ≥1.6× | correct (factor) |
| Exposure | Sunshine warm bias | (anomaly in strong sun) − (anomaly at night), daily; shift ≥1.5 °C with t ≥5 | exclude |
| Exposure | Blocked gauge | 0 mm while neighbours got ≥10 mm, plus the release burst | exclude |
| Exposure | Rain burst | ≥4 mm / 10 min while neighbours <1 mm | exclude |
| Exposure | Snow | >50% of tips below 0 °C | keep |
| Sun | Timing | daily sunlight centre vs network, >30 min for ≥3 days | correct (clock) |
| Sun | Night sunlight | >50 W/m² with the sun below the horizon | exclude |
| Events | Storm / fog | ≥75% of working stations ≥10 mm; ≥60% at RH ≥95% for ≥2 h | keep |

**Neighbours:** the 4 nearest stations within 500 m of height. With fewer than 2 (S01 at 2,913 m),
only single-station checks apply, flagged `keep`.

**Greedy steps:** S02's pressure jump shifted the "median of the others", which made S04, S05 and S06
look shifted the opposite way (Explore 05). So the checker fixes the biggest step in the network
first, then searches again.

## Assumptions
- All times in `flags.csv` are **true UTC** after any clock correction. The S06 note also gives the
  logger's own times and file rows.
- **Missing data** uses `exclude`, meaning "treat as missing, do not fill in". The brief has no
  "missing" action.
- **Storm detection** ignores stations whose rain is already flagged bad: a blocked gauge (S04) is
  not a dry station, so it doesn't vote.
- A `flags.csv` row holds one time range, so S04's warm bias (daytime only) is excluded for the whole
  period. The note says night minimums are usable.

## What I did not get to
- The wind change point is only accurate to about ±8 h. On the test pack it came out 7.5 h early.
- The warm-bias onset can't be dated precisely from the data. The log says 15 March and the checker
  finds a later date.
- The S07 wind factor is an estimate. Different methods give about ×2.7 to ×4.
- No check for a stuck wind vane or a drifting sunlight sensor.
- A missing GPS file is handled without crashing, but isn't flagged.
- Thresholds were tuned on one 8-station spring pack (see DECISIONS.md Q4).
