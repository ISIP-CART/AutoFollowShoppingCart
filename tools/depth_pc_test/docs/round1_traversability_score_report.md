# Round 1 Traversability Score Report

Date: 2026-07-09

## Purpose

This round changes the PC-side depth test from "which side is the passage" to a narrower and safer question:

```text
For a candidate short motion, does the depth map suggest enough free space to allow cautious testing, or should the system veto motion?
```

This better matches the shopping-cart problem. The phone does not need to understand that a scene contains a left corridor, right corridor, or aisle topology. For the first prototype, depth should mainly provide a conservative traversability signal for a small motion envelope.

## Input

Depth source:

```text
tools/depth_pc_test/Depth-Anything-V2/outputs/round1_gray/*.png
```

Input image count:

```text
18
```

Candidate actions per image:

```text
SHORT_FORWARD_CAUTION
LEFT_ARC_CAUTION
RIGHT_ARC_CAUTION
```

Total scored rows:

```text
54
```

## Command

Run from the project root:

```powershell
& 'D:\miniconda3\envs\depth_pc_test\python.exe' tools\depth_pc_test\scripts\traversability_score.py `
  --depth-dir tools\depth_pc_test\Depth-Anything-V2\outputs\round1_gray `
  --input-root tools\depth_pc_test\Depth-Anything-V2\inputs `
  --labels tools\depth_pc_test\labels\round1_traversability_labels.csv `
  --outdir tools\depth_pc_test\Depth-Anything-V2\outputs\round3_traversability_score
```

## Output

Ignored local output directory:

```text
tools/depth_pc_test/Depth-Anything-V2/outputs/round3_traversability_score/
```

Generated files:

```text
traversability_scores.csv
summary.json
overlays/*.png  # 54 files
```

The overlay images draw the approximate candidate motion envelope over the grayscale depth image and show:

```text
candidate_action
predicted_verdict
expected_verdict
open_score
near_risk
bottom_near_risk
risk_reason
```

## Run Summary

The first run generated:

```text
traversability_scores.csv: 54 rows
overlays/: 54 png files
summary.json: generated
```

Predicted verdict distribution:

```text
ALLOW_CAUTION: 20
UNCLEAR: 27
VETO_STOP: 7
```

Per-action distribution:

```text
SHORT_FORWARD_CAUTION: ALLOW_CAUTION 6, UNCLEAR 8, VETO_STOP 4
LEFT_ARC_CAUTION: ALLOW_CAUTION 7, UNCLEAR 9, VETO_STOP 2
RIGHT_ARC_CAUTION: ALLOW_CAUTION 7, UNCLEAR 10, VETO_STOP 1
```

Labeled rows:

```text
0
```

Therefore the current match rate is intentionally `null`.

## Label Interface

The tracked manual-label file is:

```text
tools/depth_pc_test/labels/round1_traversability_labels.csv
```

It currently contains one row for each image and candidate action. All rows are intentionally left as:

```text
expected_verdict = REVIEW
label_confidence = todo
```

This is an explicit interface for later human review, not a fake ground truth. After looking at the overlay images, a reviewer can replace `REVIEW` with:

```text
ALLOW_CAUTION
VETO_STOP
UNCLEAR
```

## Heuristic

The current prototype assumes the Round 1 grayscale convention:

```text
larger grayscale value = nearer
smaller grayscale value = farther
```

It converts the lower-middle depth region into three approximate motion envelopes:

```text
SHORT_FORWARD_CAUTION: narrow forward trapezoid
LEFT_ARC_CAUTION: left-biased arc-like trapezoid
RIGHT_ARC_CAUTION: right-biased arc-like trapezoid
```

For each candidate action, it reports:

```text
open_score
near_risk
bottom_near_risk
floor_continuity_score
confidence
predicted_verdict
risk_reason
```

The verdict logic is conservative, but intentionally does not hard-veto on the bottom image band alone:

```text
bottom_near_risk -> diagnostic only, because nearby floor is expected
high envelope near_risk plus weak open_score -> VETO_STOP
enough open_score and low risk -> ALLOW_CAUTION
otherwise -> UNCLEAR
```

## Interpretation

This round should not be used to claim an accuracy number yet, because the label file still needs manual review.

The main engineering conclusion is that the PC prototype now has a better interface:

```text
Depth map -> candidate motion risk evidence -> cautious action gate
```

instead of:

```text
Depth map -> left/center/right topology classification
```

This keeps the future Android module aligned with the current Human Cart Simulator design: depth evidence should help decide whether a short local search or cautious arc is allowed, but it should not directly command the chassis and should not pretend to solve navigation.

## Next Step

Before Android work, manually review `round3_traversability_score/overlays/` and fill `round1_traversability_labels.csv`. Then rerun the script and check whether the heuristic agrees with the human verdicts often enough to justify tuning thresholds or adding temporal smoothing.
