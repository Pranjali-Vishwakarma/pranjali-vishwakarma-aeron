"""Timestamp checks: gaps, duplicates, backwards jumps."""

import numpy as np
import pandas as pd

import checks.flags
import config

MEASUREMENT_COLS = [
    "temp_c",
    "rh_pct",
    "pressure_hpa",
    "wind_kmh",
    "wind_dir_deg",
    "rain_mm",
    "ghi_wm2",
]


def drop_resent(station_id: str, df: pd.DataFrame) -> pd.DataFrame:
    # Identify duplicate rows (same timestamp and all values, excluding file_row and logger_ts)
    data_cols = [c for c in df.columns if c not in ("file_row", "logger_ts")]
    is_dup = df.duplicated(subset=data_cols, keep="first")

    if is_dup.any():
        # Group consecutive duplicates into blocks
        blocks = []
        curr_block = []
        for idx in df.index:
            if is_dup.loc[idx]:
                curr_block.append(idx)
            else:
                if curr_block:
                    blocks.append(curr_block)
                    curr_block = []
        if curr_block:
            blocks.append(curr_block)

        for block_indices in blocks:
            block_df = df.loc[block_indices]
            count = len(block_df)
            first_row = int(block_df["file_row"].iloc[0])
            last_row = int(block_df["file_row"].iloc[-1])
            start_utc = block_df["logger_ts"].iloc[0].strftime("%Y-%m-%d %H:%M")
            end_utc = block_df["logger_ts"].iloc[-1].strftime("%Y-%m-%d %H:%M")
            note = (
                f"All {count} rows appear a second time, identical, at the end of the file "
                f"(rows {first_row}-{last_row}); drop the copy so rain is not counted twice."
            )
            checks.flags.add_flag(
                station_id, "all", start_utc, end_utc, "day re-sent twice", "exclude", note
            )

        df = df[~is_dup].copy()

    return df


def fix_clock(station_id: str, df: pd.DataFrame, runs: list) -> pd.DataFrame:
    df["ts"] = df["logger_ts"].copy()

    candidate_runs = [
        r
        for r in runs
        if abs(r[0]) >= config.CLOCK_TOL_MIN and r[3] >= config.CLOCK_MIN_LINES
    ]

    for idx, (offset_min, first_gps_log, last_gps_log, n_lines) in enumerate(candidate_runs):
        # find the first data row of that run
        jump_diffs = (df["logger_ts"] - df["logger_ts"].shift(1)).dt.total_seconds() / 60.0
        expected_jump = config.DATA_INTERVAL_MIN + offset_min
        jump_mask = (jump_diffs >= expected_jump - 15.0) & (jump_diffs <= expected_jump + 15.0)

        if jump_mask.any():
            start_pos = df.index.get_loc(df[jump_mask].index[0])
        else:
            cutoff = first_gps_log - pd.Timedelta(hours=1)
            matching = df[df["logger_ts"] >= cutoff]
            start_pos = df.index.get_loc(matching.index[0]) if len(matching) > 0 else 0

        # run ends at the row before next run starts or last row
        if idx + 1 < len(candidate_runs):
            next_off = candidate_runs[idx + 1][0]
            next_jump = config.DATA_INTERVAL_MIN + next_off
            next_mask = (jump_diffs >= next_jump - 15.0) & (jump_diffs <= next_jump + 15.0)
            if next_mask.any():
                end_pos = df.index.get_loc(df[next_mask].index[0]) - 1
            else:
                end_pos = len(df) - 1
        else:
            end_pos = len(df) - 1

        # Apply offset to ts: ts = logger_ts - offset
        target_indices = df.index[start_pos : end_pos + 1]
        df.loc[target_indices, "ts"] = df.loc[target_indices, "logger_ts"] - pd.Timedelta(minutes=offset_min)

        run_slice = df.loc[target_indices]
        start_utc = run_slice["ts"].iloc[0].strftime("%Y-%m-%d %H:%M")
        end_utc = run_slice["ts"].iloc[-1].strftime("%Y-%m-%d %H:%M")
        log_start = run_slice["logger_ts"].iloc[0].strftime("%Y-%m-%d %H:%M")
        log_end = run_slice["logger_ts"].iloc[-1].strftime("%Y-%m-%d %H:%M")
        first_file_row = int(run_slice["file_row"].iloc[0])
        last_file_row = int(run_slice["file_row"].iloc[-1])
        hours_add = -offset_min / 60.0

        note = (
            f"After the battery swap the logger ran {abs(offset_min)//60} h behind UTC "
            f"(GPS offset {offset_min} min in {n_lines} sentences; timestamps jump back "
            f"{abs(offset_min)//60} h at file row {first_file_row}); add {hours_add:.0f} h to logger times "
            f"{log_start} to {log_end}."
        )
        checks.flags.add_flag(
            station_id, "all", start_utc, end_utc, "logger clock on local time", "correct", note
        )

    return df


def find_gaps(station_id: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("ts").reset_index(drop=True)
    step_diffs = (df["ts"] - df["ts"].shift(1)).dt.total_seconds() / 60.0
    gap_indices = df.index[step_diffs > 1.5 * config.DATA_INTERVAL_MIN].tolist()

    for idx in gap_indices:
        prev_ts = df["ts"].iloc[idx - 1]
        curr_ts = df["ts"].iloc[idx]
        diff_min = step_diffs.iloc[idx]
        missing_count = int(round(diff_min / config.DATA_INTERVAL_MIN)) - 1
        start_utc = (prev_ts + pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)).strftime("%Y-%m-%d %H:%M")
        end_utc = (curr_ts - pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)).strftime("%Y-%m-%d %H:%M")
        hrs = int(diff_min // 60)
        mins = int(diff_min % 60)
        time_str = f"{hrs} h {mins} min" if hrs > 0 else f"{mins} min"
        note = (
            f"No data for {time_str} ({missing_count} missing records); "
            f"treat as missing, do not fill in."
        )
        checks.flags.add_flag(
            station_id, "all", start_utc, end_utc, "transmission gap", "exclude", note
        )

    # Returns df sorted by ts, with ts as index, keeping only measurement columns
    cols_to_keep = [c for c in MEASUREMENT_COLS if c in df.columns]
    return df.set_index("ts")[cols_to_keep]
