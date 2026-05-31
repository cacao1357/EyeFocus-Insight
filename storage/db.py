"""
storage/db.py — SQLite 数据库层

提供 DatabaseManager 类，管理 SQLite 数据库连接和操作：
- 会话数据写入
- 历史数据查询
- 数据聚合统计
- 数据导出（JSON/CSV）

数据库 Schema:
- sessions: 会话表
- frame_records: 帧记录表
- focus_records: 专注度记录表
- fatigue_records: 疲劳记录表
- blink_events: 眨眼事件表
"""

import csv
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from storage.models import (
    BlinkRecord,
    FatigueLevel,
    FatigueRecord,
    FocusRecord,
    FrameRecord,
    GlassesMode,
    Session,
)

logger = logging.getLogger("eyefocus.storage")


# 默认数据库路径
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "eyefocus.db"
)


# 数据库 Schema
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    baseline_ear REAL,
    baseline_yaw_std REAL,
    baseline_pitch_std REAL,
    cqs_score REAL,
    glasses_mode TEXT DEFAULT 'unknown',
    is_calibrated INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS frame_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    ear_left REAL,
    ear_right REAL,
    ear_avg REAL,
    yaw REAL,
    pitch REAL,
    roll REAL,
    gaze_score REAL,
    brightness REAL,
    face_detected INTEGER,
    blendshapes_json TEXT,
    blink_flag INTEGER DEFAULT 0,
    perclos REAL,
    gaze_status TEXT,
    fatigue_label TEXT,
    focus_score REAL,
    focus_breakdown TEXT,
    light_level TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS focus_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    window_start REAL NOT NULL,
    window_end REAL NOT NULL,
    focus_score REAL NOT NULL,
    eye_score REAL,
    head_score REAL,
    gaze_score REAL,
    blink_rate REAL,
    avg_ear REAL,
    avg_yaw REAL,
    avg_pitch REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS fatigue_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    fatigue_level TEXT NOT NULL,
    blink_rate REAL,
    avg_ear_nadir REAL,
    head_stability REAL,
    cumulative_fatigue_score REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS blink_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    start_timestamp REAL NOT NULL,
    end_timestamp REAL NOT NULL,
    duration_seconds REAL,
    ear_nadir REAL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS calibration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp REAL,
    ear_mean REAL,
    ear_min REAL,
    ear_mid REAL,
    yaw_mean REAL,
    yaw_left_max REAL,
    yaw_right_max REAL,
    pitch_mean REAL,
    pitch_up_max REAL,
    pitch_down_max REAL,
    glasses_mode INTEGER,
    is_accepted INTEGER,
    notes TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS blink_calibration_round (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calibration_id INTEGER,
    round_index INTEGER,
    duration_seconds INTEGER,
    user_blink_count INTEGER,
    program_blink_count INTEGER,
    program_squint_count INTEGER,
    error_rate REAL,
    adjustment_factor REAL,
    FOREIGN KEY (calibration_id) REFERENCES calibration(id)
);

