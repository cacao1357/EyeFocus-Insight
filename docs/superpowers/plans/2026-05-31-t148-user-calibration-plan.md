# T148 用户校准系统实现计划

> ⚠️ **【状态：已被 v4.2 取代，未实施】**
> 此 T148 计划（2026-05-31）实测全部失效，**未落地**。被 2026-06-02 重设计 spec 取代：`docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`，v4.2 校准模块 `calibration/` 已完成 14 子任务（T-CAL-01~T-CAL-14）并集成进 main.py（真机 CQS=1.00）。**新读者请直接阅读 v4.2 文档。**
>
> 本文件作为失败教训保留：警示"模块耦合 main.py → 实测失效"的失败链。归档于 `docs/old_schemes/T148_USER_CALIBRATION_DESIGN_v1.0.md` 已有设计稿。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 T148 用户辅助多轮校准系统，包括 6 阶段校准流程（自动基线采集、闭眼、睁眼恢复、眯眼、头部姿态、眨眼计数）。

**Architecture:** 事件驱动型架构。`UserCalibrationManager` 内部状态机通过回调接口与 `main.py` 通信，`main.py` 实现回调并调用 `overlay.py` 更新 UI。

**Tech Stack:** Python 3.12, MediaPipe FaceLandmarker, OpenCV, SQLite

---

## 文件结构

```
analyzer/user_calibration.py   # 新增：UserCalibrationManager + CalibrationCallbacks
storage/models.py              # 修改：新增 CalibrationSignal, BlinkCalibrationRound, CalibrationResult
storage/db.py                  # 修改：新增 calibration + blink_calibration_round 表
gui/overlay.py                 # 修改：新增校准 UI 方法
main.py                        # 修改：集成 UserCalibrationManager
tests/test_user_calibration.py # 新增：单元测试
```

---

## Task 1: 数据模型扩展 (T148b)

**Files:**
- Modify: `storage/models.py:1-140`

- [ ] **Step 1: 添加导入和 dataclass**

在 `storage/models.py` 文件末尾（在 `SystemStatus` 类之后）添加：

```python
from typing import List


@dataclass
class CalibrationSignal:
    """单信号采集结果"""
    ear_mean: float = 0.0           # EAR 均值（睁眼基线）
    ear_min: float = 0.0           # EAR 最小值（闭眼阈值参考）
    ear_mid: float = 0.0           # EAR 中间值（眯眼阈值参考）
    yaw_mean: float = 0.0          # 头部偏转均值
    yaw_range: tuple = (0.0, 0.0)  # (左偏最大值, 右偏最大值)
    pitch_mean: float = 0.0        # 头部俯仰均值
    pitch_range: tuple = (0.0, 0.0)  # (仰角最大值, 俯角最大值)
    glasses_mode: bool = False      # 眼镜模式
    timestamp: float = 0.0         # 采集时间戳


@dataclass
class BlinkCalibrationRound:
    """单轮眨眼校准数据"""
    round_index: int = 0           # 第几轮（1-3）
    duration_seconds: int = 0       # 本轮时长（秒）
    user_blink_count: int = 0      # 用户手动计数
    program_blink_count: int = 0   # 程序统计计数
    program_squint_count: int = 0  # 程序统计眯眼次数
    error_rate: float = 0.0        # 误差率
    adjustment_factor: float = 1.0 # 本轮调整因子


@dataclass
class CalibrationResult:
    """完整校准结果"""
    session_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    signal: CalibrationSignal = field(default_factory=CalibrationSignal)
    blink_rounds: List[BlinkCalibrationRound] = field(default_factory=list)
    final_adjustment_factor: float = 1.0  # 多轮平均调整因子
    final_blink_threshold: float = 0.26  # 调整后的眨眼阈值
    final_squint_threshold: float = 0.20  # 调整后的眯眼阈值
    is_accepted: bool = True      # 用户是否接受
    notes: str = ""              # 用户备注
```

- [ ] **Step 2: 验证修改**

Run: `cd /d/Users/Katysia/Desktop/EyeFocus%20Insight && python -c "from storage.models import CalibrationSignal, BlinkCalibrationRound, CalibrationResult; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add storage/models.py
git commit -m "feat(T148b): 新增 CalibrationSignal, BlinkCalibrationRound, CalibrationResult 数据模型"
```

---

## Task 2: 数据库表扩展 (T148c)

**Files:**
- Modify: `storage/db.py:52-132`

- [ ] **Step 1: 添加新的 SCHEMA SQL**

在 `SCHEMA_SQL` 变量中（在 `blink_events` 表定义之后、`CREATE INDEX` 语句之前）添加：

```sql
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
```

- [ ] **Step 2: 添加 save_calibration 方法**

在 `DatabaseManager` 类中（在 `write_blink_event` 方法之后）添加：

```python
# ========== Calibration Records ==========

def save_calibration(self, calibration_id: int, session_id: str,
                      signal: 'CalibrationSignal',
                      is_accepted: bool = True,
                      notes: str = "") -> None:
    """保存校准信号数据

    Args:
        calibration_id: 校准记录 ID
        session_id: 会话 ID
        signal: CalibrationSignal 对象
        is_accepted: 用户是否接受
        notes: 用户备注
    """
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
    """保存单轮眨眼校准数据

    Args:
        calibration_id: 校准记录 ID
        round_data: BlinkCalibrationRound 对象
    """
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
    """创建校准记录

    Args:
        session_id: 会话 ID

    Returns:
        calibration_id: 新建记录的 ID
    """
    with self._get_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO calibration (session_id, timestamp)
            VALUES (?, ?)
            """,
            (session_id, time.time()),
        )
        return cursor.lastrowid
```

- [ ] **Step 3: 验证数据库初始化**

Run: `cd /d/Users/Katysia/Desktop/EyeFocus%20Insight && python -c "from storage.db import DatabaseManager; db = DatabaseManager(); db.initialize(); print('DB init OK')"`

Expected: `DB init OK`

- [ ] **Step 4: Commit**

