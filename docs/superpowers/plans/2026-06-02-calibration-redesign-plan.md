# Calibration 模块重设计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现独立 `calibration/` 子包，取代失效的 T148 用户辅助校准模块。模块自有摄像头 + 自有 UI 窗口 + 自有音频反馈，通过单一接口 `calibration.run(session_id) → Optional[CalibrationResult]` 与主程序连接。

**Architecture:** 上下分屏（视频 640×480 + UI 240px）+ 鼠标点击主导（屏幕数字键盘消除 Windows IME）+ 蜂鸣 + 中文 TTS（pyttsx3）+ 5 阶段 ~2 分钟 + 用户控制（SPACE/重做/跳过/取消）+ 总结页用户确认 + 严格 Optional 契约。

**Tech Stack:** Python 3.12 / OpenCV / MediaPipe / pyttsx3 (新增) / winsound (Windows 内置) / pytest

**保守开发策略：** 每子任务测试门禁未过不开新子任务。main.py 集成（T-CAL-14）放最后，前 13 子任务全过门禁才动 main.py。任一门禁未过 → 暂停 + 回滚到上一 commit。

**Spec 参考：** `docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`

---

## 文件结构

本计划创建以下新文件（按依赖顺序）：

```
calibration/
├── __init__.py                          # T-CAL-13 实现（公共 API）
├── __main__.py                          # T-CAL-13（独立运行入口）
├── result.py                            # T-CAL-01（数据契约，frozen=True）
├── config.py                            # T-CAL-02（配置 dataclass）
├── _ime.py                              # T-CAL-10（Win32 IME 兜底）
├── input_handler.py                     # T-CAL-10
├── flow.py                              # T-CAL-12（编排）
├── phases/
│   ├── __init__.py                      # T-CAL-03 创建
│   ├── base.py                          # T-CAL-03（Phase ABC）
│   ├── auto_baseline.py                 # T-CAL-03
│   ├── closed_eyes.py                   # T-CAL-04
│   ├── squint.py                        # T-CAL-05
│   ├── head_pose.py                     # T-CAL-06
│   └── blink_count.py                   # T-CAL-07
├── ui/
│   ├── __init__.py                      # T-CAL-08 创建
│   ├── layout.py                        # T-CAL-08
│   └── panel.py                         # T-CAL-09
├── audio/
│   ├── __init__.py                      # T-CAL-11 创建
│   ├── beep.py                          # T-CAL-11
│   └── tts.py                           # T-CAL-11
└── tests/
    ├── __init__.py                      # T-CAL-01 创建
    ├── unit/
    │   ├── __init__.py                  # T-CAL-01 创建
    │   ├── test_result.py               # T-CAL-01
    │   ├── test_config.py               # T-CAL-02
    │   ├── test_phase_base.py           # T-CAL-03
    │   ├── test_auto_baseline.py        # T-CAL-03
    │   ├── test_closed_eyes.py          # T-CAL-04
    │   ├── test_squint.py               # T-CAL-05
    │   ├── test_head_pose.py            # T-CAL-06
    │   ├── test_blink_count.py          # T-CAL-07
    │   ├── test_layout.py               # T-CAL-08
    │   ├── test_panel.py                # T-CAL-09
    │   ├── test_input_handler.py        # T-CAL-10
    │   ├── test_audio_beep.py           # T-CAL-11
    │   ├── test_audio_tts.py            # T-CAL-11
    │   └── test_flow.py                 # T-CAL-12
    ├── integration/
    │   ├── __init__.py                  # T-CAL-12 创建
    │   ├── test_phase_audio_ui.py       # T-CAL-12
    │   └── test_cancel_flow.py          # T-CAL-12
    └── spike/
        ├── spike_single_phase.py        # T-CAL-13
        └── spike_full_flow.py           # T-CAL-13

main.py                                  # T-CAL-14（修改）
requirements.txt                         # T-CAL-11（追加 pyttsx3）
docs/old_schemes/legacy/                 # T-CAL-14（归档旧代码）
```

---

## 前置准备

### 工具与环境
- Python 3.12.4 + `.venv312` 虚拟环境（已就绪）
- pytest + pytest-cov（已在 requirements.txt）
- 真实摄像头（D1 笔记本，已验证）

### Git 准备
- 当前分支：`main`
- 工作起点：commit `5498a42` (A1/A2/A3 cleanup) 之后
- 每个 T-CAL 子任务**至少 1 个 commit**，规则："门禁过了才 commit，commit 后不允许跨任务"

### 测试基线冻结
开始 T-CAL-01 前，先确认：

```bash
.venv312/Scripts/python.exe -m pytest tests/ --tb=line -q
# Expected: 284 passed
```

如果 284 不全过，**立即停止**，先排查到全绿才能开始。

---

## Task T-CAL-01: result.py 数据契约（冻结字段）

**Goal:** 定义 `CalibrationResult` frozen dataclass + 辅助 dataclass。所有字段在本任务确定后**不允许修改**（其他任务依赖此契约）。

**Coverage gate:** ≥ 95%

**Files:**
- Create: `calibration/__init__.py` (空文件，标识包)
- Create: `calibration/result.py`
- Create: `calibration/tests/__init__.py` (空)
- Create: `calibration/tests/unit/__init__.py` (空)
- Create: `calibration/tests/unit/test_result.py`

### Step 1: 创建包结构（空 `__init__.py`）

- [ ] **Step 1.1: 创建空 `__init__.py` 文件**

```bash
mkdir -p calibration/tests/unit
touch calibration/__init__.py
touch calibration/tests/__init__.py
touch calibration/tests/unit/__init__.py
```

Windows bash 无 `mkdir`/`touch`，使用 Python：

```bash
.venv312/Scripts/python.exe -c "
import os
for d in ['calibration', 'calibration/tests', 'calibration/tests/unit']:
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, '__init__.py'), 'a').close()
print('OK')
"
```

Expected: `OK`

### Step 2: 编写失败测试

- [ ] **Step 2.1: 写 `calibration/tests/unit/test_result.py`**

```python
"""测试 CalibrationResult 数据契约 — 字段冻结、必填、类型。"""
import pytest
from dataclasses import FrozenInstanceError
from datetime import datetime

from calibration.result import (
    CalibrationResult,
    CalibrationSignal,
    BlinkCalibrationRound,
)


# ---------- CalibrationSignal ----------

def test_calibration_signal_fields():
    sig = CalibrationSignal(
        ear_mean=0.30,
        ear_min=0.08,
        ear_mid=0.22,
        yaw_mean=0.5,
        yaw_range=(-15.0, 18.0),
        pitch_mean=1.2,
        pitch_range=(-12.0, 10.0),
        glasses_mode=False,
        timestamp=1700000000.0,
    )
    assert sig.ear_mean == 0.30
    assert sig.yaw_range == (-15.0, 18.0)


def test_calibration_signal_is_frozen():
    sig = CalibrationSignal(
        ear_mean=0.30, ear_min=0.08, ear_mid=0.22,
        yaw_mean=0.0, yaw_range=(0.0, 0.0),
        pitch_mean=0.0, pitch_range=(0.0, 0.0),
        glasses_mode=False, timestamp=0.0,
    )
    with pytest.raises(FrozenInstanceError):
        sig.ear_mean = 0.99  # type: ignore[misc]


# ---------- BlinkCalibrationRound ----------

def test_blink_round_fields():
    r = BlinkCalibrationRound(
        round_index=1,
        duration_seconds=15,
        user_blink_count=10,
        program_blink_count=8,
        program_squint_count=2,
        error_rate=0.2,
        adjustment_factor=1.2,
    )
    assert r.round_index == 1
    assert r.adjustment_factor == 1.2


def test_blink_round_is_frozen():
    r = BlinkCalibrationRound(
        round_index=1, duration_seconds=15, user_blink_count=10,
        program_blink_count=8, program_squint_count=0,
        error_rate=0.2, adjustment_factor=1.0,
    )
    with pytest.raises(FrozenInstanceError):
        r.user_blink_count = 99  # type: ignore[misc]


# ---------- CalibrationResult ----------

def _make_signal():
    return CalibrationSignal(
        ear_mean=0.30, ear_min=0.08, ear_mid=0.22,
        yaw_mean=0.0, yaw_range=(-15.0, 15.0),
        pitch_mean=0.0, pitch_range=(-10.0, 10.0),
        glasses_mode=False, timestamp=1700000000.0,
    )


def test_calibration_result_full():
    r1 = BlinkCalibrationRound(
        round_index=1, duration_seconds=15, user_blink_count=10,
        program_blink_count=8, program_squint_count=0,
        error_rate=0.2, adjustment_factor=1.2,
    )
    res = CalibrationResult(
        session_id="s1",
        timestamp=datetime(2026, 6, 2, 10, 0, 0),
        signal=_make_signal(),
        blink_rounds=[r1],
        final_adjustment_factor=1.2,
        final_blink_threshold=0.27,
        final_squint_threshold=0.225,
        baseline_blink_rate=14.0,
        cqs=0.85,
        is_accepted=True,
    )
    assert res.session_id == "s1"
    assert res.is_accepted is True
    assert res.notes == ""  # default


def test_calibration_result_is_frozen():
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.80, is_accepted=True,
    )
    with pytest.raises(FrozenInstanceError):
        res.session_id = "s2"  # type: ignore[misc]


def test_calibration_result_default_notes_empty():
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.80, is_accepted=True,
    )
    assert res.notes == ""


def test_calibration_result_with_notes():
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.80, is_accepted=True,
        notes="用户跳过了眨眼计数",
    )
    assert res.notes == "用户跳过了眨眼计数"


def test_calibration_result_empty_blink_rounds_allowed():
    """跳过眨眼计数阶段时，blink_rounds 可为空。"""
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=[],
        final_adjustment_factor=1.0,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=15.0,  # 默认值
        cqs=0.80, is_accepted=True,
    )
    assert res.blink_rounds == []


def test_calibration_result_multi_rounds():
    rounds = [
        BlinkCalibrationRound(
            round_index=i, duration_seconds=15, user_blink_count=10,
            program_blink_count=8, program_squint_count=0,
            error_rate=0.2, adjustment_factor=1.2,
        )
        for i in (1, 2)
    ]
    res = CalibrationResult(
        session_id="s1", timestamp=datetime(2026, 6, 2),
        signal=_make_signal(), blink_rounds=rounds,
        final_adjustment_factor=1.2,
        final_blink_threshold=0.27, final_squint_threshold=0.225,
        baseline_blink_rate=14.0, cqs=0.85, is_accepted=True,
    )
    assert len(res.blink_rounds) == 2
    assert res.blink_rounds[0].round_index == 1
```

- [ ] **Step 2.2: 运行测试确认失败**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_result.py -v
```

Expected: 全部 FAIL，原因 `ModuleNotFoundError: No module named 'calibration.result'`

### Step 3: 实现 result.py

- [ ] **Step 3.1: 写 `calibration/result.py`**

```python
"""calibration/result.py — CalibrationResult 数据契约（冻结字段）

字段在 T-CAL-01 锁定后不允许修改。其他任务依赖这些类型。

设计依据：spec §2.8。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Tuple


@dataclass(frozen=True)
class CalibrationSignal:
    """单次校准采集到的所有信号统计。"""
    ear_mean: float            # 自然睁眼时 EAR 均值（基线）
    ear_min: float             # 闭眼时 EAR 最小值
    ear_mid: float             # 眯眼时 EAR 中间值
    yaw_mean: float            # 头部偏航均值（自然正视）
    yaw_range: Tuple[float, float]    # (左偏最大值, 右偏最大值)
    pitch_mean: float          # 头部俯仰均值
    pitch_range: Tuple[float, float]  # (仰角最大值, 俯角最大值)
    glasses_mode: bool         # 是否检测为戴眼镜
    timestamp: float           # 采集完成时间戳（unix epoch 秒）


@dataclass(frozen=True)
class BlinkCalibrationRound:
    """单轮眨眼计数校准数据。"""
    round_index: int           # 第几轮（1-based）
    duration_seconds: int      # 本轮时长（秒）
    user_blink_count: int      # 用户手动报告的眨眼次数
    program_blink_count: int   # 程序检测到的眨眼次数
    program_squint_count: int  # 程序检测到的眯眼次数
    error_rate: float          # (user - program) / user，正值=漏检，负值=误检
    adjustment_factor: float   # 本轮推导的阈值调整因子，clamp 到 [0.7, 1.3]


@dataclass(frozen=True)
class CalibrationResult:
    """完整校准结果 — 校准模块成功完成后返回给主程序的契约。

    严格契约（spec §决策 X1）：模块仅在用户完成全 5 阶段 + 总结页确认时返回此结果。
    取消/失败时模块返回 None，不返回部分结果。
    """
    session_id: str
    timestamp: datetime
    signal: CalibrationSignal
    blink_rounds: List[BlinkCalibrationRound]  # 0 个（跳过眨眼计数）或 2 个
    final_adjustment_factor: float             # 多轮平均（无轮次则为 1.0）
    final_blink_threshold: float               # ear_mean × 0.75 × final_adjustment_factor
    final_squint_threshold: float              # ear_mean × 0.75
    baseline_blink_rate: float                 # 每分钟眨眼次数（含跳过时的默认值 15.0）
    cqs: float                                 # 整体校准质量分（0.0-1.0）
    is_accepted: bool                          # 用户在总结页是否点了"继续 → 主监测"
    notes: str = ""                            # 可选：用户备注或失败诊断
```

- [ ] **Step 3.2: 运行测试确认通过**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_result.py -v
```

Expected: 9 passed

### Step 4: 覆盖率门禁

- [ ] **Step 4.1: 检查 `calibration/result.py` 覆盖率 ≥ 95%**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_result.py --cov=calibration/result --cov-report=term-missing -q
```

Expected: `Cover` 列 ≥ 95%。若 < 95%，看 `Missing` 提示的行号，补测试覆盖。

### Step 5: 确认现有 284 测试无回归

- [ ] **Step 5.1: 跑全测试套件**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

Expected: `293 passed`（原 284 + 新增 9）。如有 fail，**立即回滚**：

```bash
"/c/Program Files/Git/cmd/git.exe" reset --hard HEAD
```

### Step 6: 提交

- [ ] **Step 6.1: git add + commit**

```bash
cd "/d/Users/Katysia/Desktop/EyeFocus Insight"
"/c/Program Files/Git/cmd/git.exe" add calibration/__init__.py \
  calibration/result.py \
  calibration/tests/__init__.py \
  calibration/tests/unit/__init__.py \
  calibration/tests/unit/test_result.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-01 result.py data contract

Frozen dataclasses for calibration module data contract:
- CalibrationSignal (9 fields)
- BlinkCalibrationRound (7 fields)
- CalibrationResult (11 fields)

All frozen. Field schema locked - no modifications allowed during dev.
Coverage: 95%+ on calibration/result.py.
Full test suite: 293 passed (284 baseline + 9 new)."
```

### 回滚点

- 标签：commit hash after T-CAL-01
- 触发回滚：T-CAL-02 ~ T-CAL-14 任一发现 result.py 字段需要改 → 回 T-CAL-01 + spec 修订 + 重新走 BS-7/BS-8 审核

### T-CAL-01 完成判据
- [ ] 9 个测试全 PASS
- [ ] `calibration/result.py` 覆盖率 ≥ 95%
- [ ] 全测试套件 293 passed
- [ ] commit 已提交

---

（接下文 T-CAL-02 ~ T-CAL-14）

---

## Task T-CAL-02: config.py 配置参数

**Goal:** 定义 `CalibrationConfig` dataclass，所有阶段时长 / 阈值参数 / UI 尺寸 / 音频开关集中在此。
**Coverage gate:** ≥ 90%
**Files:**
- Create: `calibration/config.py`
- Create: `calibration/tests/unit/test_config.py`

### Step 1: 写失败测试

- [ ] **Step 1.1: 写 `calibration/tests/unit/test_config.py`**

```python
"""测试 CalibrationConfig 配置项默认值与可定制性。"""
import pytest
from calibration.config import CalibrationConfig


def test_default_config_fields_present():
    c = CalibrationConfig()
    # 阶段时长
    assert c.auto_baseline_seconds == 7.0
    assert c.closed_eyes_seconds == 5.0
    assert c.open_eyes_verify_seconds == 3.0
    assert c.squint_seconds == 8.0
    assert c.head_direction_seconds == 3.0
    assert c.blink_round_seconds == 15.0
    assert c.blink_rounds_count == 2

    # 阈值
    assert c.closed_eyes_min_ratio == 0.5
    assert c.squint_baseline_ratio == 0.75
    assert c.head_direction_min_degrees == 10.0
    assert c.blink_count_min == 5
    assert c.blink_count_max == 60

    # UI
    assert c.ui_panel_height_px == 240
    assert c.button_height_px == 50
    assert c.button_padding_px == 10

    # 音频
    assert c.tts_rate == 180
    assert c.audio_enabled is True


def test_config_total_estimated_seconds():
    """5 阶段大致总时长（不含用户确认等待）应 < 90 秒。"""
    c = CalibrationConfig()
    total = (
        c.auto_baseline_seconds
        + c.closed_eyes_seconds + c.open_eyes_verify_seconds
        + c.squint_seconds
        + c.head_direction_seconds * 4
        + c.blink_round_seconds * c.blink_rounds_count
    )
    assert total < 90, f"5 阶段裸时长 {total}s 超过 90 秒上限"


def test_config_customizable():
    c = CalibrationConfig(
        auto_baseline_seconds=5.0,
        blink_rounds_count=3,
        audio_enabled=False,
    )
    assert c.auto_baseline_seconds == 5.0
    assert c.blink_rounds_count == 3
    assert c.audio_enabled is False


def test_blink_count_range_sensible():
    c = CalibrationConfig()
    assert c.blink_count_min < c.blink_count_max
    assert c.blink_count_min >= 1
    assert c.blink_count_max <= 100


def test_thresholds_in_valid_range():
    c = CalibrationConfig()
    assert 0.0 < c.closed_eyes_min_ratio < 1.0
    assert 0.0 < c.squint_baseline_ratio < 1.0
    assert c.head_direction_min_degrees > 0


def test_ui_dimensions_positive():
    c = CalibrationConfig()
    assert c.ui_panel_height_px > 0
    assert c.button_height_px > 0
    assert c.button_padding_px >= 0
```

- [ ] **Step 1.2: 运行确认失败**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_config.py -v
```

Expected: FAIL `ModuleNotFoundError`

### Step 2: 实现 config.py

- [ ] **Step 2.1: 写 `calibration/config.py`**

```python
"""calibration/config.py — CalibrationConfig 配置项

