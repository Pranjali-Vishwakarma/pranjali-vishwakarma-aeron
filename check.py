import os
import sys

import checks.flags
import checks.gps
import checks.loader
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

# 5. write_flags("flags.csv") and print "wrote flags.csv: N flags"
checks.flags.write_flags("flags.csv")
print(f"wrote flags.csv: {len(checks.flags.FLAGS)} flags")