```bash
git add storage/db.py
git commit -m "feat(T148c): 新增 calibration 和 blink_calibration_round 表"
```

---

## Task 3: UserCalibrationManager (T148a)

**Files:**
- Create: `analyzer/user_calibration.py`

- [ ] **Step 1: 创建基础结构**

创建 `analyzer/user_calibration.py`：

```python
"""
analyzer/user_calibration.py — 用户校准管理器

提供 UserCalibrationManager 类：
- 事件驱动状态机
- 6 阶段校准流程
- 回调接口通知外部

阶段：
0. 自动基线采集（7秒）
1. 闭眼校准（5秒）
2. 睁眼恢复（3秒）
3. 眯眼校准（8秒）
4. 头部姿态（12秒）
5. 眨眼计数（3轮×20秒）
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, List, Optional, Callable
from datetime import datetime

from storage.models import CalibrationSignal, BlinkCalibrationRound, CalibrationResult, GlassesMode

logger = logging.getLogger("eyefocus.analyzer")


# 默认阶段配置
DEFAULT_PHASES = {
    "auto_calib": 7,       # 阶段0：自动基线采集
    "closed_eyes": 5,      # 阶段1：闭眼校准
    "open_eyes": 3,        # 阶段2：睁眼恢复
    "squint": 8,           # 阶段3：眯眼校准
    "head_pose": 12,       # 阶段4：头部姿态
    # 阶段5：眨眼计数（动态，blink_rounds × blink_duration）
}

# 眨眼/眯眼判定阈值
BLINK_DURATION_THRESHOLD = 0.4  # 400ms


class CalibrationCallbacks(Protocol):
    """校准过程回调接口"""

    def on_phase_start(self, phase: int, phase_name: str, instruction: str) -> None:
        """新阶段开始"""
        ...

    def on_countdown_tick(self, remaining: int) -> None:
        """倒计时每秒更新"""
        ...

    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float) -> None:
        """实时信号更新"""
        ...

    def on_phase_complete(self, phase: int, collected_data: dict) -> None:
        """阶段完成"""
        ...

    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int) -> None:
        """眨眼校准轮开始"""
        ...

    def on_blink_round_tick(self, remaining: int, detected_blinks: int) -> None:
        """眨眼校准轮每秒更新"""
        ...

    def on_blink_round_end(self, round_num: int, program_count: int) -> None:
        """眨眼校准轮结束，等待用户输入"""
        ...

    def on_calibration_complete(self, result: CalibrationResult) -> None:
        """校准全部完成"""
        ...

    def on_error(self, phase: int, message: str) -> None:
        """校准过程出错"""
        ...
```

- [ ] **Step 2: 添加状态枚举和数据收集类**

继续添加：

```python
class CalibrationState:
    """校准状态枚举"""
    IDLE = "idle"
    AUTO_CALIB = "auto_calib"
    CLOSED_EYES = "closed_eyes"
    OPEN_EYES = "open_eyes"
    SQUINT = "squint"
    HEAD_UP = "head_up"
    HEAD_DOWN = "head_down"
    HEAD_LEFT = "head_left"
    HEAD_RIGHT = "head_right"
    BLINK_COUNTING = "blink_counting"
    BLINK_INPUT = "blink_input"
    FINISHED = "finished"
    ERROR = "error"


@dataclass
class SignalCollector:
    """信号采集器（用于阶段0）"""
    ears: List[float] = field(default_factory=list)
    yaws: List[float] = field(default_factory=list)
    pitches: List[float] = field(default_factory=list)
    ear_min: float = 999.0
    yaw_left_max: float = 0.0
    yaw_right_max: float = 0.0
    pitch_up_max: float = 0.0
    pitch_down_max: float = 0.0


class BlinkRoundCollector:
    """眨眼轮采集器"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time: Optional[float] = None
        self.detected_blinks: int = 0
        self.detected_squints: int = 0
        self._in_blink: bool = False
        self._blink_start_time: Optional[float] = None

    def record_frame(self, ear: float, ear_threshold: float, squint_threshold: float, current_time: float):
        """记录一帧数据

        Args:
            ear: 当前 EAR 值
            ear_threshold: 眨眼阈值
            squint_threshold: 眯眼阈值
            current_time: 当前时间戳
        """
        if ear < squint_threshold:
            # 眯眼或眨眼中
            if not self._in_blink:
                self._in_blink = True
                self._blink_start_time = current_time
        else:
            # 睁眼
            if self._in_blink and self._blink_start_time is not None:
                duration = current_time - self._blink_start_time
                if duration < BLINK_DURATION_THRESHOLD:
                    self.detected_blinks += 1
                else:
                    self.detected_squints += 1
                self._in_blink = False
                self._blink_start_time = None
```

- [ ] **Step 3: 添加 UserCalibrationManager 类核心**

继续添加：

