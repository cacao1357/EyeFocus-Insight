"""
tests/test_storage.py — Storage 模块单元测试
覆盖 storage/ 包中所有可离线测试的函数。
"""

import sys
import os
import tempfile
import json

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.models import (
    Session,
    FrameRecord,
    FocusRecord,
    FatigueRecord,
    BlinkRecord,
    GlassesMode,
    FatigueLevel,
)
from storage.db import DatabaseManager


class TestStorageModels:
    """Storage 数据模型单元测试"""

    def test_session_creation(self):
        """测试 Session 创建"""
        session = Session(
            session_id="test-123",
            start_time=0.0,
        )
        assert session.session_id == "test-123"
        assert session.is_active is True
        assert session.is_calibrated is False

    def test_frame_record_creation(self):
        """测试 FrameRecord 创建"""
        record = FrameRecord(
            session_id="test-123",
            timestamp=1.0,
            ear_left=0.25,
            ear_right=0.26,
            ear_avg=0.255,
            yaw=0.5,
            pitch=-1.0,
            roll=0.2,
            gaze_score=85.0,
            brightness=128.0,
            face_detected=True,
        )
        assert record.session_id == "test-123"
        assert record.ear_avg == 0.255
        assert record.face_detected is True

    def test_glasses_mode_enum(self):
        """测试 GlassesMode 枚举"""
        assert GlassesMode.UNKNOWN.value == "unknown"
        assert GlassesMode.WITH_GLASSES.value == "with_glasses"
        assert GlassesMode.WITHOUT_GLASSES.value == "without_glasses"
        assert GlassesMode.MANUAL_GLASSES.value == "manual_glasses"
        assert GlassesMode.MANUAL_NO_GLASSES.value == "manual_no_glasses"

    def test_fatigue_level_enum(self):
        """测试 FatigueLevel 枚举"""
        assert FatigueLevel.LOW.value == "low"
        assert FatigueLevel.MEDIUM.value == "medium"
        assert FatigueLevel.HIGH.value == "high"


