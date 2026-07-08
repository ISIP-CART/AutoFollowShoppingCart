from pathlib import Path
import argparse
import csv
import statistics

import torch
import torch.nn.functional as F
from torchreid.utils import FeatureExtractor


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def collect_images(image_dir: Path):
    image_paths = sorted(
        p for p in image_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )

    if not image_paths:
        raise RuntimeError(f"没有在 {image_dir} 下找到图片。")

    labels = [p.parent.name for p in image_paths]
    return image_paths, labels


def cosine_similarity_matrix(features: torch.Tensor) -> torch.Tensor:
    """
    features: [N, D]
    return:   [N, N]
    """
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
        scores[i] = -999.0  # 排除自己
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

    top1_acc = correct / n
    return rows, top1_acc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--images",
        type=str,
        default="images",
        help="图片根目录，默认 images。其子文件夹名会作为身份标签。"
    )
    parser.add_argument(
        "--weight",
        type=str,
        required=True,
        help="OSNet 权重路径，例如 weights/osnet_x0_25_market1501.pth"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="osnet_x0_25",
        help="模型名，默认 osnet_x0_25"
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    image_dir = (root / args.images).resolve()
    weight_path = (root / args.weight).resolve()
    output_dir = root / "outputs"
    output_dir.mkdir(exist_ok=True)

    if not weight_path.exists():
        raise RuntimeError(f"权重文件不存在：{weight_path}")

    image_paths, labels = collect_images(image_dir)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"[INFO] image_dir = {image_dir}")
    print(f"[INFO] weight = {weight_path}")
    print(f"[INFO] model = {args.model}")
    print(f"[INFO] device = {device}")
    print(f"[INFO] num_images = {len(image_paths)}")
    print(f"[INFO] identities = {sorted(set(labels))}")

    extractor = FeatureExtractor(
        model_name=args.model,
        model_path=str(weight_path),
        device=device
    )

    # Torchreid 官方 FeatureExtractor 可以直接接收图片路径列表并输出特征。
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
        print(
            f"均值差距 same_mean - diff_mean = "
            f"{statistics.mean(same_scores) - statistics.mean(diff_scores):.3f}"
        )

    top1_rows, top1_acc = compute_top1(sim, labels, image_paths)
    print(f"\nTop-1 最近邻身份正确率: {top1_acc:.3f}")

    print("\n=== Top-1 nearest match for each image ===")
    for row in top1_rows:
        print(
            f"{Path(row['query']).relative_to(image_dir)} "
            f"({row['query_label']}) -> "
            f"{Path(row['best_match']).relative_to(image_dir)} "
            f"({row['best_label']}), "
            f"score={row['score']:.3f}, "
            f"correct={row['correct']}"
        )

    # 保存相似度矩阵
    matrix_csv = output_dir / "similarity_matrix.csv"
    rel_names = [str(p.relative_to(image_dir)) for p in image_paths]

    with matrix_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["image"] + rel_names)
        for i, name in enumerate(rel_names):
            writer.writerow([name] + [f"{sim[i, j].item():.6f}" for j in range(len(rel_names))])

    # 保存两两分数
    pairwise_csv = output_dir / "pairwise_scores.csv"
    with pairwise_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["image_a", "label_a", "image_b", "label_b", "same_identity", "score"])
        n = len(image_paths)
        for i in range(n):
            for j in range(i + 1, n):
                writer.writerow([
                    rel_names[i],
                    labels[i],
                    rel_names[j],
                    labels[j],
                    labels[i] == labels[j],
                    f"{sim[i, j].item():.6f}",
                ])

    # 保存每张图的最近邻
    top1_csv = output_dir / "top1_matches.csv"
    with top1_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "query_label", "best_match", "best_label", "score", "correct"])
        for row in top1_rows:
            writer.writerow([
                str(Path(row["query"]).relative_to(image_dir)),
                row["query_label"],
                str(Path(row["best_match"]).relative_to(image_dir)),
                row["best_label"],
                f"{row['score']:.6f}",
                row["correct"],
            ])

    print("\n[INFO] 已保存：")
    print(f"  {matrix_csv}")
    print(f"  {pairwise_csv}")
    print(f"  {top1_csv}")


if __name__ == "__main__":
    main()