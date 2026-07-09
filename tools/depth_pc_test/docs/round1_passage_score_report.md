# Round 1 Passage Score Test Report

Date: 2026-07-09

## Purpose

This test turns the first Depth Anything V2 grayscale outputs into a PC-side `PassageEvidence` prototype. It does not integrate Android, Human Cart Simulator, or vehicle control.

The goal is to check whether left / center / right ROI scores can explain likely passage openings well enough to justify further research.

## Environment

```text
Python: D:\miniconda3\envs\depth_pc_test\python.exe
Model output source: Depth Anything V2 Small / vits
Depth input: Depth-Anything-V2/outputs/round1_gray/*.png
Image count: 18
Device used for depth inference: CPU
```

The Round 1 visual direction was:

```text
purple / blue = farther
yellow / orange / red = nearer
```

For grayscale scoring, the current convention is:

```text
larger grayscale value = nearer
far_score = 1 - grayscale_depth
```

## Command

```powershell
& 'D:\miniconda3\envs\depth_pc_test\python.exe' tools\depth_pc_test\scripts\passage_score.py `
  --depth-dir tools\depth_pc_test\Depth-Anything-V2\outputs\round1_gray `
  --input-root tools\depth_pc_test\Depth-Anything-V2\inputs `
  --labels tools\depth_pc_test\labels\round1_manual_labels.csv `
  --outdir tools\depth_pc_test\Depth-Anything-V2\outputs\round2_passage_score
```

## Outputs

All generated outputs are ignored by git.

```text
Depth-Anything-V2/outputs/round2_passage_score/passage_scores.csv
Depth-Anything-V2/outputs/round2_passage_score/summary.json
Depth-Anything-V2/outputs/round2_passage_score/overlays/*.png
```

Validation:

```text
passage_scores.csv rows: 18
overlay images: 18
summary.json: generated
```

## Results

Overall, the first heuristic matched 9 of 15 directionally labeled images:

```text
overall_label_match_rate = 0.6000
```

Per scene:

```text
corridor:
  count = 6
  labeled_count = 6
  label_match_rate = 0.3333
  avg_left_opening = 0.2881
  avg_center_opening = 0.3371
  avg_right_opening = 0.3196

shelf_corner_left:
  count = 7
  labeled_count = 5
  label_match_rate = 0.6000
  avg_left_opening = 0.3025
  avg_center_opening = 0.3658
  avg_right_opening = 0.3575

shelf_corner_right:
  count = 5
  labeled_count = 4
  label_match_rate = 1.0000
  avg_left_opening = 0.3879
  avg_center_opening = 0.4003
  avg_right_opening = 0.2844
```

## Interpretation

Depth Anything V2 Small remains promising as a source of local passage evidence. It separates nearby walls, columns, and floor regions from farther hallway regions well enough to continue PC-side research.

The current ROI scoring rule is not ready to drive behavior. It uses fixed left / center / right thirds and a simple lower-image band, so small camera yaw, wall-dominant framing, and long corridors can shift the best ROI away from the manual label. The corridor subset is the clearest warning: visually straight corridors often receive a slight left bias.

The current output should therefore be treated as:

```text
debuggable PassageEvidence prototype
```

not:

```text
safe action selector
```

## Next Step

Continue PC-side testing before Android work:

1. Add more images with explicit `left`, `center`, `right`, `blocked`, and `unclear` labels.
2. Tune ROI geometry for cart-mounted phone framing, especially the vertical band and center corridor bias.
3. Add an overlay that combines original RGB + depth + ROI score in one image for easier manual review.
4. Keep generated images, local phone photos, model weights, and CSV outputs ignored by git.

Android / Human Cart Simulator integration should wait until the scoring rule is more stable and evaluated on more labeled scenes.
