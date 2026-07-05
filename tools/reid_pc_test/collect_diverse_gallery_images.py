from pathlib import Path
import argparse
import csv
import shutil


DEFAULT_CSVS = [
    r"outputs\x025_bal16_g3_diverse_gallery_selected.csv",
    r"outputs\x025_bal16_g5_diverse_gallery_selected.csv",
    r"outputs\x025_bal16_g8_diverse_gallery_selected.csv",
]


def resolve_path(path_str: str, root: Path) -> Path:
    """
    支持绝对路径和相对路径。
    相对路径默认相对于脚本所在目录，也就是 reid_pc_test。
    """
    p = Path(path_str)
    if p.is_absolute():
        return p.resolve()
    return (root / p).resolve()


def safe_filename(name: str) -> str:
    """
    避免 Windows 文件名里出现奇怪字符。
    """
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name


def infer_experiment_name(csv_path: Path) -> str:
    """
    例如：
    x025_bal16_g5_diverse_gallery_selected.csv
    -> x025_bal16_g5_diverse
    """
    name = csv_path.stem
    suffix = "_gallery_selected"
    if name.endswith(suffix):
        name = name[: -len(suffix)]
    return safe_filename(name)


def find_image_path(image_root: Path, raw_path: str) -> Path:
    """
    gallery_selected.csv 里的 path 通常是：
      chy/xxx.jpg
      rxy/xxx.jpg

    这里同时兼容：
      1. 相对 images 的路径
      2. 绝对路径
      3. 反斜杠路径
    """
    raw_path = raw_path.strip().replace("\\", "/")
    p = Path(raw_path)

    if p.is_absolute():
        candidate = p
    else:
        candidate = image_root / p

    return candidate.resolve()


def copy_gallery_images(csv_path: Path, image_root: Path, output_root: Path) -> list[dict]:
    experiment_name = infer_experiment_name(csv_path)
    experiment_out = output_root / experiment_name
    experiment_out.mkdir(parents=True, exist_ok=True)

    copied_rows = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required_cols = {"trial", "identity", "path"}
        missing = required_cols - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(
                f"{csv_path} 缺少列：{missing}。"
                f"实际列为：{reader.fieldnames}"
            )

        counters = {}

        for row in reader:
            trial = str(row.get("trial", "0")).strip()
            identity = str(row["identity"]).strip()
            rel_path = str(row["path"]).strip()
            strategy = str(row.get("strategy", "")).strip()

            src = find_image_path(image_root, rel_path)

            if not src.exists():
                print(f"[WARN] 图片不存在，跳过：{src}")
                continue

            trial_dir = f"trial_{int(trial):03d}" if trial.isdigit() else f"trial_{safe_filename(trial)}"
            dst_dir = experiment_out / trial_dir / safe_filename(identity)
            dst_dir.mkdir(parents=True, exist_ok=True)

            key = (experiment_name, trial, identity)
            counters[key] = counters.get(key, 0) + 1
            idx = counters[key]

            # 保留原始后缀，文件名前加编号，方便看选择顺序。
            dst_name = f"{idx:02d}__{src.name}"
            dst = dst_dir / dst_name

            shutil.copy2(src, dst)

            copied_rows.append({
                "experiment": experiment_name,
                "trial": trial,
                "identity": identity,
                "strategy": strategy,
                "source": str(src),
                "destination": str(dst),
                "original_csv_path": rel_path,
            })

    return copied_rows


def write_manifest(rows: list[dict], output_root: Path) -> None:
    manifest_path = output_root / "gallery_visual_check_manifest.csv"
    output_root.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "experiment",
        "trial",
        "identity",
        "strategy",
        "original_csv_path",
        "source",
        "destination",
    ]

    with manifest_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[INFO] manifest 已保存：{manifest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="把 diverse gallery_selected.csv 中选中的图片复制出来，便于肉眼检查多姿态/多视角覆盖情况。"
    )
    parser.add_argument(
        "--images",
        default="images",
        help="图片根目录，默认 images。"
    )
    parser.add_argument(
        "--output",
        default=r"outputs\gallery_visual_check",
        help="复制后的输出目录，默认 outputs/gallery_visual_check。"
    )
    parser.add_argument(
        "--csvs",
        nargs="*",
        default=DEFAULT_CSVS,
        help="要读取的 gallery_selected.csv 文件列表。默认读取 g3/g5/g8 diverse 三个文件。"
    )

    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    image_root = resolve_path(args.images, root)
    output_root = resolve_path(args.output, root)

    if not image_root.exists():
        raise RuntimeError(f"图片根目录不存在：{image_root}")

    all_rows = []

    print(f"[INFO] root = {root}")
    print(f"[INFO] image_root = {image_root}")
    print(f"[INFO] output_root = {output_root}")

    for csv_str in args.csvs:
        csv_path = resolve_path(csv_str, root)

        if not csv_path.exists():
            print(f"[WARN] CSV 不存在，跳过：{csv_path}")
            continue

        print(f"\n[INFO] 处理 CSV：{csv_path}")
        rows = copy_gallery_images(csv_path, image_root, output_root)
        all_rows.extend(rows)
        print(f"[INFO] 已复制 {len(rows)} 张图片")

    write_manifest(all_rows, output_root)

    print("\n[INFO] 完成。你可以打开这个目录肉眼检查：")
    print(f"  {output_root}")


if __name__ == "__main__":
    main()