```python
class UserCalibrationManager:
    """用户校准管理器（事件驱动）"""

    def __init__(
        self,
        callbacks: CalibrationCallbacks,
        blink_rounds: int = 3,
        blink_duration: int = 20,
        phases: dict = None,
    ):
        """
        Args:
            callbacks: 回调接口实现
            blink_rounds: 眨眼校准轮数
            blink_duration: 每轮眨眼校准时长（秒）
            phases: 各阶段时长配置
        """
        self.callbacks = callbacks
        self.blink_rounds = blink_rounds
        self.blink_duration = blink_duration
        self.phases = phases or DEFAULT_PHASES.copy()

        self._state = CalibrationState.IDLE
        self._current_phase = 0
        self._signal_collector = SignalCollector()
        self._blink_collector = BlinkRoundCollector()
        self._blink_rounds_data: List[BlinkCalibrationRound] = []

        self._phase_start_time: Optional[float] = None
        self._current_blink_round = 0
        self._squint_ear_values: List[float] = []

        # 外部传入的检测器引用（用于获取实时 EAR）
        self._get_ear_callback: Optional[Callable[[], float]] = None
        self._get_head_pose_callback: Optional[Callable[[], tuple]] = None
        self._get_blink_count_callback: Optional[Callable[[], int]] = None

    def set_ear_callback(self, callback: Callable[[], float]) -> None:
        """设置获取实时 EAR 的回调"""
        self._get_ear_callback = callback

    def set_head_pose_callback(self, callback: Callable[[], tuple]) -> None:
        """设置获取实时头部姿态的回调"""
        self._get_head_pose_callback = callback

    def set_blink_detector_callback(self, callback: Callable[[], int]) -> None:
        """设置获取眨眼次数的回调"""
        self._get_blink_count_callback = callback

    @property
    def state(self) -> str:
        """当前状态"""
        return self._state

    @property
    def current_phase(self) -> int:
        """当前阶段号"""
        return self._current_phase

    def start(self) -> None:
        """开始校准流程"""
        if self._state != CalibrationState.IDLE:
            logger.warning("校准已在进行中")
            return

        self._reset()
        self._state = CalibrationState.AUTO_CALIB
        self._current_phase = 0
        self._phase_start_time = time.time()

        phase_name, instruction = self._get_phase_info(0)
        self.callbacks.on_phase_start(0, phase_name, instruction)
        logger.info("校准开始: 阶段0 自动基线采集")

    def on_user_ready(self) -> None:
        """用户按 Enter确认"""
        if self._state == CalibrationState.AUTO_CALIB:
            # 用户在阶段0按Enter，跳过等待直接开始
            self._run_auto_calib()
        elif self._state == CalibrationState.BLINK_COUNTING:
            # 用户在眨眼计数阶段按Enter，可能想取消
            pass

    def on_user_input(self, user_blink_count: int) -> None:
        """用户输入眨眼次数"""
        if self._state != CalibrationState.BLINK_INPUT:
            logger.warning("不在输入状态，忽略输入")
            return

        self._record_blink_round(user_blink_count)

    def on_cancel(self) -> None:
        """用户取消校准"""
        logger.info("用户取消校准")
        self._state = CalibrationState.IDLE
        self._reset()

    def get_current_round_blinks(self) -> int:
        """获取当前轮检测到的眨眼次数"""
        return self._blink_collector.detected_blinks

    def get_current_round_squints(self) -> int:
        """获取当前轮检测到的眯眼次数"""
        return self._blink_collector.detected_squints

    def get_result(self) -> Optional[CalibrationResult]:
        """获取校准结果（仅在 FINISHED 状态有效）"""
        if self._state != CalibrationState.FINISHED:
            return None
        return self._compute_result()

    def _reset(self) -> None:
        """重置内部状态"""
        self._signal_collector = SignalCollector()
        self._blink_collector.reset()
        self._blink_rounds_data.clear()
        self._current_blink_round = 0
        self._squint_ear_values.clear()

    def _get_phase_info(self, phase: int) -> tuple:
        """获取阶段信息"""
        phases = [
            ("自动基线采集", "请保持自然睁眼，系统将自动采集数据..."),
            ("闭眼校准", "请闭眼并保持 5 秒..."),
            ("睁眼恢复", "请睁眼并保持 3 秒..."),
            ("眯眼校准", "请故意眯眼并保持 2-3 秒..."),
            ("头部姿态", "请按照指示移动头部..."),
            ("眨眼计数校准", "即将开始眨眼计数..."),
        ]
        if phase < len(phases):
            return phases[phase]
        return ("未知", "")

    def _run_auto_calib(self) -> None:
        """执行自动基线采集阶段"""
        elapsed = time.time() - self._phase_start_time
        remaining = int(self.phases["auto_calib"] - elapsed)

        if remaining > 0:
            self.callbacks.on_countdown_tick(remaining)

        # 采集数据
        if self._get_ear_callback:
            ear = self._get_ear_callback()
            self._signal_collector.ears.append(ear)
            if ear < self._signal_collector.ear_min:
                self._signal_collector.ear_min = ear

        if self._get_head_pose_callback:
            yaw, pitch = self._get_head_pose_callback()
            self._signal_collector.yaws.append(yaw)
            self._signal_collector.pitches.append(pitch)

        # 检查是否完成
        if elapsed >= self.phases["auto_calib"]:
            # 阶段完成
            self.callbacks.on_phase_complete(0, {
                "ear_mean": sum(self._signal_collector.ears) / len(self._signal_collector.ears) if self._signal_collector.ears else 0,
                "frame_count": len(self._signal_collector.ears),
            })
            self._transition_to_next_phase()
```

- [ ] **Step 4: 添加状态转换和定时器方法**

继续添加：

