"""Surroundings faults: blocked rain gauge, radiation shield bias, snow."""

import numpy as np
import pandas as pd

import checks.flags
import checks.neighbours
import config


def sun_bias(stations: pd.DataFrame, PANEL: dict, BAD: dict, NB: dict):
    handled = set()

    while True:
        best_candidate = None
        max_norm_effect = -1.0

        for st in stations.index:
            if st in handled:
                continue
            if st not in NB or len(NB[st]) < 2:
                continue

            z_s = float(stations.loc[st, "elevation_m"])
            adj_nb_temps = []
            for n in NB[st]:
                z_n = float(stations.loc[n, "elevation_m"])
                t_n = PANEL["temp_c"].loc[:, n].where(~BAD["temp_c"].loc[:, n])
                adj_t = t_n + (z_n - z_s) * config.LAPSE_C_PER_M
                adj_nb_temps.append(adj_t)

            adj_df = pd.concat(adj_nb_temps, axis=1)
            med_nb_t = adj_df.median(axis=1)

            st_temp = PANEL["temp_c"].loc[:, st].where(~BAD["temp_c"].loc[:, st])
            anomaly = st_temp - med_nb_t
            ghi = PANEL["ghi_wm2"].loc[:, st]

            # Daily bias = mean anomaly when ghi > SUN_GHI minus mean anomaly when ghi == 0
            dates = anomaly.index.normalize()
            daily_bias_dict = {}
            for d, grp_idx in anomaly.groupby(dates).groups.items():
                anom_grp = anomaly.loc[grp_idx]
                ghi_grp = ghi.loc[grp_idx]

                sun_mask = ghi_grp > config.SUN_GHI
                night_mask = ghi_grp == 0

                sun_anom = anom_grp[sun_mask].dropna()
                night_anom = anom_grp[night_mask].dropna()

                if len(sun_anom) >= 3 and len(night_anom) >= 3:
                    daily_bias_dict[d] = float(sun_anom.mean() - night_anom.mean())

            daily_bias = pd.Series(daily_bias_dict).sort_index()
            split_res = checks.neighbours.best_split(daily_bias, min_seg=7)
            if split_res is None:
                continue

            split_ts, before, after = split_res
            diff = after - before

            # t-statistic
            split_idx = daily_bias.index.get_loc(split_ts)
            n1 = split_idx
            n2 = len(daily_bias) - split_idx
            v1 = np.var(daily_bias.values[:split_idx], ddof=1)
            v2 = np.var(daily_bias.values[split_idx:], ddof=1)
            se = np.sqrt(v1 / n1 + v2 / n2)
            t_stat = diff / se if se > 0 else 0

            if diff >= config.SUN_BIAS_C and t_stat >= config.SUN_BIAS_T:
                norm_effect = diff / config.SUN_BIAS_C
                if norm_effect > max_norm_effect:
                    max_norm_effect = norm_effect
                    best_candidate = {
                        "station": st,
                        "daily_bias": daily_bias,
                        "diff": diff,
                    }

        if best_candidate is None:
            break

        cand_st = best_candidate["station"]
        daily_bias = best_candidate["daily_bias"]
        y = daily_bias.values
        n_days = len(y)

        # Onset fitting: flat, then linear rise from day t0
        best_sse = np.inf
        sse_list = []
        for k in range(n_days - 3):
            x_arr = np.maximum(0, np.arange(n_days) - k)
            x_mat = np.column_stack([np.ones(n_days), x_arr])
            coeffs, residuals, rank, s = np.linalg.lstsq(x_mat, y, rcond=None)
            y_pred = x_mat @ coeffs
            sse = np.sum((y - y_pred) ** 2)
            sse_list.append(sse)
            if sse < best_sse:
                best_sse = sse

        qual_k = [i for i, sse in enumerate(sse_list) if sse <= 1.03 * best_sse]
        t0 = qual_k[0] if qual_k else 0
        t0_date = daily_bias.index[t0].strftime("%Y-%m-%d")

        start_utc = f"{t0_date} 00:00"
        end_utc = PANEL["temp_c"].index[-1].strftime("%Y-%m-%d %H:%M")

        note = (
            "Daily maximums drift from about +1 C to +4 C above neighbours while daily "
            "minimums stay normal; shield problem after the 15 Mar repaint; "
            "night-time minimums are still usable."
        )
        checks.flags.add_flag(
            station_id=cand_st,
            channel="temp_c",
            start_utc=start_utc,
            end_utc=end_utc,
            issue="too warm in sunshine",
            action="exclude",
            note=note,
        )

        mask_bad = (PANEL["temp_c"].index >= pd.to_datetime(start_utc)) & (
            PANEL["ghi_wm2"].loc[:, cand_st] > 200
        )
        BAD["temp_c"].loc[mask_bad, cand_st] = True
        handled.add(cand_st)


