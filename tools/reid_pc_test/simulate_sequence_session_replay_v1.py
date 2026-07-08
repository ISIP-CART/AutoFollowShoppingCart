from pathlib import Path
import argparse
import csv
import json
from collections import Counter, defaultdict

import torch

from simulate_chronological_session_replay_v1 import (
    FOLLOW_CAUTION,
    FOLLOW_CONFIDENT,
    IDENTITY_UNCERTAIN,
    LOST_SEARCH,
    REACQUIRE_TARGET,
    STOP,
    enter_state,
    initial_counters,
    step_state_machine,
    write_csv,
)
from simulate_target_follow_with_bbox_v1 import bbox_metrics, extract, resolve, select_diverse


def to_int(row, key, default=0):
    value = row.get(key, "")
    return int(float(value)) if value != "" else default


def to_float(row, key, default=0.0):
    value = row.get(key, "")
    return float(value) if value != "" else default


def truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_session(sequence_dir):
    frame_rows = load_csv(sequence_dir / "frame_log.csv")
    detection_rows = load_csv(sequence_dir / "detections.csv")
    event_rows = load_csv(sequence_dir / "events.csv")
    session_info_path = sequence_dir / "session_info.json"
    session_info = {}
    if session_info_path.exists():
        with session_info_path.open("r", encoding="utf-8-sig") as f:
            session_info = json.load(f)
    return frame_rows, detection_rows, event_rows, session_info


def bbox_from_detection(row):
    return {
        "left": to_float(row, "bbox_left"),
        "top": to_float(row, "bbox_top"),
        "right": to_float(row, "bbox_right"),
        "bottom": to_float(row, "bbox_bottom"),
        "width": to_float(row, "bbox_width"),
        "height": to_float(row, "bbox_height"),
        "image_width": 0,
        "image_height": 0,
    }


def add_dimensions(bbox, frame_row):
    bbox = dict(bbox)
    bbox["image_width"] = to_int(frame_row, "image_width", 1280)
    bbox["image_height"] = to_int(frame_row, "image_height", 720)
    return bbox


def pair_intervals(events, start_name, end_name, start_time, end_time, tolerance_ms):
    intervals = []
    active_start = None
    for event in sorted(events, key=lambda r: to_int(r, "timestamp_ms")):
        event_type = event.get("event_type", "")
        ts = to_int(event, "timestamp_ms")
        if event_type == start_name and active_start is None:
            active_start = ts
        elif event_type == end_name and active_start is not None:
            intervals.append((max(start_time, active_start - tolerance_ms), min(end_time, ts + tolerance_ms)))
            active_start = None
    if active_start is not None:
        intervals.append((max(start_time, active_start - tolerance_ms), end_time))
    return intervals


def in_intervals(timestamp_ms, intervals):
    return any(start <= timestamp_ms <= end for start, end in intervals)


def build_event_windows(frame_rows, event_rows, tolerance_ms):
    if not frame_rows:
        return {}, [], [], []
    start_time = min(to_int(r, "timestamp_ms") for r in frame_rows)
    end_time = max(to_int(r, "timestamp_ms") for r in frame_rows)
    absent = pair_intervals(event_rows, "target_left", "target_return", start_time, end_time, tolerance_ms)
    occlusion = pair_intervals(event_rows, "occlusion_start", "occlusion_end", start_time, end_time, tolerance_ms)
    distractor = pair_intervals(event_rows, "distractor_enter", "distractor_leave", start_time, end_time, tolerance_ms)
    by_frame = {}
    for row in frame_rows:
        ts = to_int(row, "timestamp_ms")
        tags = []
        if in_intervals(ts, absent):
            tags.append("target_absent")
        if in_intervals(ts, occlusion):
            tags.append("occlusion")
        if in_intervals(ts, distractor):
            tags.append("distractor")
        by_frame[to_int(row, "frame_id")] = ";".join(tags)
    return by_frame, absent, occlusion, distractor


