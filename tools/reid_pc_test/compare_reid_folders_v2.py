from pathlib import Path
import argparse
import csv
import statistics
import random
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


def cosine_similarity_matrix(features: torch.Tensor) -> torch.Tensor:
    features = F.normalize(features, p=2, dim=1)
    return features @ features.t()


def summarize_scores(sim: torch.Tensor, labels):
    same_scores = []
    diff_scores = []

    n = len(labels)
    for i in range(n):
        for j in range(i + 1, n):
            score = sim[i, j].item()
            if labels[i] == labels[j]:
                same_scores.append(score)
            else:
                diff_scores.append(score)

    def desc(values):
        if not values:
            return "无"
        return (
            f"count={len(values)}, "
            f"mean={statistics.mean(values):.3f}, "
            f"min={min(values):.3f}, "
            f"max={max(values):.3f}"
        )

    return same_scores, diff_scores, desc(same_scores), desc(diff_scores)


def compute_top1(sim: torch.Tensor, labels, image_paths):
    n = len(labels)
    rows = []
    correct = 0

    for i in range(n):
        scores = sim[i].clone()
        scores[i] = -999.0
        j = int(torch.argmax(scores).item())

        is_correct = labels[i] == labels[j]
        if is_correct:
            correct += 1

        rows.append({
            "query": str(image_paths[i]),
            "query_label": labels[i],
            "best_match": str(image_paths[j]),
            "best_label": labels[j],
            "score": scores[j].item(),
            "correct": is_correct,
        })

    return rows, correct / n