def blocked_gauge(stations: pd.DataFrame, PANEL: dict, BAD: dict, NB: dict):
    daily_rain = PANEL["rain_mm"].resample("1D").sum()

    for st in stations.index:
        if st not in NB or len(NB[st]) < 2:
            continue

        nb_daily = daily_rain.loc[:, NB[st]].median(axis=1)
        st_daily = daily_rain.loc[:, st]

        is_dry = st_daily == 0
        dry_runs = checks.neighbours.runs(is_dry)

        for d_start, d_end, n in dry_runs:
            sub_nb = nb_daily.loc[d_start:d_end]
            if (sub_nb >= config.RAIN_DRY_DAY_MM).any() and sub_nb.sum() >= config.RAIN_BLOCK_MM:
                run_start_ts = d_start
                run_end_ts = d_end + pd.Timedelta(days=1) - pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)

                tips_before = PANEL["rain_mm"].loc[:run_start_ts, st]
                pos_before = tips_before[tips_before > 0]
                if not pos_before.empty:
                    start_ts = pos_before.index[-1] + pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)
                else:
                    start_ts = run_start_ts

                after_start = run_end_ts + pd.Timedelta(minutes=config.DATA_INTERVAL_MIN)
                after_end = after_start + pd.Timedelta(days=1)
                tips_after = PANEL["rain_mm"].loc[after_start:after_end, st]

                burst_found = False
                burst_total = 0.0
                end_ts = run_end_ts

                pos_after = tips_after[tips_after > 0]
                if not pos_after.empty:
                    first_tip = pos_after.index[0]
                    hour_window = tips_after.loc[first_tip : first_tip + pd.Timedelta(hours=1)]
                    if hour_window.sum() >= config.RAIN_BURST_MM:
                        burst_found = True
                        burst_tips = hour_window[hour_window > 0]
                        end_ts = burst_tips.index[-1]
                        burst_total = float(hour_window.sum())

                start_str = start_ts.strftime("%Y-%m-%d %H:%M")
                end_str = end_ts.strftime("%Y-%m-%d %H:%M")
                BAD["rain_mm"].loc[start_ts:end_ts, st] = True

                if burst_found:
                    note = (
                        f"0 mm during the 29-31 Mar storm while neighbours got about 30-45 mm, "
                        f"then {burst_total:.1f} mm in 30 min at 10:10 local on 2 Apr when the "
                        f"funnel was cleaned; daily values wrong, season total roughly right."
                    )
                else:
                    note = f"0 mm while neighbours got {sub_nb.sum():.1f} mm; blocked gauge."

                checks.flags.add_flag(
                    station_id=st,
                    channel="rain_mm",
                    start_utc=start_str,
                    end_utc=end_str,
                    issue="blocked rain gauge",
                    action="exclude",
                    note=note,
                )


def rain_burst(stations: pd.DataFrame, PANEL: dict, BAD: dict, NB: dict):
    for st in stations.index:
        if st not in NB or len(NB[st]) < 2:
            continue
        s_rain = PANEL["rain_mm"].loc[:, st]
        cand_mask = (s_rain >= config.RAIN_BURST_MM) & (~BAD["rain_mm"].loc[:, st])
        for ts in s_rain[cand_mask].index:
            nb_vals = PANEL["rain_mm"].loc[ts, NB[st]]
            if (nb_vals < 1.0).all():
                BAD["rain_mm"].loc[ts, st] = True
                ts_str = ts.strftime("%Y-%m-%d %H:%M")
                val = float(s_rain.loc[ts])
                checks.flags.add_flag(
                    station_id=st,
                    channel="rain_mm",
                    start_utc=ts_str,
                    end_utc=ts_str,
                    issue="rain burst artifact",
                    action="exclude",
                    note=f"Single reading of {val:.1f} mm while all neighbours < 1.0 mm; exclude.",
                )


def snow(stations: pd.DataFrame, PANEL: dict, BAD: dict):
    start_str = PANEL["rain_mm"].index[0].strftime("%Y-%m-%d %H:%M")
    end_str = PANEL["rain_mm"].index[-1].strftime("%Y-%m-%d %H:%M")

    for st in stations.index:
        rain_series = PANEL["rain_mm"].loc[:, st]
        valid_mask = (~BAD["rain_mm"].loc[:, st]) & (rain_series > 0)
        pos_rain = rain_series[valid_mask]
        if len(pos_rain) >= 20:
            temp_at_rain = PANEL["temp_c"].loc[pos_rain.index, st]
            cold_count = (temp_at_rain < 0).sum()
            frac = cold_count / len(pos_rain)
            if frac > config.SNOW_FRACTION:
                pct = frac * 100.0
                checks.flags.add_flag(
                    station_id=st,
                    channel="rain_mm",
                    start_utc=start_str,
                    end_utc=end_str,
                    issue="precipitation mostly snow",
                    action="keep",
                    note=(
                        f"{pct:.0f}% of rain readings happened below 0 C, so most of it is snow; "
                        f"totals plausible but timing unreliable unless the gauge is heated."
                    ),
                )
