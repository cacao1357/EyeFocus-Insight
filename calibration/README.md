# `calibration/` — 用户辅助校准子系统

> **v4.2 范本** | 测试覆盖 198 个 | 状态：✅ 活跃（默认） | CQS=1.00 真机验收

**职责**：用户开机引导校准。**模块隔离原则** — 自有摄像头、自有 cv2 窗口、自有音频反馈（beep + TTS）、自有状态机编排。**单接口 `calibration.run()` 与主程序连接**。

> 📐 **设计范本**：`docs/MODULE_INTERFACES.md` §2.3 锁定本模块为 v4.2 范式参照。新增模块应遵循 6 条硬约束（单入口 / 独立运行 / 资源自有 / dataclass 契约 / Optional 不抛 / 不依赖 main.py）。

## 公共 API（`__init__.py` 单入口）

```python
from calibration import run, CalibrationConfig, CalibrationResult

# 主入口 — 一行调用
result: Optional[CalibrationResult] = run(
    session_id="abc-123",
    config=CalibrationConfig(audio_enabled=True, auto_baseline_seconds=7.0),
    db=database_manager,  # 可选
)
if result is None:
    # 用户取消 / 失败 / 异常 — 严格 Optional 契约（X1）
    ...
else:
    print(f"EAR baseline: {result.signal.ear_mean:.4f}")
    print(f"CQS: {result.cqs:.2f}")
```

## 子结构

| 子目录 | 职责 |
|--------|------|
| `phases/` | 5 阶段状态机（auto_baseline / blink_count / closed_eyes / head_pose / squint）|
| `ui/` | 屏幕数字键盘 + panel 渲染（上下分屏：视频 480 + UI 240）|
| `audio/` | 蜂鸣（beep.py）+ 中文 TTS（tts.py，pyttsx3 封装，失败降级）|
| `tests/` | 198 测试（unit 14 + integration 4 + spike 2）— `python -m pytest calibration/tests/` |

| 顶层文件 | 职责 |
|---------|------|
| `__init__.py` | 公共 API：`run()` / `CalibrationResult` / `CalibrationConfig` |
| `__main__.py` | `python -m calibration` 独立运行入口（带诊断日志落盘）|
| `config.py` | `CalibrationConfig` dataclass（41 行）|
| `flow.py` | `CalibrationFlow` 状态机核心（474 行）|
| `input_handler.py` | 鼠标 + 键盘 + IME 兼容（Windows 微软拼音 拦截兜底）|
| `result.py` | `CalibrationResult` / `CalibrationSignal` / `BlinkCalibrationRound` 数据契约 |
| `_ime.py` | IME 内部辅助（22 行）|

## 独立运行

```bash
python -m calibration              # 默认 session_id="standalone_test"
python -m calibration my_session   # 自定义 session
```

## 集成到 main.py

```python
import calibration as calibration_module

# main.py:1227 调一行
result = calibration_module.run(session_id, config, db)
if result is not None:
    self._apply_v4_2_calibration_result(result)
```

## 测试入口

```bash
pytest calibration/tests/unit/ -v                    # 187 单元（0.9s）
pytest calibration/tests/integration/ -v --durations=5  # 11 集成（~44s，含真摄像头）
```

> ⚠️ **集成测试卡顿**：`test_face_detection_call.py::test_extract_metrics_with_real_detector_face_detected_true` 单测 43s（真摄像头 + MediaPipe 加载）。建议 CI 单独跑，不阻塞 PR。

## 关键设计（v4.2 范式）

| ID | 决策 | 说明 |
|----|------|------|
| A1 | 接口边界 | 模块自有摄像头（main.py release → module acquire → release）|
| L1 | UI 布局 | 上下分屏（视频 480 + UI 240），无重叠 |
| S2 | 音频反馈 | beep + 中文 TTS（pyttsx3 ≥ 2.90，SAPI 失败时降级 beep-only）|
| C2 | 用户控制权 | 鼠标点屏幕数字键盘主导 + 键盘加速 + IME 兼容 |
| X1 | 失败契约 | `Optional[CalibrationResult]`，失败/取消**返回 None 不抛异常** |

## 关联文档

- 设计 spec：`docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`（已实施）
- 实施 plan：`docs/superpowers/plans/2026-06-02-calibration-redesign-plan.md`
- 真机验收：`docs/REAL_MACHINE_TEST_v4.3.md`（CQS=1.00）
- 失败教训：`docs/old_schemes/T148_USER_CALIBRATION_DESIGN_v1.0.md`（T148 旧方案）