```python
    def tick(self) -> None:
        """定时器触发（每秒调用一次）"""
        if self._state == CalibrationState.IDLE or self._state == CalibrationState.FINISHED:
            return

        elapsed = time.time() - self._phase_start_time
        current_phase_duration = self._get_current_phase_duration()

        if current_phase_duration > 0:
            remaining = int(current_phase_duration - elapsed)
            if remaining >= 0:
                self.callbacks.on_countdown_tick(remaining)

        # 阶段内数据采集
        self._collect_phase_data()

        # 检查阶段是否完成
        if elapsed >= current_phase_duration:
            if current_phase_duration > 0:
                self._on_phase_complete()

    def _get_current_phase_duration(self) -> float:
        """获取当前阶段的时长"""
        if self._state == CalibrationState.AUTO_CALIB:
            return self.phases["auto_calib"]
        elif self._state == CalibrationState.CLOSED_EYES:
            return self.phases["closed_eyes"]
        elif self._state == CalibrationState.OPEN_EYES:
            return self.phases["open_eyes"]
        elif self._state == CalibrationState.SQUINT:
            return self.phases["squint"]
        elif self._state in (CalibrationState.HEAD_UP, CalibrationState.HEAD_DOWN,
                             CalibrationState.HEAD_LEFT, CalibrationState.HEAD_RIGHT):
            return self.phases["head_pose"] / 4  # 4个子阶段平分
        elif self._state == CalibrationState.BLINK_COUNTING:
            return self.blink_duration
        return 0

    def _collect_phase_data(self) -> None:
        """在当前阶段采集数据"""
        if self._state == CalibrationState.CLOSED_EYES:
            if self._get_ear_callback:
                ear = self._get_ear_callback()
                if ear < self._signal_collector.ear_min:
                    self._signal_collector.ear_min = ear

        elif self._state == CalibrationState.SQUINT:
            if self._get_ear_callback:
                ear = self._get_ear_callback()
                self._squint_ear_values.append(ear)

        elif self._state == CalibrationState.HEAD_UP:
            if self._get_head_pose_callback:
                _, pitch = self._get_head_pose_callback()
                if pitch < self._signal_collector.pitch_up_max:
                    self._signal_collector.pitch_up_max = pitch

        elif self._state == CalibrationState.HEAD_DOWN:
            if self._get_head_pose_callback:
                _, pitch = self._get_head_pose_callback()
                if pitch > self._signal_collector.pitch_down_max:
                    self._signal_collector.pitch_down_max = pitch

        elif self._state == CalibrationState.HEAD_LEFT:
            if self._get_head_pose_callback:
                yaw, _ = self._get_head_pose_callback()
                if yaw < self._signal_collector.yaw_left_max:
                    self._signal_collector.yaw_left_max = yaw

        elif self._state == CalibrationState.HEAD_RIGHT:
            if self._get_head_pose_callback:
                yaw, _ = self._get_head_pose_callback()
                if yaw > self._signal_collector.yaw_right_max:
                    self._signal_collector.yaw_right_max = yaw

        elif self._state == CalibrationState.BLINK_COUNTING:
            # 眨眼计数在 get_blink_count_callback 中获取
            pass

    def _on_phase_complete(self) -> None:
        """阶段完成处理"""
        phase = self._current_phase

        if self._state == CalibrationState.CLOSED_EYES:
            # 记录闭眼 EAR 最小值
            self.callbacks.on_phase_complete(1, {"ear_min": self._signal_collector.ear_min})

        elif self._state == CalibrationState.OPEN_EYES:
            self.callbacks.on_phase_complete(2, {})

        elif self._state == CalibrationState.SQUINT:
            # 计算眯眼阈值
            if self._squint_ear_values:
                squint_ear = sum(self._squint_ear_values) / len(self._squint_ear_values)
            else:
                squint_ear = self._signal_collector.ear_min * 1.5
            self.callbacks.on_phase_complete(3, {"squint_ear": squint_ear})

        elif self._state == CalibrationState.HEAD_RIGHT:
            self.callbacks.on_phase_complete(4, {})

        elif self._state == CalibrationState.BLINK_COUNTING:
            # 眨眼计数轮结束，等待用户输入
            program_count = self._blink_collector.detected_blinks
            self.callbacks.on_blink_round_end(self._current_blink_round, program_count)
            self._state = CalibrationState.BLINK_INPUT
            return

        self._transition_to_next_phase()

    def _transition_to_next_phase(self) -> None:
        """转换到下一阶段"""
        self._current_phase += 1
        self._phase_start_time = time.time()

        if self._current_phase == 1:
            self._state = CalibrationState.CLOSED_EYES
        elif self._current_phase == 2:
            self._state = CalibrationState.OPEN_EYES
        elif self._current_phase == 3:
            self._state = CalibrationState.SQUINT
        elif self._current_phase == 4:
            self._state = CalibrationState.HEAD_UP
        elif self._current_phase == 5:
            # 眨眼计数阶段
            self._current_blink_round = 1
            self._blink_collector.reset()
            self._state = CalibrationState.BLINK_COUNTING
            self.callbacks.on_blink_round_start(1, self.blink_rounds, self.blink_duration)
        else:
            # 校准完成
            self._state = CalibrationState.FINISHED
            result = self._compute_result()
            self.callbacks.on_calibration_complete(result)
            return

        phase_name, instruction = self._get_phase_info(self._current_phase)
        self.callbacks.on_phase_start(self._current_phase, phase_name, instruction)

    def _record_blink_round(self, user_count: int) -> None:
        """记录一轮眨眼校准数据"""
        program_count = self._blink_collector.detected_blinks
        squint_count = self._blink_collector.detected_squints

        if user_count > 0:
            error_rate = (user_count - program_count) / user_count
            adjustment = 1.0 + error_rate
        else:
            error_rate = 0.0
            adjustment = 1.0

        adjustment = max(0.7, min(1.3, adjustment))

        round_data = BlinkCalibrationRound(
            round_index=self._current_blink_round,
            duration_seconds=self.blink_duration,
            user_blink_count=user_count,
            program_blink_count=program_count,
            program_squint_count=squint_count,
            error_rate=error_rate,
            adjustment_factor=adjustment,
        )
        self._blink_rounds_data.append(round_data)

        # 检查是否还有下一轮
        if self._current_blink_round < self.blink_rounds:
            self._current_blink_round += 1
            self._blink_collector.reset()
            self._state = CalibrationState.BLINK_COUNTING
            self.callbacks.on_blink_round_start(
                self._current_blink_round,
                self.blink_rounds,
                self.blink_duration
            )
        else:
            # 所有轮完成，校准结束
            self._state = CalibrationState.FINISHED
            result = self._compute_result()
            self.callbacks.on_calibration_complete(result)

    def _compute_result(self) -> CalibrationResult:
        """计算校准结果"""
        # EAR 均值
        ear_mean = sum(self._signal_collector.ears) / len(self._signal_collector.ears) if self._signal_collector.ears else 0.25
        ear_min = self._signal_collector.ear_min if self._signal_collector.ear_min != 999.0 else ear_mean * 0.3

        # 眯眼阈值（EAR 中间值）
        squint_threshold = ear_mean * 0.75

        # 眨眼阈值调整因子
        if self._blink_rounds_data:
            adjustments = [r.adjustment_factor for r in self._blink_rounds_data]
            final_adjustment = sum(adjustments) / len(adjustments)
        else:
            final_adjustment = 1.0

        # 眨眼阈值 = baseline * 0.75 * adjustment
        final_blink_threshold = ear_mean * 0.75 * final_adjustment

        signal = CalibrationSignal(
            ear_mean=ear_mean,
            ear_min=ear_min,
            ear_mid=squint_threshold,
            yaw_mean=sum(self._signal_collector.yaws) / len(self._signal_collector.yaws) if self._signal_collector.yaws else 0.0,
            yaw_range=(self._signal_collector.yaw_left_max, self._signal_collector.yaw_right_max),
            pitch_mean=sum(self._signal_collector.pitches) / len(self._signal_collector.pitches) if self._signal_collector.pitches else 0.0,
            pitch_range=(self._signal_collector.pitch_up_max, self._signal_collector.pitch_down_max),
            glasses_mode=False,  # 后续从 glasses_detector 获取
            timestamp=time.time(),
        )

        return CalibrationResult(
            session_id="",
            timestamp=datetime.now(),
            signal=signal,
            blink_rounds=self._blink_rounds_data.copy(),
            final_adjustment_factor=final_adjustment,
            final_blink_threshold=final_blink_threshold,
            final_squint_threshold=squint_threshold,
            is_accepted=True,
            notes="",
        )


def create_user_calibration_manager(callbacks: CalibrationCallbacks) -> UserCalibrationManager:
    """工厂函数：创建用户校准管理器"""
    return UserCalibrationManager(callbacks=callbacks)
```

