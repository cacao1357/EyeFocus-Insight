"""
storage/models.py — EyeFocus Insight 数据模型定义

定义会话、帧记录、专注度记录、疲劳记录等核心数据模型。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class FatigueLevel(Enum):
    """疲劳等级枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GlassesMode(Enum):
    """眼镜模式枚举"""
    UNKNOWN = "unknown"
    WITH_GLASSES = "with_glasses"
    WITHOUT_GLASSES = "without_glasses"
    MANUAL_GLASSES = "manual_glasses"
    MANUAL_NO_GLASSES = "manual_no_glasses"


@dataclass
class Session:
    """会话数据模型"""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    baseline_ear: Optional[float] = None
    baseline_yaw_std: Optional[float] = None
    baseline_pitch_std: Optional[float] = None
    cqs_score: Optional[float] = None
    baseline_blink_rate: Optional[float] = None
    glasses_mode: GlassesMode = GlassesMode.UNKNOWN
    is_calibrated: bool = False
    is_active: bool = True

    def duration_seconds(self) -> Optional[float]:
        """计算会话时长（秒）

        会话未结束时返回从 start_time 到现在的时长。
        """
        end = self.end_time
        if end is None:
            end = datetime.now()
        return (end - self.start_time).total_seconds()


@dataclass
class FrameRecord:
    """单帧检测数据模型"""
    session_id: str
    timestamp: float  # Unix 时间戳（秒）
    ear_left: float
    ear_right: float
    ear_avg: float
    yaw: float
    pitch: float
    roll: float
    gaze_score: float  # 视线聚焦分数 0-100
    brightness: float  # 帧亮度 0-255
    face_detected: bool
    blendshapes: Optional[dict] = None  # MediaPipe blendshapes 数据
    # 以下字段与 PROJECT_PLAN.md §7 对齐
    blink_flag: bool = False
    perclos: Optional[float] = None
    gaze_status: Optional[str] = None  # 'screen' / 'away'
    fatigue_label: Optional[str] = None  # 'normal' / 'mild' / 'severe'
    focus_score: Optional[float] = None
    focus_breakdown: Optional[str] = None  # JSON
    light_level: Optional[str] = None  # 'bright' / 'normal' / 'dark'


@dataclass
class BlinkRecord:
    """眨眼记录模型（用于数据库存储）"""
    session_id: str
    start_timestamp: float
    end_timestamp: float
    duration_seconds: float
    ear_nadir: float  # 眨眼时的最小 EAR 值


@dataclass
class FocusRecord:
    """专注度记录模型（滑动窗口聚合）"""
    session_id: str
    window_start: float
    window_end: float
    focus_score: float  # 0-100
    eye_score: float  # 眼部专注分数 0-100
    head_score: float  # 头部姿态分数 0-100
    gaze_score: float  # 视线分数 0-100
    blink_rate: float  # 眨眼频率 (次/分钟)
    avg_ear: float
    avg_yaw: float
    avg_pitch: float


@dataclass
class FatigueRecord:
    """疲劳分析记录模型"""
    session_id: str
    timestamp: float
    fatigue_level: FatigueLevel
    blink_rate: float  # 眨眼频率 (次/分钟)
    avg_ear_nadir: float  # 平均眨眼 EAR 谷值
    head_stability: float  # 头部稳定性分数 0-100
    cumulative_fatigue_score: float  # 累积疲劳分数 0-100


@dataclass
class GlassesDetectionResult:
    """眼镜检测结果模型"""
    is_glasses: bool
    confidence: float  # 置信度 0-1
    squint_ratio: Optional[float] = None  # blendshapes 眯眼比率
    inner_canthus_distance: Optional[float] = None  # 眼角内侧距离
    inner_canthus_ratio: Optional[float] = None  # 归一化比值 inner_canthus_distance / pupil_distance
    method: Optional[str] = None  # 检测方法: "blendshapes", "distance", "both"


@dataclass
class BaselineResult:
    """基线校准结果模型"""
    session_id: str
    is_valid: bool
    cqs_score: float
    ear_mean: float
    ear_std: float
    yaw_std: float
    pitch_std: float
    valid_frame_count: int
    total_frame_count: int
    glasses_mode: GlassesMode = GlassesMode.UNKNOWN
    calibration_timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SystemStatus:
    """系统状态模型"""
    camera_available: bool
    model_loaded: bool
    is_calibrated: bool
    current_session_id: Optional[str] = None
    fps: float = 0.0
    last_error: Optional[str] = None


@dataclass
class CalibrationSignal:
    """单信号采集结果（v4.33: 统一为 calibration/result.py 的再导出）

    规范定义位于 calibration/result.py。此处保持向后兼容的别名。
    """
    ear_mean: float = 0.0           # EAR 均值（睁眼基线）
    ear_min: float = 0.0           # EAR 最小值（闭眼阈值参考）
    ear_mid: float = 0.0           # EAR 中间值（眯眼阈值参考）
    yaw_mean: float = 0.0          # 头部偏转均值
    yaw_range: tuple = (0.0, 0.0)  # (左偏最大值, 右偏最大值)
    pitch_mean: float = 0.0        # 头部俯仰均值
    pitch_range: tuple = (0.0, 0.0)  # (仰角最大值, 俯角最大值)
    glasses_mode: bool = False      # 眼镜模式
    timestamp: float = 0.0         # 采集时间戳


@dataclass
class BlinkCalibrationRound:
    """单轮眨眼校准数据"""
    round_index: int = 0           # 第几轮（1-3）
    duration_seconds: int = 0       # 本轮时长（秒）
    user_blink_count: int = 0      # 用户手动计数
    program_blink_count: int = 0   # 程序统计计数
    program_squint_count: int = 0  # 程序统计眯眼次数
    error_rate: float = 0.0        # 误差率
    adjustment_factor: float = 1.0 # 本轮调整因子


@dataclass
class CalibrationResult:
    """完整校准结果（v4.33: calibration/result.py 是 v4.2 路径的规范定义）

    此版本保持非冻结 + 全默认值以兼容 v3.x 路径（analyzer/user_calibration.py）。
    v4.2 路径使用 calibration.result.CalibrationResult（冻结字段）。
    两套字段已对齐：cqs 字段在两个版本中均存在。
    """
    session_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    signal: CalibrationSignal = field(default_factory=CalibrationSignal)
    blink_rounds: List[BlinkCalibrationRound] = field(default_factory=list)
    final_adjustment_factor: float = 1.0  # 多轮平均调整因子
    final_blink_threshold: float = 0.26  # 调整后的眨眼阈值
    final_squint_threshold: float = 0.20  # 调整后的眯眼阈值
    baseline_blink_rate: Optional[float] = None  # 个人基线眨眼频率 (次/分钟)
    cqs: float = 0.0              # v4.33: 校准质量分（与 calibration/result.py 对齐）
    is_accepted: bool = True      # 用户是否接受
    notes: str = ""              # 用户备注


# ── v4.17: 游戏化数据模型 ──


@dataclass
class DailyStats:
    """每日专注统计"""
    date: str  # "2026-06-16"
    total_focus_minutes: float = 0.0
    session_count: int = 0
    avg_focus_score: float = 0.0
    best_focus_score: float = 0.0
    longest_session_minutes: float = 0.0


@dataclass
class Achievement:
    """成就定义"""
    id: str
    name: str
    description: str
    icon: str  # emoji
    unlocked: bool = False
    unlocked_date: Optional[str] = None  # "2026-06-16"
