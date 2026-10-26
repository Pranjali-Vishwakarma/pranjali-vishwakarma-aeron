"""All thresholds live here, each with a comment explaining why."""

DATA_INTERVAL_MIN = 10       # logger interval stated in stations.csv / README
CLOCK_TOL_MIN = 2            # GPS lines arrive 0-2 s late; >=2 min means a real clock error
CLOCK_MIN_LINES = 3          # an offset must persist for 3 hourly lines to count
POS_TOL_KM = 0.5             # GPS scatter is ~10 m; 0.5 km means the sheet is wrong
ELEV_TOL_M = 50              # GPS altitude scatter is a few metres
BAD_CHECKSUM_FACTOR = 3      # a station with >3x the network's bad-checksum rate...
BAD_CHECKSUM_MIN_RATE = 0.01 # ...and above 1% has a noisy GPS link
