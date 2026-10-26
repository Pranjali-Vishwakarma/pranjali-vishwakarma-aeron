import glob
import os
import sys

import numpy as np
import pandas as pd


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python explore/06_sun_events.py <pack_folder>")
        sys.exit(1)

    pack_folder = sys.argv[1]

    # Load stations metadata
    stations_csv = os.path.join(pack_folder, "stations.csv")
    stations_meta = pd.read_csv(stations_csv)
    lon_map = {
        str(row["station_id"]): float(row["lon"])
        for _, row in stations_meta.iterrows()
    }

    # Load data files and apply in-memory fixes
    data_files = sorted(glob.glob(os.path.join(pack_folder, "data", "S*.csv")))
    stations_data = {}

    for f in data_files:
        station_id = os.path.splitext(os.path.basename(f))[0]
        df = pd.read_csv(f)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])

        # Fix 1: S06 6-hour shift from the first row earlier than previous row
        if station_id == "S06":
            ts = df["timestamp_utc"]
            jump_idx = None
            for i in range(1, len(df)):
                if ts.iloc[i] < ts.iloc[i - 1]:
                    jump_idx = i
                    break
            if jump_idx is not None:
                df.loc[df.index[jump_idx:], "timestamp_utc"] += pd.Timedelta(hours=6)

        # Fix 2: Drop exact duplicates, keeping first
        df = df.drop_duplicates(keep="first")

        stations_data[station_id] = df

    # Align on common timestamp index
    all_timestamps = sorted(
        set().union(*(df["timestamp_utc"] for df in stations_data.values()))
    )
    common_index = pd.DatetimeIndex(all_timestamps)

    for st in stations_data:
        df = stations_data[st]
        df = df.set_index("timestamp_utc")
        df = df[~df.index.duplicated(keep="first")]
        stations_data[st] = df.reindex(common_index)

    # 1. Sun timing
    print("1. Sun timing (centroid_hour - solar_noon_hour in minutes):")
    dates_list = sorted(set(common_index.strftime("%Y-%m-%d")))

    timing_dict = {st: [] for st in stations_data}

    for d in dates_list:
        dt = pd.to_datetime(d)
        day_of_year = dt.day_of_year
        b = 2.0 * np.pi * (day_of_year - 81) / 364.0
        eot = 9.87 * np.sin(2.0 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)

        for st, df in stations_data.items():
            lon = lon_map[st]
            solar_noon_hour = 12.0 - lon / 15.0 - eot / 60.0

            sub = df[df.index.strftime("%Y-%m-%d") == d]
            sum_ghi = sub["ghi_wm2"].sum()

            if sum_ghi > 0:
                hours_of_day = sub.index.hour + sub.index.minute / 60.0 - 5.0 / 60.0
                centroid_hour = (sub["ghi_wm2"] * hours_of_day).sum() / sum_ghi
                diff_min = (centroid_hour - solar_noon_hour) * 60.0
                timing_dict[st].append(round(diff_min))
            else:
                timing_dict[st].append(np.nan)

    sun_table = pd.DataFrame(timing_dict, index=dates_list)
    sun_table.index.name = "date"
    print(sun_table.to_string())
    print()

    print("Median sun timing difference per station:")
    for st in sun_table.columns:
        med_val = sun_table[st].median()
        print(f"  {st}: {med_val:.1f} min")
    print()

    # 2. Sunlight at night
    print("2. Sunlight at night (ghi_wm2 > 50 between 03:00 and 11:00 UTC):")
    for st, df in stations_data.items():
        times = df.index.time
        mask = (
            (df["ghi_wm2"] > 50)
            & (times >= pd.to_datetime("03:00").time())
            & (times <= pd.to_datetime("11:00").time())
        )
        count = int(mask.sum())
        print(f"  {st}: {count}")
    print()

    # 3. Precipitation in freezing air
    print("3. Precipitation in freezing air (among rows with rain_mm > 0):")
    for st, df in stations_data.items():
        rain_mask = df["rain_mm"] > 0
        rain_count = int(rain_mask.sum())
        if rain_count > 0:
            freezing_mask = rain_mask & (df["temp_c"] < 0)
            freezing_count = int(freezing_mask.sum())
            pct = (freezing_count / rain_count) * 100.0
            print(
                f"  {st}: rain rows={rain_count}, temp < 0={freezing_count} ({pct:.1f}%)"
            )
        else:
            print(f"  {st}: rain rows=0, temp < 0=0 (0.0%)")
    print()

    # 4. Network-wide events
    print("4. Network-wide events:")
    # a) Dates where >= 6 stations have daily rain >= 10 mm
    print("  a) Dates where >= 6 stations have daily rain total >= 10 mm:")
    rain_daily = pd.DataFrame(
        {
            st: df["rain_mm"].groupby(df.index.strftime("%Y-%m-%d")).sum()
            for st, df in stations_data.items()
        }
    )
    found_rain_event = False
    for date_str, row in rain_daily.iterrows():
        ge_10 = row[row >= 10.0]
        if len(ge_10) >= 6:
            found_rain_event = True
            totals_str = ", ".join(f"{st}={val:.1f}" for st, val in row.items())
            print(f"    Date: {date_str} (>=10 mm at {len(ge_10)} stations)")
            print(f"      Totals (mm): {totals_str}")
    if not found_rain_event:
        print("    None")
    print()

    # b) Periods >= 2 hours where >= 5 stations have rh_pct >= 95
    print(
        "  b) Periods (>= 2 hours) where >= 5 stations have rh_pct >= 95 at the same time:"
    )
    rh_df = pd.DataFrame({st: df["rh_pct"] for st, df in stations_data.items()})
    cond = (rh_df >= 95.0).sum(axis=1) >= 5

    periods = []
    curr_timestamps = []
    curr_prev = None

    for ts, is_met in cond.items():
        if is_met:
            if curr_prev is None or (ts - curr_prev) == pd.Timedelta(minutes=10):
                curr_timestamps.append(ts)
                curr_prev = ts
            else:
                if len(curr_timestamps) >= 12 or (
                    curr_timestamps[-1] - curr_timestamps[0]
                ) >= pd.Timedelta(hours=2):
                    periods.append(
                        (curr_timestamps[0], curr_timestamps[-1], curr_timestamps)
                    )
                curr_timestamps = [ts]
                curr_prev = ts
        else:
            if curr_timestamps:
                if len(curr_timestamps) >= 12 or (
                    curr_timestamps[-1] - curr_timestamps[0]
                ) >= pd.Timedelta(hours=2):
                    periods.append(
                        (curr_timestamps[0], curr_timestamps[-1], curr_timestamps)
                    )
                curr_timestamps = []
                curr_prev = None

    if curr_timestamps:
        if len(curr_timestamps) >= 12 or (
            curr_timestamps[-1] - curr_timestamps[0]
        ) >= pd.Timedelta(hours=2):
            periods.append((curr_timestamps[0], curr_timestamps[-1], curr_timestamps))

    if periods:
        for start_t, end_t, ts_list in periods:
            sub_rh = rh_df.loc[ts_list]
            st_involved = sorted(
                [st for st in sub_rh.columns if (sub_rh[st] >= 95.0).any()]
            )
            start_str = start_t.strftime("%Y-%m-%d %H:%M")
            end_str = end_t.strftime("%Y-%m-%d %H:%M")
            print(
                f"    Start: {start_str}, End: {end_str}, "
                f"Stations: {', '.join(st_involved)}"
            )
    else:
        print("    None")


if __name__ == "__main__":
    main()
