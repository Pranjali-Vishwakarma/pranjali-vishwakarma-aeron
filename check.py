import os
import sys

import checks.flags

if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
    print("usage: python check.py <data_pack_folder>")
    sys.exit(1)

checks.flags.write_flags("flags.csv")
print(f"wrote flags.csv: {len(checks.flags.FLAGS)} flags")
