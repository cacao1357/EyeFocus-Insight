"""
analyzer/gamification.py — 游戏化引擎 (v4.17)

提供专注成就系统、每日统计、连续天数追踪。

用法：
    engine = GamificationEngine(db)
    new_achievements = engine.on_session_end(session, avg_focus)
    streak = engine.get_streak_days()
"""

import logging
from datetime import datetime
from typing import List, Optional

from storage.models import Achievement, DailyStats, Session

logger = logging.getLogger("eyefocus.analyzer")

# ── 成就定义 ──

ALL_ACHIEVEMENTS = [
    Achievement("first_session", "初次专注", "完成首个专注会话", "🌟"),
    Achievement("focus_30min", "专注入门", "单次会话专注≥30分钟", "⏱"),
    Achievement("focus_1h", "专注达人", "单次会话专注≥60分钟", "💪"),
    Achievement("focus_3h", "专注大师", "单次会话专注≥180分钟", "🏆"),
    Achievement("total_10h", "累积进步", "总专注时长≥10小时", "📈"),
    Achievement("total_50h", "专注强者", "总专注时长≥50小时", "🚀"),
    Achievement("streak_3", "初露锋芒", "连续使用≥3天", "🔥"),
    Achievement("streak_7", "坚持不懈", "连续使用≥7天", "💎"),
    Achievement("streak_30", "专注满贯", "连续使用≥30天", "👑"),
    Achievement("morning_person", "早起鸟", "最佳专注时段在上午", "☀️"),
]


class GamificationEngine:
    """游戏化引擎

    跟踪每日专注统计、检查成就解锁条件。
    所有状态持久化到数据库 daily_stats 表。
    """

    def __init__(self, db):
        self._db = db
        self._today = datetime.now().strftime("%Y-%m-%d")
        self._logged_achievements: set = set()  # 防重复通知

    def on_session_end(self, session: Session, avg_focus: float) -> List[Achievement]:
        """会话结束时更新统计并检查成就

        Args:
            session: 已结束的会话
            avg_focus: 会话平均专注度

        Returns:
            本次新解锁的成就列表
        """
        if not session.end_time:
            return []

        duration_min = session.duration_seconds() / 60.0 if session.duration_seconds() else 0.0

        # 更新当日统计
        today = self._today
        existing = self._db.get_daily_stats(today)
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
        self._db.save_daily_stats(stats)

        # 检查成就解锁（去重：仅首次通知）
        new_achievements = self._check_achievements(session, avg_focus, duration_min)
        first_time = [a for a in new_achievements if a.id not in self._logged_achievements]
        for a in first_time:
            self._logged_achievements.add(a.id)
            logger.info("🏅 新成就解锁: %s %s", a.icon, a.name)

        return first_time

    def get_streak_days(self) -> int:
        """计算连续使用天数

        从今天往前数，连续有记录的"天"的数量。
        今天的记录也会被计入。
        """
        all_stats = self._db.get_all_daily_stats()
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
            elif stat_date == check_date:
                # 中间跳了一天
                break
            else:
                # 日期不连续
                break

        return streak

    def get_today_minutes(self) -> float:
        """获取今日累计专注分钟数"""
        stats = self._db.get_daily_stats(self._today)
        return stats.total_focus_minutes if stats else 0.0

    def get_achievements(self) -> List[Achievement]:
        """获取所有成就及其解锁状态

        成就解锁记录存储在成就 ID 列表的占位机制中。
        """
        return ALL_ACHIEVEMENTS

    def _check_achievements(self, session: Session, avg_focus: float,
                            duration_min: float) -> List[Achievement]:
        """检查成就解锁条件"""
        today = self._today
        unlocked = []

        # 首次会话
        if self._is_first_session():
            unlocked.append(Achievement("first_session", "初次专注",
                                        "完成首个专注会话", "🌟", True, today))

        # 时长成就
        if duration_min >= 180:
            unlocked.append(Achievement("focus_3h", "专注大师",
                                        "单次会话专注≥180分钟", "🏆", True, today))
        elif duration_min >= 60:
            unlocked.append(Achievement("focus_1h", "专注达人",
                                        "单次会话专注≥60分钟", "💪", True, today))
        elif duration_min >= 30:
            unlocked.append(Achievement("focus_30min", "专注入门",
                                        "单次会话专注≥30分钟", "⏱", True, today))

        # 总时长成就
        total_minutes = self._get_total_minutes()
        if total_minutes >= 50 * 60:
            unlocked.append(Achievement("total_50h", "专注强者",
                                        "总专注时长≥50小时", "🚀", True, today))
        elif total_minutes >= 10 * 60:
            unlocked.append(Achievement("total_10h", "累积进步",
                                        "总专注时长≥10小时", "📈", True, today))

        # 连续天数成就
        streak = self.get_streak_days()
        if streak >= 30:
            unlocked.append(Achievement("streak_30", "专注满贯",
                                        "连续使用≥30天", "👑", True, today))
        elif streak >= 7:
            unlocked.append(Achievement("streak_7", "坚持不懈",
                                        "连续使用≥7天", "💎", True, today))
        elif streak >= 3:
            unlocked.append(Achievement("streak_3", "初露锋芒",
                                        "连续使用≥3天", "🔥", True, today))

        # 早起鸟（最高效时段在上午）
        if session.start_time.hour < 12 and avg_focus >= 75:
            unlocked.append(Achievement("morning_person", "早起鸟",
                                        "最佳专注时段在上午", "☀️", True, today))

        return unlocked

    def _is_first_session(self) -> bool:
        """判断是否是首个完整会话"""
        all_stats = self._db.get_all_daily_stats()
        total = sum(s.session_count for s in all_stats)
        return total <= 1

    def _get_total_minutes(self) -> float:
        """获取所有时间累计专注分钟数"""
        all_stats = self._db.get_all_daily_stats()
        return sum(s.total_focus_minutes for s in all_stats)


def create_gamification_engine(db) -> GamificationEngine:
    """工厂函数"""
    return GamificationEngine(db=db)
