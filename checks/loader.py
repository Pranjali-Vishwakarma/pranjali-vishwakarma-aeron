"""Read stations.csv, data/*.csv and gps/*.nmea from a data pack."""

import os

import numpy as np
import pandas as pd


def load_stations(pack: str) -> pd.DataFrame:
    path = os.path.join(pack, "stations.csv")
    df = pd.read_csv(path)
    return df.set_index("station_id")


def load_data(pack: str, station_id: str) -> pd.DataFrame:
    path = os.path.join(pack, "data", f"{station_id}.csv")
    df = pd.read_csv(path)
    df["file_row"] = np.arange(2, len(df) + 2)
    df["logger_ts"] = pd.to_datetime(df["timestamp_utc"])
    return df


def load_gps(pack: str, station_id: str) -> pd.DataFrame:
    path = os.path.join(pack, "gps", f"{station_id}.nmea")
    if not os.path.isfile(path):
        return pd.DataFrame(columns=["logger_ts", "sentence"])

    records = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            dollar_idx = line.find("$")
            if dollar_idx != -1:
                ts_str = line[:dollar_idx].rstrip(",")
                sentence = line[dollar_idx:]
                records.append({
                    "logger_ts": pd.to_datetime(ts_str),
                    "sentence": sentence,
                })
            else:
                parts = line.split(",", 1)
                if len(parts) == 2:
                    records.append({
                        "logger_ts": pd.to_datetime(parts[0]),
                        "sentence": parts[1],
                    })

    if records:
        return pd.DataFrame(records)
    return pd.DataFrame(columns=["logger_ts", "sentence"])
