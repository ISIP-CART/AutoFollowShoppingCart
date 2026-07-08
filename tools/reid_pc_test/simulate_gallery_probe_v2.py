from pathlib import Path
import argparse
import csv
import random
import statistics
from collections import defaultdict

import torch
import torch.nn.functional as F
from torchreid.utils import FeatureExtractor


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def resolve_path(path_str: str, root: Path) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p.resolve()
    return (root / p).resolve()


def collect_by_identity(image_dir: Path, per_id: int | None, seed: int, sample_mode: str, allow_smaller: bool):
    rng = random.Random(seed)
    data = {}

    for person_dir in sorted([p for p in image_dir.iterdir() if p.is_dir()]):
        images = sorted([
            p for p in person_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        ])

        if not images:
            continue

        if per_id is not None:
            if len(images) < per_id and not allow_smaller:
                raise RuntimeError(
                    f"{person_dir.name} 只有 {len(images)} 张，不足 --per-id {per_id}。"
                    f"可减少 --per-id 或加 --allow-smaller。"
                )

            k = min(per_id, len(images))
            if sample_mode == "random":
                images = sorted(rng.sample(images, k))
            elif sample_mode == "first":
                images = images[:k]
            else:
                raise ValueError(f"未知 sample_mode: {sample_mode}")

        data[person_dir.name] = images

    if not data:
        raise RuntimeError(f"没有在 {image_dir} 下找到身份子文件夹和图片。")

    return data


def flatten_data(data):
    image_paths = []
    labels = []
    for identity, paths in data.items():
        for p in paths:
            image_paths.append(p)
            labels.append(identity)
    return image_paths, labels


def extract_features(extractor, all_paths):
    features = extractor([str(p) for p in all_paths])
    if not isinstance(features, torch.Tensor):
        features = torch.tensor(features)
    return F.normalize(features.detach().cpu(), p=2, dim=1)


def select_gallery_random(paths, k, rng):
    return rng.sample(paths, k)


def select_gallery_diverse(paths, k, features, path_to_idx):
    """
    多样性选择：先选“中心样本”，再用 farthest-first 选择和已有 gallery 最不相似的样本。
    这会让 gallery 覆盖更大的姿态/视角/局部变化。
    """
    if k >= len(paths):
        return list(paths)

    idxs = [path_to_idx[p] for p in paths]
    feats = features[idxs]
    sim = feats @ feats.t()

    # 第一张选中心样本：与同身份其他图片平均相似度最高，避免从极端 outlier 开始。
    avg_sim = sim.mean(dim=1)
    first_local = int(torch.argmax(avg_sim).item())

    selected_local = [first_local]
    remaining = set(range(len(paths)))
    remaining.remove(first_local)

    while len(selected_local) < k:
        best_local = None
        best_novelty = -1.0

        selected_tensor = torch.tensor(selected_local, dtype=torch.long)

        for cand in remaining:
            # cand 和当前 gallery 的最高相似度越低，说明它越“新”、越能补充不同视角。
            max_sim_to_selected = sim[cand, selected_tensor].max().item()
            novelty = 1.0 - max_sim_to_selected

            if novelty > best_novelty:
                best_novelty = novelty
                best_local = cand

        selected_local.append(best_local)
        remaining.remove(best_local)

    return [paths[i] for i in selected_local]


def load_manual_gallery_csv(csv_path: Path, image_dir: Path):
    """
    CSV 格式：
    identity,path
    ysy,ysy/xxx.jpg
    rxy,rxy/xxx.jpg
    """
    gallery = defaultdict(list)
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            identity = row["identity"]
            p = image_dir / row["path"]
            if not p.exists():
                raise RuntimeError(f"manual gallery 图片不存在：{p}")
            gallery[identity].append(p)
    return dict(gallery)


def build_gallery(strategy, data, k, rng, features, path_to_idx, manual_gallery):
    gallery = {}

    if strategy == "manual":
        if manual_gallery is None:
            raise RuntimeError("--gallery-strategy manual 需要提供 --manual-gallery-csv")
        for identity, paths in manual_gallery.items():
            if len(paths) < k:
                raise RuntimeError(f"{identity} manual gallery 只有 {len(paths)} 张，不足 gallery-k={k}")
            gallery[identity] = paths[:k]
        return gallery

    for identity, paths in data.items():
        if len(paths) <= k:
            raise RuntimeError(f"{identity} 图片数 {len(paths)} 必须大于 gallery-k={k}")

        if strategy == "random":
            gallery[identity] = select_gallery_random(paths, k, rng)
        elif strategy == "diverse":
            gallery[identity] = select_gallery_diverse(paths, k, features, path_to_idx)
        else:
            raise ValueError(f"未知 gallery strategy: {strategy}")

    return gallery


