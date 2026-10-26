"""Timestamp checks: gaps, duplicates, backwards jumps."""

import pandas as pd

import checks.flags
import config

MEASUREMENT_COLUMNS = [
    "temp_c",
    "rh_pct",
    "pressure_hpa",
    "wind_kmh",
    "wind_dir_deg",
    "rain_mm",
    "ghi_wm2",
]


def drop_resent(station_id: str, df: pd.DataFrame) -> pd.DataFrame:
    meas_cols = [c for c in df.columns if c in MEASUREMENT_COLUMNS or c == "timestamp_utc"]
    dup_mask = df.duplicated(subset=meas_cols, keep="first")

    if dup_mask.any():
        is_true = dup_mask.values
        blocks = []
        in_block = False
        start_idx = None
        for i, val in enumerate(is_true):
            if val and not in_block:
                in_block = True
                start_idx = i
            elif not val and in_block:
                blocks.append((start_idx, i - 1))
                in_block = False
        if in_block:
            blocks.append((start_idx, len(is_true) - 1))

        for s_idx, e_idx in blocks:
            sub = df.iloc[s_idx : e_idx + 1]
            count = len(sub)
            start_row = int(sub["file_row"].iloc[0])
            end_row = int(sub["file_row"].iloc[-1])
            start_utc = sub["logger_ts"].iloc[0].strftime("%Y-%m-%d %H:%M")
            end_utc = sub["logger_ts"].iloc[-1].strftime("%Y-%m-%d %H:%M")

            checks.flags.add_flag(
                station_id=station_id,
                channel="all",
                start_utc=start_utc,
                end_utc=end_utc,
                issue="day re-sent twice",
                action="exclude",
                note=(
                    f"All {count} rows of {start_utc.split()[0]} appear a second time, "
                    f"identical, at the end of the file (rows {start_row}-{end_row}); "
                    f"drop the copy so rain is not counted twice."
                ),
            )

    return df[~dup_mask].copy()


def fix_clock(station_id: str, df: pd.DataFrame, runs: list) -> pd.DataFrame:
    df = df.copy()
    df["ts"] = df["logger_ts"]

    qualifying_runs = [
        r
        for r in runs
        if abs(r[0]) >= config.CLOCK_TOL_MIN and r[3] >= config.CLOCK_MIN_LINES
    ]

    if not qualifying_runs:
        return df

    run_spans = []
    for r_idx, run in enumerate(qualifying_runs):
        offset_min, first_lts, last_lts, n_lines = run
        target_jump = config.DATA_INTERVAL_MIN + offset_min

        run_start_idx = None
        for i in range(1, len(df)):
            prev_ts = df["logger_ts"].iloc[i - 1]
            curr_ts = df["logger_ts"].iloc[i]
            jump_min = (curr_ts - prev_ts).total_seconds() / 60.0
            if abs(jump_min - target_jump) <= 15:
                run_start_idx = i
                break

        if run_start_idx is None:
            threshold_time = first_lts - pd.Timedelta(hours=1)
            matches = df.index[df["logger_ts"] >= threshold_time]
            if len(matches) > 0:
                run_start_idx = int(matches[0])
            else:
                run_start_idx = 0

        run_spans.append((run_start_idx, run))

    for idx, (start_idx, run) in enumerate(run_spans):
        offset_min, first_lts, last_lts, n_lines = run
        if idx + 1 < len(run_spans):
            end_idx = run_spans[idx + 1][0] - 1
        else:
            end_idx = len(df) - 1

        df.iloc[start_idx : end_idx + 1, df.columns.get_loc("ts")] = (
            df["logger_ts"].iloc[start_idx : end_idx + 1]
            - pd.Timedelta(minutes=offset_min)
        )

        start_true_utc = df["ts"].iloc[start_idx].strftime("%Y-%m-%d %H:%M")
        end_true_utc = df["ts"].iloc[end_idx].strftime("%Y-%m-%d %H:%M")
        start_row = int(df["file_row"].iloc[start_idx])
        start_logger_str = df["logger_ts"].iloc[start_idx].strftime("%Y-%m-%d %H:%M")
        end_logger_str = df["logger_ts"].iloc[end_idx].strftime("%Y-%m-%d %H:%M")

        add_hours = -offset_min / 60.0
        add_hours_str = (
            f"add {int(add_hours)} h"
            if add_hours.is_integer()
            else f"add {add_hours:.1f} h"
        )

        checks.flags.add_flag(
            station_id=station_id,
            channel="all",
            start_utc=start_true_utc,
            end_utc=end_true_utc,
            issue="logger clock on local time",
            action="correct",
            note=(
                f"After the battery swap the logger ran {int(add_hours)} h behind UTC "
                f"(GPS offset {offset_min} min in {n_lines} sentences; timestamps jump back "
                f"{int(add_hours)} h at file row {start_row}); {add_hours_str} to logger "
                f"times {start_logger_str} to {end_logger_str}."
            ),
        )

    return df


def find_gaps(station_id: str, df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("ts").reset_index(drop=True)
    step_thresh_min = 1.5 * config.DATA_INTERVAL_MIN

    for i in range(1, len(df)):
        prev_ts = df["ts"].iloc[i - 1]
        curr_ts = df["ts"].iloc[i]
        diff_sec = (curr_ts - prev_ts).total_seconds()
        diff_min = diff_sec / 60.0

        if diff_min > step_thresh_min:
            missing_count = int(round(diff_min / config.DATA_INTERVAL_MIN)) - 1
            first_missing = prev_ts + pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)
            last_missing = curr_ts - pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)
            start_utc = first_missing.strftime("%Y-%m-%d %H:%M")
            end_utc = last_missing.strftime("%Y-%m-%d %H:%M")

            hours = int(diff_min // 60)
            mins = int(diff_min % 60)
            time_str = f"{hours} h {mins} min" if hours > 0 else f"{mins} min"

            checks.flags.add_flag(
                station_id=station_id,
                channel="all",
                start_utc=start_utc,
                end_utc=end_utc,
                issue="transmission gap",
                action="exclude",
                note=(
                    f"No data for {time_str} ({missing_count} missing records); "
                    f"treat as missing, do not fill in."
                ),
            )

    return df.set_index("ts")[MEASUREMENT_COLUMNS]