def identity_pair_summary(pairwise_rows):
    pair_scores = defaultdict(list)

    for row in pairwise_rows:
        key = tuple(sorted([row["label_a"], row["label_b"]]))
        pair_scores[key].append(row["score"])

    rows = []
    for pair, scores in pair_scores.items():
        rows.append({
            "identity_a": pair[0],
            "identity_b": pair[1],
            "count": len(scores),
            "mean": statistics.mean(scores),
            "min": min(scores),
            "max": max(scores),
        })

    rows.sort(key=lambda r: r["mean"], reverse=True)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="PC 端 ReID 基线测试：支持每个身份抽样数量、模型名、权重绝对/相对路径。"
    )
    parser.add_argument("--images", default="images", help="图片根目录，子文件夹名作为身份标签。默认 images")
    parser.add_argument("--weight", required=True, help="模型权重路径，可为绝对路径或相对 reid_pc_test 的路径")
    parser.add_argument("--model", default="osnet_x0_25", help="Torchreid 模型名，例如 osnet_x0_25 / osnet_x0_5")
    parser.add_argument("--per-id", type=int, default=None, help="每个身份抽取多少张图片。不填则使用全部图片")
    parser.add_argument("--sample-mode", choices=["random", "first"], default="random", help="抽样方式")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--allow-smaller", action="store_true", help="某身份图片不足 --per-id 时允许使用全部图片")
    parser.add_argument("--output-prefix", default="reid", help="输出文件名前缀")
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

    data = collect_by_identity(
        image_dir=image_dir,
        per_id=args.per_id,
        seed=args.seed,
        sample_mode=args.sample_mode,
        allow_smaller=args.allow_smaller,
    )

    image_paths, labels = flatten_data(data)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"[INFO] image_dir = {image_dir}")
    print(f"[INFO] weight = {weight_path}")
    print(f"[INFO] model = {args.model}")
    print(f"[INFO] device = {device}")
    print(f"[INFO] per_id = {args.per_id}")
    print(f"[INFO] sample_mode = {args.sample_mode}")
    print(f"[INFO] seed = {args.seed}")
    print("[INFO] identities:")
    for identity, paths in data.items():
        print(f"  {identity}: {len(paths)} images")
    print(f"[INFO] total_images = {len(image_paths)}")

    extractor = FeatureExtractor(
        model_name=args.model,
        model_path=str(weight_path),
        device=device
    )

    features = extractor([str(p) for p in image_paths])
    if not isinstance(features, torch.Tensor):
        features = torch.tensor(features)

    features = features.detach().cpu()
    print(f"[INFO] feature_shape = {tuple(features.shape)}")

    sim = cosine_similarity_matrix(features)

    same_scores, diff_scores, same_desc, diff_desc = summarize_scores(sim, labels)

    print("\n=== Summary ===")
    print(f"同一人相似度: {same_desc}")
    print(f"不同人相似度: {diff_desc}")

    if same_scores and diff_scores:
        print(f"均值差距 same_mean - diff_mean = {statistics.mean(same_scores) - statistics.mean(diff_scores):.3f}")

    top1_rows, top1_acc = compute_top1(sim, labels, image_paths)
    print(f"\nTop-1 最近邻身份正确率: {top1_acc:.3f}")

    rel_names = [str(p.relative_to(image_dir)) for p in image_paths]

    pairwise_rows = []
    n = len(image_paths)
    for i in range(n):
        for j in range(i + 1, n):
            pairwise_rows.append({
                "image_a": rel_names[i],
                "label_a": labels[i],
                "image_b": rel_names[j],
                "label_b": labels[j],
                "same_identity": labels[i] == labels[j],
                "score": sim[i, j].item(),
            })

    pair_summary = identity_pair_summary(pairwise_rows)

    print("\n=== Identity Pair Similarity Summary ===")
    for r in pair_summary:
        print(
            f"{r['identity_a']:>8s} vs {r['identity_b']:<8s} "
            f"count={r['count']:4d} mean={r['mean']:.3f} "
            f"min={r['min']:.3f} max={r['max']:.3f}"
        )

    prefix = args.output_prefix

    matrix_csv = output_dir / f"{prefix}_similarity_matrix.csv"
    with matrix_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["image"] + rel_names)
        for i, name in enumerate(rel_names):
            writer.writerow([name] + [f"{sim[i, j].item():.6f}" for j in range(len(rel_names))])

    pairwise_csv = output_dir / f"{prefix}_pairwise_scores.csv"
    with pairwise_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["image_a", "label_a", "image_b", "label_b", "same_identity", "score"]
        )
        writer.writeheader()
        for row in pairwise_rows:
            out = dict(row)
            out["score"] = f"{row['score']:.6f}"
            writer.writerow(out)

    top1_csv = output_dir / f"{prefix}_top1_matches.csv"
    with top1_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["query", "query_label", "best_match", "best_label", "score", "correct"]
        )
        writer.writeheader()
        for row in top1_rows:
            writer.writerow({
                "query": str(Path(row["query"]).relative_to(image_dir)),
                "query_label": row["query_label"],
                "best_match": str(Path(row["best_match"]).relative_to(image_dir)),
                "best_label": row["best_label"],
                "score": f"{row['score']:.6f}",
                "correct": row["correct"],
            })

    pair_summary_csv = output_dir / f"{prefix}_identity_pair_summary.csv"
    with pair_summary_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["identity_a", "identity_b", "count", "mean", "min", "max"]
        )
        writer.writeheader()
        for r in pair_summary:
            writer.writerow({
                "identity_a": r["identity_a"],
                "identity_b": r["identity_b"],
                "count": r["count"],
                "mean": f"{r['mean']:.6f}",
                "min": f"{r['min']:.6f}",
                "max": f"{r['max']:.6f}",
            })

    manifest_csv = output_dir / f"{prefix}_sample_manifest.csv"
    with manifest_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["image", "label"])
        for p, label in zip(image_paths, labels):
            writer.writerow([str(p.relative_to(image_dir)), label])

    print("\n[INFO] 已保存：")
    for p in [matrix_csv, pairwise_csv, top1_csv, pair_summary_csv, manifest_csv]:
        print(f"  {p}")


if __name__ == "__main__":
    main()
