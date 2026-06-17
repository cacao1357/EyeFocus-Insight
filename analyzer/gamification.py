"""
analyzer/gamification.py — 游戏化引擎 (v4.24)

移除成就系统，保留：
- 每日专注统计持久化
- 连续使用天数追踪
- 今日累计时长

用法：
    engine = GamificationEngine(db)
    engine.on_session_end(session, avg_focus)
    streak = engine.get_streak_days()
"""

import logging
from datetime import datetime
from typing import Optional

from storage.models import DailyStats, Session

logger = logging.getLogger("eyefocus.analyzer")


class GamificationEngine:
    """游戏化引擎

    跟踪每日专注统计、连续天数。
    所有状态持久化到数据库 daily_stats 表。
    """

    def __init__(self, db):
        self._db = db

    def _today_str(self) -> str:
        """获取当前日期字符串（每次调用实时计算，防跨午夜）"""
        return datetime.now().strftime("%Y-%m-%d")

    def on_session_end(self, session: Session, avg_focus: float) -> None:
        """会话结束时更新每日统计

        Args:
            session: 已结束的会话
            avg_focus: 会话平均专注度
        """
        if not session.end_time:
            return

        duration_min = session.duration_seconds() / 60.0 if session.duration_seconds() else 0.0
        today = self._today_str()

        try:
            existing = self._db.get_daily_stats(today)
        except Exception as e:
            logger.warning("获取每日统计失败: %s", e)
            existing = None

        if existing:
            stats = DailyStats(
                date=today,
                total_focus_minutes=existing.total_focus_minutes + duration_min,
                session_count=existing.session_count + 1,
                avg_focus_score=(existing.avg_focus_score * existing.session_count + avg_focus) / (existing.session_count + 1),
                best_focus_score=max(existing.best_focus_score, avg_focus),
                longest_session_minutes=max(existing.longest_session_minutes, duration_min),
            )
        else:
            stats = DailyStats(
                date=today,
                total_focus_minutes=duration_min,
                session_count=1,
                avg_focus_score=avg_focus,
                best_focus_score=avg_focus,
                longest_session_minutes=duration_min,
            )

        try:
            self._db.save_daily_stats(stats)
        except Exception as e:
            logger.warning("保存每日统计失败: %s", e)

    def get_streak_days(self) -> int:
        """计算连续使用天数

        从今天往前数，连续有记录的"天"的数量。
        """
        try:
            all_stats = self._db.get_all_daily_stats()
        except Exception:
            return 0
        if not all_stats:
            return 0

        dates = sorted(set(s.date for s in all_stats), reverse=True)
        if not dates:
            return 0

        from datetime import datetime, timedelta
        streak = 0
        check_date = datetime.now().date()

        for d in dates:
            stat_date = datetime.strptime(d, "%Y-%m-%d").date()
            if stat_date == check_date:
                streak += 1
                check_date -= timedelta(days=1)
            elif stat_date < check_date:
                break

        return streak

    def get_today_minutes(self) -> float:
        """获取今日累计专注分钟数"""
        try:
            stats = self._db.get_daily_stats(self._today_str())
            return stats.total_focus_minutes if stats else 0.0
        except Exception:
            return 0.0


def create_gamification_engine(db) -> GamificationEngine:
    """工厂函数"""
    return GamificationEngine(db=db)
