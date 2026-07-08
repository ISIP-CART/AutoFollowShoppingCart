from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional local dependency
    Image = None


DEFAULT_INPUT = Path("images/cartfollow_diagnostics")
DEFAULT_OUTPUT = Path("outputs/cartfollow_diagnostics_analysis")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except Exception:
        return default


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.mean(values) if values else 0.0


def pct_true(rows: list[dict[str, str]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get(field) == "1") / len(rows)


def nearest_at_or_after(sorted_frames: list[int], frame_id: int) -> int | None:
    for frame in sorted_frames:
        if frame >= frame_id:
            return frame
    return None


def first_after(
    sorted_frames: list[int],
    frame_rows: dict[int, dict[str, str]],
    identity_rows: dict[int, dict[str, str]],
    frame_id: int,
    predicate: Callable[[dict[str, str], dict[str, str]], bool],
    window_frames: int,
) -> int | None:
    for frame in sorted_frames:
        if frame < frame_id:
            continue
        if frame - frame_id > window_frames:
            break
        if predicate(frame_rows.get(frame, {}), identity_rows.get(frame, {})):
            return frame
    return None


def image_shape(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    if Image is not None:
        try:
            with Image.open(path) as img:
                return img.size
        except Exception:
            pass
    return jpeg_shape(path)


def jpeg_shape(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        while marker == 0xFF and i < len(data):
            marker = data[i]
            i += 1
        if marker in {0xD8, 0xD9}:
            continue
        if i + 2 > len(data):
            return None
        length = int.from_bytes(data[i : i + 2], "big")
        if length < 2 or i + length > len(data):
            return None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if length < 7:
                return None
            height = int.from_bytes(data[i + 3 : i + 5], "big")
            width = int.from_bytes(data[i + 5 : i + 7], "big")
            return width, height
        i += length
    return None


def crop_quality_flags(path: Path) -> str:
    shape = image_shape(path)
    if shape is None:
        return "missing_or_unreadable"
    w, h = shape
    flags = []
    if w > h * 1.15:
        flags.append("landscape_or_rotated")
    if h > w * 3.0:
        flags.append("very_tall_narrow")
    if min(w, h) < 80:
        flags.append("small_crop")
    return "|".join(flags) if flags else "ok"


def resolve_rel(session_dir: Path, rel_path: str) -> Path | None:
    rel_path = (rel_path or "").strip()
    if not rel_path:
        return None
    return session_dir / rel_path.replace("\\", "/")


@dataclass
class SessionData:
    session_dir: Path
    info: dict[str, object]
    frames: list[dict[str, str]]
    identities: list[dict[str, str]]
    events: list[dict[str, str]]

    @property
    def session_id(self) -> str:
        return self.session_dir.name

    @property
    def frame_by_id(self) -> dict[int, dict[str, str]]:
        return {safe_int(r.get("frame_id")): r for r in self.frames}

    @property
    def identity_by_id(self) -> dict[int, dict[str, str]]:
        return {safe_int(r.get("frame_id")): r for r in self.identities}

    @property
    def sorted_frames(self) -> list[int]:
        return sorted(self.frame_by_id)


def load_session(session_dir: Path) -> SessionData:
    info_path = session_dir / "session_info.json"
    info = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            info = {}
    return SessionData(
        session_dir=session_dir,
        info=info,
        frames=read_csv(session_dir / "frame_log.csv"),
        identities=read_csv(session_dir / "identity_log.csv"),
        events=read_csv(session_dir / "events.csv"),
    )


def summarize_session(s: SessionData) -> dict[str, object]:
    states = Counter(r.get("follow_state", "") for r in s.frames)
    actions = Counter(r.get("selected_action", "") for r in s.frames)
    persons = [safe_int(r.get("num_persons")) for r in s.frames]
    fps = [safe_float(r.get("fps")) for r in s.frames]
    best = [safe_float(r.get("best_score")) for r in s.identities]
    margin = [safe_float(r.get("margin")) for r in s.identities]
    belief = [safe_float(r.get("target_belief")) for r in s.identities]
    reasons = Counter(r.get("belief_reason", "") for r in s.identities)
    event_counts = Counter(r.get("event_type", "") for r in s.events)
    crop_count = len(list((s.session_dir / "crops").glob("*.jpg")))
    gallery_count = len(list((s.session_dir / "gallery").glob("*.jpg")))
    return {
        "session_id": s.session_id,
        "created_at": s.info.get("created_at", ""),
        "detector": s.info.get("detector", ""),
        "reid_available": s.info.get("reid_available", ""),
        "gallery_size": s.info.get("gallery_size", ""),
        "frame_rows": len(s.frames),
        "identity_rows": len(s.identities),
        "event_rows": len(s.events),
        "crop_count": crop_count,
        "gallery_count": gallery_count,
        "dominant_state": states.most_common(1)[0][0] if states else "",
        "dominant_action": actions.most_common(1)[0][0] if actions else "",
        "state_counts": ";".join(f"{k}:{v}" for k, v in states.most_common()),
        "action_counts": ";".join(f"{k}:{v}" for k, v in actions.most_common()),
        "target_left_events": event_counts.get("target_left", 0),
        "target_return_events": event_counts.get("target_return", 0),
        "persons_mean": f"{mean(persons):.3f}",
        "persons_max": max(persons) if persons else 0,
        "fps_mean": f"{mean(fps):.3f}",
        "fps_min": f"{min(fps):.3f}" if fps else "0.000",
        "fps_max": f"{max(fps):.3f}" if fps else "0.000",
        "best_score_mean": f"{mean(best):.4f}",
        "margin_mean": f"{mean(margin):.4f}",
        "belief_mean": f"{mean(belief):.4f}",
        "weak_ok_rate": f"{pct_true(s.identities, 'weak_ok'):.4f}",
        "mid_ok_rate": f"{pct_true(s.identities, 'mid_ok'):.4f}",
        "strong_ok_rate": f"{pct_true(s.identities, 'strong_ok'):.4f}",
        "bbox_default_ok_rate": f"{pct_true(s.identities, 'bbox_default_ok'):.4f}",
        "bbox_strict_ok_rate": f"{pct_true(s.identities, 'bbox_strict_ok'):.4f}",
        "prediction_ok_rate": f"{pct_true(s.identities, 'prediction_ok'):.4f}",
        "top_belief_reasons": ";".join(f"{k}:{v}" for k, v in reasons.most_common(5)),
    }


def classify_return_window(
    event_frame: int,
    frames: list[int],
    frame_by_id: dict[int, dict[str, str]],
    identity_by_id: dict[int, dict[str, str]],
    window_frames: int,
) -> str:
    window = [
        (f, frame_by_id.get(f, {}), identity_by_id.get(f, {}))
        for f in frames
        if event_frame <= f <= event_frame + window_frames
    ]
    if not window:
        return "no_window_rows"
    if any(fr.get("follow_state") == "STOP" for _, fr, _ in window[:3]):
        return "hard_stop_before_return"

    high_belief_bbox_failed = any(
        safe_float(ir.get("target_belief")) >= 0.75
        and ir.get("bbox_default_ok") != "1"
        and ir.get("bbox_strict_ok") != "1"
        for _, _, ir in window
    )
    if high_belief_bbox_failed:
        return "belief_high_bbox_failed"

    low_reid = all(
        safe_float(ir.get("best_score")) < 0.75 or safe_float(ir.get("margin")) < 0.03
        for _, _, ir in window
        if ir
    )
    if low_reid:
        return "reid_low_or_margin_low"

    switch_penalty = any(
        "switchPenalty=0.12" in (ir.get("belief_reason") or "")
        or safe_int(ir.get("candidate_switch_count")) > 0
        for _, _, ir in window
    )
    if switch_penalty:
        return "candidate_switch_penalty"

    return "recovered_or_mixed"


def collect_crop_refs(
    session_dir: Path,
    event_frame: int,
    frames: list[int],
    identity_by_id: dict[int, dict[str, str]],
    window_frames: int,
    limit: int = 6,
) -> tuple[str, str]:
    refs = []
    qualities = []
    for frame in frames:
        if frame < event_frame or frame > event_frame + window_frames:
            continue
        ir = identity_by_id.get(frame, {})
        for field in ("locked_crop_path", "suspected_crop_path", "best_reid_crop_path"):
            path = resolve_rel(session_dir, ir.get(field, ""))
            if path is None:
                continue
            rel = path.relative_to(session_dir).as_posix()
            if rel not in refs:
                refs.append(rel)
                qualities.append(f"{rel}:{crop_quality_flags(path)}")
        if len(refs) >= limit:
            break
    return ";".join(refs[:limit]), ";".join(qualities[:limit])


def analyze_events(s: SessionData, window_frames: int) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    event_rows = []
    recovery_rows = []
    frame_by_id = s.frame_by_id
    identity_by_id = s.identity_by_id
    frames = s.sorted_frames

    previous_left_frame: int | None = None
    for e in s.events:
        event_type = e.get("event_type", "")
        event_frame = safe_int(e.get("frame_id"))
        if event_type == "target_left":
            previous_left_frame = event_frame
        if event_type not in {"target_left", "target_return"}:
            continue

        nearest = nearest_at_or_after(frames, event_frame)
        fr = frame_by_id.get(nearest, {}) if nearest is not None else {}
        ir = identity_by_id.get(nearest, {}) if nearest is not None else {}
        crop_refs, crop_quality = collect_crop_refs(
            s.session_dir, event_frame, frames, identity_by_id, window_frames
        )
        category = ""
        if event_type == "target_return":
            category = classify_return_window(
                event_frame, frames, frame_by_id, identity_by_id, window_frames
            )

        event_rows.append(
            {
                "session_id": s.session_id,
                "event_type": event_type,
                "event_frame": event_frame,
                "nearest_frame": nearest if nearest is not None else "",
                "frames_since_left": event_frame - previous_left_frame
                if event_type == "target_return" and previous_left_frame is not None
                else "",
                "category": category,
                "follow_state": fr.get("follow_state", ""),
                "selected_action": fr.get("selected_action", ""),
                "num_persons": fr.get("num_persons", ""),
                "track_id": ir.get("track_id", ""),
                "locked_track_id": ir.get("locked_track_id", ""),
                "suspected_track_id": ir.get("suspected_track_id", ""),
                "best_score": ir.get("best_score", ""),
                "second_score": ir.get("second_score", ""),
                "margin": ir.get("margin", ""),
                "target_belief": ir.get("target_belief", ""),
                "bbox_default_ok": ir.get("bbox_default_ok", ""),
                "bbox_strict_ok": ir.get("bbox_strict_ok", ""),
                "prediction_ok": ir.get("prediction_ok", ""),
                "candidate_switch_count": ir.get("candidate_switch_count", ""),
                "belief_reason": ir.get("belief_reason", ""),
                "crop_refs": crop_refs,
                "crop_quality_flags": crop_quality,
            }
        )

        if event_type != "target_return":
            continue

        first_reacquire = first_after(
            frames,
            frame_by_id,
            identity_by_id,
            event_frame,
            lambda fr2, _: fr2.get("follow_state") == "REACQUIRE_TARGET",
            window_frames,
        )
        first_follow = first_after(
            frames,
            frame_by_id,
            identity_by_id,
            event_frame,
            lambda fr2, _: fr2.get("follow_state") in {"FOLLOW", "FOLLOW_CAUTION"},
            window_frames,
        )
        first_stop = first_after(
            frames,
            frame_by_id,
            identity_by_id,
            event_frame,
            lambda fr2, _: fr2.get("follow_state") == "STOP",
            window_frames,
        )
        first_belief = first_after(
            frames,
            frame_by_id,
            identity_by_id,
            event_frame,
            lambda _, ir2: safe_float(ir2.get("target_belief")) >= 0.75,
            window_frames,
        )
        first_bbox_default = first_after(
            frames,
            frame_by_id,
            identity_by_id,
            event_frame,
            lambda _, ir2: ir2.get("bbox_default_ok") == "1",
            window_frames,
        )
        recovery_rows.append(
            {
                "session_id": s.session_id,
                "event_frame": event_frame,
                "category": category,
                "first_reacquire_frame": first_reacquire or "",
                "frames_to_reacquire": first_reacquire - event_frame
                if first_reacquire is not None
                else "",
                "first_follow_frame": first_follow or "",
                "frames_to_follow": first_follow - event_frame if first_follow is not None else "",
                "first_stop_frame": first_stop or "",
                "frames_to_stop": first_stop - event_frame if first_stop is not None else "",
                "first_belief_ge_075_frame": first_belief or "",
                "frames_to_belief_ge_075": first_belief - event_frame
                if first_belief is not None
                else "",
                "first_bbox_default_ok_frame": first_bbox_default or "",
                "frames_to_bbox_default_ok": first_bbox_default - event_frame
                if first_bbox_default is not None
                else "",
                "crop_refs": crop_refs,
                "crop_quality_flags": crop_quality,
            }
        )

    return event_rows, recovery_rows


def gallery_quality_rows(sessions: list[SessionData]) -> list[dict[str, object]]:
    rows = []
    for s in sessions:
        for path in sorted((s.session_dir / "gallery").glob("*.jpg")):
            shape = image_shape(path)
            rows.append(
                {
                    "session_id": s.session_id,
                    "gallery_file": path.relative_to(s.session_dir).as_posix(),
                    "width": shape[0] if shape else "",
                    "height": shape[1] if shape else "",
                    "quality_flags": crop_quality_flags(path),
                }
            )
    return rows


def build_case_report(
    sessions: list[SessionData],
    session_rows: list[dict[str, object]],
    event_rows: list[dict[str, object]],
    recovery_rows: list[dict[str, object]],
    output_path: Path,
) -> None:
    by_category: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in recovery_rows:
        by_category[str(row.get("category", ""))].append(row)

    lines = [
        "# CartFollow Diagnostic Case Report",
        "",
        "## Summary",
        "",
        f"- Sessions analyzed: {len(sessions)}",
        f"- Target return events: {len(recovery_rows)}",
        "- This report is generated from logged diagnostics only; no strategy thresholds were changed.",
        "",
        "## Session Overview",
        "",
    ]
    for row in session_rows:
        lines.append(
            f"- `{row['session_id']}`: frames={row['frame_rows']}, events={row['event_rows']}, "
            f"dominant_state={row['dominant_state']}, dominant_action={row['dominant_action']}, "
            f"best_mean={row['best_score_mean']}, belief_mean={row['belief_mean']}, "
            f"bbox_default_rate={row['bbox_default_ok_rate']}"
        )
    lines.extend(["", "## Return Event Classification", ""])
    for category, rows in sorted(by_category.items()):
        lines.append(f"### {category or 'uncategorized'}")
        lines.append("")
        for row in rows:
            lines.append(
                f"- `{row['session_id']}` return frame `{row['event_frame']}`: "
                f"to_reacquire={row['frames_to_reacquire'] or '-'}, "
                f"to_follow={row['frames_to_follow'] or '-'}, "
                f"to_stop={row['frames_to_stop'] or '-'}, "
                f"to_belief075={row['frames_to_belief_ge_075'] or '-'}, "
                f"to_bbox_default={row['frames_to_bbox_default_ok'] or '-'}"
            )
            if row.get("crop_refs"):
                lines.append(f"  - crops: `{row['crop_refs']}`")
            if row.get("crop_quality_flags"):
                lines.append(f"  - crop_quality: `{row['crop_quality_flags']}`")
        lines.append("")

    lines.extend(
        [
            "## Preliminary Findings",
            "",
            "- `hard_stop_before_return` means the state machine already entered terminal STOP, so later target return cannot recover without restart.",
            "- `belief_high_bbox_failed` means ReID/belief is not the bottleneck; bbox continuity or prediction gate is blocking recovery.",
            "- `crop_quality_bad` should be verified manually from listed crop paths, especially landscape/rotated gallery snapshots and candidate crops with large background regions.",
            "",
            "## Recommended Next Check",
            "",
            "Inspect whether Android ReID uses crops in the same orientation as the diagnostic gallery/crops. If yes, prioritize upright crop normalization before tuning ReID or belief thresholds.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Human Cart Simulator diagnostic sessions.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Diagnostic session root directory.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Analysis output directory.")
    parser.add_argument(
        "--sessions",
        default="",
        help="Comma-separated session directory names. Empty means all sessions.",
    )
    parser.add_argument("--window-frames", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.input)
    output = Path(args.output)
    if not root.exists():
        raise FileNotFoundError(f"Diagnostic root not found: {root}")

    selected = {s.strip() for s in args.sessions.split(",") if s.strip()}
    session_dirs = sorted([p for p in root.iterdir() if p.is_dir()])
    if selected:
        session_dirs = [p for p in session_dirs if p.name in selected]
    if not session_dirs:
        raise RuntimeError("No diagnostic sessions found.")

    sessions = [load_session(p) for p in session_dirs]
    session_rows = [summarize_session(s) for s in sessions]
    event_rows: list[dict[str, object]] = []
    recovery_rows: list[dict[str, object]] = []
    for session in sessions:
        e_rows, r_rows = analyze_events(session, args.window_frames)
        event_rows.extend(e_rows)
        recovery_rows.extend(r_rows)

    output.mkdir(parents=True, exist_ok=True)
    write_csv(
        output / "diagnostic_session_summary.csv",
        session_rows,
        [
            "session_id",
            "created_at",
            "detector",
            "reid_available",
            "gallery_size",
            "frame_rows",
            "identity_rows",
            "event_rows",
            "crop_count",
            "gallery_count",
            "dominant_state",
            "dominant_action",
            "state_counts",
            "action_counts",
            "target_left_events",
            "target_return_events",
            "persons_mean",
            "persons_max",
            "fps_mean",
            "fps_min",
            "fps_max",
            "best_score_mean",
            "margin_mean",
            "belief_mean",
            "weak_ok_rate",
            "mid_ok_rate",
            "strong_ok_rate",
            "bbox_default_ok_rate",
            "bbox_strict_ok_rate",
            "prediction_ok_rate",
            "top_belief_reasons",
        ],
    )
    write_csv(
        output / "diagnostic_event_windows.csv",
        event_rows,
        [
            "session_id",
            "event_type",
            "event_frame",
            "nearest_frame",
            "frames_since_left",
            "category",
            "follow_state",
            "selected_action",
            "num_persons",
            "track_id",
            "locked_track_id",
            "suspected_track_id",
            "best_score",
            "second_score",
            "margin",
            "target_belief",
            "bbox_default_ok",
            "bbox_strict_ok",
            "prediction_ok",
            "candidate_switch_count",
            "belief_reason",
            "crop_refs",
            "crop_quality_flags",
        ],
    )
    write_csv(
        output / "diagnostic_recovery_summary.csv",
        recovery_rows,
        [
            "session_id",
            "event_frame",
            "category",
            "first_reacquire_frame",
            "frames_to_reacquire",
            "first_follow_frame",
            "frames_to_follow",
            "first_stop_frame",
            "frames_to_stop",
            "first_belief_ge_075_frame",
            "frames_to_belief_ge_075",
            "first_bbox_default_ok_frame",
            "frames_to_bbox_default_ok",
            "crop_refs",
            "crop_quality_flags",
        ],
    )
    write_csv(
        output / "diagnostic_gallery_quality.csv",
        gallery_quality_rows(sessions),
        ["session_id", "gallery_file", "width", "height", "quality_flags"],
    )
    build_case_report(
        sessions,
        session_rows,
        event_rows,
        recovery_rows,
        output / "diagnostic_case_report.md",
    )

    print(f"[INFO] sessions = {len(sessions)}")
    print(f"[INFO] target_return_events = {len(recovery_rows)}")
    print(f"[INFO] output = {output.resolve()}")
    categories = Counter(str(row.get("category", "")) for row in recovery_rows)
    print("[INFO] categories:")
    for key, count in categories.most_common():
        print(f"  {key}: {count}")


if __name__ == "__main__":
    main()