- [ ] **Step 5: 验证语法**

Run: `cd /d/Users/Katysia/Desktop/EyeFocus%20Insight && python -c "from analyzer.user_calibration import UserCalibrationManager, CalibrationCallbacks; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 6: Commit**

```bash
git add analyzer/user_calibration.py
git commit -m "feat(T148a): 实现 UserCalibrationManager 状态机和回调接口"
```

---

## Task 4: GUI 校准 UI (T148d)

**Files:**
- Modify: `gui/overlay.py:74-410`

- [ ] **Step 1: 添加校准相关常量和数据结构**

在 `gui/overlay.py` 中，在 `FocusOverlay` 类之前添加：

```python
# ========== 校准 UI 相关 ==========

@dataclass
class CalibrationPhaseInfo:
    """校准阶段信息"""
    phase: int
    name: str
    instruction: str
    remaining: int = 0
    is_input_mode: bool = False
    round_num: int = 0
    total_rounds: int = 0
    detected_blinks: int = 0
    program_count: int = 0
    result: Optional['CalibrationResult'] = None


@dataclass
class CalibrationDisplayData:
    """校准显示数据"""
    is_calibrating: bool = False
    current_phase: Optional[CalibrationPhaseInfo] = None
```

- [ ] **Step 2: 添加 FocusOverlay 校准方法**

在 `FocusOverlay` 类的 `__init__` 方法之后、`draw` 方法之前添加：

```python
def show_calibration_phase(self, phase: int, phase_name: str, instruction: str) -> None:
    """显示校准阶段信息

    Args:
        phase: 阶段号 (0-5)
        phase_name: 阶段名称
        instruction: 指导文字
    """
    self._calib_phase = CalibrationPhaseInfo(
        phase=phase,
        name=phase_name,
        instruction=instruction,
    )
    self._calib_display = CalibrationDisplayData(
        is_calibrating=True,
        current_phase=self._calib_phase,
    )

def update_calibration_countdown(self, remaining: int) -> None:
    """更新校准倒计时

    Args:
        remaining: 剩余秒数
    """
    if self._calib_phase:
        self._calib_phase.remaining = remaining

def show_phase_complete(self, phase: int) -> None:
    """显示阶段完成"""
    pass  # 可以添加短暂的成功提示

def show_blink_round(self, round_num: int, total: int, duration: int) -> None:
    """显示眨眼校准轮开始

    Args:
        round_num: 当前轮号
        total: 总轮数
        duration: 本轮时长（秒）
    """
    if self._calib_phase:
        self._calib_phase.round_num = round_num
        self._calib_phase.total_rounds = total
        self._calib_phase.remaining = duration
        self._calib_phase.is_input_mode = False

def update_blink_round(self, remaining: int, detected_blinks: int) -> None:
    """更新眨眼校准轮状态

    Args:
        remaining: 剩余秒数
        detected_blinks: 检测到的眨眼次数
    """
    if self._calib_phase:
        self._calib_phase.remaining = remaining
        self._calib_phase.detected_blinks = detected_blinks

def show_blink_input(self, round_num: int, program_count: int) -> None:
    """显示眨眼输入框

    Args:
        round_num: 当前轮号
        program_count: 程序检测到的眨眼次数
    """
    if self._calib_phase:
        self._calib_phase.round_num = round_num
        self._calib_phase.program_count = program_count
        self._calib_phase.is_input_mode = True

def show_calibration_result(self, result: 'CalibrationResult') -> None:
    """显示校准结果

    Args:
        result: 校准结果
    """
    if self._calib_phase:
        self._calib_phase.result = result
        self._calib_phase.is_input_mode = False

def hide_calibration_ui(self) -> None:
    """隐藏校准 UI"""
    self._calib_display = CalibrationDisplayData(is_calibrating=False)
    self._calib_phase = None

