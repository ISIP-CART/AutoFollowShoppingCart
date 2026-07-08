from pathlib import Path
import csv
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
IMAGE_DIR = ROOT / "images"
PAIRWISE_CSV = ROOT / "outputs" / "pairwise_scores.csv"
OUT_DIR = ROOT / "outputs" / "hard_pairs"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_pairs():
    rows = []
    with PAIRWISE_CSV.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["score"] = float(row["score"])
            row["same_identity"] = row["same_identity"].lower() == "true"
            rows.append(row)
    return rows


def make_pair_image(row, out_path):
    img_a = Image.open(IMAGE_DIR / row["image_a"]).convert("RGB")
    img_b = Image.open(IMAGE_DIR / row["image_b"]).convert("RGB")

    h = 360
    def resize_keep(im):
        w = int(im.width * h / im.height)
        return im.resize((w, h))

    img_a = resize_keep(img_a)
    img_b = resize_keep(img_b)

    pad = 20
    text_h = 80
    canvas_w = img_a.width + img_b.width + pad * 3
    canvas_h = h + text_h + pad * 2

    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    canvas.paste(img_a, (pad, pad + text_h))
    canvas.paste(img_b, (pad * 2 + img_a.width, pad + text_h))

    draw = ImageDraw.Draw(canvas)
    title = (
        f"same={row['same_identity']}  "
        f"score={row['score']:.3f}\n"
        f"A: {row['image_a']}\n"
        f"B: {row['image_b']}"
    )
    draw.text((pad, pad), title, fill="black")

    canvas.save(out_path)


def main():
    rows = load_pairs()

    diff_pairs = [r for r in rows if not r["same_identity"]]
    same_pairs = [r for r in rows if r["same_identity"]]

    # 最危险：不同人但分数最高
    diff_pairs = sorted(diff_pairs, key=lambda r: r["score"], reverse=True)

    # 最脆弱：同人但分数最低
    same_pairs = sorted(same_pairs, key=lambda r: r["score"])

    print("=== Top 10 highest different-person pairs ===")
    for i, row in enumerate(diff_pairs[:10]):
        print(row["score"], row["image_a"], row["image_b"])
        make_pair_image(row, OUT_DIR / f"diff_high_{i+1:02d}_{row['score']:.3f}.jpg")

    print("\n=== Top 10 lowest same-person pairs ===")
    for i, row in enumerate(same_pairs[:10]):
        print(row["score"], row["image_a"], row["image_b"])
        make_pair_image(row, OUT_DIR / f"same_low_{i+1:02d}_{row['score']:.3f}.jpg")

    print(f"\n[INFO] 已输出图片到：{OUT_DIR}")


if __name__ == "__main__":
    main()