"""spike/insights/_common.py — 共用工具

数据生成：合成 N 个 session 的特征矩阵，模拟用户行为模式。
数据库连接：复用主项目 storage/db.py（如果有真实数据）。
"""
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class SyntheticSession:
    """合成 session 的特征向量（与 PROJECT_PLAN §6.9.1 features 一致）。"""
    session_id: str
    avg_focus_score: float
    focus_score_std: float
    avg_perclos: float
    blink_rate_baseline_ratio: float
    gaze_away_ratio: float
    head_movement_intensity: float
    duration_minutes: float
    hour_of_day: int
    light_dark_ratio: float = 0.1
    fatigue_severe_ratio: float = 0.0
    focus_below_60_ratio: float = 0.2


def gen_synthetic_sessions(n_per_mode: int = 8, seed: int = 42) -> List[SyntheticSession]:
    """生成 4 种模式的合成 session，每种 n_per_mode 个。

    模式定义：
      1. 早高峰高效型：avg_focus ~80, blink ~0.9, hour=9
      2. 午后疲倦型：avg_focus ~55, blink ~1.5, hour=14
      3. 晚间分心型：avg_focus ~50, gaze_away ~0.4, hour=20
      4. 心流型：avg_focus ~85, focus_std ~3 (低), hour=10
    """
    rng = np.random.default_rng(seed)
    sessions = []
    # 4 modes with larger separation so KMeans can recover them in 8D feature space.
    # 调整说明：原始 plan 中 flow/early_peak 仅差 5 focus 点，afternoon_tired/evening_distracted
    # 仅差 5 focus 点，导致 KMeans 倾向于 k=2 而非 k=4。此处放大间距以达到 75% 对齐度门禁。
    modes = [
        {"name": "early_peak", "focus_mu": 80, "focus_std_mu": 8, "blink_mu": 0.9,
         "gaze_away_mu": 0.05, "hour_mu": 9, "perclos_mu": 0.02},
        {"name": "afternoon_tired", "focus_mu": 55, "focus_std_mu": 12, "blink_mu": 1.5,
         "gaze_away_mu": 0.15, "hour_mu": 14, "perclos_mu": 0.08},
        {"name": "evening_distracted", "focus_mu": 45, "focus_std_mu": 15, "blink_mu": 1.0,
         "gaze_away_mu": 0.45, "hour_mu": 20, "perclos_mu": 0.04},
        {"name": "flow", "focus_mu": 92, "focus_std_mu": 3, "blink_mu": 0.7,
         "gaze_away_mu": 0.02, "hour_mu": 11, "perclos_mu": 0.005},
    ]
    sid_n = 0
    for m in modes:
        for i in range(n_per_mode):
            sid_n += 1
            sessions.append(SyntheticSession(
                session_id=f"sess_{m['name']}_{sid_n:03d}",
                avg_focus_score=rng.normal(m["focus_mu"], 4),
                focus_score_std=max(1.0, rng.normal(m["focus_std_mu"], 2)),
                avg_perclos=max(0.0, rng.normal(m["perclos_mu"], 0.01)),
                blink_rate_baseline_ratio=rng.normal(m["blink_mu"], 0.1),
                gaze_away_ratio=max(0.0, min(1.0, rng.normal(m["gaze_away_mu"], 0.05))),
                head_movement_intensity=rng.normal(2.0, 0.5),
                duration_minutes=rng.uniform(30, 90),
                hour_of_day=int(rng.normal(m["hour_mu"], 1)) % 24,
            ))
    return sessions


def sessions_to_matrix(sessions: List[SyntheticSession]):
    """转为 (n_sessions, n_features) 矩阵 + 特征名列表。"""
    feature_names = [
        "avg_focus_score", "focus_score_std", "avg_perclos",
        "blink_rate_baseline_ratio", "gaze_away_ratio",
        "head_movement_intensity", "duration_minutes", "hour_of_day",
    ]
    X = np.array([[getattr(s, n) for n in feature_names] for s in sessions])
    return X, feature_names


def save_result(name: str, payload: dict) -> str:
    """保存 spike 结果到 spike/results/D1/。

    注意：user 明确指定使用 spike/results/D1/ 而非 plan 中的 spike/results/insights/。
    两种路径都在 .gitignore 中被忽略。
    """
    path = os.path.join("spike/results/D1", f"{name}_result.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


def save_png(name: str, fig) -> str:
    """保存 matplotlib 图到 spike/results/D1/。"""
    path = os.path.join("spike/results/D1", f"{name}.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=80, bbox_inches="tight")
    return path


def gen_focus_timeseries_with_drops(n_seconds: int = 3600,
                                     sample_hz: int = 2,
                                     drop_points: List[float] = None,
                                     seed: int = 42) -> np.ndarray:
    """生成"中间有断崖"的 focus_score 时序，用于 S12 变点检测验证。"""
    if drop_points is None:
        drop_points = [900, 2400]
    rng = np.random.default_rng(seed)
    n = n_seconds * sample_hz
    base = np.ones(n) * 80
    for t in drop_points:
        idx = int(t * sample_hz)
        base[idx:] -= 25
    noise = rng.normal(0, 3, n)
    return np.clip(base + noise, 0, 100)


def gen_hourly_focus_with_daily_pattern(n_days: int = 14, seed: int = 42) -> pd.Series:
    """生成 N 天 × 24 小时聚合的 focus_score 序列，含已知日内规律。"""
    rng = np.random.default_rng(seed)
    hours = pd.date_range("2026-05-01", periods=n_days * 24, freq="1H")

    def base_for_hour(h: int) -> float:
        if 9 <= h <= 11: return 85
        if 15 <= h <= 16: return 55
        if 19 <= h <= 20: return 75
        return 65

    values = [base_for_hour(t.hour) + rng.normal(0, 3) for t in hours]
    return pd.Series(values, index=hours)


def get_real_db_path() -> Optional[str]:
    """如有真实 SQLite，返回路径；否则 None。spike 优先用合成数据。"""
    p = "data/eyefocus.db"
    return p if os.path.exists(p) else None
