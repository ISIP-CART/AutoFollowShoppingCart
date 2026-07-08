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
DEFAULT_OUTPUT = Path("outputs/cartfollow_diagnostics_analysis/current")
FAST_RECOVERY_MS = 5000


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
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else 0.0


def mean_nonempty(values: Iterable[object]) -> str:
    vals = [safe_float(v) for v in values if v not in ("", None)]
    return f"{mean(vals):.3f}" if vals else ""


def pct_true(rows: list[dict[str, str]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get(field) == "1") / len(rows)


def csv_join(values: Iterable[object]) -> str:
    return ";".join(str(v) for v in values if v not in ("", None))


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


def gallery_role(path: Path) -> str:
    name = path.name
    if "gallery_candidate" in name:
        return "gallery_candidate"
    if "confirmed_snapshot" in name:
        return "confirmed_snapshot"
    return "other"


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


@dataclass
class AnalysisResult:
    label: str
    root: Path
    output: Path | None
    sessions: list[SessionData]
    session_rows: list[dict[str, object]]
    event_rows: list[dict[str, object]]
    recovery_rows: list[dict[str, object]]
    gallery_rows: list[dict[str, object]]


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


def row_timestamp_ms(row: dict[str, str]) -> int | None:
    if not row:
        return None
    value = row.get("timestamp_ms")
    if value in ("", None):
        return None
    return safe_int(value)


def delta_ms(event_row: dict[str, str], target_frame: int | None, frame_by_id: dict[int, dict[str, str]]) -> str:
    if target_frame is None:
        return ""
    event_ts = row_timestamp_ms(event_row)
    target_ts = row_timestamp_ms(frame_by_id.get(target_frame, {}))
    if event_ts is None or target_ts is None:
        return ""
    return str(max(0, target_ts - event_ts))


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
    gallery_files = list((s.session_dir / "gallery").glob("*.jpg"))
    gallery_candidates = [p for p in gallery_files if gallery_role(p) == "gallery_candidate"]
    return {
        "session_id": s.session_id,
        "created_at": s.info.get("created_at", ""),
        "detector": s.info.get("detector", ""),
        "reid_available": s.info.get("reid_available", ""),
        "reid_crop_upright": s.info.get("reid_crop_upright", ""),
        "sensor_orientation": s.info.get("sensor_orientation", ""),
        "gallery_size": s.info.get("gallery_size", ""),
        "frame_rows": len(s.frames),
        "identity_rows": len(s.identities),
        "event_rows": len(s.events),
        "crop_count": crop_count,
        "gallery_count": len(gallery_files),
        "gallery_candidate_count": len(gallery_candidates),
        "dominant_state": states.most_common(1)[0][0] if states else "",
        "dominant_action": actions.most_common(1)[0][0] if actions else "",
        "state_counts": csv_join(f"{k}:{v}" for k, v in states.most_common()),
        "action_counts": csv_join(f"{k}:{v}" for k, v in actions.most_common()),
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
        "top_belief_reasons": csv_join(f"{k}:{v}" for k, v in reasons.most_common(5)),
    }


def window_rows(
    event_frame: int,
    frames: list[int],
    frame_by_id: dict[int, dict[str, str]],
    identity_by_id: dict[int, dict[str, str]],
    window_frames: int,
) -> list[tuple[int, dict[str, str], dict[str, str]]]:
    return [
        (f, frame_by_id.get(f, {}), identity_by_id.get(f, {}))
        for f in frames
        if event_frame <= f <= event_frame + window_frames
    ]


def candidate_switch_in_window(rows: list[tuple[int, dict[str, str], dict[str, str]]]) -> bool:
    values = [safe_int(ir.get("candidate_switch_count")) for _, _, ir in rows if ir]
    switch_reason = any("switchPenalty=0.12" in (ir.get("belief_reason") or "") for _, _, ir in rows)
    if not values:
        return switch_reason
    return switch_reason or max(values) > min(values)


def classify_blockers(rows: list[tuple[int, dict[str, str], dict[str, str]]]) -> list[str]:
    flags = []
    if any(fr.get("follow_state") == "STOP" for _, fr, _ in rows[:3]):
        flags.append("hard_stop_before_return")
    if any("no_visible_track" in (ir.get("belief_reason") or "") for _, _, ir in rows[:5]):
        flags.append("no_visible_track")
    if any(
        safe_float(ir.get("target_belief")) >= 0.75
        and ir.get("bbox_default_ok") != "1"
        and ir.get("bbox_strict_ok") != "1"
        for _, _, ir in rows
    ):
        flags.append("belief_high_bbox_failed")

    first_belief_idx = next(
        (i for i, (_, _, ir) in enumerate(rows) if safe_float(ir.get("target_belief")) >= 0.75),
        None,
    )
    first_bbox_idx = next((i for i, (_, _, ir) in enumerate(rows) if ir.get("bbox_default_ok") == "1"), None)
    if first_belief_idx is not None and (first_bbox_idx is None or first_bbox_idx > first_belief_idx + 2):
        flags.append("bbox_gate_lag")

    valid_id_rows = [ir for _, _, ir in rows if ir]
    if valid_id_rows and all(
        safe_float(ir.get("best_score")) < 0.75 or safe_float(ir.get("margin")) < 0.03
        for ir in valid_id_rows
    ):
        flags.append("reid_low_or_margin_low")
    if candidate_switch_in_window(rows):
        flags.append("candidate_switch_penalty")
    return flags


def primary_blocker(flags: list[str]) -> str:
    for flag in [
        "hard_stop_before_return",
        "belief_high_bbox_failed",
        "bbox_gate_lag",
        "candidate_switch_penalty",
        "reid_low_or_margin_low",
        "no_visible_track",
    ]:
        if flag in flags:
            return flag
    return "none"


def outcome_from(first_follow: int | None, stopped_at_return: bool, event_frame: int, ms_to_follow: str) -> str:
    if stopped_at_return:
        return "hard_stop_before_return"
    if first_follow is None:
        return "not_recovered_in_window"
    if ms_to_follow and safe_int(ms_to_follow) <= FAST_RECOVERY_MS:
        return "recovered_fast"
    if not ms_to_follow and first_follow - event_frame <= 150:
        return "recovered_fast"
    return "recovered_slow"


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
    return csv_join(refs[:limit]), csv_join(qualities[:limit])


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
        rows = window_rows(event_frame, frames, frame_by_id, identity_by_id, window_frames)
        blockers = classify_blockers(rows) if event_type == "target_return" else []
        crop_refs, crop_quality = collect_crop_refs(s.session_dir, event_frame, frames, identity_by_id, window_frames)

        event_rows.append(
            {
                "session_id": s.session_id,
                "event_type": event_type,
                "event_frame": event_frame,
                "event_timestamp_ms": e.get("timestamp_ms", ""),
                "nearest_frame": nearest if nearest is not None else "",
                "frames_since_left": event_frame - previous_left_frame
                if event_type == "target_return" and previous_left_frame is not None
                else "",
                "blocker_flags": csv_join(blockers),
                "primary_blocker": primary_blocker(blockers) if blockers else "",
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

        ms_to_reacquire = delta_ms(e, first_reacquire, frame_by_id)
        ms_to_follow = delta_ms(e, first_follow, frame_by_id)
        ms_to_stop = delta_ms(e, first_stop, frame_by_id)
        ms_to_belief = delta_ms(e, first_belief, frame_by_id)
        ms_to_bbox = delta_ms(e, first_bbox_default, frame_by_id)
        outcome = outcome_from(first_follow, "hard_stop_before_return" in blockers, event_frame, ms_to_follow)

        recovery_rows.append(
            {
                "session_id": s.session_id,
                "event_frame": event_frame,
                "event_timestamp_ms": e.get("timestamp_ms", ""),
                "outcome": outcome,
                "blocker_flags": csv_join(blockers),
                "primary_blocker": primary_blocker(blockers),
                "first_reacquire_frame": first_reacquire or "",
                "frames_to_reacquire": first_reacquire - event_frame if first_reacquire is not None else "",
                "ms_to_reacquire": ms_to_reacquire,
                "first_follow_frame": first_follow or "",
                "frames_to_follow": first_follow - event_frame if first_follow is not None else "",
                "ms_to_follow": ms_to_follow,
                "first_stop_frame": first_stop or "",
                "frames_to_stop": first_stop - event_frame if first_stop is not None else "",
                "ms_to_stop": ms_to_stop,
                "first_belief_ge_075_frame": first_belief or "",
                "frames_to_belief_ge_075": first_belief - event_frame if first_belief is not None else "",
                "ms_to_belief_ge_075": ms_to_belief,
                "first_bbox_default_ok_frame": first_bbox_default or "",
                "frames_to_bbox_default_ok": first_bbox_default - event_frame if first_bbox_default is not None else "",
                "ms_to_bbox_default_ok": ms_to_bbox,
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
            role = gallery_role(path)
            rows.append(
                {
                    "session_id": s.session_id,
                    "gallery_file": path.relative_to(s.session_dir).as_posix(),
                    "role": role,
                    "is_reid_gallery_input": "1" if role == "gallery_candidate" else "0",
                    "width": shape[0] if shape else "",
                    "height": shape[1] if shape else "",
                    "quality_flags": crop_quality_flags(path),
                }
            )
    return rows


SESSION_FIELDS = [
    "session_id",
    "created_at",
    "detector",
    "reid_available",
    "reid_crop_upright",
    "sensor_orientation",
    "gallery_size",
    "frame_rows",
    "identity_rows",
    "event_rows",
    "crop_count",
    "gallery_count",
    "gallery_candidate_count",
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
]

EVENT_FIELDS = [
    "session_id",
    "event_type",
    "event_frame",
    "event_timestamp_ms",
    "nearest_frame",
    "frames_since_left",
    "blocker_flags",
    "primary_blocker",
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
]

RECOVERY_FIELDS = [
    "session_id",
    "event_frame",
    "event_timestamp_ms",
    "outcome",
    "blocker_flags",
    "primary_blocker",
    "first_reacquire_frame",
    "frames_to_reacquire",
    "ms_to_reacquire",
    "first_follow_frame",
    "frames_to_follow",
    "ms_to_follow",
    "first_stop_frame",
    "frames_to_stop",
    "ms_to_stop",
    "first_belief_ge_075_frame",
    "frames_to_belief_ge_075",
    "ms_to_belief_ge_075",
    "first_bbox_default_ok_frame",
    "frames_to_bbox_default_ok",
    "ms_to_bbox_default_ok",
    "crop_refs",
    "crop_quality_flags",
]

GALLERY_FIELDS = [
    "session_id",
    "gallery_file",
    "role",
    "is_reid_gallery_input",
    "width",
    "height",
    "quality_flags",
]


def build_case_report(result: AnalysisResult, output_path: Path) -> None:
    by_outcome: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in result.recovery_rows:
        by_outcome[str(row.get("outcome", ""))].append(row)

    lines = [
        "# CartFollow Diagnostic Case Report",
        "",
        "## Summary",
        "",
        f"- Label: `{result.label}`",
        f"- Root: `{result.root}`",
        f"- Sessions analyzed: {len(result.sessions)}",
        f"- Target return events: {len(result.recovery_rows)}",
        "- This report is generated from logged diagnostics only; no strategy thresholds were changed.",
        "",
        "## Session Overview",
        "",
    ]
    for row in result.session_rows:
        lines.append(
            f"- `{row['session_id']}`: frames={row['frame_rows']}, events={row['event_rows']}, "
            f"dominant_state={row['dominant_state']}, dominant_action={row['dominant_action']}, "
            f"best_mean={row['best_score_mean']}, belief_mean={row['belief_mean']}, "
            f"bbox_default_rate={row['bbox_default_ok_rate']}, upright={row['reid_crop_upright']}"
        )

    lines.extend(["", "## Return Outcomes", ""])
    for outcome, rows in sorted(by_outcome.items()):
        lines.append(f"### {outcome or 'uncategorized'}")
        lines.append("")
        for row in rows:
            lines.append(
                f"- `{row['session_id']}` return frame `{row['event_frame']}`: "
                f"blockers={row['blocker_flags'] or '-'}, "
                f"to_reacquire={row['ms_to_reacquire'] or '-'}ms, "
                f"to_follow={row['ms_to_follow'] or '-'}ms, "
                f"to_bbox={row['ms_to_bbox_default_ok'] or '-'}ms, "
                f"to_belief075={row['ms_to_belief_ge_075'] or '-'}ms"
            )
            if row.get("crop_refs"):
                lines.append(f"  - crops: `{row['crop_refs']}`")
            if row.get("crop_quality_flags"):
                lines.append(f"  - crop_quality: `{row['crop_quality_flags']}`")
        lines.append("")

    gallery_candidates = [r for r in result.gallery_rows if r.get("role") == "gallery_candidate"]
    landscape = [r for r in gallery_candidates if "landscape_or_rotated" in str(r.get("quality_flags", ""))]
    lines.extend(
        [
            "## Gallery Candidate Quality",
            "",
            f"- gallery_candidate_count={len(gallery_candidates)}",
            f"- landscape_or_rotated_count={len(landscape)}",
            "",
            "## Recommended Next Check",
            "",
            "Compare this report with the old/new comparison output before changing Android strategy thresholds.",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_sessions(root: Path, sessions_filter: set[str] | None = None) -> list[SessionData]:
    if not root.exists():
        raise FileNotFoundError(f"Diagnostic root not found: {root}")
    session_dirs = sorted([p for p in root.iterdir() if p.is_dir()])
    if sessions_filter:
        session_dirs = [p for p in session_dirs if p.name in sessions_filter]
    if not session_dirs:
        raise RuntimeError(f"No diagnostic sessions found in {root}")
    return [load_session(p) for p in session_dirs]


def analyze_root(
    root: Path,
    output: Path | None,
    label: str,
    window_frames: int,
    sessions_filter: set[str] | None = None,
) -> AnalysisResult:
    sessions = load_sessions(root, sessions_filter)
    session_rows = [summarize_session(s) for s in sessions]
    event_rows: list[dict[str, object]] = []
    recovery_rows: list[dict[str, object]] = []
    for session in sessions:
        e_rows, r_rows = analyze_events(session, window_frames)
        event_rows.extend(e_rows)
        recovery_rows.extend(r_rows)
    gallery_rows = gallery_quality_rows(sessions)
    result = AnalysisResult(label, root, output, sessions, session_rows, event_rows, recovery_rows, gallery_rows)
    if output is not None:
        write_analysis_outputs(result)
    return result


def write_analysis_outputs(result: AnalysisResult) -> None:
    assert result.output is not None
    result.output.mkdir(parents=True, exist_ok=True)
    write_csv(result.output / "diagnostic_session_summary.csv", result.session_rows, SESSION_FIELDS)
    write_csv(result.output / "diagnostic_event_windows.csv", result.event_rows, EVENT_FIELDS)
    write_csv(result.output / "diagnostic_recovery_summary.csv", result.recovery_rows, RECOVERY_FIELDS)
    write_csv(result.output / "diagnostic_gallery_quality.csv", result.gallery_rows, GALLERY_FIELDS)
    build_case_report(result, result.output / "diagnostic_case_report.md")


def parse_compare_roots(value: str) -> dict[str, Path]:
    roots = {}
    if not value.strip():
        return roots
    for item in value.split(","):
        if "=" not in item:
            raise ValueError(f"Invalid --compare-roots item: {item}")
        label, path = item.split("=", 1)
        label = label.strip()
        path = path.strip()
        if not label or not path:
            raise ValueError(f"Invalid --compare-roots item: {item}")
        roots[label] = Path(path)
    if len(roots) < 2:
        raise ValueError("--compare-roots requires at least two label=path entries")
    return roots


def compare_summary_row(result: AnalysisResult) -> dict[str, object]:
    recoveries = result.recovery_rows
    outcomes = Counter(str(r.get("outcome", "")) for r in recoveries)
    blockers = Counter()
    for row in recoveries:
        for flag in str(row.get("blocker_flags", "")).split(";"):
            if flag:
                blockers[flag] += 1
    gallery_candidates = [r for r in result.gallery_rows if r.get("role") == "gallery_candidate"]
    candidate_landscape = [
        r for r in gallery_candidates if "landscape_or_rotated" in str(r.get("quality_flags", ""))
    ]
    candidate_ok = [r for r in gallery_candidates if r.get("quality_flags") == "ok"]
    recovered = outcomes.get("recovered_fast", 0) + outcomes.get("recovered_slow", 0)
    identities = [r for s in result.sessions for r in s.identities]
    return {
        "label": result.label,
        "root": result.root.as_posix(),
        "session_count": len(result.sessions),
        "target_return_count": len(recoveries),
        "recovered_count": recovered,
        "recovered_rate": f"{(recovered / len(recoveries)):.4f}" if recoveries else "0.0000",
        "recovered_fast_count": outcomes.get("recovered_fast", 0),
        "recovered_slow_count": outcomes.get("recovered_slow", 0),
        "not_recovered_count": outcomes.get("not_recovered_in_window", 0),
        "hard_stop_count": outcomes.get("hard_stop_before_return", 0),
        "mean_ms_to_follow": mean_nonempty(r.get("ms_to_follow") for r in recoveries),
        "mean_ms_to_reacquire": mean_nonempty(r.get("ms_to_reacquire") for r in recoveries),
        "mean_ms_to_bbox_default": mean_nonempty(r.get("ms_to_bbox_default_ok") for r in recoveries),
        "mean_ms_to_belief075": mean_nonempty(r.get("ms_to_belief_ge_075") for r in recoveries),
        "best_score_mean": f"{mean(safe_float(r.get('best_score')) for r in identities):.4f}",
        "margin_mean": f"{mean(safe_float(r.get('margin')) for r in identities):.4f}",
        "belief_mean": f"{mean(safe_float(r.get('target_belief')) for r in identities):.4f}",
        "weak_ok_rate": f"{pct_true(identities, 'weak_ok'):.4f}",
        "mid_ok_rate": f"{pct_true(identities, 'mid_ok'):.4f}",
        "strong_ok_rate": f"{pct_true(identities, 'strong_ok'):.4f}",
        "bbox_default_ok_rate": f"{pct_true(identities, 'bbox_default_ok'):.4f}",
        "bbox_strict_ok_rate": f"{pct_true(identities, 'bbox_strict_ok'):.4f}",
        "prediction_ok_rate": f"{pct_true(identities, 'prediction_ok'):.4f}",
        "gallery_candidate_count": len(gallery_candidates),
        "gallery_candidate_landscape_rate": f"{(len(candidate_landscape) / len(gallery_candidates)):.4f}"
        if gallery_candidates
        else "0.0000",
        "gallery_candidate_ok_rate": f"{(len(candidate_ok) / len(gallery_candidates)):.4f}"
        if gallery_candidates
        else "0.0000",
        "blocker_counts": csv_join(f"{k}:{v}" for k, v in blockers.most_common()),
        "outcome_counts": csv_join(f"{k}:{v}" for k, v in outcomes.most_common()),
    }


COMPARE_SUMMARY_FIELDS = [
    "label",
    "root",
    "session_count",
    "target_return_count",
    "recovered_count",
    "recovered_rate",
    "recovered_fast_count",
    "recovered_slow_count",
    "not_recovered_count",
    "hard_stop_count",
    "mean_ms_to_follow",
    "mean_ms_to_reacquire",
    "mean_ms_to_bbox_default",
    "mean_ms_to_belief075",
    "best_score_mean",
    "margin_mean",
    "belief_mean",
    "weak_ok_rate",
    "mid_ok_rate",
    "strong_ok_rate",
    "bbox_default_ok_rate",
    "bbox_strict_ok_rate",
    "prediction_ok_rate",
    "gallery_candidate_count",
    "gallery_candidate_landscape_rate",
    "gallery_candidate_ok_rate",
    "blocker_counts",
    "outcome_counts",
]


RETURN_COMPARISON_FIELDS = [
    "label",
    "session_id",
    "event_frame",
    "outcome",
    "blocker_flags",
    "primary_blocker",
    "frames_to_reacquire",
    "ms_to_reacquire",
    "frames_to_follow",
    "ms_to_follow",
    "frames_to_stop",
    "ms_to_stop",
    "frames_to_belief_ge_075",
    "ms_to_belief_ge_075",
    "frames_to_bbox_default_ok",
    "ms_to_bbox_default_ok",
    "crop_refs",
    "crop_quality_flags",
]


def write_compare_outputs(results: list[AnalysisResult], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    summary_rows = [compare_summary_row(r) for r in results]
    write_csv(output / "diagnostic_compare_summary.csv", summary_rows, COMPARE_SUMMARY_FIELDS)

    return_rows = []
    for result in results:
        for row in result.recovery_rows:
            new_row = dict(row)
            new_row["label"] = result.label
            return_rows.append(new_row)
    write_csv(output / "diagnostic_return_comparison.csv", return_rows, RETURN_COMPARISON_FIELDS)
    build_upright_report(results, summary_rows, output / "diagnostic_upright_effect_report.md")


def build_upright_report(
    results: list[AnalysisResult], summary_rows: list[dict[str, object]], output_path: Path
) -> None:
    lines = [
        "# CartFollow Upright Crop Effect Report",
        "",
        "## Summary",
        "",
        "- This report compares diagnostic roots without changing Android thresholds or strategy.",
        "- `gallery_candidate` rows are treated as ReID gallery inputs; `confirmed_snapshot` is reported separately and not counted as gallery input.",
        "",
        "## Root Comparison",
        "",
    ]
    for row in summary_rows:
        lines.append(
            f"- `{row['label']}`: returns={row['target_return_count']}, "
            f"recovered_rate={row['recovered_rate']}, mean_follow_ms={row['mean_ms_to_follow'] or '-'}, "
            f"best_mean={row['best_score_mean']}, margin_mean={row['margin_mean']}, "
            f"bbox_default_rate={row['bbox_default_ok_rate']}, "
            f"gallery_landscape_rate={row['gallery_candidate_landscape_rate']}, "
            f"blockers={row['blocker_counts'] or '-'}"
        )

    lines.extend(["", "## Return Outcomes", ""])
    for result in results:
        outcomes = Counter(str(r.get("outcome", "")) for r in result.recovery_rows)
        blockers = Counter()
        for row in result.recovery_rows:
            for flag in str(row.get("blocker_flags", "")).split(";"):
                if flag:
                    blockers[flag] += 1
        lines.append(f"### {result.label}")
        lines.append(f"- outcomes: `{csv_join(f'{k}:{v}' for k, v in outcomes.most_common()) or '-'}`")
        lines.append(f"- blockers: `{csv_join(f'{k}:{v}' for k, v in blockers.most_common()) or '-'}`")
        slow = [
            r
            for r in result.recovery_rows
            if r.get("outcome") in {"recovered_slow", "not_recovered_in_window"}
        ][:5]
        for row in slow:
            lines.append(
                f"  - `{row['session_id']}` frame `{row['event_frame']}` "
                f"outcome={row['outcome']} blockers={row['blocker_flags'] or '-'} "
                f"follow_ms={row['ms_to_follow'] or '-'} bbox_ms={row['ms_to_bbox_default_ok'] or '-'}"
            )
        lines.append("")

    lines.extend(
        [
            "## Interpretation Checklist",
            "",
            "- If new `gallery_candidate_landscape_rate` is near 0 while recovery remains slow, upright crop fixed input orientation but not the recovery gate.",
            "- If `bbox_gate_lag` and `belief_high_bbox_failed` remain dominant, the next Android plan should focus on state-dependent bbox/prediction gates.",
            "- If `candidate_switch_penalty` grows, the next Android plan should focus on track association and locked-track protection.",
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
    parser.add_argument(
        "--compare-roots",
        default="",
        help="Comma-separated label=path roots, e.g. old=images/cartfollow_diagnostics_old,new=images/cartfollow_diagnostics.",
    )
    parser.add_argument("--window-frames", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = {s.strip() for s in args.sessions.split(",") if s.strip()}
    sessions_filter = selected or None
    compare_roots = parse_compare_roots(args.compare_roots)
    output = Path(args.output)

    if compare_roots:
        results = [
            analyze_root(root, None, label, args.window_frames, sessions_filter)
            for label, root in compare_roots.items()
        ]
        write_compare_outputs(results, output)
        print(f"[INFO] compare_roots = {len(results)}")
        print(f"[INFO] output = {output.resolve()}")
        for result in results:
            outcomes = Counter(str(r.get("outcome", "")) for r in result.recovery_rows)
            print(f"[INFO] {result.label}: sessions={len(result.sessions)} returns={len(result.recovery_rows)}")
            for key, count in outcomes.most_common():
                print(f"  {key}: {count}")
        return

    result = analyze_root(Path(args.input), output, "current", args.window_frames, sessions_filter)
    print(f"[INFO] sessions = {len(result.sessions)}")
    print(f"[INFO] target_return_events = {len(result.recovery_rows)}")
    print(f"[INFO] output = {output.resolve()}")
    outcomes = Counter(str(row.get("outcome", "")) for row in result.recovery_rows)
    blockers = Counter()
    for row in result.recovery_rows:
        for flag in str(row.get("blocker_flags", "")).split(";"):
            if flag:
                blockers[flag] += 1
    print("[INFO] outcomes:")
    for key, count in outcomes.most_common():
        print(f"  {key}: {count}")
    print("[INFO] blockers:")
    for key, count in blockers.most_common():
        print(f"  {key}: {count}")


if __name__ == "__main__":
    main()
