import glob
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


def parse_nmea_coord(coord_str, direction):
    dot_idx = coord_str.find(".")
    if dot_idx < 2:
        return None
    deg_str = coord_str[: dot_idx - 2]
    min_str = coord_str[dot_idx - 2 :]
    deg = float(deg_str) if deg_str else 0.0
    minutes = float(min_str)
    dec_deg = deg + minutes / 60.0
    if direction.upper() in ("S", "W"):
        dec_deg = -dec_deg
    return dec_deg


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0  # Earth radius in kilometers
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    delta_phi = np.radians(lat2 - lat1)
    delta_lambda = np.radians(lon2 - lon1)

    a = (
        np.sin(delta_phi / 2.0) ** 2
        + np.cos(phi1) * np.cos(phi2) * np.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return r * c


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        print("usage: python explore/03_gps.py <pack_folder>")
        sys.exit(1)

    pack_folder = sys.argv[1]

    # Load station metadata
    stations_csv = os.path.join(pack_folder, "stations.csv")
    stations_df = pd.read_csv(stations_csv)
    stations_info = {}
    for _, row in stations_df.iterrows():
        stations_info[str(row["station_id"])] = {
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "elevation_m": float(row["elevation_m"]),
        }

    gps_files = sorted(glob.glob(os.path.join(pack_folder, "gps", "S*.nmea")))

    for f in gps_files:
        station_id = os.path.splitext(os.path.basename(f))[0]
        st_info = stations_info.get(station_id, {})

        total_lines = 0
        bad_checksum_count = 0

        valid_lines = []

        with open(f, "r", encoding="utf-8", errors="ignore") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                total_lines += 1

                dollar_pos = line.find("$")
                star_pos = line.rfind("*")

                if dollar_pos == -1 or star_pos == -1 or star_pos <= dollar_pos:
                    bad_checksum_count += 1
                    continue

                body_for_ck = line[dollar_pos + 1 : star_pos]
                hex_str = line[star_pos + 1 : star_pos + 3]

                calc_ck = 0
                for ch in body_for_ck:
                    calc_ck ^= ord(ch)

                try:
                    given_ck = int(hex_str, 16)
                    if calc_ck != given_ck:
                        bad_checksum_count += 1
                        continue
                except ValueError:
                    bad_checksum_count += 1
                    continue

                logger_ts_str = line[:dollar_pos].rstrip(",")
                sentence_body = line[dollar_pos:star_pos]
                valid_lines.append((logger_ts_str, sentence_body))

        print(f"=== {station_id} ===")
        # 1. Checksum
        print(f"1. Checksum: total lines={total_lines}, bad checksum={bad_checksum_count}")

        # Process valid lines
        count_rmc_a = 0
        count_rmc_v = 0

        rmc_valid_records = []
        lats = []
        lons = []
        altitudes = []

        for logger_ts_str, sentence_body in valid_lines:
            parts = sentence_body.split(",")
            stype = parts[0]

            if stype == "$GPRMC":
                if len(parts) > 2:
                    status = parts[2]
                    if status == "A":
                        count_rmc_a += 1
                        # Parse clock
                        try:
                            time_int = parts[1].split(".")[0].zfill(6)
                            date_str = parts[9].zfill(6)
                            gps_dt = datetime.strptime(f"{date_str}{time_int}", "%d%m%y%H%M%S")

                            if len(logger_ts_str) >= 19:
                                logger_dt = datetime.strptime(logger_ts_str[:19], "%Y-%m-%d %H:%M:%S")
                            else:
                                logger_dt = datetime.strptime(logger_ts_str, "%Y-%m-%d %H:%M")

                            diff_sec = (logger_dt - gps_dt).total_seconds()
                            offset_min = int(round(diff_sec / 60.0))

                            rmc_valid_records.append((offset_min, logger_ts_str))
                        except Exception:
                            pass

                        # Parse position
                        try:
                            lat = parse_nmea_coord(parts[3], parts[4])
                            lon = parse_nmea_coord(parts[5], parts[6])
                            if lat is not None and lon is not None:
                                lats.append(lat)
                                lons.append(lon)
                        except Exception:
                            pass

                    elif status == "V":
                        count_rmc_v += 1

            elif stype == "$GPGGA":
                # Altitude
                if len(parts) > 9 and parts[9]:
                    try:
                        alt = float(parts[9])
                        altitudes.append(alt)
                    except ValueError:
                        pass

        # 2. $GPRMC status
        print(f"2. $GPRMC: status A={count_rmc_a}, status V={count_rmc_v}")

        # 3. Clock offset runs
        print("3. Clock offsets (runs of consecutive lines with same offset):")
        runs = []
        curr_offset = None
        first_ts = None
        last_ts = None
        run_count = 0

        for off, ts_str in rmc_valid_records:
            if curr_offset is None:
                curr_offset = off
                first_ts = ts_str
                last_ts = ts_str
                run_count = 1
            elif off == curr_offset:
                last_ts = ts_str
                run_count += 1
            else:
                runs.append((curr_offset, first_ts, last_ts, run_count))
                curr_offset = off
                first_ts = ts_str
                last_ts = ts_str
                run_count = 1

        if curr_offset is not None:
            runs.append((curr_offset, first_ts, last_ts, run_count))

        if runs:
            for r_off, r_first, r_last, r_len in runs:
                print(f"  offset={r_off} min, first={r_first}, last={r_last}, lines={r_len}")
        else:
            print("  None")

        # 4. Position
        print("4. Position:")
        if lats and lons:
            med_lat = float(np.median(lats))
            med_lon = float(np.median(lons))
            st_lat = st_info.get("lat", np.nan)
            st_lon = st_info.get("lon", np.nan)
            dist_km = haversine_km(med_lat, med_lon, st_lat, st_lon)
            print(f"  GPS median: lat={med_lat:.5f}, lon={med_lon:.5f}")
            print(f"  stations.csv: lat={st_lat:.5f}, lon={st_lon:.5f}")
            print(f"  Distance: {dist_km:.4f} km")
        else:
            print("  No valid GPS position data")

        # 5. Altitude
        print("5. Altitude:")
        if altitudes:
            med_alt = float(np.median(altitudes))
            st_elev = st_info.get("elevation_m", np.nan)
            print(f"  GPS median altitude: {med_alt:.1f} m")
            print(f"  stations.csv elevation_m: {st_elev:.1f} m")
        else:
            print("  No valid GPS altitude data")

        print()


if __name__ == "__main__":
    main()
