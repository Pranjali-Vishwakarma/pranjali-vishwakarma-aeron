import glob
import os
import sys

import numpy as np
import pandas as pd


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python explore/01_inventory.py <pack_folder>")
        sys.exit(1)

    pack = sys.argv[1]

    # 1. Read <pack>/stations.csv and print it as-is
    stations_path = os.path.join(pack, "stations.csv")
    with open(stations_path, "r", encoding="utf-8") as f:
        print(f.read().rstrip())
    print()

    # 2. For each file <pack>/data/Sxx.csv (sorted by name)
    data_files = sorted(glob.glob(os.path.join(pack, "data", "S*.csv")))
    dfs = []
    for f in data_files:
        station_id = os.path.splitext(os.path.basename(f))[0]
        df = pd.read_csv(f)
        dfs.append((station_id, df))

        n_rows = len(df)
        first_ts = df["timestamp_utc"].iloc[0]
        last_ts = df["timestamp_utc"].iloc[-1]

        ts = pd.to_datetime(df["timestamp_utc"])
        diffs = ts.diff().iloc[1:]
        bad_steps = int((diffs != pd.Timedelta(minutes=10)).sum())
        dups = int(df["timestamp_utc"].duplicated().sum())
        nans = int(df.isna().sum().sum())

        print(
            f"{station_id}: rows={n_rows}, start={first_ts}, end={last_ts}, "
            f"non_10m_steps={bad_steps}, duplicates={dups}, empty_cells={nans}"
        )
    print()

    # 3. For each column except timestamp_utc, print a table with one row per station
    # and the columns: min, max, mean (rounded to 1 decimal).
    if dfs:
        cols = [c for c in dfs[0][1].columns if c != "timestamp_utc"]
        for col in cols:
            print(f"{col}:")
            records = []
            for station_id, df in dfs:
                records.append({
                    "station": station_id,
                    "min": df[col].min(),
                    "max": df[col].max(),
                    "mean": round(float(df[col].mean()), 1),
                })
            table_df = pd.DataFrame(records)
            print(table_df.to_string(index=False))
            print()

    # 4. For each file <pack>/gps/Sxx.nmea, print ONE line with:
    # station_id, total lines, count of lines per sentence type ($GPRMC, $GPGGA, other)
    gps_files = sorted(glob.glob(os.path.join(pack, "gps", "S*.nmea")))
    for f in gps_files:
        station_id = os.path.splitext(os.path.basename(f))[0]
        total = 0
        rmc = 0
        gga = 0
        other = 0
        with open(f, "r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                total += 1
                if "$GPRMC" in line:
                    rmc += 1
                elif "$GPGGA" in line:
                    gga += 1
                else:
                    other += 1
        print(
            f"{station_id}: total={total}, $GPRMC={rmc}, $GPGGA={gga}, other={other}"
        )


if __name__ == "__main__":
    main()
