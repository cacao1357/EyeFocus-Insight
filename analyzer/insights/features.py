"""analyzer/insights/features.py — 特征提取与矩阵化 (v4.1)

从 SQLite 历史会话数据提取特征向量，构建 (n_sessions, n_features) 矩阵。

特征列表（与 PROJECT_PLAN §6.9.1 对齐）：
  - avg_focus_score: 平均专注度
  - focus_score_std: 专注度标准差
  - avg_perclos: 平均 PERCLOS 值
  - blink_rate_ratio: 眨眼频率 / 基线眨眼频率
  - gaze_away_ratio: 视线偏离总时长占比
  - head_movement: 头部运动强度
  - duration_minutes: 会话时长
  - hour_of_day: 开始时段（小时，0-23）
  - fatigue_severe_ratio: HIGH 疲劳帧占比
  - light_dark_ratio: 暗光帧占比（可选）

依赖：storage/db.py DatabaseManager
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

from storage.db import DatabaseManager
from storage.models import FatigueLevel

logger = logging.getLogger("eyefocus.insights.features")


@dataclass
class SessionFeatures:
    """单个 session 的特征向量。"""
    session_id: str
    avg_focus_score: float
    focus_score_std: float
    avg_perclos: float
    blink_rate_ratio: float     # blink_rate / baseline_blink_rate
    gaze_away_ratio: float      # 视线偏离占比 [0, 1]
    head_movement: float         # 头部运动强度（yaw/pitch std 均值）
    duration_minutes: float
    hour_of_day: int             # 开始时段 (0-23)
    fatigue_severe_ratio: float = 0.0   # HIGH 疲劳占比
    light_dark_ratio: float = 0.0       # 暗光帧占比


# 特征名列表（与矩阵列一一对应）
FEATURE_NAMES = [
    "avg_focus_score",
    "focus_score_std",
    "avg_perclos",
    "blink_rate_ratio",
    "gaze_away_ratio",
    "head_movement",
    "duration_minutes",
    "hour_of_day",
    "fatigue_severe_ratio",
    "light_dark_ratio",
]


def _fetch_all_sessions(db: DatabaseManager) -> list:
    """从 DB 读取所有已结束的活跃 session 元数据。

    Returns:
        list of sqlite3.Row: session_id, start_time, end_time,
        baseline_blink_rate, baseline_ear
    """
    with db._get_cursor() as cur:
        cur.execute("""
            SELECT session_id, start_time, end_time,
                   baseline_blink_rate, baseline_ear, cqs_score
            FROM sessions
            WHERE is_active = 1 AND end_time IS NOT NULL
            ORDER BY start_time
        """)
        return cur.fetchall()


def _fetch_focus_records(db: DatabaseManager, session_id: str) -> List[dict]:
    """读取 session 的 focus_records 聚合数据。"""
    with db._get_cursor() as cur:
        cur.execute("""
            SELECT focus_score, blink_rate, avg_ear, avg_yaw, avg_pitch
            FROM focus_records
            WHERE session_id = ?
            ORDER BY window_start
        """, (session_id,))
        return [dict(r) for r in cur.fetchall()]


def _fetch_frame_summary(db: DatabaseManager, session_id: str) -> dict:
    """读取 session 的帧级汇总统计。"""
    with db._get_cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total_frames,
                AVG(CASE WHEN perclos IS NOT NULL THEN perclos ELSE 0 END) as avg_perclos,
                AVG(CASE WHEN gaze_status = 'away' THEN 1.0 ELSE 0 END) as gaze_away_ratio,
                AVG(brightness) as avg_brightness
            FROM frame_records
            WHERE session_id = ?
        """, (session_id,))
        row = dict(cur.fetchone())
        # 暗光判断：brightness < 50 算 dark
        cur.execute("""
            SELECT COUNT(*) as dark_frames
            FROM frame_records
            WHERE session_id = ? AND brightness < 50
        """, (session_id,))
        dark_row = dict(cur.fetchone())
        total = row.get("total_frames", 0) or 1
        row["light_dark_ratio"] = dark_row.get("dark_frames", 0) / total
        return row


