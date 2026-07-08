from pathlib import Path
import csv
from collections import defaultdict
import statistics


ROOT = Path(__file__).resolve().parent
PAIRWISE_CSV = ROOT / "outputs" / "pairwise_scores.csv"


def main():
    pair_scores = defaultdict(list)

    with PAIRWISE_CSV.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            label_a = row["label_a"]
            label_b = row["label_b"]
            score = float(row["score"])

            key = tuple(sorted([label_a, label_b]))
            pair_scores[key].append(score)

    print("=== Identity Pair Similarity Summary ===")

    rows = []
    for pair, scores in pair_scores.items():
        mean_score = statistics.mean(scores)
        min_score = min(scores)
        max_score = max(scores)

        rows.append((pair, len(scores), mean_score, min_score, max_score))

    rows.sort(key=lambda x: x[2], reverse=True)

    for pair, count, mean_score, min_score, max_score in rows:
        print(
            f"{pair[0]:>8s} vs {pair[1]:<8s} "
            f"count={count:4d} "
            f"mean={mean_score:.3f} "
            f"min={min_score:.3f} "
            f"max={max_score:.3f}"
        )


if __name__ == "__main__":
    main()