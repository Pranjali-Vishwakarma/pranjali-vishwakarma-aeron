import glob
import os
import sys

import pandas as pd


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python explore/02_timeline.py <pack_folder>")
        sys.exit(1)

    pack_folder = sys.argv[1]
    data_files = sorted(glob.glob(os.path.join(pack_folder, "data", "S*.csv")))

    for f in data_files:
        station_id = os.path.splitext(os.path.basename(f))[0]
        df = pd.read_csv(f)

        ts = pd.to_datetime(df["timestamp_utc"])

        # 1. Non-10-minute intervals (keeping file order)
        diffs = ts.diff()
        bad_indices = []
        for i in range(1, len(df)):
            if diffs.iloc[i] != pd.Timedelta(minutes=10):
                bad_indices.append(i)

        # 2. Duplicated timestamps
        dup_mask = df["timestamp_utc"].duplicated()
        has_dups = dup_mask.any()

        # Skip stations with nothing to report
        if not bad_indices and not has_dups:
            print(f"{station_id}: clean")
            continue

        print(f"=== {station_id} ===")

        # 1. Print step anomalies
        if bad_indices:
            print("1. Timestamp step anomalies:")
            for i in bad_indices:
                file_row = i + 2  # header is row 1
                prev_ts = df["timestamp_utc"].iloc[i - 1]
                curr_ts = df["timestamp_utc"].iloc[i]
                diff_val = diffs.iloc[i]
                print(
                    f"  station: {station_id}, file row: {file_row}, "
                    f"previous: {prev_ts}, this: {curr_ts}, diff: {diff_val}"
                )
                start_idx = max(0, i - 3)
                end_idx = min(len(df), i + 4)
                context_df = df.iloc[start_idx:end_idx]
                print(context_df.to_string())
                print()
        else:
            print("1. Timestamp step anomalies: None\n")

        # 2. Print duplicates
        if has_dups:
            dup_rows = df[dup_mask]
            num_dups = len(dup_rows)
            first_dup = dup_rows["timestamp_utc"].iloc[0]
            last_dup = dup_rows["timestamp_utc"].iloc[-1]

            other_cols = [c for c in df.columns if c != "timestamp_utc"]
            first_occurrences = {}
            count_identical = 0
            count_different = 0

            for idx, row in df.iterrows():
                t = row["timestamp_utc"]
                if t not in first_occurrences:
                    first_occurrences[t] = row[other_cols]
                else:
                    first_row = first_occurrences[t]
                    if row[other_cols].equals(first_row):
                        count_identical += 1
                    else:
                        count_different += 1

            print(
                f"2. Duplicated timestamp_utc values:\n"
                f"  station: {station_id}, count: {num_dups}, "
                f"first: {first_dup}, last: {last_dup}, "
                f"identical: {count_identical}, different: {count_different}\n"
            )
        else:
            print("2. Duplicated timestamp_utc values: None\n")

        # 3. Earliest and latest timestamp (true min and max)
        earliest_ts = ts.min().strftime("%Y-%m-%d %H:%M")
        latest_ts = ts.max().strftime("%Y-%m-%d %H:%M")
        print(f"3. Timestamp range (true min/max): earliest: {earliest_ts}, latest: {latest_ts}\n")


if __name__ == "__main__":
    main()
