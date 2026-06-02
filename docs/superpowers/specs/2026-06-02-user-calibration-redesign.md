# EyeFocus Insight — 用户辅助校准模块重设计

> **Spec 编号**：2026-06-02-user-calibration-redesign
> **日期**：2026-06-02
> **作者**：D1 + Brainstorm 会话产出
> **状态**：待评审 → 待写入 PROJECT_PLAN/PHASE_PLAN → 待执行
> **严重度**：🔴 严重 — 替代 T148（实测全部失效），独立模块开发

---

## 0. 背景与触发原因

### 0.1 原 T148 用户辅助校准的实测结论

2026-06-02 用户实测后明确反馈："**功能完全实现不了，需要列为严重问题**"。

代码审计 + 用户实测合并发现 **7 个核心问题**（全部已确认）：

| # | 等级 | 问题 | 代码根因 / 用户感受 |
|---|------|------|---------------------|
| 1 | 🔴 致命 | 眨眼检测一直 0 | `BLINK_COUNTING` 阶段在 `tick()` 内采样 EAR，节流 ≥ 1 秒；眨眼仅 100-400ms → 漏检 95%+ |
| 2 | 🔴 严重 | UI 与视频重叠 | 单 cv2 窗口，半透明 UI 条覆盖在 640×480 视频底部 80-100px → 遮挡用户脸/上半身 |
| 3 | 🔴 根本性 UX | 闭眼用户失明 | 阶段 1（闭眼 5s）→ 阶段 2（睁眼 3s）切换无任何音频提示，用户闭眼看不见 UI 倒计时 |
| 4 | 🟡 严重 UX | 头部姿态无指令 | HEAD_UP/DOWN/LEFT/RIGHT 4 子阶段切换无独立 UI/TTS 提示，用户什么也没做 → 数据全是垃圾 |
| 5 | 🟡 严重 UX | 全程无有效反馈 | 没有"采集了多少数据 / 做得对不对 / 阶段成功了吗"反馈 → 用户"对着空气表演" |
| 6 | 🟡 严重 UX | 节奏快 + 无控制权 | 纯定时器驱动，无"准备好再开始 / 暂停 / 重试 / 跳过" → 用户被推着走 |
| 7 | 🟡 严重 UX | 结束无及时退出 | 校准完成后停留在原录像界面，无明确"校准已完成"反馈，用户不知是否进入主监测 |

### 0.2 修复范围决策（已确认）

**完整重设计 + 模块隔离**：
- 推倒原 T148（`analyzer/user_calibration.py` + `gui/overlay.py` 校准 UI 部分）
- 新建 `calibration/` 独立模块，主程序不再持有校准逻辑
- 通过单一接口 `calibration.run(session_id) → Optional[CalibrationResult]` 连接
- 摄像头资源由模块在校准期间独占（acquire-release 切换）

### 0.3 核心设计决策一览（已逐项确认）

| ID | 决策 | 选项 |
|----|------|------|
| **A** | 修复范围 | 完整重设计 + 模块隔离 |
| **A1** | 接口边界 | 模块自有摄像头，主程序 release → calibration.run() → re-acquire |
| **L1** | UI 布局 | 上下分屏（视频 640×480 上 + UI 区 640×240 下）|
| **S2** | 音频反馈 | 蜂鸣（winsound）+ 中文 TTS（pyttsx3）双轨 |
| **C2** | 用户控制权 | 鼠标点击主导 + 键盘仅用于数字输入（受 IME 影响时屏幕数字键盘兜底）|
| **F1** | 反馈机制 | 实时数据计数 + 阶段结束摘要 + 失败诊断 |
| **P2** | 阶段结构 | 5 阶段约 2 分钟（合并睁眼回升 + 头部姿态拆 4 子阶段 + 眨眼 2 轮）|
| **E1** | 结束过渡 | 总结页 + 用户确认才返回 |
| **X1** | 失败/取消契约 | `Optional[CalibrationResult]` — 严格契约：成功才返回完整结果，取消/失败返回 None |

