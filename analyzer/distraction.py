"""analyzer/distraction.py — 分心模式识别模块 (v4.1)

基于 gaze_score + face_detected 检测分心事件，分类模式，生成热力图。

模块输出：
  - DistractionResult: 分心事件列表 + 统计 + 模式分类 + 热力图

依赖：
  - storage.db: DatabaseManager 读取 frame_records
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger("eyefocus.distraction")

# ── 默认阈值 ─────────────────────────────────────────────
GAZE_DISTRACTED_THRESHOLD = 40.0   # gaze_score < 此值视为分心
SHORT_MAX_SEC = 15.0                # 短分心上限
MEDIUM_MAX_SEC = 60.0               # 中分心上限
LONG_MIN_SEC = 60.0                 # 长分心下限
MIN_EVENT_GAP_SEC = 3.0             # 小于此间隔的连续分心合并为一个事件


@dataclass
class DistractionEvent:
    """单个分心事件。"""
    start_time: float          # Unix 时间戳
    end_time: float
    duration_seconds: float
    category: str              # "short" / "medium" / "long"
    mean_gaze_score: float     # 期间平均 gaze_score


@dataclass
class DistractionResult:
    """分心分析完整结果。"""
    detected: bool                         # 是否有分心事件
    total_events: int                      # 总事件数
    total_distraction_seconds: float       # 总分心秒数
    distraction_ratio: float               # 分心占比 (0-1)
    n_frames_total: int                    # 总帧数
    n_frames_distracted: int               # 分心帧数

    # 按类别统计
    short_events: int = 0                  # 3-15s
    medium_events: int = 0                 # 15-60s
    long_events: int = 0                   # 60s+

    events: List[DistractionEvent] = field(default_factory=list)

    # 模式分类
    pattern_type: Optional[str] = None     # "frequent_short" / "intermittent" / "long_breaks"
    pattern_description: Optional[str] = None

    # 热力图（按分钟聚合，每分钟的分心比例 0-1）
    heatmap: List[float] = field(default_factory=list)
    heatmap_labels: List[str] = field(default_factory=list)  # 如 ["+0min", "+1min", ...]


def _fetch_frame_data(db, session_id: str) -> List[Tuple[float, float, bool]]:
    """从 frame_records 读取 (timestamp, gaze_score, face_detected) 三元组。

    Returns:
        [(timestamp, gaze_score, face_detected), ...] 按时间升序
    """
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT timestamp, gaze_score, face_detected
            FROM frame_records
            WHERE session_id = ? AND gaze_score IS NOT NULL
            ORDER BY timestamp
        """, (session_id,))
        rows = cur.fetchall()

    result = []
    for row in rows:
        ts = row["timestamp"]
        gaze = row["gaze_score"]
        face = bool(row["face_detected"]) if row["face_detected"] is not None else True
        result.append((ts, gaze, face))
    return result


def _is_distracted(gaze_score: float, face_detected: bool) -> bool:
    """判断单帧是否处于分心状态。"""
    return (not face_detected) or (gaze_score < GAZE_DISTRACTED_THRESHOLD)


def _detect_events(frames: List[Tuple[float, float, bool]]) -> List[DistractionEvent]:
    """从帧数据中检测分心事件。

    连续分心帧合并，间隔 < MIN_EVENT_GAP_SEC 的合并为同一事件。

    Args:
        frames: [(timestamp, gaze_score, face_detected), ...]

    Returns:
        DistractionEvent 列表（按开始时间降序）
    """
    raw_segments: List[List[Tuple[float, float, bool]]] = []
    current: List[Tuple[float, float, bool]] = []

    for f in frames:
        ts, gaze, face = f
        if _is_distracted(gaze, face):
            current.append(f)
        else:
            if current:
                raw_segments.append(current)
                current = []

    if current:
        raw_segments.append(current)

    if not raw_segments:
        return []

    # 合并间隔小的段
    merged: List[List[Tuple[float, float, bool]]] = [raw_segments[0]]
    for seg in raw_segments[1:]:
        gap = seg[0][0] - merged[-1][-1][0]
        if gap < MIN_EVENT_GAP_SEC:
            merged[-1].extend(seg)
        else:
            merged.append(seg)

    # 转为 DistractionEvent
    events = []
    for seg in merged:
        duration = seg[-1][0] - seg[0][0]
        if duration < 3.0:  # < 3 秒不算分心事件
            continue
        mean_gaze = sum(f[1] for f in seg) / len(seg)

        if duration <= SHORT_MAX_SEC:
            category = "short"
        elif duration <= MEDIUM_MAX_SEC:
            category = "medium"
        else:
            category = "long"

        events.append(DistractionEvent(
            start_time=seg[0][0],
            end_time=seg[-1][0],
            duration_seconds=round(duration, 1),
            category=category,
            mean_gaze_score=round(mean_gaze, 1),
        ))

    # 按开始时间降序（最新的在前）
    events.sort(key=lambda e: e.start_time, reverse=True)
    return events


