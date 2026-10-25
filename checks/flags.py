"""Flag storage and serialization."""

import pandas as pd

COLUMNS = ["station_id", "channel", "start_utc", "end_utc", "issue", "action", "note"]
ACTIONS = {"exclude", "correct", "keep"}
FLAGS = []


def add_flag(station_id, channel, start_utc, end_utc, issue, action, note):
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}, got {action!r}")
    FLAGS.append({
        "station_id": station_id,
        "channel": channel,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "issue": issue,
        "action": action,
        "note": note,
    })


def write_flags(path):
    df = pd.DataFrame(FLAGS, columns=COLUMNS)
    df.to_csv(path, index=False)