def evaluate_once(data, gallery, features, path_to_idx, image_dir, margin_thresholds):
    probes = []
    for identity, paths in data.items():
        gallery_set = set(gallery[identity])
        for p in paths:
            if p not in gallery_set:
                probes.append((identity, p))

    results = []
    for true_identity, probe_path in probes:
        probe_feature = features[path_to_idx[probe_path]]
        identity_scores = {}

        for identity, gallery_paths in gallery.items():
            gallery_indices = [path_to_idx[p] for p in gallery_paths]
            gallery_features = features[gallery_indices]
            sims = gallery_features @ probe_feature
            identity_scores[identity] = sims.max().item()

        ranked = sorted(identity_scores.items(), key=lambda x: x[1], reverse=True)
        pred_identity = ranked[0][0]
        best_score = ranked[0][1]
        second_score = ranked[1][1]
        margin = best_score - second_score
        correct = pred_identity == true_identity

        row = {
            "probe": str(probe_path.relative_to(image_dir)),
            "true": true_identity,
            "pred": pred_identity,
            "best_score": best_score,
            "second_score": second_score,
            "margin": margin,
            "correct": correct,
        }
        results.append(row)

    metrics_by_threshold = {}
    for th in margin_thresholds:
        accepted = [r for r in results if r["margin"] >= th]
        accepted_count = len(accepted)
        total = len(results)
        accepted_rate = accepted_count / total if total else 0.0
        reject_rate = 1.0 - accepted_rate

        if accepted_count:
            accepted_acc = sum(1 for r in accepted if r["correct"]) / accepted_count
        else:
            accepted_acc = None

        metrics_by_threshold[th] = {
            "total": total,
            "accepted": accepted_count,
            "accepted_rate": accepted_rate,
            "reject_rate": reject_rate,
            "accepted_acc": accepted_acc,
        }

    acc = sum(1 for r in results if r["correct"]) / len(results)
    mean_margin = statistics.mean([r["margin"] for r in results]) if results else 0.0

    return results, acc, mean_margin, metrics_by_threshold


