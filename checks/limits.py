"""Single-station checks: impossible values and frozen readings."""

import numpy as np
import pandas as pd

import checks.flags
import checks.neighbours
import config


def out_of_range(stations: pd.DataFrame, PANEL: dict, BAD: dict):
    for ch, (low, high) in config.LIMITS.items():
        if ch not in PANEL:
            continue
        effective_high = high + config.RH_TOL if ch == "rh_pct" else high
        for st in stations.index:
            s = PANEL[ch].loc[:, st]
            mask = (s < low) | (s > effective_high)
            BAD[ch].loc[mask, st] = True

            if ch in ("rh_pct", "rain_mm"):
                continue

            for start_ts, end_ts, n in checks.neighbours.runs(mask):
                sub_vals = s.loc[start_ts:end_ts]
                start_str = start_ts.strftime("%Y-%m-%d %H:%M")
                end_str = end_ts.strftime("%Y-%m-%d %H:%M")

                is_error_code = ((sub_vals == -40.0) | (sub_vals == 85.0)).all()
                if is_error_code:
                    val = sub_vals.iloc[0]
                    val_str = f"{val:.1f}"
                    val_int = f"{int(val)}" if val.is_integer() else val_str
                    note = (
                        f"Single reading of {val_str} C between normal values; "
                        f"{val_int} is a typical sensor error code."
                        if n == 1
                        else f"{n} readings of {val_str} C; typical sensor error code."
                    )
                    issue = "sensor error code"
                else:
                    note = f"{n} readings outside physical limits [{low}, {effective_high}]; exclude."
                    issue = "out of range"

                checks.flags.add_flag(
                    station_id=st,
                    channel=ch,
                    start_utc=start_str,
                    end_utc=end_str,
                    issue=issue,
                    action="exclude",
                    note=note,
                )


def frozen(stations: pd.DataFrame, PANEL: dict, BAD: dict):
    for ch, hours in config.FLATLINE_HOURS.items():
        if ch not in PANEL:
            continue
        min_rows = int(hours * 60 / config.DATA_INTERVAL_MIN)
        for st in stations.index:
            s = PANEL[ch].loc[:, st]
            is_diff = (s != s.shift(1)) | (s.isna() != s.shift(1).isna())
            run_id = is_diff.cumsum()
            for _, grp in s.groupby(run_id):
                if grp.isna().all():
                    continue
                if len(grp) >= min_rows:
                    val = grp.iloc[0]
                    if ch == "rh_pct" and val >= 98:
                        continue
                    start_ts = grp.index[0]
                    end_ts = grp.index[-1]
                    BAD[ch].loc[start_ts:end_ts, st] = True

                    start_str = start_ts.strftime("%Y-%m-%d %H:%M")
                    end_str = end_ts.strftime("%Y-%m-%d %H:%M")
                    duration_h = int(len(grp) * config.DATA_INTERVAL_MIN / 60)

                    note = (
                        f"Temperature stuck at exactly {val:.1f} C for {len(grp)} readings ({duration_h} h) "
                        f"while humidity and neighbours kept changing."
                        if ch == "temp_c"
                        else f"Sensor stuck at {val} for {len(grp)} readings ({duration_h} h); exclude."
                    )
                    checks.flags.add_flag(
                        station_id=st,
                        channel=ch,
                        start_utc=start_str,
                        end_utc=end_str,
                        issue="sensor frozen",
                        action="exclude",
                        note=note,
                    )


def rh_saturation(stations: pd.DataFrame, PANEL: dict, BAD: dict, NB: dict = None):
    min_rows = int(6 * 60 / config.DATA_INTERVAL_MIN)
    for st in stations.index:
        s = PANEL["rh_pct"].loc[:, st]
        mask_98 = s >= 98.0
        for start_ts, end_ts, n in checks.neighbours.runs(mask_98):
            if n < min_rows:
                continue
            sub_rh = s.loc[start_ts:end_ts]
            has_above_tol = (sub_rh > 100.0 + config.RH_TOL).any()

            if NB and st in NB and len(NB[st]) >= 2:
                others = NB[st]
            else:
                others = [o for o in stations.index if o != st]

            other_rh = PANEL["rh_pct"].loc[start_ts:end_ts, others].where(
                ~BAD["rh_pct"].loc[start_ts:end_ts, others]
            )
            nb_med = other_rh.median(axis=1)
            nb_dry_frac = (nb_med < 85.0).mean()

            if has_above_tol or nb_dry_frac > 0.30:
                BAD["rh_pct"].loc[start_ts:end_ts, st] = True
                start_str = start_ts.strftime("%Y-%m-%d %H:%M")
                end_str = end_ts.strftime("%Y-%m-%d %H:%M")
                duration_days = (end_ts - start_ts).total_seconds() / 86400.0
                note = (
                    f"Humidity {int(sub_rh.min())}-{int(sub_rh.max())}% for {duration_days:.1f} days "
                    f"while neighbours were dry and no network fog was seen; "
                    f"wet or failed sensor that recovered on its own."
                )
                checks.flags.add_flag(
                    station_id=st,
                    channel="rh_pct",
                    start_utc=start_str,
                    end_utc=end_str,
                    issue="humidity sensor stuck high",
                    action="exclude",
                    note=note,
                )


def spikes(stations: pd.DataFrame, PANEL: dict, BAD: dict):
    for st in stations.index:
        s = PANEL["temp_c"].loc[:, st]
        valid_s = s.where(~BAD["temp_c"].loc[:, st])
        roll_med = valid_s.rolling(5, center=True, min_periods=3).median()
        diff = (valid_s - roll_med).abs()
        spike_mask = diff > config.SPIKE_C
        for start_ts, end_ts, n in checks.neighbours.runs(spike_mask):
            BAD["temp_c"].loc[start_ts:end_ts, st] = True
            start_str = start_ts.strftime("%Y-%m-%d %H:%M")
            end_str = end_ts.strftime("%Y-%m-%d %H:%M")
            checks.flags.add_flag(
                station_id=st,
                channel="temp_c",
                start_utc=start_str,
                end_utc=end_str,
                issue="temperature spike",
                action="exclude",
                note=f"Temperature jump > {config.SPIKE_C} C from local 5-point median; exclude.",
            )
