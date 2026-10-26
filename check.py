import os
import sys

import pandas as pd

import checks.events
import checks.exposure
import checks.flags
import checks.gps
import checks.limits
import checks.loader
import checks.neighbours
import checks.sun
import checks.timeline

if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
    print("usage: python check.py <data_pack_folder>")
    sys.exit(1)

pack = sys.argv[1]

# 1. load stations
stations_df = checks.loader.load_stations(pack)

# 2. for each station: load gps, parse_rmc, check_position, clock_runs
all_gps = {}
station_clock_runs = {}

for station_id in stations_df.index:
    gps_df = checks.loader.load_gps(pack, station_id)
    all_gps[station_id] = gps_df
    rmc_df = checks.gps.parse_rmc(gps_df)

    station_row = stations_df.loc[station_id]
    corrected_fields = checks.gps.check_position(
        station_id, station_row, rmc_df, gps_df
    )
    for field, val in corrected_fields.items():
        stations_df.loc[station_id, field] = val

    runs = checks.gps.clock_runs(rmc_df)
    station_clock_runs[station_id] = runs

# 3. check_link over all stations
checks.gps.check_link(all_gps)

# 4. for each station: load data, drop_resent, fix_clock, find_gaps
clean_data = {}
for station_id in stations_df.index:
    df = checks.loader.load_data(pack, station_id)
    df = checks.timeline.drop_resent(station_id, df)
    df = checks.timeline.fix_clock(station_id, df, station_clock_runs[station_id])
    df = checks.timeline.find_gaps(station_id, df)
    clean_data[station_id] = df

# 5. Build PANEL and BAD
all_timestamps = sorted(set().union(*(df.index for df in clean_data.values())))
master_index = pd.DatetimeIndex(all_timestamps)
channels = [
    "temp_c",
    "rh_pct",
    "pressure_hpa",
    "wind_kmh",
    "wind_dir_deg",
    "rain_mm",
    "ghi_wm2",
]

PANEL = {}
BAD = {}
for ch in channels:
    PANEL[ch] = pd.DataFrame(
        {st: clean_data[st][ch] for st in stations_df.index}, index=master_index
    )
    BAD[ch] = pd.DataFrame(False, index=master_index, columns=stations_df.index)

# 6. Pipeline checks in exact specified order:
checks.limits.out_of_range(stations_df, PANEL, BAD)
checks.limits.frozen(stations_df, PANEL, BAD)
checks.limits.rh_saturation(stations_df, PANEL, BAD)
checks.limits.spikes(stations_df, PANEL, BAD)

NB = checks.neighbours.pick(stations_df, PANEL, BAD)
checks.neighbours.steps("pressure_hpa", stations_df, PANEL, BAD, NB)
checks.neighbours.steps("wind_kmh", stations_df, PANEL, BAD, NB)

checks.exposure.sun_bias(stations_df, PANEL, BAD, NB)
checks.exposure.blocked_gauge(stations_df, PANEL, BAD, NB)
checks.exposure.rain_burst(stations_df, PANEL, BAD, NB)
checks.exposure.snow(stations_df, PANEL, BAD)

checks.sun.timing(stations_df, PANEL, BAD)
checks.sun.night(stations_df, PANEL)
checks.events.storms(stations_df, PANEL, BAD)
checks.events.fog(stations_df, PANEL, BAD)

# 7. sort flags by station_id, then start_utc, then channel, and write
checks.flags.FLAGS.sort(key=lambda r: (r["station_id"], r["start_utc"], r["channel"]))
checks.flags.write_flags("flags.csv")
print(f"wrote flags.csv: {len(checks.flags.FLAGS)} flags")
