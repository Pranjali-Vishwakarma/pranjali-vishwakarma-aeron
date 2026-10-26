import os
import sys

import checks.flags
import checks.gps
import checks.loader
import checks.timeline


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python check.py <data_pack_folder>")
        sys.exit(1)

    pack = sys.argv[1]

    # 1. load stations
    stations = checks.loader.load_stations(pack)

    # 2. for each station: load gps, parse_rmc, check_position (update the stations table with any returned fields), clock_runs
    all_gps = {}
    station_runs = {}
    for st_id, st_row in stations.iterrows():
        gps_df = checks.loader.load_gps(pack, st_id)
        all_gps[st_id] = gps_df
        rmc_df = checks.gps.parse_rmc(gps_df)
        corrections = checks.gps.check_position(st_id, st_row, rmc_df, gps_df)
        if corrections:
            for k, v in corrections.items():
                stations.loc[st_id, k] = v
        runs = checks.gps.clock_runs(rmc_df)
        station_runs[st_id] = runs

    # 3. check_link over all stations
    checks.gps.check_link(all_gps)

    # 4. for each station: load data, drop_resent, fix_clock, find_gaps
    clean_data = {}
    for st_id in stations.index:
        data_df = checks.loader.load_data(pack, st_id)
        data_df = checks.timeline.drop_resent(st_id, data_df)
        data_df = checks.timeline.fix_clock(st_id, data_df, station_runs[st_id])
        data_df = checks.timeline.find_gaps(st_id, data_df)
        clean_data[st_id] = data_df

    # 5. write_flags("flags.csv") and print "wrote flags.csv: N flags"
    checks.flags.write_flags("flags.csv")
    print(f"wrote flags.csv: {len(checks.flags.FLAGS)} flags")


if __name__ == "__main__":
    main()