---

## 1. 架构总览

### 1.1 模块边界

```
┌──────────────────────────────────────────────────────────────┐
│  主程序 main.py（不变）                                        │
│  - 摄像头采集 / FrameProcessor / FocusOverlay / DB / Reporter │
│                                                                │
│  启动时校准接入点（唯一改动点）：                              │
│    self._cap.release()                                         │
│    result = calibration.run(session_id, db=self._db)           │
│    self._cap = cv2.VideoCapture(0)                             │
│    if result:                                                  │
│        self._eye_detector.apply(result)                        │
│        self._fatigue_analyzer.apply(result)                    │
│        self._head_pose.apply(result)                           │
│    else:                                                       │
│        logger.info("用户取消校准，使用默认基线")               │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼  Python import boundary
┌──────────────────────────────────────────────────────────────┐
│  calibration/  （新独立模块）                                   │
│  ─────────                                                    │
│  __init__.py                                                  │
│  __main__.py                                                  │
│  flow.py                                                      │
│  phases/                                                      │
│    auto_baseline.py / closed_eyes.py / squint.py /            │
│    head_pose.py / blink_count.py                              │
│  ui/                                                          │
│    layout.py / panel.py                                       │
│  audio/                                                       │
│    beep.py / tts.py                                           │
│  input_handler.py                                             │
│  result.py                                                    │
│  config.py                                                    │
│  _ime.py                  (可选 Win32 IME 禁用兜底)            │
│  tests/                                                       │
│    unit/  integration/  spike/                                │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 公共 API（唯一对外接口）

```python
# calibration/__init__.py

def run(
    session_id: str,
    config: Optional[CalibrationConfig] = None,
    db: Optional[DatabaseManager] = None,
) -> Optional[CalibrationResult]:
    """运行完整校准流程。

    阻塞调用 — 接管摄像头 + 显示自己的 cv2 窗口 + 等待用户完成。

    Returns:
        CalibrationResult: 全 5 阶段完成 + 用户在总结页按 SPACE/点击确认
        None: 用户取消、阶段失败放弃、模块崩溃
    """
