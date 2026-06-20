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


@dataclass(frozen=True)
class FocusLevelConfig:
    """v4.47: 专注度等级判定与分心提醒的可调阈值"""
    focused_max_deviation_secs: int = 6       # v4.47: 30s窗口，≤6次偏离 → FOCUSED
    distracted_min_deviation_secs: int = 16   # v4.47: 30s窗口，≥16次偏离 → 候选 DISTRACTED
    gaze_ok_threshold: float = 30.0            # v4.47: gaze_score(0-60)≥30 → 视线在屏幕
    head_ok_threshold: float = 50.0            # head_score≥此值 → 头部稳定
    distract_count_threshold: int = 4          # ≥N 次切为分心 → 触发提醒
    distract_window: float = 600.0             # 分心统计窗口 (秒)
    notify_cooldown: float = 180.0             # 基础提醒冷却 (秒)
    distraction_gap: float = 300.0             # 两次分心提醒最短间隔 (秒)


FOCUS_LEVEL_CFG = FocusLevelConfig()

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
_dotenv_loaded: bool = False


def _load_dotenv(dotenv_path: Optional[str] = None) -> None:
    """加载 .env 文件到 os.environ（不依赖 python-dotenv）

    仅设置 os.environ 中尚不存在的键（.env 不覆盖已有环境变量）。
    支持 KEY=VALUE 和 KEY="VALUE" 两种格式，忽略空行和 # 注释行。
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True

    if dotenv_path is None:
        dotenv_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".env"
        )

    if not os.path.exists(dotenv_path):
        return

    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # 去掉可选引号
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                # 仅设置尚不存在的键（命令行覆盖 > 已有环境变量 > .env）
                if key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass  # .env 可选，加载失败不阻断启动


def _save_dotenv(dotenv_path: Optional[str] = None) -> None:
    """将 os.environ 中与 .env 相关的键写回 .env 文件。

    保留原 .env 中的注释行和非敏感键，更新/新增敏感键。
    """
    if dotenv_path is None:
        dotenv_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".env"
        )

    # 收集当前环境中的 .env 相关键
    env_keys = {
        "MINIMAX_API_KEY": os.environ.get("MINIMAX_API_KEY", ""),
    }

    # 尝试读取原 .env 保留注释和非敏感行
    existing_lines = []
    existing_keys = set()
    if os.path.exists(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        existing_lines.append(line.rstrip("\n"))
                        continue
                    if "=" in stripped:
                        k = stripped.split("=", 1)[0].strip()
                        if k in env_keys:
                            # 用新值替换
                            existing_lines.append(f"{k}={env_keys[k]}")
                            existing_keys.add(k)
                        else:
                            existing_lines.append(line.rstrip("\n"))
                            existing_keys.add(k)
        except Exception:
            existing_lines = []

    # 追加尚未写入的键
    for k, v in env_keys.items():
        if k not in existing_keys and v:
            existing_lines.append(f"{k}={v}")

    try:
        with open(dotenv_path, "w", encoding="utf-8") as f:
            f.write("\n".join(existing_lines))
            if existing_lines:
                f.write("\n")
    except Exception:
        pass


def load_yaml_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """从 YAML 文件加载配置

    Args:
        config_path: YAML 文件路径，默认为 config.yaml

    Returns:
        配置字典
    """
    global _yaml_config
    _load_dotenv()  # v4.33: 启动时自动加载 .env

    if _yaml_config is not None:
        return _yaml_config

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config.yaml"
        )

    if not os.path.exists(config_path):
        _yaml_config = {}
        return _yaml_config

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            _yaml_config = yaml.safe_load(f)
        return _yaml_config or {}
    except ImportError:
        _yaml_config = {}
        return _yaml_config
    except Exception as e:
        print(f"Warning: Failed to load config.yaml: {e}")
        _yaml_config = {}
        return _yaml_config


def get_yaml_value(*keys, default: Any = None) -> Any:
    """从 YAML 配置中获取值

    Args:
        keys: 配置键路径，例如 get_yaml_value("camera", "index")
        default: 默认值

    Returns:
        配置值或默认值

    v4.33: 自动展开 ${ENV_VAR} 占位符（从环境变量读取）。
    """
    import os as _os
    config = load_yaml_config()
    value = config
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return default
        if value is None:
            return default
    # 展开环境变量占位符 ${VAR}（仅字符串类型）
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        value = _os.environ.get(env_var, value)
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

    v4.33: ai.api_key 不写入 config.yaml，改为写入 .env + os.environ。
    这样即使 config.yaml 被误提交，密钥也不会泄露。

    Args:
        config_path: 目标路径，默认为 config.yaml

    Returns:
        True 保存成功
    """
    global _yaml_config

    if _yaml_config is None:
        return False

    # ── v4.33: 提取敏感值写入 .env ──
    ai_section = _yaml_config.get("ai", {})
    if isinstance(ai_section, dict) and "api_key" in ai_section:
        raw_key = ai_section.get("api_key", "")
        if raw_key and not (isinstance(raw_key, str) and raw_key.startswith("${")):
            # 真实 key → 写入 .env + 设置环境变量
            os.environ["MINIMAX_API_KEY"] = str(raw_key)
            _save_dotenv()
        elif raw_key == "" or raw_key is None:
            # 删除 key → 从 .env 和环境变量中移除
            os.environ.pop("MINIMAX_API_KEY", None)
            _save_dotenv()
        # 始终在 YAML 中保留占位符
        ai_section["api_key"] = "${MINIMAX_API_KEY}"

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
