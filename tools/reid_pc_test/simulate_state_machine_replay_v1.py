from pathlib import Path
import argparse
import csv
from collections import Counter, defaultdict

REID_PROFILES = {
    "weak": {"best": 0.75, "margin": 0.03},
    "mid": {"best": 0.80, "margin": 0.05},
    "strong": {"best": 0.85, "margin": 0.05},
}

BBOX_PROFILES = {
    "loose": {"center": 0.30, "x": 0.30, "area_min": 0.45, "area_max": 2.20},
    "default": {"center": 0.25, "x": 0.25, "area_min": 0.50, "area_max": 2.00},
    "strict": {"center": 0.18, "x": 0.18, "area_min": 0.60, "area_max": 1.67},
}

FOLLOW_CONFIDENT = "FOLLOW_CONFIDENT"
FOLLOW_CAUTION = "FOLLOW_CAUTION"
REACQUIRE_TARGET = "REACQUIRE_TARGET"
LOST_SEARCH = "LOST_SEARCH"
IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"
STOP = "STOP"


def resolve(root: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def truthy(value):
    return str(value).strip().lower() == "true"


def to_float(row, key, default=0.0):
    value = row.get(key, "")
    if value == "":
        return default
    return float(value)


def reid_ok(obs, profile):
    rule = REID_PROFILES[profile]
    return obs["best_score"] >= rule["best"] and obs["margin"] >= rule["margin"]


def bbox_ok(obs, profile):
    rule = BBOX_PROFILES[profile]
    return (
        obs["center_jump_ratio"] <= rule["center"]
        and obs["x_jump_ratio"] <= rule["x"]
        and rule["area_min"] <= obs["area_ratio"] <= rule["area_max"]
    )


def prediction_ok(obs, profile):
    value = obs.get("prediction_error", "")
    if value == "":
        return False
    return float(value) <= BBOX_PROFILES[profile]["center"]


def load_observations(rows_path: Path):
    observations = {}
    with rows_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            # One representative row per simulated frame is enough because
            # bbox metrics and ReID scores are duplicated across profiles.
            if not (
                row["strategy"] == "reid_only"
                and row["reid_profile"] == "weak"
                and row["bbox_profile"] == "loose"
            ):
                continue
            key = (
                int(row["trial"]),
                int(row["gap"]),
                row["scenario"],
                row["target_identity"],
                int(row["frame_no"]),
            )
            observations[key] = {
                "trial": int(row["trial"]),
                "gap": int(row["gap"]),
                "scenario": row["scenario"],
                "target_identity": row["target_identity"],
                "frame_no": int(row["frame_no"]),
                "best_label": row["best_label"],
                "best_path": row["best_path"],
                "last_target_path": row["last_target_path"],
                "best_score": to_float(row, "best_score"),
                "second_score": to_float(row, "second_score"),
                "margin": to_float(row, "margin"),
                "center_jump_ratio": to_float(row, "center_jump_ratio"),
                "x_jump_ratio": to_float(row, "x_jump_ratio"),
                "area_ratio": to_float(row, "area_ratio"),
                "prediction_error": row.get("prediction_error", ""),
                "correct": truthy(row.get("correct", "")),
            }

    grouped = defaultdict(list)
    for obs in observations.values():
        group_key = (obs["trial"], obs["gap"], obs["scenario"], obs["target_identity"])
        grouped[group_key].append(obs)
    for key in grouped:
        grouped[key].sort(key=lambda x: x["frame_no"])
    return grouped


def enter_state(state, next_state, counters, durations):
    if state == IDENTITY_UNCERTAIN and next_state != IDENTITY_UNCERTAIN:
        durations.append(counters["identity_uncertain_duration"])
        counters["identity_uncertain_duration"] = 0
    if next_state == IDENTITY_UNCERTAIN and state != IDENTITY_UNCERTAIN:
        counters["identity_uncertain_entries"] += 1
    if next_state != state:
        counters["state_stable_count"] = 0
    return next_state


def replay_sequence(seq, args):
    scenario = seq[0]["scenario"]
    state = FOLLOW_CONFIDENT if scenario == "target_present" else LOST_SEARCH
    transitions = Counter()
    frame_rows = []
    counters = {
        "mid_default_streak": 0,
        "strong_default_streak": 0,
        "strong_strict_streak": 0,
        "strong_strict_prediction_streak": 0,
        "unstable_streak": 0,
        "identity_uncertain_duration": 0,
        "identity_uncertain_entries": 0,
        "state_stable_count": 0,
        "search_duration": 0,
    }
    uncertain_durations = []
    wrong_follow_recovery_count = 0
    wrong_follow_frame_count = 0
    target_present_over_stop_count = 0
    target_present_uncertain_count = 0
    reacquire_entries = 0

    for obs in seq:
        prev_state = state
        weak_ok = reid_ok(obs, "weak")
        mid_ok = reid_ok(obs, "mid")
        strong_ok = reid_ok(obs, "strong")
        bbox_default = bbox_ok(obs, "default")
        bbox_strict = bbox_ok(obs, "strict")
        pred_strict = prediction_ok(obs, "strict")

        if mid_ok and bbox_default:
            counters["mid_default_streak"] += 1
        else:
            counters["mid_default_streak"] = 0

        if strong_ok and bbox_default:
            counters["strong_default_streak"] += 1
        else:
            counters["strong_default_streak"] = 0

        if strong_ok and bbox_strict:
            counters["strong_strict_streak"] += 1
        else:
            counters["strong_strict_streak"] = 0

        if strong_ok and bbox_strict and pred_strict:
            counters["strong_strict_prediction_streak"] += 1
        else:
            counters["strong_strict_prediction_streak"] = 0

        if state == FOLLOW_CONFIDENT:
            if bbox_default and weak_ok:
                next_state = FOLLOW_CONFIDENT
                counters["unstable_streak"] = 0
            elif bbox_default:
                next_state = FOLLOW_CAUTION
                counters["unstable_streak"] = 0
            else:
                next_state = IDENTITY_UNCERTAIN
                counters["unstable_streak"] += 1

        elif state == FOLLOW_CAUTION:
            if counters["mid_default_streak"] >= args.caution_stable_frames:
                next_state = FOLLOW_CONFIDENT
                counters["unstable_streak"] = 0
            elif not bbox_default:
                counters["unstable_streak"] += 1
                next_state = IDENTITY_UNCERTAIN if counters["unstable_streak"] >= args.uncertain_frames else FOLLOW_CAUTION
            else:
                next_state = FOLLOW_CAUTION

        elif state == REACQUIRE_TARGET:
            if counters["strong_strict_streak"] >= args.reacquire_strict_frames:
                next_state = FOLLOW_CONFIDENT
            elif counters["strong_default_streak"] >= args.reacquire_default_frames:
                next_state = FOLLOW_CONFIDENT
            elif strong_ok and not bbox_default:
                next_state = IDENTITY_UNCERTAIN
            else:
                next_state = REACQUIRE_TARGET

        elif state == IDENTITY_UNCERTAIN:
            counters["identity_uncertain_duration"] += 1
            if counters["strong_strict_streak"] >= args.uncertain_recover_frames:
                next_state = REACQUIRE_TARGET
            elif counters["identity_uncertain_duration"] >= args.identity_timeout:
                next_state = STOP
            else:
                next_state = IDENTITY_UNCERTAIN

        elif state == LOST_SEARCH:
            counters["search_duration"] += 1
            if counters["strong_strict_prediction_streak"] >= args.lost_recover_frames:
                next_state = REACQUIRE_TARGET
            elif counters["search_duration"] >= args.search_timeout:
                next_state = STOP
            else:
                next_state = LOST_SEARCH

        else:
            next_state = STOP

        state = enter_state(state, next_state, counters, uncertain_durations)
        counters["state_stable_count"] += 1
        if prev_state != state:
            transitions[(prev_state, state)] += 1
            if state == REACQUIRE_TARGET:
                reacquire_entries += 1
            if scenario == "target_absent" and state == FOLLOW_CONFIDENT:
                wrong_follow_recovery_count += 1

        if scenario == "target_absent" and state == FOLLOW_CONFIDENT:
            wrong_follow_frame_count += 1
        if scenario == "target_present" and state == STOP:
            target_present_over_stop_count += 1
        if scenario == "target_present" and state == IDENTITY_UNCERTAIN:
            target_present_uncertain_count += 1

        frame_rows.append({
            "trial": obs["trial"],
            "gap": obs["gap"],
            "scenario": scenario,
            "target_identity": obs["target_identity"],
            "frame_no": obs["frame_no"],
            "prev_state": prev_state,
            "state": state,
            "best_label": obs["best_label"],
            "best_score": obs["best_score"],
            "margin": obs["margin"],
            "weak_ok": weak_ok,
            "mid_ok": mid_ok,
            "strong_ok": strong_ok,
            "bbox_default_ok": bbox_default,
            "bbox_strict_ok": bbox_strict,
            "prediction_strict_ok": pred_strict,
            "mid_default_streak": counters["mid_default_streak"],
            "strong_default_streak": counters["strong_default_streak"],
            "strong_strict_streak": counters["strong_strict_streak"],
            "strong_strict_prediction_streak": counters["strong_strict_prediction_streak"],
            "correct": obs["correct"],
        })

    if state == IDENTITY_UNCERTAIN:
        uncertain_durations.append(counters["identity_uncertain_duration"])

    return {
        "final_state": state,
        "transitions": transitions,
        "frame_rows": frame_rows,
        "wrong_follow_recovery_count": wrong_follow_recovery_count,
        "wrong_follow_frame_count": wrong_follow_frame_count,
        "target_present_over_stop_count": target_present_over_stop_count,
        "target_present_uncertain_count": target_present_uncertain_count,
        "identity_uncertain_entries": counters["identity_uncertain_entries"],
        "uncertain_durations": uncertain_durations,
        "reacquire_entries": reacquire_entries,
    }


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(
        description="Replay a first-version follow safety state machine from bbox gate row evidence."
    )
    ap.add_argument("--rows", default="outputs/openbot_follow_x025_g8_d2_bboxgate_pred_bbox_gate_rows.csv")
    ap.add_argument("--output-prefix", default="openbot_follow_x025_g8_d2_state_replay")
    ap.add_argument("--caution-stable-frames", type=int, default=3)
    ap.add_argument("--uncertain-frames", type=int, default=3)
    ap.add_argument("--reacquire-default-frames", type=int, default=3)
    ap.add_argument("--reacquire-strict-frames", type=int, default=2)
    ap.add_argument("--uncertain-recover-frames", type=int, default=3)
    ap.add_argument("--lost-recover-frames", type=int, default=5)
    ap.add_argument("--identity-timeout", type=int, default=8)
    ap.add_argument("--search-timeout", type=int, default=12)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    rows_path = resolve(root, args.rows)
    out_dir = root / "outputs"
    out_dir.mkdir(exist_ok=True)

    groups = load_observations(rows_path)
    if not groups:
        raise RuntimeError(f"No observations found in {rows_path}")

    summary_by_gap_scenario = defaultdict(lambda: Counter())
    transition_rows = []
    frame_rows = []
    final_state_counts = Counter()
    uncertain_durations_by_group = defaultdict(list)

    for (trial, gap, scenario, target_identity), seq in sorted(groups.items()):
        result = replay_sequence(seq, args)
        key = (gap, scenario)
        summary_by_gap_scenario[key]["sequence_count"] += 1
        summary_by_gap_scenario[key]["frame_count"] += len(seq)
        summary_by_gap_scenario[key]["wrong_follow_recovery_count"] += result["wrong_follow_recovery_count"]
        summary_by_gap_scenario[key]["wrong_follow_frame_count"] += result["wrong_follow_frame_count"]
        summary_by_gap_scenario[key]["target_present_over_stop_count"] += result["target_present_over_stop_count"]
        summary_by_gap_scenario[key]["target_present_uncertain_count"] += result["target_present_uncertain_count"]
        summary_by_gap_scenario[key]["identity_uncertain_entries"] += result["identity_uncertain_entries"]
        summary_by_gap_scenario[key]["reacquire_entries"] += result["reacquire_entries"]
        final_state_counts[(gap, scenario, result["final_state"])] += 1
        uncertain_durations_by_group[key].extend(result["uncertain_durations"])

        for (from_state, to_state), count in result["transitions"].items():
            transition_rows.append({
                "trial": trial,
                "gap": gap,
                "scenario": scenario,
                "target_identity": target_identity,
                "from_state": from_state,
                "to_state": to_state,
                "count": count,
            })

        frame_rows.extend(result["frame_rows"])

    summary_rows = []
    for (gap, scenario), c in sorted(summary_by_gap_scenario.items()):
        durations = uncertain_durations_by_group[(gap, scenario)]
        final_counts = {
            state: final_state_counts[(gap, scenario, state)]
            for state in [FOLLOW_CONFIDENT, FOLLOW_CAUTION, REACQUIRE_TARGET, LOST_SEARCH, IDENTITY_UNCERTAIN, STOP]
        }
        frame_count = c["frame_count"]
        summary_rows.append({
            "gap": gap,
            "scenario": scenario,
            "sequence_count": c["sequence_count"],
            "frame_count": frame_count,
            "wrong_follow_recovery_count": c["wrong_follow_recovery_count"],
            "wrong_follow_frame_rate": c["wrong_follow_frame_count"] / frame_count if frame_count else 0,
            "target_present_over_stop_count": c["target_present_over_stop_count"],
            "target_present_over_stop_rate": c["target_present_over_stop_count"] / frame_count if frame_count else 0,
            "target_present_uncertain_rate": c["target_present_uncertain_count"] / frame_count if frame_count else 0,
            "identity_uncertain_entries": c["identity_uncertain_entries"],
            "average_uncertainty_duration": (sum(durations) / len(durations)) if durations else 0,
            "reacquire_entries": c["reacquire_entries"],
            "final_follow_confident": final_counts[FOLLOW_CONFIDENT],
            "final_follow_caution": final_counts[FOLLOW_CAUTION],
            "final_reacquire_target": final_counts[REACQUIRE_TARGET],
            "final_lost_search": final_counts[LOST_SEARCH],
            "final_identity_uncertain": final_counts[IDENTITY_UNCERTAIN],
            "final_stop": final_counts[STOP],
        })

    summary_fields = [
        "gap", "scenario", "sequence_count", "frame_count",
        "wrong_follow_recovery_count", "wrong_follow_frame_rate",
        "target_present_over_stop_count", "target_present_over_stop_rate",
        "target_present_uncertain_rate", "identity_uncertain_entries",
        "average_uncertainty_duration", "reacquire_entries",
        "final_follow_confident", "final_follow_caution", "final_reacquire_target",
        "final_lost_search", "final_identity_uncertain", "final_stop",
    ]
    transition_fields = ["trial", "gap", "scenario", "target_identity", "from_state", "to_state", "count"]
    frame_fields = [
        "trial", "gap", "scenario", "target_identity", "frame_no", "prev_state", "state",
        "best_label", "best_score", "margin",
        "weak_ok", "mid_ok", "strong_ok", "bbox_default_ok", "bbox_strict_ok", "prediction_strict_ok",
        "mid_default_streak", "strong_default_streak", "strong_strict_streak",
        "strong_strict_prediction_streak", "correct",
    ]

    write_csv(out_dir / f"{args.output_prefix}_summary.csv", summary_rows, summary_fields)
    write_csv(out_dir / f"{args.output_prefix}_transitions.csv", transition_rows, transition_fields)
    write_csv(out_dir / f"{args.output_prefix}_frame_rows.csv", frame_rows, frame_fields)

    print(f"[INFO] rows = {rows_path}")
    print("[INFO] note: bbox gate rows are sampled evidence streams, not real continuous video tracks.")
    print("[INFO] target-present over_stop_rate is a stress-test signal and should be verified again on chronological tracks.")
    print("\n=== State Machine Replay Summary ===")
    for row in summary_rows:
        print(
            f"gap={row['gap']} scenario={row['scenario']} "
            f"wrong_recover={row['wrong_follow_recovery_count']} "
            f"wrong_follow_frame_rate={row['wrong_follow_frame_rate']:.3f} "
            f"over_stop_rate={row['target_present_over_stop_rate']:.3f} "
            f"uncertain_rate={row['target_present_uncertain_rate']:.3f} "
            f"avg_uncertain={row['average_uncertainty_duration']:.2f}"
        )

    print("\n[INFO] saved:")
    print(f"  {out_dir / (args.output_prefix + '_summary.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_transitions.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_frame_rows.csv')}")


if __name__ == "__main__":
    main()
