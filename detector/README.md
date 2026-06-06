# `detector/` — 检测器层

> v4.0+ 稳定 | 测试覆盖 100% | 状态：✅ 活跃

**职责**：**单帧检测器**——从 BGR ndarray 提取人脸关键点、EAR、头部姿态、视线、光照。**无状态**（除个别滑动窗口），**无 I/O**（不写 DB），输入帧，输出 dataclass / 数值。

## 公共 API（`__init__.py` 单入口）

| 工厂函数 | 返回类 | 输入 | 输出 |
|---------|--------|------|------|
| `create_face_mesh_detector()` | `FaceMeshDetector` | BGR frame | `FaceMeshResult`（468 关键点 + 变换矩阵 + yaw/pitch）|
| `create_eye_aspect_detector()` | `EyeAspectDetector` | face landmarks | `EyeAspectResult` / `BlinkEvent` |
| `create_head_pose_detector()` | `HeadPoseDetector` | face landmarks | `HeadPoseResult`（yaw/pitch 角度）|
| `create_gaze_detector()` | `GazeDetector` | face landmarks + iris | `GazeResult`（归一化视线坐标）|
| `create_light_detector()` | `LightDetector` | BGR frame | `LightResult` + `LightCondition` 枚举（BRIGHT/NORMAL/DIM）|

## 子模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `face_mesh.py` | 313 | MediaPipe FaceLandmarker 封装（468 关键点 + blendshapes）|
| `eye_aspect.py` | 550 | EAR 计算 + 眨眼检测（动态阈值 = baseline × 0.75）|
| `head_pose.py` | 128 | yaw/pitch 计算（solvePnP + euler）|
| `gaze.py` | 220 | 视线方向（iris 关键点）|
| `light.py` | 204 | 帧亮度统计 → LightCondition |
| `euler_utils.py` | 64 | rotation matrix ↔ euler 内部工具（**未在 `__init__` 暴露**）|

## 使用示例

```python
from detector import create_face_mesh_detector, create_eye_aspect_detector

face = create_face_mesh_detector()
eye = create_eye_aspect_detector()

import cv2
frame = cv2.imread("face.jpg")
result = face.detect_from_frame(frame, timestamp_ms=0)
if result.face_detected:
    ear, _ = eye.compute(result.landmarks)
```

## 测试入口

```bash
pytest tests/test_detector.py tests/test_face_mesh.py tests/test_light.py  # 完整套件
```

## 关键常量（来自 `config.py`）

- `EAR_MIN = 0.08`（眨眼判定下限）
- `CQS_THRESHOLD = 0.60`（v4.0 起，v4.0 之前 0.70）
- `HeadPoseConfig.yaw_thresh = 10.0` / `pitch_thresh = 20.0`（分心判定）

## 已知限制

- `*.task` 模型文件不在 git 中（`*.task` 被 .gitignore）。首次运行 MediaPipe 自动从 Google Storage 下载（`face_landmarker/float16/1/face_landmarker.task` ~3.6 MB）。
- `euler_utils.py` 是内部工具，不在 `__init__` 暴露。
