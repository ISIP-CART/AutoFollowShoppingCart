from pathlib import Path
import argparse
import csv
from collections import Counter
import random

import torch

from simulate_target_follow_with_bbox_v1 import (
    BBOX_PROFILES,
    REID_PROFILES,
    bbox_metrics,
    collect_from_manifest,
    extract,
    load_manifest,
    resolve,
    score_candidates,
    select_gallery,
)

FOLLOW_CONFIDENT = "FOLLOW_CONFIDENT"
FOLLOW_CAUTION = "FOLLOW_CAUTION"
REACQUIRE_TARGET = "REACQUIRE_TARGET"
LOST_SEARCH = "LOST_SEARCH"
IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"
STOP = "STOP"


def parse_ranges(text):
    ranges = []
    if not text:
        return ranges
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            idx = int(part)
            ranges.append((idx, idx))
            continue
        start, end = part.split(":", 1)
        ranges.append((int(start), int(end)))
    return ranges


def in_ranges(index, ranges):
    return any(start <= index <= end for start, end in ranges)


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_sequences(manifest_rows, path_to_idx):
    sequences = {}
    for item in manifest_rows:
        if item["path"] not in path_to_idx:
            continue
        key = (item["identity"], item["session_id"])
        sequences.setdefault(key, []).append(item)
    for key in sequences:
        sequences[key].sort(key=lambda x: (x["timestamp_ms"], x["frame_id"], x["rel_path"]))
    return sequences


def choose_target_sequence(sequences, identity, session_id):
    matches = [
        (key, seq)
        for key, seq in sequences.items()
        if key[0] == identity and (not session_id or key[1] == session_id)
    ]
    if not matches:
        raise RuntimeError(f"No session found for identity={identity!r}, session_id={session_id!r}")
    matches.sort(key=lambda x: (x[0][0], x[0][1]))
    return matches[0]


def choose_distractor_sequence(sequences, identity, session_id, target_identity):
    if not identity:
        return None, []
    matches = [
        (key, seq)
        for key, seq in sequences.items()
        if key[0] == identity and key[0] != target_identity and (not session_id or key[1] == session_id)
    ]
    if not matches:
        raise RuntimeError(f"No distractor session found for identity={identity!r}, session_id={session_id!r}")
    matches.sort(key=lambda x: (x[0][0], x[0][1]))
    return matches[0]


def get_by_pos(seq, pos):
    if not seq:
        return None
    return seq[pos % len(seq)]


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
    return value != "" and float(value) <= BBOX_PROFILES[profile]["center"]


def enter_state(state, next_state, counters):
    if next_state != state:
        counters["state_stable_count"] = 0
    if state == IDENTITY_UNCERTAIN and next_state != IDENTITY_UNCERTAIN:
        counters["identity_uncertain_duration"] = 0
    if next_state == IDENTITY_UNCERTAIN and state != IDENTITY_UNCERTAIN:
        counters["identity_uncertain_entries"] += 1
    if next_state == LOST_SEARCH and state != LOST_SEARCH:
        counters["search_duration"] = 0
    return next_state


def step_state_machine(state, obs, counters, args):
    weak_ok = reid_ok(obs, "weak")
    mid_ok = reid_ok(obs, "mid")
    strong_ok = reid_ok(obs, "strong")
    bbox_default = bbox_ok(obs, "default")
    bbox_strict = bbox_ok(obs, "strict")
    pred_strict = prediction_ok(obs, "strict")

    counters["mid_default_streak"] = counters["mid_default_streak"] + 1 if mid_ok and bbox_default else 0
    counters["strong_default_streak"] = counters["strong_default_streak"] + 1 if strong_ok and bbox_default else 0
    counters["strong_strict_streak"] = counters["strong_strict_streak"] + 1 if strong_ok and bbox_strict else 0
    counters["strong_strict_prediction_streak"] = (
        counters["strong_strict_prediction_streak"] + 1 if strong_ok and bbox_strict and pred_strict else 0
    )

    if state == FOLLOW_CONFIDENT:
        if bbox_default and weak_ok:
            next_state = FOLLOW_CONFIDENT
            counters["unstable_streak"] = 0
        elif bbox_default:
            next_state = FOLLOW_CAUTION
            counters["unstable_streak"] = 0
        else:
            counters["unstable_streak"] += 1
            next_state = IDENTITY_UNCERTAIN

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

    return {
        "next_state": next_state,
        "weak_ok": weak_ok,
        "mid_ok": mid_ok,
        "strong_ok": strong_ok,
        "bbox_default_ok": bbox_default,
        "bbox_strict_ok": bbox_strict,
        "prediction_strict_ok": pred_strict,
    }


