from pathlib import Path
import argparse
import random
import statistics
from collections import defaultdict

import torch
import torch.nn.functional as F
from torchreid.utils import FeatureExtractor


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def collect_by_identity(image_dir: Path):
    data = {}

    for person_dir in sorted([p for p in image_dir.iterdir() if p.is_dir()]):
        images = sorted([
            p for p in person_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        ])
        if images:
            data[person_dir.name] = images

    return data


def extract_features(extractor, all_paths):
    features = extractor([str(p) for p in all_paths])

    if not isinstance(features, torch.Tensor):
        features = torch.tensor(features)

    features = F.normalize(features.detach().cpu(), p=2, dim=1)
    return features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", default="images")
    parser.add_argument("--weight", required=True)
    parser.add_argument("--model", default="osnet_x0_25")
    parser.add_argument("--gallery-k", type=int, default=5)
    parser.add_argument("--trials", type=int, default=50)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    image_dir = (root / args.images).resolve()
    weight_path = (root / args.weight).resolve()

    data = collect_by_identity(image_dir)

    print(f"[INFO] identities = {list(data.keys())}")
    for identity, paths in data.items():
        print(f"  {identity}: {len(paths)} images")

    min_count = min(len(v) for v in data.values())
    if min_count <= args.gallery_k:
        raise RuntimeError("每个身份的图片数量必须大于 gallery-k")

    all_paths = []
    labels = []

    for identity, paths in data.items():
        for p in paths:
            all_paths.append(p)
            labels.append(identity)

    path_to_idx = {p: i for i, p in enumerate(all_paths)}

    device = "cuda" if torch.cuda.is_available() else "cpu"

    extractor = FeatureExtractor(
        model_name=args.model,
        model_path=str(weight_path),
        device=device
    )

    features = extract_features(extractor, all_paths)

    trial_accs = []
    trial_margins = []
    fail_cases = []

    rng = random.Random(42)

    for t in range(args.trials):
        gallery = {}
        probes = []

        for identity, paths in data.items():
            selected = rng.sample(paths, args.gallery_k)
            gallery[identity] = selected

            for p in paths:
                if p not in selected:
                    probes.append((identity, p))

        correct = 0

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

            trial_margins.append(margin)

            if pred_identity == true_identity:
                correct += 1
            else:
                fail_cases.append({
                    "trial": t,
                    "probe": str(probe_path.relative_to(image_dir)),
                    "true": true_identity,
                    "pred": pred_identity,
                    "best_score": best_score,
                    "second_score": second_score,
                    "margin": margin,
                })

        acc = correct / len(probes)
        trial_accs.append(acc)

    print("\n=== Gallery-Probe Simulation ===")
    print(f"model = {args.model}")
    print(f"gallery_k = {args.gallery_k}")
    print(f"trials = {args.trials}")
    print(f"mean_acc = {statistics.mean(trial_accs):.3f}")
    print(f"min_acc = {min(trial_accs):.3f}")
    print(f"max_acc = {max(trial_accs):.3f}")

    if trial_margins:
        print(f"mean_margin = {statistics.mean(trial_margins):.3f}")
        print(f"min_margin = {min(trial_margins):.3f}")
        print(f"max_margin = {max(trial_margins):.3f}")

    print("\n=== Fail Cases: first 20 ===")
    for case in fail_cases[:20]:
        print(
            f"trial={case['trial']} "
            f"probe={case['probe']} "
            f"true={case['true']} "
            f"pred={case['pred']} "
            f"best={case['best_score']:.3f} "
            f"second={case['second_score']:.3f} "
            f"margin={case['margin']:.3f}"
        )

    out_path = root / "outputs" / "gallery_probe_fail_cases.csv"
    out_path.parent.mkdir(exist_ok=True)

    with out_path.open("w", encoding="utf-8-sig") as f:
        f.write("trial,probe,true,pred,best_score,second_score,margin\n")
        for case in fail_cases:
            f.write(
                f"{case['trial']},{case['probe']},{case['true']},{case['pred']},"
                f"{case['best_score']:.6f},{case['second_score']:.6f},{case['margin']:.6f}\n"
            )

    print(f"\n[INFO] fail cases saved to {out_path}")


if __name__ == "__main__":
    main()