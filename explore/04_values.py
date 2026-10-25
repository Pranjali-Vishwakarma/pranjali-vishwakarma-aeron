import glob
import os
import sys

import pandas as pd

LIMITS = {
    "temp_c": (-35.0, 45.0),
    "rh_pct": (0.0, 100.0),
    "pressure_hpa": (500.0, 1080.0),
    "wind_kmh": (0.0, 150.0),
    "wind_dir_deg": (0.0, 360.0),
    "rain_mm": (0.0, 5.0),
    "ghi_wm2": (0.0, 1400.0),
}

FROZEN_COLS = ["temp_c", "rh_pct", "pressure_hpa"]


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python explore/04_values.py <pack_folder>")
        sys.exit(1)

    pack_folder = sys.argv[1]
    data_files = sorted(glob.glob(os.path.join(pack_folder, "data", "S*.csv")))

    for f in data_files:
        station_id = os.path.splitext(os.path.basename(f))[0]
        df = pd.read_csv(f)

        print(f"=== {station_id} ===")

        # 1. Out of range values
        print("1. Out of range:")
        any_out_of_range = False
        for col, (low, high) in LIMITS.items():
            if col not in df.columns:
                continue
            bad_mask = (df[col] < low) | (df[col] > high)
            bad_rows = df[bad_mask]
            count = len(bad_rows)
            if count > 0:
                any_out_of_range = True
                if count > 10:
                    first_ts = bad_rows["timestamp_utc"].iloc[0]
                    last_ts = bad_rows["timestamp_utc"].iloc[-1]
                    pairs = [
                        (row["timestamp_utc"], row[col])
                        for _, row in bad_rows.head(10).iterrows()
                    ]
                    print(
                        f"  station={station_id}, col={col}, count={count}, "
                        f"first_ts={first_ts}, last_ts={last_ts}"
                    )
                    print(f"    sample 10 pairs: {pairs}")
                else:
                    pairs = [
                        (row["timestamp_utc"], row[col])
                        for _, row in bad_rows.iterrows()
                    ]
                    print(f"  station={station_id}, col={col}, count={count}")
                    print(f"    pairs: {pairs}")

        if not any_out_of_range:
            print("  none")

        # 2. Frozen values
        print("2. Frozen values (runs >= 18 rows / 3 hours):")
        any_frozen = False
        for col in FROZEN_COLS:
            if col not in df.columns:
                continue
            curr_val = None
            first_ts = None
            last_ts = None
            run_len = 0
            runs = []

            for _, row in df.iterrows():
                val = row[col]
                ts = row["timestamp_utc"]
                if curr_val is None:
                    curr_val = val
                    first_ts = ts
                    last_ts = ts
                    run_len = 1
                elif val == curr_val:
                    last_ts = ts
                    run_len += 1
                else:
                    if run_len >= 18:
                        runs.append((curr_val, first_ts, last_ts, run_len))
                    curr_val = val
                    first_ts = ts
                    last_ts = ts
                    run_len = 1

            if curr_val is not None and run_len >= 18:
                runs.append((curr_val, first_ts, last_ts, run_len))

            if runs:
                any_frozen = True
                for val, f_ts, l_ts, r_len in runs:
                    print(
                        f"  station={station_id}, col={col}, value={val}, "
                        f"first={f_ts}, last={l_ts}, run_length={r_len}"
                    )

        if not any_frozen:
            print("  none")

        print()


if __name__ == "__main__":
    main()
