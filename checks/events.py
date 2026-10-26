"""Network-wide real events that look odd but are real (keep)."""

import numpy as np
import pandas as pd

import checks.flags
import config


def storms(stations, PANEL, BAD):
    """Daily rain totals; runs of days where >= EVENT_RAIN_SHARE of stations have >= EVENT_RAIN_MM."""
    rain_df = PANEL["rain_mm"]
    bad_rain = BAD["rain_mm"]

    ts = rain_df.index
    dates = sorted(set(ts.strftime("%Y-%m-%d")))

    wet_counts = {}
    storm_day = {}
    for d in dates:
        mask_d = ts.strftime("%Y-%m-%d") == d
        sub_rain = rain_df.loc[mask_d]
        sub_bad = bad_rain.loc[mask_d]

        valid_stations = [st for st in stations.index if not sub_bad[st].any()]
        n_valid = len(valid_stations)

        if n_valid > 0:
            daily_totals = sub_rain[valid_stations].sum()
            n_wet = int((daily_totals >= config.EVENT_RAIN_MM).sum())
            share = n_wet / n_valid
        else:
            n_wet = 0
            share = 0.0

        wet_counts[d] = n_wet
        storm_day[d] = share >= config.EVENT_RAIN_SHARE

    wet_stations_per_day = pd.Series(wet_counts)
    storm_day = pd.Series(storm_day)
    n_stations = len(stations)

    # Find consecutive runs of storm days
    run_start = None
    for i, (date_str, is_storm) in enumerate(storm_day.items()):
        if is_storm and run_start is None:
            run_start = i
        elif not is_storm and run_start is not None:
            _flag_storm(dates[run_start:i], wet_stations_per_day, n_stations, ts)
            run_start = None
    if run_start is not None:
        _flag_storm(dates[run_start:], wet_stations_per_day, n_stations, ts)


def _flag_storm(run_dates, wet_counts, n_stations, ts_index):
    start_date = run_dates[0]
    end_date = run_dates[-1]
    ts_sub = ts_index[(ts_index.strftime("%Y-%m-%d") >= start_date) & (ts_index.strftime("%Y-%m-%d") <= end_date)]
    start_utc = ts_sub[0].strftime("%Y-%m-%d %H:%M")
    end_utc = ts_sub[-1].strftime("%Y-%m-%d %H:%M")

    max_wet = int(wet_counts.loc[run_dates].max())
    note = (
        f"{max_wet} of {n_stations} stations got >={config.EVENT_RAIN_MM:.1f} mm; "
        "real weather, not a fault."
    )
    checks.flags.add_flag(
        station_id="ALL",
        channel="rain_mm",
        start_utc=start_utc,
        end_utc=end_utc,
        issue="network-wide storm",
        action="keep",
        note=note,
    )


def fog(stations, PANEL, BAD):
    """Runs of timestamps where >= EVENT_RH_SHARE of stations have rh_pct >= EVENT_RH lasting >= EVENT_RH_MIN_HOURS."""
    rh_df = PANEL["rh_pct"].copy()
    rh_df[BAD["rh_pct"]] = np.nan

    n_stations = len(stations)
    wet_stations = (rh_df >= config.EVENT_RH).sum(axis=1)
    fog_mask = (wet_stations / n_stations) >= config.EVENT_RH_SHARE

    ts = rh_df.index
    step_delta = pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)

    run_indices = []
    for i, is_fog in enumerate(fog_mask):
        if is_fog:
            if not run_indices or (i == run_indices[-1] + 1 and (ts[i] - ts[i - 1]) == step_delta):
                run_indices.append(i)
            else:
                _check_and_flag_fog(run_indices, ts, n_stations)
                run_indices = [i]
        else:
            if run_indices:
                _check_and_flag_fog(run_indices, ts, n_stations)
                run_indices = []

    if run_indices:
        _check_and_flag_fog(run_indices, ts, n_stations)


def _check_and_flag_fog(run_indices, ts, n_stations):
    n_steps = len(run_indices)
    duration_hours = n_steps * (config.DATA_INTERVAL_MIN / 60.0)
    if duration_hours >= config.EVENT_RH_MIN_HOURS:
        start_utc = ts[run_indices[0]].strftime("%Y-%m-%d %H:%M")
        end_utc = ts[run_indices[-1]].strftime("%Y-%m-%d %H:%M")
        note = (
            f"Stations at >={config.EVENT_RH:.1f}% humidity for {duration_hours:.1f} h; "
            "real fog, not a sensor fault."
        )
        checks.flags.add_flag(
            station_id="ALL",
            channel="rh_pct",
            start_utc=start_utc,
            end_utc=end_utc,
            issue="network-wide fog",
            action="keep",
            note=note,
        )
