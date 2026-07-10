# Round 2 Physical Motion Traversability Report

Date: 2026-07-10

## Purpose

Round 2 replaces abstract translated trapezoids with an explicit provisional
vehicle model. It tests whether a candidate action can be described and
projected clearly enough before any Android integration or real control.

The two-stage behavior is:

```text
PROBE_FORWARD_20CM
  -> capture a new frame
  -> PIVOT_LEFT_20DEG or PIVOT_RIGHT_20DEG
```

## Provisional Geometry

```text
vehicle width: 0.305 m
vehicle length: 0.40 m
safety margin: 0.05 m on every side
camera height: 0.65 m
camera downward pitch: 12 degrees
horizontal FOV: 70 degrees
forward probe: 0.20 m
pivot: 20 degrees
sampled poses: 7
```

These are interface-development assumptions, not measured control parameters.

## Implementation

For each action, the prototype now:

1. Generates sampled vehicle poses in top-down ground coordinates.
2. Unions the body footprints and subtracts the initial footprint on the ground plane.
3. Projects only the newly swept ground region through a provisional pinhole camera.
4. Displays RGB, relative depth, and a top-down motion storyboard together.
5. Uses row-relative inverse-depth residuals instead of one global grayscale threshold when the projected sweep is visible.

The new label schema adds optional reason codes:

```text
obstacle_in_sweep
insufficient_clearance
depth_failure
geometry_uncertain
single_frame_insufficient
```

## Command

```powershell
& 'D:\miniconda3\envs\depth_pc_test\python.exe' tools\depth_pc_test\scripts\traversability_score.py `
  --depth-dir tools\depth_pc_test\Depth-Anything-V2\outputs\round1_gray `
  --input-root tools\depth_pc_test\Depth-Anything-V2\inputs `
  --labels tools\depth_pc_test\labels\round2_motion_labels.csv `
  --config tools\depth_pc_test\config\provisional_motion_geometry.json `
  --outdir tools\depth_pc_test\Depth-Anything-V2\outputs\round4_physical_motion
```

Generated ignored artifacts:

```text
traversability_scores.csv: 54 rows
storyboards/: 54 images
summary.json
labeling.html
```

## Result

The action visualization passed its main representation check:

```text
forward: sampled body poses translate by 0.20 m
left pivot: sampled body poses rotate counterclockwise by 20 degrees
right pivot: sampled body poses rotate clockwise by 20 degrees
```

Left and right no longer look like identical image trapezoids shifted sideways.

The physical projection also exposed a blocking camera-geometry result. With
the provisional `0.65 m / 12 degree` camera setup, the newly swept region for
all three immediate actions lies below the camera image:

```text
visible sweep rows: 0 / 54
predicted verdict: UNCLEAR 54 / 54
risk_reason: new_sweep_outside_camera_fov
```

This is a valid conservative result. The earlier `bottom_near_risk ~= 0.99`
problem is no longer interpreted as an obstacle; unobservable risk is now
represented explicitly as `UNCLEAR`, with residual risk values left at zero
and `sweep_visible = false`.

A sensitivity check on one representative portrait frame produced:

```text
camera pitch 12 deg: forward 0 px, left 0 px, right 0 px
camera pitch 15 deg: forward visible, pivots not visible
camera pitch 25 deg: forward and both pivot corner sweeps visible
```

This sensitivity test is diagnostic only. It does not justify changing the
camera mount to 25 degrees without checking target-following visibility.

## Conclusion

Depth Anything V2 has shown useful qualitative scene structure, but the project
has not yet demonstrated action-level traversability. The next dependency is a
measured camera/chassis setup and a near-field visibility decision, not threshold
tuning or Android deployment.

Before collecting new action labels:

1. Measure complete vehicle width/length and phone position.
2. Measure camera pitch and field of view, including the nearest visible floor point.
3. Decide whether the phone alone can observe the immediate sweep or whether a separate near-field safety sensor is required.
4. Capture paired frames: before the 20 cm probe, after the probe, and after the selected 20 degree pivot.
5. Only then replace Round 2 `REVIEW` labels and evaluate veto recall.
