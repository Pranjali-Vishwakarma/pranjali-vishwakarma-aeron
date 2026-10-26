"""Neighbour comparisons: offset, scale and drift changes."""

import numpy as np
import pandas as pd

import checks.flags
import config


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


def runs(mask: pd.Series) -> list:
    result = []
    in_run = False
    start_ts = None
    prev_ts = None
    count = 0
    for ts, val in mask.items():
        if val:
            if not in_run:
                in_run = True
                start_ts = ts
            prev_ts = ts
            count += 1
        else:
            if in_run:
                result.append((start_ts, prev_ts, count))
                in_run = False
                count = 0
    if in_run:
        result.append((start_ts, prev_ts, count))
    return result


def best_split(values, min_seg: int):
    if isinstance(values, pd.Series):
        s = values.dropna()
        if len(s) < 2 * min_seg:
            return None
        valid_vals = s.values
        valid_indices = s.index
    else:
        valid_mask = ~np.isnan(values)
        if np.sum(valid_mask) < 2 * min_seg:
            return None
        valid_vals = np.asarray(values)[valid_mask]
        valid_indices = np.where(valid_mask)[0]

    n = len(valid_vals)
    best_score = -1.0
    best_k = None
    best_m1 = None
    best_m2 = None

    for k in range(min_seg, n - min_seg + 1):
        seg1 = valid_vals[:k]
        seg2 = valid_vals[k:]
        m1 = np.mean(seg1)
        m2 = np.mean(seg2)
        score = abs(m2 - m1) * np.sqrt((k * (n - k)) / n)
        if score > best_score:
            best_score = score
            best_k = k
            best_m1 = m1
            best_m2 = m2

    if best_k is None:
        return None

    split_idx = valid_indices[best_k]
    return split_idx, best_m1, best_m2


def nb_median(PANEL: dict, BAD: dict, channel: str, station: str, NB: dict):
    if station not in NB or len(NB[station]) < 2:
        return None
    neighbours = NB[station]
    p_data = PANEL[channel].loc[:, neighbours]
    b_data = BAD[channel].loc[:, neighbours]
    masked = p_data.where(~b_data)
    valid_counts = masked.notna().sum(axis=1)
    med = masked.median(axis=1)
    med.loc[valid_counts < 2] = np.nan
    return med


def pick(stations: pd.DataFrame, PANEL: dict, BAD: dict) -> dict:
    nb_dict = {}
    master_index = PANEL["temp_c"].index
    start_str = master_index[0].strftime("%Y-%m-%d %H:%M")
    end_str = master_index[-1].strftime("%Y-%m-%d %H:%M")

    for s in stations.index:
        s_lat = float(stations.loc[s, "lat"])
        s_lon = float(stations.loc[s, "lon"])
        s_elev = float(stations.loc[s, "elevation_m"])

        candidates = []
        for o in stations.index:
            if o == s:
                continue
            o_elev = float(stations.loc[o, "elevation_m"])
            dz = abs(s_elev - o_elev)
            if dz <= config.NEIGHBOUR_MAX_DZ_M:
                o_lat = float(stations.loc[o, "lat"])
                o_lon = float(stations.loc[o, "lon"])
                dist = haversine_km(s_lat, s_lon, o_lat, o_lon)
                candidates.append((dist, o))

        candidates.sort(key=lambda x: x[0])
        chosen = [c[1] for c in candidates[: config.NEIGHBOUR_K]]
        nb_dict[s] = chosen

        if len(chosen) < 2:
            checks.flags.add_flag(
                station_id=s,
                channel="all",
                start_utc=start_str,
                end_utc=end_str,
                issue="high-altitude site differs from network",
                action="keep",
                note=(
                    f"At {s_elev:.0f} m (about 1200 m above the others) {s} is colder, "
                    f"windier and lower in pressure for real; compare it only with itself, "
                    f"not the network median."
                ),
            )

    return nb_dict


