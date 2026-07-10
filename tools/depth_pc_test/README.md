# Depth PC Test Workspace

This directory is the project workspace for PC-side monocular depth experiments. It is used before Android integration to answer a narrow question:

```text
Can Depth Anything V2 Small provide useful evidence for whether a cautious short motion is traversable or too risky?
```

## Source

`Depth-Anything-V2/` was copied from the official Depth Anything V2 repository:

```text
https://github.com/DepthAnything/Depth-Anything-V2.git
```

The local copy was observed at upstream commit:

```text
a561b849ebae10a6f5ef49e26c83cbbcd36c71bf
```

The upstream `.git` directory has been removed intentionally, so this folder is no longer an independent Git repository. It is now a normal project research workspace under `AutoFollowShoppingCart`, similar to the existing `tools/reid_pc_test/` convention.

Keep the upstream `LICENSE` file in `Depth-Anything-V2/` with the copied source.

## Project Use

This workspace supports the "Depth Passage Simulator / Passage Detector" research line documented in:

```text
design/货架拐角跟随目标转弯讨论总结与后续工作计划.md
```

Current scope:

```text
PC static images -> depth visualization -> candidate-motion traversability review
```

Out of scope for this workspace at the current stage:

```text
Android integration
TFLite / ONNX conversion
real-time video inference
automatic target-disappearance triggering
direct coupling into Human Cart Simulator
direct vehicle control
```

## Privacy and Large File Rules

Do not commit local test photos, generated depth outputs, model weights, or converted model artifacts.

Protected paths include:

```text
Depth-Anything-V2/inputs/
Depth-Anything-V2/outputs/
Depth-Anything-V2/checkpoints/
images/
outputs/
weights/
checkpoints/
depth_raw/
depth_vis/
logs/
```

Protected file types include:

```text
*.pth
*.pt
*.ckpt
*.onnx
*.tflite
*.engine
```

Local phone photos may include private scenes or people. Generated depth images may still reveal those scenes, so they should be treated as private by default.

## Suggested First Test

After preparing the conda environment and placing `depth_anything_v2_vits.pth` under `Depth-Anything-V2/checkpoints/`, run from `Depth-Anything-V2/`:

```powershell
python run.py --encoder vits --img-path inputs --outdir outputs\round1_vits
```

The first review should answer:

```text
1. Can the depth map separate nearby shelves from farther corridor space?
2. Does a candidate short-forward or arc motion envelope look blocked or open?
3. Are there obvious failure cases such as shelf gaps, glass, reflective floors, or people being mistaken for open passage?
```

## Round 1 Status

Round 1 has been run locally with Depth Anything V2 Small (`vits`) on 18 PC-side test images:

```text
inputs/corridor: 6
inputs/shelf_corner_left: 7
inputs/shelf_corner_right: 5
```

Generated images and CSV files remain under ignored `Depth-Anything-V2/outputs/`.

The qualitative result is promising: far corridor space is generally separated from nearby walls, columns, and floor regions. However, the first fixed-ROI scoring heuristic is not stable enough for behavior decisions, and should be treated as a legacy exploration rather than the main decision interface.

## Legacy Passage Score Prototype

The tracked helper script is:

```text
tools/depth_pc_test/scripts/passage_score.py
```

Run it from the project root after Round 1 grayscale depth images exist:

```powershell
& 'D:\miniconda3\envs\depth_pc_test\python.exe' tools\depth_pc_test\scripts\passage_score.py `
  --depth-dir tools\depth_pc_test\Depth-Anything-V2\outputs\round1_gray `
  --input-root tools\depth_pc_test\Depth-Anything-V2\inputs `
  --labels tools\depth_pc_test\labels\round1_manual_labels.csv `
  --outdir tools\depth_pc_test\Depth-Anything-V2\outputs\round2_passage_score
```

It writes ignored outputs:

```text
passage_scores.csv
summary.json
overlays/*.png
```

The first passage-score report is tracked at:

```text
tools/depth_pc_test/docs/round1_passage_score_report.md
```

## Legacy Traversability Pilot

The first action-scoring pilot used an earlier version of:

```text
tools/depth_pc_test/scripts/traversability_score.py
```

with translated image-space trapezoids for:

```text
SHORT_FORWARD_CAUTION
LEFT_ARC_CAUTION
RIGHT_ARC_CAUTION
```

The completed human review is preserved in
`labels/round1_traversability_labels.csv`. It produced 49 evaluable rows and a
legacy heuristic match rate of 38.8%, but the action geometry was too abstract
for this to count as model accuracy. See
`docs/round1_traversability_score_report.md`.

## Physical Motion Prototype

The current prototype uses explicit actions:

```text
PROBE_FORWARD_20CM
PIVOT_LEFT_20DEG
PIVOT_RIGHT_20DEG
```

and outputs a conservative verdict:

```text
ALLOW_CAUTION
VETO_STOP
UNCLEAR
```

Run it from the project root after Round 1 grayscale depth images exist:

```powershell
& 'D:\miniconda3\envs\depth_pc_test\python.exe' tools\depth_pc_test\scripts\traversability_score.py `
  --depth-dir tools\depth_pc_test\Depth-Anything-V2\outputs\round1_gray `
  --input-root tools\depth_pc_test\Depth-Anything-V2\inputs `
  --labels tools\depth_pc_test\labels\round2_motion_labels.csv `
  --config tools\depth_pc_test\config\provisional_motion_geometry.json `
  --outdir tools\depth_pc_test\Depth-Anything-V2\outputs\round4_physical_motion
```

It writes ignored outputs:

```text
traversability_scores.csv
summary.json
storyboards/*.png
```

The manual label interface is tracked at:

```text
tools/depth_pc_test/labels/round2_motion_labels.csv
```

Rows are initially marked `REVIEW`. Do not label them until the provisional
camera geometry has been replaced or explicitly accepted for a UI-only trial.

For image-first manual review, generate a private offline labeling page:

```powershell
& 'D:\miniconda3\envs\depth_pc_test\python.exe' tools\depth_pc_test\scripts\generate_traversability_label_page.py `
  --labels tools\depth_pc_test\labels\round2_motion_labels.csv `
  --input-root tools\depth_pc_test\Depth-Anything-V2\inputs `
  --overlay-dir tools\depth_pc_test\Depth-Anything-V2\outputs\round4_physical_motion\storyboards `
  --output tools\depth_pc_test\Depth-Anything-V2\outputs\round4_physical_motion\labeling.html
```

Open `labeling.html` in a browser. Each action card shows an RGB/depth/top-down
storyboard, supports optional reason-code checkboxes, saves on every edit, and
reports whether any `REVIEW` rows remain. Exported CSV is compatible with the
current scorer. Keep the HTML beside the generated outputs so its local image
links remain valid.

The current physical-motion report is tracked at:

```text
tools/depth_pc_test/docs/round2_physical_motion_report.md
```

Keep `Depth-Anything-V2/inputs/`, `Depth-Anything-V2/outputs/`, and `Depth-Anything-V2/checkpoints/` private and uncommitted.