def choose_gallery(detections_with_crops, frame_by_id, sequence_dir, gallery_seconds, gallery_k, feats, path_to_idx):
    if not detections_with_crops:
        raise RuntimeError("No detections with crop_path found.")
    first_ts = min(to_int(row, "timestamp_ms") for row in detections_with_crops)
    cutoff = first_ts + int(gallery_seconds * 1000)
    candidates = []
    for row in detections_with_crops:
        frame = frame_by_id.get(to_int(row, "frame_id"))
        if frame is None:
            continue
        if to_int(frame, "num_persons") != 1:
            continue
        if to_int(row, "timestamp_ms") > cutoff:
            continue
        path = (sequence_dir / row["crop_path"]).resolve()
        if path in path_to_idx:
            candidates.append(path_to_idx[path])

    if len(candidates) < gallery_k:
        fallback = []
        for row in detections_with_crops:
            frame = frame_by_id.get(to_int(row, "frame_id"))
            if frame is None or to_int(frame, "num_persons") != 1:
                continue
            path = (sequence_dir / row["crop_path"]).resolve()
            if path in path_to_idx:
                fallback.append(path_to_idx[path])
            if len(fallback) >= gallery_k:
                break
        candidates = fallback

    if len(candidates) < gallery_k:
        raise RuntimeError(f"Need at least {gallery_k} single-person crop detections for gallery.")
    return select_diverse(candidates, feats, gallery_k)


def score_frame_candidates(rows, sequence_dir, path_to_idx, gallery, feats):
    scored = []
    for row in rows:
        crop_path = row.get("crop_path", "")
        if not crop_path:
            continue
        path = (sequence_dir / crop_path).resolve()
        idx = path_to_idx.get(path)
        if idx is None:
            continue
        score = (feats[gallery] @ feats[idx]).max().item()
        scored.append((row, idx, score))
    scored.sort(key=lambda x: x[2], reverse=True)
    if not scored:
        return None
    best_row, best_idx, best_score = scored[0]
    second_score = scored[1][2] if len(scored) > 1 else 0.0
    return best_row, best_idx, best_score, second_score, scored


def format_intervals(intervals):
    return ";".join(f"{start}:{end}" for start, end in intervals)


def make_diagnostic_rows(frame_rows, first_stop_frame_no):
    def is_reid_row(row):
        return row.get("best_score", "") != ""

    def is_visible(row):
        return truthy(row.get("target_visible_by_event", ""))

    def in_segment(row, segment):
        if not is_reid_row(row):
            return False
        if first_stop_frame_no == "":
            return segment in {"all_reid", "pre_stop"}
        replay_no = int(row["replay_frame_no"])
        stop_no = int(first_stop_frame_no)
        if segment == "all_reid":
            return True
        if segment == "pre_stop":
            return replay_no < stop_no
        if segment == "at_or_post_stop":
            return replay_no >= stop_no
        if segment == "post_stop_only":
            return replay_no > stop_no
        return False

    rows = []
    for segment in ["all_reid", "pre_stop", "at_or_post_stop", "post_stop_only"]:
        selected = [row for row in frame_rows if in_segment(row, segment)]
        visible = [row for row in selected if is_visible(row)]
        absent = [row for row in selected if not is_visible(row)]
        stop_visible = [row for row in visible if row["state"] == STOP]
        uncertain_visible = [row for row in visible if row["state"] == IDENTITY_UNCERTAIN]
        wrong_follow_absent = [row for row in absent if row["state"] == FOLLOW_CONFIDENT]
        follow_confident_visible = [row for row in visible if row["state"] == FOLLOW_CONFIDENT]
        rows.append({
            "segment": segment,
            "reid_frames": len(selected),
            "visible_reid_frames": len(visible),
            "absent_reid_frames": len(absent),
            "follow_confident_visible_frames": len(follow_confident_visible),
            "uncertain_visible_frames": len(uncertain_visible),
            "stop_visible_frames": len(stop_visible),
            "wrong_follow_absent_frames": len(wrong_follow_absent),
            "wrong_follow_absent_rate": len(wrong_follow_absent) / len(absent) if absent else 0,
            "uncertain_visible_rate": len(uncertain_visible) / len(visible) if visible else 0,
            "stop_visible_rate": len(stop_visible) / len(visible) if visible else 0,
        })
    return rows


def step_empty_detection_state(state, counters, args):
    if state in {FOLLOW_CONFIDENT, FOLLOW_CAUTION, REACQUIRE_TARGET}:
        return LOST_SEARCH
    if state == IDENTITY_UNCERTAIN:
        counters["identity_uncertain_duration"] += 1
        return STOP if counters["identity_uncertain_duration"] >= args.identity_timeout else IDENTITY_UNCERTAIN
    if state == LOST_SEARCH:
        counters["search_duration"] += 1
        return STOP if counters["search_duration"] >= args.search_timeout else LOST_SEARCH
    return STOP


