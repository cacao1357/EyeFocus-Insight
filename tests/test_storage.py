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