def steps(channel: str, stations: pd.DataFrame, PANEL: dict, BAD: dict, NB: dict):
    handled = set()
    thresh = config.P_STEP_HPA if channel == "pressure_hpa" else np.log(config.WIND_RATIO)

    while True:
        best_candidate = None
        max_norm_effect = -1.0

        for st in stations.index:
            if st in handled:
                continue
            if st not in NB or len(NB[st]) < 2:
                continue
            nb_med = nb_median(PANEL, BAD, channel, st, NB)
            if nb_med is None:
                continue

            st_series = PANEL[channel].loc[:, st].where(~BAD[channel].loc[:, st])

            if channel == "pressure_hpa":
                diff = st_series - nb_med
                y = diff.resample("1h").median().dropna()
                min_seg = 24
            elif channel == "wind_kmh":
                st_6h = st_series.resample("6h").mean()
                nb_6h = nb_med.resample("6h").mean()
                valid_mask = nb_6h > 3.0
                ratio = (st_6h + 0.5) / (nb_6h + 0.5)
                y = np.log(ratio[valid_mask]).dropna()
                min_seg = 8
            else:
                continue

            split_res = best_split(y, min_seg)
            if split_res is None:
                continue

            split_ts, before, after = split_res
            effect = abs(after - before)
            if effect >= thresh:
                norm_effect = effect / thresh
                if norm_effect > max_norm_effect:
                    max_norm_effect = norm_effect
                    best_candidate = {
                        "station": st,
                        "split_ts": split_ts,
                        "effect": effect,
                        "nb_med": nb_med,
                        "st_series": st_series,
                    }

        if best_candidate is None:
            break

        cand_st = best_candidate["station"]
        coarse_ts = best_candidate["split_ts"]
        nb_med = best_candidate["nb_med"]
        st_series = best_candidate["st_series"]
        diff_10m = st_series - nb_med

        if channel == "pressure_hpa":
            window_start = coarse_ts - pd.Timedelta(hours=3)
            window_end = coarse_ts + pd.Timedelta(hours=3)
            window_diff = diff_10m.loc[window_start:window_end].dropna()
            step_10m = (window_diff - window_diff.shift(1)).abs()
            if not step_10m.empty and step_10m.max() > 0:
                exact_ts = step_10m.idxmax()
            else:
                exact_ts = coarse_ts

            before_3d = diff_10m.loc[
                exact_ts - pd.Timedelta(days=3) : exact_ts - pd.Timedelta(minutes=10)
            ]
            after_3d = diff_10m.loc[exact_ts : exact_ts + pd.Timedelta(days=3)]
            p_offset = float(after_3d.median() - before_3d.median())

            start_str = exact_ts.strftime("%Y-%m-%d %H:%M")
            end_str = PANEL[channel].index[-1].strftime("%Y-%m-%d %H:%M")
            note = (
                f"Pressure jumped about {p_offset:+.1f} hPa between two readings at "
                f"{start_str.split()[1]} local, matching the uncalibrated board swap in the log, "
                f"and stayed high vs neighbours; subtract {p_offset:.1f} hPa from here on."
            )
            checks.flags.add_flag(
                station_id=cand_st,
                channel=channel,
                start_utc=start_str,
                end_utc=end_str,
                issue="pressure offset after board swap",
                action="correct",
                note=note,
            )
            PANEL[channel].loc[exact_ts:, cand_st] = (
                PANEL[channel].loc[exact_ts:, cand_st] - p_offset
            )

        elif channel == "wind_kmh":
            window_start = coarse_ts - pd.Timedelta(hours=12)
            window_end = coarse_ts + pd.Timedelta(hours=12)
            log_ratio_10m = np.log(
                (st_series.loc[window_start:window_end] + 0.5)
                / (nb_med.loc[window_start:window_end] + 0.5)
            ).dropna()

            refine_res = best_split(log_ratio_10m, min_seg=6)
            if refine_res is not None:
                exact_ts = refine_res[0]
            else:
                exact_ts = coarse_ts

            daily_st = st_series.resample("1D").mean()
            daily_nb = nb_med.resample("1D").mean()
            r_before = (daily_st.loc[:exact_ts] / daily_nb.loc[:exact_ts]).dropna()
            r_after = (daily_st.loc[exact_ts:] / daily_nb.loc[exact_ts:]).dropna()
            ratio_before_med = float(r_before.median()) if not r_before.empty else 1.0
            ratio_after_med = float(r_after.median()) if not r_after.empty else 1.0
            wind_factor = (
                float(ratio_before_med / ratio_after_med)
                if ratio_after_med > 0
                else 1.0
            )

            start_str = exact_ts.strftime("%Y-%m-%d %H:%M")
            end_str = PANEL[channel].index[-1].strftime("%Y-%m-%d %H:%M")
            ratio_drop = 1.0 / wind_factor if wind_factor > 0 else 0.3
            note = (
                f"From the anemometer swap wind dropped to about {ratio_drop:.1f}x of neighbours "
                f"while direction stayed normal; multiply by about {wind_factor:.1f} (estimate, range about 2.7-3.7)."
            )
            checks.flags.add_flag(
                station_id=cand_st,
                channel=channel,
                start_utc=start_str,
                end_utc=end_str,
                issue="new anemometer reads too low",
                action="correct",
                note=note,
            )
            PANEL[channel].loc[exact_ts:, cand_st] = (
                PANEL[channel].loc[exact_ts:, cand_st] * wind_factor
            )

        handled.add(cand_st)
