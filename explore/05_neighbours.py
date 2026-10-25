import glob
import os
import sys

import numpy as np
import pandas as pd


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python explore/05_neighbours.py <pack_folder>")
        sys.exit(1)

    pack_folder = sys.argv[1]
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

        # Fix 2: Drop exact duplicates (same timestamp and same values), keeping first
        df = df.drop_duplicates(keep="first")

        # Fix 3: Quality control NaNs
        # a) temp_c outside -35..45
        if "temp_c" in df.columns:
            df.loc[(df["temp_c"] < -35.0) | (df["temp_c"] > 45.0), "temp_c"] = np.nan

            # b) temp_c in any run of 18+ identical values
            s = df["temp_c"]
            is_diff = (s != s.shift(1)) | (s.isna() != s.shift(1).isna())
            run_id = is_diff.cumsum()
            run_counts = df.groupby(run_id)["temp_c"].transform("count")
            df.loc[run_counts >= 18, "temp_c"] = np.nan

        # c) rh_pct values in any day where rh_pct exceeds 100
        if "rh_pct" in df.columns:
            date_col = df["timestamp_utc"].dt.strftime("%Y-%m-%d")
            high_rh_days = set(date_col[df["rh_pct"] > 100.0])
            df.loc[date_col.isin(high_rh_days), "rh_pct"] = np.nan

        stations_data[station_id] = df

    # Align all stations on a common timestamp index
    all_timestamps = sorted(
        set().union(*(df["timestamp_utc"] for df in stations_data.values()))
    )
    common_index = pd.DatetimeIndex(all_timestamps)

    for st in stations_data:
        df = stations_data[st]
        df = df.set_index("timestamp_utc")
        df = df[~df.index.duplicated(keep="first")]
        stations_data[st] = df.reindex(common_index)

    # All dates in common index
    dates_list = sorted(set(common_index.strftime("%Y-%m-%d")))
    first_14_dates = set(dates_list[:14])

    # 1. Daily rain total (sum of rain_mm)
    rain_dict = {}
    for st, df in stations_data.items():
        rain_dict[st] = df["rain_mm"].groupby(df.index.strftime("%Y-%m-%d")).sum()
    rain_table = pd.DataFrame(rain_dict).round(1)
    rain_table.index.name = "date"

    # 2. Pressure difference from network median
    pressure_df = pd.DataFrame(
        {st: df["pressure_hpa"] for st, df in stations_data.items()}
    )
    pressure_dict = {}
    for st in pressure_df.columns:
        others = [c for c in pressure_df.columns if c != st]
        med_others = pressure_df[others].median(axis=1)
        diff = pressure_df[st] - med_others
        mask_14 = [d in first_14_dates for d in diff.index.strftime("%Y-%m-%d")]
        base_median = diff[mask_14].median()
        res = diff - base_median
        pressure_dict[st] = res.groupby(res.index.strftime("%Y-%m-%d")).mean()
    pressure_table = pd.DataFrame(pressure_dict).round(1)
    pressure_table.index.name = "date"

    # 3. Wind ratio to network median (exclude S01 from median)
    wind_df = pd.DataFrame({st: df["wind_kmh"] for st, df in stations_data.items()})
    wind_daily_mean = wind_df.groupby(wind_df.index.strftime("%Y-%m-%d")).mean()
    wind_dict = {}
    for st in wind_df.columns:
        others = [c for c in wind_df.columns if c != st and c != "S01"]
        med_others_ts = wind_df[others].median(axis=1)
        daily_mean_med_others = med_others_ts.groupby(
            med_others_ts.index.strftime("%Y-%m-%d")
        ).mean()
        wind_dict[st] = wind_daily_mean[st] / daily_mean_med_others
    wind_table = pd.DataFrame(wind_dict).round(1)
    wind_table.index.name = "date"

    # 4. Temperature max and min differences (exclude S01 from median)
    temp_df = pd.DataFrame({st: df["temp_c"] for st, df in stations_data.items()})
    daily_max = temp_df.groupby(temp_df.index.strftime("%Y-%m-%d")).max()
    daily_min = temp_df.groupby(temp_df.index.strftime("%Y-%m-%d")).min()

    temp_max_dict = {}
    temp_min_dict = {}
    for st in temp_df.columns:
        others = [c for c in temp_df.columns if c != st and c != "S01"]
        med_other_max = daily_max[others].median(axis=1)
        temp_max_dict[st] = daily_max[st] - med_other_max

        med_other_min = daily_min[others].median(axis=1)
        temp_min_dict[st] = daily_min[st] - med_other_min

    temp_max_table = pd.DataFrame(temp_max_dict).round(1)
    temp_max_table.index.name = "date"

    temp_min_table = pd.DataFrame(temp_min_dict).round(1)
    temp_min_table.index.name = "date"

    # Print tables
    print("1. Daily rain total (sum of rain_mm):")
    print(rain_table.to_string())
    print()

    print("2. Pressure (residual from network median, relative to first 14 days):")
    print(pressure_table.to_string())
    print()

    print("3. Wind (daily mean divided by daily mean of network median, excluding S01):")
    print(wind_table.to_string())
    print()

    print("4a. Temperature daily max minus network median (excluding S01):")
    print(temp_max_table.to_string())
    print()

    print("4b. Temperature daily min minus network median (excluding S01):")
    print(temp_min_table.to_string())


if __name__ == "__main__":
    main()
