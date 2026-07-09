"""Score candidate short-motion traversability from grayscale depth maps.

This script is intentionally PC-only. It does not try to recognize corridor
topology. Instead, it evaluates whether a small candidate motion envelope looks
safe enough to test cautiously, using Depth Anything V2 grayscale outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np


CANDIDATE_ACTIONS = (
    "SHORT_FORWARD_CAUTION",
    "LEFT_ARC_CAUTION",
    "RIGHT_ARC_CAUTION",
)
VALID_EXPECTED_VERDICTS = {"ALLOW_CAUTION", "VETO_STOP", "UNCLEAR", "REVIEW"}


@dataclass
class Label:
    expected_verdict: str
    label_confidence: str
    note: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score cautious candidate-motion traversability from grayscale depth maps."
    )
    parser.add_argument("--depth-dir", required=True, type=Path, help="Directory containing grayscale depth PNG files.")
    parser.add_argument("--input-root", required=True, type=Path, help="Root containing scene subfolders with source images.")
    parser.add_argument("--labels", required=True, type=Path, help="Manual traversability label CSV path.")
    parser.add_argument("--outdir", required=True, type=Path, help="Output directory for CSV, overlays, and summary JSON.")
    parser.add_argument("--roi-y-start", type=float, default=0.40, help="Top of motion ROI as a fraction of image height.")
    parser.add_argument("--roi-y-end", type=float, default=0.95, help="Bottom of motion ROI as a fraction of image height.")
    return parser.parse_args()


def iter_image_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}:
            yield path


def load_scene_map(input_root: Path) -> Dict[str, str]:
    scene_by_image: Dict[str, str] = {}
    for path in iter_image_files(input_root):
        scene_by_image[path.stem] = path.parent.name
    return scene_by_image


def load_labels(path: Path) -> Dict[Tuple[str, str], Label]:
    labels: Dict[Tuple[str, str], Label] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        required = {"image", "scene", "candidate_action", "expected_verdict", "label_confidence", "note"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Label CSV missing columns: {sorted(missing)}")
        for row in reader:
            image = row["image"].strip()
            action = row["candidate_action"].strip().upper()
            expected = row["expected_verdict"].strip().upper()
            if action not in CANDIDATE_ACTIONS:
                raise ValueError(f"Invalid candidate_action for {image}: {action}")
            if expected not in VALID_EXPECTED_VERDICTS:
                raise ValueError(f"Invalid expected_verdict for {image}/{action}: {expected}")
            labels[(image, action)] = Label(
                expected_verdict=expected,
                label_confidence=row["label_confidence"].strip(),
                note=row["note"].strip(),
            )
    return labels


def candidate_polygon(action: str, width: int, height: int, y_start: float, y_end: float) -> np.ndarray:
    y0 = int(y_start * height)
    y1 = int(y_end * height)
    cx = width * 0.50

    if action == "SHORT_FORWARD_CAUTION":
        points = [
            (int(cx - width * 0.11), y0),
            (int(cx + width * 0.11), y0),
            (int(cx + width * 0.25), y1),
            (int(cx - width * 0.25), y1),
        ]
    elif action == "LEFT_ARC_CAUTION":
        points = [
            (int(width * 0.20), y0),
            (int(width * 0.46), y0),
            (int(width * 0.57), y1),
            (int(width * 0.08), y1),
        ]
    elif action == "RIGHT_ARC_CAUTION":
        points = [
            (int(width * 0.54), y0),
            (int(width * 0.80), y0),
            (int(width * 0.92), y1),
            (int(width * 0.43), y1),
        ]
    else:
        raise ValueError(f"Unknown candidate action: {action}")

    return np.array(points, dtype=np.int32)


def polygon_mask(shape: Tuple[int, int], polygon: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 1)
    return mask.astype(bool)


def score_candidate(depth_gray: np.ndarray, action: str, y_start: float, y_end: float) -> Dict[str, object]:
    height, width = depth_gray.shape
    near = depth_gray.astype(np.float32) / 255.0
    far = 1.0 - near

    polygon = candidate_polygon(action, width, height, y_start, y_end)
    mask = polygon_mask(depth_gray.shape, polygon)
    envelope_far = far[mask]
    envelope_near = near[mask]

    y_bottom = int((y_end - 0.15) * height)
    bottom_mask = mask.copy()
    bottom_mask[: max(0, y_bottom), :] = False
    bottom_near = near[bottom_mask] if bottom_mask.any() else envelope_near

    vertical_samples: List[float] = []
    ys = np.linspace(int(y_start * height), int(y_end * height) - 1, num=8).astype(int)
    for y in ys:
        xs = np.where(mask[y])[0]
        if xs.size == 0:
            continue
        band = far[max(0, y - 2) : min(height, y + 3), xs.min() : xs.max() + 1]
        if band.size:
            vertical_samples.append(float(np.median(band)))
    floor_continuity = float(np.mean(vertical_samples)) if vertical_samples else 0.0

    open_score = float(
        0.45 * np.median(envelope_far)
        + 0.20 * np.percentile(envelope_far, 75)
        + 0.20 * (envelope_far > 0.55).mean()
        + 0.15 * floor_continuity
    )
    near_risk = float((envelope_near > 0.65).mean())
    bottom_near_risk = float((bottom_near > 0.60).mean())
    confidence = float(
        min(
            1.0,
            abs(open_score - 0.32) * 1.2
            + abs(0.28 - near_risk) * 0.7
            + abs(0.36 - bottom_near_risk) * 0.5,
        )
    )

    # The lower image band is often nearby floor, not necessarily an obstacle.
    # Keep bottom_near_risk as a diagnostic signal, but do not hard-veto on it
    # until floor/obstacle separation is available.
    if near_risk >= 0.44 and open_score <= 0.44:
        predicted_verdict = "VETO_STOP"
        reason = "motion_envelope_near_risk_high"
    elif open_score >= 0.50 and near_risk <= 0.38:
        predicted_verdict = "ALLOW_CAUTION"
        reason = "envelope_open_and_near_risk_low"
    else:
        predicted_verdict = "UNCLEAR"
        reason = "insufficient_margin"

    return {
        "candidate_action": action,
        "open_score": round(open_score, 4),
        "near_risk": round(near_risk, 4),
        "bottom_near_risk": round(bottom_near_risk, 4),
        "floor_continuity_score": round(floor_continuity, 4),
        "confidence": round(confidence, 4),
        "predicted_verdict": predicted_verdict,
        "risk_reason": reason,
        "polygon": polygon,
    }


def verdict_match(predicted: str, expected: str) -> Optional[bool]:
    if expected in {"REVIEW", "UNCLEAR"}:
        return None
    return predicted == expected


def draw_overlay(depth_gray: np.ndarray, row: Dict[str, object], polygon: np.ndarray, out_path: Path) -> None:
    vis = cv2.cvtColor(depth_gray, cv2.COLOR_GRAY2BGR)
    color_by_verdict = {
        "ALLOW_CAUTION": (60, 190, 60),
        "VETO_STOP": (40, 40, 230),
        "UNCLEAR": (0, 190, 230),
    }
    color = color_by_verdict.get(str(row["predicted_verdict"]), (220, 220, 220))
    fill = vis.copy()
    cv2.fillPoly(fill, [polygon], color)
    vis = cv2.addWeighted(fill, 0.28, vis, 0.72, 0)
    cv2.polylines(vis, [polygon], True, color, 4, cv2.LINE_AA)

    lines = [
        f"{row['image']} | {row['candidate_action']}",
        f"pred={row['predicted_verdict']} expected={row['expected_verdict']} match={row['label_match']}",
        f"open={row['open_score']:.3f} near={row['near_risk']:.3f} bottom={row['bottom_near_risk']:.3f}",
        f"reason={row['risk_reason']}",
    ]
    y = 36
    for line in lines:
        cv2.putText(vis, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(vis, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (0, 0, 0), 2, cv2.LINE_AA)
        y += 34
    cv2.imwrite(str(out_path), vis)


def summarize(rows: List[Dict[str, object]]) -> Dict[str, object]:
    per_action: Dict[str, object] = {}
    for action in CANDIDATE_ACTIONS:
        subset = [row for row in rows if row["candidate_action"] == action]
        labeled = [row for row in subset if row["label_match"] in {"true", "false"}]
        matched = [row for row in labeled if row["label_match"] == "true"]
        verdict_counts = {
            verdict: len([row for row in subset if row["predicted_verdict"] == verdict])
            for verdict in ("ALLOW_CAUTION", "VETO_STOP", "UNCLEAR")
        }
        per_action[action] = {
            "rows": len(subset),
            "labeled_rows": len(labeled),
            "label_match_rate": round(len(matched) / len(labeled), 4) if labeled else None,
            "avg_open_score": round(float(np.mean([row["open_score"] for row in subset])), 4),
            "avg_near_risk": round(float(np.mean([row["near_risk"] for row in subset])), 4),
            "avg_bottom_near_risk": round(float(np.mean([row["bottom_near_risk"] for row in subset])), 4),
            "predicted_verdict_counts": verdict_counts,
        }

    per_scene: Dict[str, object] = {}
    for scene in sorted({str(row["scene"]) for row in rows}):
        subset = [row for row in rows if row["scene"] == scene]
        per_scene[scene] = {
            "rows": len(subset),
            "images": len({row["image"] for row in subset}),
            "predicted_verdict_counts": {
                verdict: len([row for row in subset if row["predicted_verdict"] == verdict])
                for verdict in ("ALLOW_CAUTION", "VETO_STOP", "UNCLEAR")
            },
        }

    labeled_all = [row for row in rows if row["label_match"] in {"true", "false"}]
    matched_all = [row for row in labeled_all if row["label_match"] == "true"]
    return {
        "total_rows": len(rows),
        "total_images": len({row["image"] for row in rows}),
        "candidate_actions": list(CANDIDATE_ACTIONS),
        "labeled_rows": len(labeled_all),
        "overall_label_match_rate": round(len(matched_all) / len(labeled_all), 4) if labeled_all else None,
        "per_action": per_action,
        "per_scene": per_scene,
    }


def main() -> None:
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    overlay_dir = args.outdir / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    scene_by_image = load_scene_map(args.input_root)
    labels = load_labels(args.labels)

    rows: List[Dict[str, object]] = []
    for depth_path in sorted(args.depth_dir.glob("*.png")):
        depth = cv2.imread(str(depth_path), cv2.IMREAD_GRAYSCALE)
        if depth is None:
            raise ValueError(f"Could not read depth image: {depth_path}")
        image = depth_path.stem
        scene = scene_by_image.get(image, "unknown")
        for action in CANDIDATE_ACTIONS:
            score = score_candidate(depth, action, args.roi_y_start, args.roi_y_end)
            polygon = score.pop("polygon")
            label = labels.get(
                (image, action),
                Label(expected_verdict="REVIEW", label_confidence="todo", note="manual review required"),
            )
            match = verdict_match(str(score["predicted_verdict"]), label.expected_verdict)
            row: Dict[str, object] = {
                "image": image,
                "scene": scene,
                **score,
                "expected_verdict": label.expected_verdict,
                "label_confidence": label.label_confidence,
                "label_match": "na" if match is None else str(match).lower(),
                "note": label.note,
            }
            rows.append(row)
            overlay_name = f"{image}_{action.lower()}.png"
            draw_overlay(depth, row, polygon, overlay_dir / overlay_name)

    csv_fields = [
        "image",
        "scene",
        "candidate_action",
        "open_score",
        "near_risk",
        "bottom_near_risk",
        "floor_continuity_score",
        "confidence",
        "predicted_verdict",
        "risk_reason",
        "expected_verdict",
        "label_confidence",
        "label_match",
        "note",
    ]
    with (args.outdir / "traversability_scores.csv").open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(rows)

    with (args.outdir / "summary.json").open("w", encoding="utf-8") as fp:
        json.dump(summarize(rows), fp, indent=2, ensure_ascii=False)

    print(f"Wrote {len(rows)} rows to {args.outdir / 'traversability_scores.csv'}")
    print(f"Wrote overlays to {overlay_dir}")
    print(f"Wrote summary to {args.outdir / 'summary.json'}")


if __name__ == "__main__":
    main()
