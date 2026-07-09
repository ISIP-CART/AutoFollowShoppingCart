"""Compute first-pass passage scores from Depth Anything grayscale outputs.

This script is intentionally PC-only. It converts monocular relative depth
visualizations into an explainable PassageEvidence prototype for left / center
/ right local passage hypotheses.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import cv2
import numpy as np


ROI_NAMES = ("left", "center", "right")
VALID_LABELS = {"left", "center", "right", "blocked", "unclear"}


@dataclass
class Label:
    expected_opening: str
    label_confidence: str
    note: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score passage openings from grayscale depth maps.")
    parser.add_argument("--depth-dir", required=True, type=Path, help="Directory containing grayscale depth PNG files.")
    parser.add_argument("--input-root", required=True, type=Path, help="Root containing scene subfolders with source images.")
    parser.add_argument("--labels", required=True, type=Path, help="Manual label CSV path.")
    parser.add_argument("--outdir", required=True, type=Path, help="Output directory for CSV, overlays, and summary JSON.")
    parser.add_argument("--roi-y-start", type=float, default=0.40, help="Top of ROI band as a fraction of image height.")
    parser.add_argument("--roi-y-end", type=float, default=0.95, help="Bottom of ROI band as a fraction of image height.")
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


def load_labels(path: Path) -> Dict[str, Label]:
    labels: Dict[str, Label] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        required = {"image", "scene", "expected_opening", "label_confidence", "note"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Label CSV missing columns: {sorted(missing)}")
        for row in reader:
            image = row["image"].strip()
            expected = row["expected_opening"].strip().lower()
            if expected not in VALID_LABELS:
                raise ValueError(f"Invalid expected_opening for {image}: {expected}")
            labels[image] = Label(
                expected_opening=expected,
                label_confidence=row["label_confidence"].strip(),
                note=row["note"].strip(),
            )
    return labels


def score_depth(depth_gray: np.ndarray, roi_y_start: float, roi_y_end: float) -> Dict[str, float]:
    h, w = depth_gray.shape
    y0 = int(roi_y_start * h)
    y1 = int(roi_y_end * h)
    near = depth_gray.astype(np.float32) / 255.0
    far = 1.0 - near

    roi_bounds = {
        "left": (0, w // 3),
        "center": (w // 3, 2 * w // 3),
        "right": (2 * w // 3, w),
    }
    scores: Dict[str, float] = {}
    for name, (x0, x1) in roi_bounds.items():
        roi_far = far[y0:y1, x0:x1]
        roi_near = near[y0:y1, x0:x1]
        far_median = float(np.median(roi_far))
        far_p75 = float(np.percentile(roi_far, 75))
        free_area_ratio = float((roi_far > 0.55).mean())
        near_risk = float((roi_near > 0.65).mean())
        opening = 0.40 * far_median + 0.25 * far_p75 + 0.20 * free_area_ratio - 0.40 * near_risk
        opening = max(0.0, min(1.0, opening))
        scores[f"{name}_opening"] = round(opening, 4)
        scores[f"{name}_near_risk"] = round(near_risk, 4)
        scores[f"{name}_far_median"] = round(far_median, 4)
        scores[f"{name}_free_area_ratio"] = round(free_area_ratio, 4)
    return scores


def choose_best(scores: Dict[str, float]) -> str:
    return max(ROI_NAMES, key=lambda name: scores[f"{name}_opening"])


def is_match(best_roi: str, expected: str) -> Optional[bool]:
    if expected in {"blocked", "unclear"}:
        return None
    return best_roi == expected


def draw_overlay(depth_gray: np.ndarray, row: Dict[str, object], out_path: Path) -> None:
    h, w = depth_gray.shape
    vis = cv2.cvtColor(depth_gray, cv2.COLOR_GRAY2BGR)
    y0 = int(0.40 * h)
    y1 = int(0.95 * h)
    bounds = {
        "left": (0, w // 3),
        "center": (w // 3, 2 * w // 3),
        "right": (2 * w // 3, w),
    }
    colors = {"left": (255, 128, 0), "center": (0, 180, 0), "right": (0, 128, 255)}
    for name, (x0, x1) in bounds.items():
        color = colors[name]
        cv2.rectangle(vis, (x0, y0), (x1 - 1, y1 - 1), color, 3)
        label = f"{name[0].upper()} {row[f'{name}_opening']:.3f}/{row[f'{name}_near_risk']:.3f}"
        cv2.putText(vis, label, (x0 + 12, y0 + 42), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2, cv2.LINE_AA)
    headline = f"best={row['best_roi']} expected={row['expected_opening']} match={row['label_match']}"
    cv2.putText(vis, headline, (20, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 4, cv2.LINE_AA)
    cv2.putText(vis, headline, (20, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), vis)


def summarize(rows: List[Dict[str, object]]) -> Dict[str, object]:
    scene_summary: Dict[str, object] = {}
    for scene in sorted({str(row["scene"]) for row in rows}):
        subset = [row for row in rows if row["scene"] == scene]
        labeled = [row for row in subset if row["label_match"] in {"true", "false"}]
        matches = [row for row in labeled if row["label_match"] == "true"]
        scene_summary[scene] = {
            "count": len(subset),
            "labeled_count": len(labeled),
            "label_match_rate": round(len(matches) / len(labeled), 4) if labeled else None,
            "avg_left_opening": round(float(np.mean([row["left_opening"] for row in subset])), 4),
            "avg_center_opening": round(float(np.mean([row["center_opening"] for row in subset])), 4),
            "avg_right_opening": round(float(np.mean([row["right_opening"] for row in subset])), 4),
        }
    labeled_all = [row for row in rows if row["label_match"] in {"true", "false"}]
    matched_all = [row for row in labeled_all if row["label_match"] == "true"]
    return {
        "total_images": len(rows),
        "labeled_images": len(labeled_all),
        "overall_label_match_rate": round(len(matched_all) / len(labeled_all), 4) if labeled_all else None,
        "scenes": scene_summary,
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
        label = labels.get(image, Label(expected_opening="unclear", label_confidence="low", note="missing manual label"))
        scores = score_depth(depth, args.roi_y_start, args.roi_y_end)
        best = choose_best(scores)
        match = is_match(best, label.expected_opening)
        row: Dict[str, object] = {
            "image": image,
            "scene": scene,
            **scores,
            "best_roi": best,
            "expected_opening": label.expected_opening,
            "label_confidence": label.label_confidence,
            "label_match": "na" if match is None else str(match).lower(),
            "note": label.note,
        }
        rows.append(row)
        draw_overlay(depth, row, overlay_dir / f"{image}.png")

    csv_fields = [
        "image",
        "scene",
        "left_opening",
        "center_opening",
        "right_opening",
        "left_near_risk",
        "center_near_risk",
        "right_near_risk",
        "left_far_median",
        "center_far_median",
        "right_far_median",
        "left_free_area_ratio",
        "center_free_area_ratio",
        "right_free_area_ratio",
        "best_roi",
        "expected_opening",
        "label_confidence",
        "label_match",
        "note",
    ]
    with (args.outdir / "passage_scores.csv").open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(rows)

    with (args.outdir / "summary.json").open("w", encoding="utf-8") as fp:
        json.dump(summarize(rows), fp, indent=2, ensure_ascii=False)

    print(f"Wrote {len(rows)} rows to {args.outdir / 'passage_scores.csv'}")
    print(f"Wrote overlays to {overlay_dir}")
    print(f"Wrote summary to {args.outdir / 'summary.json'}")


if __name__ == "__main__":
    main()