def _draw_calibration_full(self, frame: np.ndarray) -> np.ndarray:
    """绘制完整校准 UI

    Args:
        frame: 原始帧

    Returns:
        叠加后的帧
    """
    if not self._calib_display or not self._calib_display.is_calibrating:
        return frame

    h, w = frame.shape[:2]
    phase = self._calib_phase
    if not phase:
        return frame

    # 中央面板
    panel_w = 400
    panel_h = 250
    panel_x = (w - panel_w) // 2
    panel_y = (h - panel_h) // 2

    # 半透明背景
    overlay = frame.copy()
    cv2.rectangle(overlay, (panel_x - 10, panel_y - 10),
                   (panel_x + panel_w + 10, panel_y + panel_h + 10),
                   (20, 20, 20), -1)
    frame = cv2.addWeighted(overlay, 0.8, frame, 0.2, 0)

    # 阶段名称
    phase_text = f"[阶段 {phase.phase + 1}/6] {phase.name}"
    cv2.putText(frame, phase_text,
                (panel_x + 20, panel_y + 35),
                self.config.font, 0.7, (255, 255, 255), 2)

    # 指导文字
    cv2.putText(frame, phase.instruction,
                (panel_x + 20, panel_y + 70),
                self.config.font, 0.5, (200, 200, 200), 1)

    # 倒计时
    if not phase.is_input_mode:
        countdown_text = f"剩余: {phase.remaining} 秒"
        cv2.putText(frame, countdown_text,
                    (panel_x + 20, panel_y + 110),
                    self.config.font, 0.6, (0, 255, 0), 2)

    # 眨眼计数阶段特殊显示
    if phase.round_num > 0:
        round_text = f"眨眼计数: 第 {phase.round_num}/{phase.total_rounds} 轮"
        cv2.putText(frame, round_text,
                    (panel_x + 20, panel_y + 145),
                    self.config.font, 0.5, (255, 255, 0), 1)

        detected_text = f"检测到: {phase.detected_blinks} 次眨眼"
        cv2.putText(frame, detected_text,
                    (panel_x + 20, panel_y + 170),
                    self.config.font, 0.5, (0, 255, 255), 1)

    # 输入模式提示
    if phase.is_input_mode:
        input_text = f"请输入您的眨眼次数（程序检测到 {phase.program_count} 次）"
        cv2.putText(frame, input_text,
                    (panel_x + 20, panel_y + 145),
                    self.config.font, 0.5, (255, 200, 0), 1)

        hint_text = "按数字键输入，按 Enter 确认"
        cv2.putText(frame, hint_text,
                    (panel_x + 20, panel_y + 200),
                    self.config.font, 0.4, (150, 150, 150), 1)

    # 取消提示
    cv2.putText(frame, "按 ESC 取消校准",
                (panel_x + 20, panel_y + panel_h - 20),
                self.config.font, 0.4, (100, 100, 100), 1)

    return frame

def _draw_calibration_result(self, frame: np.ndarray) -> np.ndarray:
    """绘制校准结果

    Args:
        frame: 原始帧

    Returns:
        叠加后的帧
    """
    if not self._calib_phase or not self._calib_phase.result:
        return frame

    h, w = frame.shape[:2]
    result = self._calib_phase.result

    # 结果面板
    panel_w = 450
    panel_h = 200
    panel_x = (w - panel_w) // 2
    panel_y = (h - panel_h) // 2

    overlay = frame.copy()
    cv2.rectangle(overlay, (panel_x - 10, panel_y - 10),
                   (panel_x + panel_w + 10, panel_y + panel_h + 10),
                   (30, 30, 30), -1)
    frame = cv2.addWeighted(overlay, 0.85, frame, 0.15, 0)

    # 标题
    cv2.putText(frame, "校准完成",
                (panel_x + 20, panel_y + 35),
                self.config.font, 0.8, (0, 255, 0), 2)

    # EAR 信息
    ear_text = f"EAR 基线: {result.signal.ear_mean:.4f}"
    cv2.putText(frame, ear_text,
                (panel_x + 20, panel_y + 75),
                self.config.font, 0.5, (255, 255, 255), 1)

    # 阈值信息
    threshold_text = f"眨眼阈值: {result.final_blink_threshold:.4f}"
    cv2.putText(frame, threshold_text,
                (panel_x + 20, panel_y + 100),
                self.config.font, 0.5, (255, 255, 255), 1)

    # 调整因子
    adj_text = f"调整因子: {result.final_adjustment_factor:.3f}"
    cv2.putText(frame, adj_text,
                (panel_x + 20, panel_y + 125),
                self.config.font, 0.5, (255, 255, 255), 1)

    # 确认提示
    cv2.putText(frame, "按 Enter 开始检测",
                (panel_x + 20, panel_y + 170),
                self.config.font, 0.5, (0, 255, 0), 1)

    return frame
```

- [ ] **Step 3: 修改 draw 方法集成校准 UI**

找到 `FocusOverlay.draw` 方法，在末尾（`return cv2.addWeighted(...)` 之前）添加：

```python
        # 绘制校准 UI
        if hasattr(self, '_calib_display') and self._calib_display and self._calib_display.is_calibrating:
            if self._calib_phase and self._calib_phase.result:
                frame = self._draw_calibration_result(frame)
            else:
                frame = self._draw_calibration_full(frame)
```

- [ ] **Step 4: 验证语法**

Run: `cd /d/Users/Katysia/Desktop/EyeFocus%20Insight && python -c "from gui.overlay import FocusOverlay; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 5: Commit**

```bash
git add gui/overlay.py
git commit -m "feat(T148d): 新增校准 UI 方法到 FocusOverlay"
```

---

## Task 5: main.py 集成 (T148e)

**Files:**
- Modify: `main.py:1-604`

- [ ] **Step 1: 添加导入**

在 `main.py` 顶部的导入部分（在 `from gui.overlay import` 行）添加：

```python
from analyzer.user_calibration import (
    UserCalibrationManager,
    CalibrationCallbacks,
    create_user_calibration_manager,
)
from storage.models import CalibrationResult
```

- [ ] **Step 2: 添加校准回调实现类**

在 `EyeFocusApp` 类定义之前添加：

