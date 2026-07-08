from pathlib import Path
import argparse
import csv
import math
import random
import statistics
import torch
import torch.nn.functional as F
from torchreid.utils import FeatureExtractor

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

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

STRATEGIES = ("reid_only", "reid_center", "reid_center_area", "reid_prediction_area")


def resolve(root: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def norm_rel(path_text: str) -> str:
    return str(Path(path_text.replace("\\", "/")).as_posix())


def truthy(v):
    return str(v).strip().lower() in {"1", "true", "yes"}


def to_float(row, key, default=0.0):
    value = row.get(key, "")
    if value == "":
        return default
    return float(value)


def load_source_dimensions(src_path_text: str, cache):
    src_path = Path(src_path_text)
    if not src_path.exists():
        return None
    session_dir = src_path.parent.parent
    metadata_path = session_dir / "metadata.csv"
    if not metadata_path.exists():
        return None

    if metadata_path not in cache:
        lookup = {}
        with metadata_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                crop_path = norm_rel(row.get("crop_path", ""))
                if crop_path and row.get("image_width") and row.get("image_height"):
                    lookup[crop_path] = (int(float(row["image_width"])), int(float(row["image_height"])))
        cache[metadata_path] = lookup

    crop_rel = norm_rel(src_path.relative_to(session_dir).as_posix())
    return cache[metadata_path].get(crop_rel)


def load_manifest(manifest_path: Path, image_dir: Path, default_w: int, default_h: int):
    rows = []
    by_rel = {}
    source_dim_cache = {}
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rel = norm_rel(row["out_path"])
            path = (image_dir / rel).resolve()
            if not path.exists():
                continue
            source_dims = load_source_dimensions(row.get("src_path", ""), source_dim_cache)
            width = int(float(row.get("image_width") or (source_dims[0] if source_dims else default_w)))
            height = int(float(row.get("image_height") or (source_dims[1] if source_dims else default_h)))
            bbox = {
                "left": to_float(row, "bbox_left"),
                "top": to_float(row, "bbox_top"),
                "right": to_float(row, "bbox_right"),
                "bottom": to_float(row, "bbox_bottom"),
                "width": to_float(row, "bbox_width"),
                "height": to_float(row, "bbox_height"),
                "image_width": width,
                "image_height": height,
            }
            item = {
                "identity": row["identity"],
                "session_id": row.get("session_id", ""),
                "path": path,
                "rel_path": rel,
                "frame_id": int(float(row.get("frame_id") or 0)),
                "timestamp_ms": int(float(row.get("timestamp_ms") or 0)),
                "bbox": bbox,
            }
            rows.append(item)
            by_rel[rel] = item
    if not rows:
        raise RuntimeError(f"No usable manifest rows found: {manifest_path}")
    return rows, by_rel


def collect_from_manifest(rows, per_id=None, seed=42, sample_mode="random"):
    rng = random.Random(seed)
    data = {}
    for item in rows:
        data.setdefault(item["identity"], []).append(item["path"])
    for ident in list(data):
        paths = sorted(data[ident])
        if per_id is not None and len(paths) > per_id:
            if sample_mode == "even":
                idxs = [round(i * (len(paths) - 1) / (per_id - 1)) for i in range(per_id)] if per_id > 1 else [len(paths) // 2]
                paths = [paths[i] for i in idxs]
            else:
                paths = sorted(rng.sample(paths, per_id))
        data[ident] = paths
    if len(data) < 2:
        raise RuntimeError("Need at least two identity folders.")
    return data


def extract(model_name, weight_path, paths, device):
    extractor = FeatureExtractor(model_name=model_name, model_path=str(weight_path), device=device)
    feats = extractor([str(p) for p in paths])
    if not isinstance(feats, torch.Tensor):
        feats = torch.tensor(feats)
    return F.normalize(feats.detach().cpu(), p=2, dim=1)


def select_diverse(indices, feats, k):
    if k >= len(indices):
        return list(indices)
    sub = feats[indices]
    sim = sub @ sub.t()
    first = int(torch.argmin(sim.mean(dim=1)).item())
    selected = [first]
    remaining = set(range(len(indices)))
    remaining.remove(first)
    while len(selected) < k and remaining:
        best_j, best_s = None, None
        for j in remaining:
            s = sim[j, selected].max().item()
            if best_s is None or s < best_s:
                best_s = s
                best_j = j
        selected.append(best_j)
        remaining.remove(best_j)
    return [indices[i] for i in selected]


def select_gallery(indices, feats, k, strategy, rng):
    if k >= len(indices):
        return list(indices)
    if strategy == "diverse":
        return select_diverse(indices, feats, k)
    return rng.sample(indices, k)


def bbox_center(bbox):
    return ((bbox["left"] + bbox["right"]) / 2.0, (bbox["top"] + bbox["bottom"]) / 2.0)


def bbox_area(bbox):
    area = bbox["width"] * bbox["height"]
    return max(area, 1e-9)


def bbox_metrics(candidate_bbox, last_bbox, prev_bbox=None):
    cx, cy = bbox_center(candidate_bbox)
    lx, ly = bbox_center(last_bbox)
    image_w = candidate_bbox["image_width"] or last_bbox["image_width"]
    image_h = candidate_bbox["image_height"] or last_bbox["image_height"]
    image_diag = math.hypot(image_w, image_h)
    center_jump = math.hypot(cx - lx, cy - ly) / image_diag
    x_jump = abs(cx - lx) / image_w
    area_ratio = bbox_area(candidate_bbox) / bbox_area(last_bbox)

    prediction_error = ""
    if prev_bbox is not None:
        px, py = bbox_center(prev_bbox)
        pred_x = lx + (lx - px)
        pred_y = ly + (ly - py)
        prediction_error = math.hypot(cx - pred_x, cy - pred_y) / image_diag

    return {
        "center_jump_ratio": center_jump,
        "x_jump_ratio": x_jump,
        "area_ratio": area_ratio,
        "prediction_error": prediction_error,
    }


def score_candidates(candidate_indices, target_gallery, feats):
    scored = []
    for idx in candidate_indices:
        score = (feats[target_gallery] @ feats[idx]).max().item()
        scored.append((idx, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    best_idx, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0
    return best_idx, best_score, second_score


def gate_flags(best_score, margin, metrics, reid_profile, bbox_profile, strategy, enable_prediction):
    best_ok = best_score >= reid_profile["best"]
    margin_ok = margin >= reid_profile["margin"]
    center_ok = metrics["center_jump_ratio"] <= bbox_profile["center"]
    x_ok = metrics["x_jump_ratio"] <= bbox_profile["x"]
    area_ok = bbox_profile["area_min"] <= metrics["area_ratio"] <= bbox_profile["area_max"]
    pred_value = metrics["prediction_error"]
    prediction_available = pred_value != ""
    prediction_ok = bool(prediction_available and pred_value <= bbox_profile["center"])

    if strategy == "reid_only":
        accepted = best_ok and margin_ok
    elif strategy == "reid_center":
        accepted = best_ok and margin_ok and center_ok and x_ok
    elif strategy == "reid_center_area":
        accepted = best_ok and margin_ok and center_ok and x_ok and area_ok
    elif strategy == "reid_prediction_area":
        accepted = best_ok and margin_ok and area_ok
        accepted = accepted and ((enable_prediction and prediction_ok) or ((not enable_prediction) and center_ok and x_ok))
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return {
        "best_ok": best_ok,
        "margin_ok": margin_ok,
        "center_ok": center_ok,
        "x_ok": x_ok,
        "area_ok": area_ok,
        "prediction_ok": prediction_ok if prediction_available else "",
        "accepted": accepted,
    }


def first_reject_reason(flags, strategy, enable_prediction):
    if not flags["best_ok"]:
        return "rejected_by_best_score"
    if not flags["margin_ok"]:
        return "rejected_by_margin"
    if strategy in {"reid_center", "reid_center_area"}:
        if not flags["center_ok"]:
            return "rejected_by_center_jump"
        if not flags["x_ok"]:
            return "rejected_by_x_jump"
    if strategy == "reid_center_area" and not flags["area_ok"]:
        return "rejected_by_area_ratio"
    if strategy == "reid_prediction_area":
        if enable_prediction and not flags["prediction_ok"]:
            return "rejected_by_prediction"
        if (not enable_prediction) and not flags["center_ok"]:
            return "rejected_by_center_jump"
        if (not enable_prediction) and not flags["x_ok"]:
            return "rejected_by_x_jump"
        if not flags["area_ok"]:
            return "rejected_by_area_ratio"
    return ""


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def pct(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def stat(values):
    if not values:
        return {}
    return {
        "mean": statistics.mean(values),
        "p25": pct(values, 0.25),
        "median": pct(values, 0.5),
        "p75": pct(values, 0.75),
        "max": max(values),
    }


def summarize(rows):
    groups = {}
    for row in rows:
        key = (row["gap"], row["strategy"], row["reid_profile"], row["bbox_profile"])
        groups.setdefault(key, []).append(row)

    summary = []
    reject_rows = []
    for (gap, strategy, reid_name, bbox_name), group in sorted(groups.items()):
        present = [r for r in group if r["scenario"] == "target_present"]
        absent = [r for r in group if r["scenario"] == "target_absent"]
        present_accepted = [r for r in present if truthy(r["accepted"])]
        present_correct = [r for r in present_accepted if truthy(r["correct"])]
        absent_accepted = [r for r in absent if truthy(r["accepted"])]

        summary.append({
            "gap": gap,
            "strategy": strategy,
            "reid_profile": reid_name,
            "bbox_profile": bbox_name,
            "present_accept_rate": len(present_accepted) / len(present) if present else 0,
            "present_accept_acc": len(present_correct) / len(present_accepted) if present_accepted else "",
            "present_true_accept_rate": len(present_correct) / len(present) if present else 0,
            "present_false_reject_rate": 1 - (len(present_correct) / len(present) if present else 0),
            "absent_false_accept_rate": len(absent_accepted) / len(absent) if absent else 0,
            "absent_reject_rate": 1 - (len(absent_accepted) / len(absent) if absent else 0),
        })

        counts = {
            "rejected_by_best_score": 0,
            "rejected_by_margin": 0,
            "rejected_by_center_jump": 0,
            "rejected_by_x_jump": 0,
            "rejected_by_area_ratio": 0,
            "rejected_by_prediction": 0,
        }
        for row in group:
            reason = row["reject_reason"]
            if reason in counts:
                counts[reason] += 1
        reject_rows.append({
            "gap": gap,
            "strategy": strategy,
            "reid_profile": reid_name,
            "bbox_profile": bbox_name,
            **counts,
        })
    return summary, reject_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="images_openbot_clean")
    ap.add_argument("--manifest", default="images_openbot_clean/dataset_manifest.csv")
    ap.add_argument("--weight", required=True)
    ap.add_argument("--model", default="osnet_x0_25")
    ap.add_argument("--per-id", type=int, default=None)
    ap.add_argument("--sample-mode", choices=["random", "even"], default="random")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--gallery-k", type=int, default=8)
    ap.add_argument("--gallery-strategy", choices=["random", "diverse"], default="diverse")
    ap.add_argument("--distractors", type=int, default=2)
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--frames-per-target", type=int, default=50)
    ap.add_argument("--gap-values", default="1,3,5")
    ap.add_argument("--image-width", type=int, default=1280)
    ap.add_argument("--image-height", type=int, default=720)
    ap.add_argument("--enable-prediction", action="store_true")
    ap.add_argument("--output-prefix", default="target_follow_bbox_v1")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    image_dir = resolve(root, args.images)
    manifest_path = resolve(root, args.manifest)
    weight_path = resolve(root, args.weight)
    out_dir = root / "outputs"
    out_dir.mkdir(exist_ok=True)

    gaps = [int(x) for x in args.gap_values.split(",") if x.strip()]
    rng = random.Random(args.seed)

    manifest_rows, manifest_by_rel = load_manifest(manifest_path, image_dir, args.image_width, args.image_height)
    data = collect_from_manifest(manifest_rows, args.per_id, args.seed, args.sample_mode)
    identities = sorted(data.keys())
    if args.distractors > len(identities) - 1:
        raise RuntimeError("distractors must be <= number of identities - 1")

    all_paths, labels = [], []
    for ident in identities:
        for path in data[ident]:
            all_paths.append(path)
            labels.append(ident)

    path_to_idx = {p: i for i, p in enumerate(all_paths)}
    idx_to_path = {i: p for p, i in path_to_idx.items()}
    idx_to_label = {i: labels[i] for i in range(len(labels))}
    path_to_item = {item["path"]: item for item in manifest_rows}
    rel_to_idx = {norm_rel(p.relative_to(image_dir).as_posix()): idx for p, idx in path_to_idx.items()}

    sequences = {}
    for item in manifest_rows:
        if item["path"] in path_to_idx:
            key = (item["identity"], item["session_id"])
            sequences.setdefault(key, []).append(item)
    for key in sequences:
        sequences[key].sort(key=lambda x: (x["frame_id"], x["timestamp_ms"], x["rel_path"]))

    print(f"[INFO] image_dir = {image_dir}")
    print(f"[INFO] manifest = {manifest_path}")
    print(f"[INFO] weight = {weight_path}")
    print(f"[INFO] model = {args.model}")
    print(f"[INFO] gaps = {gaps}")
    print(f"[INFO] enable_prediction = {args.enable_prediction}")
    print("[INFO] identities:")
    for ident in identities:
        print(f"  {ident}: {len(data[ident])} images")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device = {device}")

    feats = extract(args.model, weight_path, all_paths, device)
    print(f"[INFO] feature_shape = {tuple(feats.shape)}")

    rows, gallery_rows = [], []
    for trial in range(args.trials):
        gallery, probes = {}, {}
        for ident in identities:
            indices = [path_to_idx[p] for p in data[ident]]
            gal = select_gallery(indices, feats, args.gallery_k, args.gallery_strategy, rng)
            gallery[ident] = gal
            probes[ident] = [idx for idx in indices if idx not in set(gal)]
            for gi in gal:
                gallery_rows.append({"trial": trial, "identity": ident, "path": idx_to_path[gi].relative_to(image_dir).as_posix()})

        for gap in gaps:
            for target in identities:
                others = [x for x in identities if x != target]
                target_pairs = []
                for (ident, _session), seq in sequences.items():
                    if ident != target:
                        continue
                    for pos in range(gap, len(seq)):
                        curr_item = seq[pos]
                        prev_item = seq[pos - gap]
                        if curr_item["path"] not in path_to_idx or prev_item["path"] not in path_to_idx:
                            continue
                        if path_to_idx[curr_item["path"]] in gallery[target]:
                            continue
                        prev2_item = seq[pos - (2 * gap)] if pos >= 2 * gap else None
                        target_pairs.append((prev_item, curr_item, prev2_item))
                if not target_pairs:
                    continue

                for frame_no in range(args.frames_per_target):
                    last_item, target_item, prev2_item = rng.choice(target_pairs)
                    target_idx = path_to_idx[target_item["path"]]
                    candidate_indices = [target_idx]
                    for did in rng.sample(others, args.distractors):
                        pool = probes[did] or [path_to_idx[p] for p in data[did]]
                        candidate_indices.append(rng.choice(pool))
                    best_idx, best_score, second_score = score_candidates(candidate_indices, gallery[target], feats)
                    margin = best_score - second_score
                    metrics = bbox_metrics(path_to_item[idx_to_path[best_idx]]["bbox"], last_item["bbox"], prev2_item["bbox"] if prev2_item else None)
                    correct = idx_to_label[best_idx] == target
                    best_rel = idx_to_path[best_idx].relative_to(image_dir).as_posix()

                    for reid_name, reid_profile in REID_PROFILES.items():
                        for bbox_name, bbox_profile in BBOX_PROFILES.items():
                            for strategy in STRATEGIES:
                                if strategy == "reid_prediction_area" and args.enable_prediction and prev2_item is None:
                                    continue
                                flags = gate_flags(best_score, margin, metrics, reid_profile, bbox_profile, strategy, args.enable_prediction)
                                reason = "" if flags["accepted"] else first_reject_reason(flags, strategy, args.enable_prediction)
                                rows.append({
                                    "trial": trial,
                                    "frame_no": frame_no,
                                    "gap": gap,
                                    "scenario": "target_present",
                                    "strategy": strategy,
                                    "reid_profile": reid_name,
                                    "bbox_profile": bbox_name,
                                    "target_identity": target,
                                    "best_label": idx_to_label[best_idx],
                                    "best_path": best_rel,
                                    "last_target_path": last_item["rel_path"],
                                    "best_score": best_score,
                                    "second_score": second_score,
                                    "margin": margin,
                                    "center_jump_ratio": metrics["center_jump_ratio"],
                                    "x_jump_ratio": metrics["x_jump_ratio"],
                                    "area_ratio": metrics["area_ratio"],
                                    "prediction_error": metrics["prediction_error"],
                                    **flags,
                                    "correct": correct,
                                    "reject_reason": reason,
                                })

                for frame_no in range(args.frames_per_target):
                    last_item, _target_item, prev2_item = rng.choice(target_pairs)
                    candidate_indices = []
                    for did in rng.sample(others, args.distractors):
                        pool = probes[did] or [path_to_idx[p] for p in data[did]]
                        candidate_indices.append(rng.choice(pool))
                    best_idx, best_score, second_score = score_candidates(candidate_indices, gallery[target], feats)
                    margin = best_score - second_score
                    metrics = bbox_metrics(path_to_item[idx_to_path[best_idx]]["bbox"], last_item["bbox"], prev2_item["bbox"] if prev2_item else None)
                    best_rel = idx_to_path[best_idx].relative_to(image_dir).as_posix()

                    for reid_name, reid_profile in REID_PROFILES.items():
                        for bbox_name, bbox_profile in BBOX_PROFILES.items():
                            for strategy in STRATEGIES:
                                if strategy == "reid_prediction_area" and args.enable_prediction and prev2_item is None:
                                    continue
                                flags = gate_flags(best_score, margin, metrics, reid_profile, bbox_profile, strategy, args.enable_prediction)
                                reason = "" if flags["accepted"] else first_reject_reason(flags, strategy, args.enable_prediction)
                                rows.append({
                                    "trial": trial,
                                    "frame_no": frame_no,
                                    "gap": gap,
                                    "scenario": "target_absent",
                                    "strategy": strategy,
                                    "reid_profile": reid_name,
                                    "bbox_profile": bbox_name,
                                    "target_identity": target,
                                    "best_label": idx_to_label[best_idx],
                                    "best_path": best_rel,
                                    "last_target_path": last_item["rel_path"],
                                    "best_score": best_score,
                                    "second_score": second_score,
                                    "margin": margin,
                                    "center_jump_ratio": metrics["center_jump_ratio"],
                                    "x_jump_ratio": metrics["x_jump_ratio"],
                                    "area_ratio": metrics["area_ratio"],
                                    "prediction_error": metrics["prediction_error"],
                                    **flags,
                                    "correct": False,
                                    "reject_reason": reason,
                                })

    summary_rows, reject_rows = summarize(rows)

    summary_fields = [
        "gap", "strategy", "reid_profile", "bbox_profile",
        "present_accept_rate", "present_accept_acc", "present_true_accept_rate", "present_false_reject_rate",
        "absent_false_accept_rate", "absent_reject_rate",
    ]
    row_fields = [
        "trial", "frame_no", "gap", "scenario", "strategy", "reid_profile", "bbox_profile",
        "target_identity", "best_label", "best_path", "last_target_path",
        "best_score", "second_score", "margin",
        "center_jump_ratio", "x_jump_ratio", "area_ratio", "prediction_error",
        "best_ok", "margin_ok", "center_ok", "x_ok", "area_ok", "prediction_ok",
        "accepted", "correct", "reject_reason",
    ]
    reject_fields = [
        "gap", "strategy", "reid_profile", "bbox_profile",
        "rejected_by_best_score", "rejected_by_margin", "rejected_by_center_jump",
        "rejected_by_x_jump", "rejected_by_area_ratio", "rejected_by_prediction",
    ]

    write_csv(out_dir / f"{args.output_prefix}_bbox_gate_summary.csv", summary_rows, summary_fields)
    write_csv(out_dir / f"{args.output_prefix}_bbox_gate_rows.csv", rows, row_fields)
    write_csv(out_dir / f"{args.output_prefix}_bbox_reject_reasons.csv", reject_rows, reject_fields)
    write_csv(out_dir / f"{args.output_prefix}_gallery_selected.csv", gallery_rows, ["trial", "identity", "path"])

    print("\n=== BBox Gate Summary: strong profile, selected rows ===")
    selected = [
        r for r in summary_rows
        if r["reid_profile"] == "strong"
        and r["strategy"] in {"reid_only", "reid_center_area", "reid_prediction_area"}
        and r["bbox_profile"] in {"default", "strict"}
    ]
    for r in selected:
        print(
            f"gap={r['gap']} {r['strategy']} {r['bbox_profile']}: "
            f"present_true_accept={float(r['present_true_accept_rate']):.3f}, "
            f"present_acc={float(r['present_accept_acc']) if r['present_accept_acc'] != '' else 0:.3f}, "
            f"absent_false_accept={float(r['absent_false_accept_rate']):.3f}"
        )

    print("\n[INFO] saved:")
    print(f"  {out_dir / (args.output_prefix + '_bbox_gate_summary.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_bbox_gate_rows.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_bbox_reject_reasons.csv')}")


if __name__ == "__main__":
    main()
