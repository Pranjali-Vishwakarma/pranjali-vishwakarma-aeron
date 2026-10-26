"""Compare checker flags against manual reference flags."""

import sys
import pandas as pd


def main():
    if len(sys.argv) != 3:
        print("Usage: python tests/compare_manual.py <flags.csv> <flags_manual.csv>")
        sys.exit(1)

    checker_df = pd.read_csv(sys.argv[1])
    manual_df = pd.read_csv(sys.argv[2])

    checker_df["_dt_start"] = pd.to_datetime(checker_df["start_utc"])
    manual_df["_dt_start"] = pd.to_datetime(manual_df["start_utc"])

    checker_matched = set()
    manual_matched = set()
    matched_pairs = []

    keys = (
        set(zip(checker_df["station_id"], checker_df["channel"], checker_df["action"]))
        | set(zip(manual_df["station_id"], manual_df["channel"], manual_df["action"]))
    )

    for key in sorted(keys):
        c_idxs = [
            i
            for i, row in checker_df.iterrows()
            if (row["station_id"], row["channel"], row["action"]) == key
        ]
        m_idxs = [
            j
            for j, row in manual_df.iterrows()
            if (row["station_id"], row["channel"], row["action"]) == key
        ]

        while c_idxs and m_idxs:
            best_pair = None
            best_diff = None
            for ci in c_idxs:
                for mj in m_idxs:
                    diff = abs(checker_df.loc[ci, "_dt_start"] - manual_df.loc[mj, "_dt_start"])
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        best_pair = (ci, mj)
            ci, mj = best_pair
            c_idxs.remove(ci)
            m_idxs.remove(mj)
            checker_matched.add(ci)
            manual_matched.add(mj)
            matched_pairs.append((ci, mj))

    matched_pairs.sort(
        key=lambda pair: (
            checker_df.loc[pair[0], "station_id"],
            checker_df.loc[pair[0], "start_utc"],
            checker_df.loc[pair[0], "channel"],
        )
    )

    # Section 1: MATCHED
    print("MATCHED:")
    print(
        f"{'station':<8} {'channel':<13} {'action':<8} "
        f"{'checker start .. end':<37} {'manual start .. end':<37} {'difference'}"
    )
    print("-" * 115)
    for ci, mj in matched_pairs:
        crow = checker_df.loc[ci]
        mrow = manual_df.loc[mj]

        c_span = f"{crow['start_utc']} .. {crow['end_utc']}"
        m_span = f"{mrow['start_utc']} .. {mrow['end_utc']}"

        diffs = []
        if crow["start_utc"] != mrow["start_utc"]:
            diffs.append("start")
        if crow["end_utc"] != mrow["end_utc"]:
            diffs.append("end")

        diff_str = "OK" if not diffs else f"DIFF ({', '.join(diffs)})"

        print(
            f"{crow['station_id']:<8} {crow['channel']:<13} {crow['action']:<8} "
            f"{c_span:<37} {m_span:<37} {diff_str}"
        )
    print()

    # Section 2: ONLY IN CHECKER
    print("ONLY IN CHECKER:")
    only_checker = [i for i in checker_df.index if i not in checker_matched]
    if not only_checker:
        print("(none)")
    else:
        for ci in only_checker:
            row = checker_df.loc[ci]
            print(
                f"{row['station_id']:<8} {row['channel']:<13} {row['action']:<8} "
                f"{row['start_utc']} .. {row['end_utc']}  {row['issue']}"
            )
    print()

    # Section 3: ONLY IN MANUAL
    print("ONLY IN MANUAL:")
    only_manual = [j for j in manual_df.index if j not in manual_matched]
    if not only_manual:
        print("(none)")
    else:
        for mj in only_manual:
            row = manual_df.loc[mj]
            print(
                f"{row['station_id']:<8} {row['channel']:<13} {row['action']:<8} "
                f"{row['start_utc']} .. {row['end_utc']}  {row['issue']}"
            )


if __name__ == "__main__":
    main()