```python
class CalibrationFlowCallbacks:
    """校准流程回调实现"""

    def __init__(self, app: 'EyeFocusApp'):
        self.app = app
        self._input_buffer: str = ""
        self._input_mode: bool = False

    def on_phase_start(self, phase: int, phase_name: str, instruction: str) -> None:
        """阶段开始"""
        self.app._overlay.show_calibration_phase(phase, phase_name, instruction)
        self._input_mode = False
        self._input_buffer = ""

    def on_countdown_tick(self, remaining: int) -> None:
        """倒计时更新"""
        self.app._overlay.update_calibration_countdown(remaining)

        # 通知校准管理器采集数据
        if hasattr(self.app, '_calib_manager') and self.app._calib_manager:
            self.app._calib_manager.tick()

    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float) -> None:
        """信号更新"""
        pass

    def on_phase_complete(self, phase: int, collected_data: dict) -> None:
        """阶段完成"""
        self.app._overlay.show_phase_complete(phase)

    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int) -> None:
        """眨眼轮开始"""
        self.app._overlay.show_blink_round(round_num, total_rounds, duration)

    def on_blink_round_tick(self, remaining: int, detected_blinks: int) -> None:
        """眨眼轮更新"""
        self.app._overlay.update_blink_round(remaining, detected_blinks)

        # 通知校准管理器采集眨眼数据
        if hasattr(self.app, '_calib_manager') and self.app._calib_manager:
            self.app._calib_manager.tick()

    def on_blink_round_end(self, round_num: int, program_count: int) -> None:
        """眨眼轮结束，等待输入"""
        self.app._overlay.show_blink_input(round_num, program_count)
        self._input_mode = True
        self._input_buffer = ""

    def on_calibration_complete(self, result: CalibrationResult) -> None:
        """校准完成"""
        self.app._overlay.show_calibration_result(result)
        self._input_mode = False
        self._apply_calibration_result(result)

    def on_error(self, phase: int, message: str) -> None:
        """错误"""
        logger.error("校准错误 [阶段 %d]: %s", phase, message)

    def on_digit_input(self, digit: str) -> None:
        """数字输入"""
        if self._input_mode:
            self._input_buffer += digit

    def on_enter_pressed(self) -> None:
        """确认输入"""
        if self._input_mode and hasattr(self.app, '_calib_manager') and self.app._calib_manager:
            try:
                count = int(self._input_buffer) if self._input_buffer else 0
                self.app._calib_manager.on_user_input(count)
            except ValueError:
                logger.warning("无效输入: %s", self._input_buffer)
            self._input_buffer = ""
            self._input_mode = False

    def _apply_calibration_result(self, result: CalibrationResult) -> None:
        """应用校准结果到各模块"""
        # 更新眨眼检测阈值
        if hasattr(self.app, '_eye_detector') and self.app._eye_detector:
            self.app._eye_detector.set_baseline(result.signal.ear_mean)
            # 注意：set_blink_threshold 和 set_squint_threshold 方法需要确认存在

        # 更新会话信息
        if self.app._db and self.app._session_id:
            self.app._db.update_session(
                self.app._session_id,
                baseline_ear=result.signal.ear_mean,
                is_calibrated=True,
            )

        logger.info("校准结果已应用: EAR=%.4f, 眨眼阈值=%.4f",
                    result.signal.ear_mean, result.final_blink_threshold)
```

- [ ] **Step 3: 修改 EyeFocusApp.__init__**

在 `EyeFocusApp.__init__` 方法中（在 `self._latest_glasses_result = None` 之后）添加：

```python
        # 校准相关
        self._calib_manager: Optional[UserCalibrationManager] = None
        self._calib_callbacks: Optional[CalibrationFlowCallbacks] = None
```

- [ ] **Step 4: 修改 initialize 方法**

在 `initialize` 方法中（在 `self._fatigue_analyzer.start()` 之后）添加：

```python
            # 初始化校准管理器
            self._calib_callbacks = CalibrationFlowCallbacks(self)
            self._calib_manager = create_user_calibration_manager(
                callbacks=self._calib_callbacks
            )
```

- [ ] **Step 5: 添加校准启动方法**

在 `EyeFocusApp` 类中添加：

```python
    def start_calibration_flow(self) -> bool:
        """启动新的用户校准流程（替代旧的 start_calibration）

        Returns:
            True 如果成功开始
        """
        if self._calib_manager is None:
            logger.error("校准管理器未初始化")
            return False

        # 设置回调获取实时数据
        self._calib_manager.set_ear_callback(
            lambda: self._eye_detector.get_current_ear() if hasattr(self._eye_detector, 'get_current_ear') else 0.0
        )
        self._calib_manager.set_head_pose_callback(
            lambda: (0.0, 0.0)  # 从 face_result 获取
        )

        self._calib_manager.start()
        return True

    def is_calibration_flow_active(self) -> bool:
        """检查校准流程是否在进行中"""
        if self._calib_manager is None:
            return False
        return self._calib_manager.state != CalibrationState.IDLE
```

- [ ] **Step 6: 修改 _main_loop 键盘处理**

找到 `_main_loop` 中的键盘处理部分（`if key == ord('q'):` 附近），在之前添加：

```python
                # 校准流程键盘处理
                if self._calib_callbacks and self._calib_callbacks._input_mode:
                    if 48 <= key <= 57:  # 数字键
                        self._calib_callbacks.on_digit_input(chr(key))
                    elif key == 13 or key == 10:  # Enter
                        self._calib_callbacks.on_enter_pressed()
                    elif key == 27:  # ESC
                        if self._calib_manager:
                            self._calib_manager.on_cancel()
                            self._overlay.hide_calibration_ui()
                else:
                    # 正常模式键盘处理
                    if key == ord('c') or key == ord('C'):
                        # 手动触发校准
                        self.start_calibration_flow()
                    elif key == ord('q'):
                        logger.info("用户请求退出")
                        break
```

- [ ] **Step 7: 修改 _process_frame 集成校准数据采集**

在 `_process_frame` 方法中，找到 `if self._calibrating:` 块，在其后添加（或修改现有逻辑）：

```python
        # 用户校准流程中（替代旧的 _calibrating）
        if self._calib_manager and self._calib_manager.state != CalibrationState.IDLE:
            # 在各阶段采集数据
            state = self._calib_manager.state
            if state in (CalibrationState.AUTO_CALIB, CalibrationState.CLOSED_EYES,
                        CalibrationState.SQUINT, CalibrationState.HEAD_UP,
                        CalibrationState.HEAD_DOWN, CalibrationState.HEAD_LEFT,
                        CalibrationState.HEAD_RIGHT):
                # 采集 EAR 和头部姿态数据
                pass  # 数据通过回调获取
            elif state == CalibrationState.BLINK_COUNTING:
                # 更新眨眼计数
                pass  # 数据通过回调获取
```

