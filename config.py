"""All thresholds live here, each with a comment explaining why."""

DATA_INTERVAL_MIN = 10       # logger interval stated in stations.csv / README
CLOCK_TOL_MIN = 2            # GPS lines arrive 0-2 s late; >=2 min means a real clock error
CLOCK_MIN_LINES = 3          # an offset must persist for 3 hourly lines to count
POS_TOL_KM = 0.5             # GPS scatter is ~10 m; 0.5 km means the sheet is wrong
ELEV_TOL_M = 50              # GPS altitude scatter is a few metres
BAD_CHECKSUM_FACTOR = 3      # a station with >3x the network's bad-checksum rate...
BAD_CHECKSUM_MIN_RATE = 0.01 # ...and above 1% has a noisy GPS link

LIMITS = {
    "temp_c": (-35, 45),
    "rh_pct": (0, 100),
    "pressure_hpa": (500, 1080),
    "wind_kmh": (0, 150),
    "wind_dir_deg": (0, 360),
    "rain_mm": (0, 10),
    "ghi_wm2": (0, 1400),
}                            # physically possible here
RH_TOL = 2                   # RH sensors read up to ~102% normally
FLATLINE_HOURS = {"temp_c": 3, "rh_pct": 6, "pressure_hpa": 6}  # real air never holds one value this long
SPIKE_C = 6                  # a 10-min temp jump > 6 C away from both sides is not weather
NEIGHBOUR_K = 4              # compare with the 4 nearest stations...
NEIGHBOUR_MAX_DZ_M = 500     # ...that are within 500 m of height
LAPSE_C_PER_M = 0.0065       # standard drop of temperature with height
P_STEP_HPA = 1.5             # pressure offset vs neighbours that counts as a step
WIND_RATIO = 1.6             # wind scale change vs neighbours that counts as a step
SUN_GHI = 500                # "strong sun" for the shield-bias check
SUN_BIAS_C = 1.5             # extra daytime warming vs neighbours that counts as a fault
SUN_BIAS_T = 5               # t-statistic needed; daily scatter is large, so be strict
RAIN_DRY_DAY_MM = 2          # a neighbour-median day this wet should give the station some rain
RAIN_BLOCK_MM = 10           # station got 0 while neighbours got this much in total
RAIN_BURST_MM = 4            # in 10 min while all neighbours got < 1 mm
SNOW_FRACTION = 0.5          # more than half of tips below 0 C means mostly snow