def _build_heatmap(frames: List[Tuple[float, float, bool]],
                   events: List[DistractionEvent]) -> Tuple[List[float], List[str]]:
    """按分钟聚合分心比例用于热力图。

    Args:
        frames: 原始帧数据
        events: 检测到的分心事件

    Returns:
        (heatmap, labels): 每分钟分心比例 [0-1], 标签如 ["+0min", "+1min"]
    """
    if not frames:
        return [], []

    start_ts = frames[0][0]
    end_ts = frames[-1][0]
    total_minutes = max(1, int((end_ts - start_ts) / 60) + 1)

    # 初始化每分钟计数器
    per_minute_total = [0] * total_minutes
    per_minute_distracted = [0] * total_minutes

    for ts, gaze, face in frames:
        minute_idx = int((ts - start_ts) / 60)
        if minute_idx >= total_minutes:
            minute_idx = total_minutes - 1
        per_minute_total[minute_idx] += 1
        if _is_distracted(gaze, face):
            per_minute_distracted[minute_idx] += 1

    heatmap = []
    labels = []
    for i in range(total_minutes):
        total = per_minute_total[i]
        ratio = per_minute_distracted[i] / total if total > 0 else 0.0
        heatmap.append(round(ratio, 4))
        labels.append(f"+{i}min")

    return heatmap, labels


def _classify_pattern(result: DistractionResult) -> None:
    """根据事件统计分类分心模式。

    规则：
      - 短事件(short)占比 > 60% 且事件数 >= 4 → "frequent_short" 高频短促分心
      - 长事件(long) >= 1 且总占比 > 20% → "long_breaks" 单次长断
      - 其余 → "intermittent" 间歇中长分心
    """
    if result.total_events == 0:
        return

    short_ratio = result.short_events / result.total_events if result.total_events > 0 else 0
    distraction_ratio = result.distraction_ratio

    if short_ratio > 0.6 and result.total_events >= 4:
        result.pattern_type = "frequent_short"
        result.pattern_description = (
            f"频繁短促分心（{result.short_events}/{result.total_events} 为短分心），"
            f"可能受频繁打断或通知影响"
        )
    elif result.long_events >= 1 and distraction_ratio > 0.2:
        result.pattern_type = "long_breaks"
        result.pattern_description = (
            f"存在长时间分心（{result.long_events} 次 ≥ 60s），"
            f"分心总占比 {distraction_ratio:.1%}，可能需要调整工作环境"
        )
    else:
        result.pattern_type = "intermittent"
        result.pattern_description = (
            f"间歇性分心（{result.total_events} 次事件），"
            f"平均每 {result.total_distraction_seconds / result.total_events:.0f}s/次"
        )


def analyze_distraction(db, session_id: str) -> DistractionResult:
    """分析指定 session 的分心行为。

    Args:
        db: DatabaseManager 实例
        session_id: 目标会话 ID

    Returns:
        DistractionResult
    """
    frames = _fetch_frame_data(db, session_id)

    if not frames or len(frames) < 10:
        return DistractionResult(detected=False, total_events=0,
                                 total_distraction_seconds=0.0,
                                 distraction_ratio=0.0,
                                 n_frames_total=0, n_frames_distracted=0)

    n_total = len(frames)
    n_distracted = sum(1 for f in frames if _is_distracted(f[1], f[2]))
    distraction_ratio = n_distracted / n_total if n_total > 0 else 0.0

    events = _detect_events(frames)
    total_sec = sum(e.duration_seconds for e in events)

    short_count = sum(1 for e in events if e.category == "short")
    medium_count = sum(1 for e in events if e.category == "medium")
    long_count = sum(1 for e in events if e.category == "long")

    result = DistractionResult(
        detected=len(events) > 0,
        total_events=len(events),
        total_distraction_seconds=round(total_sec, 1),
        distraction_ratio=round(distraction_ratio, 4),
        n_frames_total=n_total,
        n_frames_distracted=n_distracted,
        short_events=short_count,
        medium_events=medium_count,
        long_events=long_count,
        events=events,
    )

    heatmap, labels = _build_heatmap(frames, events)
    result.heatmap = heatmap
    result.heatmap_labels = labels

    _classify_pattern(result)

    return result
