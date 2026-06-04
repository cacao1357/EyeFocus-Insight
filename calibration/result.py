"""calibration/result.py — CalibrationResult 数据契约（冻结字段）

字段在 T-CAL-01 锁定后不允许修改。其他任务依赖这些类型。

设计依据：spec §2.8。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple


@dataclass(frozen=True)
class CalibrationSignal:
    """单次校准采集到的所有信号统计。"""
    ear_mean: float            # 自然睁眼时 EAR 均值（基线）
    ear_min: float             # 闭眼时 EAR 最小值
    ear_mid: float             # 眯眼时 EAR 中间值
    yaw_mean: float            # 头部偏航均值 (自然正视, 单位度)
    yaw_range: Tuple[float, float]    # (左偏最大值, 右偏最大值) — T-CAL-31: 左=正, 右=负
    pitch_mean: float          # 头部俯仰均值 (单位度)
    pitch_range: Tuple[float, float]  # (仰角最大值, 俯角最大值) — 仰=负, 俯=正
    glasses_mode: bool         # 是否检测为戴眼镜
    timestamp: float           # 采集完成时间戳（unix epoch 秒）


@dataclass(frozen=True)
class BlinkCalibrationRound:
    """单轮眨眼计数校准数据。"""
    round_index: int           # 第几轮（1-based）
    duration_seconds: int      # 本轮时长（秒）
    user_blink_count: int      # 用户手动报告的眨眼次数
    program_blink_count: int   # 程序检测到的眨眼次数
    program_squint_count: int  # 程序检测到的眯眼次数
    error_rate: float          # (user - program) / user，正值=漏检，负值=误检
    adjustment_factor: float   # 本轮推导的阈值调整因子，clamp 到 [0.7, 1.3]


@dataclass(frozen=True)
class CalibrationResult:
    """完整校准结果 — 校准模块成功完成后返回给主程序的契约。

    严格契约（spec §决策 X1）：模块仅在用户完成全 5 阶段 + 总结页确认时返回此结果。
    取消/失败时模块返回 None，不返回部分结果。
    """
    session_id: str
    timestamp: datetime
    signal: CalibrationSignal
    blink_rounds: List[BlinkCalibrationRound]  # 0 个（跳过眨眼计数）或 2 个
    final_adjustment_factor: float             # 多轮平均（无轮次则为 1.0）
    final_blink_threshold: float               # ear_mean × 0.75 × final_adjustment_factor
    final_squint_threshold: float              # ear_mean × 0.75
    baseline_blink_rate: float                 # 每分钟眨眼次数（含跳过时的默认值 15.0）
    cqs: float                                 # 整体校准质量分（0.0-1.0）
    is_accepted: bool                          # 用户在总结页是否点了"继续 → 主监测"
    notes: str = ""                            # 可选：用户备注或失败诊断
