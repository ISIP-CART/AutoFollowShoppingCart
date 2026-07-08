from pathlib import Path
import argparse
import csv
import json
import random
import re
import shutil
from collections import defaultdict

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def canonical_identity(person_id: str) -> str:
    """Convert ysy-1 -> ysy, rxy-2 -> rxy. If no numeric suffix, keep unchanged."""
    return re.sub(r"-\d+$", "", person_id.strip())


def read_json(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def read_metadata(path: Path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def safe_float(row, key, default=0.0):
    try:
        return float(row.get(key, default))
    except Exception:
        return default


def safe_int(row, key, default=0):
    try:
        return int(float(row.get(key, default)))
    except Exception:
        return default


def select_rows(rows, args):
    filtered = []
    for row in rows:
        conf = safe_float(row, 'confidence', 0.0)
        if conf < args.min_conf:
            continue
        if args.skip_edge_touch and safe_int(row, 'edge_touch', 0) != 0:
            continue
        if safe_float(row, 'bbox_width', 0.0) < args.min_bbox_width:
            continue
        if safe_float(row, 'bbox_height', 0.0) < args.min_bbox_height:
            continue
        filtered.append(row)

    if args.max_per_session and len(filtered) > args.max_per_session:
        if args.sample_mode == 'random':
            rng = random.Random(args.seed)
            filtered = sorted(rng.sample(filtered, args.max_per_session), key=lambda r: safe_int(r, 'crop_id', 0))
        elif args.sample_mode == 'even':
            # evenly sample across time/crop order
            if args.max_per_session <= 1:
                filtered = [filtered[0]]
            else:
                idxs = [round(i * (len(filtered) - 1) / (args.max_per_session - 1)) for i in range(args.max_per_session)]
                filtered = [filtered[i] for i in idxs]
        else:
            filtered = filtered[:args.max_per_session]

    return filtered


def discover_sessions(src: Path):
    sessions = []
    for p in sorted(src.iterdir()):
        if not p.is_dir():
            continue
        if (p / 'session_info.json').exists() and (p / 'metadata.csv').exists() and (p / 'crops').is_dir():
            sessions.append(p)
    return sessions


def resolve_identity(session_dir: Path, session_info: dict, mode: str) -> str:
    if mode == 'folder':
        raw = session_dir.name.split('_')[0]
    else:
        raw = session_info.get('person_id') or session_dir.name.split('_')[0]
    if mode == 'base':
        return canonical_identity(raw)
    return raw


def main():
    parser = argparse.ArgumentParser(description='Prepare OpenBot PersonCropCollector session folders for Torchreid tests.')
    parser.add_argument('--src', default='images', help='Root directory containing session folders, e.g. images/')
    parser.add_argument('--dst', default='images_openbot_clean', help='Output dataset directory with person-id subfolders')
    parser.add_argument('--identity-mode', choices=['base', 'session', 'folder'], default='base',
                        help='base: ysy-1 -> ysy; session: keep session_info person_id; folder: use folder prefix before underscore')
    parser.add_argument('--min-conf', type=float, default=0.75)
    parser.add_argument('--skip-edge-touch', action='store_true')
    parser.add_argument('--min-bbox-width', type=float, default=0.0)
    parser.add_argument('--min-bbox-height', type=float, default=0.0)
    parser.add_argument('--max-per-session', type=int, default=0, help='0 means keep all filtered crops')
    parser.add_argument('--sample-mode', choices=['first', 'random', 'even'], default='even')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--copy-mode', choices=['copy', 'symlink'], default='copy')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    src = (root / args.src).resolve() if not Path(args.src).is_absolute() else Path(args.src).resolve()
    dst = (root / args.dst).resolve() if not Path(args.dst).is_absolute() else Path(args.dst).resolve()

    if not src.exists():
        raise RuntimeError(f'Source directory not found: {src}')

    if dst.exists():
        if args.overwrite:
            shutil.rmtree(dst)
        else:
            raise RuntimeError(f'Destination exists: {dst}. Use --overwrite to recreate it.')
    dst.mkdir(parents=True, exist_ok=True)

    sessions = discover_sessions(src)
    if not sessions:
        raise RuntimeError(f'No session folders found under {src}. Expected session_info.json + metadata.csv + crops/.')

    manifest_path = dst / 'dataset_manifest.csv'
    counts = defaultdict(int)
    session_counts = {}
    written = 0

    with manifest_path.open('w', encoding='utf-8-sig', newline='') as f:
        fieldnames = [
            'identity', 'session_id', 'person_id', 'out_path', 'src_path',
            'crop_id', 'frame_id', 'timestamp_ms', 'confidence', 'bbox_left', 'bbox_top',
            'bbox_right', 'bbox_bottom', 'bbox_width', 'bbox_height', 'edge_touch', 'save_reason'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for session_dir in sessions:
            info = read_json(session_dir / 'session_info.json')
            rows = read_metadata(session_dir / 'metadata.csv')
            selected = select_rows(rows, args)
            identity = resolve_identity(session_dir, info, args.identity_mode)
            out_identity_dir = dst / identity
            out_identity_dir.mkdir(parents=True, exist_ok=True)
            session_id = info.get('session_id', session_dir.name)
            person_id = info.get('person_id', session_dir.name.split('_')[0])

            kept = 0
            for row in selected:
                rel_crop = row.get('crop_path', '')
                src_crop = session_dir / rel_crop
                if not src_crop.exists():
                    # fallback if metadata contains only filename or different slash style
                    src_crop = session_dir / 'crops' / Path(rel_crop).name
                if not src_crop.exists() or src_crop.suffix.lower() not in IMAGE_EXTS:
                    continue

                out_name = f"{session_id}__{Path(src_crop).name}"
                out_crop = out_identity_dir / out_name

                if args.copy_mode == 'copy':
                    shutil.copy2(src_crop, out_crop)
                else:
                    try:
                        out_crop.symlink_to(src_crop)
                    except Exception:
                        shutil.copy2(src_crop, out_crop)

                writer.writerow({
                    'identity': identity,
                    'session_id': session_id,
                    'person_id': person_id,
                    'out_path': str(out_crop.relative_to(dst)),
                    'src_path': str(src_crop),
                    'crop_id': row.get('crop_id', ''),
                    'frame_id': row.get('frame_id', ''),
                    'timestamp_ms': row.get('timestamp_ms', ''),
                    'confidence': row.get('confidence', ''),
                    'bbox_left': row.get('bbox_left', ''),
                    'bbox_top': row.get('bbox_top', ''),
                    'bbox_right': row.get('bbox_right', ''),
                    'bbox_bottom': row.get('bbox_bottom', ''),
                    'bbox_width': row.get('bbox_width', ''),
                    'bbox_height': row.get('bbox_height', ''),
                    'edge_touch': row.get('edge_touch', ''),
                    'save_reason': row.get('save_reason', ''),
                })
                counts[identity] += 1
                kept += 1
                written += 1
            session_counts[session_id] = kept

    print(f'[INFO] sessions found: {len(sessions)}')
    for sid, n in session_counts.items():
        print(f'  {sid}: {n} crops kept')
    print('[INFO] identity counts:')
    for identity, n in sorted(counts.items()):
        print(f'  {identity}: {n}')
    print(f'[INFO] total crops written: {written}')
    print(f'[INFO] output dataset: {dst}')
    print(f'[INFO] manifest: {manifest_path}')


if __name__ == '__main__':
    main()
