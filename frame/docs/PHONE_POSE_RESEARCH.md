# Marker-free phone pose options

Research date: 2026-10-15. This is an assessment, not a new implemented tracker.
The owner rejected the on-screen-marker product direction because the clean
captured feed must follow app switches and the launcher/home screen. Fiducial
implementation changes currently in the working tree are an uncommitted draft;
they should not be mistaken for the selected final product architecture.

## Requirements and observed failure

- No permanent display marker, custom neural-network training, or repeated corner clicking.
- Existing paired phone IMU/body dimensions; two front grayscale cameras only.
- Estimate metric phone position and rotation, handle some hand occlusion, and
  measure latency on the actual headset. No desktop benchmark substitutes for it.
- The owner's YOLOX trial took over 1000 ms, missed the phone in about 90% of
  frames and reached around 40% confidence. Those are this experiment's results,
  not a general benchmark. Its output was 2D boxes, not a 6D pose estimator.

## Primary-source candidates

| Method | Actual task and available pretrained assets | Important limits |
| --- | --- | --- |
| PoseFromShape | Shape-conditioned viewpoint/orientation estimation; released pretrained ObjectNet3D/ShapeNet models and explicit cellphone-category results. | A target 3D shape and object image are needed. Coarse orientation is not complete metric XYZ tracking; legacy dependencies and mono-camera behavior need testing. |
| Gen6D | Pretrained detector, viewpoint selector and refiner for full 6DoF on novel objects using posed reference images; no per-object NN training required for its custom-object workflow. | One-time reference capture, COLMAP reconstruction, object cropping/axis setup and metric-scale registration. Published PyTorch/CUDA environment; headset speed/mono transfer unverified. |
| OnePose++ | Released pretrained 2D–3D matching/LoFTR models, semi-dense reference reconstruction and PnP, including low-texture objects. | Per-object reference reconstruction/setup, GPU-oriented inference examples; changing display content and hands require trials. Not a phone-specific ready-to-run mobile model. |
| FoundationPose | Released generalizable 6D registration/tracking networks; model-based inference can use a new CAD object without retraining the pose networks. | Official demo uses RGB, depth, calibrated intrinsics, an initial mask, mesh and CUDA rasterization. Our two monochrome streams are not an existing RGB-D pipeline. Model-free neural-field setup is not the same as no onboarding/training. |
| M3T | Existing C++ multi-camera model-based translation/rotation tracker using region, texture and optional depth modalities; no phone-specific NN training. | Requires a mesh and initial pose. Included detectors are static/manual, so automatic acquisition is still a separate problem. OpenGL rendering and monocular/grayscale adaptation must be validated; no Frame speed claim. |

Sources:
- [PoseFromShape author repository](https://github.com/YoungXIAO13/PoseFromShape),
  [paper: viewpoint estimation/coarse alignment](https://arxiv.org/html/1906.05105v2).
- [Gen6D project](https://liuyuan-pal.github.io/Gen6D/),
  [pretrained releases and environment](https://github.com/liuyuan-pal/Gen6D),
  [actual custom-object setup](https://github.com/liuyuan-pal/Gen6D/blob/main/custom_object.md).
- [OnePose++ project](https://zju3dv.github.io/onepose_plus_plus/),
  [pretrained weights, reconstruction and GPU evaluation](https://github.com/zju3dv/OnePose_Plus_Plus).
- [FoundationPose official repository](https://github.com/NVlabs/FoundationPose),
  [demo's actual inputs and CUDA context](https://github.com/NVlabs/FoundationPose/blob/main/run_demo.py).
- [M3T documented components and initialization](https://github.com/DLR-RM/3DObjectTracking/tree/master/M3T).

Objectron is not a phone-pose shortcut: its published categories are bikes,
books, bottles, cameras, cereal boxes, chairs, cups, laptops and shoes.
[Official dataset](https://github.com/google-research-datasets/Objectron).
Also, a LINEMOD result labelled phone concerns a fixed benchmark object, not
evidence of generalization to the owner's modern smartphone/case.

The HccePose script name test_mi10_bin_picking is not evidence that its pretrained
target is a Xiaomi phone: it is a bin-picking workflow with separately prepared
object models. It was not selected as a verified phone-specific checkpoint.

## Recommendation: benchmark before another product rewrite

No reviewed source establishes an off-the-shelf, modern-phone-specific,
real-time 6D model for Steam Frame's cameras. The promising alternative is to
give an existing generic pose estimator an object-specific reference/mesh,
without training a new NN.

First compare Gen6D/OnePose++ reference-based acquisition on actual recorded
Frame images, not ordinary RGB sample photos. Rectify KB4 images consistently
and record intrinsics, camera identities, timing and metric body dimensions.
Use independently measured poses to judge errors, not only plausible wireframes.
Include tilted fronts/backs, grips, display changes, low contrast and loss.
Prove the pretrained weights load and measure full latency and recall before
adding any of these stacks to the headset executable.

If acquisition works, evaluate M3T as the local continuous tracker using both
front views and a phone model. Heavier acquisition can run less frequently;
phone gyro can eventually predict between visual updates after axis/time
alignment. This is a proposed architecture, not demonstrated Frame capability.
If it cannot meet an on-headset budget, state that before introducing a desktop
inference requirement. The user's default remains a standalone headset app.

No new model weights were downloaded, executed or bundled during this research.
