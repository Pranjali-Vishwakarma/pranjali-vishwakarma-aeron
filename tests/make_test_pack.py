"""Create a test data pack with injected faults."""

import os
import shutil
import sys
import pandas as pd


def main():
    if len(sys.argv) != 3:
        print("Usage: python tests/make_test_pack.py <source_pack> <output_pack>")
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2]

    # Delete output_pack first if it exists, then copy source pack
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    # 1. Rename every station Sxx to X(10+i) in stations.csv and the data/ and gps/ file names
    # (S01->X10, S02->X11, ... S08->X17)
    mapping = {f"S{i:02d}": f"X{10 + i - 1}" for i in range(1, 9)}

    stations_csv_path = os.path.join(dst, "stations.csv")
    stations_df = pd.read_csv(stations_csv_path)
    stations_df["station_id"] = (
        stations_df["station_id"].astype(str).map(lambda s: mapping.get(s, s))
    )
    stations_df.to_csv(stations_csv_path, index=False)

    for old_id, new_id in mapping.items():
        old_data = os.path.join(dst, "data", f"{old_id}.csv")
        new_data = os.path.join(dst, "data", f"{new_id}.csv")
        if os.path.exists(old_data):
            os.rename(old_data, new_data)

        old_gps = os.path.join(dst, "gps", f"{old_id}.nmea")
        new_gps = os.path.join(dst, "gps", f"{new_id}.nmea")
        if os.path.exists(old_gps):
            os.rename(old_gps, new_gps)

    print("1. Renamed stations S01-S08 to X10-X17 in stations.csv and file names.")

    # 2. stations.csv: flip the sign of X13's longitude.
    stations_df = pd.read_csv(stations_csv_path)
    mask_x13 = stations_df["station_id"] == "X13"
    stations_df.loc[mask_x13, "lon"] = -stations_df.loc[mask_x13, "lon"]
    stations_df.to_csv(stations_csv_path, index=False)
    print("2. stations.csv: flipped the sign of X13's longitude.")

    # 3. X17: subtract 4.0 from pressure_hpa for all rows with timestamp_utc >= "2025-04-01 06:00".
    x17_path = os.path.join(dst, "data", "X17.csv")
    x17_df = pd.read_csv(x17_path)
    mask_p = x17_df["timestamp_utc"] >= "2025-04-01 06:00"
    x17_df.loc[mask_p, "pressure_hpa"] = (
        x17_df.loc[mask_p, "pressure_hpa"] - 4.0
    ).round(2)
    x17_df.to_csv(x17_path, index=False)
    print(
        "3. X17: subtracted 4.0 from pressure_hpa for rows >= 2025-04-01 06:00."
    )

    # 4. X12: multiply wind_kmh by 2 (round to 1 decimal) for rows >= "2025-03-10 00:00".
    x12_path = os.path.join(dst, "data", "X12.csv")
    x12_df = pd.read_csv(x12_path)
    mask_w = x12_df["timestamp_utc"] >= "2025-03-10 00:00"
    x12_df.loc[mask_w, "wind_kmh"] = (
        x12_df.loc[mask_w, "wind_kmh"] * 2.0
    ).round(1)
    x12_df.to_csv(x12_path, index=False)
    print("4. X12: multiplied wind_kmh by 2 for rows >= 2025-03-10 00:00.")

    # 5. X14: set temp_c to empty for file rows 100-110; set rh_pct to 55.0 for 60 consecutive
    # rows starting at timestamp "2025-04-03 00:00".
    x14_path = os.path.join(dst, "data", "X14.csv")
    x14_df = pd.read_csv(x14_path)
    # File row 1 is header, so file rows 100-110 correspond to df.iloc[98:109]
    col_temp = x14_df.columns.get_loc("temp_c")
    x14_df.iloc[98:109, col_temp] = float("nan")

    start_idx = x14_df.index[x14_df["timestamp_utc"] == "2025-04-03 00:00"]
    if len(start_idx) > 0:
        idx0 = start_idx[0]
        x14_df.loc[idx0 : idx0 + 59, "rh_pct"] = 55.0

    x14_df.to_csv(x14_path, index=False)
    print(
        "5. X14: set temp_c to empty for file rows 100-110; set rh_pct to 55.0 for 60 rows starting at 2025-04-03 00:00."
    )

    # 6. X16: add 1 hour to timestamp_utc for every row >= "2025-04-02 00:00", and add 1 hour
    # to the logger timestamp (first field) of every gps line >= "2025-04-02 00:00".
    x16_path = os.path.join(dst, "data", "X16.csv")
    x16_df = pd.read_csv(x16_path)
    ts_series = pd.to_datetime(x16_df["timestamp_utc"])
    mask_ts = ts_series >= pd.to_datetime("2025-04-02 00:00")
    new_ts = ts_series[mask_ts] + pd.Timedelta(hours=1)
    x16_df.loc[mask_ts, "timestamp_utc"] = new_ts.dt.strftime("%Y-%m-%d %H:%M")
    x16_df.to_csv(x16_path, index=False)

    x16_gps_path = os.path.join(dst, "gps", "X16.nmea")
    new_lines = []
    with open(x16_gps_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_clean = line.strip()
            if not line_clean:
                continue
            dollar_pos = line_clean.find("$")
            if dollar_pos == -1:
                new_lines.append(f"{line_clean}\n")
                continue
            ts_part = line_clean[:dollar_pos].rstrip(",")
            sentence_part = line_clean[dollar_pos:]
            try:
                ts_val = pd.to_datetime(ts_part)
                if ts_val >= pd.to_datetime("2025-04-02 00:00"):
                    ts_val = ts_val + pd.Timedelta(hours=1)
                    if len(ts_part) >= 19:
                        new_ts_str = ts_val.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        new_ts_str = ts_val.strftime("%Y-%m-%d %H:%M")
                    new_lines.append(f"{new_ts_str},{sentence_part}\n")
                else:
                    new_lines.append(f"{line_clean}\n")
            except Exception:
                new_lines.append(f"{line_clean}\n")

    with open(x16_gps_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(
        "6. X16: added 1 hour to timestamp_utc and GPS logger timestamp for rows >= 2025-04-02 00:00."
    )

    # 7. Delete gps/X11.nmea.
    x11_gps = os.path.join(dst, "gps", "X11.nmea")
    if os.path.exists(x11_gps):
        os.remove(x11_gps)
    print("7. Deleted gps/X11.nmea.")


if __name__ == "__main__":
    main()
