"""calibration/config.py — CalibrationConfig 配置项

集中管理：阶段时长、判定阈值、UI 尺寸、音频开关。
设计依据：spec §2.9。
"""
from dataclasses import dataclass


@dataclass
class CalibrationConfig:
    """校准模块配置 — 所有可调参数。"""

    # ---------- 阶段时长（秒）----------
    auto_baseline_seconds: float = 7.0
    closed_eyes_seconds: float = 5.0
    open_eyes_verify_seconds: float = 3.0
    squint_seconds: float = 8.0
    head_direction_seconds: float = 3.0   # 每个方向单独 3 秒（4 方向共 12s）
    blink_round_seconds: float = 15.0      # 每轮 15s
    blink_rounds_count: int = 2            # 2 轮（spec P2 精简，原 3 轮）

    # ---------- 判定阈值 ----------
    closed_eyes_min_ratio: float = 0.6          # T-CAL-15: ear_min ≤ baseline × 此值算闭眼成功 (放宽 0.5→0.6 适配用户实测)
    squint_baseline_ratio: float = 0.75         # squint_threshold = baseline × 此值
    head_direction_min_degrees: float = 20.0    # T-CAL-16: 每个方向 |偏转| ≥ 此度数算有效 (放宽 10°→20° 适配用户幅度)
    blink_count_min: int = 5                    # 用户输入眨眼数下限
    blink_count_max: int = 60                   # 上限

    # ---------- UI 参数 ----------
    ui_panel_height_px: int = 240               # 下方 UI 区高度（视频区固定 480）
    button_height_px: int = 50
    button_padding_px: int = 10

    # ---------- 音频参数 ----------
    tts_rate: int = 180                         # pyttsx3 语速（中文）
    audio_enabled: bool = True                  # False 时跳过所有音频
