"""Sun position, timing checks, and night-time radiation checks."""

import numpy as np
import pandas as pd

import checks.flags
import config


def eot_minutes(ts):
    """Equation of time in minutes."""
    dayofyear = ts.dayofyear
    b = 2.0 * np.pi * (dayofyear - 81) / 364.0
    return 9.87 * np.sin(2.0 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)


def declination(ts):
    """Solar declination in degrees."""
    dayofyear = ts.dayofyear
    angle_deg = 360.0 * (284 + dayofyear) / 365.0
    return 23.45 * np.sin(np.radians(angle_deg))


def cos_zenith(ts, lat, lon):
    """Cosine of solar zenith angle."""
    eot = eot_minutes(ts)
    hour = ts.hour
    minute = ts.minute
    solar_time = hour + minute / 60.0 + lon / 15.0 + eot / 60.0
    hour_angle_deg = 15.0 * (solar_time - 12.0)

    lat_rad = np.radians(lat)
    dec_rad = np.radians(declination(ts))
    ha_rad = np.radians(hour_angle_deg)

    return np.sin(lat_rad) * np.sin(dec_rad) + np.cos(lat_rad) * np.cos(dec_rad) * np.cos(ha_rad)


def timing(stations, PANEL, BAD):
    """Check sun timing centroid vs solar noon to detect clock or longitude errors."""
    ghi_df = PANEL["ghi_wm2"].copy()
    ghi_df[BAD["ghi_wm2"]] = np.nan

    ts = ghi_df.index
    half_interval_hours = (config.DATA_INTERVAL_MIN / 2.0) / 60.0
    hours_mid = ts.hour + ts.minute / 60.0 - half_interval_hours
    dates = sorted(set(ts.strftime("%Y-%m-%d")))

    diff_records = {}
    for d in dates:
        dt = pd.to_datetime(d)
        eot = float(eot_minutes(dt))
        mask_d = ts.strftime("%Y-%m-%d") == d
        sub_hours = hours_mid[mask_d]

        diff_records[d] = {}
        for st in stations.index:
            lon = float(stations.loc[st, "lon"])
            solar_noon_hour = 12.0 - lon / 15.0 - eot / 60.0

            sub_ghi = ghi_df.loc[mask_d, st]
            total_ghi = sub_ghi.sum()
            if total_ghi > 0:
                centroid_hour = (sub_ghi * sub_hours).sum() / total_ghi
                diff_min = (centroid_hour - solar_noon_hour) * 60.0
                diff_records[d][st] = diff_min
            else:
                diff_records[d][st] = np.nan

    diff_df = pd.DataFrame.from_dict(diff_records, orient="index")
    net_median = diff_df.median(axis=1)
    rel_diff = diff_df.sub(net_median, axis=0)

    for st in stations.index:
        st_series = rel_diff[st].rolling(window=config.SUN_SHIFT_DAYS, center=True, min_periods=1).median()
        is_shift = st_series.abs() > config.SUN_SHIFT_MIN

        run_start = None
        for i, (date_str, shifted) in enumerate(is_shift.items()):
            if shifted and run_start is None:
                run_start = i
            elif not shifted and run_start is not None:
                run_len = i - run_start
                if run_len >= config.SUN_SHIFT_DAYS:
                    _flag_shift(st, dates[run_start:i], st_series, ts)
                run_start = None
        if run_start is not None:
            run_len = len(is_shift) - run_start
            if run_len >= config.SUN_SHIFT_DAYS:
                _flag_shift(st, dates[run_start:], st_series, ts)


def _flag_shift(station_id, run_dates, st_series, ts_index):
    start_date = run_dates[0]
    end_date = run_dates[-1]
    ts_sub = ts_index[(ts_index.strftime("%Y-%m-%d") >= start_date) & (ts_index.strftime("%Y-%m-%d") <= end_date)]
    start_utc = ts_sub[0].strftime("%Y-%m-%d %H:%M")
    end_utc = ts_sub[-1].strftime("%Y-%m-%d %H:%M")
    med_shift = float(st_series.loc[run_dates].median())
    checks.flags.add_flag(
        station_id=station_id,
        channel="all",
        start_utc=start_utc,
        end_utc=end_utc,
        issue="clock or longitude wrong",
        action="correct",
        note=f"Solar noon centroid shifted by {med_shift:.1f} minutes; clock or longitude wrong.",
    )


def night(stations, PANEL):
    """Check for readings with sunlight at night."""
    ghi_df = PANEL["ghi_wm2"]
    ts = ghi_df.index

    for st in stations.index:
        lat = float(stations.loc[st, "lat"])
        lon = float(stations.loc[st, "lon"])
        cos_z = cos_zenith(ts, lat, lon)
        ghi = ghi_df[st]

        offending = (ghi > config.NIGHT_GHI) & (cos_z < -0.1)
        count = int(offending.sum())
        if count > config.NIGHT_MAX_COUNT:
            offending_ts = ts[offending]
            start_utc = offending_ts[0].strftime("%Y-%m-%d %H:%M")
            end_utc = offending_ts[-1].strftime("%Y-%m-%d %H:%M")
            checks.flags.add_flag(
                station_id=st,
                channel="ghi_wm2",
                start_utc=start_utc,
                end_utc=end_utc,
                issue="sunlight at night",
                action="exclude",
                note=f"{count} readings with ghi > {config.NIGHT_GHI:.1f} W/m2 while sun down; night-time radiation sensor error.",
            )
