"""
EyeFocus Insight — 集中配置管理
所有模块共享的常量和参数统一定义在此文件。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CameraConfig:
    index: int = 0
    min_fps: float = 25.0


@dataclass(frozen=True)
class FaceMeshConfig:
    model_filename: str = "face_landmarker.task"
    num_faces: int = 1
    min_detection_confidence: float = 0.5
    min_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5


@dataclass(frozen=True)
class HeadPoseConfig:
    yaw_thresh: float = 10.0
    pitch_thresh: float = 20.0  # Relaxed: laptop users naturally tilt head ~10-20° downward
    frontal_yaw_std_thresh: float = 3.0
    frontal_pitch_std_thresh: float = 3.0


@dataclass(frozen=True)
class EyeConfig:
    left_indices: tuple = (33, 160, 158, 133, 153, 144)
    right_indices: tuple = (362, 385, 387, 263, 380, 373)
    ear_min: float = 0.08
    glasses_variance_thresh: float = 0.003


@dataclass(frozen=True)
class BaselineConfig:
    collection_duration: float = 7.0
    trim_ratio: float = 0.10
    min_valid_frames: int = 30


@dataclass(frozen=True)
class BenchmarkConfig:
    min_duration: float = 120.0
    fps_window_size: int = 30


@dataclass(frozen=True)
class HeadPoseProtoConfig:
    phase_duration: float = 5.0
    phases: tuple = field(default_factory=lambda: (
        {"name": "Phase 1: 正视屏幕", "instruction": "请自然正对屏幕"},
        {"name": "Phase 2: 缓慢低头", "instruction": "向下看约 30°"},
        {"name": "Phase 3: 缓慢左转", "instruction": "向左转头约 30°"},
        {"name": "Phase 4: 回到正视", "instruction": "恢复到自然正视"},
    ))


@dataclass(frozen=True)
class EarVarianceConfig:
    collection_duration: float = 7.0
    variance_window: int = 15


CAMERA = CameraConfig()
FACE_MESH = FaceMeshConfig()
HEAD_POSE = HeadPoseConfig()
EYE = EyeConfig()
BASELINE = BaselineConfig()
BENCHMARK = BenchmarkConfig()
HEAD_POSE_PROTO = HeadPoseProtoConfig()
EAR_VARIANCE = EarVarianceConfig()
