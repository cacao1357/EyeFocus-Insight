# T148 用户校准系统设计

> **版本**：v1.0 | **日期**：2026-05-31
> **基于**：PHASE1_PLAN.md v1.3 T148
> **架构方案**：事件驱动型

---

## 一、整体架构

### 1.1 核心组件

```
┌─────────────────────────────────────────────────────────┐
│                        main.py                           │
│  - 管理 UserCalibrationManager 实例                      │
│  - 实现 CalibrationCallbacks 回调接口                    │
│  - 处理状态切换和业务逻辑                                │
└─────────────────────────────────────────────────────────┘
              ↓ 持有引用
┌─────────────────────────────────────────────────────────┐
│              UserCalibrationManager                      │
│  - 内部状态机                                           │
│  - 纯计算逻辑，不依赖 GUI                               │
│  - 通过回调通知外部                                      │
└─────────────────────────────────────────────────────────┘
              ↓ 回调
┌─────────────────────────────────────────────────────────┐
│               CalibrationCallbacks                       │
│  - on_phase_start / on_phase_complete                  │
│  - on_countdown_tick                                   │
│  - on_blink_round_start / on_blink_round_tick          │
│  - on_blink_round_end / on_calibration_complete        │
│  - on_error                                            │
└─────────────────────────────────────────────────────────┘
              ↓ 调用
┌─────────────────────────────────────────────────────────┐
│                    overlay.py                           │
│  - 实现回调接口                                          │
│  - 显示校准 UI：倒计时、眨眼计数、输入框、结果对比        │
└─────────────────────────────────────────────────────────┘
```

### 1.2 组件职责

| 组件 | 职责 |
|------|------|
| `UserCalibrationManager` | 状态机 + 信号采集 + 阈值计算逻辑 |
| `main.py` | 持有 Manager 实例，实现回调接口，驱动主循环 |
| `overlay.py` | UI 渲染，不持有 Manager 引用 |

---

## 二、校准流程

### 2.1 完整阶段

| 阶段 | 名称 | 时长 | 说明 |
|------|------|------|------|
| 0 | 自动基线采集 | 7秒 | EAR均值、yaw/pitch均值、眼镜模式 |
| 1 | 闭眼校准 | 5秒 | 请闭眼保持，采集 ear_min |
| 2 | 睁眼恢复 | 3秒 | 请睁眼，验证 EAR 恢复 |
| 3 | 眯眼校准 | 8秒 | 请故意眯眼 2-3秒，采集眯眼阈值 |
| 4 | 头部姿态 | 12秒 | 抬头3s + 低头3s + 左转3s + 右转3s |
| 5 | 眨眼计数 | 3轮×20秒 | 用户计数 vs 程序检测对比 |

**总时长**：约 87 秒（< 90 秒要求）

### 2.2 状态机流转

```
IDLE
  ↓ start()
AUTO_CALIB (7s)
  ↓
CLOSED_EYES (5s)
  ↓
OPEN_EYES (3s)
  ↓
SQUINT (8s)
  ↓
HEAD_POSE (12s)
  ↓
BLINK_ROUND_1 (20s) → INPUT_1 → BLINK_ROUND_2 (20s) → INPUT_2 → BLINK_ROUND_3 (20s) → INPUT_3
  ↓
FINISHED
```

---

## 三、数据模型

### 3.1 新增 dataclass

```python
@dataclass
class CalibrationSignal:
    """单信号采集结果"""
    ear_mean: float           # EAR 均值（睁眼基线）
    ear_min: float            # EAR 最小值（闭眼阈值参考）
    ear_mid: float           # EAR 中间值（眯眼阈值参考）
    yaw_mean: float          # 头部偏转均值
    yaw_range: tuple          # (左偏最大值, 右偏最大值)
    pitch_mean: float         # 头部俯仰均值
    pitch_range: tuple        # (仰角最大值, 俯角最大值)
    glasses_mode: bool        # 眼镜模式
    timestamp: float         # 采集时间戳


@dataclass
class BlinkCalibrationRound:
    """单轮眨眼校准数据"""
    round_index: int          # 第几轮（1-3）
    duration_seconds: int     # 本轮时长（秒）
    user_blink_count: int    # 用户手动计数
    program_blink_count: int # 程序统计计数
    program_squint_count: int # 程序统计眯眼次数
    error_rate: float        # 误差率
    adjustment_factor: float # 本轮调整因子


@dataclass
class CalibrationResult:
    """完整校准结果"""
    session_id: str
    timestamp: datetime
    signal: CalibrationSignal
    blink_rounds: List[BlinkCalibrationRound]
    final_adjustment_factor: float   # 多轮平均调整因子
    final_blink_threshold: float     # 调整后的眨眼阈值
    final_squint_threshold: float    # 调整后的眯眼阈值
    is_accepted: bool              # 用户是否接受
    notes: str                      # 用户备注
```

### 3.2 数据库新增表

