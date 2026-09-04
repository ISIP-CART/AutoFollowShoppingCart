"""Recompute archived bench-log statistics using the Python 3 standard library."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean, median

DATA = Path(__file__).resolve().parent / "data"
TOF = re.compile(r"(\d+),(LEFT|RIGHT),(0x[0-9A-Fa-f]+),(-?\d+),(-?\d+),(NEAR|VALID|INVALID_RANGE|TIMEOUT|I2C_ERROR)")
SONAR = re.compile(r"(\d+),(VALID|INVALID),(?:(\d+) cm|raw=(\d+)|(I2C_WRITE_ERROR|I2C_READ_ERROR))")


def read_log(name, pattern, allow_first_prefix=False):
    raw = (DATA / name).read_bytes()
    rows, prefix = [], ""
    for line_no, line in enumerate(raw.decode("utf-8-sig", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        match = pattern.fullmatch(line.strip())
        if not match and allow_first_prefix and line_no == 1:
            match = pattern.search(line)
            if match and match.end() == len(line):
                prefix = line[:match.start()]
            else:
                match = None
        if not match:
            raise ValueError(f"Unrecognized record in {name}:{line_no}")
        rows.append(match.groups())
    return rows, {"file": name, "sha256": hashlib.sha256(raw).hexdigest(),
                  "records": len(rows), "ignored_first_line_prefix": prefix}


def summarize(rows):
    intervals = [b["t"] - a["t"] for a, b in zip(rows, rows[1:])]
    if not intervals or min(intervals) <= 0:
        raise ValueError("Sensor timestamps must be strictly increasing")
    valid = [r for r in rows if r["valid"]]
    runs, start = [], None
    for i in range(len(rows) + 1):
        invalid = i < len(rows) and not rows[i]["valid"]
        if invalid and start is None:
            start = i
        elif not invalid and start is not None:
            runs.append({"count": i - start, "start_ms": rows[start]["t"],
                         "end_ms": rows[i - 1]["t"],
                         "span_ms": rows[i - 1]["t"] - rows[start]["t"],
                         "previous_valid_ms": rows[start - 1]["t"] if start else None,
                         "next_valid_ms": rows[i]["t"] if i < len(rows) else None})
            start = None
    return {"records": len(rows), "start_ms": rows[0]["t"], "end_ms": rows[-1]["t"],
            "span_ms": rows[-1]["t"] - rows[0]["t"],
            "valid": len(valid), "invalid": len(rows) - len(valid),
            "valid_percent": round(100 * len(valid) / len(rows), 4),
            "valid_min": min(r["distance"] for r in valid),
            "valid_max": max(r["distance"] for r in valid),
            "interval_ms": {"min": min(intervals), "median": median(intervals),
                            "mean": mean(intervals), "max": max(intervals)},
            "rate_hz": 1000 / mean(intervals),
            "states": dict(Counter(r["state"] for r in rows)),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "invalid_runs": sorted(runs, key=lambda r: r["count"], reverse=True)}


def main():
    tof, tof_source = read_log("vl53l1x-dual-serial.txt", TOF)
    sonar, sonar_source = read_log("urm09-serial.txt", SONAR, allow_first_prefix=True)
    result = {"sources": [tof_source, sonar_source], "sensors": {}}
    for side, address in (("LEFT", "0x2A"), ("RIGHT", "0x2B")):
        rows = []
        for t, s, addr, distance, status, state in tof:
            if s != side:
                continue
            if addr.upper() != address.upper():
                raise ValueError(f"Unexpected address for {side}: {addr}")
            d, st = int(distance), int(status)
            valid = st == 0 and 40 <= d <= 1300
            if state in ("NEAR", "VALID", "INVALID_RANGE"):
                expected = "INVALID_RANGE" if not valid else ("NEAR" if d <= 300 else "VALID")
                if state != expected:
                    raise ValueError(f"ToF state disagrees with quality/range gate at {t}")
            rows.append(dict(t=int(t), distance=d, status=st, state=state,
                             valid=valid and state in ("NEAR", "VALID")))
        result["sensors"][side] = {"unit": "mm", "address": address, **summarize(rows)}
    rows = []
    for t, state, distance, raw, error in sonar:
        value = int(distance or raw) if distance or raw else None
        if (state == "VALID") != (error is None and value is not None and 2 <= value <= 500):
            raise ValueError(f"Sonar state disagrees with range gate at {t}")
        rows.append(dict(t=int(t), distance=value,
                         status=error or ("in_range" if state == "VALID" else f"raw={raw}"),
                         state=state, valid=state == "VALID"))
    stats = summarize(rows)
    stats["local_far_jumps"] = [
        {"time_ms": b["t"], "sequence_cm": [a["distance"], b["distance"], c["distance"]]}
        for a, b, c in zip(rows, rows[1:], rows[2:])
        if all(r["valid"] for r in (a, b, c))
        and b["distance"] > max(100, 2.5 * (a["distance"] + c["distance"]) / 2)
    ]
    result["sensors"]["URM09"] = {"unit": "cm", **stats}
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