def main():
    ap = argparse.ArgumentParser(description="Replay a real PersonSequenceCollector session with ReID + bbox gates.")
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--identity", required=True)
    ap.add_argument("--weight", required=True)
    ap.add_argument("--model", default="osnet_x0_25")
    ap.add_argument("--gallery-seconds", type=float, default=5.0)
    ap.add_argument("--gallery-k", type=int, default=8)
    ap.add_argument("--event-tolerance-ms", type=int, default=1000)
    ap.add_argument("--gap", type=int, default=1)
    ap.add_argument("--output-prefix", default="sequence_session_replay")
    ap.add_argument("--caution-stable-frames", type=int, default=3)
    ap.add_argument("--uncertain-frames", type=int, default=3)
    ap.add_argument("--reacquire-default-frames", type=int, default=3)
    ap.add_argument("--reacquire-strict-frames", type=int, default=2)
    ap.add_argument("--uncertain-recover-frames", type=int, default=3)
    ap.add_argument("--lost-recover-frames", type=int, default=5)
    ap.add_argument("--identity-timeout", type=int, default=20)
    ap.add_argument("--search-timeout", type=int, default=20)
    ap.add_argument(
        "--missing-frame-policy",
        choices=["hold", "advance_empty"],
        default="hold",
        help="hold keeps state unchanged on frames without crop features; advance_empty lets num_persons=0 frames drive LOST_SEARCH/STOP.",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    sequence_dir = resolve(root, args.sequence)
    weight_path = resolve(root, args.weight)
    out_dir = root / "outputs"
    out_dir.mkdir(exist_ok=True)

    frame_rows_raw, detection_rows_raw, event_rows, session_info = load_session(sequence_dir)
    frame_by_id = {to_int(row, "frame_id"): row for row in frame_rows_raw}
    detections_by_frame = defaultdict(list)
    detections_with_crops = []
    missing_crop_rows = 0
    missing_crop_files = 0
    for row in detection_rows_raw:
        frame_id = to_int(row, "frame_id")
        detections_by_frame[frame_id].append(row)
        crop_path = row.get("crop_path", "")
        if crop_path:
            path = sequence_dir / crop_path
            if path.exists():
                detections_with_crops.append(row)
            else:
                missing_crop_files += 1
        else:
            missing_crop_rows += 1

    event_by_frame, absent_intervals, occlusion_intervals, distractor_intervals = build_event_windows(
        frame_rows_raw, event_rows, args.event_tolerance_ms
    )

    crop_paths = sorted({(sequence_dir / row["crop_path"]).resolve() for row in detections_with_crops})
    if not crop_paths:
        raise RuntimeError("No usable crop files found in sequence.")
    path_to_idx = {path: i for i, path in enumerate(crop_paths)}

    print(f"[INFO] sequence = {sequence_dir}")
    print(f"[INFO] identity = {args.identity}")
    print(f"[INFO] model = {args.model}")
    print(f"[INFO] weight = {weight_path}")
    print(f"[INFO] frame_rows = {len(frame_rows_raw)}")
    print(f"[INFO] detection_rows = {len(detection_rows_raw)}")
    print(f"[INFO] crop_files_used = {len(crop_paths)}")
    print(f"[INFO] event_rows = {len(event_rows)}")
    print(f"[INFO] event_tolerance_ms = {args.event_tolerance_ms}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device = {device}")
    feats = extract(args.model, weight_path, crop_paths, device)
    print(f"[INFO] feature_shape = {tuple(feats.shape)}")

    gallery = choose_gallery(
        detections_with_crops,
        frame_by_id,
        sequence_dir,
        args.gallery_seconds,
        args.gallery_k,
        feats,
        path_to_idx,
    )
    gallery_paths = {crop_paths[idx] for idx in gallery}

    state = FOLLOW_CONFIDENT
    counters = initial_counters()
    frame_rows = []
    transition_rows = []
    summary = Counter()
    recovery_waits = []
    waiting_for_recovery = None
    first_stop_frame_no = ""
    first_stop_frame_id = ""
    first_stop_timestamp_ms = ""
    visible_history = []
    for row in detections_with_crops:
        path = (sequence_dir / row["crop_path"]).resolve()
        if path in gallery_paths:
            frame = frame_by_id.get(to_int(row, "frame_id"))
            if frame is not None:
                visible_history.append(add_dimensions(bbox_from_detection(row), frame))
    if not visible_history:
        first_row = detections_with_crops[0]
        visible_history.append(add_dimensions(bbox_from_detection(first_row), frame_by_id[to_int(first_row, "frame_id")]))

    for replay_no, frame in enumerate(sorted(frame_rows_raw, key=lambda r: to_int(r, "timestamp_ms"))):
        frame_id = to_int(frame, "frame_id")
        candidate_rows = detections_by_frame.get(frame_id, [])
        scored = score_frame_candidates(candidate_rows, sequence_dir, path_to_idx, gallery, feats)
        event_window = event_by_frame.get(frame_id, "")
        target_absent = "target_absent" in event_window
        target_visible = not target_absent

        if scored is None:
            prev_state = state
            missing_policy_action = "hold"
            if args.missing_frame_policy == "advance_empty" and len(candidate_rows) == 0:
                next_state = step_empty_detection_state(state, counters, args)
                state = enter_state(state, next_state, counters)
                counters["state_stable_count"] += 1
                missing_policy_action = "advance_empty"
                if state == STOP and first_stop_frame_no == "":
                    first_stop_frame_no = replay_no
                    first_stop_frame_id = frame_id
                    first_stop_timestamp_ms = to_int(frame, "timestamp_ms")
                if prev_state != state:
                    transition_rows.append({
                        "frame_no": replay_no,
                        "frame_id": frame_id,
                        "timestamp_ms": to_int(frame, "timestamp_ms"),
                        "from_state": prev_state,
                        "to_state": state,
                        "event_window": event_window,
                        "target_visible_by_event": target_visible,
                        "best_det_id": "",
                        "best_score": "",
                        "margin": "",
                    })

            frame_rows.append({
                "replay_frame_no": replay_no,
                "frame_id": frame_id,
                "timestamp_ms": to_int(frame, "timestamp_ms"),
                "elapsed_ms": to_int(frame, "elapsed_ms"),
                "num_persons": to_int(frame, "num_persons"),
                "event_window": event_window,
                "target_visible_by_event": target_visible,
                "candidate_count": len(candidate_rows),
                "crop_candidate_count": 0,
                "best_det_id": "",
                "best_path": "",
                "best_score": "",
                "second_score": "",
                "margin": "",
                "center_jump_ratio": "",
                "x_jump_ratio": "",
                "area_ratio": "",
                "prediction_error": "",
                "prev_state": state,
                "state": state,
                "weak_ok": "",
                "mid_ok": "",
                "strong_ok": "",
                "bbox_default_ok": "",
                "bbox_strict_ok": "",
                "prediction_strict_ok": "",
                "missing_policy_action": missing_policy_action,
            })
            continue

        best_row, best_idx, best_score, second_score, scored_candidates = scored
        margin = best_score - second_score
        best_bbox = add_dimensions(bbox_from_detection(best_row), frame)
        last_ref = visible_history[-args.gap] if len(visible_history) >= args.gap else visible_history[-1]
        prev_ref = visible_history[-2 * args.gap] if len(visible_history) >= 2 * args.gap else None
        metrics = bbox_metrics(best_bbox, last_ref, prev_ref)
        obs = {"best_score": best_score, "margin": margin, **metrics}

        prev_state = state
        was_before_first_stop = first_stop_frame_no == ""
        flags = step_state_machine(state, obs, counters, args)
        next_state = flags.pop("next_state")
        state = enter_state(state, next_state, counters)
        counters["state_stable_count"] += 1
        if state == STOP and first_stop_frame_no == "":
            first_stop_frame_no = replay_no
            first_stop_frame_id = frame_id
            first_stop_timestamp_ms = to_int(frame, "timestamp_ms")

        if prev_state != state:
            transition_rows.append({
                "frame_no": replay_no,
                "frame_id": frame_id,
                "timestamp_ms": to_int(frame, "timestamp_ms"),
                "from_state": prev_state,
                "to_state": state,
                "event_window": event_window,
                "target_visible_by_event": target_visible,
                "best_det_id": best_row.get("det_id", ""),
                "best_score": best_score,
                "margin": margin,
            })
            if target_absent and state == FOLLOW_CONFIDENT:
                summary["wrong_recovery_count"] += 1
            if waiting_for_recovery is not None and state == FOLLOW_CONFIDENT:
                recovery_waits.append(replay_no - waiting_for_recovery)
                waiting_for_recovery = None

        if target_visible and waiting_for_recovery is None and prev_state in {LOST_SEARCH, IDENTITY_UNCERTAIN, STOP}:
            waiting_for_recovery = replay_no

        if target_visible:
            summary["target_visible_frames"] += 1
            if was_before_first_stop and state != STOP:
                summary["target_visible_frames_before_stop"] += 1
            if state == STOP:
                summary["over_stop_frames"] += 1
            if state == IDENTITY_UNCERTAIN:
                summary["uncertain_frames"] += 1
                if was_before_first_stop:
                    summary["uncertain_frames_before_stop"] += 1
            visible_history.append(best_bbox)
        else:
            summary["target_absent_frames"] += 1
            if state == FOLLOW_CONFIDENT:
                summary["wrong_follow_frames"] += 1

        if "distractor" in event_window:
            summary["distractor_window_frames"] += 1
            if state == FOLLOW_CONFIDENT and target_absent:
                summary["distractor_absent_follow_frames"] += 1
        if "occlusion" in event_window:
            summary["occlusion_window_frames"] += 1
        if prev_state == REACQUIRE_TARGET and state == FOLLOW_CONFIDENT:
            summary["reacquire_success_count"] += 1

        frame_rows.append({
            "replay_frame_no": replay_no,
            "frame_id": frame_id,
            "timestamp_ms": to_int(frame, "timestamp_ms"),
            "elapsed_ms": to_int(frame, "elapsed_ms"),
            "num_persons": to_int(frame, "num_persons"),
            "event_window": event_window,
            "target_visible_by_event": target_visible,
            "candidate_count": len(candidate_rows),
            "crop_candidate_count": len(scored_candidates),
            "best_det_id": best_row.get("det_id", ""),
            "best_path": best_row.get("crop_path", ""),
            "best_score": best_score,
            "second_score": second_score,
            "margin": margin,
            "center_jump_ratio": metrics["center_jump_ratio"],
            "x_jump_ratio": metrics["x_jump_ratio"],
            "area_ratio": metrics["area_ratio"],
            "prediction_error": metrics["prediction_error"],
            "prev_state": prev_state,
            "state": state,
            "missing_policy_action": "",
            **flags,
        })

    total_reid_frames = sum(1 for row in frame_rows if row["best_score"] != "")
    visible_frames = summary["target_visible_frames"]
    absent_frames = summary["target_absent_frames"]
    diagnostic_rows = make_diagnostic_rows(frame_rows, first_stop_frame_no)
    summary_row = {
        "identity": args.identity,
        "session_id": session_info.get("session_id", sequence_dir.name),
        "total_frame_log_rows": len(frame_rows_raw),
        "total_detection_rows": len(detection_rows_raw),
        "total_crop_files_used": len(crop_paths),
        "total_reid_frames": total_reid_frames,
        "target_visible_reid_frames": visible_frames,
        "target_absent_reid_frames": absent_frames,
        "wrong_follow_frame_rate": summary["wrong_follow_frames"] / absent_frames if absent_frames else 0,
        "wrong_recovery_count": summary["wrong_recovery_count"],
        "over_stop_rate": summary["over_stop_frames"] / visible_frames if visible_frames else 0,
        "uncertain_rate": summary["uncertain_frames"] / visible_frames if visible_frames else 0,
        "stop_count": sum(1 for row in transition_rows if row["to_state"] == STOP),
        "first_stop_frame_no": first_stop_frame_no,
        "first_stop_frame_id": first_stop_frame_id,
        "first_stop_timestamp_ms": first_stop_timestamp_ms,
        "target_visible_frames_before_stop": summary["target_visible_frames_before_stop"],
        "target_visible_frames_at_or_after_stop": (
            visible_frames - summary["target_visible_frames_before_stop"] if first_stop_frame_no != "" else 0
        ),
        "terminal_stop_tail_share_of_visible": (
            (visible_frames - summary["target_visible_frames_before_stop"]) / visible_frames
            if visible_frames and first_stop_frame_no != ""
            else 0
        ),
        "uncertain_before_stop_rate": (
            summary["uncertain_frames_before_stop"] / summary["target_visible_frames_before_stop"]
            if summary["target_visible_frames_before_stop"]
            else 0
        ),
        "reacquire_success_count": summary["reacquire_success_count"],
        "mean_recovery_frames": sum(recovery_waits) / len(recovery_waits) if recovery_waits else "",
        "distractor_window_frames": summary["distractor_window_frames"],
        "distractor_absent_follow_frames": summary["distractor_absent_follow_frames"],
        "occlusion_window_frames": summary["occlusion_window_frames"],
        "final_state": state,
        "gallery_k": args.gallery_k,
        "gallery_seconds": args.gallery_seconds,
        "event_tolerance_ms": args.event_tolerance_ms,
        "identity_timeout": args.identity_timeout,
        "search_timeout": args.search_timeout,
        "missing_frame_policy": args.missing_frame_policy,
        "target_absent_intervals": format_intervals(absent_intervals),
        "occlusion_intervals": format_intervals(occlusion_intervals),
        "distractor_intervals": format_intervals(distractor_intervals),
    }

    data_quality_rows = [
        {"metric": "frame_log_rows", "value": len(frame_rows_raw), "note": ""},
        {"metric": "detection_rows", "value": len(detection_rows_raw), "note": ""},
        {"metric": "event_rows", "value": len(event_rows), "note": ""},
        {"metric": "detections_with_crop_files", "value": len(detections_with_crops), "note": ""},
        {"metric": "unique_crop_files_used", "value": len(crop_paths), "note": ""},
        {"metric": "detection_rows_without_crop_path", "value": missing_crop_rows, "note": "Expected when crop sampling is slower than frame logging."},
        {"metric": "detection_rows_with_missing_crop_file", "value": missing_crop_files, "note": ""},
        {"metric": "num_persons_0_frames", "value": sum(1 for r in frame_rows_raw if to_int(r, "num_persons") == 0), "note": ""},
        {"metric": "num_persons_1_frames", "value": sum(1 for r in frame_rows_raw if to_int(r, "num_persons") == 1), "note": ""},
        {"metric": "num_persons_2plus_frames", "value": sum(1 for r in frame_rows_raw if to_int(r, "num_persons") >= 2), "note": ""},
        {"metric": "target_absent_intervals", "value": format_intervals(absent_intervals), "note": "Expanded by event tolerance."},
        {"metric": "occlusion_intervals", "value": format_intervals(occlusion_intervals), "note": "Expanded by event tolerance."},
        {"metric": "distractor_intervals", "value": format_intervals(distractor_intervals), "note": "Expanded by event tolerance."},
    ]

    frame_fields = [
        "replay_frame_no", "frame_id", "timestamp_ms", "elapsed_ms", "num_persons", "event_window",
        "target_visible_by_event", "candidate_count", "crop_candidate_count", "best_det_id", "best_path",
        "best_score", "second_score", "margin", "center_jump_ratio", "x_jump_ratio", "area_ratio",
        "prediction_error", "prev_state", "state", "weak_ok", "mid_ok", "strong_ok",
        "bbox_default_ok", "bbox_strict_ok", "prediction_strict_ok", "missing_policy_action",
    ]
    transition_fields = [
        "frame_no", "frame_id", "timestamp_ms", "from_state", "to_state", "event_window",
        "target_visible_by_event", "best_det_id", "best_score", "margin",
    ]
    diagnostic_fields = [
        "segment", "reid_frames", "visible_reid_frames", "absent_reid_frames",
        "follow_confident_visible_frames", "uncertain_visible_frames", "stop_visible_frames",
        "wrong_follow_absent_frames", "wrong_follow_absent_rate", "uncertain_visible_rate",
        "stop_visible_rate",
    ]
    summary_fields = list(summary_row.keys())

    write_csv(out_dir / f"{args.output_prefix}_data_quality.csv", data_quality_rows, ["metric", "value", "note"])
    write_csv(out_dir / f"{args.output_prefix}_frame_rows.csv", frame_rows, frame_fields)
    write_csv(out_dir / f"{args.output_prefix}_transitions.csv", transition_rows, transition_fields)
    write_csv(out_dir / f"{args.output_prefix}_diagnostic_summary.csv", diagnostic_rows, diagnostic_fields)
    write_csv(out_dir / f"{args.output_prefix}_summary.csv", [summary_row], summary_fields)

    print("\n=== Sequence Session Replay Summary ===")
    for key in [
        "total_frame_log_rows", "total_detection_rows", "total_crop_files_used", "total_reid_frames",
        "target_absent_reid_frames", "wrong_follow_frame_rate", "wrong_recovery_count",
        "over_stop_rate", "terminal_stop_tail_share_of_visible", "uncertain_rate", "stop_count", "final_state",
    ]:
        print(f"{key} = {summary_row[key]}")
    print("\n[INFO] saved:")
    print(f"  {out_dir / (args.output_prefix + '_data_quality.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_frame_rows.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_transitions.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_diagnostic_summary.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_summary.csv')}")


if __name__ == "__main__":
    main()
