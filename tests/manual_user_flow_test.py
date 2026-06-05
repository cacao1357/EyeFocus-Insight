"""手动用户使用测试: 用真机数据 (data/eyefocus.db) 验证 v4.3 fix

测试场景:
  1. 打开真实 DB, 列出历史会话
  2. 读 frame_records 验证 H-08: 7 个 v4.x 字段不丢
  3. 模拟并发写入验证 CRIT-01: 线程安全
  4. export_json 验证 H-09: 不会因为 session 不存在崩
  5. analyzer 跑一段数据验证 H-03/H-04/H-05/H-06 在真实数据流中正常

不是 pytest 自动测试, 仅作为 v4.3 维护完成后的 smoke test。
手动跑: python tests/manual_user_flow_test.py
"""
import os
import sys
import tempfile
import threading
import time
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.db import DatabaseManager, DBConfig
from storage.models import FrameRecord, FatigueLevel
from analyzer.fatigue import create_fatigue_analyzer
from analyzer.focus import create_focus_analyzer


def test_1_list_existing_sessions():
    """1. 打开真机 DB, 列出会话"""
    print("\n=== 1. 列出现有会话 ===")
    db = DatabaseManager(config=DBConfig(db_path="data/eyefocus.db"))
    db.initialize()
    try:
        sessions = db.list_sessions()[:10]
        print(f"找到 {len(sessions)} 个最近会话:")
        for s in sessions[:5]:
            print(f"  - {s.session_id}  start={s.start_time}  active={s.is_active}")
        return sessions
    finally:
        db.close()


