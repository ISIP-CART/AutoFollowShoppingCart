from pathlib import Path
import argparse
import random
import statistics
import csv
from typing import Dict, List, Tuple

import torch
import torch.nn.functional as F
from torchreid.utils import FeatureExtractor

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def resolve_path(root: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (root / path).resolve()


def collect_by_identity(image_dir: Path) -> Dict[str, List[Path]]:
    data: Dict[str, List[Path]] = {}
    for person_dir in sorted([p for p in image_dir.iterdir() if p.is_dir()]):
        images = sorted([p for p in person_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS])
        if images:
            data[person_dir.name] = images
    if len(data) < 2:
        raise RuntimeError('至少需要 2 个身份文件夹。')
    return data


def sample_per_id(data: Dict[str, List[Path]], per_id: int | None, seed: int) -> Dict[str, List[Path]]:
    rng = random.Random(seed)
    out: Dict[str, List[Path]] = {}
    for ident, paths in data.items():
        if per_id is None or per_id <= 0 or len(paths) <= per_id:
            out[ident] = list(paths)
        else:
            out[ident] = sorted(rng.sample(paths, per_id))
    return out


def extract_all_features(extractor, all_paths: List[Path]) -> torch.Tensor:
    feats = extractor([str(p) for p in all_paths])
    if not isinstance(feats, torch.Tensor):
        feats = torch.tensor(feats)
    return F.normalize(feats.detach().cpu(), p=2, dim=1)


def choose_gallery(paths: List[Path], features: torch.Tensor, path_to_idx: Dict[Path, int], k: int, strategy: str, rng: random.Random) -> List[Path]:
    if len(paths) <= k:
        return list(paths)
    if strategy == 'random':
        return sorted(rng.sample(paths, k))
    if strategy != 'diverse':
        raise ValueError(f'unknown gallery strategy: {strategy}')

    idxs = [path_to_idx[p] for p in paths]
    feats = features[idxs]

    # 先选最靠近该身份特征均值的一张作为“中心锚点”，再做 farthest-first 多样性扩展。
    centroid = F.normalize(feats.mean(dim=0, keepdim=True), p=2, dim=1)[0]
    sim_to_centroid = feats @ centroid
    first_local = int(torch.argmax(sim_to_centroid).item())

    selected_local = [first_local]
    remaining = set(range(len(paths)))
    remaining.remove(first_local)

    while len(selected_local) < k and remaining:
        best_local = None
        best_diversity = None
        selected_feats = feats[selected_local]
        for cand in remaining:
            # cand 和当前 gallery 的最大相似度越低，说明越“新颖 / 不冗余”。
            max_sim_to_gallery = torch.max(selected_feats @ feats[cand]).item()
            diversity = -max_sim_to_gallery
            if best_diversity is None or diversity > best_diversity:
                best_diversity = diversity
                best_local = cand
        selected_local.append(best_local)
        remaining.remove(best_local)

    return [paths[i] for i in selected_local]


def score_candidate(candidate_path: Path, gallery_paths: List[Path], features: torch.Tensor, path_to_idx: Dict[Path, int]) -> float:
    cand_feat = features[path_to_idx[candidate_path]]
    gallery_feats = features[[path_to_idx[p] for p in gallery_paths]]
    return torch.max(gallery_feats @ cand_feat).item()


def percentile(values: List[float], q: float):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def summarize_reject(rows: List[dict], thresholds: List[float], key_correct='correct'):
    summary = []
    total = len(rows)
    for th in thresholds:
        accepted = [r for r in rows if r['margin'] >= th]
        if accepted:
            acc = sum(1 for r in accepted if r[key_correct]) / len(accepted)
        else:
            acc = None
        summary.append({
            'margin_threshold': th,
            'accepted_rate': len(accepted) / total if total else 0.0,
            'accepted_acc': acc,
            'reject_rate': 1 - (len(accepted) / total if total else 0.0),
            'accepted_count': len(accepted),
            'total': total,
        })
    return summary


def main():
    parser = argparse.ArgumentParser(description='Simulate shopping-cart target-following ReID: one target gallery vs candidates in a frame.')
    parser.add_argument('--images', default='images')
    parser.add_argument('--per-id', type=int, default=None, help='每个身份最多抽取多少张；不填则使用全部。')
    parser.add_argument('--sample-seed', type=int, default=42)
    parser.add_argument('--model', default='osnet_x0_25')
    parser.add_argument('--weight', required=True)
    parser.add_argument('--gallery-k', type=int, default=5)
    parser.add_argument('--gallery-strategy', choices=['random', 'diverse'], default='diverse')
    parser.add_argument('--trials', type=int, default=50, help='random gallery 建议 50；diverse 可设 1 或更多用于不同 frame 采样。')
    parser.add_argument('--frames-per-target', type=int, default=50, help='每个 target 身份每轮模拟多少个含目标 frame。')
    parser.add_argument('--distractors', type=int, default=2, help='每个 frame 中非目标候选人数。')
    parser.add_argument('--absent-frames-per-target', type=int, default=50, help='每个 target 身份每轮模拟多少个目标缺席 frame。')
    parser.add_argument('--output-prefix', default='target_follow')
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    image_dir = resolve_path(root, args.images)
    weight_path = resolve_path(root, args.weight)
    out_dir = root / 'outputs'
    out_dir.mkdir(exist_ok=True)

    data_all = collect_by_identity(image_dir)
    data = sample_per_id(data_all, args.per_id, args.sample_seed)

    print(f'[INFO] image_dir = {image_dir}')
    print(f'[INFO] weight = {weight_path}')
    print(f'[INFO] model = {args.model}')
    print(f'[INFO] per_id = {args.per_id}')
    print(f'[INFO] gallery_k = {args.gallery_k}')
    print(f'[INFO] gallery_strategy = {args.gallery_strategy}')
    print(f'[INFO] distractors = {args.distractors}')
    print('[INFO] identities:')
    for ident, paths in data.items():
        print(f'  {ident}: {len(paths)} images')
        if len(paths) <= args.gallery_k:
            raise RuntimeError(f'{ident} 图片数量必须大于 gallery-k。')

    all_paths: List[Path] = []
    for paths in data.values():
        all_paths.extend(paths)
    path_to_idx = {p: i for i, p in enumerate(all_paths)}

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'[INFO] device = {device}')
    extractor = FeatureExtractor(model_name=args.model, model_path=str(weight_path), device=device)
    features = extract_all_features(extractor, all_paths)
    print(f'[INFO] feature_shape = {tuple(features.shape)}')

    thresholds = [0.0, 0.03, 0.05, 0.08, 0.10]
    rng_master = random.Random(args.sample_seed)
    identities = list(data.keys())
    follow_rows = []
    absent_rows = []
    gallery_rows = []

    for trial in range(args.trials):
        rng = random.Random(rng_master.randint(0, 10**9))

        galleries: Dict[str, List[Path]] = {}
        probes_by_id: Dict[str, List[Path]] = {}

        for ident, paths in data.items():
            gallery = choose_gallery(paths, features, path_to_idx, args.gallery_k, args.gallery_strategy, rng)
            galleries[ident] = gallery
            gallery_set = set(gallery)
            probes = [p for p in paths if p not in gallery_set]
            probes_by_id[ident] = probes
            for p in gallery:
                gallery_rows.append({'trial': trial, 'identity': ident, 'path': str(p.relative_to(image_dir))})

        # 含目标 frame：候选列表中有 1 个目标 + N 个干扰人。
        for target_ident in identities:
            if not probes_by_id[target_ident]:
                continue
            other_idents = [x for x in identities if x != target_ident]
            for _ in range(args.frames_per_target):
                target_probe = rng.choice(probes_by_id[target_ident])
                frame_candidates: List[Tuple[str, Path, bool]] = [(target_ident, target_probe, True)]

                chosen_distractor_idents = [rng.choice(other_idents) for _ in range(args.distractors)]
                for did in chosen_distractor_idents:
                    frame_candidates.append((did, rng.choice(data[did]), False))

                scored = []
                for cand_ident, cand_path, is_target in frame_candidates:
                    s = score_candidate(cand_path, galleries[target_ident], features, path_to_idx)
                    scored.append((s, cand_ident, cand_path, is_target))
                scored.sort(key=lambda x: x[0], reverse=True)
                best = scored[0]
                second = scored[1] if len(scored) > 1 else (0.0, None, None, False)
                follow_rows.append({
                    'trial': trial,
                    'target': target_ident,
                    'best_identity': best[1],
                    'best_path': str(best[2].relative_to(image_dir)),
                    'best_score': best[0],
                    'second_score': second[0],
                    'margin': best[0] - second[0],
                    'correct': best[3],
                })

        # 目标缺席 frame：候选列表全是干扰人。理想状态是全部拒绝。
        for target_ident in identities:
            other_idents = [x for x in identities if x != target_ident]
            for _ in range(args.absent_frames_per_target):
                frame_candidates = []
                chosen_distractor_idents = [rng.choice(other_idents) for _ in range(max(1, args.distractors + 1))]
                for did in chosen_distractor_idents:
                    frame_candidates.append((did, rng.choice(data[did])))
                scored = []
                for cand_ident, cand_path in frame_candidates:
                    s = score_candidate(cand_path, galleries[target_ident], features, path_to_idx)
                    scored.append((s, cand_ident, cand_path))
                scored.sort(key=lambda x: x[0], reverse=True)
                best = scored[0]
                second = scored[1] if len(scored) > 1 else (0.0, None, None)
                absent_rows.append({
                    'trial': trial,
                    'target': target_ident,
                    'best_identity': best[1],
                    'best_path': str(best[2].relative_to(image_dir)),
                    'best_score': best[0],
                    'second_score': second[0],
                    'margin': best[0] - second[0],
                    # absent frame 中没有正确候选；被“接受”就是 false accept。
                    'correct': False,
                })

    acc = sum(1 for r in follow_rows if r['correct']) / len(follow_rows)
    margins = [r['margin'] for r in follow_rows]
    print('\n=== Target-present frame simulation ===')
    print(f'total_frames = {len(follow_rows)}')
    print(f'top1_target_selected_acc = {acc:.3f}')
    print(f'margin mean={statistics.mean(margins):.3f}, p25={percentile(margins,0.25):.3f}, median={percentile(margins,0.50):.3f}, p75={percentile(margins,0.75):.3f}, max={max(margins):.3f}')
    print('\nReject by margin when target is present:')
    present_summary = summarize_reject(follow_rows, thresholds)
    for row in present_summary:
        acc_text = 'None' if row['accepted_acc'] is None else f"{row['accepted_acc']:.3f}"
        print(f"margin >= {row['margin_threshold']:.3f}: accepted_rate={row['accepted_rate']:.3f}, accepted_acc={acc_text}, reject_rate={row['reject_rate']:.3f}")

    absent_margins = [r['margin'] for r in absent_rows]
    print('\n=== Target-absent frame simulation ===')
    print(f'total_absent_frames = {len(absent_rows)}')
    print(f'margin mean={statistics.mean(absent_margins):.3f}, p25={percentile(absent_margins,0.25):.3f}, median={percentile(absent_margins,0.50):.3f}, p75={percentile(absent_margins,0.75):.3f}, max={max(absent_margins):.3f}')
    print('\nFalse accept by margin when target is absent:')
    for th in thresholds:
        accepted = [r for r in absent_rows if r['margin'] >= th]
        print(f'margin >= {th:.3f}: false_accept_rate={len(accepted)/len(absent_rows):.3f}, reject_rate={1-len(accepted)/len(absent_rows):.3f}')

    def write_csv(path: Path, rows: List[dict]):
        if not rows:
            return
        with path.open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    write_csv(out_dir / f'{args.output_prefix}_target_present_rows.csv', follow_rows)
    write_csv(out_dir / f'{args.output_prefix}_target_absent_rows.csv', absent_rows)
    write_csv(out_dir / f'{args.output_prefix}_gallery_selected.csv', gallery_rows)

    # summary csv
    with (out_dir / f'{args.output_prefix}_summary.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['section', 'margin_threshold', 'accepted_rate', 'accepted_acc_or_false_accept_rate', 'reject_rate'])
        for row in present_summary:
            writer.writerow(['target_present', row['margin_threshold'], row['accepted_rate'], row['accepted_acc'], row['reject_rate']])
        for th in thresholds:
            accepted = [r for r in absent_rows if r['margin'] >= th]
            writer.writerow(['target_absent', th, len(accepted)/len(absent_rows), len(accepted)/len(absent_rows), 1-len(accepted)/len(absent_rows)])

    print('\n[INFO] saved:')
    print(f"  {out_dir / (args.output_prefix + '_target_present_rows.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_target_absent_rows.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_gallery_selected.csv')}")
    print(f"  {out_dir / (args.output_prefix + '_summary.csv')}")


if __name__ == '__main__':
    main()