- [ ] **Step 8: Commit**

```bash
git add main.py
git commit -m "feat(T148e): 集成 UserCalibrationManager 到 main.py"
```

---

## Task 6: 单元测试 (T148f)

**Files:**
- Create: `tests/test_user_calibration.py`

- [ ] **Step 1: 创建测试文件**

创建 `tests/test_user_calibration.py`：

```python
"""
tests/test_user_calibration.py — 用户校准模块单元测试
"""

import time
import pytest
from unittest.mock import Mock, MagicMock

from analyzer.user_calibration import (
    UserCalibrationManager,
    CalibrationCallbacks,
    CalibrationState,
    SignalCollector,
    BlinkRoundCollector,
    BLINK_DURATION_THRESHOLD,
)
from storage.models import CalibrationSignal, BlinkCalibrationRound


class MockCallbacks:
    """模拟回调"""
    def __init__(self):
        self.events = []
        self.last_phase = None
        self.last_countdown = 0
        self.last_blink_round_end = None
        self.last_result = None

    def on_phase_start(self, phase: int, phase_name: str, instruction: str):
        self.events.append(("phase_start", phase, phase_name))
        self.last_phase = phase

    def on_countdown_tick(self, remaining: int):
        self.events.append(("countdown", remaining))
        self.last_countdown = remaining

    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float):
        pass

    def on_phase_complete(self, phase: int, collected_data: dict):
        self.events.append(("phase_complete", phase))

    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int):
        self.events.append(("blink_round_start", round_num, total_rounds))

    def on_blink_round_tick(self, remaining: int, detected_blinks: int):
        self.events.append(("blink_round_tick", remaining, detected_blinks))

    def on_blink_round_end(self, round_num: int, program_count: int):
        self.events.append(("blink_round_end", round_num, program_count))
        self.last_blink_round_end = (round_num, program_count)

    def on_calibration_complete(self, result):
        self.events.append(("calibration_complete",))
        self.last_result = result

    def on_error(self, phase: int, message: str):
        self.events.append(("error", phase, message))


class TestSignalCollector:
    """SignalCollector 测试"""

    def test_init(self):
        sc = SignalCollector()
        assert sc.ears == []
        assert sc.ear_min == 999.0

    def test_record_ear(self):
        sc = SignalCollector()
        sc.ears = [0.3, 0.35, 0.32]
        assert len(sc.ears) == 3


class TestBlinkRoundCollector:
    """BlinkRoundCollector 测试"""

    def test_init(self):
        brc = BlinkRoundCollector()
        brc.reset()
        assert brc.detected_blinks == 0
        assert brc.detected_squints == 0

    def test_short_blink(self):
        """测试短闭眼（眨眼）"""
        brc = BlinkRoundCollector()
        current_time = time.time()

        # 闭眼
        brc.record_frame(ear=0.1, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time)
        assert brc._in_blink == True

        # 快速睁眼（眨眼）
        brc.record_frame(ear=0.35, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time + 0.2)
        assert brc.detected_blinks == 1
        assert brc.detected_squints == 0

    def test_long_blink(self):
        """测试长闭眼（眯眼）"""
        brc = BlinkRoundCollector()
        current_time = time.time()

        # 闭眼
        brc.record_frame(ear=0.1, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time)
        # 长闭眼（眯眼）
        brc.record_frame(ear=0.15, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time + 0.5)
        assert brc._in_blink == True
        # 睁眼
        brc.record_frame(ear=0.35, ear_threshold=0.25, squint_threshold=0.2,
                         current_time=current_time + 0.5 + BLINK_DURATION_THRESHOLD)
        assert brc.detected_squints == 1
        assert brc.detected_blinks == 0


class TestUserCalibrationManager:
    """UserCalibrationManager 测试"""

    def test_init(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        assert mgr.state == CalibrationState.IDLE
        assert mgr.current_phase == 0

    def test_start(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        mgr.start()
        assert mgr.state == CalibrationState.AUTO_CALIB
        assert len(callbacks.events) > 0
        assert callbacks.events[0][0] == "phase_start"

    def test_cancel(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        mgr.start()
        mgr.on_cancel()
        assert mgr.state == CalibrationState.IDLE

    def test_get_result_before_finish(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks)
        assert mgr.get_result() is None

    def test_blink_round_input(self):
        callbacks = MockCallbacks()
        mgr = UserCalibrationManager(callbacks=callbacks, blink_rounds=1, blink_duration=1)

        # 手动设置到 BLINK_INPUT 状态
        mgr._state = CalibrationState.BLINK_INPUT
        mgr._blink_collector.detected_blinks = 5

        mgr.on_user_input(user_blink_count=6)

        # 应该切换到 FINISHED（只有1轮）
        assert mgr.state == CalibrationState.FINISHED
        assert len(mgr._blink_rounds_data) == 1
        assert mgr._blink_rounds_data[0].user_blink_count == 6
        assert mgr._blink_rounds_data[0].program_blink_count == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: 运行测试**

Run: `cd /d/Users/Katysia/Desktop/EyeFocus%20Insight && python -m pytest tests/test_user_calibration.py -v`

Expected: 测试通过（PASS）

- [ ] **Step 3: Commit**

```bash
git add tests/test_user_calibration.py
git commit -m "test(T148f): 新增 UserCalibrationManager 单元测试"
```

---

## 自我审查清单

- [ ] Spec coverage: 每个设计部分都有对应任务
- [ ] Placeholder scan: 无 TBD/TODO
- [ ] Type consistency: 数据模型、回调接口、状态枚举一致
- [ ] 文件路径: 所有路径使用 `storage/models.py` 格式（Windows 兼容）
- [ ] 命令格式: 使用 `cd /d/...` 格式（Git Bash 兼容）

---

## 执行选项

**Plan complete and saved to `docs/superpowers/plans/2026-05-31-t148-user-calibration-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