```sql
CREATE TABLE calibration (
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

CREATE TABLE blink_calibration_round (
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

---

## 四、回调接口

### 4.1 CalibrationCallbacks

```python
class CalibrationCallbacks(Protocol):
    """校准过程回调接口"""

    def on_phase_start(self, phase: int, phase_name: str, instruction: str) -> None: ...
    def on_countdown_tick(self, remaining: int) -> None: ...
    def on_detected_signals_update(self, ear: float, yaw: float, pitch: float) -> None: ...
    def on_phase_complete(self, phase: int, collected_data: dict) -> None: ...
    def on_blink_round_start(self, round_num: int, total_rounds: int, duration: int) -> None: ...
    def on_blink_round_tick(self, remaining: int, detected_blinks: int) -> None: ...
    def on_blink_round_end(self, round_num: int, program_count: int) -> None: ...
    def on_calibration_complete(self, result: CalibrationResult) -> None: ...
    def on_error(self, phase: int, message: str) -> None: ...
```

### 4.2 UserCalibrationManager 接口

```python
class UserCalibrationManager:
    def __init__(self, callbacks: CalibrationCallbacks,
                 blink_rounds: int = 3,
                 blink_duration: int = 20,
                 phases: dict = None):
        ...

    def start(self) -> None:           # 开始校准
    def on_user_ready(self) -> None:   # 用户按 Enter
    def on_user_input(self, user_blink_count: int) -> None:  # 用户输入眨眼次数
    def on_cancel(self) -> None:       # 用户取消
    def get_current_phase(self) -> int: ...
    def get_detected_blinks(self) -> int: ...
    def get_result(self) -> CalibrationResult: ...
```

### 4.3 默认阶段时长

```python
DEFAULT_PHASES = {
    "auto_calib": 7,       # 阶段0
    "closed_eyes": 5,      # 阶段1
    "open_eyes": 3,       # 阶段2
    "squint": 8,          # 阶段3
    "head_pose": 12,      # 阶段4
    # 阶段5：眨眼计数（动态，blink_rounds × blink_duration）
}
```

---

## 五、与 main.py 的集成

### 5.1 main.py 集成

```python
class EyeFocusApp:
    def __init__(self):
        self._calib_callbacks = CalibrationCallbacksImpl(self)
        self._calib_manager = UserCalibrationManager(
            callbacks=self._calib_callbacks,
            blink_rounds=3,
            blink_duration=20
        )

    def _run_calibration_flow(self):
        self._calib_manager.start()
```

### 5.2 结果应用

```python
def _apply_calibration_result(self, result: CalibrationResult):
    # 更新眨眼检测阈值
    self.eye_detector.set_baseline(result.signal.ear_mean)
    self.eye_detector.set_blink_threshold(result.final_blink_threshold)
    self.eye_detector.set_squint_threshold(result.final_squint_threshold)

    # 更新头部姿态阈值
    self.head_pose_detector.set_yaw_range(result.signal.yaw_range)
    self.head_pose_detector.set_pitch_range(result.signal.pitch_range)

    # 更新疲劳分析器
    self.fatigue_analyzer.set_blink_rate_baseline(
        result.signal.ear_mean, result.signal.ear_min
    )

    # 保存到数据库
    self.db.save_calibration(result)
```

### 5.3 键盘事件

| 按键 | 动作 |
|------|------|
| C | 手动触发校准 |
| ESC | 取消校准 |
| 0-9 | 数字输入 |
| Enter | 确认输入 |

---

## 六、验收标准

### 6.1 校准流程

| 指标 | 标准 |
|------|------|
| 启动方式 | 启动时自动触发，或用户按 C 键 |
| 阶段切换 | 自动按顺序切换，无手动干预 |
| 倒计时准确 | 误差 < 1秒 |
| 用户输入 | 键盘数字输入，回车确认 |
| 取消功能 | ESC 键可取消，返回 IDLE |

### 6.2 信号采集

| 指标 | 标准 |
|------|------|
| EAR 基线 | 7 秒自动采集，CQS >= 0.60 |
| 闭眼阈值 | ear_min < baseline_ear × 0.3 |
| 眯眼阈值 | baseline_ear × 0.75 > squint > ear_min |
| 头部姿态 | yaw/pitch 范围采集完整 |
| 眨眼校准 | 3 轮完成，误差 < 20% |

### 6.3 结果应用

| 指标 | 标准 |
|------|------|
| 阈值更新 | 校准完成后立即生效 |
| 持久化 | 保存到 SQLite |
| 启动恢复 | 下次启动可加载历史数据 |

### 6.4 用户体验

| 指标 | 标准 |
|------|------|
| 总时长 | < 90 秒 |
| 指导清晰 | 每阶段有明确文字提示 |
| 进度可见 | 当前阶段和剩余时间可见 |

---

## 七、实现文件清单

| 文件 | 内容 |
|------|------|
| `analyzer/user_calibration.py` | UserCalibrationManager + CalibrationCallbacks |
| `storage/models.py` | CalibrationSignal, BlinkCalibrationRound, CalibrationResult |
| `storage/db.py` | calibration 表 + blink_calibration_round 表 |
| `gui/overlay.py` | 校准 UI 方法 |
| `main.py` | 集成回调实现 |

---

## 八、工时估算

| 子任务 | 估时 |
|--------|------|
| T148a user_calibration.py | 2h |
| T148b models.py 新增数据模型 | 0.5h |
| T148c db.py 新增表 | 0.5h |
| T148d overlay.py 校准 UI | 2h |
| T148e main.py 集成 | 1h |
| T148f 单元测试 | 0.5h |
| **合计** | **6.5h** |

---

## 九、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-05-31 | 初始设计：事件驱动架构，6阶段校准流程 |
