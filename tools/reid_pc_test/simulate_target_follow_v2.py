from pathlib import Path
import argparse
import csv
import random
import statistics
import torch
import torch.nn.functional as F
from torchreid.utils import FeatureExtractor

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def resolve(root: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def collect(image_dir: Path, per_id=None, seed=42, sample_mode="random"):
    rng = random.Random(seed)
    data = {}
    for d in sorted([p for p in image_dir.iterdir() if p.is_dir()]):
        imgs = sorted([p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS])
        if not imgs:
            continue
        if per_id is not None and len(imgs) > per_id:
            if sample_mode == "even":
                idxs = [round(i * (len(imgs) - 1) / (per_id - 1)) for i in range(per_id)] if per_id > 1 else [len(imgs)//2]
                imgs = [imgs[i] for i in idxs]
            else:
                imgs = sorted(rng.sample(imgs, per_id))
        data[d.name] = imgs
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


def score_to_gallery(candidate_idx, gallery_indices, feats):
    return (feats[gallery_indices] @ feats[candidate_idx]).max().item()


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


def gate_present(rows, best_ths, margin_ths):
    out = []
    n = len(rows)
    for b in best_ths:
        for m in margin_ths:
            accepted = [r for r in rows if r["best_score"] >= b and r["margin"] >= m]
            correct = [r for r in accepted if r["correct"]]
            out.append({
                "best_threshold": b,
                "margin_threshold": m,
                "accepted_rate": len(accepted) / n if n else 0,
                "accepted_acc": len(correct) / len(accepted) if accepted else "",
                "true_accept_rate": len(correct) / n if n else 0,
                "reject_rate": 1 - (len(accepted) / n if n else 0),
            })
    return out


def gate_absent(rows, best_ths, margin_ths):
    out = []
    n = len(rows)
    for b in best_ths:
        for m in margin_ths:
            accepted = [r for r in rows if r["best_score"] >= b and r["margin"] >= m]
            out.append({
                "best_threshold": b,
                "margin_threshold": m,
                "false_accept_rate": len(accepted) / n if n else 0,
                "reject_rate": 1 - (len(accepted) / n if n else 0),
            })
    return out


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="images_openbot_clean")
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
    ap.add_argument("--absent-frames-per-target", type=int, default=50)
    ap.add_argument("--best-thresholds", default="0.70,0.75,0.80,0.85,0.90")
    ap.add_argument("--margin-thresholds", default="0.03,0.05,0.08,0.10")
    ap.add_argument("--output-prefix", default="target_follow_v2")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    image_dir = resolve(root, args.images)
    weight_path = resolve(root, args.weight)
    out_dir = root / "outputs"
    out_dir.mkdir(exist_ok=True)

    best_ths = [float(x) for x in args.best_thresholds.split(",") if x.strip()]
    margin_ths = [float(x) for x in args.margin_thresholds.split(",") if x.strip()]
    rng = random.Random(args.seed)

    data = collect(image_dir, args.per_id, args.seed, args.sample_mode)
    identities = sorted(data.keys())
    if args.distractors > len(identities) - 1:
        raise RuntimeError("distractors must be <= number of identities - 1")

    all_paths, labels = [], []
    for ident in identities:
        for p in data[ident]:
            all_paths.append(p)
            labels.append(ident)
    path_to_idx = {p: i for i, p in enumerate(all_paths)}
    idx_to_path = {i: p for p, i in path_to_idx.items()}
    idx_to_label = {i: labels[i] for i in range(len(labels))}

    print(f"[INFO] image_dir = {image_dir}")
    print(f"[INFO] weight = {weight_path}")
    print(f"[INFO] model = {args.model}")
    print(f"[INFO] identities:")
    for ident in identities:
        print(f"  {ident}: {len(data[ident])} images")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device = {device}")

    feats = extract(args.model, weight_path, all_paths, device)
    print(f"[INFO] feature_shape = {tuple(feats.shape)}")

    present_rows, absent_rows, gallery_rows = [], [], []
    for t in range(args.trials):
        gallery, probes = {}, {}
        for ident in identities:
            indices = [path_to_idx[p] for p in data[ident]]
            gal = select_gallery(indices, feats, args.gallery_k, args.gallery_strategy, rng)
            gallery[ident] = gal
            probes[ident] = [i for i in indices if i not in set(gal)]
            for gi in gal:
                gallery_rows.append({"trial": t, "identity": ident, "path": str(idx_to_path[gi].relative_to(image_dir))})

        # target present: one target candidate + N distractors
        for target in identities:
            if not probes[target]:
                continue
            others = [x for x in identities if x != target]
            for _ in range(args.frames_per_target):
                candidate_idxs = [rng.choice(probes[target])]
                for did in rng.sample(others, args.distractors):
                    pool = probes[did] or [path_to_idx[p] for p in data[did]]
                    candidate_idxs.append(rng.choice(pool))

                scored = [(ci, score_to_gallery(ci, gallery[target], feats)) for ci in candidate_idxs]
                ranked = sorted(scored, key=lambda x: x[1], reverse=True)
                best_idx, best_score = ranked[0]
                second_score = ranked[1][1]
                present_rows.append({
                    "trial": t,
                    "target_identity": target,
                    "best_label": idx_to_label[best_idx],
                    "best_path": str(idx_to_path[best_idx].relative_to(image_dir)),
                    "best_score": best_score,
                    "second_score": second_score,
                    "margin": best_score - second_score,
                    "correct": idx_to_label[best_idx] == target,
                })

        # target absent: target gallery exists, but current candidates are all distractors
        for target in identities:
            others = [x for x in identities if x != target]
            for _ in range(args.absent_frames_per_target):
                candidate_idxs = []
                for did in rng.sample(others, args.distractors):
                    pool = probes[did] or [path_to_idx[p] for p in data[did]]
                    candidate_idxs.append(rng.choice(pool))

                scored = [(ci, score_to_gallery(ci, gallery[target], feats)) for ci in candidate_idxs]
                ranked = sorted(scored, key=lambda x: x[1], reverse=True)
                best_idx, best_score = ranked[0]
                second_score = ranked[1][1]
                absent_rows.append({
                    "trial": t,
                    "target_identity": target,
                    "best_label": idx_to_label[best_idx],
                    "best_path": str(idx_to_path[best_idx].relative_to(image_dir)),
                    "best_score": best_score,
                    "second_score": second_score,
                    "margin": best_score - second_score,
                })

    present_top1 = sum(r["correct"] for r in present_rows) / len(present_rows)
    present_best = stat([r["best_score"] for r in present_rows])
    present_margin = stat([r["margin"] for r in present_rows])
    absent_best = stat([r["best_score"] for r in absent_rows])
    absent_margin = stat([r["margin"] for r in absent_rows])
    pg = gate_present(present_rows, best_ths, margin_ths)
    ag = gate_absent(absent_rows, best_ths, margin_ths)

    print("\n=== Target-present frame simulation ===")
    print(f"total_frames = {len(present_rows)}")
    print(f"top1_target_selected_acc = {present_top1:.3f}")
    print(f"best_score mean={present_best['mean']:.3f}, p25={present_best['p25']:.3f}, median={present_best['median']:.3f}, p75={present_best['p75']:.3f}, max={present_best['max']:.3f}")
    print(f"margin mean={present_margin['mean']:.3f}, p25={present_margin['p25']:.3f}, median={present_margin['median']:.3f}, p75={present_margin['p75']:.3f}, max={present_margin['max']:.3f}")

    print("\nGate grid when target is present:")
    for r in pg:
        acc = "None" if r["accepted_acc"] == "" else f"{r['accepted_acc']:.3f}"
        print(f"best>={r['best_threshold']:.2f}, margin>={r['margin_threshold']:.3f}: accepted_rate={r['accepted_rate']:.3f}, accepted_acc={acc}, true_accept_rate={r['true_accept_rate']:.3f}, reject_rate={r['reject_rate']:.3f}")

    print("\n=== Target-absent frame simulation ===")
    print(f"total_absent_frames = {len(absent_rows)}")
    print(f"best_score mean={absent_best['mean']:.3f}, p25={absent_best['p25']:.3f}, median={absent_best['median']:.3f}, p75={absent_best['p75']:.3f}, max={absent_best['max']:.3f}")
    print(f"margin mean={absent_margin['mean']:.3f}, p25={absent_margin['p25']:.3f}, median={absent_margin['median']:.3f}, p75={absent_margin['p75']:.3f}, max={absent_margin['max']:.3f}")

    print("\nGate grid when target is absent:")
    for r in ag:
        print(f"best>={r['best_threshold']:.2f}, margin>={r['margin_threshold']:.3f}: false_accept_rate={r['false_accept_rate']:.3f}, reject_rate={r['reject_rate']:.3f}")

    write_csv(out_dir / f"{args.output_prefix}_target_present_rows.csv", present_rows,
              ["trial", "target_identity", "best_label", "best_path", "best_score", "second_score", "margin", "correct"])
    write_csv(out_dir / f"{args.output_prefix}_target_absent_rows.csv", absent_rows,
              ["trial", "target_identity", "best_label", "best_path", "best_score", "second_score", "margin"])
    write_csv(out_dir / f"{args.output_prefix}_present_gate_grid.csv", pg,
              ["best_threshold", "margin_threshold", "accepted_rate", "accepted_acc", "true_accept_rate", "reject_rate"])
    write_csv(out_dir / f"{args.output_prefix}_absent_gate_grid.csv", ag,
              ["best_threshold", "margin_threshold", "false_accept_rate", "reject_rate"])
    write_csv(out_dir / f"{args.output_prefix}_gallery_selected.csv", gallery_rows,
              ["trial", "identity", "path"])

    print("\n[INFO] saved:")
    print(f"  {out_dir / (args.output_prefix + '_present_gate_grid.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_absent_gate_grid.csv')}")


if __name__ == "__main__":
    main()
