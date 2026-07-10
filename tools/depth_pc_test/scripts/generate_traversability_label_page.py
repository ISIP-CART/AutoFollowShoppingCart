"""Generate a private, offline HTML page for traversability labeling."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote


ACTIONS = (
    "PROBE_FORWARD_20CM",
    "PIVOT_LEFT_20DEG",
    "PIVOT_RIGHT_20DEG",
)

REASON_CODES = (
    ("obstacle_in_sweep", "障碍侵入"),
    ("insufficient_clearance", "宽度不足"),
    ("depth_failure", "深度异常"),
    ("geometry_uncertain", "几何不确定"),
    ("single_frame_insufficient", "单帧证据不足"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an offline image-first traversability label page.")
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--overlay-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def browser_src(path: Path, page_dir: Path) -> str:
    relative = os.path.relpath(path.resolve(), page_dir.resolve()).replace("\\", "/")
    return quote(relative, safe="/.:_-~")


def find_source_images(root: Path) -> dict[str, Path]:
    supported = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    return {
        path.stem: path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in supported
    }


def overlay_path(root: Path, image: str, action: str) -> Path:
    return root / f"{image}_{action.lower()}.png"


def main() -> None:
    args = parse_args()
    with args.labels.open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["image"]].append(row)

    sources = find_source_images(args.input_root)
    missing: list[str] = []
    sections: list[str] = []
    initial_rows: list[dict[str, str]] = []

    for image_name, image_rows in grouped.items():
        row_by_action = {row["candidate_action"]: row for row in image_rows}
        scene = image_rows[0]["scene"]
        source = sources.get(image_name)
        if source is None:
            missing.append(f"source:{image_name}")
            source_html = '<div class="missing">RGB source missing</div>'
        else:
            source_html = f'<img src="{browser_src(source, args.output.parent)}" alt="{html.escape(image_name)} RGB">'

        cards: list[str] = []
        for action in ACTIONS:
            row = row_by_action.get(action)
            if row is None:
                missing.append(f"label:{image_name}/{action}")
                continue
            initial_rows.append(row)
            overlay = overlay_path(args.overlay_dir, image_name, action)
            if overlay.exists():
                overlay_html = f'<img src="{browser_src(overlay, args.output.parent)}" alt="{html.escape(action)} overlay">'
            else:
                missing.append(f"overlay:{image_name}/{action}")
                overlay_html = '<div class="missing">Overlay missing</div>'
            key = f"{image_name}|{action}"
            reason_html = "".join(
                f'<label class="reason"><input type="checkbox" value="{code}">{label}</label>'
                for code, label in REASON_CODES
            )
            cards.append(
                f"""
                <article class="action-card" data-key="{html.escape(key)}">
                  <h3>{html.escape(action)}</h3>
                  {overlay_html}
                  <label>人工结论
                    <select class="verdict">
                      <option value="REVIEW">REVIEW</option>
                      <option value="ALLOW_CAUTION">ALLOW_CAUTION</option>
                      <option value="VETO_STOP">VETO_STOP</option>
                      <option value="UNCLEAR">UNCLEAR</option>
                    </select>
                  </label>
                  <label>置信度
                    <select class="confidence">
                      <option value="todo">todo</option>
                      <option value="high">high</option>
                      <option value="medium">medium</option>
                      <option value="low">low</option>
                    </select>
                  </label>
                  <fieldset><legend>判断原因（可多选）</legend>{reason_html}</fieldset>
                  <label>补充备注（可选）
                    <textarea class="note" rows="2" placeholder="只记录选项无法表达的信息"></textarea>
                  </label>
                </article>
                """
            )

        sections.append(
            f"""
            <section class="scene-block" data-image="{html.escape(image_name)}">
              <header><h2>{html.escape(image_name)}</h2><span>{html.escape(scene)}</span></header>
              <div class="source"><h3>RGB 原图</h3>{source_html}</div>
              <div class="actions">{''.join(cards)}</div>
            </section>
            """
        )

    template = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>深度可通行性人工标注</title>
<style>
:root { color-scheme: light; font-family: Arial, "Microsoft YaHei", sans-serif; }
body { margin: 0; background: #f4f5f7; color: #202124; }
.toolbar { position: sticky; top: 0; z-index: 5; display: flex; gap: 12px; align-items: center; padding: 12px 20px; background: #fff; border-bottom: 1px solid #cfd3d8; }
.toolbar strong { margin-right: auto; }
button { border: 1px solid #246b45; background: #287a50; color: #fff; padding: 9px 14px; cursor: pointer; }
button.secondary { background: #fff; color: #333; border-color: #9aa0a6; }
main { max-width: 1500px; margin: 0 auto; padding: 18px; }
.guide { background: #fff; border-left: 4px solid #287a50; padding: 12px 16px; margin-bottom: 18px; }
.scene-block { background: #fff; border: 1px solid #d8dce1; margin-bottom: 22px; padding: 14px; }
.scene-block > header { display: flex; align-items: baseline; gap: 12px; border-bottom: 1px solid #e4e7eb; margin-bottom: 12px; }
h2 { font-size: 20px; } h3 { font-size: 14px; }
.source img { display: block; max-width: min(100%, 760px); max-height: 520px; object-fit: contain; background: #111; }
.actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.action-card { border: 1px solid #cfd3d8; padding: 10px; min-width: 0; }
.action-card img { width: 100%; aspect-ratio: 3/2; object-fit: contain; background: #111; }
label { display: block; margin-top: 9px; font-size: 13px; }
select, textarea { box-sizing: border-box; width: 100%; margin-top: 4px; padding: 7px; border: 1px solid #9aa0a6; background: #fff; }
fieldset { margin: 10px 0 0; padding: 7px; border: 1px solid #cfd3d8; }
legend { font-size: 13px; }
.reason { display: inline-flex; align-items: center; gap: 4px; margin: 3px 12px 3px 0; }
.reason input { width: auto; margin: 0; }
.done { border-color: #287a50; box-shadow: inset 0 0 0 1px #287a50; }
.ready { color: #176c3a; font-weight: 700; }
.pending { color: #9a4f00; font-weight: 700; }
.missing { padding: 30px; background: #fee; color: #8b1e1e; }
@media (max-width: 900px) { .actions { grid-template-columns: 1fr; } .toolbar { flex-wrap: wrap; } }
</style>
</head>
<body>
<div class="toolbar"><strong>深度可通行性人工标注</strong><span id="progress"></span><span id="export-status"></span><button id="export">导出 CSV</button><button id="clear" class="secondary">清除本页缓存</button></div>
<main>
<div class="guide">先看右侧俯视故事板理解车辆姿态，再判断这一段明确动作能否低速执行。顺序是先前探 20 cm、重新观察，再单独判断原地左转或右转 20°。绿色区域是新增扫掠区；暂定几何只用于实验，不代表真实车辆尺寸。</div>
__SECTIONS__
</main>
<script>
const initial = __INITIAL__;
const storageKey = 'depth-traversability-physical-motion-labels-v2';
const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
const cards = [...document.querySelectorAll('.action-card')];
const byKey = Object.fromEntries(initial.map(row => [`${row.image}|${row.candidate_action}`, row]));

function updateProgress() {
  const done = cards.filter(card => card.querySelector('.verdict').value !== 'REVIEW').length;
  document.getElementById('progress').textContent = `${done} / ${cards.length} 已标注`;
  const status = document.getElementById('export-status');
  status.textContent = done === cards.length ? '无 REVIEW，可导出正式复核' : `仍有 ${cards.length - done} 项 REVIEW`;
  status.className = done === cards.length ? 'ready' : 'pending';
}
function persist() {
  const state = {};
  cards.forEach(card => {
    state[card.dataset.key] = {
      expected_verdict: card.querySelector('.verdict').value,
      label_confidence: card.querySelector('.confidence').value,
      reason_codes: [...card.querySelectorAll('.reason input:checked')].map(input => input.value).join('|'),
      note: card.querySelector('.note').value
    };
    card.classList.toggle('done', state[card.dataset.key].expected_verdict !== 'REVIEW');
  });
  localStorage.setItem(storageKey, JSON.stringify(state));
  updateProgress();
}
cards.forEach(card => {
  const base = byKey[card.dataset.key];
  const value = saved[card.dataset.key] || base;
  card.querySelector('.verdict').value = value.expected_verdict;
  card.querySelector('.confidence').value = value.label_confidence || 'todo';
  const reasons = new Set((value.reason_codes || '').split('|').filter(Boolean));
  card.querySelectorAll('.reason input').forEach(input => { input.checked = reasons.has(input.value); });
  card.querySelector('.note').value = value.note || '';
  card.querySelectorAll('select,textarea,input').forEach(control => {
    control.addEventListener('change', persist);
    control.addEventListener('input', persist);
  });
});
persist();

function csvCell(value) { return `"${String(value ?? '').replaceAll('"', '""')}"`; }
document.getElementById('export').addEventListener('click', () => {
  persist();
  const state = JSON.parse(localStorage.getItem(storageKey));
  const header = ['image','scene','candidate_action','expected_verdict','label_confidence','reason_codes','note'];
  const lines = [header.join(',')];
  initial.forEach(row => {
    const current = state[`${row.image}|${row.candidate_action}`] || row;
    lines.push([row.image,row.scene,row.candidate_action,current.expected_verdict,current.label_confidence,current.reason_codes,current.note].map(csvCell).join(','));
  });
  const blob = new Blob(['\ufeff' + lines.join('\\r\\n')], {type: 'text/csv;charset=utf-8'});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'round2_motion_labels.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  const remaining = cards.filter(card => card.querySelector('.verdict').value === 'REVIEW').length;
  const status = document.getElementById('export-status');
  status.textContent = remaining === 0 ? '导出成功：54 项完整' : `已导出，但仍有 ${remaining} 项 REVIEW`;
  status.className = remaining === 0 ? 'ready' : 'pending';
});
document.getElementById('clear').addEventListener('click', () => {
  if (confirm('确定清除这个页面保存在浏览器中的标注吗？')) { localStorage.removeItem(storageKey); location.reload(); }
});
</script>
</body>
</html>
"""
    rendered = template.replace("__SECTIONS__", "\n".join(sections)).replace(
        "__INITIAL__", json.dumps(initial_rows, ensure_ascii=False)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {len(grouped)} image groups and {len(initial_rows)} label rows to {args.output}")
    if missing:
        print("Missing assets:")
        for item in missing:
            print(f"  {item}")


if __name__ == "__main__":
    main()