def _fetch_fatigue_summary(db: DatabaseManager, session_id: str) -> dict:
    """读取 session 的疲劳汇总。"""
    with db._get_cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN fatigue_level = 'high' THEN 1 ELSE 0 END) as severe_count
            FROM fatigue_records
            WHERE session_id = ?
        """, (session_id,))
        row = dict(cur.fetchone())
        total = row.get("total", 0) or 1
        row["fatigue_severe_ratio"] = row.get("severe_count", 0) / total
        return row


def extract_session_features(db: DatabaseManager, session_id: str) -> Optional[SessionFeatures]:
    """从 DB 提取单个 session 的特征向量。

    Args:
        db: DatabaseManager 实例
        session_id: 目标会话 ID

    Returns:
        SessionFeatures 或 None（数据不足时）
    """
    # 获取 session 元数据
    with db._get_cursor() as cur:
        cur.execute("""
            SELECT session_id, start_time, end_time,
                   baseline_blink_rate, baseline_ear
            FROM sessions
            WHERE session_id = ?
        """, (session_id,))
        srow = cur.fetchone()
    if not srow:
        logger.warning("session 不存在: %s", session_id)
        return None

    # 解析元数据
    start_time = srow["start_time"]
    if isinstance(start_time, str):
        try:
            dt = datetime.fromisoformat(start_time)
        except ValueError:
            dt = datetime.now()
    else:
        dt = datetime.now()
    end_time = srow["end_time"]
    baseline_blink_rate = srow["baseline_blink_rate"] or 15.0

    # 时长（分钟）
    duration_minutes = 30.0
    if end_time:
        if isinstance(end_time, str):
            try:
                end_dt = datetime.fromisoformat(end_time)
                duration_minutes = max(1.0, (end_dt - dt).total_seconds() / 60.0)
            except ValueError:
                pass
        else:
            duration_minutes = 30.0

    # 专注度记录
    focus_recs = _fetch_focus_records(db, session_id)
    if not focus_recs:
        logger.debug("session %s 无 focus_records，跳过", session_id)
        return None

    focus_scores = [r["focus_score"] for r in focus_recs if r.get("focus_score") is not None]
    if not focus_scores:
        return None
    avg_focus = float(np.mean(focus_scores))
    focus_std = float(np.std(focus_scores))

    blink_rates = [r["blink_rate"] for r in focus_recs if r.get("blink_rate") is not None]
    avg_blink_rate = float(np.mean(blink_rates)) if blink_rates else 15.0
    blink_rate_ratio = avg_blink_rate / baseline_blink_rate if baseline_blink_rate > 0 else 1.0

    # 帧汇总
    frame_summary = _fetch_frame_summary(db, session_id)
    avg_perclos = frame_summary.get("avg_perclos") or 0.0
    gaze_away_ratio = frame_summary.get("gaze_away_ratio") or 0.0
    light_dark_ratio = frame_summary.get("light_dark_ratio") or 0.0

    # 头部运动（从 focus_records 的 avg_yaw/avg_pitch 算）
    yaw_vals = [abs(r.get("avg_yaw", 0.0) or 0.0) for r in focus_recs]
    pitch_vals = [abs(r.get("avg_pitch", 0.0) or 0.0) for r in focus_recs]
    head_movement = float(np.mean(yaw_vals + pitch_vals)) if (yaw_vals or pitch_vals) else 0.0

    # 疲劳汇总
    fatigue_summary = _fetch_fatigue_summary(db, session_id)
    fatigue_severe_ratio = fatigue_summary.get("fatigue_severe_ratio") or 0.0

    # 时段
    hour_of_day = dt.hour

    return SessionFeatures(
        session_id=session_id,
        avg_focus_score=round(avg_focus, 2),
        focus_score_std=round(focus_std, 2),
        avg_perclos=round(avg_perclos, 4),
        blink_rate_ratio=round(blink_rate_ratio, 3),
        gaze_away_ratio=round(gaze_away_ratio, 4),
        head_movement=round(head_movement, 3),
        duration_minutes=round(duration_minutes, 1),
        hour_of_day=hour_of_day,
        fatigue_severe_ratio=round(fatigue_severe_ratio, 4),
        light_dark_ratio=round(light_dark_ratio, 4),
    )


def features_to_matrix(features: List[SessionFeatures]) -> Tuple[np.ndarray, List[str]]:
    """将 SessionFeatures 列表转为 (n, m) 矩阵 + 特征名。

    Args:
        features: SessionFeatures 列表

    Returns:
        (X, feature_names): X 为 (n_features, n_features) float 矩阵，
                            feature_names 为列名列表
    """
    if not features:
        return np.empty((0, len(FEATURE_NAMES))), FEATURE_NAMES
    X = np.array([[getattr(f, name) for name in FEATURE_NAMES] for f in features])
    return X, FEATURE_NAMES


def extract_all_sessions(db: DatabaseManager) -> Tuple[List[SessionFeatures], np.ndarray, List[str]]:
    """从 DB 提取所有已结束 session 的特征。

    Args:
        db: DatabaseManager 实例

    Returns:
        (features, X, feature_names): 特征对象列表 + 矩阵 + 列名
        无数据时返回 ([], array([]), [])
    """
    rows = _fetch_all_sessions(db)
    features = []
    for row in rows:
        sf = extract_session_features(db, row["session_id"])
        if sf is not None:
            features.append(sf)

    if not features:
        return [], np.array([]), FEATURE_NAMES

    X, fn = features_to_matrix(features)
    return features, X, fn