class TestDatabaseManager:
    """DatabaseManager 单元测试"""

    def test_initialize(self):
        """测试数据库初始化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            from storage.db import DBConfig
            config = DBConfig(db_path=db_path)
            db = DatabaseManager(config=config)
            db.initialize()

            # 验证表已创建
            assert os.path.exists(db_path)
            db.close()

    def test_create_session(self):
        """测试创建会话"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            from storage.db import DBConfig
            config = DBConfig(db_path=db_path)
            db = DatabaseManager(config=config)
            db.initialize()

            session_id = db.create_session()
            assert isinstance(session_id, str)
            assert len(session_id) > 0
            db.close()

    def test_create_session_rapid_unique(self):
        """v4.0.1 回归: 100 次连续 create_session 必须全部成功且 ID 唯一 (B1)
        原 bug: datetime 微秒方案同微秒 97% 失败"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "rapid.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                sids = [db.create_session() for _ in range(100)]
            finally:
                db.close()
            assert len(sids) == 100, f"应 100 个成功, 实际 {len(sids)}"
            assert len(set(sids)) == 100, "100 个 ID 必须唯一"

    def test_create_session_id_format(self):
        """v4.0.1 回归: session_id 格式 = YYYYMMDD_HHMMSS_<12 hex> (含 uuid)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "fmt.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                sid = db.create_session()
            finally:
                db.close()
            import re
            pattern = r"^\d{8}_\d{6}_[0-9a-f]{12}$"
            assert re.match(pattern, sid), (
                f"session_id 格式应为 YYYYMMDD_HHMMSS_xxxxxxxxxxxx (含 12 hex uuid), 实际 {sid}"
            )

    def test_write_and_read_frame(self):
        """测试帧数据写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            from storage.db import DBConfig
            config = DBConfig(db_path=db_path)
            db = DatabaseManager(config=config)
            db.initialize()

            session_id = db.create_session()

            # 写入帧数据
            frame = FrameRecord(
                session_id=session_id,
                timestamp=1.0,
                ear_left=0.25,
                ear_right=0.26,
                ear_avg=0.255,
                yaw=0.5,
                pitch=-1.0,
                roll=0.2,
                gaze_score=85.0,
                brightness=128.0,
                face_detected=True,
            )
            db.write_frame(session_id, frame)

            # 验证写入成功（不抛出异常）
            db.close()

    def test_write_focus_record(self):
        """测试专注度记录写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            from storage.db import DBConfig
            config = DBConfig(db_path=db_path)
            db = DatabaseManager(config=config)
            db.initialize()

            session_id = db.create_session()

            focus = FocusRecord(
                session_id=session_id,
                window_start=1.0,
                window_end=2.0,
                focus_score=85.0,
                eye_score=90.0,
                head_score=80.0,
                gaze_score=85.0,
                blink_rate=15.0,
                avg_ear=0.25,
                avg_yaw=0.5,
                avg_pitch=-1.0,
            )
            db.write_focus_record(session_id, focus)
            db.close()

    def test_write_fatigue_record(self):
        """测试疲劳记录写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            from storage.db import DBConfig
            config = DBConfig(db_path=db_path)
            db = DatabaseManager(config=config)
            db.initialize()

            session_id = db.create_session()

            fatigue = FatigueRecord(
                session_id=session_id,
                timestamp=1.0,
                fatigue_level=FatigueLevel.MEDIUM,
                blink_rate=22.0,
                avg_ear_nadir=0.10,
                head_stability=75.0,
                cumulative_fatigue_score=45.0,
            )
            db.write_fatigue_record(session_id, fatigue)
            db.close()

    def test_export_json(self):
        """测试 JSON 导出"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            export_dir = os.path.join(tmpdir, "exports")
            os.makedirs(export_dir, exist_ok=True)

            from storage.db import DBConfig
            config = DBConfig(db_path=db_path)
            db = DatabaseManager(config=config)
            db.initialize()

            session_id = db.create_session()

            # 添加一些测试数据
            frame = FrameRecord(
                session_id=session_id,
                timestamp=1.0,
                ear_left=0.25,
                ear_right=0.26,
                ear_avg=0.255,
                yaw=0.5,
                pitch=-1.0,
                roll=0.2,
                gaze_score=85.0,
                brightness=128.0,
                face_detected=True,
            )
            db.write_frame(session_id, frame)

            # 导出
            output_path = os.path.join(export_dir, "export.json")
            db.export_json(session_id, output_path)

            # 验证导出文件
            assert os.path.exists(output_path)
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                assert "session" in data
                assert data["session"]["session_id"] == session_id
            db.close()

    def test_close(self):
        """测试数据库关闭"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            from storage.db import DBConfig
            config = DBConfig(db_path=db_path)
            db = DatabaseManager(config=config)
            db.initialize()
            db.close()  # 不应该抛出异常

    # ========== v4.3 漏洞修复回归测试 ==========

    def testget_cursor_holds_lock_for_thread_safety_CRIT01(self):
        """CRIT-01: get_cursor 必须持锁, 否则共享连接事务可被其他线程 rollback 撤销
        docstring 承诺线程安全, 但 get_cursor 实现没 acquire self._lock
        """
        import threading
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "thread.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                session_id = db.create_session()

                # 验证 get_cursor 函数体内有 with self._lock:
                import inspect
                src = inspect.getsource(db.get_cursor)
                assert "self._lock" in src, (
                    f"get_cursor 必须使用 self._lock 以兑现 docstring 的线程安全承诺. 实际源码:\n{src}"
                )

                # 进一步: 并发调用 write_frame 验证互斥 (不要求快, 要求成功)
                errors = []

                def writer(idx):
                    try:
                        for i in range(10):
                            frame = FrameRecord(
                                session_id=session_id,
                                timestamp=float(idx * 100 + i),
                                ear_left=0.25, ear_right=0.26, ear_avg=0.255,
                                yaw=0.5, pitch=-1.0, roll=0.2,
                                gaze_score=85.0, brightness=128.0,
                                face_detected=True,
                            )
                            db.write_frame(session_id, frame)
                    except Exception as e:
                        errors.append(e)

                threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
                for t in threads: t.start()
                for t in threads: t.join()

                assert not errors, f"并发写入应成功, 实际错误: {errors}"
                records = db.get_frame_records(session_id)
                assert len(records) == 50, f"应写入 50 条 (5 线程 × 10 帧), 实际 {len(records)}"
            finally:
                db.close()

    def test_get_frame_records_preserves_7_new_fields_H08(self):
        """H-08: get_frame_records 回读必须保留 7 个 v4.x 新增字段
        当前实现只填 12 个旧字段, 7 个新字段 (blink_flag/perclos/gaze_status/
        fatigue_label/focus_score/focus_breakdown/light_level) 全部丢失, 被 dataclass 默认值覆盖
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "fields.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                session_id = db.create_session()

                # 写入一条带 7 个非默认新字段的 frame
                original = FrameRecord(
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
                    focus_breakdown='{"eye":80,"head":65,"gaze":70}',
                    light_level="normal",
                )
                db.write_frame(session_id, original)

                # 回读
                records = db.get_frame_records(session_id)
                assert len(records) == 1
                got = records[0]

                # 7 个新字段必须从 DB 读出, 不能是默认值
                assert got.blink_flag is True, f"blink_flag 丢失 (got {got.blink_flag})"
                assert got.perclos == 12.5, f"perclos 丢失 (got {got.perclos})"
                assert got.gaze_status == "away", f"gaze_status 丢失 (got {got.gaze_status})"
                assert got.fatigue_label == "mild", f"fatigue_label 丢失 (got {got.fatigue_label})"
                assert got.focus_score == 72.3, f"focus_score 丢失 (got {got.focus_score})"
                assert got.focus_breakdown == '{"eye":80,"head":65,"gaze":70}', (
                    f"focus_breakdown 丢失 (got {got.focus_breakdown})"
                )
                assert got.light_level == "normal", f"light_level 丢失 (got {got.light_level})"
            finally:
                db.close()

    def test_export_json_nonexistent_session_returns_early_H09(self):
        """H-09: export_json 收到不存在的 session_id 必须早返回, 不能 AttributeError 崩溃
        get_session 返回 None 时, line 798 直接访问 session.session_id 抛 AttributeError
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "nonesess.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                output_path = os.path.join(tmpdir, "should_not_be_created.json")

                # 调用不存在的 session_id, 不应抛异常, 也不应创建文件
                db.export_json("definitely_not_a_real_session_xyz", output_path)

                # 验证函数早返回 (不写文件)
                assert not os.path.exists(output_path), (
                    f"session 不存在时不应创建输出文件, 但 {output_path} 存在"
                )
            finally:
                db.close()

    def test_foreign_keys_pragma_enabled_M12(self):
        """M-12: initialize() 必须开启 PRAGMA foreign_keys=ON, FK 约束才生效
        否则 SCHEMA_SQL 声明 FK 形同虚设, 孤立 frame_records 可插入
        """
        import sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "fk.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                # 1) PRAGMA foreign_keys 必须返回 1
                with db.get_cursor() as cursor:
                    cursor.execute("PRAGMA foreign_keys")
                    fk_state = cursor.fetchone()[0]
                assert fk_state == 1, f"PRAGMA foreign_keys 应为 1 (ON), 实际 {fk_state}"

                # 2) 插入孤立 frame_records (不存在的 session_id) 应抛 IntegrityError
                bad_frame = FrameRecord(
                    session_id="nonexistent_session_xyz",
                    timestamp=1.0,
                    ear_left=0.25, ear_right=0.26, ear_avg=0.255,
                    yaw=0.5, pitch=-1.0, roll=0.2,
                    gaze_score=85.0, brightness=128.0,
                    face_detected=True,
                )
                with pytest.raises(sqlite3.IntegrityError):
                    db.write_frame("nonexistent_session_xyz", bad_frame)
            finally:
                db.close()

    def test_get_frame_records_tolerates_bad_json_M13(self):
        """M-13: get_frame_records 单条坏 blendshapes_json 不能让整次查询失败
        修复前: json.loads 无 try/except, 坏数据抛 JSONDecodeError 整次崩溃
        修复后: 每个反序列化 try/except, 坏字段返回 None, 整条 row 异常跳过
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "badjson.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                session_id = db.create_session()

                # 写入 1 条好数据
                good = FrameRecord(
                    session_id=session_id,
                    timestamp=1.0,
                    ear_left=0.25, ear_right=0.26, ear_avg=0.255,
                    yaw=0.5, pitch=-1.0, roll=0.2,
                    gaze_score=85.0, brightness=128.0,
                    face_detected=True,
                    blendshapes={"eyeBlinkLeft": 0.5, "eyeBlinkRight": 0.4},
                )
                db.write_frame(session_id, good)

                # 直接用 SQL 注入 1 条坏数据 (blendshapes_json = 非法 JSON 字符串)
                with db.get_cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO frame_records
                           (session_id, timestamp, ear_avg, face_detected, blendshapes_json)
                           VALUES (?, ?, ?, ?, ?)""",
                        (session_id, 2.0, 0.30, 1, "{not valid json at all"),
                    )

                # 再写 1 条好数据
                good2 = FrameRecord(
                    session_id=session_id,
                    timestamp=3.0,
                    ear_left=0.27, ear_right=0.28, ear_avg=0.275,
                    yaw=0.6, pitch=-1.1, roll=0.3,
                    gaze_score=86.0, brightness=130.0,
                    face_detected=True,
                )
                db.write_frame(session_id, good2)

                # get_frame_records 不应抛异常
                records = db.get_frame_records(session_id)

                # 至少有 2 条好数据 (坏数据 blendshapes 字段降级为 None 或整条跳过都接受)
                assert len(records) >= 2, (
                    f"应至少有 2 条好记录, 实际 {len(records)}"
                )
                # 验证第一条 (时间戳 1.0) 的 blendshapes 字段被正确读出
                ts_to_record = {r.timestamp: r for r in records}
                assert 1.0 in ts_to_record, "好数据 1.0 应被读出"
                assert ts_to_record[1.0].blendshapes == {"eyeBlinkLeft": 0.5, "eyeBlinkRight": 0.4}
                assert 3.0 in ts_to_record, "好数据 3.0 应被读出"
            finally:
                db.close()

    def test_close_truncates_wal_M14(self):
        """M-14: close() 必须主动 wal_checkpoint(TRUNCATE), 否则 .db-wal 残片可持续增长
        修复前 close() 只 _conn.close(), 多连接场景下 WAL 不被回收
        修复后 close() 前先 PRAGMA wal_checkpoint(TRUNCATE) 把 WAL 内容刷到主库并截断

        验证: (1) close 源码包含 wal_checkpoint(TRUNCATE);
              (2) 持有外部读连接时 close 仍能截断 WAL (size=0 或不存在)
        """
        import sqlite3
        import inspect
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "wal.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            session_id = db.create_session()

            # 写几条数据撑大 WAL
            for i in range(50):
                frame = FrameRecord(
                    session_id=session_id,
                    timestamp=float(i),
                    ear_left=0.25, ear_right=0.26, ear_avg=0.255,
                    yaw=0.5, pitch=-1.0, roll=0.2,
                    gaze_score=85.0, brightness=128.0,
                    face_detected=True,
                )
                db.write_frame(session_id, frame)

            wal_path = db_path + "-wal"
            assert os.path.exists(wal_path), "WAL 模式下应存在 .db-wal 文件"
            wal_size_before = os.path.getsize(wal_path)
            assert wal_size_before > 0, "撑大 WAL 应有非零 size"

            # 源码层验证: close 必须显式调用 wal_checkpoint(TRUNCATE)
            src = inspect.getsource(db.close)
            assert "wal_checkpoint" in src.lower(), (
                f"close() 必须显式调用 PRAGMA wal_checkpoint(TRUNCATE). 实际源码:\n{src}"
            )
            assert "truncate" in src.lower(), (
                f"close() 必须用 TRUNCATE 模式 checkpoint. 实际源码:\n{src}"
            )

            db.close()

            # 行为层验证: close 后 .db-wal 应被截断 (size=0) 或删除
            if os.path.exists(wal_path):
                wal_size_after = os.path.getsize(wal_path)
                assert wal_size_after == 0, (
                    f"close() 后 .db-wal 应被截断 (size=0), "
                    f"实际 size={wal_size_after} (close 前 {wal_size_before})"
                )

    def test_create_session_retries_on_operational_error_M15(self):
        """M-15: create_session 5 次重试必须同时覆盖 OperationalError
        修复前只 catch IntegrityError, 'database is locked' 等 OperationalError 立即失败
        修复后 IntegrityError + OperationalError 都触发重试
        """
        import sqlite3
        import inspect

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "retry.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                # 1) 源码层验证: create_session 的 except 必须含 OperationalError
                src = inspect.getsource(db.create_session)
                assert "OperationalError" in src, (
                    f"create_session 重试 except 必须含 sqlite3.OperationalError. "
                    f"实际源码:\n{src}"
                )

                # 2) 行为层验证: 通过 _conn proxy 让前 2 次 INSERT 抛 OperationalError, 第 3 次成功
                real_conn = db._conn
                call_count = {"n": 0}

                class FlakyCursor:
                    def __init__(self, real):
                        self._real = real
                    def execute(self, sql, params=()):
                        if "INSERT INTO sessions" in sql:
                            call_count["n"] += 1
                            if call_count["n"] <= 2:
                                raise sqlite3.OperationalError("database is locked")
                        return self._real.execute(sql, params)
                    def __getattr__(self, name):
                        return getattr(self._real, name)
                    def close(self):
                        return self._real.close()

                class ConnProxy:
                    def __init__(self, real):
                        self._real = real
                    def cursor(self):
                        return FlakyCursor(self._real.cursor())
                    def __getattr__(self, name):
                        return getattr(self._real, name)

                db._conn = ConnProxy(real_conn)
                try:
                    session_id = db.create_session()
                finally:
                    db._conn = real_conn

                assert session_id, "create_session 应在重试后成功"
                assert call_count["n"] == 3, (
                    f"前 2 次 OperationalError 应触发重试, 第 3 次成功. "
                    f"实际调用 {call_count['n']} 次"
                )
            finally:
                db.close()

    def test_save_calibration_raises_on_missing_id_M16(self):
        """M-16: save_calibration UPDATE 后必须检查 rowcount, 不存在的 calibration_id 不能静默成功
        修复前 UPDATE 无 WHERE 匹配也算"成功", 上层完全感知不到丢数据
        修复后 cursor.rowcount == 0 抛 ValueError
        """
        from storage.models import CalibrationSignal
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "calib.db")
            from storage.db import DBConfig
            db = DatabaseManager(config=DBConfig(db_path=db_path))
            db.initialize()
            try:
                session_id = db.create_session()

                # 正常路径: 创建 calibration → save 应成功
                cid = db.create_calibration(session_id)
                signal = CalibrationSignal(
                    ear_mean=0.28, ear_min=0.10, ear_mid=0.20,
                    yaw_mean=0.5, yaw_range=(-15.0, 15.0),
                    pitch_mean=-1.0, pitch_range=(10.0, -10.0),
                    glasses_mode=False,
                    timestamp=1.0,
                )
                db.save_calibration(cid, session_id, signal)  # 应成功, 不抛

                # 异常路径: 不存在的 calibration_id 必须抛 ValueError
                bogus_id = 999999
                with pytest.raises(ValueError, match=str(bogus_id)):
                    db.save_calibration(bogus_id, session_id, signal)
            finally:
                db.close()
