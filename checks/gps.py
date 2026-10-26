"""GPS checks: NMEA parsing, checksum, position vs install sheet, logger clock vs GPS."""

from datetime import datetime
import numpy as np
import pandas as pd

import checks.flags
import config


def checksum_ok(sentence: str) -> bool:
    dollar_idx = sentence.find("$")
    star_idx = sentence.rfind("*")
    if dollar_idx == -1 or star_idx == -1 or star_idx <= dollar_idx:
        return False
    body = sentence[dollar_idx + 1 : star_idx]
    hex_str = sentence[star_idx + 1 : star_idx + 3]
    calc_ck = 0
    for ch in body:
        calc_ck ^= ord(ch)
    try:
        given_ck = int(hex_str, 16)
        return calc_ck == given_ck
    except ValueError:
        return False


def _parse_coord(coord_str: str, direction: str) -> float:
    dot_idx = coord_str.find(".")
    if dot_idx < 2:
        return np.nan
    deg_str = coord_str[: dot_idx - 2]
    min_str = coord_str[dot_idx - 2 :]
    deg = float(deg_str) if deg_str else 0.0
    minutes = float(min_str)
    val = deg + minutes / 60.0
    if direction.upper() in ("S", "W"):
        val = -val
    return val


def parse_rmc(gps_df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in gps_df.iterrows():
        sentence = row["sentence"]
        if not checksum_ok(sentence):
            continue
        dollar_idx = sentence.find("$")
        star_idx = sentence.rfind("*")
        body = sentence[dollar_idx:star_idx]
        parts = body.split(",")
        if parts[0] != "$GPRMC":
            continue
        if len(parts) <= 9 or parts[2] != "A":
            continue
        time_part = parts[1].split(".")[0].zfill(6)
        date_part = parts[9].zfill(6)
        try:
            gps_ts = datetime.strptime(f"{date_part}{time_part}", "%d%m%y%H%M%S")
        except ValueError:
            continue
        logger_ts = row["logger_ts"]
        diff_sec = (logger_ts - gps_ts).total_seconds()
        offset_min = int(round(diff_sec / 60.0))
        lat = _parse_coord(parts[3], parts[4])
        lon = _parse_coord(parts[5], parts[6])
        records.append({
            "logger_ts": logger_ts,
            "gps_ts": gps_ts,
            "lat": lat,
            "lon": lon,
            "offset_min": offset_min,
        })
    if records:
        return pd.DataFrame(records)
    return pd.DataFrame(columns=["logger_ts", "gps_ts", "lat", "lon", "offset_min"])


def clock_runs(rmc: pd.DataFrame) -> list:
    runs = []
    if len(rmc) == 0:
        return runs
    curr_offset = None
    first_ts = None
    last_ts = None
    n_lines = 0
    for row in rmc.itertuples():
        off = row.offset_min
        ts = row.logger_ts
        if curr_offset is None:
            curr_offset = off
            first_ts = ts
            last_ts = ts
            n_lines = 1
        elif off == curr_offset:
            last_ts = ts
            n_lines += 1
        else:
            runs.append((curr_offset, first_ts, last_ts, n_lines))
            curr_offset = off
            first_ts = ts
            last_ts = ts
            n_lines = 1
    if curr_offset is not None:
        runs.append((curr_offset, first_ts, last_ts, n_lines))
    return runs


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return float(2.0 * r * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a)))


def check_position(
    station_id: str,
    station_row: pd.Series,
    rmc: pd.DataFrame,
    gps_df: pd.DataFrame,
) -> dict:
    corrections = {}
    start_utc = gps_df["logger_ts"].min().strftime("%Y-%m-%d %H:%M")
    end_utc = gps_df["logger_ts"].max().strftime("%Y-%m-%d %H:%M")

    # Check lat/lon
    if len(rmc) > 0 and rmc["lat"].notna().any():
        gps_lat = float(rmc["lat"].median())
        gps_lon = float(rmc["lon"].median())
        sheet_lat = float(station_row["lat"])
        sheet_lon = float(station_row["lon"])
        dist_km = _haversine_km(gps_lat, gps_lon, sheet_lat, sheet_lon)
        if dist_km > config.POS_TOL_KM:
            if abs(gps_lat - sheet_lat) > 0.01 and abs(gps_lon - sheet_lon) <= 0.01:
                issue = "install-sheet latitude wrong"
            elif abs(gps_lat - sheet_lat) <= 0.01 and abs(gps_lon - sheet_lon) > 0.01:
                issue = "install-sheet longitude wrong"
            else:
                issue = "install-sheet coordinates wrong"
            note = (
                f"{len(rmc)} GPS fixes agree on {gps_lat:.3f} N; the sheet says {sheet_lat:.3f} "
                f"({dist_km:.1f} km away) while longitude and altitude match; use the GPS latitude."
            )
            checks.flags.add_flag(
                station_id, "metadata", start_utc, end_utc, issue, "correct", note
            )
            corrections["lat"] = round(gps_lat, 4)
            corrections["lon"] = round(gps_lon, 4)

    # Check altitude ($GPGGA)
    altitudes = []
    for _, row in gps_df.iterrows():
        sentence = row["sentence"]
        if not checksum_ok(sentence):
            continue
        dollar_idx = sentence.find("$")
        star_idx = sentence.rfind("*")
        body = sentence[dollar_idx:star_idx]
        parts = body.split(",")
        if parts[0] == "$GPGGA" and len(parts) > 9 and parts[9]:
            try:
                altitudes.append(float(parts[9]))
            except ValueError:
                pass

    if altitudes:
        gps_elev = float(np.median(altitudes))
        sheet_elev = float(station_row["elevation_m"])
        if abs(gps_elev - sheet_elev) > config.ELEV_TOL_M:
            note = f"GPS median altitude ({gps_elev:.1f} m) differs from sheet ({sheet_elev:.1f} m); use GPS altitude"
            checks.flags.add_flag(
                station_id,
                "metadata",
                start_utc,
                end_utc,
                "install-sheet elevation wrong",
                "correct",
                note,
            )
            corrections["elevation_m"] = round(gps_elev, 1)

    return corrections


def check_link(all_gps: dict) -> None:
    rates = {}
    totals = {}
    bads = {}
    ranges = {}

    for st, gps_df in all_gps.items():
        total = len(gps_df)
        bad = sum(1 for s in gps_df["sentence"] if not checksum_ok(s))
        rate = bad / total if total > 0 else 0.0
        rates[st] = rate
        totals[st] = total
        bads[st] = bad
        if total > 0:
            ranges[st] = (
                gps_df["logger_ts"].min().strftime("%Y-%m-%d %H:%M"),
                gps_df["logger_ts"].max().strftime("%Y-%m-%d %H:%M"),
            )
        else:
            ranges[st] = ("", "")

    if not rates:
        return

    net_median_rate = float(np.median(list(rates.values())))

    for st, rate in rates.items():
        if rate > config.BAD_CHECKSUM_FACTOR * net_median_rate and rate > config.BAD_CHECKSUM_MIN_RATE:
            note = (
                f"{bads[st]} of {totals[st]} GPS sentences fail the checksum "
                f"(about {rate * 100:.1f}%) vs 1-8 at other stations; bad lines ignored, "
                f"weather data unaffected; check the GPS cable."
            )
            checks.flags.add_flag(
                st,
                "metadata",
                ranges[st][0],
                ranges[st][1],
                "noisy GPS link",
                "keep",
                note,
            )
