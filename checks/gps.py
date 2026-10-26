"""GPS checks: NMEA parsing, checksum, position vs install sheet, logger clock vs GPS."""

import numpy as np
import pandas as pd

import checks.flags
import config


def checksum_ok(sentence: str) -> bool:
    dollar_pos = sentence.find("$")
    star_pos = sentence.rfind("*")
    if dollar_pos == -1 or star_pos == -1 or star_pos <= dollar_pos:
        return False
    body = sentence[dollar_pos + 1 : star_pos]
    hex_str = sentence[star_pos + 1 : star_pos + 3]
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
    deg = float(coord_str[: dot_idx - 2])
    minutes = float(coord_str[dot_idx - 2 :])
    dec = deg + minutes / 60.0
    if direction.upper() in ("S", "W"):
        dec = -dec
    return dec


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = (
        np.sin(dphi / 2.0) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    )
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return r * c


def parse_rmc(gps_df: pd.DataFrame) -> pd.DataFrame:
    records = []
    if gps_df.empty:
        return pd.DataFrame(
            columns=["logger_ts", "gps_ts", "lat", "lon", "offset_min"]
        )

    for _, row in gps_df.iterrows():
        sentence = row["sentence"]
        if not checksum_ok(sentence):
            continue
        dollar_pos = sentence.find("$")
        star_pos = sentence.rfind("*")
        parts = sentence[dollar_pos:star_pos].split(",")
        if parts[0] != "$GPRMC" or len(parts) <= 9:
            continue
        status = parts[2]
        if status != "A":
            continue

        logger_ts = row["logger_ts"]
        try:
            time_str = parts[1].split(".")[0].zfill(6)
            date_str = parts[9].zfill(6)
            gps_ts = pd.to_datetime(f"{date_str}{time_str}", format="%d%m%y%H%M%S")
            lat = _parse_coord(parts[3], parts[4])
            lon = _parse_coord(parts[5], parts[6])
            diff_sec = (logger_ts - gps_ts).total_seconds()
            offset_min = int(round(diff_sec / 60.0))

            records.append({
                "logger_ts": logger_ts,
                "gps_ts": gps_ts,
                "lat": lat,
                "lon": lon,
                "offset_min": offset_min,
            })
        except Exception:
            continue

    return pd.DataFrame(records)


def clock_runs(rmc: pd.DataFrame) -> list:
    runs = []
    if rmc.empty:
        return runs

    curr_offset = None
    first_ts = None
    last_ts = None
    count = 0

    for _, row in rmc.iterrows():
        off = row["offset_min"]
        lts = row["logger_ts"]
        if curr_offset is None:
            curr_offset = off
            first_ts = lts
            last_ts = lts
            count = 1
        elif off == curr_offset:
            last_ts = lts
            count += 1
        else:
            runs.append((curr_offset, first_ts, last_ts, count))
            curr_offset = off
            first_ts = lts
            last_ts = lts
            count = 1

    if curr_offset is not None:
        runs.append((curr_offset, first_ts, last_ts, count))

    return runs


def check_position(
    station_id: str,
    station_row: pd.Series,
    rmc: pd.DataFrame,
    gps_df: pd.DataFrame,
) -> dict:
    corrected = {}

    start_str = ""
    end_str = ""
    if not rmc.empty and "gps_ts" in rmc.columns and rmc["gps_ts"].notna().any():
        start_str = rmc["gps_ts"].min().strftime("%Y-%m-%d %H:%M")
        end_str = rmc["gps_ts"].max().strftime("%Y-%m-%d %H:%M")

    # Position check (lat / lon)
    if not rmc.empty and rmc["lat"].notna().any():
        med_lat = float(rmc["lat"].median())
        med_lon = float(rmc["lon"].median())
        sheet_lat = float(station_row["lat"])
        sheet_lon = float(station_row["lon"])
        dist_km = haversine_km(med_lat, med_lon, sheet_lat, sheet_lon)

        if dist_km > config.POS_TOL_KM:
            checks.flags.add_flag(
                station_id=station_id,
                channel="metadata",
                start_utc=start_str,
                end_utc=end_str,
                issue="install-sheet latitude wrong",
                action="correct",
                note=(
                    f"{len(rmc)} GPS fixes agree on {med_lat:.3f} N, {med_lon:.4f} W; "
                    f"the sheet says {sheet_lat:.3f}, {sheet_lon:.4f} ({dist_km:.1f} km away); "
                    f"use the GPS latitude."
                ),
            )
            corrected["lat"] = med_lat
            corrected["lon"] = med_lon

    # Altitude check ($GPGGA)
    altitudes = []
    if not gps_df.empty:
        for _, row in gps_df.iterrows():
            sentence = row["sentence"]
            if not checksum_ok(sentence):
                continue
            dollar_pos = sentence.find("$")
            star_pos = sentence.rfind("*")
            parts = sentence[dollar_pos:star_pos].split(",")
            if parts[0] == "$GPGGA" and len(parts) > 9 and parts[9]:
                try:
                    altitudes.append(float(parts[9]))
                except ValueError:
                    pass

    if altitudes:
        med_alt = float(np.median(altitudes))
        sheet_elev = float(station_row["elevation_m"])
        if abs(med_alt - sheet_elev) > config.ELEV_TOL_M:
            checks.flags.add_flag(
                station_id=station_id,
                channel="metadata",
                start_utc=start_str,
                end_utc=end_str,
                issue="install-sheet elevation wrong",
                action="correct",
                note=(
                    f"GPS median altitude {med_alt:.1f} m differs from sheet elevation "
                    f"{sheet_elev:.1f} m (> {config.ELEV_TOL_M} m); use GPS altitude."
                ),
            )
            corrected["elevation_m"] = med_alt

    return corrected


def check_link(all_gps: dict):
    station_stats = {}
    for st, gps_df in all_gps.items():
        total = len(gps_df)
        if total == 0:
            rate = 0.0
            bad = 0
        else:
            bad = sum(1 for s in gps_df["sentence"] if not checksum_ok(s))
            rate = bad / total
        station_stats[st] = {"total": total, "bad": bad, "rate": rate, "df": gps_df}

    rates = [s["rate"] for s in station_stats.values()]
    net_median_rate = float(np.median(rates)) if rates else 0.0

    for st, stats in station_stats.items():
        total = stats["total"]
        bad = stats["bad"]
        rate = stats["rate"]
        gps_df = stats["df"]

        if (
            rate > config.BAD_CHECKSUM_FACTOR * net_median_rate
            and rate > config.BAD_CHECKSUM_MIN_RATE
        ):
            start_str = (
                gps_df["logger_ts"].min().strftime("%Y-%m-%d %H:%M")
                if not gps_df.empty
                else ""
            )
            end_str = (
                gps_df["logger_ts"].max().strftime("%Y-%m-%d %H:%M")
                if not gps_df.empty
                else ""
            )
            checks.flags.add_flag(
                station_id=st,
                channel="metadata",
                start_utc=start_str,
                end_utc=end_str,
                issue="noisy GPS link",
                action="keep",
                note=(
                    f"{bad} of {total} GPS sentences fail the checksum "
                    f"({rate * 100:.1f}%) vs network median {net_median_rate * 100:.1f}%; "
                    f"bad lines ignored, weather data unaffected; check the GPS cable."
                ),
            )
