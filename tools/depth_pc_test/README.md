# Depth PC Test Workspace

This directory is the project workspace for PC-side monocular depth experiments. It is used before Android integration to answer a narrow question:

```text
Can Depth Anything V2 Small produce depth maps that make shelf corners, corridors, and left / center / right passage openings visually distinguishable?
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
PC static images -> depth visualization -> manual judgment of passage usefulness
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
2. Are left / right passage openings visible in shelf-corner scenes?
3. Are there obvious failure cases such as shelf gaps, glass, reflective floors, or people being mistaken for open passage?
```
