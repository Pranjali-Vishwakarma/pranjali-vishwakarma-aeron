"""Read stations.csv, data/*.csv and gps/*.nmea from a data pack."""

import os
import pandas as pd


def load_stations(pack: str) -> pd.DataFrame:
    path = os.path.join(pack, "stations.csv")
    df = pd.read_csv(path)
    df["station_id"] = df["station_id"].astype(str)
    return df.set_index("station_id")


def load_data(pack: str, station_id: str) -> pd.DataFrame:
    path = os.path.join(pack, "data", f"{station_id}.csv")
    df = pd.read_csv(path)
    df["file_row"] = df.index + 2
    df["logger_ts"] = pd.to_datetime(df["timestamp_utc"])
    return df


def load_gps(pack: str, station_id: str) -> pd.DataFrame:
    path = os.path.join(pack, "gps", f"{station_id}.nmea")
    if not os.path.exists(path):
        return pd.DataFrame(columns=["logger_ts", "sentence"])

    logger_ts_list = []
    sentence_list = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            dollar_pos = line.find("$")
            if dollar_pos == -1:
                continue
            ts_str = line[:dollar_pos].rstrip(",")
            sentence = line[dollar_pos:]
            try:
                ts = pd.to_datetime(ts_str)
                logger_ts_list.append(ts)
                sentence_list.append(sentence)
            except Exception:
                continue

    return pd.DataFrame({"logger_ts": logger_ts_list, "sentence": sentence_list})
