"""spike/test_report_with_insights.py — 验证 insights 报告生成

生成合成数据 → 运行 pipeline → 输出 HTML → 浏览器打开。
"""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

from storage.db import create_database_manager
from storage.models import (
    FrameRecord, FocusRecord, FatigueRecord, BlinkRecord, FatigueLevel,
)
import numpy as np
import time
from datetime import datetime


def _make_synthetic_data(db, session_id: str, n_minutes: int = 30,
                         target_focus: float = 70.0,
                         fatigue_level: FatigueLevel = FatigueLevel.LOW):
    """向 session 写入合成帧/疲劳/眨眼/专注度数据。"""
    base_time = time.time() - n_minutes * 60
    rng = np.random.default_rng(hash(session_id) % 2**32)

    # 专注度记录 (每分钟一条，insights pipeline 消费)
    for i in range(n_minutes):
        ws = base_time + i * 60
        we = ws + 60
        # 每个 session 有波动，末尾下降模拟疲劳
        decline = max(0, (i / n_minutes) * 20)  # 最多下降 20 分
        focus = target_focus - rng.normal(decline, 5)
        focus = max(0, min(100, focus))
        db.write_focus_record(session_id, FocusRecord(
            session_id=session_id,
            window_start=ws,
            window_end=we,
            focus_score=round(focus, 1),
            eye_score=round(focus + rng.uniform(-5, 5), 1),
            head_score=round(80 + rng.uniform(-10, 10), 1),
            gaze_score=round(focus + rng.uniform(-10, 5), 1),
            blink_rate=round(15 + rng.uniform(0, 5), 1),
            avg_ear=round(0.40 - rng.uniform(0, 0.03), 4),
            avg_yaw=round(rng.normal(0, 5), 2),
            avg_pitch=round(rng.normal(0, 4), 2),
        ))

    # 帧记录 (1 fps，报告图表使用)
    for i in range(min(n_minutes * 60, 300)):  # 最多 5 分钟给帧记录
        ts = base_time + i
        focus = target_focus - rng.normal(0, 5)
        focus = max(0, min(100, focus))
        ear = 0.40 - rng.normal(0, 0.02)
        yaw = rng.normal(0, 5)
        db.write_frame(session_id, FrameRecord(
            session_id=session_id,
            timestamp=ts,
            ear_left=ear + 0.01, ear_right=ear - 0.01, ear_avg=ear,
            yaw=yaw, pitch=rng.normal(0, 4), roll=rng.normal(0, 2),
            gaze_score=focus + rng.uniform(-10, 5),
            brightness=rng.uniform(40, 80),
            face_detected=True,
            blendshapes=None,
        ))

    # 疲劳记录 (每分钟一条)
    for i in range(n_minutes):
        ts = base_time + i * 60
        db.write_fatigue_record(session_id, FatigueRecord(
            session_id=session_id,
            timestamp=ts,
            fatigue_level=fatigue_level,
            blink_rate=15 + rng.uniform(0, 5),
            avg_ear_nadir=0.25 + rng.uniform(0, 0.05),
            head_stability=0.8 + rng.uniform(0, 0.1),
            cumulative_fatigue_score=i / n_minutes * 100,
        ))

    # 眨眼事件 (~15次/分钟)
    for i in range(n_minutes * 15):
        db.write_blink_event(session_id, BlinkRecord(
            session_id=session_id,
            start_timestamp=base_time + rng.uniform(0, n_minutes * 60),
            end_timestamp=base_time + rng.uniform(0.05, 0.15),
            duration_seconds=rng.uniform(0.05, 0.15),
            ear_nadir=0.20 + rng.uniform(0, 0.05),
        ))


def main():
    # 创建临时数据库
    db = create_database_manager(":memory:")
    db.initialize()

    # 创建多样化的 sessions: 高效/普通/低效/短时/分心, 各种模式
    print("创建合成数据...")
    session_ids = []
    patterns = [
        ("高效专注", 85, 20, FatigueLevel.LOW),    # 高专注, 不疲劳
        ("普通上午", 72, 30, FatigueLevel.LOW),
        ("普通下午", 65, 45, FatigueLevel.MEDIUM),
        ("疲劳工作", 55, 60, FatigueLevel.HIGH),    # 低专注, 高疲劳
        ("分心模式", 45, 35, FatigueLevel.MEDIUM),  # 低专注+频繁分心
        ("短时冲刺", 90, 15, FatigueLevel.LOW),     # 短时高专注
        ("长时会议", 60, 90, FatigueLevel.HIGH),    # 长时低专注
        ("上午高效", 80, 40, FatigueLevel.LOW),
        ("午后低迷", 50, 50, FatigueLevel.MEDIUM),  # 下午低效
        ("加班疲劳", 40, 45, FatigueLevel.HIGH),    # 晚上加班
    ]
    for i, (label, avg_focus, duration, fatigue) in enumerate(patterns):
        sid = db.create_session()
        db.update_session(sid,
            end_time=datetime.now(),
            is_active=False,
            is_calibrated=True,
            baseline_ear=0.40,
            baseline_blink_rate=18.0,
        )
        _make_synthetic_data(db, sid, n_minutes=duration,
                             target_focus=avg_focus, fatigue_level=fatigue)
        session_ids.append(sid)
        print(f"  [{label:6s}] session {sid[-12:]}: {avg_focus}分, {duration}min")

    target_sid = session_ids[0]

    # 生成报告
    print(f"\n生成含 insights 的 HTML 报告 (session: {target_sid})...")
    from reporter.report_html import create_html_generator

    generator = create_html_generator(db)
    html = generator.generate_report_with_insights(target_sid)

    os.makedirs("reports", exist_ok=True)
    report_path = f"reports/spike_insights_test.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {report_path}")

    # 浏览器打开
    import webbrowser
    webbrowser.open(os.path.abspath(report_path))

    print("\n✅ 完成! 请在浏览器中检查 4 个 insights 章节。")
    print("   - 工作模式分析 (饼图)")
    print("   - 今日异常分析 (条形图)")
    print("   - 长期趋势 (24h 折线图)")
    print("   - 关联分析 (effect size 图)")

    db.close()


if __name__ == "__main__":
    main()
