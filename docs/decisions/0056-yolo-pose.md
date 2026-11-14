# 0056: People are found with YOLO pose; the repo is AGPL-3.0

- Date: 2026-11-14
- Status: accepted
- Source: Alex, Sat afternoon (T-15)
- Agreed by: Alex

Person detection and follow use Ultralytics YOLO pose (Grant's pipeline, `yolo26n-pose`). Ultralytics is AGPL-3.0, so the public repo is released under AGPL-3.0. Hand gestures can add MediaPipe's gesture recognizer later; recognizing objects ("the pill bottle") goes to Claude's vision on demand, not YOLO.

## Alternatives

| Option | Critique |
| --- | --- |
| **YOLO pose** | Standard, ~15 ms a frame on the laptop, several people at once, keypoints for distance and gestures; already built and tested |
| MediaPipe pose | Apache-2.0, strong hand gestures, weaker at keeping one person among several |
| Apple Vision | Fast, but Mac-only and awkward from Python |
| Larger detectors (RT-DETR) | Heavier, no gain for following one person |

## Reversibility

Easy for the model (one file behind the Detector interface); the license choice is set once the repo goes public.