def main():
    parser = argparse.ArgumentParser(
        description="Gallery-Probe ReID 模拟：支持每身份抽样数量、随机/多样性 gallery、拒绝阈值评估、权重绝对/相对路径。"
    )
    parser.add_argument("--images", default="images", help="图片根目录，子文件夹名作为身份标签。默认 images")
    parser.add_argument("--weight", required=True, help="模型权重路径，可为绝对路径或相对 reid_pc_test 的路径")
    parser.add_argument("--model", default="osnet_x0_25", help="Torchreid 模型名")
    parser.add_argument("--per-id", type=int, default=None, help="每个身份抽取多少张图片。不填则使用全部")
    parser.add_argument("--sample-mode", choices=["random", "first"], default="random")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--allow-smaller", action="store_true")
    parser.add_argument("--gallery-k", type=int, default=5)
    parser.add_argument("--gallery-strategy", choices=["random", "diverse", "manual"], default="random")
    parser.add_argument("--trials", type=int, default=50, help="random gallery 时有效；diverse/manual 通常 1 次即可")
    parser.add_argument("--manual-gallery-csv", default=None, help="manual gallery CSV：identity,path")
    parser.add_argument(
        "--margin-thresholds",
        default="0,0.03,0.05,0.08,0.10",
        help="拒绝阈值列表，逗号分隔。例如 0,0.03,0.05,0.08,0.10"
    )
    parser.add_argument("--output-prefix", default="gallery_probe")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    image_dir = resolve_path(args.images, root)
    weight_path = resolve_path(args.weight, root)
    output_dir = root / "outputs"
    output_dir.mkdir(exist_ok=True)

    if not image_dir.exists():
        raise RuntimeError(f"图片目录不存在：{image_dir}")
    if not weight_path.exists():
        raise RuntimeError(f"权重文件不存在：{weight_path}")

    margin_thresholds = [float(x.strip()) for x in args.margin_thresholds.split(",") if x.strip()]

    data = collect_by_identity(
        image_dir=image_dir,
        per_id=args.per_id,
        seed=args.seed,
        sample_mode=args.sample_mode,
        allow_smaller=args.allow_smaller,
    )

    all_paths, labels = flatten_data(data)
    path_to_idx = {p: i for i, p in enumerate(all_paths)}

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"[INFO] image_dir = {image_dir}")
    print(f"[INFO] weight = {weight_path}")
    print(f"[INFO] model = {args.model}")
    print(f"[INFO] device = {device}")
    print(f"[INFO] per_id = {args.per_id}")
    print(f"[INFO] sample_mode = {args.sample_mode}")
    print(f"[INFO] gallery_k = {args.gallery_k}")
    print(f"[INFO] gallery_strategy = {args.gallery_strategy}")
    print("[INFO] identities:")
    for identity, paths in data.items():
        print(f"  {identity}: {len(paths)} images")

    extractor = FeatureExtractor(
        model_name=args.model,
        model_path=str(weight_path),
        device=device
    )
    features = extract_features(extractor, all_paths)
    print(f"[INFO] feature_shape = {tuple(features.shape)}")

    manual_gallery = None
    if args.manual_gallery_csv:
        manual_gallery = load_manual_gallery_csv(resolve_path(args.manual_gallery_csv, root), image_dir)

    trials = args.trials if args.gallery_strategy == "random" else 1
    rng = random.Random(args.seed)

    all_trial_accs = []
    all_trial_margins = []
    all_fail_cases = []
    all_reject_metrics = defaultdict(list)
    gallery_records = []

    for t in range(trials):
        trial_rng = random.Random(args.seed + t)

        gallery = build_gallery(
            strategy=args.gallery_strategy,
            data=data,
            k=args.gallery_k,
            rng=trial_rng,
            features=features,
            path_to_idx=path_to_idx,
            manual_gallery=manual_gallery,
        )

        for identity, paths in gallery.items():
            for p in paths:
                gallery_records.append({
                    "trial": t,
                    "identity": identity,
                    "path": str(p.relative_to(image_dir)),
                    "strategy": args.gallery_strategy,
                })

        results, acc, mean_margin, metrics_by_threshold = evaluate_once(
            data=data,
            gallery=gallery,
            features=features,
            path_to_idx=path_to_idx,
            image_dir=image_dir,
            margin_thresholds=margin_thresholds,
        )

        all_trial_accs.append(acc)
        all_trial_margins.append(mean_margin)

        for r in results:
            if not r["correct"]:
                out = dict(r)
                out["trial"] = t
                all_fail_cases.append(out)

        for th, metrics in metrics_by_threshold.items():
            all_reject_metrics[th].append(metrics)

    print("\n=== Gallery-Probe Simulation ===")
    print(f"model = {args.model}")
    print(f"gallery_k = {args.gallery_k}")
    print(f"gallery_strategy = {args.gallery_strategy}")
    print(f"trials = {trials}")
    print(f"mean_acc = {statistics.mean(all_trial_accs):.3f}")
    print(f"min_acc = {min(all_trial_accs):.3f}")
    print(f"max_acc = {max(all_trial_accs):.3f}")
    print(f"mean_margin = {statistics.mean(all_trial_margins):.3f}")
    print(f"min_margin = {min(all_trial_margins):.3f}")
    print(f"max_margin = {max(all_trial_margins):.3f}")

    print("\n=== Reject Evaluation by margin threshold ===")
    reject_summary_rows = []
    for th in margin_thresholds:
        ms = all_reject_metrics[th]
        accepted_rates = [m["accepted_rate"] for m in ms]
        reject_rates = [m["reject_rate"] for m in ms]
        accs = [m["accepted_acc"] for m in ms if m["accepted_acc"] is not None]

        mean_accepted_rate = statistics.mean(accepted_rates) if accepted_rates else 0.0
        mean_reject_rate = statistics.mean(reject_rates) if reject_rates else 0.0
        mean_accepted_acc = statistics.mean(accs) if accs else None

        reject_summary_rows.append({
            "threshold": th,
            "accepted_rate": mean_accepted_rate,
            "reject_rate": mean_reject_rate,
            "accepted_acc": mean_accepted_acc,
        })

        acc_text = "None" if mean_accepted_acc is None else f"{mean_accepted_acc:.3f}"
        print(
            f"margin >= {th:.3f}: "
            f"accepted_rate={mean_accepted_rate:.3f}, "
            f"accepted_acc={acc_text}, "
            f"reject_rate={mean_reject_rate:.3f}"
        )

    print("\n=== Fail Cases: first 20 ===")
    for case in all_fail_cases[:20]:
        print(
            f"trial={case['trial']} probe={case['probe']} "
            f"true={case['true']} pred={case['pred']} "
            f"best={case['best_score']:.3f} "
            f"second={case['second_score']:.3f} "
            f"margin={case['margin']:.3f}"
        )

    prefix = args.output_prefix

    fail_csv = output_dir / f"{prefix}_fail_cases.csv"
    with fail_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["trial", "probe", "true", "pred", "best_score", "second_score", "margin", "correct"]
        )
        writer.writeheader()
        for r in all_fail_cases:
            writer.writerow({
                "trial": r["trial"],
                "probe": r["probe"],
                "true": r["true"],
                "pred": r["pred"],
                "best_score": f"{r['best_score']:.6f}",
                "second_score": f"{r['second_score']:.6f}",
                "margin": f"{r['margin']:.6f}",
                "correct": r["correct"],
            })

    gallery_csv = output_dir / f"{prefix}_gallery_selected.csv"
    with gallery_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["trial", "identity", "path", "strategy"])
        writer.writeheader()
        writer.writerows(gallery_records)

    reject_csv = output_dir / f"{prefix}_reject_summary.csv"
    with reject_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["threshold", "accepted_rate", "accepted_acc", "reject_rate"])
        writer.writeheader()
        for r in reject_summary_rows:
            writer.writerow({
                "threshold": f"{r['threshold']:.6f}",
                "accepted_rate": f"{r['accepted_rate']:.6f}",
                "accepted_acc": "" if r["accepted_acc"] is None else f"{r['accepted_acc']:.6f}",
                "reject_rate": f"{r['reject_rate']:.6f}",
            })

    print("\n[INFO] 已保存：")
    for p in [fail_csv, gallery_csv, reject_csv]:
        print(f"  {p}")


if __name__ == "__main__":
    main()
