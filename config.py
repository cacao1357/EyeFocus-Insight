"""
EyeFocus Insight — 集中配置管理
所有模块共享的常量和参数统一定义在此文件。

支持两种配置方式：
1. dataclass 常量（默认）
2. YAML 配置文件（可选）
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


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
    # ⚠️ DEPRECATED: glasses_variance_thresh based on flawed assumption
    # Phase 0 实测：戴眼镜 EAR 方差反而更低（0.00002-0.003 vs 不戴眼镜 0.004-0.007）
    # 阈值 0.003 无法可靠区分，详见 ISSUES_REPORT.md §1.1
    glasses_variance_thresh: float = 0.003


@dataclass(frozen=True)
class BaselineConfig:
    collection_duration: float = 7.0
    trim_ratio: float = 0.10
    min_valid_frames: int = 30
    cqs_threshold: float = 0.60  # Lowered from 0.70 — Phase 0 实测最高 0.629


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


# YAML 配置加载
_yaml_config: Optional[Dict[str, Any]] = None


def load_yaml_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """从 YAML 文件加载配置

    Args:
        config_path: YAML 文件路径，默认为 config.yaml

    Returns:
        配置字典
    """
    global _yaml_config

    if _yaml_config is not None:
        return _yaml_config

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config.yaml"
        )

    if not os.path.exists(config_path):
        return {}

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            _yaml_config = yaml.safe_load(f)
        return _yaml_config or {}
    except ImportError:
        # PyYAML 未安装，使用默认配置
        return {}
    except Exception as e:
        print(f"Warning: Failed to load config.yaml: {e}")
        return {}


def get_yaml_value(*keys, default: Any = None) -> Any:
    """从 YAML 配置中获取值

    Args:
        keys: 配置键路径，例如 get_yaml_value("camera", "index")
        default: 默认值

    Returns:
        配置值或默认值
    """
    config = load_yaml_config()
    value = config
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return default
        if value is None:
            return default
    return value


def set_yaml_value(*keys, value: Any) -> None:
    """设置 YAML 配置值（运行时，不立即写盘）

    Args:
        keys: 配置键路径，例如 set_yaml_value("voice", "enabled", value=False)
        value: 要设置的值
    """
    config = load_yaml_config()
    d = config
    for key in keys[:-1]:
        if key not in d or not isinstance(d[key], dict):
            d[key] = {}
        d = d[key]
    d[keys[-1]] = value


def save_yaml_config(config_path: Optional[str] = None) -> bool:
    """将当前运行时配置持久化到 YAML 文件

    Args:
        config_path: 目标路径，默认为 config.yaml

    Returns:
        True 保存成功
    """
    global _yaml_config

    if _yaml_config is None:
        return False

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config.yaml"
        )

    try:
        import yaml
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(_yaml_config, f, allow_unicode=True, default_flow_style=False)
        return True
    except Exception as e:
        print(f"Warning: Failed to save config.yaml: {e}")
        return False


def reset_yaml_cache() -> None:
    """重置 YAML 缓存，下次 load 重新读取文件"""
    global _yaml_config
    _yaml_config = None