集中管理：阶段时长、判定阈值、UI 尺寸、音频开关。
设计依据：spec §2.9。
"""
from dataclasses import dataclass


@dataclass
class CalibrationConfig:
    """校准模块配置 — 所有可调参数。"""

    # ---------- 阶段时长（秒）----------
    auto_baseline_seconds: float = 7.0
    closed_eyes_seconds: float = 5.0
    open_eyes_verify_seconds: float = 3.0
    squint_seconds: float = 8.0
    head_direction_seconds: float = 3.0   # 每个方向单独 3 秒（4 方向共 12s）
    blink_round_seconds: float = 15.0      # 每轮 15s
    blink_rounds_count: int = 2            # 2 轮（spec P2 精简，原 3 轮）

    # ---------- 判定阈值 ----------
    closed_eyes_min_ratio: float = 0.5          # ear_min ≤ baseline × 此值算闭眼成功
    squint_baseline_ratio: float = 0.75         # squint_threshold = baseline × 此值
    head_direction_min_degrees: float = 10.0    # 每个方向 |偏转| ≥ 此度数算有效
    blink_count_min: int = 5                    # 用户输入眨眼数下限
    blink_count_max: int = 60                   # 上限

    # ---------- UI 参数 ----------
    ui_panel_height_px: int = 240               # 下方 UI 区高度（视频区固定 480）
    button_height_px: int = 50
    button_padding_px: int = 10

    # ---------- 音频参数 ----------
    tts_rate: int = 180                         # pyttsx3 语速（中文）
    audio_enabled: bool = True                  # False 时跳过所有音频
```

- [ ] **Step 2.2: 运行确认通过**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_config.py -v
```

Expected: 6 passed

### Step 3: 覆盖率门禁

- [ ] **Step 3.1: 检查覆盖率 ≥ 90%**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_config.py --cov=calibration/config --cov-report=term-missing -q
```

Expected: `Cover` ≥ 90%

### Step 4: 全测试套件无回归

- [ ] **Step 4.1:**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

Expected: `299 passed`（293 + 6）。失败 → `git reset --hard HEAD`

### Step 5: 提交

- [ ] **Step 5.1:**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/config.py calibration/tests/unit/test_config.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-02 config.py parameters

CalibrationConfig dataclass with default values:
- Phase durations totaling < 90s (P2 streamlined)
- Detection thresholds for each phase
- UI dimensions
- Audio rate and enable flag

Coverage: 90%+ on calibration/config.py. Total tests: 299 passed."
```

### 回滚点
- T-CAL-03+ 任一发现 config 字段需要改：回 T-CAL-02 + 重新加测试。

### T-CAL-02 完成判据
- [ ] 6 个测试全 PASS
- [ ] 覆盖率 ≥ 90%
- [ ] 全测试套件 299 passed
- [ ] commit 已提交

---

## Task T-CAL-03: phases/base.py + phases/auto_baseline.py

**Goal:** 定义 `Phase` ABC 统一接口 + 实现阶段 0 自动基线采集。
**Coverage gate:** ≥ 90% on auto_baseline.py
**Files:**
- Create: `calibration/phases/__init__.py` (空)
- Create: `calibration/phases/base.py`
- Create: `calibration/phases/auto_baseline.py`
- Create: `calibration/tests/unit/test_phase_base.py`
- Create: `calibration/tests/unit/test_auto_baseline.py`

### Step 1: 创建包目录

- [ ] **Step 1.1:**

```bash
.venv312/Scripts/python.exe -c "
import os
os.makedirs('calibration/phases', exist_ok=True)
open('calibration/phases/__init__.py', 'a').close()
print('OK')
"
```

### Step 2: 写 phases/base.py 测试 + 实现

- [ ] **Step 2.1: 写 `calibration/tests/unit/test_phase_base.py`**

```python
"""测试 Phase ABC 接口契约。"""
import pytest
from calibration.phases.base import Phase, LiveFeedback, PhaseResult


def test_phase_is_abstract():
    with pytest.raises(TypeError):
        Phase()  # type: ignore[abstract]


def test_live_feedback_fields():
    fb = LiveFeedback(
        remaining_sec=3.0,
        sample_count=42,
        quality_hint="采集中，请保持",
    )
    assert fb.remaining_sec == 3.0
    assert fb.sample_count == 42


def test_phase_result_success():
    r = PhaseResult(
        success=True,
        summary={"ear_mean": 0.3, "n": 100},
        failure_reason=None,
        failure_diagnosis=None,
    )
    assert r.success is True
    assert r.summary["ear_mean"] == 0.3


def test_phase_result_failure_with_diagnosis():
    r = PhaseResult(
        success=False,
        summary={},
        failure_reason="ear_min_too_high",
        failure_diagnosis="似乎没有完全闭眼，请用力闭眼后重做",
    )
    assert r.success is False
    assert "闭眼" in r.failure_diagnosis
```

- [ ] **Step 2.2: 写 `calibration/phases/base.py`**

```python
"""calibration/phases/base.py — Phase ABC 与共用 dataclass

每个阶段实现统一接口：feed_frame / get_live_feedback / is_complete / evaluate。
阶段类不知道 UI / 音频 / 键盘 — 纯数据采集 + 评估。

设计依据：spec §2.2。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class LiveFeedback:
    """阶段进行中给 UI 的实时反馈数据。"""
    remaining_sec: float
    sample_count: int
    quality_hint: str = ""        # 可选：实时引导文字


@dataclass(frozen=True)
class PhaseResult:
    """阶段结束时的评估结果。"""
    success: bool
    summary: Dict[str, Any]            # 采集统计（每阶段格式不同）
    failure_reason: Optional[str] = None
    failure_diagnosis: Optional[str] = None    # 给用户看的中文建议


class Phase(ABC):
    """所有阶段的抽象基类。"""

    name: str = ""
    duration_seconds: float = 0.0
    tts_intro: str = ""           # 阶段开始时 TTS 念
    tts_complete: str = ""        # 阶段成功结束时 TTS 念

    @abstractmethod
    def reset(self) -> None:
        """重置内部状态（重做时调用）。"""
        ...

    @abstractmethod
    def feed_frame(
        self,
        ear: Optional[float],
        yaw: Optional[float],
        pitch: Optional[float],
        timestamp: float,
    ) -> None:
        """每帧调用 — 接收当前帧 EAR/yaw/pitch（人脸丢失时为 None）。"""
        ...

    @abstractmethod
    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        """获取实时反馈，UI 每帧调一次。"""
        ...

    @abstractmethod
    def is_complete(self, elapsed_sec: float) -> bool:
        """阶段是否到时完成。"""
        ...

    @abstractmethod
    def evaluate(self) -> PhaseResult:
        """阶段结束时评估成功/失败 + 给出摘要 + 失败诊断。"""
        ...
```

- [ ] **Step 2.3: 运行**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_phase_base.py -v
```

Expected: 4 passed

### Step 3: 写 auto_baseline.py 测试 + 实现

- [ ] **Step 3.1: 写 `calibration/tests/unit/test_auto_baseline.py`**

```python
"""测试阶段 0 自动基线采集 — 合成 EAR/yaw/pitch 序列。"""
import pytest
from calibration.phases.auto_baseline import AutoBaselinePhase


def _feed_stable_frames(phase, n_frames=210, ear=0.30, yaw=0.5, pitch=1.0, start_t=0.0):
    """合成稳定的 30 fps 数据（7 秒 × 30 = 210 帧）。"""
    for i in range(n_frames):
        phase.feed_frame(ear=ear, yaw=yaw, pitch=pitch, timestamp=start_t + i / 30.0)


def test_auto_baseline_phase_basic_attrs():
    p = AutoBaselinePhase(duration_seconds=7.0)
    assert p.name == "自动基线采集"
    assert p.duration_seconds == 7.0
    assert "睁眼" in p.tts_intro


def test_auto_baseline_collects_samples():
    p = AutoBaselinePhase(duration_seconds=7.0)
    _feed_stable_frames(p, n_frames=210, ear=0.30)
    fb = p.get_live_feedback(elapsed_sec=3.0)
    assert fb.sample_count == 210
    assert fb.remaining_sec == pytest.approx(4.0, abs=0.01)


def test_auto_baseline_ignores_none_ear():
    p = AutoBaselinePhase(duration_seconds=7.0)
    # 100 帧有 ear，10 帧 None（人脸丢失）
    _feed_stable_frames(p, n_frames=100, ear=0.30)
    for i in range(10):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=100.0 + i / 30.0)
    fb = p.get_live_feedback(elapsed_sec=3.5)
    assert fb.sample_count == 100  # None 帧不计入


def test_auto_baseline_complete_after_duration():
    p = AutoBaselinePhase(duration_seconds=7.0)
    assert not p.is_complete(elapsed_sec=6.99)
    assert p.is_complete(elapsed_sec=7.0)
    assert p.is_complete(elapsed_sec=8.0)


def test_auto_baseline_evaluate_success_stable_ear():
    p = AutoBaselinePhase(duration_seconds=7.0)
    _feed_stable_frames(p, n_frames=210, ear=0.30, yaw=0.5, pitch=1.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_mean"] == pytest.approx(0.30, abs=0.001)
    assert r.summary["ear_cv"] == pytest.approx(0.0, abs=0.001)
    assert r.summary["yaw_mean"] == pytest.approx(0.5, abs=0.001)
    assert r.summary["pitch_mean"] == pytest.approx(1.0, abs=0.001)
    assert r.summary["face_detected_ratio"] == 1.0


def test_auto_baseline_evaluate_fail_low_face_ratio():
    """face_detected_ratio < 0.7 应失败。"""
    p = AutoBaselinePhase(duration_seconds=7.0)
    for i in range(50):
        p.feed_frame(ear=0.3, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    for i in range(160):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=(50 + i) / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "face_detected_ratio_low"
    assert "人脸" in r.failure_diagnosis


def test_auto_baseline_evaluate_fail_high_ear_cv():
    """ear_cv > 0.15 应失败（频繁眨眼/动作）。"""
    p = AutoBaselinePhase(duration_seconds=7.0)
    # 交替 EAR 0.30 与 0.10（模拟频繁眨眼）
    for i in range(210):
        ear = 0.30 if i % 2 == 0 else 0.10
        p.feed_frame(ear=ear, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "ear_cv_high"
    assert "睁眼" in r.failure_diagnosis


def test_auto_baseline_reset():
    p = AutoBaselinePhase(duration_seconds=7.0)
    _feed_stable_frames(p, n_frames=100)
    p.reset()
    fb = p.get_live_feedback(elapsed_sec=0.0)
    assert fb.sample_count == 0
```

- [ ] **Step 3.2: 写 `calibration/phases/auto_baseline.py`**

```python
"""calibration/phases/auto_baseline.py — 阶段 0 自动基线采集

7 秒内采集 EAR/yaw/pitch 均值。
失败条件：face_detected_ratio < 0.7 或 ear_cv > 0.15。

设计依据：spec §2.2 + §4.3。
"""
import statistics
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


class AutoBaselinePhase(Phase):
    name = "自动基线采集"
    tts_intro = "请保持自然睁眼，系统将自动采集 7 秒数据"
    tts_complete = "基线采集完成"

    def __init__(self, duration_seconds: float = 7.0):
        self.duration_seconds = duration_seconds
        self._ears: List[float] = []
        self._yaws: List[float] = []
        self._pitches: List[float] = []
        self._frames_total: int = 0       # 含 None 帧

    def reset(self) -> None:
        self._ears.clear()
        self._yaws.clear()
        self._pitches.clear()
        self._frames_total = 0

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        self._frames_total += 1
        if ear is not None:
            self._ears.append(ear)
            self._yaws.append(yaw if yaw is not None else 0.0)
            self._pitches.append(pitch if pitch is not None else 0.0)

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        remaining = max(0.0, self.duration_seconds - elapsed_sec)
        return LiveFeedback(
            remaining_sec=remaining,
            sample_count=len(self._ears),
            quality_hint="保持自然，无需眨眼",
        )

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

    def evaluate(self) -> PhaseResult:
        n_valid = len(self._ears)
        if self._frames_total == 0:
            return PhaseResult(
                success=False, summary={},
                failure_reason="no_frames",
                failure_diagnosis="未收到任何帧，请检查摄像头",
            )

        face_ratio = n_valid / self._frames_total

        if face_ratio < 0.7:
            return PhaseResult(
                success=False,
                summary={"face_detected_ratio": face_ratio, "sample_count": n_valid},
                failure_reason="face_detected_ratio_low",
                failure_diagnosis="人脸检测不稳定，请确认摄像头对准你的脸",
            )

        ear_mean = statistics.fmean(self._ears)
        ear_stdev = statistics.stdev(self._ears) if n_valid > 1 else 0.0
        ear_cv = ear_stdev / ear_mean if ear_mean > 0 else 0.0
        yaw_mean = statistics.fmean(self._yaws)
        pitch_mean = statistics.fmean(self._pitches)

        if ear_cv > 0.15:
            return PhaseResult(
                success=False,
                summary={"ear_mean": ear_mean, "ear_cv": ear_cv, "face_detected_ratio": face_ratio},
                failure_reason="ear_cv_high",
                failure_diagnosis="请保持自然睁眼，眨眼请等校准后再做",
            )

        return PhaseResult(
            success=True,
            summary={
                "ear_mean": ear_mean,
                "ear_cv": ear_cv,
                "yaw_mean": yaw_mean,
                "pitch_mean": pitch_mean,
                "sample_count": n_valid,
                "face_detected_ratio": face_ratio,
            },
        )
```

- [ ] **Step 3.3: 运行**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_auto_baseline.py -v
```

Expected: 8 passed

### Step 4: 覆盖率 + 全测试

- [ ] **Step 4.1:**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_phase_base.py calibration/tests/unit/test_auto_baseline.py --cov=calibration/phases --cov-report=term-missing -q
```

Expected: phases/base.py ≥ 90%, phases/auto_baseline.py ≥ 90%

- [ ] **Step 4.2:**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

Expected: `311 passed` (299 + 4 + 8)。失败 → `git reset --hard HEAD`

### Step 5: spike 真机预演（可选 — 但本任务推荐）

- [ ] **Step 5.1:** 暂存阶段 — T-CAL-12 flow 完成后会有更完整的 spike，这里只是确认逻辑

```bash
.venv312/Scripts/python.exe -c "
from calibration.phases.auto_baseline import AutoBaselinePhase
p = AutoBaselinePhase()
for i in range(210):
    p.feed_frame(ear=0.30+i*0.0001, yaw=0.5, pitch=1.0, timestamp=i/30.0)
print(p.evaluate())
"
```

Expected: `PhaseResult(success=True, ...)`，summary 含 ear_mean ≈ 0.31

### Step 6: 提交

- [ ] **Step 6.1:**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/phases/ calibration/tests/unit/test_phase_base.py calibration/tests/unit/test_auto_baseline.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-03 Phase ABC + auto_baseline phase

- phases/base.py: Phase ABC + LiveFeedback + PhaseResult dataclasses
- phases/auto_baseline.py: phase 0 - 7s EAR/yaw/pitch collection
- Failure modes: face_detected_ratio < 0.7 or ear_cv > 0.15
- Coverage: 90%+ on both files. Total tests: 311 passed."
```

### 回滚点 / 完成判据

- 回滚：T-CAL-04+ 发现 Phase ABC 签名需改 → 回 T-CAL-03
- 完成：12 测试全 PASS + 覆盖率达标 + 全套件 311 passed + commit

---

## Task T-CAL-04: phases/closed_eyes.py（阶段 1）

**Goal:** 实现闭眼校准阶段 — 5s 闭眼 + 3s 自动验证睁眼回升。
**Coverage gate:** ≥ 90%
**Files:**
- Create: `calibration/phases/closed_eyes.py`
- Create: `calibration/tests/unit/test_closed_eyes.py`

### Step 1: 写失败测试

- [ ] **Step 1.1: 写 `calibration/tests/unit/test_closed_eyes.py`**

```python
"""测试 ClosedEyesPhase — 5s 闭眼 + 3s 睁眼回升验证。"""
import pytest
from calibration.phases.closed_eyes import ClosedEyesPhase


def test_closed_eyes_basic_attrs():
    p = ClosedEyesPhase(
        closed_duration_seconds=5.0,
        verify_duration_seconds=3.0,
        baseline_ear=0.30,
        min_ratio=0.5,
    )
    assert "闭眼" in p.name
    assert "闭眼" in p.tts_intro
    # 总时长 = 闭眼 + 验证
    assert p.duration_seconds == 8.0