```

### 1.3 隔离收益

| 项 | T148 原架构 | 新架构 |
|----|-----------|--------|
| 修改影响 | main.py + analyzer + gui 三处联动 | 仅 calibration/ 子包 |
| 独立运行 | ❌ | ✅ `python -m calibration` |
| 独立测试 | 半依赖 mock main.py | ✅ 完整 pipeline 无外部依赖 |
| 回滚 | git revert + 主程序联动 | 改 main.py 一行 import 即回退 |
| 现有 284 测试影响 | 必须重测 | 零影响（直到最后集成步骤）|

---

## 2. 组件设计

### 2.1 `flow.py` — 流程编排器

- 持有 5 个阶段实例 + 1 个摄像头 + UI/Audio/Input 子系统
- 单线程主循环（每帧 ~33ms），状态机驱动
- 关键接口：
  ```python
  class CalibrationFlow:
      def __init__(self, config: CalibrationConfig): ...
      def run(self) -> Optional[CalibrationResult]: ...
  ```

### 2.2 `phases/*.py` — 5 个阶段实现

每阶段实现统一接口：

```python
class Phase(ABC):
    name: str
    duration_seconds: float
    tts_intro: str
    tts_complete: str

    def reset(self) -> None: ...
    def feed_frame(self, ear, yaw, pitch, timestamp) -> None: ...  # 每帧调用 ← BUG 1 修复点
    def get_live_feedback(self) -> LiveFeedback: ...
    def is_complete(self, elapsed_sec) -> bool: ...
    def evaluate(self) -> PhaseResult: ...
```

5 个具体类：

| 阶段 | 类 | 时长 | 数据采集 | 关键评估 |
|------|----|------|---------|---------|
| 0 | `AutoBaselinePhase` | 7s | EAR/yaw/pitch 均值 | face_detected_ratio ≥ 0.7, ear_cv ≤ 0.15 |
| 1 | `ClosedEyesPhase` | 8s（5s 闭眼 + 3s 自动验证回升） | ear_min | ear_min ≤ baseline_ear × 0.5 |
| 2 | `SquintPhase` | 8s | ear_mid | baseline_ear × 0.75 ≥ ear_mid ≥ ear_min × 1.2 |
| 3 | `HeadPosePhase`（含 4 `HeadDirectionSubPhase`）| 12s（每方向 3s）| yaw/pitch 范围 | 每方向 \|偏转\| ≥ 10° |
| 4 | `BlinkCountPhase` | 30s（2 轮 × 15s + 输入）| 每轮 detected_blinks | 用户输入 ∈ [5, 60] |

**严格约束**：阶段类**不知道** UI / 音频 / 键盘存在 — 纯数据采集 + 评估。

### 2.3 `ui/layout.py` — 上下分屏拼合

`cv2.vconcat([camera_frame_640x480, ui_panel_640x240]) → 640×720 final`。

### 2.4 `ui/panel.py` — UI 区渲染

按 FlowState 渲染对应布局，中文文字用 PIL（继承 `gui/overlay.py:put_chinese_text` 函数）：

| FlowState | UI 区内容 | 按钮 |
|-----------|----------|------|
| `WAITING_TO_START_PHASE` | 阶段名 + 指令 | [开始] [取消] |
| `PHASE_RUNNING` | 阶段名 + 进度条 + 倒计时 + 实时反馈 | [暂停] [取消] |
| `PHASE_SUMMARY_SUCCESS` | "✓ 完成" + 采集摘要 | [继续] [重做] [取消] |
| `PHASE_SUMMARY_FAILED` | "✗ 失败" + 失败诊断 | [重做] [跳过] [取消] |
| `BLINK_INPUT_AWAITING` | 检测到 N 次 + 屏幕数字键盘 | [0-9] [⌫] [确认] [取消] |
| `FINAL_SUMMARY` | 全部基线值 + CQS | [继续 → 主监测] [重新校准] [退出] |

按钮样式：
- Primary（绿色）— 主推荐操作
- Danger（红色）— 取消类
- Neutral（灰色）— 次要操作

### 2.5 `audio/beep.py` — 蜂鸣声

```python
def phase_start(): winsound.Beep(1000, 200)
def phase_success(): winsound.Beep(1500, 300)
def phase_failed(): winsound.Beep(300, 800)
def countdown_tick(): winsound.Beep(600, 100)
def calibration_complete(): winsound.Beep(800, 200); winsound.Beep(1200, 400)
```

非 Windows 环境时全部 no-op + 日志警告。

### 2.6 `audio/tts.py` — 中文语音

```python
class TTS:
    def __init__(self):
        self._engine = pyttsx3.init()
        self._engine.setProperty('rate', 180)
        # 自动选中文音色
    def say(self, text: str) -> None:  # 异步，不阻塞主循环
        threading.Thread(target=self._engine_say, args=(text,), daemon=True).start()
    def shutdown(self) -> None: ...
```

TTS 初始化失败时降级为只蜂鸣 + UI 显示警告。

### 2.7 `input_handler.py` — 鼠标 + 键盘统一输入

**主输入路径：鼠标点击**（彻底消除 Windows IME 影响）。

```python
class UIAction(Enum):
    NONE, PROCEED, RETRY_PHASE, SKIP_PHASE, CANCEL,
    DIGIT, BACKSPACE, SUBMIT

class InputHandler:
    def __init__(self, window_name: str): ...
    def register_buttons(self, buttons: list[Button]) -> None: ...
    def poll(self, state: FlowState) -> tuple[UIAction, Optional[str]]: ...
```

**键盘只作可选加速**：
- `BLINK_INPUT_AWAITING` 状态：数字 0-9、Backspace、Enter（英文输入法时生效；中文 IME 时屏幕数字键盘兜底）
- 其他状态：仅 ESC 作为紧急取消兜底

**Win32 IME 禁用兜底**（`_ime.py`，失败也无所谓）：
```python
def try_disable_ime(window_name: str) -> bool:
    try:
        # ctypes 调 ImmAssociateContext(hwnd, NULL)
        return True
    except Exception:
        return False
```

### 2.8 `result.py` — 数据契约

```python
@dataclass(frozen=True)
class CalibrationResult:
    session_id: str
    timestamp: datetime
    signal: CalibrationSignal
    blink_rounds: List[BlinkCalibrationRound]
    final_adjustment_factor: float
    final_blink_threshold: float
    final_squint_threshold: float
    baseline_blink_rate: float    # ← T148 修复链路（v4.0 已接通，保留契约）
    cqs: float                    # 整体校准质量分
    is_accepted: bool             # 用户总结页确认
    notes: str = ""
```

字段冻结：实施前 review 完毕，开发期间不得修改字段。

### 2.9 `config.py` — 阶段时长 / 阈值

```python
@dataclass
class CalibrationConfig:
    # 阶段时长
    auto_baseline_seconds: float = 7.0
    closed_eyes_seconds: float = 5.0
    open_eyes_verify_seconds: float = 3.0
    squint_seconds: float = 8.0
    head_direction_seconds: float = 3.0   # 每个方向
    blink_round_seconds: float = 15.0
    blink_rounds_count: int = 2

    # 阈值参数
    closed_eyes_min_ratio: float = 0.5    # ear_min ≤ baseline × 此值
    squint_baseline_ratio: float = 0.75
    head_direction_min_degrees: float = 10.0
    blink_count_min: int = 5
    blink_count_max: int = 60

    # UI 参数
    ui_panel_height_px: int = 240
    button_height_px: int = 50
    button_padding_px: int = 10

    # 音频参数
    tts_rate: int = 180
    audio_enabled: bool = True
```

---

## 3. 数据流与状态机

### 3.1 模块主循环（伪代码）

```
while not done:
    ret, frame = cap.read()
    face_result = face_mesh.detect(frame)
    if face_result.detected:
        ear, yaw, pitch = extract_metrics(face_result)
    else:
        ear, yaw, pitch = None, None, None

    if state in [PHASE_RUNNING]:
        current_phase.feed_frame(ear, yaw, pitch, time.time())  # ← BUG 1 修复

    live = current_phase.get_live_feedback() if state == PHASE_RUNNING else None

    if state == PHASE_RUNNING and current_phase.is_complete(elapsed):
        result = current_phase.evaluate()
        transition_to(PHASE_SUMMARY_SUCCESS if result.success else PHASE_SUMMARY_FAILED)
        audio.beep_phase_success() / beep_phase_failed()
        tts.say(phase.tts_complete) / tts.say(result.failure_diagnosis)

    panel_img = panel.render(state, current_phase, live)
    composed = layout.compose(frame, panel_img)
    cv2.imshow(WINDOW, composed)

    input_handler.register_buttons(panel.get_buttons(state))
    action, digit = input_handler.poll(state)
    handle_action(state, action, digit)
```

### 3.2 状态机

```
IDLE
  ↓ run()
WAITING_TO_START_PHASE[i]   →  PHASE_RUNNING[i]   →  PHASE_SUMMARY_SUCCESS[i]
                                                      └─ 继续 → WAITING_TO_START_PHASE[i+1]
                                                      └─ 重做 → PHASE_RUNNING[i]
                                                   →  PHASE_SUMMARY_FAILED[i]
                                                      └─ 重做 → PHASE_RUNNING[i]
                                                      └─ 跳过 → WAITING_TO_START_PHASE[i+1]（默认值）
                                                      └─ 取消 → CANCELLED

特殊：阶段 4 BlinkCount
  PHASE_RUNNING[4_round_1] → BLINK_INPUT_AWAITING[1] → PHASE_RUNNING[4_round_2]
    → BLINK_INPUT_AWAITING[2] → PHASE_SUMMARY_SUCCESS[4]

最后：
  ... → FINAL_SUMMARY
        ├─ 继续 → DONE → return CalibrationResult
        ├─ 重新校准 → WAITING_TO_START_PHASE[0]（全部重置）
        └─ 退出 → CANCELLED → return None
```

### 3.3 音频事件时序

| 触发 | 反馈 |
|------|------|
| 进入 `WAITING_TO_START_PHASE[i]` | TTS 念阶段引导（"按开始按钮，准备闭眼校准"）|
| 用户点 "开始" 进入 `PHASE_RUNNING[i]` | beep_phase_start + TTS 念主指令（"请闭眼"）|
| 倒计时最后 3 秒 | beep_countdown_tick 每秒一次 |
| `is_complete` + success | beep_phase_success + TTS 念 `tts_complete` |
| `is_complete` + failed | beep_phase_failed + TTS 念失败诊断 |
| 进入 `BLINK_INPUT_AWAITING` | TTS 念"请输入你眨眼次数" |
| 进入 `FINAL_SUMMARY` | beep_calibration_complete + TTS 念"校准完成" |

**BUG 3 修复点**：阶段 1 闭眼 → 阶段 2 验证回升时，TTS 念 "现在可以睁眼了"，用户闭眼也能听到。

### 3.4 摄像头资源切换时序

```
主程序                     calibration/
─────                     ─────────────
cap.release()      ─→
                          VideoCapture(0)     # 模块拿
                          <主循环 ~2 分钟>
                          cap.release()       # 模块释放
                   ←─    return CalibrationResult
VideoCapture(0)
（继续主监测）
```

切换间隙 ~500ms × 2 次 = 1 秒，用户感觉"摄像头快门闪一下"。

---

## 4. 错误处理与边界

### 4.1 启动期失败

| 失败场景 | 处理 |
|---------|------|
| `cv2.VideoCapture(0)` 失败 | TTS 念"无法启动摄像头" + cv2 错误模态 → return None |
| MediaPipe 模型缺失 | 与 main.py 一致：尝试下载，失败 → return None |
| pyttsx3 init 失败 | 降级 beep-only + UI 警告 |
| winsound 不可用 | 降级 TTS-only + 日志警告 |
| TTS + beep 都失败 | UI 强制 warning + 阶段时长 +50% 补偿 |

### 4.2 运行期错误

| 失败场景 | 策略 |
|---------|------|
| `cap.read()` 单次失败 | 跳过该帧；连续 30 帧 → UI 警告 |
| 人脸未检测到 | feed_frame(None,...) 阶段内部丢弃；UI 显示"未检测到人脸" |
| 单阶段连续 3 次重做失败 | 禁用"重做"按钮，仅留"跳过"/"取消" |
| TTS 调用阻塞 | 全 daemon 线程异步，主循环不阻塞 |
| 用户关窗（点 X） | `cv2.getWindowProperty` 检测，等同 CANCEL |
| MediaPipe 推理异常 | 单帧 face_detected=False；连续 50 帧 → return None |

### 4.3 阶段失败诊断

| 阶段 | 失败条件 | 诊断（给用户）|
|------|---------|--------------|
| 自动基线 | face_detected_ratio < 0.7 | "人脸检测不稳定，请确认摄像头对准你的脸" |
| 自动基线 | ear_cv > 0.15 | "请保持自然睁眼，眨眼请等校准后" |
| 闭眼 | ear_min > baseline × 0.5 | "似乎没有完全闭眼，请用力闭眼后重做" |
| 眯眼 | 与 baseline 或 ear_min 太接近 | "眯眼幅度不够，请眼睛稍开一条缝" |
| 头部姿态 | 任一方向 < ±10° | "[方向] 转动幅度不够，请大一点动作" |
| 眨眼计数 | 用户输入 ∉ [5, 60] | "次数 [X] 不在合理范围（5-50），请重做" |

### 4.4 取消（CANCEL）资源清理

```python
def _on_cancel(self):
    self._tts.say("已取消校准")
    self._cap.release()
    cv2.destroyWindow(self._window_name)
    self._tts.shutdown()
    self._db_partial_save_if_any()  # 已完成阶段存 "cancelled" 记录留底
    return None
```

### 4.5 模块崩溃兜底

```python
def run(session_id, config, db) -> Optional[CalibrationResult]:
    try:
        return CalibrationFlow(config, db, session_id).run()
    except Exception:
        logger.exception("校准模块崩溃")
        try: cv2.destroyAllWindows()
        except: pass
        return None  # 主程序按"未校准"处理
```

**关键**：模块崩溃**不抛**异常到主程序——总返回 None。

### 4.6 DB 写入失败

- 校准成功 + DB 写失败 → 仍返回 CalibrationResult；DB 失败仅日志警告
- 校准取消 + 部分数据 DB 写失败 → 忽略

---

## 5. 测试策略

### 5.1 文件结构

```
calibration/tests/
├── unit/                       # mock 一切外部依赖
│   ├── test_result.py / test_config.py
│   ├── test_auto_baseline.py / test_closed_eyes.py / test_squint.py /
│   │   test_head_pose.py / test_blink_count.py
│   ├── test_panel.py / test_layout.py
│   ├── test_input_handler.py / test_audio_beep.py / test_audio_tts.py
│   └── test_flow.py
├── integration/                # 多组件协同
│   ├── test_phase_audio_ui.py / test_cancel_flow.py
│   ├── test_blink_input.py / test_module_to_main.py
└── spike/                      # 真摄像头手工/半自动
    ├── spike_single_phase.py / spike_full_flow.py
```

### 5.2 覆盖率门禁

| 文件 | 最低 |
|------|------|
| result.py / input_handler.py | **95%** |
| config.py / phases/* / layout.py | **90%** |
| flow.py / audio/* | **80-85%** |
| panel.py | **75%** |
| **整体** | **≥ 85%** |

### 5.3 7 个 BUG 回归测试（必含）

每个原 BUG 必须有对应回归测试 + 用户实测验收：

| BUG | 回归测试函数（示例）|
|-----|-------------------|
| 1 | `test_blink_phase_detects_30hz_blinks` — 合成 30fps EAR 序列 + 5 个 200ms 眨眼 → 期望 5 次检出 |
| 2 | `test_panel_does_not_overlap_video_region` — 验证 ui 输出图像与摄像头帧不在同一 Y 范围 |
| 3 | `test_closed_eyes_phase_tts_fires_at_open_signal` — mock TTS 验证 "睁眼" 关键词出现 |
| 4 | `test_head_pose_each_subphase_has_tts` — 4 方向各自 TTS 出现 "抬头/低头/向左/向右" |
| 5 | `test_phase_summary_contains_collected_data` — 阶段结束摘要含采集计数和质量分 |
| 6 | `test_phase_waits_for_user_start_click` — 模拟 10s 不点击 → 仍在 WAITING_TO_START |
| 7 | `test_final_summary_blocks_until_user_confirms` — 模拟 10s 不点击 → 仍在 FINAL_SUMMARY |
| IME | `test_blink_input_works_with_mouse_only` — 完全鼠标点屏幕键盘可输入 |

### 5.4 Spike 真机验证（必跑）

```
S-CAL-1 单阶段 spike
S-CAL-2 全流程 spike
S-CAL-3 IME 实战（微软拼音激活下用鼠标完成）
S-CAL-4 音频降级（pyttsx3 unload 后跑全流程）
S-CAL-5 集成实战（替换 main.py import 后跑完整启动 → 校准 → 主监测）
```

### 5.5 用户验收清单（每条必过）

```
□ BUG 1：眨眼计数轮检测到非零数字
□ BUG 2：校准 UI 完全不遮挡视频区
□ BUG 3：闭眼时听到 TTS "现在可以睁眼了"
□ BUG 4：头部姿态 4 段独立 TTS
□ BUG 5：每阶段进行中可见实时计数 + 结束有摘要
□ BUG 6：每阶段需点击"开始"才推进
□ BUG 7：校准完成有明确反馈 + 用户主动确认
□ IME：微软拼音激活下仍可完成全流程
```

---

## 6. 保守开发策略（X 章节）

### 6.1 严重风险标注（写入 PROJECT_PLAN v4.2）

```
R27 — T148 校准模块重设计（calibration/）属高风险重构
       等级：🔴 严重
       应对：保守开发策略 + 每子任务必带测试门禁 + D1 强制 review
```

### 6.2 子任务测试门禁（写入 PHASE_PLAN）

每个子任务采用 **"实现 → 测试 → 门禁 → 下一步"** 严格循环：

| ID | 子任务 | 门禁 |
|----|--------|------|
| T-CAL-01 | result.py 数据契约 | 测试 ≥ 95% + 字段冻结 review |
| T-CAL-02 | config.py 配置 | 测试 ≥ 90% + 默认值验证 |
| T-CAL-03 | phases/auto_baseline.py | 测试 ≥ 90% + spike 真机验证 |
| T-CAL-04 | phases/closed_eyes.py | 测试 ≥ 90% + 真机听到 TTS |
| T-CAL-05 | phases/squint.py | 测试 ≥ 90% |
| T-CAL-06 | phases/head_pose.py（4 子阶段）| 测试 ≥ 85% + 4 TTS 真机听到 |
| T-CAL-07 | phases/blink_count.py | 测试 ≥ 85% + 真机眨眼检出 |
| T-CAL-08 | ui/layout.py | 测试 ≥ 90% |
| T-CAL-09 | ui/panel.py | 测试 ≥ 75% + 每状态截图 review |
| T-CAL-10 | input_handler.py | 测试 ≥ 95% + IME 实战 |
| T-CAL-11 | audio/beep.py + audio/tts.py | 测试 ≥ 80-85% + 真机听音 |
| T-CAL-12 | flow.py 编排 | 测试 ≥ 80% + spike 全流程 |
| T-CAL-13 | `__main__.py` 独立运行 | `python -m calibration` 全流程通过 |
| T-CAL-14 | main.py 集成（**最后一步**）| 原 284 测试 0 破 + 用户 7-BUG 实测验收 |

### 6.3 任何门禁未过 → 暂停

- 子任务测试覆盖率不达标 → 暂停，不开新子任务
- spike 真机发现新问题 → 暂停，回 brainstorm
- 用户实测发现 BUG 1-7 任一仍存在 → 回滚到 BUG 修复阶段

### 6.4 集成时机锁定

**main.py 集成（T-CAL-14）必须放在最后**。前 13 个子任务全部完成且通过门禁后才动 main.py。

- 现有 284 测试始终绿色，直到最后一步
- 集成失败回滚成本最小（仅 main.py 几行 import 撤销）

---

## 7. 实现文件清单

| 文件 | 内容 | 估行数 |
|------|------|--------|
| `calibration/__init__.py` | 暴露 `run()` API | 30 |
| `calibration/__main__.py` | `python -m calibration` 入口 | 30 |
| `calibration/flow.py` | 主流程编排 | 350 |
| `calibration/phases/auto_baseline.py` | 阶段 0 | 100 |
| `calibration/phases/closed_eyes.py` | 阶段 1 | 80 |
| `calibration/phases/squint.py` | 阶段 2 | 70 |
| `calibration/phases/head_pose.py` | 阶段 3 + 4 子阶段 | 150 |
| `calibration/phases/blink_count.py` | 阶段 4（含 2 轮 + 输入）| 150 |
| `calibration/ui/layout.py` | vconcat 拼合 | 50 |
| `calibration/ui/panel.py` | UI 区渲染 + 按钮 | 350 |
| `calibration/audio/beep.py` | winsound 封装 | 60 |
| `calibration/audio/tts.py` | pyttsx3 封装（异步）| 80 |
| `calibration/input_handler.py` | 鼠标 + 键盘统一 | 130 |
| `calibration/_ime.py` | Win32 IME 禁用兜底（可选）| 50 |
| `calibration/result.py` | CalibrationResult dataclass | 80 |
| `calibration/config.py` | CalibrationConfig dataclass | 60 |
| `calibration/tests/unit/` | 14 个测试文件 | ~1500 |
| `calibration/tests/integration/` | 4 个集成测试 | ~400 |
| `calibration/tests/spike/` | 2 个 spike 脚本 | ~200 |
| **合计模块代码** | | **~2270 行** |
| **合计测试代码** | | **~2100 行** |

---

## 8. 依赖变更

新增依赖（生产端 pip 离线可装）：

| 包 | 版本 | 用途 |
|----|------|------|
| `pyttsx3` | ≥ 2.90 | 中文 TTS（Windows SAPI 后端）|

`winsound` 是 Python 内置（Windows-only），无需新增。

---

## 9. 删除/废弃

实施 T-CAL-14（main.py 集成）成功后立即归档/删除：

| 文件 | 处理 |
|------|------|
| `analyzer/user_calibration.py` | 移至 `docs/old_schemes/legacy/user_calibration_v1.py.txt` |
| `gui/overlay.py` 中校准 UI 方法 | 删除（show_calibration_phase, _draw_calibration_full 等约 200 行）|
| `main.py` 中 `CalibrationFlowCallbacks` 类 | 删除 |
| `main.py` 中 `CalibrationCoordinator` 类 | 删除 |
| `storage/db.py` 中 calibration 表 | 保留（与新 result.py 兼容）|

---

## 10. 验收门禁汇总

| 阶段 | 门禁 |
|------|------|
| 单子任务完成 | 测试覆盖率达标 + spike（如有）真机通过 + D1 review approve |
| 全部子任务完成 | 整体 ≥ 85% 覆盖 + 5 个 spike 全跑通 |
| 集成 | 原 284 测试 0 破 + 7 个用户验收点全过 |
| 最终签收 | 用户在微软拼音 IME 激活下能完整跑通校准 → 主监测 |

---

## 11. 与现有规划文档的同步

本 spec 通过后，立即同步以下文档（必须在执行前完成）：

| 文档 | 变更 |
|------|------|
| `PROJECT_PLAN.md` v4.1 → **v4.2** | §1.6 新增决策 #11；§2 模块图加 `calibration/`；§4 加 `pyttsx3` 依赖；§12 风险表加 R27；§13 验收清单加 AC31-AC38；§15 任务清单加 T-CAL-01 ~ T-CAL-14 |
| `PHASE1_PLAN.md` v1.7 → **v1.8** | 新增 §2.15 calibration 模块重设计任务清单 + 保守开发策略章节 |
| `PHASE2_PLAN.md` v1.0 → **v1.1** | 注明 calibration 重设计应在 Phase 2 早期完成（早于 insights spike），因 main.py 接入点改动影响后续测试 |
| 归档 | `PROJECT_PLAN.md` v4.1 → `docs/old_schemes/PROJECT_PLAN_v4.1.md` |

---

## 12. 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-06-02 | 初稿 — Brainstorm 会话产出（A/A1/L1/S2/C2/F1/P2/E1/X1 + IME 鼠标方案 + 保守开发策略）|

---

> **下一步**：spec 自查 → 你审 spec → 写入 PROJECT_PLAN/PHASE_PLAN → 等你说"执行" → 调 writing-plans skill。
