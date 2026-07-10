"""Score provisional physical motion primitives from relative depth maps.

This PC-only prototype projects a configurable vehicle sweep onto the image and
uses row-relative inverse-depth residuals. The geometry is provisional and must
not be used for real vehicle control.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np


CANDIDATE_ACTIONS = (
    "PROBE_FORWARD_20CM",
    "PIVOT_LEFT_20DEG",
    "PIVOT_RIGHT_20DEG",
)
VALID_EXPECTED_VERDICTS = {"ALLOW_CAUTION", "VETO_STOP", "UNCLEAR", "REVIEW"}


@dataclass(frozen=True)
class GeometryConfig:
    vehicle_width_m: float
    vehicle_length_m: float
    safety_margin_m: float
    camera_height_m: float
    camera_pitch_deg: float
    camera_hfov_deg: float
    camera_forward_offset_m: float
    probe_forward_m: float
    pivot_deg: float
    pose_samples: int
    row_residual_threshold: float
    severe_residual_threshold: float

    @classmethod
    def load(cls, path: Path) -> "GeometryConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    @property
    def envelope_width_m(self) -> float:
        return self.vehicle_width_m + 2.0 * self.safety_margin_m

    @property
    def envelope_length_m(self) -> float:
        return self.vehicle_length_m + 2.0 * self.safety_margin_m


@dataclass
class Label:
    expected_verdict: str
    label_confidence: str
    reason_codes: str
    note: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score provisional physical motion sweeps from depth maps.")
    parser.add_argument("--depth-dir", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    return parser.parse_args()


def iter_image_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            yield path


def load_source_map(input_root: Path) -> Dict[str, Path]:
    return {path.stem: path for path in iter_image_files(input_root)}


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
                reason_codes=row.get("reason_codes", "").strip(),
                note=row["note"].strip(),
            )
    return labels


def action_poses(action: str, config: GeometryConfig) -> List[Tuple[float, float, float]]:
    ts = np.linspace(0.0, 1.0, config.pose_samples)
    if action == "PROBE_FORWARD_20CM":
        return [(0.0, float(t * config.probe_forward_m), 0.0) for t in ts]
    angle = math.radians(config.pivot_deg)
    if action == "PIVOT_LEFT_20DEG":
        return [(0.0, 0.0, float(-t * angle)) for t in ts]
    if action == "PIVOT_RIGHT_20DEG":
        return [(0.0, 0.0, float(t * angle)) for t in ts]
    raise ValueError(f"Unknown action: {action}")


def footprint(pose: Tuple[float, float, float], config: GeometryConfig) -> np.ndarray:
    cx, cz, yaw = pose
    half_w = config.envelope_width_m / 2.0
    half_l = config.envelope_length_m / 2.0
    local = np.array(
        [[-half_w, -half_l], [half_w, -half_l], [half_w, half_l], [-half_w, half_l]],
        dtype=np.float32,
    )
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    rotated = np.empty_like(local)
    rotated[:, 0] = local[:, 0] * cos_yaw + local[:, 1] * sin_yaw + cx
    rotated[:, 1] = -local[:, 0] * sin_yaw + local[:, 1] * cos_yaw + cz
    return rotated


def clip_polygon_near_plane(points: np.ndarray, min_z: float = 0.06) -> np.ndarray:
    output = [tuple(point) for point in points]
    clipped: List[Tuple[float, float]] = []
    for index, current in enumerate(output):
        previous = output[index - 1]
        current_inside = current[1] >= min_z
        previous_inside = previous[1] >= min_z
        if current_inside != previous_inside:
            ratio = (min_z - previous[1]) / (current[1] - previous[1])
            clipped.append((previous[0] + ratio * (current[0] - previous[0]), min_z))
        if current_inside:
            clipped.append(current)
    return np.asarray(clipped, dtype=np.float32)


def project_ground(points: np.ndarray, width: int, height: int, config: GeometryConfig) -> np.ndarray:
    clipped = clip_polygon_near_plane(points.copy())
    if len(clipped) < 3:
        return np.empty((0, 2), dtype=np.int32)
    x = clipped[:, 0]
    z = clipped[:, 1] - config.camera_forward_offset_m
    h = config.camera_height_m
    pitch = math.radians(config.camera_pitch_deg)
    y_camera = math.cos(pitch) * h - math.sin(pitch) * z
    z_camera = math.sin(pitch) * h + math.cos(pitch) * z
    valid = z_camera > 0.03
    if valid.sum() < 3:
        return np.empty((0, 2), dtype=np.int32)
    fx = width / (2.0 * math.tan(math.radians(config.camera_hfov_deg) / 2.0))
    fy = fx
    u = width * 0.5 + fx * x[valid] / z_camera[valid]
    v = height * 0.5 + fy * y_camera[valid] / z_camera[valid]
    projected = np.column_stack((u, v))
    projected[:, 0] = np.clip(projected[:, 0], -width, 2 * width)
    projected[:, 1] = np.clip(projected[:, 1], -height, 2 * height)
    return np.rint(projected).astype(np.int32)


def projected_sweep(
    action: str, shape: Tuple[int, int], config: GeometryConfig
) -> Tuple[np.ndarray, List[np.ndarray], List[Tuple[float, float, float]]]:
    height, width = shape
    poses = action_poses(action, config)
    outlines: List[np.ndarray] = []
    for pose in poses:
        polygon = project_ground(footprint(pose, config), width, height, config)
        outlines.append(polygon)

    grid_size = 900
    x_min, x_max = -0.80, 0.80
    z_min, z_max = -0.50, 1.00

    def to_grid(points: np.ndarray) -> np.ndarray:
        gx = (points[:, 0] - x_min) / (x_max - x_min) * (grid_size - 1)
        gy = (z_max - points[:, 1]) / (z_max - z_min) * (grid_size - 1)
        return np.rint(np.column_stack((gx, gy))).astype(np.int32)

    ground_union = np.zeros((grid_size, grid_size), dtype=np.uint8)
    for pose in poses:
        cv2.fillConvexPoly(ground_union, to_grid(footprint(pose, config)), 1)
    ground_initial = np.zeros_like(ground_union)
    cv2.fillConvexPoly(ground_initial, to_grid(footprint(poses[0], config)), 1)
    ground_new = np.logical_and(ground_union.astype(bool), np.logical_not(ground_initial.astype(bool))).astype(np.uint8)

    image_mask = np.zeros(shape, dtype=np.uint8)
    contours, _ = cv2.findContours(ground_new, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        pixels = contour[:, 0, :].astype(np.float32)
        metric_x = x_min + pixels[:, 0] / (grid_size - 1) * (x_max - x_min)
        metric_z = z_max - pixels[:, 1] / (grid_size - 1) * (z_max - z_min)
        projected = project_ground(np.column_stack((metric_x, metric_z)), width, height, config)
        if len(projected) >= 3:
            cv2.fillPoly(image_mask, [projected], 1)
    image_mask[: int(height * 0.30), :] = 0
    return image_mask.astype(bool), outlines, poses


def smooth(values: np.ndarray, window: int = 31) -> np.ndarray:
    if len(values) < window:
        return values
    kernel = np.ones(window, dtype=np.float32) / window
    padded = np.pad(values, (window // 2, window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def row_floor_baseline(near: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    height, width = near.shape
    x0, x1 = int(width * 0.28), int(width * 0.72)
    center = near[:, x0:x1]
    baseline = np.percentile(center, 55, axis=1).astype(np.float32)
    baseline = smooth(baseline)
    mad = np.median(np.abs(center - baseline[:, None]), axis=1).astype(np.float32)
    return baseline, mad


def score_candidate(depth_gray: np.ndarray, action: str, config: GeometryConfig) -> Dict[str, object]:
    near = depth_gray.astype(np.float32) / 255.0
    sweep_mask, outlines, poses = projected_sweep(action, depth_gray.shape, config)
    baseline, row_mad = row_floor_baseline(near)
    residual = near - baseline[:, None]
    values = residual[sweep_mask]
    if values.size == 0:
        near_risk = severe_risk = p90_residual = bottom_near_risk = 0.0
        baseline_mad = 1.0
    else:
        near_risk = float((values > config.row_residual_threshold).mean())
        severe_risk = float((values > config.severe_residual_threshold).mean())
        p90_residual = float(np.percentile(values, 90))
        ys = np.where(sweep_mask)[0]
        bottom_cut = int(np.percentile(ys, 67)) if ys.size else depth_gray.shape[0]
        bottom_values = residual[np.logical_and(sweep_mask, np.indices(sweep_mask.shape)[0] >= bottom_cut)]
        bottom_near_risk = float((bottom_values > config.row_residual_threshold).mean()) if bottom_values.size else 0.0
        baseline_mad = float(np.mean(row_mad[np.unique(ys)]))

    mask_pixels = int(sweep_mask.sum())
    open_score = 0.0 if mask_pixels == 0 else float(
        np.clip(1.0 - 1.35 * near_risk - 0.85 * severe_risk - 0.70 * max(0.0, p90_residual), 0.0, 1.0)
    )
    if mask_pixels == 0:
        verdict, reason = "UNCLEAR", "new_sweep_outside_camera_fov"
    elif mask_pixels < 300:
        verdict, reason = "UNCLEAR", "projected_sweep_too_small"
    elif severe_risk >= 0.08 or near_risk >= 0.25:
        verdict, reason = "VETO_STOP", "row_relative_obstacle_residual_high"
    elif near_risk <= 0.08 and p90_residual <= 0.12:
        verdict, reason = "ALLOW_CAUTION", "row_relative_obstacle_residual_low"
    else:
        verdict, reason = "UNCLEAR", "residual_margin_insufficient"
    confidence = float(np.clip(1.0 - 2.0 * baseline_mad, 0.0, 1.0))
    return {
        "candidate_action": action,
        "open_score": round(open_score, 4),
        "near_risk": round(near_risk, 4),
        "severe_near_risk": round(severe_risk, 4),
        "bottom_near_risk": round(bottom_near_risk, 4),
        "p90_row_residual": round(p90_residual, 4),
        "floor_baseline_mad": round(baseline_mad, 4),
        "confidence": round(confidence, 4),
        "predicted_verdict": verdict,
        "risk_reason": reason,
        "mask_pixels": mask_pixels,
        "sweep_visible": mask_pixels > 0,
        "sweep_mask": sweep_mask,
        "residual": residual,
        "outlines": outlines,
        "poses": poses,
    }


def verdict_match(predicted: str, expected: str) -> Optional[bool]:
    if expected in {"REVIEW", "UNCLEAR"}:
        return None
    return predicted == expected


def source_image(path: Optional[Path], shape: Tuple[int, int]) -> np.ndarray:
    height, width = shape
    if path is None:
        return np.full((height, width, 3), 48, dtype=np.uint8)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return np.full((height, width, 3), 48, dtype=np.uint8)
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def draw_projected_panel(
    base: np.ndarray, sweep_mask: np.ndarray, outlines: Sequence[np.ndarray], color: Tuple[int, int, int]
) -> np.ndarray:
    panel = base.copy()
    fill = panel.copy()
    fill[sweep_mask] = color
    panel = cv2.addWeighted(fill, 0.34, panel, 0.66, 0)
    for index, polygon in enumerate(outlines):
        if len(polygon) >= 3:
            shade = (150, 150, 150) if index < len(outlines) - 1 else color
            cv2.polylines(panel, [polygon], True, shade, 2 if index < len(outlines) - 1 else 4, cv2.LINE_AA)
    if not sweep_mask.any():
        cv2.putText(panel, "NEW SWEEP OUTSIDE CAMERA FOV", (24, panel.shape[0] - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (20, 20, 220), 3, cv2.LINE_AA)
    return panel


def draw_depth_panel(depth_gray: np.ndarray, sweep_mask: np.ndarray, residual: np.ndarray) -> np.ndarray:
    panel = cv2.applyColorMap(depth_gray, cv2.COLORMAP_TURBO)
    risk = np.clip((residual - 0.04) / 0.20, 0.0, 1.0)
    heat = np.zeros_like(panel)
    heat[:, :, 2] = np.rint(255 * risk).astype(np.uint8)
    active = np.logical_and(sweep_mask, risk > 0)
    panel[active] = cv2.addWeighted(panel, 0.35, heat, 0.65, 0)[active]
    contours, _ = cv2.findContours(sweep_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(panel, contours, -1, (255, 255, 255), 3, cv2.LINE_AA)
    return panel


def topdown_point(x: float, z: float, width: int, height: int) -> Tuple[int, int]:
    x_min, x_max = -0.70, 0.70
    z_min, z_max = -0.35, 0.85
    px = int((x - x_min) / (x_max - x_min) * width)
    py = int(height - (z - z_min) / (z_max - z_min) * height)
    return px, py


def draw_topdown(shape: Tuple[int, int], poses: Sequence[Tuple[float, float, float]], config: GeometryConfig) -> np.ndarray:
    height, width = shape
    panel = np.full((height, width, 3), 245, dtype=np.uint8)
    grid_color = (215, 215, 215)
    for x in np.arange(-0.6, 0.61, 0.2):
        cv2.line(panel, topdown_point(float(x), -0.3, width, height), topdown_point(float(x), 0.8, width, height), grid_color, 1)
    for z in np.arange(-0.2, 0.81, 0.2):
        cv2.line(panel, topdown_point(-0.65, float(z), width, height), topdown_point(0.65, float(z), width, height), grid_color, 1)
    sweep = np.zeros((height, width), dtype=np.uint8)
    for pose in poses:
        polygon = np.array([topdown_point(float(x), float(z), width, height) for x, z in footprint(pose, config)])
        cv2.fillConvexPoly(sweep, polygon, 1)
    fill = panel.copy()
    fill[sweep.astype(bool)] = (210, 232, 218)
    panel = cv2.addWeighted(fill, 0.75, panel, 0.25, 0)
    centers = np.array([topdown_point(pose[0], pose[1], width, height) for pose in poses], dtype=np.int32)
    if len(centers) > 1:
        cv2.polylines(panel, [centers], False, (40, 110, 190), 4, cv2.LINE_AA)
    for index, pose in enumerate(poses):
        polygon = np.array([topdown_point(float(x), float(z), width, height) for x, z in footprint(pose, config)])
        color = (90, 90, 90) if index < len(poses) - 1 else (40, 135, 55)
        cv2.polylines(panel, [polygon], True, color, 2 if index < len(poses) - 1 else 4, cv2.LINE_AA)
        if index in {0, len(poses) - 1}:
            cx, cz, yaw = pose
            start = topdown_point(cx, cz, width, height)
            end = topdown_point(cx + 0.12 * math.sin(yaw), cz + 0.12 * math.cos(yaw), width, height)
            cv2.arrowedLine(panel, start, end, color, 3, cv2.LINE_AA, tipLength=0.25)
    cv2.putText(panel, "TOP-DOWN MOTION STORYBOARD", (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.putText(panel, "green=final pose  gray=intermediate", (16, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (60, 60, 60), 1, cv2.LINE_AA)
    return panel


def draw_storyboard(
    rgb: np.ndarray, depth_gray: np.ndarray, row: Dict[str, object], config: GeometryConfig, out_path: Path
) -> None:
    color_by_verdict = {"ALLOW_CAUTION": (55, 175, 55), "VETO_STOP": (45, 45, 225), "UNCLEAR": (0, 175, 225)}
    color = color_by_verdict[str(row["predicted_verdict"])]
    rgb_panel = draw_projected_panel(rgb, row["sweep_mask"], row["outlines"], color)
    depth_panel = draw_depth_panel(depth_gray, row["sweep_mask"], row["residual"])
    topdown = draw_topdown(depth_gray.shape, row["poses"], config)
    display_width = 720
    display_height = int(depth_gray.shape[0] * display_width / depth_gray.shape[1])
    rgb_panel = cv2.resize(rgb_panel, (display_width, display_height), interpolation=cv2.INTER_AREA)
    depth_panel = cv2.resize(depth_panel, (display_width, display_height), interpolation=cv2.INTER_AREA)
    topdown = cv2.resize(topdown, (display_width, display_height), interpolation=cv2.INTER_AREA)
    body = cv2.hconcat([rgb_panel, depth_panel, topdown])
    header = np.full((150, body.shape[1], 3), 250, dtype=np.uint8)
    lines = [
        f"{row['image']} | {row['candidate_action']} | PROVISIONAL GEOMETRY - NOT FOR CONTROL",
        f"vehicle={config.vehicle_width_m:.3f}x{config.vehicle_length_m:.2f}m margin={config.safety_margin_m:.2f}m camera_h={config.camera_height_m:.2f}m pitch={config.camera_pitch_deg:.0f}deg",
        f"pred={row['predicted_verdict']} open={row['open_score']:.3f} row_risk={row['near_risk']:.3f} severe={row['severe_near_risk']:.3f} bottom_residual={row['bottom_near_risk']:.3f}",
        "RGB + projected new sweep | relative depth + obstacle residual | top-down sampled body poses",
    ]
    for index, line in enumerate(lines):
        cv2.putText(header, line, (18, 30 + index * 34), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), cv2.vconcat([header, body]))


def summarize(rows: List[Dict[str, object]], config: GeometryConfig) -> Dict[str, object]:
    per_action: Dict[str, object] = {}
    for action in CANDIDATE_ACTIONS:
        subset = [row for row in rows if row["candidate_action"] == action]
        labeled = [row for row in subset if row["label_match"] in {"true", "false"}]
        matched = [row for row in labeled if row["label_match"] == "true"]
        per_action[action] = {
            "rows": len(subset),
            "labeled_rows": len(labeled),
            "label_match_rate": round(len(matched) / len(labeled), 4) if labeled else None,
            "avg_open_score": round(float(np.mean([row["open_score"] for row in subset])), 4),
            "avg_near_risk": round(float(np.mean([row["near_risk"] for row in subset])), 4),
            "avg_bottom_near_risk": round(float(np.mean([row["bottom_near_risk"] for row in subset])), 4),
            "visible_sweep_rows": len([row for row in subset if row["sweep_visible"]]),
            "predicted_verdict_counts": {
                verdict: len([row for row in subset if row["predicted_verdict"] == verdict])
                for verdict in ("ALLOW_CAUTION", "VETO_STOP", "UNCLEAR")
            },
        }
    labeled_all = [row for row in rows if row["label_match"] in {"true", "false"}]
    matched_all = [row for row in labeled_all if row["label_match"] == "true"]
    return {
        "status": "provisional_geometry_visualization_only",
        "total_rows": len(rows),
        "total_images": len({row["image"] for row in rows}),
        "candidate_actions": list(CANDIDATE_ACTIONS),
        "labeled_rows": len(labeled_all),
        "overall_label_match_rate": round(len(matched_all) / len(labeled_all), 4) if labeled_all else None,
        "geometry": config.__dict__,
        "per_action": per_action,
    }


def main() -> None:
    args = parse_args()
    config = GeometryConfig.load(args.config)
    args.outdir.mkdir(parents=True, exist_ok=True)
    storyboard_dir = args.outdir / "storyboards"
    storyboard_dir.mkdir(parents=True, exist_ok=True)
    sources = load_source_map(args.input_root)
    labels = load_labels(args.labels)
    rows: List[Dict[str, object]] = []

    for depth_path in sorted(args.depth_dir.glob("*.png")):
        depth = cv2.imread(str(depth_path), cv2.IMREAD_GRAYSCALE)
        if depth is None:
            raise ValueError(f"Could not read depth image: {depth_path}")
        image = depth_path.stem
        source_path = sources.get(image)
        scene = source_path.parent.name if source_path else "unknown"
        rgb = source_image(source_path, depth.shape)
        for action in CANDIDATE_ACTIONS:
            score = score_candidate(depth, action, config)
            label = labels.get((image, action), Label("REVIEW", "todo", "", "manual review required"))
            match = verdict_match(str(score["predicted_verdict"]), label.expected_verdict)
            row: Dict[str, object] = {
                "image": image,
                "scene": scene,
                **score,
                "expected_verdict": label.expected_verdict,
                "label_confidence": label.label_confidence,
                "label_match": "na" if match is None else str(match).lower(),
                "reason_codes": label.reason_codes,
                "note": label.note,
            }
            draw_storyboard(rgb, depth, row, config, storyboard_dir / f"{image}_{action.lower()}.png")
            for transient in ("sweep_mask", "residual", "outlines", "poses"):
                row.pop(transient)
            rows.append(row)

    csv_fields = [
        "image", "scene", "candidate_action", "open_score", "near_risk", "severe_near_risk",
        "bottom_near_risk", "p90_row_residual", "floor_baseline_mad", "mask_pixels", "sweep_visible", "confidence",
        "predicted_verdict", "risk_reason", "expected_verdict", "label_confidence", "label_match",
        "reason_codes", "note",
    ]
    with (args.outdir / "traversability_scores.csv").open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(rows)
    with (args.outdir / "summary.json").open("w", encoding="utf-8") as fp:
        json.dump(summarize(rows, config), fp, indent=2, ensure_ascii=False)
    print(f"Wrote {len(rows)} rows to {args.outdir / 'traversability_scores.csv'}")
    print(f"Wrote storyboards to {storyboard_dir}")
    print(f"Wrote summary to {args.outdir / 'summary.json'}")


if __name__ == "__main__":
    main()
