import os
import sys

import pandas as pd


def print_slice(data_dir, station_id, start_ts, end_ts):
    file_path = os.path.join(data_dir, f"{station_id}.csv")
    df = pd.read_csv(file_path)
    mask = (df["timestamp_utc"] >= start_ts) & (df["timestamp_utc"] <= end_ts)
    sub_df = df[mask]
    print(f"=== {station_id} ({start_ts} to {end_ts}) ===")
    print(sub_df.to_string(index=False))
    print()


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python explore/07_verify.py <pack_folder>")
        sys.exit(1)

    pack_folder = sys.argv[1]
    data_dir = os.path.join(pack_folder, "data")

    # 1. S02.csv: 2025-03-21 16:50 to 2025-03-21 17:50
    print_slice(data_dir, "S02", "2025-03-21 16:50", "2025-03-21 17:50")

    # 2. S07.csv: 2025-03-26 14:30 to 2025-03-26 17:00
    print_slice(data_dir, "S07", "2025-03-26 14:30", "2025-03-26 17:00")

    # 3. S05.csv: 2025-03-07 11:00 to 2025-03-07 13:00
    print_slice(data_dir, "S05", "2025-03-07 11:00", "2025-03-07 13:00")


if __name__ == "__main__":
    main()