def initial_counters():
    return {
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


def main():
    ap = argparse.ArgumentParser(description="Replay one real session in chronological order with ReID + bbox gates.")
    ap.add_argument("--images", default="images_openbot_clean")
    ap.add_argument("--manifest", default="images_openbot_clean/dataset_manifest.csv")
    ap.add_argument("--weight", required=True)
    ap.add_argument("--model", default="osnet_x0_25")
    ap.add_argument("--identity", required=True)
    ap.add_argument("--session-id", default="")
    ap.add_argument("--gallery-k", type=int, default=8)
    ap.add_argument("--gallery-strategy", choices=["random", "diverse", "first"], default="first")
    ap.add_argument("--gap", type=int, default=1)
    ap.add_argument("--distractors", type=int, default=2)
    ap.add_argument("--distractor-identity", default="")
    ap.add_argument("--distractor-session-id", default="")
    ap.add_argument("--distractor-ranges", default="")
    ap.add_argument("--missing-ranges", default="")
    ap.add_argument("--image-width", type=int, default=1280)
    ap.add_argument("--image-height", type=int, default=720)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output-prefix", default="chronological_session_replay")
    ap.add_argument("--caution-stable-frames", type=int, default=3)
    ap.add_argument("--uncertain-frames", type=int, default=3)
    ap.add_argument("--reacquire-default-frames", type=int, default=3)
    ap.add_argument("--reacquire-strict-frames", type=int, default=2)
    ap.add_argument("--uncertain-recover-frames", type=int, default=3)
    ap.add_argument("--lost-recover-frames", type=int, default=5)
    ap.add_argument("--identity-timeout", type=int, default=20)
    ap.add_argument("--search-timeout", type=int, default=20)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    image_dir = resolve(root, args.images)
    manifest_path = resolve(root, args.manifest)
    weight_path = resolve(root, args.weight)
    out_dir = root / "outputs"
    out_dir.mkdir(exist_ok=True)

    if args.gap < 1:
        raise RuntimeError("--gap must be >= 1")
    rng = random.Random(args.seed)
    missing_ranges = parse_ranges(args.missing_ranges)
    distractor_ranges = parse_ranges(args.distractor_ranges)

    manifest_rows, _ = load_manifest(manifest_path, image_dir, args.image_width, args.image_height)
    data = collect_from_manifest(manifest_rows, per_id=None, seed=args.seed, sample_mode="random")
    identities = sorted(data.keys())

    all_paths, labels = [], []
    for ident in identities:
        for path in data[ident]:
            all_paths.append(path)
            labels.append(ident)

    path_to_idx = {p: i for i, p in enumerate(all_paths)}
    idx_to_path = {i: p for p, i in path_to_idx.items()}
    idx_to_label = {i: labels[i] for i in range(len(labels))}
    path_to_item = {item["path"]: item for item in manifest_rows}
    sequences = build_sequences(manifest_rows, path_to_idx)

    (target_key, target_seq) = choose_target_sequence(sequences, args.identity, args.session_id)
    if len(target_seq) <= args.gallery_k + args.gap:
        raise RuntimeError("Target session is too short for gallery-k and gap.")

    distractor_key, distractor_seq = choose_distractor_sequence(
        sequences, args.distractor_identity, args.distractor_session_id, args.identity
    )

    other_indices = [
        i for i, label in idx_to_label.items()
        if label != args.identity
        and (not args.distractor_identity or label != args.distractor_identity)
    ]
    if args.distractors > 0 and not other_indices and not distractor_seq:
        raise RuntimeError("No available distractor images.")

    print(f"[INFO] image_dir = {image_dir}")
    print(f"[INFO] manifest = {manifest_path}")
    print(f"[INFO] weight = {weight_path}")
    print(f"[INFO] model = {args.model}")
    print(f"[INFO] identity = {target_key[0]}")
    print(f"[INFO] session_id = {target_key[1]}")
    print(f"[INFO] gallery_k = {args.gallery_k}")
    print(f"[INFO] gallery_strategy = {args.gallery_strategy}")
    print(f"[INFO] gap = {args.gap}")
    print(f"[INFO] missing_ranges = {missing_ranges}")
    print(f"[INFO] distractor = {distractor_key}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device = {device}")
    feats = extract(args.model, weight_path, all_paths, device)
    print(f"[INFO] feature_shape = {tuple(feats.shape)}")

    target_indices = [path_to_idx[item["path"]] for item in target_seq]
    if args.gallery_strategy == "first":
        gallery = target_indices[:args.gallery_k]
    else:
        gallery = select_gallery(target_indices, feats, args.gallery_k, args.gallery_strategy, rng)

    probe_seq = [item for item in target_seq if path_to_idx[item["path"]] not in set(gallery)]
    if not probe_seq:
        raise RuntimeError("No probe frames remain after gallery selection.")

    state = FOLLOW_CONFIDENT
    counters = initial_counters()
    frame_rows = []
    transition_rows = []
    summary = Counter()
    recovery_waits = []
    waiting_for_recovery = None
    visible_history = list(target_seq[:args.gallery_k])

    for replay_no, target_item in enumerate(probe_seq):
        target_visible = not in_ranges(replay_no, missing_ranges)
        inject_distractor = in_ranges(replay_no, distractor_ranges)
        candidate_indices = []

        if target_visible:
            candidate_indices.append(path_to_idx[target_item["path"]])
        if distractor_seq and (inject_distractor or not target_visible):
            distractor_item = get_by_pos(distractor_seq, replay_no)
            candidate_indices.append(path_to_idx[distractor_item["path"]])

        random_pool = list(other_indices)
        if candidate_indices:
            random_pool = [idx for idx in random_pool if idx not in set(candidate_indices)]
        for idx in rng.sample(random_pool, min(args.distractors, len(random_pool))):
            candidate_indices.append(idx)

        if not candidate_indices:
            continue

        best_idx, best_score, second_score = score_candidates(candidate_indices, gallery, feats)
        margin = best_score - second_score
        best_item = path_to_item[idx_to_path[best_idx]]
        last_ref_item = visible_history[-args.gap] if len(visible_history) >= args.gap else visible_history[-1]
        prev_ref_item = visible_history[-2 * args.gap] if len(visible_history) >= 2 * args.gap else None
        metrics = bbox_metrics(best_item["bbox"], last_ref_item["bbox"], prev_ref_item["bbox"] if prev_ref_item else None)
        obs = {
            "best_score": best_score,
            "margin": margin,
            **metrics,
        }
        prev_state = state
        flags = step_state_machine(state, obs, counters, args)
        next_state = flags.pop("next_state")
        state = enter_state(state, next_state, counters)
        counters["state_stable_count"] += 1

        if prev_state != state:
            transition_rows.append({
                "frame_no": replay_no,
                "frame_id": target_item["frame_id"],
                "timestamp_ms": target_item["timestamp_ms"],
                "from_state": prev_state,
                "to_state": state,
                "target_visible": target_visible,
                "best_label": idx_to_label[best_idx],
                "best_score": best_score,
                "margin": margin,
            })
            if not target_visible and state == FOLLOW_CONFIDENT:
                summary["wrong_recovery_count"] += 1
            if waiting_for_recovery is not None and state == FOLLOW_CONFIDENT:
                recovery_waits.append(replay_no - waiting_for_recovery)
                waiting_for_recovery = None

        if target_visible and waiting_for_recovery is None and prev_state in {LOST_SEARCH, IDENTITY_UNCERTAIN, STOP}:
            waiting_for_recovery = replay_no

        if target_visible:
            summary["target_visible_frames"] += 1
            if state == STOP:
                summary["over_stop_frames"] += 1
            if state == IDENTITY_UNCERTAIN:
                summary["uncertain_frames"] += 1
            if idx_to_label[best_idx] == args.identity:
                summary["reid_best_correct_frames"] += 1
            visible_history.append(target_item)
        else:
            summary["target_absent_frames"] += 1
            if state == FOLLOW_CONFIDENT:
                summary["wrong_follow_frames"] += 1

        if prev_state == REACQUIRE_TARGET and state == FOLLOW_CONFIDENT:
            summary["reacquire_success_count"] += 1

        frame_rows.append({
            "replay_frame_no": replay_no,
            "source_frame_id": target_item["frame_id"],
            "timestamp_ms": target_item["timestamp_ms"],
            "target_identity": args.identity,
            "target_session_id": target_key[1],
            "target_visible": target_visible,
            "candidate_count": len(candidate_indices),
            "best_label": idx_to_label[best_idx],
            "best_path": idx_to_path[best_idx].relative_to(image_dir).as_posix(),
            "best_score": best_score,
            "second_score": second_score,
            "margin": margin,
            "center_jump_ratio": metrics["center_jump_ratio"],
            "x_jump_ratio": metrics["x_jump_ratio"],
            "area_ratio": metrics["area_ratio"],
            "prediction_error": metrics["prediction_error"],
            "prev_state": prev_state,
            "state": state,
            **flags,
            "mid_default_streak": counters["mid_default_streak"],
            "strong_default_streak": counters["strong_default_streak"],
            "strong_strict_streak": counters["strong_strict_streak"],
            "strong_strict_prediction_streak": counters["strong_strict_prediction_streak"],
        })

    total_frames = len(frame_rows)
    visible_frames = summary["target_visible_frames"]
    absent_frames = summary["target_absent_frames"]
    summary_row = {
        "identity": args.identity,
        "session_id": target_key[1],
        "total_frames": total_frames,
        "target_visible_frames": visible_frames,
        "target_absent_frames": absent_frames,
        "wrong_follow_frame_rate": summary["wrong_follow_frames"] / absent_frames if absent_frames else 0,
        "wrong_recovery_count": summary["wrong_recovery_count"],
        "over_stop_rate": summary["over_stop_frames"] / visible_frames if visible_frames else 0,
        "uncertain_rate": summary["uncertain_frames"] / visible_frames if visible_frames else 0,
        "stop_count": sum(1 for row in transition_rows if row["to_state"] == STOP),
        "reacquire_success_count": summary["reacquire_success_count"],
        "mean_recovery_frames": sum(recovery_waits) / len(recovery_waits) if recovery_waits else "",
        "reid_best_acc_visible": summary["reid_best_correct_frames"] / visible_frames if visible_frames else "",
        "final_state": state,
        "identity_timeout": args.identity_timeout,
        "search_timeout": args.search_timeout,
        "missing_ranges": args.missing_ranges,
        "distractor_identity": args.distractor_identity,
        "distractor_session_id": args.distractor_session_id,
        "distractor_ranges": args.distractor_ranges,
    }

    frame_fields = [
        "replay_frame_no", "source_frame_id", "timestamp_ms", "target_identity", "target_session_id",
        "target_visible", "candidate_count", "best_label", "best_path", "best_score", "second_score", "margin",
        "center_jump_ratio", "x_jump_ratio", "area_ratio", "prediction_error", "prev_state", "state",
        "weak_ok", "mid_ok", "strong_ok", "bbox_default_ok", "bbox_strict_ok", "prediction_strict_ok",
        "mid_default_streak", "strong_default_streak", "strong_strict_streak", "strong_strict_prediction_streak",
    ]
    transition_fields = [
        "frame_no", "frame_id", "timestamp_ms", "from_state", "to_state", "target_visible",
        "best_label", "best_score", "margin",
    ]
    summary_fields = [
        "identity", "session_id", "total_frames", "target_visible_frames", "target_absent_frames",
        "wrong_follow_frame_rate", "wrong_recovery_count", "over_stop_rate", "uncertain_rate",
        "stop_count", "reacquire_success_count", "mean_recovery_frames", "reid_best_acc_visible",
        "final_state", "identity_timeout", "search_timeout", "missing_ranges",
        "distractor_identity", "distractor_session_id", "distractor_ranges",
    ]

    write_csv(out_dir / f"{args.output_prefix}_chronological_frame_rows.csv", frame_rows, frame_fields)
    write_csv(out_dir / f"{args.output_prefix}_chronological_transitions.csv", transition_rows, transition_fields)
    write_csv(out_dir / f"{args.output_prefix}_chronological_summary.csv", [summary_row], summary_fields)

    print("\n=== Chronological Session Replay Summary ===")
    print(f"identity = {summary_row['identity']}")
    print(f"session_id = {summary_row['session_id']}")
    print(f"total_frames = {summary_row['total_frames']}")
    print(f"wrong_follow_frame_rate = {summary_row['wrong_follow_frame_rate']:.3f}")
    print(f"wrong_recovery_count = {summary_row['wrong_recovery_count']}")
    print(f"over_stop_rate = {summary_row['over_stop_rate']:.3f}")
    print(f"uncertain_rate = {summary_row['uncertain_rate']:.3f}")
    print(f"stop_count = {summary_row['stop_count']}")
    print(f"reacquire_success_count = {summary_row['reacquire_success_count']}")
    print(f"final_state = {summary_row['final_state']}")
    print("\n[INFO] saved:")
    print(f"  {out_dir / (args.output_prefix + '_chronological_frame_rows.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_chronological_transitions.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_chronological_summary.csv')}")


if __name__ == "__main__":
    main()