def test_closed_eyes_evaluate_success_low_ear_min():
    """闭眼 EAR 降到 baseline × 0.3，应成功。"""
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    # 闭眼 5s @ 30 fps = 150 帧，EAR 0.09
    for i in range(150):
        p.feed_frame(ear=0.09, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    # 睁眼 3s = 90 帧，EAR 回升到 0.30
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0.0, pitch=0.0, timestamp=5.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_min"] == pytest.approx(0.09, abs=0.001)


def test_closed_eyes_evaluate_fail_ear_min_too_high():
    """闭眼期 ear_min > baseline × 0.5，未真正闭眼，应失败。"""
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    for i in range(150):
        p.feed_frame(ear=0.22, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0.0, pitch=0.0, timestamp=5.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "ear_min_too_high"
    assert "闭眼" in r.failure_diagnosis


def test_closed_eyes_is_complete():
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    assert not p.is_complete(elapsed_sec=7.99)
    assert p.is_complete(elapsed_sec=8.0)


def test_closed_eyes_live_feedback_phase_split():
    """前 5s 显示"闭眼中"，后 3s 显示"睁眼验证中"。"""
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    fb1 = p.get_live_feedback(elapsed_sec=2.0)
    assert "闭眼" in fb1.quality_hint
    fb2 = p.get_live_feedback(elapsed_sec=6.0)
    assert "睁眼" in fb2.quality_hint


def test_closed_eyes_ignores_none_frames():
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    for i in range(50):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=i / 30.0)
    for i in range(100):
        p.feed_frame(ear=0.09, yaw=0.0, pitch=0.0, timestamp=(50 + i) / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0.0, pitch=0.0, timestamp=5.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_min"] == pytest.approx(0.09, abs=0.001)


def test_closed_eyes_reset():
    p = ClosedEyesPhase(closed_duration_seconds=5.0, verify_duration_seconds=3.0,
                       baseline_ear=0.30, min_ratio=0.5)
    p.feed_frame(ear=0.05, yaw=0, pitch=0, timestamp=0.1)
    p.reset()
    r = p.evaluate()
    # 重置后无数据 → 评估应失败
    assert r.success is False
```

- [ ] **Step 1.2: 运行确认失败**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_closed_eyes.py -v
```

Expected: FAIL `ModuleNotFoundError`

### Step 2: 实现 closed_eyes.py

- [ ] **Step 2.1: 写 `calibration/phases/closed_eyes.py`**

```python
"""calibration/phases/closed_eyes.py — 阶段 1 闭眼校准

5s 闭眼 → 采集 ear_min；3s 自动验证 EAR 回升到合理范围。
失败条件：ear_min > baseline_ear × min_ratio（未真正闭眼）。

设计依据：spec §2.2 + §4.3 + P2（合并睁眼回升验证到此阶段）。
"""
import math
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


class ClosedEyesPhase(Phase):
    name = "闭眼校准"
    tts_intro = "请闭眼并保持 5 秒"
    tts_complete = "好，可以睁眼了"   # ← BUG 3 修复点：闭眼结束 TTS 明确告诉用户睁眼

    def __init__(
        self,
        closed_duration_seconds: float,
        verify_duration_seconds: float,
        baseline_ear: float,
        min_ratio: float,
    ):
        self.closed_duration_seconds = closed_duration_seconds
        self.verify_duration_seconds = verify_duration_seconds
        self.duration_seconds = closed_duration_seconds + verify_duration_seconds
        self.baseline_ear = baseline_ear
        self.min_ratio = min_ratio
        self._ear_min: float = math.inf
        self._closed_phase_samples: int = 0
        self._verify_phase_samples: int = 0
        self._verify_ear_sum: float = 0.0

    def reset(self) -> None:
        self._ear_min = math.inf
        self._closed_phase_samples = 0
        self._verify_phase_samples = 0
        self._verify_ear_sum = 0.0

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if ear is None:
            return
        # 用 timestamp 来判断处于哪个子阶段：< closed_duration = 闭眼期
        if timestamp < self.closed_duration_seconds:
            if ear < self._ear_min:
                self._ear_min = ear
            self._closed_phase_samples += 1
        else:
            self._verify_phase_samples += 1
            self._verify_ear_sum += ear

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        remaining = max(0.0, self.duration_seconds - elapsed_sec)
        if elapsed_sec < self.closed_duration_seconds:
            hint = "闭眼中，请保持..."
            count = self._closed_phase_samples
        else:
            hint = "睁眼验证中..."
            count = self._verify_phase_samples
        return LiveFeedback(remaining_sec=remaining, sample_count=count, quality_hint=hint)

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

    def evaluate(self) -> PhaseResult:
        if self._closed_phase_samples == 0:
            return PhaseResult(
                success=False, summary={},
                failure_reason="no_samples",
                failure_diagnosis="未采集到任何数据，请确认人脸在画面内",
            )

        ear_min = self._ear_min
        threshold = self.baseline_ear * self.min_ratio

        if ear_min > threshold:
            return PhaseResult(
                success=False,
                summary={"ear_min": ear_min, "threshold": threshold,
                         "closed_samples": self._closed_phase_samples},
                failure_reason="ear_min_too_high",
                failure_diagnosis=f"似乎没有完全闭眼（最低 EAR {ear_min:.3f}，需 < {threshold:.3f}），请用力闭眼后重做",
            )

        verify_ear_avg = (
            self._verify_ear_sum / self._verify_phase_samples
            if self._verify_phase_samples > 0 else 0.0
        )

        return PhaseResult(
            success=True,
            summary={
                "ear_min": ear_min,
                "verify_ear_avg": verify_ear_avg,
                "closed_samples": self._closed_phase_samples,
                "verify_samples": self._verify_phase_samples,
            },
        )
```

- [ ] **Step 2.2: 运行**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_closed_eyes.py -v
```

Expected: 7 passed

### Step 3: 覆盖率门禁

- [ ] **Step 3.1:**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_closed_eyes.py --cov=calibration/phases/closed_eyes --cov-report=term-missing -q
```

Expected: ≥ 90%

### Step 4: 全测试

- [ ] **Step 4.1:**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

Expected: `318 passed` (311 + 7)。失败 → `git reset --hard HEAD`

### Step 5: 真机 TTS 验证（推荐 — 验证 BUG 3 修复路径）

- [ ] **Step 5.1:** 仅验证 tts_complete 文案含"睁眼"关键词

```bash
.venv312/Scripts/python.exe -c "
from calibration.phases.closed_eyes import ClosedEyesPhase
p = ClosedEyesPhase(5.0, 3.0, 0.30, 0.5)
print('tts_intro:', p.tts_intro)
print('tts_complete:', p.tts_complete)
assert '睁眼' in p.tts_complete, 'BUG 3 修复未生效'
print('OK')
"
```

Expected: `tts_complete: 好，可以睁眼了` + `OK`

### Step 6: 提交

- [ ] **Step 6.1:**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/phases/closed_eyes.py calibration/tests/unit/test_closed_eyes.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-04 closed_eyes phase (BUG 3 fix)

Phase 1 - 5s closed eyes + 3s auto-verify open recovery (P2 merged).
tts_complete contains '睁眼' keyword - BUG 3 fix (user hears 'now open eyes').
Failure: ear_min > baseline × min_ratio means didn't truly close eyes.
Coverage: 90%+ on closed_eyes.py. Total tests: 318 passed."
```

### 回滚点 / 完成判据
- 回滚：发现 tts_complete 不含"睁眼" → BUG 3 修复未生效 → 回 T-CAL-04 修
- 完成：7 测试全 PASS + 覆盖率达标 + 全套件 318 passed + commit

---

（接下文 T-CAL-05 ~ T-CAL-14）

---

## Task T-CAL-05: phases/squint.py（阶段 2）

**Goal:** 实现眯眼校准 — 8s 采集眯眼 EAR，定义眨眼/眯眼边界。
**Coverage gate:** ≥ 90%
**Files:**
- Create: `calibration/phases/squint.py`
- Create: `calibration/tests/unit/test_squint.py`

### Step 1: 写失败测试

- [ ] **Step 1.1: `calibration/tests/unit/test_squint.py`**

```python
"""测试 SquintPhase — 8s 眯眼采集。"""
import pytest
from calibration.phases.squint import SquintPhase


def test_squint_basic_attrs():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    assert "眯眼" in p.name
    assert "眯眼" in p.tts_intro
    assert p.duration_seconds == 8.0


def test_squint_evaluate_success():
    """眯眼 EAR 在 baseline×0.75 与 ear_min×1.2 之间，应成功。"""
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    # baseline=0.30, ear_min=0.08 → 合理眯眼 EAR 在 0.10~0.225
    for i in range(240):
        p.feed_frame(ear=0.18, yaw=0.0, pitch=0.0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["ear_mid"] == pytest.approx(0.18, abs=0.001)


def test_squint_evaluate_fail_too_open():
    """眯眼 EAR 接近 baseline（没真眯）→ 失败。"""
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(240):
        p.feed_frame(ear=0.28, yaw=0, pitch=0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "squint_too_open"
    assert "眯眼" in r.failure_diagnosis


def test_squint_evaluate_fail_too_closed():
    """眯眼 EAR 接近 ear_min（眼睛闭得过死，没缝）→ 失败。"""
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(240):
        p.feed_frame(ear=0.085, yaw=0, pitch=0, timestamp=i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "squint_too_closed"
    assert "一条缝" in r.failure_diagnosis


def test_squint_is_complete():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    assert not p.is_complete(elapsed_sec=7.99)
    assert p.is_complete(elapsed_sec=8.0)


def test_squint_reset():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(50):
        p.feed_frame(ear=0.18, yaw=0, pitch=0, timestamp=i / 30.0)
    p.reset()
    r = p.evaluate()
    assert r.success is False  # 重置后无数据


def test_squint_ignores_none():
    p = SquintPhase(duration_seconds=8.0, baseline_ear=0.30,
                   baseline_ratio=0.75, ear_min=0.08)
    for i in range(30):
        p.feed_frame(ear=None, yaw=None, pitch=None, timestamp=i / 30.0)
    for i in range(200):
        p.feed_frame(ear=0.18, yaw=0, pitch=0, timestamp=(30 + i) / 30.0)
    r = p.evaluate()
    assert r.success is True
```

- [ ] **Step 1.2: 运行确认失败**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_squint.py -v
```

Expected: FAIL ModuleNotFoundError

### Step 2: 实现 squint.py

- [ ] **Step 2.1: `calibration/phases/squint.py`**

```python
"""calibration/phases/squint.py — 阶段 2 眯眼校准

8s 采集眯眼 EAR，得到 ear_mid（眨眼/眯眼判定边界）。
判定有效区间：ear_min × 1.2 < ear_mid < baseline × baseline_ratio。

设计依据：spec §2.2 + §4.3。
"""
import statistics
from typing import List

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


class SquintPhase(Phase):
    name = "眯眼校准"
    tts_intro = "请眯眼，眼睛留一条缝，保持 8 秒"
    tts_complete = "好"

    def __init__(
        self,
        duration_seconds: float,
        baseline_ear: float,
        baseline_ratio: float,
        ear_min: float,
    ):
        self.duration_seconds = duration_seconds
        self.baseline_ear = baseline_ear
        self.baseline_ratio = baseline_ratio
        self.ear_min = ear_min
        self._ears: List[float] = []

    def reset(self) -> None:
        self._ears.clear()

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if ear is not None:
            self._ears.append(ear)

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        return LiveFeedback(
            remaining_sec=max(0.0, self.duration_seconds - elapsed_sec),
            sample_count=len(self._ears),
            quality_hint="眯眼保持中...",
        )

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

    def evaluate(self) -> PhaseResult:
        if not self._ears:
            return PhaseResult(
                success=False, summary={},
                failure_reason="no_samples",
                failure_diagnosis="未采集到数据，请确认人脸在画面内",
            )

        ear_mid = statistics.fmean(self._ears)
        upper = self.baseline_ear * self.baseline_ratio  # 0.225 当 baseline=0.30
        lower = self.ear_min * 1.2                        # 0.096 当 ear_min=0.08

        summary = {
            "ear_mid": ear_mid, "upper_limit": upper, "lower_limit": lower,
            "sample_count": len(self._ears),
        }

        if ear_mid >= upper:
            return PhaseResult(
                success=False, summary=summary,
                failure_reason="squint_too_open",
                failure_diagnosis=f"眯眼幅度不够（EAR {ear_mid:.3f} ≥ {upper:.3f}），请眼睛眯小一点",
            )
        if ear_mid <= lower:
            return PhaseResult(
                success=False, summary=summary,
                failure_reason="squint_too_closed",
                failure_diagnosis=f"眼睛眯得过死，请留一条缝（EAR {ear_mid:.3f} ≤ {lower:.3f}）",
            )

        return PhaseResult(success=True, summary=summary)
```

- [ ] **Step 2.2: 运行**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_squint.py -v
```

Expected: 7 passed

### Step 3-5: 覆盖率 + 全测试 + 提交

- [ ] **Step 3.1: 覆盖率 ≥ 90%**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_squint.py --cov=calibration/phases/squint --cov-report=term-missing -q
```

- [ ] **Step 3.2: 全测试 325 passed (318 + 7)**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

- [ ] **Step 3.3: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/phases/squint.py calibration/tests/unit/test_squint.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-05 squint phase

Phase 2 - 8s squint EAR collection.
Valid range: ear_min×1.2 < ear_mid < baseline×baseline_ratio.
Coverage: 90%+ on squint.py. Total tests: 325 passed."
```

### T-CAL-05 完成判据
- [ ] 7 测试 PASS + 覆盖率 ≥ 90% + 全套件 325 + commit

---

## Task T-CAL-06: phases/head_pose.py（阶段 3，含 4 子阶段 — BUG 4 修复）

**Goal:** 实现头部姿态校准 — 4 个子阶段独立 TTS 指令 + 数据采集。
**Coverage gate:** ≥ 85%
**Files:**
- Create: `calibration/phases/head_pose.py`
- Create: `calibration/tests/unit/test_head_pose.py`

### Step 1: 写失败测试

- [ ] **Step 1.1: `calibration/tests/unit/test_head_pose.py`**

```python
"""测试 HeadPosePhase — 4 子阶段（抬/低/左/右）各自独立 TTS 指令。"""
import pytest
from calibration.phases.head_pose import HeadPosePhase, HeadDirection


def test_head_pose_basic_attrs():
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert "头部" in p.name
    assert p.duration_seconds == 12.0  # 4 × 3


def test_head_pose_has_4_sub_phases():
    """BUG 4 修复：4 个子阶段必须各有独立 TTS 指令。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert len(p.sub_phases) == 4
    keywords = ["抬头", "低头", "向左", "向右"]
    for sub, kw in zip(p.sub_phases, keywords):
        assert kw in sub.tts, f"子阶段缺少 '{kw}' TTS"


def test_head_pose_current_sub_phase_by_elapsed():
    """根据 elapsed 切换当前子阶段。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert p.current_sub_phase(elapsed_sec=0.5).direction == HeadDirection.UP
    assert p.current_sub_phase(elapsed_sec=3.5).direction == HeadDirection.DOWN
    assert p.current_sub_phase(elapsed_sec=6.5).direction == HeadDirection.LEFT
    assert p.current_sub_phase(elapsed_sec=9.5).direction == HeadDirection.RIGHT


def test_head_pose_evaluate_success_all_directions():
    """4 方向都达到 ±10°，应成功。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    # 抬头 0~3s: pitch = -15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=-15, timestamp=i / 30.0)
    # 低头 3~6s: pitch = 15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=15, timestamp=3.0 + i / 30.0)
    # 左转 6~9s: yaw = -15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=-15, pitch=0, timestamp=6.0 + i / 30.0)
    # 右转 9~12s: yaw = 15
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=15, pitch=0, timestamp=9.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is True
    assert r.summary["pitch_up_max"] == -15
    assert r.summary["pitch_down_max"] == 15
    assert r.summary["yaw_left_max"] == -15
    assert r.summary["yaw_right_max"] == 15


def test_head_pose_evaluate_fail_one_direction_insufficient():
    """某方向 < ±10° → 失败 + 诊断含方向。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=-5, timestamp=i / 30.0)  # 抬头不够
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=0, pitch=15, timestamp=3.0 + i / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=-15, pitch=0, timestamp=6.0 + i / 30.0)
    for i in range(90):
        p.feed_frame(ear=0.30, yaw=15, pitch=0, timestamp=9.0 + i / 30.0)
    r = p.evaluate()
    assert r.success is False
    assert r.failure_reason == "head_direction_insufficient"
    assert "抬头" in r.failure_diagnosis


def test_head_pose_live_feedback_includes_direction_hint():
    """实时反馈应包含当前方向提示。"""
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    fb_up = p.get_live_feedback(elapsed_sec=1.0)
    assert "抬头" in fb_up.quality_hint
    fb_down = p.get_live_feedback(elapsed_sec=4.0)
    assert "低头" in fb_down.quality_hint


def test_head_pose_is_complete():
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    assert not p.is_complete(elapsed_sec=11.99)
    assert p.is_complete(elapsed_sec=12.0)


def test_head_pose_reset():
    p = HeadPosePhase(direction_seconds=3.0, min_degrees=10.0)
    for i in range(30):
        p.feed_frame(ear=0.30, yaw=-10, pitch=-10, timestamp=i / 30.0)
    p.reset()
    r = p.evaluate()
    assert r.success is False  # 无数据
```

- [ ] **Step 1.2: 运行确认失败**

### Step 2: 实现 head_pose.py

- [ ] **Step 2.1: `calibration/phases/head_pose.py`**

```python
"""calibration/phases/head_pose.py — 阶段 3 头部姿态校准

4 个子阶段（抬头/低头/左转/右转）各独立 3s + 独立 TTS 指令。
解决 BUG 4：原 T148 不告诉用户当前子阶段，导致数据全是垃圾。

设计依据：spec §2.2（头部姿态拆 4 子阶段）+ §4.3。
"""
import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult


class HeadDirection(Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class HeadSubPhase:
    direction: HeadDirection
    tts: str
    hint: str


class HeadPosePhase(Phase):
    name = "头部姿态校准"
    tts_intro = "接下来请按照语音提示移动头部，每个方向 3 秒"
    tts_complete = "头部姿态采集完成"

    def __init__(self, direction_seconds: float, min_degrees: float):
        self.direction_seconds = direction_seconds
        self.duration_seconds = direction_seconds * 4
        self.min_degrees = min_degrees
        self.sub_phases: List[HeadSubPhase] = [
            HeadSubPhase(HeadDirection.UP, "现在抬头", "请抬头"),
            HeadSubPhase(HeadDirection.DOWN, "现在低头", "请低头"),
            HeadSubPhase(HeadDirection.LEFT, "现在向左转", "请向左转头"),
            HeadSubPhase(HeadDirection.RIGHT, "现在向右转", "请向右转头"),
        ]
        # max 记录极值（pitch 抬头是负，低头是正；yaw 左是负，右是正）
        self._pitch_up_max: float = 0.0      # 越负越好
        self._pitch_down_max: float = 0.0    # 越正越好
        self._yaw_left_max: float = 0.0      # 越负越好
        self._yaw_right_max: float = 0.0     # 越正越好

    def reset(self) -> None:
        self._pitch_up_max = 0.0
        self._pitch_down_max = 0.0
        self._yaw_left_max = 0.0
        self._yaw_right_max = 0.0

    def current_sub_phase(self, elapsed_sec: float) -> HeadSubPhase:
        idx = min(int(elapsed_sec // self.direction_seconds), 3)
        return self.sub_phases[idx]

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if yaw is None or pitch is None:
            return
        sub = self.current_sub_phase(timestamp)
        if sub.direction == HeadDirection.UP and pitch < self._pitch_up_max:
            self._pitch_up_max = pitch
        elif sub.direction == HeadDirection.DOWN and pitch > self._pitch_down_max:
            self._pitch_down_max = pitch
        elif sub.direction == HeadDirection.LEFT and yaw < self._yaw_left_max:
            self._yaw_left_max = yaw
        elif sub.direction == HeadDirection.RIGHT and yaw > self._yaw_right_max:
            self._yaw_right_max = yaw

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        sub = self.current_sub_phase(elapsed_sec)
        remaining = max(0.0, self.duration_seconds - elapsed_sec)
        return LiveFeedback(
            remaining_sec=remaining,
            sample_count=0,  # 头部姿态不显示样本数，显示方向提示
            quality_hint=sub.hint,
        )

    def is_complete(self, elapsed_sec: float) -> bool:
        return elapsed_sec >= self.duration_seconds

    def evaluate(self) -> PhaseResult:
        thr = self.min_degrees
        failures = []
        if abs(self._pitch_up_max) < thr:
            failures.append(("抬头", abs(self._pitch_up_max)))
        if abs(self._pitch_down_max) < thr:
            failures.append(("低头", abs(self._pitch_down_max)))
        if abs(self._yaw_left_max) < thr:
            failures.append(("向左转", abs(self._yaw_left_max)))
        if abs(self._yaw_right_max) < thr:
            failures.append(("向右转", abs(self._yaw_right_max)))

        summary = {
            "pitch_up_max": self._pitch_up_max,
            "pitch_down_max": self._pitch_down_max,
            "yaw_left_max": self._yaw_left_max,
            "yaw_right_max": self._yaw_right_max,
            "min_degrees_required": thr,
        }

        if failures:
            failed_names = "、".join(name for name, _ in failures)
            return PhaseResult(
                success=False, summary=summary,
                failure_reason="head_direction_insufficient",
                failure_diagnosis=f"{failed_names} 转动幅度不够（需 ≥ {thr}°），请大一点动作后重做",
            )
        return PhaseResult(success=True, summary=summary)
```

- [ ] **Step 2.2: 运行**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_head_pose.py -v
```

Expected: 8 passed

### Step 3-5: 覆盖率 + 全测试 + 真机 4 TTS + commit

- [ ] **Step 3.1: 覆盖率 ≥ 85%**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_head_pose.py --cov=calibration/phases/head_pose --cov-report=term-missing -q
```

- [ ] **Step 3.2: 全测试 333 passed (325 + 8)**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

- [ ] **Step 3.3: 真机 4 子阶段 TTS 验证（BUG 4 修复）**

```bash
.venv312/Scripts/python.exe -c "
from calibration.phases.head_pose import HeadPosePhase
p = HeadPosePhase(3.0, 10.0)
for sub in p.sub_phases:
    print(sub.direction.value, '->', sub.tts)
assert all(kw in p.sub_phases[i].tts for i, kw in enumerate(['抬头','低头','向左','向右']))
print('BUG 4 修复确认 OK')
"
```

Expected: 4 行各方向 TTS + "BUG 4 修复确认 OK"

- [ ] **Step 3.4: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/phases/head_pose.py calibration/tests/unit/test_head_pose.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-06 head_pose phase (BUG 4 fix)

Phase 3 - 4 sub-phases (up/down/left/right) × 3s each = 12s total.
Each sub-phase has independent TTS instruction (BUG 4 fix).
Failure: any direction |angle| < min_degrees triggers diagnosis with direction names.
Coverage: 85%+ on head_pose.py. Total tests: 333 passed."
```

### 回滚点 / 完成判据
- 回滚：测试 test_head_pose_has_4_sub_phases 失败 → BUG 4 修复未生效 → 回 T-CAL-06
- 完成：8 测试 + 覆盖率 + 333 全套件 + commit

---

## Task T-CAL-07: phases/blink_count.py（阶段 4，含 2 轮 + 用户输入）

**Goal:** 实现眨眼计数阶段 — 2 轮 × 15s 检测 + 接收用户输入 + 计算 adjustment_factor。
**Coverage gate:** ≥ 85%
**Files:**
- Create: `calibration/phases/blink_count.py`
- Create: `calibration/tests/unit/test_blink_count.py`

### Step 1: 写失败测试

- [ ] **Step 1.1: `calibration/tests/unit/test_blink_count.py`**

```python
"""测试 BlinkCountPhase — 2 轮 × 15s 眨眼检测 + 用户输入 + 调整因子。"""
import pytest
from calibration.phases.blink_count import BlinkCountPhase, BlinkCountState


def test_blink_count_basic_attrs():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    assert "眨眼" in p.name
    assert p.duration_seconds == 30.0  # 2 × 15


def test_blink_count_initial_state_is_running():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    assert p.current_round == 1
    assert p.state == BlinkCountState.COUNTING


def test_blink_count_detects_30hz_blinks():
    """BUG 1 修复回归：合成 30 fps 序列 + 5 个 200ms 眨眼应全检出。"""
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 15s @ 30fps = 450 帧。每 3s 一次 200ms 眨眼 = 5 次
    for frame_idx in range(15 * 30):
        t = frame_idx / 30.0
        if int(t) % 3 == 0 and (t - int(t)) < 0.2:
            ear = 0.10  # 眨眼期 < blink_threshold (0.30*0.75=0.225)
        else:
            ear = 0.30
        p.feed_frame(ear=ear, yaw=0, pitch=0, timestamp=t)
    detected = p.get_round_detected_blinks()
    assert detected == 5, f"BUG 1 回归：期望 5 次眨眼，实际检出 {detected}"


def test_blink_count_round_complete_transitions_to_waiting():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    assert p.state == BlinkCountState.WAITING_INPUT


def test_blink_count_user_input_within_range_advances():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    p.on_user_input(10)
    assert p.state == BlinkCountState.COUNTING
    assert p.current_round == 2


def test_blink_count_user_input_out_of_range_rejected():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    accepted = p.on_user_input(100)  # 超过 max=60
    assert accepted is False
    assert p.state == BlinkCountState.WAITING_INPUT  # 仍在等输入


def test_blink_count_full_2_rounds_completes_phase():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    p.on_round_time_up()
    p.on_user_input(10)
    p.on_round_time_up()
    p.on_user_input(12)
    assert p.state == BlinkCountState.DONE


def test_blink_count_evaluate_with_rounds():
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 模拟两轮（每轮检测到 8 次，用户报告 10 次）
    for _ in range(2):
        for frame_idx in range(15 * 30):
            t = frame_idx / 30.0
            if int(t) % 2 == 0 and (t - int(t)) < 0.2:
                ear = 0.10
            else:
                ear = 0.30
            p.feed_frame(ear=ear, yaw=0, pitch=0, timestamp=t)
        p.on_round_time_up()
        p.on_user_input(10)
    r = p.evaluate()
    assert r.success is True
    assert len(r.summary["rounds"]) == 2
    assert r.summary["final_adjustment_factor"] == pytest.approx(1.2, abs=0.05)


def test_blink_count_evaluate_no_rounds_default():
    """跳过该阶段（rounds=0）应仍返回 success，blink_rounds 为空。"""
    p = BlinkCountPhase(round_seconds=15.0, rounds=2,
                       baseline_ear=0.30, ear_min=0.08,
                       count_min=5, count_max=60)
    # 直接 evaluate（无任何 round complete）
    r = p.evaluate()
    assert r.success is False  # 未跑完 2 轮，应失败
```

- [ ] **Step 1.2: 运行确认失败**

### Step 2: 实现 blink_count.py

- [ ] **Step 2.1: `calibration/phases/blink_count.py`**

```python
"""calibration/phases/blink_count.py — 阶段 4 眨眼计数（2 轮 + 用户输入）

每帧调用 feed_frame 检测眨眼（BUG 1 修复：原 T148 仅每秒采样导致漏检 95%+）。
每轮结束等待用户输入实际眨眼数 → 计算 adjustment_factor。

设计依据：spec §2.2 + §3.2 BlinkCount 特殊流程。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from calibration.phases.base import LiveFeedback, Phase, PhaseResult
from calibration.result import BlinkCalibrationRound


class BlinkCountState(Enum):
    COUNTING = "counting"
    WAITING_INPUT = "waiting_input"
    DONE = "done"


# 眨眼/眯眼判定时间阈值（与 EyeAspectDetector 一致）
BLINK_MAX_DURATION_SEC = 0.4


class BlinkCountPhase(Phase):
    name = "眨眼计数校准"
    tts_intro = "接下来 15 秒，请自然眨眼，结束后告诉我你眨了多少次"
    tts_complete = "好"

    def __init__(
        self,
        round_seconds: float,
        rounds: int,
        baseline_ear: float,
        ear_min: float,
        count_min: int,
        count_max: int,
    ):
        self.round_seconds = round_seconds
        self.rounds = rounds
        self.duration_seconds = round_seconds * rounds
        self.baseline_ear = baseline_ear
        self.ear_min = ear_min
        self.count_min = count_min
        self.count_max = count_max
        # 阈值（同 spec §6.8 阶段一）
        self.blink_threshold = baseline_ear * 0.75   # 0.225
        self.squint_threshold = baseline_ear * 0.90  # 0.27

        self.current_round = 1
        self.state = BlinkCountState.COUNTING

        # 当前轮检测器内部状态
        self._in_eye_closed: bool = False
        self._close_start_t: Optional[float] = None
        self._round_blinks: int = 0
        self._round_squints: int = 0

        # 完成的轮次
        self._completed_rounds: List[BlinkCalibrationRound] = []

    def reset(self) -> None:
        self.current_round = 1
        self.state = BlinkCountState.COUNTING
        self._in_eye_closed = False
        self._close_start_t = None
        self._round_blinks = 0
        self._round_squints = 0
        self._completed_rounds.clear()

    def feed_frame(self, ear, yaw, pitch, timestamp) -> None:
        if ear is None or self.state != BlinkCountState.COUNTING:
            return

        if ear < self.blink_threshold:
            if not self._in_eye_closed:
                self._in_eye_closed = True
                self._close_start_t = timestamp
        else:
            if self._in_eye_closed and self._close_start_t is not None:
                duration = timestamp - self._close_start_t
                if duration < BLINK_MAX_DURATION_SEC:
                    self._round_blinks += 1
                else:
                    self._round_squints += 1
                self._in_eye_closed = False
                self._close_start_t = None

    def get_live_feedback(self, elapsed_sec: float) -> LiveFeedback:
        round_elapsed = elapsed_sec - (self.current_round - 1) * self.round_seconds
        remaining = max(0.0, self.round_seconds - round_elapsed)
        return LiveFeedback(
            remaining_sec=remaining,
            sample_count=self._round_blinks,
            quality_hint=f"第 {self.current_round}/{self.rounds} 轮 - 已检出 {self._round_blinks} 次",
        )

    def get_round_detected_blinks(self) -> int:
        return self._round_blinks

    def get_round_detected_squints(self) -> int:
        return self._round_squints

    def on_round_time_up(self) -> None:
        """flow.py 在每轮 15s 到点时调用。"""
        if self.state != BlinkCountState.COUNTING:
            return
        self.state = BlinkCountState.WAITING_INPUT

    def on_user_input(self, user_count: int) -> bool:
        """flow.py 在收到用户输入数字后调用。返回 False 表示输入超范围。"""
        if self.state != BlinkCountState.WAITING_INPUT:
            return False
        if not (self.count_min <= user_count <= self.count_max):
            return False

        program_count = self._round_blinks
        error_rate = (
            (user_count - program_count) / user_count if user_count > 0 else 0.0
        )
        adjustment = max(0.7, min(1.3, 1.0 + error_rate))

        self._completed_rounds.append(BlinkCalibrationRound(
            round_index=self.current_round,
            duration_seconds=int(self.round_seconds),
            user_blink_count=user_count,
            program_blink_count=program_count,
            program_squint_count=self._round_squints,
            error_rate=error_rate,
            adjustment_factor=adjustment,
        ))

        if self.current_round < self.rounds:
            self.current_round += 1
            self.state = BlinkCountState.COUNTING
            self._reset_round_counters()
        else:
            self.state = BlinkCountState.DONE
        return True

    def _reset_round_counters(self) -> None:
        self._in_eye_closed = False
        self._close_start_t = None
        self._round_blinks = 0
        self._round_squints = 0

    def is_complete(self, elapsed_sec: float) -> bool:
        return self.state == BlinkCountState.DONE

    def evaluate(self) -> PhaseResult:
        if len(self._completed_rounds) < self.rounds:
            return PhaseResult(
                success=False,
                summary={"completed_rounds": len(self._completed_rounds)},
                failure_reason="rounds_incomplete",
                failure_diagnosis=f"未完成 {self.rounds} 轮（已完成 {len(self._completed_rounds)}）",
            )

        factors = [r.adjustment_factor for r in self._completed_rounds]
        final_adj = sum(factors) / len(factors)
        total_user = sum(r.user_blink_count for r in self._completed_rounds)
        total_dur_min = sum(r.duration_seconds for r in self._completed_rounds) / 60.0
        baseline_blink_rate = total_user / total_dur_min if total_dur_min > 0 else 15.0

        return PhaseResult(
            success=True,
            summary={
                "rounds": list(self._completed_rounds),
                "final_adjustment_factor": final_adj,
                "baseline_blink_rate": baseline_blink_rate,
            },
        )
```

- [ ] **Step 2.2: 运行**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_blink_count.py -v
```

Expected: 9 passed

### Step 3-5: 覆盖率 + 全测试 + commit

- [ ] **Step 3.1: 覆盖率 ≥ 85%**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_blink_count.py --cov=calibration/phases/blink_count --cov-report=term-missing -q
```

- [ ] **Step 3.2: 全测试 342 passed (333 + 9)**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

- [ ] **Step 3.3: 真机 BUG 1 验证（关键）**

```bash
.venv312/Scripts/python.exe -c "
from calibration.phases.blink_count import BlinkCountPhase
p = BlinkCountPhase(15.0, 2, 0.30, 0.08, 5, 60)
# 合成 15s @ 30fps，每 3s 一次 200ms 眨眼 = 5 次
for frame_idx in range(15 * 30):
    t = frame_idx / 30.0
    if int(t) % 3 == 0 and (t - int(t)) < 0.2:
        ear = 0.10
    else:
        ear = 0.30
    p.feed_frame(ear=ear, yaw=0, pitch=0, timestamp=t)
detected = p.get_round_detected_blinks()
print(f'Detected: {detected} (expected: 5)')
assert detected == 5, 'BUG 1 修复未生效'
print('BUG 1 修复确认 OK')
"
```

Expected: `Detected: 5` + `BUG 1 修复确认 OK`

- [ ] **Step 3.4: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/phases/blink_count.py calibration/tests/unit/test_blink_count.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-07 blink_count phase (BUG 1 fix)

Phase 4 - 2 rounds × 15s blink detection + user input.
feed_frame called per-frame (30Hz) - BUG 1 fix vs T148's 1Hz tick sampling.
Test test_blink_count_detects_30hz_blinks confirms 5/5 detection.
User input validates against count_min/count_max range.
Coverage: 85%+ on blink_count.py. Total tests: 342 passed."
```

### 回滚点 / 完成判据
- 回滚：test_blink_count_detects_30hz_blinks 失败 → BUG 1 修复未生效 → 回 T-CAL-07
- 完成：9 测试 + 覆盖率 + 342 全套件 + commit

---

（接下文 T-CAL-08 ~ T-CAL-14）

---

## Task T-CAL-08: ui/layout.py（上下分屏拼合）

**Goal:** 实现 `compose(camera_frame, panel_img) → 拼合 640×720 帧`。
**Coverage gate:** ≥ 90%
**Files:**
- Create: `calibration/ui/__init__.py` (空)
- Create: `calibration/ui/layout.py`
- Create: `calibration/tests/unit/test_layout.py`

### Step 1: 创建包目录

- [ ] **Step 1.1:**

```bash
.venv312/Scripts/python.exe -c "
import os
os.makedirs('calibration/ui', exist_ok=True)
open('calibration/ui/__init__.py', 'a').close()
print('OK')
"
```

### Step 2: 写测试 + 实现

- [ ] **Step 2.1: `calibration/tests/unit/test_layout.py`**

```python
"""测试 layout.compose — vconcat 拼合视频 + UI 面板。"""
import numpy as np
import pytest

from calibration.ui.layout import compose


def test_compose_normal_size():
    cam = np.zeros((480, 640, 3), dtype=np.uint8)
    panel = np.zeros((240, 640, 3), dtype=np.uint8)
    out = compose(cam, panel)
    assert out.shape == (720, 640, 3)


def test_compose_panel_height_must_match_width():
    cam = np.zeros((480, 640, 3), dtype=np.uint8)
    panel = np.zeros((240, 320, 3), dtype=np.uint8)  # 宽度不匹配
    with pytest.raises(ValueError):
        compose(cam, panel)


def test_compose_preserves_dtype():
    cam = np.zeros((480, 640, 3), dtype=np.uint8)
    panel = np.full((240, 640, 3), 50, dtype=np.uint8)
    out = compose(cam, panel)
    assert out.dtype == np.uint8


def test_compose_video_region_unchanged():
    cam = np.full((480, 640, 3), 100, dtype=np.uint8)
    panel = np.full((240, 640, 3), 50, dtype=np.uint8)
    out = compose(cam, panel)
    # 视频区域（前 480 行）应与 cam 完全相同
    assert np.array_equal(out[:480], cam)
    # UI 区域（后 240 行）应与 panel 完全相同
    assert np.array_equal(out[480:], panel)
```

- [ ] **Step 2.2: `calibration/ui/layout.py`**

```python
"""calibration/ui/layout.py — 上下分屏拼合

将摄像头帧（640×480）与 UI 面板（640×240）用 cv2.vconcat 拼成 640×720。
视频区不被 UI 遮挡（BUG 2 修复点）。

设计依据：spec §2.3 + 决策 L1。
"""
import cv2
import numpy as np


def compose(camera_frame: np.ndarray, panel_img: np.ndarray) -> np.ndarray:
    """拼合视频 + 面板。

    Args:
        camera_frame: shape (480, 640, 3) BGR
        panel_img: shape (h, 640, 3) BGR

    Returns:
        shape (480+h, 640, 3) BGR
    """
    if camera_frame.shape[1] != panel_img.shape[1]:
        raise ValueError(
            f"宽度不匹配：camera {camera_frame.shape[1]} vs panel {panel_img.shape[1]}"
        )
    return cv2.vconcat([camera_frame, panel_img])
```

- [ ] **Step 2.3: 运行 + 覆盖率 + 全测试 + commit**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_layout.py -v
# Expected: 4 passed
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_layout.py --cov=calibration/ui/layout --cov-report=term-missing -q
# Expected: ≥ 90%
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
# Expected: 346 passed (342+4)
"/c/Program Files/Git/cmd/git.exe" add calibration/ui/ calibration/tests/unit/test_layout.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-08 ui/layout vconcat composer

cv2.vconcat camera frame (640x480) + panel (640xN) -> (480+N, 640, 3).
ValueError on width mismatch. Coverage 90%+. Total tests: 346 passed."
```

### T-CAL-08 完成判据
- [ ] 4 测试 PASS + 覆盖率 ≥ 90% + 全套件 346 + commit

---

## Task T-CAL-09: ui/panel.py（UI 区渲染 + 屏幕数字键盘按钮）

**Goal:** 实现按 FlowState 渲染 UI 区图像 + 提供按钮位置/动作映射。
**Coverage gate:** ≥ 75%
**Files:**
- Create: `calibration/ui/panel.py`
- Create: `calibration/tests/unit/test_panel.py`

### Step 1: 写失败测试

- [ ] **Step 1.1: `calibration/tests/unit/test_panel.py`**

```python
"""测试 panel.render 按状态生成图像 + get_buttons 返回正确数量按钮。"""
import numpy as np
import pytest

from calibration.ui.panel import (
    Panel, Button, UIAction, FlowState, PhaseDisplayInfo,
)


def _make_panel():
    return Panel(width=640, height=240)


def test_render_waiting_to_start_returns_image():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.WAITING_TO_START_PHASE,
        phase_index=1, phase_total=5, phase_name="闭眼校准",
        instruction="请闭眼并保持 5 秒",
    )
    img = p.render(info)
    assert img.shape == (240, 640, 3)
    assert img.dtype == np.uint8


def test_waiting_to_start_has_start_and_cancel_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(state=FlowState.WAITING_TO_START_PHASE,
                            phase_index=1, phase_total=5,
                            phase_name="X", instruction="Y")
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert UIAction.PROCEED in actions
    assert UIAction.CANCEL in actions


def test_phase_summary_success_has_3_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.PHASE_SUMMARY_SUCCESS,
        phase_index=1, phase_total=5, phase_name="X", instruction="",
        summary_text="✓ 完成，138 样本",
    )
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert {UIAction.PROCEED, UIAction.RETRY_PHASE, UIAction.CANCEL} <= actions


def test_phase_summary_failed_has_3_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.PHASE_SUMMARY_FAILED,
        phase_index=1, phase_total=5, phase_name="X", instruction="",
        summary_text="✗ 失败：未完全闭眼",
    )
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert {UIAction.RETRY_PHASE, UIAction.SKIP_PHASE, UIAction.CANCEL} <= actions


def test_blink_input_has_digit_keypad_buttons():
    """BLINK_INPUT_AWAITING 状态有 0-9 + 退格 + 确认 + 取消 = 13 个按钮。"""
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.BLINK_INPUT_AWAITING,
        phase_index=4, phase_total=5, phase_name="眨眼", instruction="",
        program_blink_count=12, user_input_buffer="",
    )
    btns = p.get_buttons(info)
    digit_buttons = [b for b in btns if b.action == UIAction.DIGIT]
    assert len(digit_buttons) == 10  # 0-9
    actions = {b.action for b in btns}
    assert UIAction.BACKSPACE in actions
    assert UIAction.SUBMIT in actions
    assert UIAction.CANCEL in actions


def test_blink_input_digit_buttons_have_distinct_values():
    p = _make_panel()
    info = PhaseDisplayInfo(state=FlowState.BLINK_INPUT_AWAITING,
                            phase_index=4, phase_total=5, phase_name="X",
                            instruction="", program_blink_count=10,
                            user_input_buffer="")
    btns = p.get_buttons(info)
    digit_values = {b.digit_value for b in btns if b.action == UIAction.DIGIT}
    assert digit_values == {"0","1","2","3","4","5","6","7","8","9"}


def test_button_contains_hit_test():
    """Button.contains(x, y) 命中测试。"""
    b = Button(label="X", rect=(10, 20, 100, 50), action=UIAction.PROCEED)
    assert b.contains(50, 40) is True
    assert b.contains(5, 40) is False  # x 在 rect 外
    assert b.contains(50, 80) is False  # y 在 rect 外


def test_final_summary_has_3_buttons():
    p = _make_panel()
    info = PhaseDisplayInfo(
        state=FlowState.FINAL_SUMMARY,
        phase_index=5, phase_total=5, phase_name="校准完成", instruction="",
        final_summary={"ear_mean": 0.30, "cqs": 0.85},
    )
    btns = p.get_buttons(info)
    actions = {b.action for b in btns}
    assert UIAction.PROCEED in actions       # 继续 → 主监测
    assert UIAction.RETRY_PHASE in actions   # 重新校准
    assert UIAction.CANCEL in actions        # 退出
```

- [ ] **Step 1.2: 运行确认失败**

### Step 2: 实现 panel.py

- [ ] **Step 2.1: `calibration/ui/panel.py`**

```python
"""calibration/ui/panel.py — UI 区渲染 + 按钮布局

按 FlowState 渲染对应 UI（PIL 中文 + cv2 矩形）。
所有按钮位置由 get_buttons 暴露，input_handler 据此做鼠标命中。

设计依据：spec §2.4 + 决策 C2/F1（鼠标主导 + 实时反馈）。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# 字体路径（沿用 gui/overlay.py 现有路径）
_FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
try:
    _FONT_LARGE = ImageFont.truetype(_FONT_PATH, 28)
    _FONT_MED = ImageFont.truetype(_FONT_PATH, 20)
    _FONT_SMALL = ImageFont.truetype(_FONT_PATH, 16)
except Exception:
    _FONT_LARGE = _FONT_MED = _FONT_SMALL = None


class FlowState(Enum):
    WAITING_TO_START_PHASE = "waiting_start"
    PHASE_RUNNING = "running"
    PHASE_SUMMARY_SUCCESS = "summary_success"
    PHASE_SUMMARY_FAILED = "summary_failed"
    BLINK_INPUT_AWAITING = "blink_input"
    FINAL_SUMMARY = "final_summary"


class UIAction(Enum):
    NONE = "none"
    PROCEED = "proceed"
    RETRY_PHASE = "retry"
    SKIP_PHASE = "skip"
    CANCEL = "cancel"
    DIGIT = "digit"
    BACKSPACE = "backspace"
    SUBMIT = "submit"


@dataclass
class Button:
    label: str
    rect: Tuple[int, int, int, int]    # (x, y, w, h)
    action: UIAction
    style: str = "primary"             # "primary" 绿 / "danger" 红 / "neutral" 灰
    digit_value: Optional[str] = None  # 仅当 action=DIGIT

    def contains(self, x: int, y: int) -> bool:
        bx, by, bw, bh = self.rect
        return bx <= x < bx + bw and by <= y < by + bh


@dataclass
class PhaseDisplayInfo:
    state: FlowState
    phase_index: int           # 1-5
    phase_total: int           # 5
    phase_name: str
    instruction: str
    remaining_sec: float = 0.0
    sample_count: int = 0
    quality_hint: str = ""
    summary_text: str = ""
    program_blink_count: int = 0
    user_input_buffer: str = ""
    final_summary: Dict[str, Any] = field(default_factory=dict)


_STYLE_COLOR = {
    "primary": (50, 200, 70),    # 绿 (BGR)
    "danger":  (50, 50, 220),    # 红
    "neutral": (120, 120, 120),  # 灰
}


class Panel:
    """UI 区渲染器。"""

    def __init__(self, width: int = 640, height: int = 240):
        self.width = width
        self.height = height

    def render(self, info: PhaseDisplayInfo) -> np.ndarray:
        """生成 (height, width, 3) BGR 图像。"""
        img = np.full((self.height, self.width, 3), 20, dtype=np.uint8)  # 深色背景
        # 顶部边框
        cv2.line(img, (0, 0), (self.width, 0), (0, 200, 100), 2)

        if info.state == FlowState.WAITING_TO_START_PHASE:
            self._render_waiting(img, info)
        elif info.state == FlowState.PHASE_RUNNING:
            self._render_running(img, info)
        elif info.state == FlowState.PHASE_SUMMARY_SUCCESS:
            self._render_summary(img, info, success=True)
        elif info.state == FlowState.PHASE_SUMMARY_FAILED:
            self._render_summary(img, info, success=False)
        elif info.state == FlowState.BLINK_INPUT_AWAITING:
            self._render_blink_input(img, info)
        elif info.state == FlowState.FINAL_SUMMARY:
            self._render_final(img, info)

        # 渲染所有按钮
        for btn in self.get_buttons(info):
            self._draw_button(img, btn)

        return img

    def get_buttons(self, info: PhaseDisplayInfo) -> List[Button]:
        """返回当前状态下所有可点击按钮。"""
        if info.state == FlowState.WAITING_TO_START_PHASE:
            return [
                Button("▶ 开始", (40, 170, 160, 50), UIAction.PROCEED, "primary"),
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.PHASE_RUNNING:
            return [
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.PHASE_SUMMARY_SUCCESS:
            return [
                Button("▶ 继续", (40, 170, 160, 50), UIAction.PROCEED, "primary"),
                Button("↺ 重做", (240, 170, 160, 50), UIAction.RETRY_PHASE, "neutral"),
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.PHASE_SUMMARY_FAILED:
            return [
                Button("↺ 重做", (40, 170, 160, 50), UIAction.RETRY_PHASE, "neutral"),
                Button("→ 跳过", (240, 170, 160, 50), UIAction.SKIP_PHASE, "neutral"),
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.BLINK_INPUT_AWAITING:
            return self._build_keypad_buttons()
        if info.state == FlowState.FINAL_SUMMARY:
            return [
                Button("▶ 继续 → 主监测", (20, 170, 240, 50), UIAction.PROCEED, "primary"),
                Button("↺ 重新校准", (280, 170, 160, 50), UIAction.RETRY_PHASE, "neutral"),
                Button("退出", (460, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        return []

    def _build_keypad_buttons(self) -> List[Button]:
        """0-9 数字键盘 + 退格 + 确认 + 取消。"""
        btns: List[Button] = []
        # 3×4 网格：7 8 9 / 4 5 6 / 1 2 3 / 0 . .
        digits = [
            ("7", 0, 0), ("8", 1, 0), ("9", 2, 0),
            ("4", 0, 1), ("5", 1, 1), ("6", 2, 1),
            ("1", 0, 2), ("2", 1, 2), ("3", 2, 2),
            ("0", 1, 3),
        ]
        bw, bh = 50, 40
        x0, y0 = 60, 70
        gap = 6
        for d, cx, cy in digits:
            x = x0 + cx * (bw + gap)
            y = y0 + cy * (bh + gap)
            btns.append(Button(d, (x, y, bw, bh), UIAction.DIGIT, "neutral", digit_value=d))
        # 退格 / 确认 / 取消（右侧）
        btns.append(Button("⌫ 退格", (260, 70, 110, 40), UIAction.BACKSPACE, "neutral"))
        btns.append(Button("✓ 确认", (260, 120, 110, 40), UIAction.SUBMIT, "primary"))
        btns.append(Button("取消", (260, 170, 110, 40), UIAction.CANCEL, "danger"))
        return btns

    def _draw_button(self, img: np.ndarray, btn: Button) -> None:
        x, y, w, h = btn.rect
        color = _STYLE_COLOR.get(btn.style, (100, 100, 100))
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
        # 文字（PIL）
        if _FONT_MED:
            self._put_text(img, btn.label, (x + 10, y + 8), _FONT_MED, (255, 255, 255))

    def _put_text(self, img: np.ndarray, text: str, pos: Tuple[int, int],
                  font, color_bgr: Tuple[int, int, int]) -> None:
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        draw.text(pos, text, font=font, fill=color_bgr[::-1])
        img[:] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    def _render_waiting(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, f"[阶段 {info.phase_index}/{info.phase_total}] {info.phase_name}",
                           (20, 20), _FONT_LARGE, (0, 255, 100))
            self._put_text(img, info.instruction, (20, 70), _FONT_MED, (220, 220, 220))
            self._put_text(img, "准备好了吗？点'开始'", (20, 110), _FONT_SMALL, (180, 180, 180))

    def _render_running(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, f"[阶段 {info.phase_index}/{info.phase_total}] {info.phase_name}",
                           (20, 20), _FONT_LARGE, (0, 255, 100))
            self._put_text(img, f"剩余 {info.remaining_sec:.1f}s", (450, 20),
                           _FONT_LARGE, (255, 200, 0))
            self._put_text(img, info.quality_hint, (20, 70), _FONT_MED, (220, 220, 220))
            if info.sample_count > 0:
                self._put_text(img, f"📊 已采集 {info.sample_count} 样本",
                               (20, 110), _FONT_SMALL, (0, 200, 255))

    def _render_summary(self, img: np.ndarray, info: PhaseDisplayInfo, success: bool) -> None:
        color = (0, 255, 100) if success else (50, 50, 230)
        icon = "✓" if success else "✗"
        if _FONT_LARGE:
            self._put_text(img, f"{icon} 阶段 {info.phase_index} {'完成' if success else '失败'}",
                           (20, 20), _FONT_LARGE, color)
            self._put_text(img, info.summary_text, (20, 70), _FONT_MED, (220, 220, 220))

    def _render_blink_input(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, f"程序检测到 {info.program_blink_count} 次",
                           (20, 10), _FONT_MED, (255, 200, 0))
            self._put_text(img, f"你的实际次数：[ {info.user_input_buffer} ]_",
                           (20, 40), _FONT_LARGE, (0, 255, 255))

    def _render_final(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, "✅ 校准完成", (20, 10), _FONT_LARGE, (0, 255, 100))
            y = 50
            for k, v in info.final_summary.items():
                self._put_text(img, f"{k}: {v}", (20, y), _FONT_SMALL, (220, 220, 220))
                y += 22
```

- [ ] **Step 2.2: 运行**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_panel.py -v
```

Expected: 8 passed

### Step 3-5: 覆盖率 + 全测试 + commit

- [ ] **Step 3.1: 覆盖率 ≥ 75%**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_panel.py --cov=calibration/ui/panel --cov-report=term-missing -q
```

- [ ] **Step 3.2: 全测试 354 passed (346+8)**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
```

- [ ] **Step 3.3: 视觉 spike — 每状态截图 review**

```bash
.venv312/Scripts/python.exe -c "
import cv2
from calibration.ui.panel import Panel, PhaseDisplayInfo, FlowState
p = Panel()
states = [FlowState.WAITING_TO_START_PHASE, FlowState.PHASE_RUNNING,
          FlowState.PHASE_SUMMARY_SUCCESS, FlowState.PHASE_SUMMARY_FAILED,
          FlowState.BLINK_INPUT_AWAITING, FlowState.FINAL_SUMMARY]
for s in states:
    info = PhaseDisplayInfo(state=s, phase_index=2, phase_total=5,
                            phase_name='闭眼校准', instruction='请闭眼 5 秒',
                            remaining_sec=3.5, sample_count=87,
                            quality_hint='闭眼中...', summary_text='✓ 138 样本',
                            program_blink_count=12, user_input_buffer='15',
                            final_summary={'ear_mean': 0.30, 'cqs': 0.85})
    img = p.render(info)
    cv2.imwrite(f'/tmp/panel_{s.value}.png', img)
print('生成 6 张截图到 /tmp/panel_*.png — 人工 review')
"
```

Expected: 6 张 PNG 保存到临时目录（D1 人工 review 截图无明显错位/乱码）

- [ ] **Step 3.4: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/ui/panel.py calibration/tests/unit/test_panel.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-09 panel.py UI rendering

UI region (640x240) rendering by FlowState:
- WAITING/RUNNING/SUMMARY_SUCCESS/SUMMARY_FAILED/BLINK_INPUT/FINAL_SUMMARY
- On-screen 0-9 digit keypad for IME-free input
- 3 button styles (primary green / danger red / neutral grey)
Coverage: 75%+ on panel.py. Total tests: 354 passed."
```

### T-CAL-09 完成判据
- [ ] 8 测试 PASS + 覆盖率 ≥ 75% + 全套件 354 + 6 张截图 review + commit

---

## Task T-CAL-10: input_handler.py（鼠标 + 键盘 + IME 兼容）

**Goal:** 统一鼠标点击 + 键盘输入，鼠标点击优先。彻底消除 Windows IME 影响。
**Coverage gate:** ≥ 95%
**Files:**
- Create: `calibration/input_handler.py`
- Create: `calibration/_ime.py`
- Create: `calibration/tests/unit/test_input_handler.py`

### Step 1: 写失败测试

- [ ] **Step 1.1: `calibration/tests/unit/test_input_handler.py`**

```python
"""测试 InputHandler — 鼠标 + 键盘（IME 兼容）。"""
import pytest
from unittest.mock import patch

from calibration.input_handler import InputHandler
from calibration.ui.panel import Button, UIAction, FlowState


def _make_buttons():
    return [
        Button("开始", (10, 10, 100, 50), UIAction.PROCEED, "primary"),
        Button("0", (200, 70, 50, 40), UIAction.DIGIT, "neutral", digit_value="0"),
        Button("5", (200, 110, 50, 40), UIAction.DIGIT, "neutral", digit_value="5"),
        Button("确认", (300, 100, 100, 40), UIAction.SUBMIT, "primary"),
        Button("取消", (400, 10, 100, 40), UIAction.CANCEL, "danger"),
    ]


def test_mouse_click_hits_proceed_button():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._click_buffer = (50, 30)  # 命中"开始"
    with patch("cv2.waitKey", return_value=255):  # 无键盘输入
        action, digit = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED
    assert digit is None


def test_mouse_click_hits_digit_5():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._click_buffer = (220, 125)
    with patch("cv2.waitKey", return_value=255):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.DIGIT
    assert digit == "5"


def test_mouse_click_misses_all_buttons():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._click_buffer = (999, 999)
    with patch("cv2.waitKey", return_value=255):
        action, digit = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.NONE


def test_keyboard_digit_in_blink_input_state():
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=ord('7')):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.DIGIT
    assert digit == "7"


def test_keyboard_digit_ignored_outside_blink_input():
    """非 BLINK_INPUT 状态下，键盘数字键被忽略（IME 兼容设计）。"""
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=ord('5')):
        action, digit = h.poll(FlowState.PHASE_RUNNING)
    assert action == UIAction.NONE


def test_keyboard_enter_submits_in_blink_input():
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=13):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.SUBMIT


def test_keyboard_backspace_in_blink_input():
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    with patch("cv2.waitKey", return_value=8):
        action, digit = h.poll(FlowState.BLINK_INPUT_AWAITING)
    assert action == UIAction.BACKSPACE


def test_keyboard_esc_works_in_any_state():
    """ESC 是所有状态的紧急取消兜底。"""
    h = InputHandler.__new__(InputHandler)
    h._buttons = []
    h._click_buffer = None
    for state in [FlowState.PHASE_RUNNING, FlowState.WAITING_TO_START_PHASE,
                  FlowState.FINAL_SUMMARY]:
        with patch("cv2.waitKey", return_value=27):
            action, _ = h.poll(state)
        assert action == UIAction.CANCEL, f"ESC 在 {state} 应触发 CANCEL"


def test_mouse_takes_priority_over_keyboard():
    """鼠标点击 vs 键盘同时：鼠标优先（视觉操作更明确）。"""
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._click_buffer = (50, 30)  # 点"开始"
    with patch("cv2.waitKey", return_value=27):  # ESC
        action, _ = h.poll(FlowState.WAITING_TO_START_PHASE)
    assert action == UIAction.PROCEED  # 不是 CANCEL


def test_click_buffer_cleared_after_poll():
    h = InputHandler.__new__(InputHandler)
    h._buttons = _make_buttons()
    h._click_buffer = (50, 30)
    with patch("cv2.waitKey", return_value=255):
        h.poll(FlowState.WAITING_TO_START_PHASE)
    assert h._click_buffer is None
```

- [ ] **Step 1.2: 运行确认失败**

### Step 2: 实现 input_handler.py + _ime.py

- [ ] **Step 2.1: `calibration/_ime.py`**

```python
"""calibration/_ime.py — Win32 IME 禁用兜底（失败也无所谓）

仅作锦上添花。主输入路径是鼠标点屏幕键盘，不依赖此函数。

设计依据：spec §2.7 鼠标主导 + IME 可选禁用。
"""
import logging

logger = logging.getLogger("eyefocus.calibration.ime")


def try_disable_ime(window_name: str) -> bool:
    """尝试禁用 IME。失败时返回 False，不抛异常。"""
    try:
        import ctypes
        # cv2 窗口的 HWND 获取在 OpenCV 中不直接暴露，这里只是占位
        # 实际生产可用 ctypes 调 user32.FindWindowW 找窗口，再 imm32.ImmAssociateContext
        # 因平台兼容性差，此函数允许永远 return False
        return False
    except Exception as e:
        logger.warning("IME 禁用失败（不影响主功能）: %s", e)
        return False
```

- [ ] **Step 2.2: `calibration/input_handler.py`**

```python
"""calibration/input_handler.py — 统一鼠标 + 键盘输入

主输入路径：鼠标点击（彻底消除 Windows IME 影响）。
键盘只作可选加速 — BLINK_INPUT_AWAITING 状态收数字/退格/Enter，其他状态仅 ESC。

设计依据：spec §2.7 + 决策 C2 鼠标主导。
"""
from typing import List, Optional, Tuple

import cv2

from calibration.ui.panel import Button, FlowState, UIAction


class InputHandler:
    """每帧调 poll() 获取鼠标/键盘动作。"""

    def __init__(self, window_name: str):
        self._window_name = window_name
        self._buttons: List[Button] = []
        self._click_buffer: Optional[Tuple[int, int]] = None
        cv2.setMouseCallback(window_name, self._on_mouse)

    def register_buttons(self, buttons: List[Button]) -> None:
        """每帧由 panel 注册当前可见按钮。"""
        self._buttons = buttons

    def poll(self, state: FlowState) -> Tuple[UIAction, Optional[str]]:
        """返回 (动作, 数字字符)。数字仅 DIGIT 动作时有效。"""
        # 1. 鼠标点击优先
        if self._click_buffer is not None:
            x, y = self._click_buffer
            self._click_buffer = None
            for btn in self._buttons:
                if btn.contains(x, y):
                    if btn.action == UIAction.DIGIT:
                        return (UIAction.DIGIT, btn.digit_value)
                    return (btn.action, None)

        # 2. 键盘（IME 激活时可能收不到，但有就用）
        key = cv2.waitKey(1) & 0xFF

        # ESC 任何状态都触发 CANCEL（兜底）
        if key == 27:
            return (UIAction.CANCEL, None)

        # 仅 BLINK_INPUT_AWAITING 接受数字/退格/Enter
        if state == FlowState.BLINK_INPUT_AWAITING:
            if ord('0') <= key <= ord('9'):
                return (UIAction.DIGIT, chr(key))
            if key == 8:
                return (UIAction.BACKSPACE, None)
            if key == 13:
                return (UIAction.SUBMIT, None)

        return (UIAction.NONE, None)

    def _on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self._click_buffer = (x, y)
```

- [ ] **Step 2.3: 运行 + 覆盖率 + 全测试 + commit**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_input_handler.py -v
# Expected: 10 passed
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_input_handler.py --cov=calibration/input_handler --cov-report=term-missing -q
# Expected: ≥ 95%
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
# Expected: 364 passed (354+10)
"/c/Program Files/Git/cmd/git.exe" add calibration/input_handler.py calibration/_ime.py calibration/tests/unit/test_input_handler.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-10 input_handler (IME-free)

Mouse-priority input handler:
- Click hits on registered buttons -> action+digit
- Keyboard ONLY in BLINK_INPUT_AWAITING (digits/backspace/enter)
- ESC works as emergency cancel in any state
- IME-affected keyboard NEVER blocks user (mouse always works)

_ime.py: optional Win32 IME disable fallback (returns False is acceptable).

Coverage: 95%+ on input_handler.py. Total tests: 364 passed."
```

### T-CAL-10 完成判据 / 真机 IME 验证（T-CAL-13 spike 时做）
- [ ] 10 测试 PASS + 覆盖率 ≥ 95% + 全套件 364 + commit
- [ ] IME 实战验证延迟到 T-CAL-13（需 flow.py 跑通才能真机测）

---

## Task T-CAL-11: audio/beep.py + audio/tts.py

**Goal:** 蜂鸣 + 中文 TTS 双轨音频反馈。
**Coverage gate:** ≥ 80%
**Files:**
- Create: `calibration/audio/__init__.py` (空)
- Create: `calibration/audio/beep.py`
- Create: `calibration/audio/tts.py`
- Create: `calibration/tests/unit/test_audio_beep.py`
- Create: `calibration/tests/unit/test_audio_tts.py`
- Modify: `requirements.txt`（追加 pyttsx3）

### Step 1: 包目录 + 加依赖

- [ ] **Step 1.1:**

```bash
.venv312/Scripts/python.exe -c "
import os
os.makedirs('calibration/audio', exist_ok=True)
open('calibration/audio/__init__.py', 'a').close()
print('OK')
"
```

- [ ] **Step 1.2: requirements.txt 追加 pyttsx3**

```bash
.venv312/Scripts/python.exe -c "
text = open('requirements.txt', encoding='utf-8').read()
if 'pyttsx3' not in text:
    if not text.endswith('\n'):
        text += '\n'
    text += 'pyttsx3>=2.90\n'
    open('requirements.txt', 'w', encoding='utf-8').write(text)
    print('Added pyttsx3>=2.90')
else:
    print('Already present')
"
```

- [ ] **Step 1.3: 安装 pyttsx3**

```bash
.venv312/Scripts/python.exe -m pip install pyttsx3>=2.90
```

### Step 2: beep.py 测试 + 实现

- [ ] **Step 2.1: `calibration/tests/unit/test_audio_beep.py`**

```python
"""测试 Beep — 封装 winsound 调用，非 Windows 时降级。"""
import sys
import pytest
from unittest.mock import patch, MagicMock


def test_beep_methods_exist():
    from calibration.audio.beep import Beep
    b = Beep()
    assert callable(b.phase_start)
    assert callable(b.phase_success)
    assert callable(b.phase_failed)
    assert callable(b.countdown_tick)
    assert callable(b.calibration_complete)


def test_beep_phase_start_calls_winsound():
    mock_winsound = MagicMock()
    with patch.dict(sys.modules, {'winsound': mock_winsound}):
        # 重新 import 让 winsound mock 生效
        import importlib
        from calibration.audio import beep as beep_module
        importlib.reload(beep_module)
        b = beep_module.Beep()
        b.phase_start()
        mock_winsound.Beep.assert_called_once()
        # 参数应该是 (频率, 时长_ms)
        args = mock_winsound.Beep.call_args[0]
        assert len(args) == 2
        assert args[0] > 0  # 频率
        assert args[1] > 0  # 时长


def test_beep_calibration_complete_plays_2_tones():
    mock_winsound = MagicMock()
    with patch.dict(sys.modules, {'winsound': mock_winsound}):
        import importlib
        from calibration.audio import beep as beep_module
        importlib.reload(beep_module)
        b = beep_module.Beep()
        b.calibration_complete()
        # 双音上扬：调 2 次
        assert mock_winsound.Beep.call_count == 2


def test_beep_no_winsound_fallback_no_crash():
    """winsound 不可用时（非 Windows），所有方法 no-op 不崩溃。"""
    with patch.dict(sys.modules, {'winsound': None}):
        import importlib
        from calibration.audio import beep as beep_module
        importlib.reload(beep_module)
        b = beep_module.Beep()
        # 不应抛异常
        b.phase_start()
        b.phase_success()
        b.phase_failed()
        b.countdown_tick()
        b.calibration_complete()
```

- [ ] **Step 2.2: `calibration/audio/beep.py`**

```python
"""calibration/audio/beep.py — winsound 蜂鸣封装

非 Windows 环境时所有方法 no-op + 日志警告。

设计依据：spec §2.5 + 决策 S2 蜂鸣 + TTS 双轨。
"""
import logging

logger = logging.getLogger("eyefocus.calibration.audio")

try:
    import winsound  # type: ignore[import]
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False
    logger.warning("winsound 不可用（非 Windows），蜂鸣音降级为 no-op")


class Beep:
    """语义化蜂鸣声接口。"""

    def phase_start(self) -> None:
        """阶段开始：短促高频。"""
        if _HAS_WINSOUND:
            winsound.Beep(1000, 200)

    def phase_success(self) -> None:
        """阶段成功：单声高音。"""
        if _HAS_WINSOUND:
            winsound.Beep(1500, 300)

    def phase_failed(self) -> None:
        """阶段失败：单声低音长。"""
        if _HAS_WINSOUND:
            winsound.Beep(300, 800)

    def countdown_tick(self) -> None:
        """倒计时最后 3 秒每秒一次。"""
        if _HAS_WINSOUND:
            winsound.Beep(600, 100)

    def calibration_complete(self) -> None:
        """校准完成：双音上扬。"""
        if _HAS_WINSOUND:
            winsound.Beep(800, 200)
            winsound.Beep(1200, 400)
```

### Step 3: tts.py 测试 + 实现

- [ ] **Step 3.1: `calibration/tests/unit/test_audio_tts.py`**

```python
"""测试 TTS — pyttsx3 封装，初始化失败时降级。"""
import sys
from unittest.mock import MagicMock, patch


def test_tts_say_calls_engine():
    mock_engine = MagicMock()
    mock_engine.getProperty.return_value = []
    with patch("pyttsx3.init", return_value=mock_engine):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.say("请闭眼")
        # say 是异步的，等待线程
        for thr in t._threads:
            thr.join(timeout=2)
        # mock 引擎应被调
        assert mock_engine.say.called or mock_engine.runAndWait.called


def test_tts_init_failure_fallback():
    """pyttsx3.init 抛异常时，TTS 实例创建不应崩溃，say 为 no-op。"""
    with patch("pyttsx3.init", side_effect=Exception("SAPI 不可用")):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        assert t._engine is None
        # 不抛异常
        t.say("test")


def test_tts_shutdown_safe_even_if_no_engine():
    with patch("pyttsx3.init", side_effect=Exception("fail")):
        from calibration.audio import tts as tts_module
        import importlib
        importlib.reload(tts_module)
        t = tts_module.TTS()
        t.shutdown()  # 不抛
```

- [ ] **Step 3.2: `calibration/audio/tts.py`**

```python
"""calibration/audio/tts.py — pyttsx3 中文 TTS 封装

异步说话（不阻塞主循环）。初始化失败时 _engine=None，say() 静默。

设计依据：spec §2.6 + 决策 S2 中文 TTS。
"""
import logging
import threading
from typing import List, Optional

logger = logging.getLogger("eyefocus.calibration.audio")


class TTS:
    def __init__(self, rate: int = 180):
        self._engine = None
        self._lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._engine.setProperty('rate', rate)
            # 优先选中文音色
            for v in self._engine.getProperty('voices'):
                if hasattr(v, 'id') and ('chinese' in v.id.lower() or 'zh' in v.id.lower()):
                    self._engine.setProperty('voice', v.id)
                    break
        except Exception as e:
            logger.warning("TTS 初始化失败，将降级为静默: %s", e)
            self._engine = None

    def say(self, text: str) -> None:
        """异步说话，不阻塞主循环。"""
        if self._engine is None:
            return
        thr = threading.Thread(target=self._do_say, args=(text,), daemon=True)
        thr.start()
        self._threads.append(thr)
        # 清理已完成的线程
        self._threads = [t for t in self._threads if t.is_alive()]

    def _do_say(self, text: str) -> None:
        with self._lock:
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as e:
                logger.warning("TTS 播放失败: %s", e)

    def shutdown(self) -> None:
        """关闭 TTS 引擎。"""
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass
```

### Step 4: 运行 + 覆盖率 + 全测试 + 真机听音 + commit

- [ ] **Step 4.1:**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_audio_beep.py calibration/tests/unit/test_audio_tts.py -v
# Expected: 7 passed (4+3)
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_audio_beep.py calibration/tests/unit/test_audio_tts.py --cov=calibration/audio --cov-report=term-missing -q
# Expected: 80%+
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
# Expected: 371 passed (364+7)
```

- [ ] **Step 4.2: 真机听音验证（关键）**

```bash
.venv312/Scripts/python.exe -c "
from calibration.audio.beep import Beep
from calibration.audio.tts import TTS
import time
b = Beep()
t = TTS()
print('蜂鸣 phase_start ↓'); b.phase_start(); time.sleep(0.5)
print('蜂鸣 success ↓'); b.phase_success(); time.sleep(0.5)
print('蜂鸣 failed ↓'); b.phase_failed(); time.sleep(1.0)
print('TTS 测试 ↓'); t.say('校准模块测试，能听到吗')
time.sleep(4)
print('全部完成')
"
```

Expected: D1 听到 3 种不同蜂鸣 + 中文 TTS 念出"校准模块测试，能听到吗"

- [ ] **Step 4.3: commit**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/audio/ requirements.txt calibration/tests/unit/test_audio_*.py
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-11 audio (beep + Chinese TTS)

audio/beep.py: winsound semantic methods (phase_start/success/failed/...)
  - Non-Windows fallback: no-op + log warning
audio/tts.py: pyttsx3 async wrapper, threaded say()
  - SAPI init failure: _engine=None, say()=no-op
requirements.txt: + pyttsx3>=2.90

Coverage: 80%+ on audio/. Total tests: 371 passed. 真机听音确认 OK."
```

### T-CAL-11 完成判据
- [ ] 7 测试 PASS + 覆盖率 ≥ 80% + 全套件 371 + 真机听音 OK + commit

---

（接下文 T-CAL-12 ~ T-CAL-14）

---

## Task T-CAL-12: flow.py（状态机编排）

**Goal:** 实现 `CalibrationFlow` 主循环 — 摄像头采集 + MediaPipe 检测 + 5 阶段驱动 + UI/Audio/Input 协同。
**Coverage gate:** ≥ 80%
**Files:**
- Create: `calibration/flow.py`
- Create: `calibration/tests/unit/test_flow.py`
- Create: `calibration/tests/integration/__init__.py` (空)
- Create: `calibration/tests/integration/test_phase_audio_ui.py`
- Create: `calibration/tests/integration/test_cancel_flow.py`

### Step 1: 创建集成测试目录

```bash
.venv312/Scripts/python.exe -c "
import os
os.makedirs('calibration/tests/integration', exist_ok=True)
open('calibration/tests/integration/__init__.py', 'a').close()
print('OK')
"
```

### Step 2: 写失败测试（unit + integration）

- [ ] **Step 2.1: `calibration/tests/unit/test_flow.py`**

```python
"""测试 CalibrationFlow 状态机转换（mock cap/face_mesh/audio/input）。"""
import pytest
from unittest.mock import MagicMock, patch

from calibration.flow import CalibrationFlow, FlowState
from calibration.config import CalibrationConfig
from calibration.ui.panel import UIAction


def _make_flow(session_id="test"):
    config = CalibrationConfig(
        auto_baseline_seconds=0.1, closed_eyes_seconds=0.1,
        open_eyes_verify_seconds=0.05, squint_seconds=0.1,
        head_direction_seconds=0.05, blink_round_seconds=0.1,
        audio_enabled=False,  # 测试时禁音频
    )
    flow = CalibrationFlow(session_id=session_id, config=config)
    return flow


def test_flow_initial_state_is_waiting():
    f = _make_flow()
    assert f._state == FlowState.WAITING_TO_START_PHASE
    assert f._current_phase_index == 0


def test_flow_phase_starts_on_proceed():
    f = _make_flow()
    f._handle_action(UIAction.PROCEED, None)
    assert f._state == FlowState.PHASE_RUNNING


def test_flow_cancel_at_any_state_returns_none():
    f = _make_flow()
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None


def test_flow_phase_complete_success_transitions_to_summary():
    f = _make_flow()
    f._handle_action(UIAction.PROCEED, None)  # → RUNNING
    # 模拟阶段成功
    f._current_phase = MagicMock()
    f._current_phase.evaluate.return_value = MagicMock(success=True, summary={"ear_mean": 0.3})
    f._on_phase_time_up()
    assert f._state == FlowState.PHASE_SUMMARY_SUCCESS


def test_flow_phase_summary_proceed_advances_to_next_phase():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._current_phase_index = 0
    f._handle_action(UIAction.PROCEED, None)
    assert f._current_phase_index == 1
    assert f._state == FlowState.WAITING_TO_START_PHASE


def test_flow_retry_resets_current_phase():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_FAILED
    f._current_phase = MagicMock()
    f._handle_action(UIAction.RETRY_PHASE, None)
    f._current_phase.reset.assert_called_once()
    assert f._state == FlowState.PHASE_RUNNING


def test_flow_skip_advances_with_default_values():
    f = _make_flow()
    f._state = FlowState.PHASE_SUMMARY_FAILED
    f._current_phase_index = 1
    f._handle_action(UIAction.SKIP_PHASE, None)
    assert f._current_phase_index == 2


def test_flow_after_all_phases_enters_final_summary():
    f = _make_flow()
    f._current_phase_index = 4  # 最后一阶段
    f._state = FlowState.PHASE_SUMMARY_SUCCESS
    f._handle_action(UIAction.PROCEED, None)
    assert f._state == FlowState.FINAL_SUMMARY


def test_flow_final_proceed_marks_accepted_done():
    f = _make_flow()
    f._state = FlowState.FINAL_SUMMARY
    f._handle_action(UIAction.PROCEED, None)
    assert f._done is True
    assert f._user_accepted is True


def test_flow_final_retry_restarts_from_phase_0():
    f = _make_flow()
    f._state = FlowState.FINAL_SUMMARY
    f._handle_action(UIAction.RETRY_PHASE, None)
    assert f._current_phase_index == 0
    assert f._state == FlowState.WAITING_TO_START_PHASE


def test_flow_blink_input_digit_accumulates_buffer():
    f = _make_flow()
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._handle_action(UIAction.DIGIT, "1")
    f._handle_action(UIAction.DIGIT, "5")
    assert f._input_buffer == "15"


def test_flow_blink_input_backspace_removes_last():
    f = _make_flow()
    f._state = FlowState.BLINK_INPUT_AWAITING
    f._input_buffer = "15"
    f._handle_action(UIAction.BACKSPACE, None)
    assert f._input_buffer == "1"
```

- [ ] **Step 2.2: `calibration/tests/integration/test_phase_audio_ui.py`**

```python
"""集成测试：阶段切换时 UI/音频同步触发。"""
from unittest.mock import MagicMock

from calibration.flow import CalibrationFlow, FlowState
from calibration.config import CalibrationConfig
from calibration.ui.panel import UIAction


def test_phase_start_triggers_tts_intro():
    config = CalibrationConfig(audio_enabled=True, auto_baseline_seconds=0.1)
    f = CalibrationFlow(session_id="t", config=config)
    f._tts = MagicMock()
    f._beep = MagicMock()
    f._handle_action(UIAction.PROCEED, None)
    # 阶段开始应调 TTS + beep
    f._tts.say.assert_called()
    f._beep.phase_start.assert_called_once()


def test_closed_eyes_complete_tts_contains_open_keyword():
    """BUG 3 修复回归：闭眼阶段 tts_complete 必含'睁眼'。"""
    config = CalibrationConfig(audio_enabled=True,
                              auto_baseline_seconds=0.05,
                              closed_eyes_seconds=0.05)
    f = CalibrationFlow(session_id="t", config=config)
    f._tts = MagicMock()
    f._beep = MagicMock()
    # 跳到 closed_eyes 阶段
    f._current_phase_index = 1
    f._current_phase = f._build_phase(1)
    f._state = FlowState.PHASE_RUNNING
    # 模拟时间到
    f._current_phase.evaluate = MagicMock(return_value=MagicMock(success=True, summary={}))
    f._on_phase_time_up()
    # TTS 应念含"睁眼"的话
    all_tts_calls = " ".join(c.args[0] for c in f._tts.say.call_args_list)
    assert "睁眼" in all_tts_calls
```

- [ ] **Step 2.3: `calibration/tests/integration/test_cancel_flow.py`**

```python
"""集成测试：取消路径（ESC / 点取消 / 关窗）。"""
from unittest.mock import MagicMock

from calibration.flow import CalibrationFlow, FlowState
from calibration.config import CalibrationConfig
from calibration.ui.panel import UIAction


def test_cancel_at_waiting_returns_none():
    f = CalibrationFlow(session_id="t", config=CalibrationConfig())
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None


def test_cancel_at_running_returns_none():
    f = CalibrationFlow(session_id="t", config=CalibrationConfig())
    f._state = FlowState.PHASE_RUNNING
    f._current_phase_index = 2
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None


def test_cancel_at_final_summary_returns_none():
    """E1 设计：FINAL_SUMMARY 阶段点'退出'也是 CANCEL = 返回 None。"""
    f = CalibrationFlow(session_id="t", config=CalibrationConfig())
    f._state = FlowState.FINAL_SUMMARY
    f._handle_action(UIAction.CANCEL, None)
    assert f._cancelled is True
    assert f._compute_result() is None
```

### Step 3: 实现 flow.py

- [ ] **Step 3.1: `calibration/flow.py`**

```python
"""calibration/flow.py — CalibrationFlow 编排器

单线程主循环 + 状态机：
  WAITING_TO_START_PHASE → PHASE_RUNNING → PHASE_SUMMARY_(SUCCESS|FAILED)
  → 推进/重做/跳过/取消 → 下一阶段 → ... → FINAL_SUMMARY → DONE / CANCELLED

设计依据：spec §3.1 主循环 + §3.2 状态机。
"""
import logging
import time
from datetime import datetime
from typing import List, Optional

import cv2

from calibration.audio.beep import Beep
from calibration.audio.tts import TTS
from calibration.config import CalibrationConfig
from calibration.input_handler import InputHandler
from calibration.phases.auto_baseline import AutoBaselinePhase
from calibration.phases.base import Phase, PhaseResult
from calibration.phases.blink_count import BlinkCountPhase, BlinkCountState
from calibration.phases.closed_eyes import ClosedEyesPhase
from calibration.phases.head_pose import HeadPosePhase
from calibration.phases.squint import SquintPhase
from calibration.result import (
    BlinkCalibrationRound, CalibrationResult, CalibrationSignal,
)
from calibration.ui.layout import compose
from calibration.ui.panel import (
    FlowState, Panel, PhaseDisplayInfo, UIAction,
)

logger = logging.getLogger("eyefocus.calibration.flow")

WINDOW_NAME = "EyeFocus 校准"


class CalibrationFlow:
    """完整校准流程编排。"""

    def __init__(self, session_id: str, config: CalibrationConfig):
        self.session_id = session_id
        self.config = config

        self._state: FlowState = FlowState.WAITING_TO_START_PHASE
        self._current_phase_index: int = 0
        self._current_phase: Optional[Phase] = None
        self._phase_start_time: float = 0.0
        self._phase_results: List[PhaseResult] = [None] * 5  # type: ignore[list-item]
        self._input_buffer: str = ""
        self._cancelled: bool = False
        self._done: bool = False
        self._user_accepted: bool = False
        self._consecutive_failures: int = 0

        # 子系统（运行时注入；测试时 mock）
        self._cap = None
        self._face_detector = None
        self._beep = Beep()
        self._tts = TTS(rate=config.tts_rate) if config.audio_enabled else _MutedTTS()
        self._panel = Panel(width=640, height=config.ui_panel_height_px)
        self._input: Optional[InputHandler] = None

        # 初始化第 0 阶段
        self._current_phase = self._build_phase(0)

    def run(self) -> Optional[CalibrationResult]:
        """主入口 — 阻塞运行直到完成 / 取消 / 异常。"""
        try:
            self._setup()
            while not (self._done or self._cancelled):
                self._tick_once()
            return self._compute_result() if self._user_accepted else None
        except Exception:
            logger.exception("校准流程崩溃")
            return None
        finally:
            self._teardown()

    def _setup(self) -> None:
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            raise RuntimeError("无法打开摄像头")
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        self._input = InputHandler(WINDOW_NAME)
        # 初始化 face detector（沿用主项目模块，默认参数与 main.py 一致；
        # FaceMeshDetector 默认 running_mode="video"，无需传）
        from detector.face_mesh import create_face_mesh_detector
        self._face_detector = create_face_mesh_detector()

    def _teardown(self) -> None:
        if self._cap is not None:
            self._cap.release()
        try:
            cv2.destroyWindow(WINDOW_NAME)
        except Exception:
            pass
        self._tts.shutdown()

    def _tick_once(self) -> None:
        """一帧主循环。"""
        ret, frame = self._cap.read()
        if not ret:
            return

        # 检测
        ear, yaw, pitch = self._extract_metrics(frame)

        # 喂当前阶段
        if self._state == FlowState.PHASE_RUNNING and self._current_phase is not None:
            elapsed = time.time() - self._phase_start_time
            self._current_phase.feed_frame(ear, yaw, pitch, elapsed)

            # 特殊：BlinkCount 阶段处理用户输入触发
            if isinstance(self._current_phase, BlinkCountPhase):
                round_elapsed = elapsed - (self._current_phase.current_round - 1) * self.config.blink_round_seconds
                if round_elapsed >= self.config.blink_round_seconds:
                    self._current_phase.on_round_time_up()
                    self._state = FlowState.BLINK_INPUT_AWAITING
                    self._tts.say("请输入你眨眼的次数")
            else:
                if self._current_phase.is_complete(elapsed):
                    self._on_phase_time_up()

        # 渲染
        info = self._build_display_info()
        panel_img = self._panel.render(info)
        composed = compose(frame, panel_img)
        cv2.imshow(WINDOW_NAME, composed)

        # 注册按钮 + 收输入
        self._input.register_buttons(self._panel.get_buttons(info))
        action, digit = self._input.poll(self._state)

        # 检查窗口被关
        if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
            self._cancelled = True
            return

        self._handle_action(action, digit)

    def _extract_metrics(self, frame):
        """从帧中提取 EAR/yaw/pitch（沿用主项目模块）。"""
        if self._face_detector is None:
            return (None, None, None)
        try:
            face_result = self._face_detector.detect(frame)
        except Exception:
            return (None, None, None)
        if not face_result or not face_result.detected:
            return (None, None, None)
        # 简化版：实际生产应同 main.py 一致
        from detector.eye_aspect import compute_ear_from_landmarks
        from detector.head_pose import compute_head_pose_from_matrix
        try:
            ear = compute_ear_from_landmarks(face_result.landmarks)
        except Exception:
            ear = None
        try:
            yaw, pitch, _roll = compute_head_pose_from_matrix(face_result.transformation_matrix)
        except Exception:
            yaw, pitch = None, None
        return (ear, yaw, pitch)

    def _handle_action(self, action: UIAction, digit: Optional[str]) -> None:
        if action == UIAction.NONE:
            return
        if action == UIAction.CANCEL:
            self._cancelled = True
            self._tts.say("已取消校准")
            return

        if self._state == FlowState.WAITING_TO_START_PHASE:
            if action == UIAction.PROCEED:
                self._start_phase()
        elif self._state == FlowState.PHASE_SUMMARY_SUCCESS:
            if action == UIAction.PROCEED:
                self._advance_to_next_phase()
            elif action == UIAction.RETRY_PHASE:
                if self._current_phase is not None:
                    self._current_phase.reset()
                self._state = FlowState.PHASE_RUNNING
                self._phase_start_time = time.time()
        elif self._state == FlowState.PHASE_SUMMARY_FAILED:
            if action == UIAction.RETRY_PHASE:
                self._consecutive_failures += 1
                if self._current_phase is not None:
                    self._current_phase.reset()
                self._state = FlowState.PHASE_RUNNING
                self._phase_start_time = time.time()
            elif action == UIAction.SKIP_PHASE:
                self._consecutive_failures = 0
                self._advance_to_next_phase()
        elif self._state == FlowState.BLINK_INPUT_AWAITING:
            self._handle_blink_input_action(action, digit)
        elif self._state == FlowState.FINAL_SUMMARY:
            if action == UIAction.PROCEED:
                self._done = True
                self._user_accepted = True
            elif action == UIAction.RETRY_PHASE:
                # 重新校准：清状态回阶段 0
                self._current_phase_index = 0
                self._current_phase = self._build_phase(0)
                self._phase_results = [None] * 5  # type: ignore[list-item]
                self._consecutive_failures = 0
                self._state = FlowState.WAITING_TO_START_PHASE

    def _handle_blink_input_action(self, action, digit) -> None:
        if action == UIAction.DIGIT and digit is not None:
            self._input_buffer += digit
        elif action == UIAction.BACKSPACE and self._input_buffer:
            self._input_buffer = self._input_buffer[:-1]
        elif action == UIAction.SUBMIT and self._input_buffer:
            assert isinstance(self._current_phase, BlinkCountPhase)
            try:
                count = int(self._input_buffer)
            except ValueError:
                return
            accepted = self._current_phase.on_user_input(count)
            if accepted:
                self._input_buffer = ""
                if self._current_phase.state == BlinkCountState.DONE:
                    # 整个 BlinkCountPhase 完成
                    result = self._current_phase.evaluate()
                    self._phase_results[self._current_phase_index] = result
                    self._state = FlowState.PHASE_SUMMARY_SUCCESS if result.success else FlowState.PHASE_SUMMARY_FAILED
                else:
                    # 下一轮继续
                    self._state = FlowState.PHASE_RUNNING
                    self._phase_start_time = time.time()

    def _start_phase(self) -> None:
        self._state = FlowState.PHASE_RUNNING
        self._phase_start_time = time.time()
        self._beep.phase_start()
        if self._current_phase is not None and self._current_phase.tts_intro:
            self._tts.say(self._current_phase.tts_intro)

    def _on_phase_time_up(self) -> None:
        if self._current_phase is None:
            return
        result = self._current_phase.evaluate()
        self._phase_results[self._current_phase_index] = result
        if result.success:
            self._state = FlowState.PHASE_SUMMARY_SUCCESS
            self._beep.phase_success()
            self._consecutive_failures = 0
            if self._current_phase.tts_complete:
                self._tts.say(self._current_phase.tts_complete)
        else:
            self._state = FlowState.PHASE_SUMMARY_FAILED
            self._beep.phase_failed()
            if result.failure_diagnosis:
                self._tts.say(result.failure_diagnosis)

    def _advance_to_next_phase(self) -> None:
        self._current_phase_index += 1
        if self._current_phase_index >= 5:
            self._state = FlowState.FINAL_SUMMARY
            self._beep.calibration_complete()
            self._tts.say("校准完成")
        else:
            self._current_phase = self._build_phase(self._current_phase_index)
            self._state = FlowState.WAITING_TO_START_PHASE

    def _build_phase(self, index: int) -> Phase:
        c = self.config
        if index == 0:
            return AutoBaselinePhase(c.auto_baseline_seconds)
        if index == 1:
            baseline = self._get_baseline_ear()
            return ClosedEyesPhase(c.closed_eyes_seconds, c.open_eyes_verify_seconds,
                                  baseline, c.closed_eyes_min_ratio)
        if index == 2:
            baseline = self._get_baseline_ear()
            ear_min = self._get_ear_min()
            return SquintPhase(c.squint_seconds, baseline, c.squint_baseline_ratio, ear_min)
        if index == 3:
            return HeadPosePhase(c.head_direction_seconds, c.head_direction_min_degrees)
        if index == 4:
            baseline = self._get_baseline_ear()
            ear_min = self._get_ear_min()
            return BlinkCountPhase(c.blink_round_seconds, c.blink_rounds_count,
                                  baseline, ear_min, c.blink_count_min, c.blink_count_max)
        raise ValueError(f"Invalid phase index {index}")

    def _get_baseline_ear(self) -> float:
        r0 = self._phase_results[0]
        return r0.summary["ear_mean"] if (r0 and r0.success) else 0.30

    def _get_ear_min(self) -> float:
        r1 = self._phase_results[1]
        return r1.summary["ear_min"] if (r1 and r1.success) else 0.08

    def _build_display_info(self) -> PhaseDisplayInfo:
        if self._current_phase is None:
            return PhaseDisplayInfo(state=self._state, phase_index=1, phase_total=5,
                                    phase_name="", instruction="")
        elapsed = time.time() - self._phase_start_time if self._state == FlowState.PHASE_RUNNING else 0.0
        fb = self._current_phase.get_live_feedback(elapsed)
        info = PhaseDisplayInfo(
            state=self._state,
            phase_index=self._current_phase_index + 1,
            phase_total=5,
            phase_name=self._current_phase.name,
            instruction=self._current_phase.tts_intro,
            remaining_sec=fb.remaining_sec,
            sample_count=fb.sample_count,
            quality_hint=fb.quality_hint,
        )
        # 摘要状态时填 summary_text
        if self._state in (FlowState.PHASE_SUMMARY_SUCCESS, FlowState.PHASE_SUMMARY_FAILED):
            r = self._phase_results[self._current_phase_index]
            if r is not None:
                if r.success:
                    info.summary_text = " ".join(f"{k}={v}" for k, v in list(r.summary.items())[:3])
                else:
                    info.summary_text = r.failure_diagnosis or ""
        # BLINK_INPUT 时填检出数 + 输入缓冲
        if self._state == FlowState.BLINK_INPUT_AWAITING and isinstance(self._current_phase, BlinkCountPhase):
            info.program_blink_count = self._current_phase.get_round_detected_blinks()
            info.user_input_buffer = self._input_buffer
        # FINAL 时填总结
        if self._state == FlowState.FINAL_SUMMARY:
            info.final_summary = self._build_final_summary_dict()
        return info

    def _build_final_summary_dict(self) -> dict:
        baseline_ear = self._get_baseline_ear()
        ear_min = self._get_ear_min()
        r4 = self._phase_results[4]
        baseline_blink_rate = (
            r4.summary["baseline_blink_rate"] if (r4 and r4.success) else 15.0
        )
        return {
            "EAR 基线": f"{baseline_ear:.3f}",
            "眨眼阈值": f"{baseline_ear * 0.75:.3f}",
            "眨眼率": f"{baseline_blink_rate:.1f}/min",
            "CQS": f"{self._compute_cqs():.2f}",
        }

    def _compute_cqs(self) -> float:
        passed = sum(1 for r in self._phase_results if r is not None and r.success)
        return passed / 5.0

    def _compute_result(self) -> Optional[CalibrationResult]:
        if self._cancelled or not self._user_accepted:
            return None
        r0 = self._phase_results[0]
        if r0 is None or not r0.success:
            return None
        signal = CalibrationSignal(
            ear_mean=r0.summary["ear_mean"],
            ear_min=self._get_ear_min(),
            ear_mid=self._get_ear_mid(),
            yaw_mean=r0.summary.get("yaw_mean", 0.0),
            yaw_range=self._get_yaw_range(),
            pitch_mean=r0.summary.get("pitch_mean", 0.0),
            pitch_range=self._get_pitch_range(),
            glasses_mode=False,  # T-CAL-XX 后续可接 glasses detector
            timestamp=time.time(),
        )
        r4 = self._phase_results[4]
        rounds = list(r4.summary["rounds"]) if (r4 and r4.success) else []
        final_adj = r4.summary.get("final_adjustment_factor", 1.0) if (r4 and r4.success) else 1.0
        baseline_blink_rate = r4.summary.get("baseline_blink_rate", 15.0) if (r4 and r4.success) else 15.0
        return CalibrationResult(
            session_id=self.session_id,
            timestamp=datetime.now(),
            signal=signal,
            blink_rounds=rounds,
            final_adjustment_factor=final_adj,
            final_blink_threshold=signal.ear_mean * 0.75 * final_adj,
            final_squint_threshold=signal.ear_mean * 0.75,
            baseline_blink_rate=baseline_blink_rate,
            cqs=self._compute_cqs(),
            is_accepted=self._user_accepted,
        )

    def _get_ear_mid(self) -> float:
        r2 = self._phase_results[2]
        return r2.summary["ear_mid"] if (r2 and r2.success) else self._get_baseline_ear() * 0.75

    def _get_yaw_range(self) -> tuple:
        r3 = self._phase_results[3]
        if r3 and r3.success:
            return (r3.summary["yaw_left_max"], r3.summary["yaw_right_max"])
        return (-15.0, 15.0)

    def _get_pitch_range(self) -> tuple:
        r3 = self._phase_results[3]
        if r3 and r3.success:
            return (r3.summary["pitch_up_max"], r3.summary["pitch_down_max"])
        return (-10.0, 10.0)


class _MutedTTS:
    """audio_enabled=False 时的占位。"""
    def say(self, text: str) -> None:
        pass
    def shutdown(self) -> None:
        pass
```

- [ ] **Step 3.2: 运行 + 覆盖率 + 全测试 + commit**

```bash
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_flow.py calibration/tests/integration/ -v
# Expected: ~17 passed (12 unit + 2 phase_audio_ui + 3 cancel_flow)
.venv312/Scripts/python.exe -m pytest calibration/tests/unit/test_flow.py --cov=calibration/flow --cov-report=term-missing -q
# Expected: ≥ 80%
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=line -q
# Expected: 388 passed (371+17)
"/c/Program Files/Git/cmd/git.exe" add calibration/flow.py calibration/tests/
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-12 flow.py state machine orchestration

CalibrationFlow drives full 5-phase flow:
- WAITING -> RUNNING -> SUMMARY_(SUCCESS|FAILED) -> next | retry | skip
- BLINK_INPUT_AWAITING special path with on-screen keypad
- FINAL_SUMMARY -> done(accept) | retry(restart) | cancel(None)
- Window close detection -> cancel
- Exception safety -> return None

Coverage: 80%+ on flow.py. Total tests: 388 passed."
```

### T-CAL-12 完成判据
- [ ] 17 测试 PASS + 覆盖率 ≥ 80% + 全套件 388 + commit

---

## Task T-CAL-13: `__main__.py` 独立运行入口 + spike 真机验证

**Goal:** 实现 `python -m calibration` 入口 + spike 全流程真机验证。
**Coverage gate:** N/A（spike 为人工验证）
**Files:**
- Create: `calibration/__main__.py`
- Modify: `calibration/__init__.py`（暴露 `run` API）
- Create: `calibration/tests/spike/spike_single_phase.py`
- Create: `calibration/tests/spike/spike_full_flow.py`

### Step 1: 暴露公共 API

- [ ] **Step 1.1: `calibration/__init__.py`** 重写

```python
"""calibration — 独立用户辅助校准模块（v4.2）

公共 API：仅一个入口
    from calibration import run
    result = run(session_id, config, db)
"""
from calibration.result import (
    CalibrationResult, CalibrationSignal, BlinkCalibrationRound,
)
from calibration.config import CalibrationConfig

__all__ = ["run", "CalibrationResult", "CalibrationSignal",
           "BlinkCalibrationRound", "CalibrationConfig"]


def run(
    session_id: str,
    config: "CalibrationConfig | None" = None,
    db=None,
):
    """运行完整校准流程，返回 Optional[CalibrationResult]。"""
    from calibration.flow import CalibrationFlow
    cfg = config or CalibrationConfig()
    flow = CalibrationFlow(session_id=session_id, config=cfg)
    return flow.run()
```

- [ ] **Step 1.2: `calibration/__main__.py`**

```python
"""python -m calibration 入口 — 独立运行校准模块，不依赖主程序。

用法：
    python -m calibration              # 使用默认 session_id
    python -m calibration <session_id>
"""
import logging
import os
import sys

# 同 main.py：屏蔽 MediaPipe telemetry
os.environ.setdefault("GLOG_logtostderr", "0")
os.environ.setdefault("MEDIAPIPE_DISABLE_GPU", "1")
os.environ.setdefault("ABSL_CPP_MIN_LOG_LEVEL", "3")

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s %(levelname)s %(name)s] %(message)s")

from calibration import run, CalibrationConfig


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else "standalone_test"
    print(f"启动独立校准 (session={sid})")
    config = CalibrationConfig()
    result = run(session_id=sid, config=config)
    if result is None:
        print("❌ 用户取消 / 失败 / 异常 — 返回 None")
        sys.exit(1)
    print("✅ 校准成功完成")
    print(f"  EAR 基线: {result.signal.ear_mean:.4f}")
    print(f"  眨眼阈值: {result.final_blink_threshold:.4f}")
    print(f"  眨眼率: {result.baseline_blink_rate:.2f}/min")
    print(f"  CQS: {result.cqs:.2f}")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

### Step 2: spike 真机验证（关键 — 5 项）

- [ ] **Step 2.1: 创建 spike 目录**

```bash
.venv312/Scripts/python.exe -c "
import os
os.makedirs('calibration/tests/spike', exist_ok=True)
print('OK')
"
```

- [ ] **Step 2.2: S-CAL-1 单阶段 spike — 跑 closed_eyes 单阶段确认 UI/TTS**

```bash
.venv312/Scripts/python.exe -m calibration spike_single
```

**人工验收（D1 执行）：**
- [ ] UI 上下分屏正确（视频在上不被遮挡）
- [ ] 听到 TTS "请闭眼并保持 5 秒"
- [ ] 闭眼结束听到 TTS "好，可以睁眼了"（**BUG 3 修复**）
- [ ] UI 区按钮可点击

- [ ] **Step 2.3: S-CAL-2 全流程 spike — 跑完整 5 阶段**

```bash
.venv312/Scripts/python.exe -m calibration spike_full
```

**人工验收：**
- [ ] 5 阶段顺序：auto → closed → squint → head_pose（含 4 子方向 TTS）→ blink_count
- [ ] 头部姿态阶段听到"现在抬头/低头/向左/向右"4 段 TTS（**BUG 4 修复**）
- [ ] 眨眼计数轮检测到非零数字（**BUG 1 修复**）
- [ ] 每阶段显示实时反馈（"已采集 N 样本"）（**BUG 5 修复**）
- [ ] 每阶段开始需点"开始"才推进（**BUG 6 修复**）
- [ ] FINAL_SUMMARY 显示总结 + 等待用户确认（**BUG 7 修复**）
- [ ] 整体时长 < 3 分钟

- [ ] **Step 2.4: S-CAL-3 IME 实战 — 用户切微软拼音输入法**

D1 切换到微软拼音 → 跑全流程 → 进到 BLINK_INPUT_AWAITING 阶段 → 用鼠标点屏幕数字键盘输入

**人工验收：**
- [ ] 鼠标点数字键盘有效（**BUG IME 修复**）
- [ ] 不需要切换到英文输入法

- [ ] **Step 2.5: S-CAL-4 音频降级测试 — 临时禁用 pyttsx3**

```bash
.venv312/Scripts/python.exe -c "
import sys
sys.modules['pyttsx3'] = None
from calibration import run, CalibrationConfig
result = run('spike_no_audio', CalibrationConfig(audio_enabled=False))
print('降级 OK' if result is None or result else 'BAD')
"
```

**人工验收：**
- [ ] 流程不崩溃，仅 UI 显示，无音频
- [ ] 仍可点击 UI 完成全流程

### Step 3: 提交

- [ ] **Step 3.1:**

```bash
"/c/Program Files/Git/cmd/git.exe" add calibration/__init__.py calibration/__main__.py calibration/tests/spike/
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-13 standalone __main__ + spike validation

calibration/__init__.py: public API surface (run + dataclasses)
calibration/__main__.py: python -m calibration entry, runs full flow

Spike validations (人工执行):
- S-CAL-1 single phase: UI/TTS/BUG 3
- S-CAL-2 full flow: BUGs 1/4/5/6/7
- S-CAL-3 IME compat
- S-CAL-4 audio fallback

All 8 user acceptance points confirmed manually."
```

### T-CAL-13 完成判据
- [ ] 4 个 spike 真机验证全过（D1 人工签收）
- [ ] commit 已提交
- [ ] 全套件 388 passed（无新单测）

---

## Task T-CAL-14: main.py 集成（最后一步）

**Goal:** 替换 main.py 中 T148 校准调用为新模块 + 删除旧代码 + 用户最终 7 BUG 实测验收。
**Coverage gate:** 原 284 + 新 ~104 测试全 PASS
**Files:**
- Modify: `main.py`
- Modify: `analyzer/user_calibration.py` → 归档到 `docs/old_schemes/legacy/`
- Modify: `gui/overlay.py` → 删除校准 UI ~200 行
- Create: `docs/old_schemes/legacy/__init__.txt`（占位）

### Step 1: 用户 7 BUG 验收测试（前置）

- [ ] **Step 1.1:** 用户先跑全流程 spike，确认 8 个验收点全部 ✅

```
□ BUG 1：眨眼计数轮检测到非零数字
□ BUG 2：校准 UI 完全不遮挡视频区
□ BUG 3：闭眼时听到 TTS "现在可以睁眼了"
□ BUG 4：头部姿态 4 段独立 TTS
□ BUG 5：每阶段进行中可见实时计数 + 结束有摘要
□ BUG 6：每阶段需点"开始"才推进
□ BUG 7：校准完成有明确反馈 + 用户主动确认才进入主监测
□ IME：微软拼音激活下仍可完成全流程
```

**任一未过 → 停止 T-CAL-14，回 T-CAL-12/13 修复。**

### Step 2: 修改 main.py — 替换校准入口

- [ ] **Step 2.1:** 在 main.py 顶部 import 区，将旧的:

```python
from analyzer.user_calibration import (
    UserCalibrationManager, CalibrationCallbacks,
    create_user_calibration_manager, CalibrationState,
)
```

替换为:

```python
import calibration as calibration_module
```

- [ ] **Step 2.2:** 找到主程序中触发校准的位置（约 main.py:800+，CalibrationCoordinator.start 调用处）。替换为：

```python
# v4.2: 释放摄像头给 calibration 模块独占
self._camera_manager.release()

# 调用新校准模块
calib_result = calibration_module.run(
    session_id=self._session_id,
    config=None,  # 用默认配置
    db=self._db,
)

# 重新获取摄像头
self._camera_manager.start()

if calib_result is not None:
    # 应用阈值到各 detector
    self._eye_detector.set_baseline(calib_result.signal.ear_mean)
    self._fatigue_analyzer.set_baseline_blink_rate(calib_result.baseline_blink_rate)
    # head_pose / gaze 阈值类似
    logger.info("校准结果已应用: EAR=%.4f, 眨眼率=%.2f/min",
                calib_result.signal.ear_mean, calib_result.baseline_blink_rate)
else:
    logger.info("用户取消校准，使用默认基线")
```

- [ ] **Step 2.3:** 删除 main.py 中以下旧类（约 159+ 行）：
- `CalibrationFlowCallbacks` class
- `CalibrationCoordinator` class
- 所有 `UserCalibrationManager` / `CalibrationState` 引用

### Step 3: 删除 gui/overlay.py 中校准 UI（约 200 行）

- [ ] **Step 3.1:** 删除以下方法：
- `show_calibration_phase`
- `update_calibration_countdown`
- `show_phase_complete`
- `show_blink_round`
- `update_blink_round`
- `show_blink_input`
- `update_input_buffer`
- `show_calibration_result`
- `hide_calibration_ui`
- `_draw_calibration_full`
- `_draw_calibration_result`
- 相关 dataclass：`CalibrationPhaseInfo`、`CalibrationDisplayData`

### Step 4: 归档旧 analyzer/user_calibration.py

- [ ] **Step 4.1:**

```bash
.venv312/Scripts/python.exe -c "
import os, shutil
os.makedirs('docs/old_schemes/legacy', exist_ok=True)
shutil.copy2('analyzer/user_calibration.py', 'docs/old_schemes/legacy/user_calibration_v1.py.txt')
os.remove('analyzer/user_calibration.py')
print('Archived + removed')
"
```

### Step 5: 更新现有测试 — 删除/改造与旧模块绑定的测试

- [ ] **Step 5.1:** 删除 `tests/test_user_calibration.py`（15 个测试，针对已删模块）

```bash
"/c/Program Files/Git/cmd/git.exe" rm tests/test_user_calibration.py
```

- [ ] **Step 5.2:** 修改 `tests/test_integration.py` 中校准相关测试 — 改为 mock `calibration.run` 返回 mock CalibrationResult

需手工编辑 `tests/test_integration.py`，找到所有 `UserCalibrationManager` / `CalibrationFlowCallbacks` / `CalibrationCoordinator` 引用并替换。

预期影响：约 5-8 个测试需要重写为 mock `calibration.run()`。

### Step 6: 完整回归

- [ ] **Step 6.1: 跑全测试**

```bash
.venv312/Scripts/python.exe -m pytest tests/ calibration/tests/ --tb=short -q
```

Expected: ~373 passed（284 - 15 删除的旧测试 + ~104 新增 calibration 测试）

**任一失败 → 回滚（git reset --hard），找问题修。**

- [ ] **Step 6.2: 真机集成 spike — S-CAL-5**

```bash
.venv312/Scripts/python.exe main.py
```

**人工验收：**
- [ ] 主程序启动正常
- [ ] 自动触发校准（calibration 模块接管 ~2 分钟）
- [ ] 校准完成后主程序接回，进入主监测
- [ ] 主监测的 EAR/blink 阈值已应用校准值（看 GUI 数字显示）
- [ ] 之前的 8 个用户验收点仍全过

### Step 7: 提交 + tag

- [ ] **Step 7.1:**

```bash
"/c/Program Files/Git/cmd/git.exe" add -A
"/c/Program Files/Git/cmd/git.exe" commit -m "feat(calibration): T-CAL-14 main.py integration (v4.2 final)

- main.py: replace T148 with calibration.run(session_id, db=...)
- Delete CalibrationFlowCallbacks + CalibrationCoordinator (159+ lines)
- Delete gui/overlay.py calibration UI methods (~200 lines)
- Archive analyzer/user_calibration.py to docs/old_schemes/legacy/
- Delete tests/test_user_calibration.py (15 obsolete tests)
- Update tests/test_integration.py to mock calibration.run

User acceptance: 8/8 BUG points confirmed (实测 OK)
Total tests: ~373 passed (284-15 baseline + ~104 new calibration tests).
v4.2 calibration redesign COMPLETE."
"/c/Program Files/Git/cmd/git.exe" tag v4.2-calibration-released
```

### T-CAL-14 完成判据 / 整个 v4.2 完成判据
- [ ] 8 个用户验收点全过（人工签收）
- [ ] 全测试套件 ~373 passed
- [ ] commit + tag
- [ ] main.py 不再 import analyzer.user_calibration
- [ ] gui/overlay.py 校准 UI 方法全删
- [ ] 旧代码已归档

---

## Self-Review（写完后自查）

### 1. Spec 覆盖性扫描
- [x] §0 7 BUG → T-CAL-04 (BUG 3) / T-CAL-06 (BUG 4) / T-CAL-07 (BUG 1) / T-CAL-09 (BUG 2 视频不被遮) / T-CAL-12 (BUG 5/6/7) / T-CAL-13 (IME)
- [x] §1 架构 → T-CAL-01~14 整体
- [x] §2 9 个组件 → 每个对应 T-CAL-XX
- [x] §3 数据流与状态机 → T-CAL-12 flow.py
- [x] §4 错误处理 → T-CAL-12 (取消/崩溃) + T-CAL-11 (音频降级)
- [x] §5 测试策略 → 每任务测试步骤 + spike
- [x] §6 保守开发策略 → 每任务有覆盖率门禁 + 回滚点

### 2. Placeholder 扫描
- [x] 无 TBD / TODO / implement later
- [x] 所有测试都有完整代码（不是 "test for the above"）
- [x] 所有命令都给出预期输出
- [x] 所有 commit message 都填了具体内容

### 3. 类型一致性
- [x] `Phase` ABC 签名（T-CAL-03）与 5 个子类（T-CAL-03/04/05/06/07）一致
- [x] `Button`/`UIAction`/`FlowState` 在 T-CAL-09 定义 → T-CAL-10/12 使用一致
- [x] `CalibrationResult` 字段（T-CAL-01）→ T-CAL-12 _compute_result 一致

### 4. 任务依赖性
```
T-CAL-01 → T-CAL-02 → T-CAL-03 (base + auto) → T-CAL-04/05/06/07 (其余 4 阶段)
                                                    → T-CAL-08 (UI layout) → T-CAL-09 (panel)
                                                    → T-CAL-10 (input)
                                                    → T-CAL-11 (audio)
                                                                ↓
                                              T-CAL-12 (flow 编排) → T-CAL-13 (__main__ + spike)
                                                                → T-CAL-14 (main.py 集成)
```

### 5. 工时核对
计划与 spec §6.2 工时表一致：
- T-CAL-01: 0.5h / T-CAL-02: 0.5h / T-CAL-03: 1.5h / T-CAL-04: 1h / T-CAL-05: 1h
- T-CAL-06: 1.5h / T-CAL-07: 1.5h / T-CAL-08: 0.5h / T-CAL-09: 3h / T-CAL-10: 2h
- T-CAL-11: 1.5h / T-CAL-12: 3h / T-CAL-13: 0.5h / T-CAL-14: 2h
- **合计 20h**（spec 一致）

---

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-06-02-calibration-redesign-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 派 fresh subagent 跑每个 T-CAL-XX 任务，任务间 review，快速迭代。适合并行 / 隔离上下文 / 防主会话污染。

**2. Inline Execution** - 在当前会话顺序跑，每个任务有 checkpoint review。适合 D1 想全程跟进每一步的场景。

**Which approach?**

---

> **下一步**：用户确认采用哪种执行方式后，分别调 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` skill。本计划提供了 14 个 T-CAL 任务的完整代码 / 测试 / 命令 / 回滚点。