CREATE INDEX IF NOT EXISTS idx_frame_records_session
ON frame_records(session_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_focus_records_session
ON focus_records(session_id, window_start);

CREATE INDEX IF NOT EXISTS idx_fatigue_records_session
ON fatigue_records(session_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_blink_events_session
ON blink_events(session_id, start_timestamp);
"""


@dataclass
class DBConfig:
    """数据库配置"""
    db_path: str = DEFAULT_DB_PATH
    journal_mode: str = "WAL"  # Write-Ahead Logging
    synchronous: str = "NORMAL"
    cache_size: int = 2000


class DatabaseManager:
    """SQLite 数据库管理器

    线程安全，支持多线程访问。

    使用方法：
        db = DatabaseManager()
        db.initialize()

        session_id = db.create_session()
        db.write_frame(session_id, frame_data)

        records = db.get_focus_records(session_id)
        db.export_json(session_id, "export.json")
    """

    def __init__(self, config: Optional[DBConfig] = None):
        self.config = config or DBConfig()
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self) -> None:
        """初始化数据库连接和表结构"""
        with self._lock:
            if self._initialized:
                return

            # 确保目录存在
            db_dir = os.path.dirname(self.config.db_path)
            if db_dir:
                Path(db_dir).mkdir(parents=True, exist_ok=True)

            # 创建连接
            self._conn = sqlite3.connect(
                self.config.db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.row_factory = sqlite3.Row

            # 设置 PRAGMA
            self._conn.execute(f"PRAGMA journal_mode={self.config.journal_mode}")
            self._conn.execute(f"PRAGMA synchronous={self.config.synchronous}")
            self._conn.execute(f"PRAGMA cache_size={self.config.cache_size}")

            # 创建表
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()

            self._initialized = True
            logger.info("数据库初始化完成: %s", self.config.db_path)

    def close(self) -> None:
        """关闭数据库连接"""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                self._initialized = False
                logger.info("数据库连接已关闭")

    @contextmanager
    def _get_cursor(self):
        """获取数据库游标的上下文管理器"""
        if not self._initialized:
            self.initialize()

        cursor = self._conn.cursor()
        try:
            yield cursor
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cursor.close()

    # ========== Session 操作 ==========

    def create_session(self) -> str:
        """创建新会话

        Returns:
            session_id 字符串
        """
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sessions (session_id, start_time, is_active)
                VALUES (?, ?, 1)
                """,
                (session_id, datetime.now().isoformat()),
            )

        logger.info("创建会话: %s", session_id)
        return session_id

    def update_session(
        self,
        session_id: str,
        end_time: Optional[datetime] = None,
        baseline_ear: Optional[float] = None,
        baseline_yaw_std: Optional[float] = None,
        baseline_pitch_std: Optional[float] = None,
        cqs_score: Optional[float] = None,
        glasses_mode: Optional[GlassesMode] = None,
        is_calibrated: Optional[bool] = None,
        is_active: Optional[bool] = None,
    ) -> None:
        """更新会话信息"""
        updates = []
        params = []

        if end_time is not None:
            updates.append("end_time = ?")
            params.append(end_time.isoformat())
        if baseline_ear is not None:
            updates.append("baseline_ear = ?")
            params.append(baseline_ear)
        if baseline_yaw_std is not None:
            updates.append("baseline_yaw_std = ?")
            params.append(baseline_yaw_std)
        if baseline_pitch_std is not None:
            updates.append("baseline_pitch_std = ?")
            params.append(baseline_pitch_std)
        if cqs_score is not None:
            updates.append("cqs_score = ?")
            params.append(cqs_score)
        if glasses_mode is not None:
            updates.append("glasses_mode = ?")
            params.append(glasses_mode.value)
        if is_calibrated is not None:
            updates.append("is_calibrated = ?")
            params.append(1 if is_calibrated else 0)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)

        if not updates:
            return

        params.append(session_id)

        with self._get_cursor() as cursor:
            cursor.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = ?",
                params,
            )

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话信息"""
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return Session(
            session_id=row["session_id"],
            start_time=datetime.fromisoformat(row["start_time"]),
            end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
            baseline_ear=row["baseline_ear"],
            baseline_yaw_std=row["baseline_yaw_std"],
            baseline_pitch_std=row["baseline_pitch_std"],
            cqs_score=row["cqs_score"],
            glasses_mode=GlassesMode(row["glasses_mode"]),
            is_calibrated=bool(row["is_calibrated"]),
            is_active=bool(row["is_active"]),
        )

    def list_sessions(self, active_only: bool = False) -> List[Session]:
        """列出所有会话"""
        query = "SELECT * FROM sessions"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY start_time DESC"

        with self._get_cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        return [
            Session(
                session_id=row["session_id"],
                start_time=datetime.fromisoformat(row["start_time"]),
                end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
                baseline_ear=row["baseline_ear"],
                baseline_yaw_std=row["baseline_yaw_std"],
                baseline_pitch_std=row["baseline_pitch_std"],
                cqs_score=row["cqs_score"],
                glasses_mode=GlassesMode(row["glasses_mode"]),
                is_calibrated=bool(row["is_calibrated"]),
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    # ========== Frame Records ==========

    def write_frame(self, session_id: str, frame: FrameRecord) -> None:
        """写入单帧记录"""
        blendshapes_json = None
        if frame.blendshapes:
            blendshapes_json = json.dumps(frame.blendshapes)

        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO frame_records
                (session_id, timestamp, ear_left, ear_right, ear_avg,
                 yaw, pitch, roll, gaze_score, brightness, face_detected, blendshapes_json,
                 blink_flag, perclos, gaze_status, fatigue_label, focus_score, focus_breakdown, light_level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    frame.timestamp,
                    frame.ear_left,
                    frame.ear_right,
                    frame.ear_avg,
                    frame.yaw,
                    frame.pitch,
                    frame.roll,
                    frame.gaze_score,
                    frame.brightness,
                    1 if frame.face_detected else 0,
                    blendshapes_json,
                    1 if frame.blink_flag else 0,
                    frame.perclos,
                    frame.gaze_status,
                    frame.fatigue_label,
                    frame.focus_score,
                    frame.focus_breakdown,
                    frame.light_level,
                ),
            )

    def get_frame_records(
        self,
        session_id: str,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[FrameRecord]:
        """获取帧记录"""
        query = "SELECT * FROM frame_records WHERE session_id = ?"
        params: List[Any] = [session_id]

        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        if until is not None:
            query += " AND timestamp <= ?"
            params.append(until)

        query += " ORDER BY timestamp"

        with self._get_cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

        records = []
        for row in rows:
            blendshapes = None
            if row["blendshapes_json"]:
                blendshapes = json.loads(row["blendshapes_json"])

            records.append(FrameRecord(
                session_id=row["session_id"],
                timestamp=row["timestamp"],
                ear_left=row["ear_left"],
                ear_right=row["ear_right"],
                ear_avg=row["ear_avg"],
                yaw=row["yaw"],
                pitch=row["pitch"],
                roll=row["roll"],
                gaze_score=row["gaze_score"],
                brightness=row["brightness"],
                face_detected=bool(row["face_detected"]),
                blendshapes=blendshapes,
            ))

        return records

    # ========== Focus Records ==========

    def write_focus_record(self, session_id: str, record: FocusRecord) -> None:
        """写入专注度记录"""
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO focus_records
                (session_id, window_start, window_end, focus_score,
                 eye_score, head_score, gaze_score, blink_rate, avg_ear, avg_yaw, avg_pitch)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    record.window_start,
                    record.window_end,
                    record.focus_score,
                    record.eye_score,
                    record.head_score,
                    record.gaze_score,
                    record.blink_rate,
                    record.avg_ear,
                    record.avg_yaw,
                    record.avg_pitch,
                ),
            )

    def get_focus_records(self, session_id: str) -> List[FocusRecord]:
        """获取专注度记录"""
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM focus_records WHERE session_id = ? ORDER BY window_start",
                (session_id,),
            )
            rows = cursor.fetchall()

        return [
            FocusRecord(
                session_id=row["session_id"],
                window_start=row["window_start"],
                window_end=row["window_end"],
                focus_score=row["focus_score"],
                eye_score=row["eye_score"],
                head_score=row["head_score"],
                gaze_score=row["gaze_score"],
                blink_rate=row["blink_rate"],
                avg_ear=row["avg_ear"],
                avg_yaw=row["avg_yaw"],
                avg_pitch=row["avg_pitch"],
            )
            for row in rows
        ]

    # ========== Fatigue Records ==========

    def write_fatigue_record(self, session_id: str, record: FatigueRecord) -> None:
        """写入疲劳记录"""
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO fatigue_records
                (session_id, timestamp, fatigue_level, blink_rate,
                 avg_ear_nadir, head_stability, cumulative_fatigue_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    record.timestamp,
                    record.fatigue_level.value,
                    record.blink_rate,
                    record.avg_ear_nadir,
                    record.head_stability,
                    record.cumulative_fatigue_score,
                ),
            )

    def get_fatigue_records(self, session_id: str) -> List[FatigueRecord]:
        """获取疲劳记录"""
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM fatigue_records WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            )
            rows = cursor.fetchall()

        return [
            FatigueRecord(
                session_id=row["session_id"],
                timestamp=row["timestamp"],
                fatigue_level=FatigueLevel(row["fatigue_level"]),
                blink_rate=row["blink_rate"],
                avg_ear_nadir=row["avg_ear_nadir"],
                head_stability=row["head_stability"],
                cumulative_fatigue_score=row["cumulative_fatigue_score"],
            )
            for row in rows
        ]

    # ========== Blink Events ==========

    def write_blink_event(self, session_id: str, event: BlinkRecord) -> None:
        """写入眨眼事件"""
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO blink_events
                (session_id, start_timestamp, end_timestamp, duration_seconds, ear_nadir)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    event.start_timestamp,
                    event.end_timestamp,
                    event.duration_seconds,
                    event.ear_nadir,
                ),
            )

    def get_blink_events(self, session_id: str) -> List[BlinkRecord]:
        """获取眨眼事件"""
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM blink_events WHERE session_id = ? ORDER BY start_timestamp",
                (session_id,),
            )
            rows = cursor.fetchall()

        return [
            BlinkRecord(
                session_id=row["session_id"],
                start_timestamp=row["start_timestamp"],
                end_timestamp=row["end_timestamp"],
                duration_seconds=row["duration_seconds"],
                ear_nadir=row["ear_nadir"],
            )
            for row in rows
        ]

    # ========== Calibration Records ==========

    def save_calibration(self, calibration_id: int, session_id: str,
                          signal: 'CalibrationSignal',
                          is_accepted: bool = True,
                          notes: str = "") -> None:
        """保存校准信号数据"""
        yaw_left, yaw_right = signal.yaw_range if signal.yaw_range else (0.0, 0.0)
        pitch_up, pitch_down = signal.pitch_range if signal.pitch_range else (0.0, 0.0)

        with self._get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE calibration SET
                    timestamp = ?,
                    ear_mean = ?,
                    ear_min = ?,
                    ear_mid = ?,
                    yaw_mean = ?,
                    yaw_left_max = ?,
                    yaw_right_max = ?,
                    pitch_mean = ?,
                    pitch_up_max = ?,
                    pitch_down_max = ?,
                    glasses_mode = ?,
                    is_accepted = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    signal.timestamp,
                    signal.ear_mean,
                    signal.ear_min,
                    signal.ear_mid,
                    signal.yaw_mean,
                    yaw_left,
                    yaw_right,
                    signal.pitch_mean,
                    pitch_up,
                    pitch_down,
                    1 if signal.glasses_mode else 0,
                    1 if is_accepted else 0,
                    notes,
                    calibration_id,
                ),
            )


    def save_blink_calibration_round(self, calibration_id: int,
                                      round_data: 'BlinkCalibrationRound') -> None:
        """保存单轮眨眼校准数据"""
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO blink_calibration_round
                (calibration_id, round_index, duration_seconds,
                 user_blink_count, program_blink_count, program_squint_count,
                 error_rate, adjustment_factor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    calibration_id,
                    round_data.round_index,
                    round_data.duration_seconds,
                    round_data.user_blink_count,
                    round_data.program_blink_count,
                    round_data.program_squint_count,
                    round_data.error_rate,
                    round_data.adjustment_factor,
                ),
            )


    def create_calibration(self, session_id: str) -> int:
        """创建校准记录"""
        with self._get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO calibration (session_id, timestamp)
                VALUES (?, ?)
                """,
                (session_id, time.time()),
            )
            return cursor.lastrowid

    # ========== 数据聚合统计 ==========

    def get_session_statistics(self, session_id: str) -> Dict[str, Any]:
        """获取会话统计信息"""
        stats = {}

        with self._get_cursor() as cursor:
            # 帧记录统计
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_frames,
                    COUNT(DISTINCT face_detected) as face_detect_variety,
                    AVG(ear_avg) as avg_ear,
                    MIN(ear_avg) as min_ear,
                    MAX(ear_avg) as max_ear,
                    AVG(yaw) as avg_yaw,
                    AVG(pitch) as avg_pitch,
                    AVG(brightness) as avg_brightness
                FROM frame_records
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            stats["frames"] = dict(row) if row else {}

            # 专注度统计
            cursor.execute(
                """
                SELECT
                    AVG(focus_score) as avg_focus,
                    MIN(focus_score) as min_focus,
                    MAX(focus_score) as max_focus,
                    AVG(blink_rate) as avg_blink_rate
                FROM focus_records
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            stats["focus"] = dict(row) if row else {}

            # 眨眼统计
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_blinks,
                    AVG(duration_seconds) as avg_blink_duration,
                    AVG(ear_nadir) as avg_ear_nadir
                FROM blink_events
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            stats["blinks"] = dict(row) if row else {}

        return stats

    # ========== 数据导出 ==========

    def export_json(self, session_id: str, output_path: str) -> None:
        """导出会话数据为 JSON"""
        session = self.get_session(session_id)
        frames = self.get_frame_records(session_id)
        focus_records = self.get_focus_records(session_id)
        fatigue_records = self.get_fatigue_records(session_id)
        blink_events = self.get_blink_events(session_id)

        data = {
            "session": {
                "session_id": session.session_id,
                "start_time": session.start_time.isoformat() if session else None,
                "end_time": session.end_time.isoformat() if session and session.end_time else None,
                "baseline_ear": session.baseline_ear if session else None,
                "cqs_score": session.cqs_score if session else None,
                "glasses_mode": session.glasses_mode.value if session else None,
                "is_calibrated": session.is_calibrated if session else None,
            },
            "frame_records": [
                {
                    "timestamp": f.timestamp,
                    "ear_left": f.ear_left,
                    "ear_right": f.ear_right,
                    "ear_avg": f.ear_avg,
                    "yaw": f.yaw,
                    "pitch": f.pitch,
                    "roll": f.roll,
                    "gaze_score": f.gaze_score,
                    "brightness": f.brightness,
                    "face_detected": f.face_detected,
                }
                for f in frames
            ],
            "focus_records": [
                {
                    "window_start": r.window_start,
                    "window_end": r.window_end,
                    "focus_score": r.focus_score,
                    "eye_score": r.eye_score,
                    "head_score": r.head_score,
                    "gaze_score": r.gaze_score,
                    "blink_rate": r.blink_rate,
                }
                for r in focus_records
            ],
            "fatigue_records": [
                {
                    "timestamp": r.timestamp,
                    "fatigue_level": r.fatigue_level.value,
                    "blink_rate": r.blink_rate,
                    "cumulative_fatigue_score": r.cumulative_fatigue_score,
                }
                for r in fatigue_records
            ],
            "blink_events": [
                {
                    "start_timestamp": e.start_timestamp,
                    "end_timestamp": e.end_timestamp,
                    "duration_seconds": e.duration_seconds,
                    "ear_nadir": e.ear_nadir,
                }
                for e in blink_events
            ],
            "statistics": self.get_session_statistics(session_id),
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("导出 JSON 完成: %s", output_path)

    def export_csv(self, session_id: str, output_dir: str) -> None:
        """导出会话数据为 CSV（多个文件）"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 导出帧记录
        frames = self.get_frame_records(session_id)
        if frames:
            with open(
                os.path.join(output_dir, f"{session_id}_frames.csv"),
                "w",
                newline="",
                encoding="utf-8",
            ) as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "ear_left", "ear_right", "ear_avg",
                    "yaw", "pitch", "roll", "gaze_score", "brightness", "face_detected"
                ])
                for frame in frames:
                    writer.writerow([
                        frame.timestamp, frame.ear_left, frame.ear_right, frame.ear_avg,
                        frame.yaw, frame.pitch, frame.roll, frame.gaze_score,
                        frame.brightness, frame.face_detected
                    ])

        # 导出专注度记录
        focus_records = self.get_focus_records(session_id)
        if focus_records:
            with open(
                os.path.join(output_dir, f"{session_id}_focus.csv"),
                "w",
                newline="",
                encoding="utf-8",
            ) as f:
                writer = csv.writer(f)
                writer.writerow([
                    "window_start", "window_end", "focus_score",
                    "eye_score", "head_score", "gaze_score", "blink_rate"
                ])
                for record in focus_records:
                    writer.writerow([
                        record.window_start, record.window_end, record.focus_score,
                        record.eye_score, record.head_score, record.gaze_score, record.blink_rate
                    ])

        logger.info("导出 CSV 完成: %s", output_dir)

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_database_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """工厂函数：创建数据库管理器"""
    config = DBConfig(db_path=db_path or DEFAULT_DB_PATH)
    return DatabaseManager(config)