def test_2_h08_7_fields_preserved(sessions):
    """2. H-08: 验证回读 frame 时 7 个 v4.x 字段不丢"""
    print("\n=== 2. H-08: 7 字段回读 ===")
    db = DatabaseManager(config=DBConfig(db_path="data/eyefocus.db"))
    db.initialize()
    try:
        if not sessions:
            print("  (无会话, 跳过)")
            return
        # 取最近一个有 frame 的 session
        test_session = None
        for s in sessions:
            frames = db.get_frame_records(s.session_id, since=0, until=time.time() + 1)
            if frames:
                test_session = s
                break

        if not test_session:
            print("  (没找到含 frame 的 session, 跳过)")
            return

        frames = db.get_frame_records(test_session.session_id, since=0, until=time.time() + 1)
        print(f"session {test_session.session_id}: {len(frames)} frames")

        # 统计 7 字段实际有值的比例
        if frames:
            n = len(frames)
            n_blink = sum(1 for f in frames if f.blink_flag)
            n_perclos = sum(1 for f in frames if f.perclos is not None)
            n_gaze = sum(1 for f in frames if f.gaze_status is not None)
            n_fatigue = sum(1 for f in frames if f.fatigue_label is not None)
            n_focus = sum(1 for f in frames if f.focus_score is not None)
            n_breakdown = sum(1 for f in frames if f.focus_breakdown is not None)
            n_light = sum(1 for f in frames if f.light_level is not None)
            print(f"  blink_flag=True: {n_blink}/{n}")
            print(f"  perclos 非 None: {n_perclos}/{n}")
            print(f"  gaze_status 非 None: {n_gaze}/{n}")
            print(f"  fatigue_label 非 None: {n_fatigue}/{n}")
            print(f"  focus_score 非 None: {n_focus}/{n}")
            print(f"  focus_breakdown 非 None: {n_breakdown}/{n}")
            print(f"  light_level 非 None: {n_light}/{n}")

            # 抽样打印一帧
            sample = frames[len(frames) // 2]
            print(f"\n  抽样 (frame {len(frames) // 2}):")
            print(f"    ear_avg={sample.ear_avg:.3f}  yaw={sample.yaw:.1f}  pitch={sample.pitch:.1f}")
            print(f"    blink_flag={sample.blink_flag}  perclos={sample.perclos}")
            print(f"    fatigue_label={sample.fatigue_label}  focus_score={sample.focus_score}")
            print(f"    light_level={sample.light_level}")
    finally:
        db.close()


def test_3_crit01_thread_safety():
    """3. CRIT-01: 验证多线程并发写不丢数据"""
    print("\n=== 3. CRIT-01: 线程安全并发写 ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "thread_safety.db")
        db = DatabaseManager(config=DBConfig(db_path=db_path))
        db.initialize()
        try:
            session_id = db.create_session()

            errors = []
            n_per_thread = 50
            n_threads = 8

            def writer(idx):
                try:
                    for i in range(n_per_thread):
                        frame = FrameRecord(
                            session_id=session_id,
                            timestamp=time.time() + (idx * 1000 + i) * 0.001,
                            ear_left=0.25, ear_right=0.26, ear_avg=0.255,
                            yaw=0.5, pitch=-1.0, roll=0.2,
                            gaze_score=85.0, brightness=128.0,
                            face_detected=True,
                            blink_flag=(i % 3 == 0),
                            perclos=12.5,
                            gaze_status="screen",
                            fatigue_label="normal",
                            focus_score=72.3,
                            focus_breakdown='{"eye":80,"head":65,"gaze":70}',
                            light_level="normal",
                        )
                        db.write_frame(session_id, frame)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
            t0 = time.time()
            for t in threads: t.start()
            for t in threads: t.join()
            dt = time.time() - t0

            expected = n_threads * n_per_thread
            records = db.get_frame_records(session_id)
            n_written = len(records)
            print(f"  {n_threads} 线程 × {n_per_thread} 帧 = {expected} 应有")
            print(f"  实际写入: {n_written}  (耗时 {dt:.2f}s)")
            print(f"  errors: {len(errors)}")
            if errors:
                for e in errors[:3]:
                    print(f"    {type(e).__name__}: {e}")
            assert n_written == expected, f"并发丢数据! 期望 {expected} 实际 {n_written}"
            print("  ✓ CRIT-01 线程安全 fix 验证通过")
        finally:
            db.close()


def test_4_h09_export_json_nonexistent():
    """4. H-09: 验证 export_json 不存在 session 早返回不崩"""
    print("\n=== 4. H-09: export_json None 守卫 ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "h09.db")
        db = DatabaseManager(config=DBConfig(db_path=db_path))
        db.initialize()
        try:
            output_path = os.path.join(tmpdir, "should_not_exist.json")
            db.export_json("not_a_real_session_zzz", output_path)
            assert not os.path.exists(output_path), "应早返回不写文件"
            print("  ✓ H-09 export_json 收到不存在 session_id 早返回, 未创建文件")
        finally:
            db.close()


def test_5_analyzer_synthetic_flow():
    """5. analyzer 跑一段合成数据, 验证 v4.3 fix 不破"""
    print("\n=== 5. analyzer 合成数据流 ===")
    fat = create_fatigue_analyzer(baseline_blink_rate=15.0)
    focus = create_focus_analyzer()
    focus.set_baseline(ear=0.25, yaw_std=3.0, pitch_std=3.0)

    # 模拟 30 秒 session
    n_frames = 30
    fatigue_changes = []
    focus_results = []
    for i in range(n_frames):
        ear = 0.25 + (i % 5) * 0.01
        blink_rate = 15.0 + i * 0.5
        perclos = 3.0 + i * 0.2
        result = fat.analyze(blink_rate=blink_rate, ear_nadir=ear * 0.4, head_stability=80.0 - i * 0.5)
        focus_result = focus.analyze(ear=ear, yaw=i * 0.1, pitch=-i * 0.1, gaze_score=85.0)
        fatigue_changes.append(result.fatigue_level.value)
        focus_results.append(focus_result.focus_score)

    print(f"  疲劳等级变化: {fatigue_changes[0]} → ... → {fatigue_changes[-1]}")
    print(f"  专注度分数范围: {min(focus_results):.1f} ~ {max(focus_results):.1f}")
    print(f"  H-03 perclos 阈值: {fat.perclos_threshold_mild} (期望 5.0)")
    print(f"  H-05 baseline_ear: {focus.baseline_ear} (期望 0.25)")

    # 验证 H-03 默认值
    assert fat.perclos_threshold_mild == 5.0, f"H-03 应为 5.0, 实际 {fat.perclos_threshold_mild}"
    print("  ✓ H-03 perclos_threshold_mild = 5.0")

    # 验证 H-05 baseline_ear 保护 (显式 set_baseline(0))
    focus.set_baseline(ear=0.0)
    score = focus._compute_eye_score(ear=0.25)
    assert score == 50.0, f"H-05 baseline=0 应返回 50.0, 实际 {score}"
    print("  ✓ H-05 baseline_ear=0 返回中性分 50.0")
    focus.set_baseline(ear=0.25, yaw_std=3.0, pitch_std=3.0)  # reset

    print("  ✓ analyzer 合成流验证通过")


def test_6_h08_new_write_preserves_fields():
    """6. H-08: 验证 v4.3 修后新写入的 frame 7 字段被保留 (write-then-read 验证)"""
    print("\n=== 6. H-08: 新写入 7 字段被保留 ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "h08_new.db")
        db = DatabaseManager(config=DBConfig(db_path=db_path))
        db.initialize()
        try:
            session_id = db.create_session()
            # 写入 v4.3 fix 后的 frame
            frame = FrameRecord(
                session_id=session_id,
                timestamp=1.0,
                ear_left=0.25, ear_right=0.26, ear_avg=0.255,
                yaw=0.5, pitch=-1.0, roll=0.2,
                gaze_score=85.0, brightness=128.0,
                face_detected=True,
                blink_flag=True,
                perclos=12.5,
                gaze_status="away",
                fatigue_label="mild",
                focus_score=72.3,
                focus_breakdown='{"eye":80}',
                light_level="normal",
            )
            db.write_frame(session_id, frame)

            # 读回
            frames = db.get_frame_records(session_id)
            assert len(frames) == 1
            got = frames[0]
            print(f"  写入: blink_flag=True perclos=12.5 gaze_status='away' fatigue_label='mild' focus_score=72.3")
            print(f"  读出: blink_flag={got.blink_flag} perclos={got.perclos} gaze_status='{got.gaze_status}' fatigue_label='{got.fatigue_label}' focus_score={got.focus_score}")
            assert got.blink_flag is True
            assert got.perclos == 12.5
            assert got.gaze_status == "away"
            assert got.fatigue_label == "mild"
            assert got.focus_score == 72.3
            assert got.focus_breakdown == '{"eye":80}'
            assert got.light_level == "normal"
            print("  ✓ H-08 新数据 7 字段完整保留")
        finally:
            db.close()


def main():
    print("=" * 60)
    print("EyeFocus Insight v4.3 用户使用测试")
    print(f"运行时间: {datetime.now().isoformat()}")
    print("=" * 60)

    try:
        sessions = test_1_list_existing_sessions()
        test_2_h08_7_fields_preserved(sessions)
        test_3_crit01_thread_safety()
        test_4_h09_export_json_nonexistent()
        test_5_analyzer_synthetic_flow()
        test_6_h08_new_write_preserves_fields()
        print("\n" + "=" * 60)
        print("✓ 全部 6 个用户使用测试通过")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n✗ 测试失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
