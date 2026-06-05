# v4.4 GUI 清晰化 + 拖窗口 REC 指示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能 (1) 校验阶段拖窗口时知道数据继续记录, (2) 主程序 GUI 信息一眼看清 (MODE/focus/fatigue/无脸).

**Architecture:** v4.2 校准模块加 REC 指示 + 拖窗口检测 (calibration/flow.py); 主 GUI 重设计状态栏圆点/圆环/告警/无脸 (gui/overlay.py). 7 个 TDD 任务, 7 commits.

**Tech Stack:** Python 3.12, OpenCV (cv2.putText/cv2.circle), PIL (put_chinese_text), threading, time. 复用 v4.3 已有的 `set_mode()` API + `OverlayConfig` 字段.

**Spec:** `docs/superpowers/specs/2026-06-05-v4-4-gui-clarity-and-drag-rec.md`

---

## File Structure

| 文件 | 责任 | 任务 |
|------|------|------|
| `calibration/flow.py` | 加 `_last_waitkey_time` / `_drag_start_time` 字段; `_build_display_info` 返回 `rec_indicator` 和 `dragging`; `_render_calibration` 画 ●REC + 拖窗口遮罩 | T1, T2 |
| `gui/overlay.py` | `_draw_status_bar` 圆点 12/字体 0.75/粗体; `_draw_focus_display` 圆环 70/数字 1.5/8px 边框; 新增 `_draw_fatigue_alert`; 新增 `_draw_no_face_banner`; `draw()` 加 `last_face_time` 参数 | T3, T4, T5, T6 |
| `main.py` | `EyeFocusApp._last_face_time` 追踪; `_render_frame` 传 `last_face_time` 给 overlay | T6 |
| `tests/test_calibration_v4_2.py` | T1 + T2 共 3 个测试 (rec_indicator / dragging detected / dragging clears) | T1, T2 |
| `tests/test_gui.py` | T3-T6 共 4 个测试 (mode dot radius / focus circle radius / fatigue alert / no face banner) | T3, T4, T5, T6 |

---

## Task 1: v4.2 校准面板加常驻 ●REC 指示

**Files:**
- Modify: `calibration/flow.py:80-120` (CalibrationFlow.__init__ + _build_display_info)
- Modify: `calibration/flow.py:130-150` (_render_calibration 加 putText 调用)
- Test: `tests/test_calibration_v4_2.py` (加新测试)

- [ ] **Step 1: 写 failing test — rec_indicator 包含在 panel info**

打开 `tests/test_calibration_v4_2.py`, 找 `_build_display_info` 测试附近 (或新建测试). 加:

```python
def test_rec_indicator_always_in_panel_info_v4_4():
    """v4.4: 校验阶段 panel info 始终包含 rec_indicator 字段 (●REC 录制中)"""
    from calibration.flow import CalibrationFlow
    from unittest.mock import MagicMock

    # 构造最小 CalibrationFlow 实例 (不需要真实摄像头)
    flow = CalibrationFlow.__new__(CalibrationFlow)
    flow._state = FlowState.PHASE_RUNNING
    flow._current_phase = MagicMock()
    flow._phase_start_time = time.time()
    flow._input = MagicMock()
    flow._panel = MagicMock()
    flow._panel.get_buttons.return_value = []
    flow._last_waitkey_time = time.time()  # v4.4 字段
    flow._beep = MagicMock()

    info = flow._build_display_info()

    assert "rec_indicator" in info, f"panel info 应有 rec_indicator 字段, 实际 keys: {list(info.keys())}"
    assert "●REC" in info["rec_indicator"], f"rec_indicator 应含 ●REC 文字, 实际 {info['rec_indicator']!r}"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_calibration_v4_2.py::test_rec_indicator_always_in_panel_info_v4_4 -v --tb=short
```

Expected: FAIL with `KeyError: 'rec_indicator'` 或 `'rec_indicator' not in info`

- [ ] **Step 3: 实现 _build_display_info 加 rec_indicator**

打开 `calibration/flow.py`, 找 `_build_display_info` 方法 (约 line 95). 在方法末尾 (return info 前) 加:

```python
        # v4.4: 常驻 ●REC 录制中 指示 (告诉用户数据在记录, 即使画面冻结)
        info["rec_indicator"] = "●REC 录制中"
        return info
```

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_calibration_v4_2.py::test_rec_indicator_always_in_panel_info_v4_4 -v
```

Expected: PASS

- [ ] **Step 5: 在 _render_calibration 中画 rec_indicator**

打开 `calibration/flow.py` `_render_calibration` 方法 (约 line 130). 找 `panel_img` 创建后第一段绘制之前. 加 (假设已有 put_chinese_text import):

```python
        # v4.4: 顶部加常驻 ●REC 指示
        rec_text = info.get("rec_indicator", "")
        if rec_text:
            try:
                # 绿底白字, 让用户清楚看见
                cv2.rectangle(panel_img, (5, 5), (180, 32), (0, 180, 0), -1)
                panel_img = put_chinese_text(panel_img, rec_text, (12, 8), _chinese_font, (255, 255, 255))
            except Exception:
                # put_chinese_text 失败时 fallback 到 cv2.putText
                cv2.putText(panel_img, "REC", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
```

- [ ] **Step 6: 跑全套测试确认无回归**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/ calibration/tests/ --tb=no -q
```

Expected: 568+ passed (新 +1, 旧测试不动)

- [ ] **Step 7: Commit**

```bash
git add calibration/flow.py tests/test_calibration_v4_2.py
git commit -m "feat(calib): v4.4 panel header 加常驻 ●REC 录制中 指示

用户报校验阶段拖窗口时画面冻结, 误以为停止记录.
v4.4 改进: panel 顶部 (5, 5)-(180, 32) 画绿底白字 '●REC 录制中',
让用户明确知道数据继续记录。

测试: test_rec_indicator_always_in_panel_info_v4_4 新增
568 → 569 passed (+1, 0 回归)"
```

---

## Task 2: v4.2 拖窗口检测 + DRAGGING 画面冻结提示

**Files:**
- Modify: `calibration/flow.py:80-95` (CalibrationFlow.__init__ 加字段)
- Modify: `calibration/flow.py:105-120` (_build_display_info 加 dragging 检测)
- Modify: `calibration/flow.py:130-150` (_render_calibration 加拖窗口遮罩)
- Test: `tests/test_calibration_v4_2.py` (加 2 个测试)

- [ ] **Step 1: 写 failing test — dragging 检测**

打开 `tests/test_calibration_v4_2.py`, 加:

```python
def test_dragging_detected_when_waitkey_stalls_v4_4():
    """v4.4: 拖窗口时 waitKey 卡住, _build_display_info 标 dragging=True"""
    from calibration.flow import CalibrationFlow
    from unittest.mock import MagicMock

    flow = CalibrationFlow.__new__(CalibrationFlow)
    flow._state = FlowState.PHASE_RUNNING
    flow._current_phase = MagicMock()
    flow._phase_start_time = time.time()
    flow._input = MagicMock()
    flow._panel = MagicMock()
    flow._panel.get_buttons.return_value = []
    flow._beep = MagicMock()
    # 模拟 waitKey 300ms 前返回, 现在 time.time() 已过去
    flow._last_waitkey_time = time.time() - 0.3  # 300ms 前

    info = flow._build_display_info()

    assert info.get("dragging") is True, f"waitKey 300ms 未返回应判定 dragging=True, 实际 {info.get('dragging')}"


def test_dragging_clears_when_waitkey_resumes_v4_4():
    """v4.4: waitKey 频率恢复后 dragging 自动 False"""
    from calibration.flow import CalibrationFlow
    from unittest.mock import MagicMock

    flow = CalibrationFlow.__new__(CalibrationFlow)
    flow._state = FlowState.PHASE_RUNNING
    flow._current_phase = MagicMock()
    flow._phase_start_time = time.time()
    flow._input = MagicMock()
    flow._panel = MagicMock()
    flow._panel.get_buttons.return_value = []
    flow._beep = MagicMock()
    # 模拟 waitKey 刚返回 (50ms 内, 阈值 200ms)
    flow._last_waitkey_time = time.time() - 0.05

    info = flow._build_display_info()

    assert info.get("dragging") is False, f"waitKey 50ms 内应判定 dragging=False, 实际 {info.get('dragging')}"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest "tests/test_calibration_v4_2.py::test_dragging_detected_when_waitkey_stalls_v4_4" "tests/test_calibration_v4_2.py::test_dragging_clears_when_waitkey_resumes_v4_4" -v
```

Expected: FAIL (AttributeError: '_last_waitkey_time' not set)

- [ ] **Step 3: 实现 _last_waitkey_time 字段 + 拖窗口检测**

打开 `calibration/flow.py`, 找 `CalibrationFlow.__init__` (约 line 80). 在已有字段后加:

```python
        # v4.4: 追踪 waitKey 返回时间, 检测拖窗口
        self._last_waitkey_time: float = time.time()
```

打开 `_build_display_info` (约 line 95). 在 `return info` 前加:

```python
        # v4.4: 拖窗口检测 — waitKey 超过 200ms 未返回判定为拖窗口
        info["dragging"] = (time.time() - self._last_waitkey_time) > 0.2
        return info
```

- [ ] **Step 4: 在 _tick_once 更新 _last_waitkey_time**

打开 `calibration/flow.py` `_tick_once` 方法. 找 `cv2.waitKey` 调用 (约 line 160). 在它后面加:

```python
        self._last_waitkey_time = time.time()  # v4.4: 追踪用于拖窗口检测
```

- [ ] **Step 5: 跑测试确认 GREEN**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest "tests/test_calibration_v4_2.py::test_dragging_detected_when_waitkey_stalls_v4_4" "tests/test_calibration_v4_2.py::test_dragging_clears_when_waitkey_resumes_v4_4" -v
```

Expected: PASS

- [ ] **Step 6: 在 _render_calibration 加拖窗口遮罩**

打开 `calibration/flow.py` `_render_calibration`. 找 rec_indicator 绘制代码 (Task 1 Step 5 位置). 在它下面加:

```python
        # v4.4: 拖窗口时叠加 ❄ DRAGGING 画面冻结 提示
        if info.get("dragging"):
            h, w = panel_img.shape[:2]
            # 半透明黑色遮罩
            overlay = panel_img.copy()
            cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
            panel_img = cv2.addWeighted(overlay, 0.4, panel_img, 0.6, 0)
            # 居中显示
            try:
                main_text = "❄ DRAGGING 画面冻结"
                sub_text = "(数据继续录制)"
                panel_img = put_chinese_text(panel_img, main_text, (w // 2 - 90, h // 2 - 20), _chinese_font_large, (100, 200, 255))
                panel_img = put_chinese_text(panel_img, sub_text, (w // 2 - 80, h // 2 + 20), _chinese_font, (200, 200, 200))
            except Exception:
                cv2.putText(panel_img, "DRAGGING", (w // 2 - 60, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 200, 255), 2)
```

- [ ] **Step 7: 跑全套确认无回归**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/ calibration/tests/ --tb=no -q
```

Expected: 570+ passed (Task 1 +1, Task 2 +2 = +3, 0 回归)

- [ ] **Step 8: Commit**

```bash
git add calibration/flow.py tests/test_calibration_v4_2.py
git commit -m "feat(calib): v4.4 拖窗口检测 + DRAGGING 画面冻结提示

启发式检测: 追踪 _last_waitkey_time, 超过 200ms 未返回
判定为拖窗口中 (OpenCV 不直接暴露 drag 事件)。

拖窗口时 panel 叠加半透明黑色遮罩 + 居中提示:
  ❄ DRAGGING 画面冻结
  (数据继续录制)

拖完 waitKey 频率恢复, dragging 自动 False, 提示消失。

测试: dragging_detected / dragging_clears (2 个新增)
570 → 572 passed (+2, 0 回归)"
```

---

## Task 3: 主 GUI MODE 状态栏更大醒目

**Files:**
- Modify: `gui/overlay.py:286-310` (_draw_status_bar 圆点+字体+粗体)
- Test: `tests/test_gui.py` (加 test_mode_dot_radius_12)

- [ ] **Step 1: 写 failing test — 圆点半径 12**

打开 `tests/test_gui.py`, 加:

```python
def test_mode_dot_radius_is_12_v4_4():
    """v4.4: MODE 圆点半径 = 12 (原 5, 2.4x)"""
    overlay = FocusOverlay()
    # 检查源码 — radius=12 硬编码
    import inspect
    src = inspect.getsource(overlay._draw_status_bar)
    assert "radius=12" in src or "radius = 12" in src, \
        f"_draw_status_bar 应使用 radius=12, 实际源码不含"
    # 同时检查 MODE 字体 0.75
    assert "0.75" in src, f"_draw_status_bar 应使用字体 0.75, 实际源码不含"
    # 同时检查 ● 前缀
    assert "●" in src, f"_draw_status_bar 应使用 ● 前缀, 实际源码不含"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_mode_dot_radius_is_12_v4_4 -v
```

Expected: FAIL

- [ ] **Step 3: 实现 MODE 状态栏变大醒目**

打开 `gui/overlay.py`, 找 `_draw_status_bar` 方法. 找原来 `cv2.circle(frame, (x + 6, y_main - 5), 5, mode_color, -1)` (约 line 287 附近). 改为:

```python
        # v4.4: 圆点 r=12, 字体 0.75, thickness 2, ● 前缀
        cv2.circle(frame, (x + 6, y_main - 5), 12, mode_color, -1)
        cv2.putText(frame, f"●{self._current_mode}", (x + 25, y_main),
                    self.config.font, 0.75, mode_color, 2)
```

原 `x += 18 + len(self._current_mode) * 9 + 18` 的间距算式需调整:

```python
        x += 25 + len(f"●{self._current_mode}") * 11 + 15
```

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_mode_dot_radius_is_12_v4_4 -v
```

Expected: PASS

- [ ] **Step 5: 跑全套确认无回归**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/ calibration/tests/ --tb=no -q
```

Expected: 572+ passed (+1, 0 回归)

- [ ] **Step 6: Commit**

```bash
git add gui/overlay.py tests/test_gui.py
git commit -m "feat(gui): v4.4 MODE 状态栏圆点 2.4x + 字体 1.36x + ● 前缀

圆点 5 → 12 (2.4x)
字体 0.55 → 0.75 (1.36x)
thickness 1 → 2 (粗体)
模式名前缀 ● (Unicode 圆点)

让用户 5m 外也能看清当前模式 (MONITORING 绿 / CALIBRATING 橙 /
PAUSED 灰 / INITIALIZING 黄 / ERROR 红)

测试: test_mode_dot_radius_is_12_v4_4 新增
572 → 573 passed (+1, 0 回归)"
```

---

## Task 4: focus score 圆环更大 (r=70, 数字 1.5x, 8px 边框)

**Files:**
- Modify: `gui/overlay.py:343-385` (_draw_focus_display)
- Test: `tests/test_gui.py`

- [ ] **Step 1: 写 failing test — 圆环半径 70 + 数字 1.5x**

打开 `tests/test_gui.py`, 加:

```python
def test_focus_circle_radius_is_70_v4_4():
    """v4.4: focus score 圆环半径 50 → 70, 数字 字号 0.6 → 1.5, 8px 边框颜色按分数"""
    overlay = FocusOverlay()
    import inspect
    src = inspect.getsource(overlay._draw_focus_display)
    assert "radius = 70" in src or "radius=70" in src, \
        f"_draw_focus_display 圆环应 radius=70, 实际源码不含"
    assert "1.5" in src, f"数字字号应 1.5, 实际不含"
    # 8px 边框 (thickness=8)
    assert "8)" in src or "thickness=8" in src or ", 8," in src, f"边框应 8px, 实际不含"
    # FOCUS 标签
    assert '"FOCUS"' in src, "应有 FOCUS 标签"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_focus_circle_radius_is_70_v4_4 -v
```

Expected: FAIL

- [ ] **Step 3: 实现 focus 圆环重设计**

打开 `gui/overlay.py`, 找 `_draw_focus_display`. 找 `radius = 50` (约 line 353). 改为:

```python
        radius = 70
        center_x = w - 90
        center_y = h - 130
```

找 `cv2.circle(overlay, (center_x, center_y), radius, (40, 40, 40), -1)` (背景圆). 在它下面加 8px 边框:

```python
        # v4.4: 8px 边框, 颜色按分数
        border_color = self._focus_color(focus_score)
        cv2.circle(overlay, (center_x, center_y), radius, border_color, 8)
```

找中心数字 `cv2.putText(frame, f"{focus_score:.0f}", (center_x - 30, center_y), ...)`. 改为 (字号 1.5, thickness 3, 上方加 FOCUS 标签):

```python
        # v4.4: 中心数字大字 + 上方 FOCUS 标签
        cv2.putText(frame, "FOCUS", (center_x - 30, center_y - 30),
                    self.config.font, 0.5, COLOR_TEXT_MUTED, 1)
        cv2.putText(frame, f"{focus_score:.0f}", (center_x - 45, center_y + 18),
                    self.config.font, 1.5, COLOR_WHITE, 3)
```

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_focus_circle_radius_is_70_v4_4 -v
```

Expected: PASS

- [ ] **Step 5: 跑全套确认无回归**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/ calibration/tests/ --tb=no -q
```

Expected: 573+ passed (+1, 0 回归)

- [ ] **Step 6: Commit**

```bash
git add gui/overlay.py tests/test_gui.py
git commit -m "feat(gui): v4.4 focus 圆环 r=70 + 数字 1.5x + 8px 边框颜色按分数

圆环 50 → 70 (1.4x)
中心数字字号 0.6 → 1.5 (2.5x, ~50pt)
数字上方加 'FOCUS' 标签
8px 边框 (绿 >=70 / 黄 50-70 / 红 <50) 按分数变色
整体 5m 外也能一眼看清

测试: test_focus_circle_radius_is_70_v4_4 新增
573 → 574 passed (+1, 0 回归)"
```

---

## Task 5: fatigue 切档醒目 (彩色横条 + 闪烁 + 居中警告)

**Files:**
- Modify: `gui/overlay.py` (新增 `_draw_fatigue_alert` 方法)
- Modify: `gui/overlay.py:230-240` (draw() 调 _draw_fatigue_alert)
- Test: `tests/test_gui.py`

- [ ] **Step 1: 写 failing test**

打开 `tests/test_gui.py`, 加:

```python
def test_fatigue_alert_high_draws_warning_v4_4():
    """v4.4: fatigue=HIGH 时 _draw_fatigue_alert 绘制 '⚠ 疲劳警告 ⚠'"""
    import numpy as np
    overlay = FocusOverlay()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # 调 _draw_fatigue_alert (HIGH)
    result = overlay._draw_fatigue_alert(frame, "HIGH")

    # 验证 frame 像素被改变 (证明绘制了)
    assert not np.array_equal(result, frame), "_draw_fatigue_alert 应修改 frame"

    # 验证源码包含 "疲劳警告"
    import inspect
    src = inspect.getsource(overlay._draw_fatigue_alert)
    assert "疲劳警告" in src, "HIGH 时应显示 '⚠ 疲劳警告 ⚠'"
    assert "0, 0, 220" in src or "(0, 0, 255)" in src, "HIGH 红色边框"
    # MEDIUM 黄色横条
    assert "(0, 200, 220)" in src or "(0, 255, 255)" in src, "MEDIUM 黄色"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_fatigue_alert_high_draws_warning_v4_4 -v
```

Expected: FAIL (AttributeError: '_draw_fatigue_alert' not exist)

- [ ] **Step 3: 实现 _draw_fatigue_alert 方法**

打开 `gui/overlay.py`. 找 `_draw_fatigue_color` 方法. 在它上面加:

```python
    def _draw_fatigue_alert(self, frame: np.ndarray, fatigue_level: Optional[str]) -> np.ndarray:
        """v4.4: fatigue 切档醒目提示

        Args:
            frame: 当前帧
            fatigue_level: "LOW" / "MEDIUM" / "HIGH" / None

        Returns:
            绘制后的帧
        """
        if fatigue_level is None or fatigue_level == "LOW":
            return frame
        h, w = frame.shape[:2]
        bar_y = self.config.status_bar_height  # 60, 紧贴状态栏下方
        if fatigue_level == "MEDIUM":
            # 4px 黄色横条
            cv2.rectangle(frame, (0, bar_y), (w, bar_y + 4), (0, 200, 220), -1)
        elif fatigue_level == "HIGH":
            # 8px 红色横条, 闪烁 (0.5s 周期)
            if int(time.time() * 2) % 2 == 0:
                cv2.rectangle(frame, (0, bar_y), (w, bar_y + 8), (0, 0, 220), -1)
            # 居中大警告
            warn_text = "⚠ 疲劳警告 ⚠"
            (tw, th), _ = cv2.getTextSize(warn_text, self.config.font, 1.2, 3)
            cv2.putText(frame, warn_text, ((w - tw) // 2, h // 2),
                        self.config.font, 1.2, (0, 0, 255), 3)
        return frame
```

- [ ] **Step 4: 在 draw() 调 _draw_fatigue_alert**

打开 `gui/overlay.py` `draw()`. 找 `overlay = self._draw_alerts(overlay)` (约 line 237). 在它后面加:

```python
        # v4.4: fatigue 切档醒目
        overlay = self._draw_fatigue_alert(overlay, fatigue_level)
```

- [ ] **Step 5: 跑测试确认 GREEN**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_fatigue_alert_high_draws_warning_v4_4 -v
```

Expected: PASS

- [ ] **Step 6: 跑全套确认无回归**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/ calibration/tests/ --tb=no -q
```

Expected: 574+ passed (+1, 0 回归)

- [ ] **Step 7: Commit**

```bash
git add gui/overlay.py tests/test_gui.py
git commit -m "feat(gui): v4.4 fatigue 切档醒目 (MEDIUM 黄横条 / HIGH 红横条闪烁 + 居中警告)

MEDIUM: 状态栏下方 4px 黄色横条 (0, 200, 220)
HIGH: 8px 红色横条 + 0.5s 周期闪烁 + 居中 1.2 字号红字 '⚠ 疲劳警告 ⚠'
LOW: 不绘制 (默认安静)

让疲劳状态变化从'颜色变了'升级为'5m 外也看得见的横条 + 警告字'。

测试: test_fatigue_alert_high_draws_warning_v4_4 新增
574 → 575 passed (+1, 0 回归)"
```

---

## Task 6: 无脸检测红底白字横条 (5s+ 倒计时 + 闪烁)

**Files:**
- Modify: `gui/overlay.py` (新增 `_draw_no_face_banner`)
- Modify: `gui/overlay.py:183-235` (draw() 加 last_face_time 参数)
- Modify: `main.py` (`EyeFocusApp._last_face_time` 追踪 + _render_frame 传入)
- Test: `tests/test_gui.py`

- [ ] **Step 1: 写 failing test**

打开 `tests/test_gui.py`, 加:

```python
def test_no_face_banner_after_5s_v4_4():
    """v4.4: 无脸 5s+ 后 _draw_no_face_banner 绘制红底白字横条"""
    import numpy as np
    overlay = FocusOverlay()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # 模拟 10s 前最后检测到脸
    last_face_time = time.time() - 10.0
    result = overlay._draw_no_face_banner(frame, face_detected=False, last_face_time=last_face_time)

    # 验证 frame 被修改
    assert not np.array_equal(result, frame), "_draw_no_face_banner 应修改 frame (红底白字)"

    # 5s 阈值内不绘制
    frame2 = np.zeros((480, 640, 3), dtype=np.uint8)
    result2 = overlay._draw_no_face_banner(frame2, face_detected=False, last_face_time=time.time() - 2.0)
    assert np.array_equal(result2, frame2), "5s 内不应绘制 (避免一过性闪烁)"

    # 脸检测到时不绘制
    result3 = overlay._draw_no_face_banner(frame, face_detected=True, last_face_time=None)
    assert np.array_equal(result3, frame), "face_detected=True 不应绘制"

    # 源码含关键字符串
    import inspect
    src = inspect.getsource(overlay._draw_no_face_banner)
    assert "请将面部对准摄像头" in src, "提示文案"
    assert "(0, 0, 200)" in src or "(0, 0, 255)" in src, "红底"
```

- [ ] **Step 2: 跑测试确认 RED**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_no_face_banner_after_5s_v4_4 -v
```

Expected: FAIL (AttributeError: '_draw_no_face_banner' not exist)

- [ ] **Step 3: 实现 _draw_no_face_banner**

打开 `gui/overlay.py`. 找 `_draw_fatigue_alert` (Task 5 加的). 在它下面加:

```python
    def _draw_no_face_banner(
        self,
        frame: np.ndarray,
        face_detected: bool,
        last_face_time: Optional[float],
    ) -> np.ndarray:
        """v4.4: 无脸检测红底白字横条 (5s+ 倒计时 + 闪烁)"""
        if face_detected or last_face_time is None:
            return frame
        # 5s 阈值, 避免启动时一过性闪烁
        if time.time() - last_face_time < 5.0:
            return frame

        lost_sec = int(time.time() - last_face_time)
        h, w = frame.shape[:2]
        text = f"● 请将面部对准摄像头 ({lost_sec}s) ●"
        (tw, th), _ = cv2.getTextSize(text, self.config.font, 1.2, 3)
        bar_w = tw + 40
        bar_h = th + 30
        bar_x = (w - bar_w) // 2
        bar_y = h // 2 - bar_h // 2
        # 0.5s 周期闪烁
        if int(time.time() * 2) % 2 == 0:
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (0, 0, 200), -1)
        cv2.putText(frame, text, (bar_x + 20, bar_y + th + 15),
                    self.config.font, 1.2, COLOR_WHITE, 3)
        return frame
```

- [ ] **Step 4: draw() 加 last_face_time 参数 + 调 _draw_no_face_banner**

打开 `gui/overlay.py` `draw()`. 找签名 line 183-195. 改:

```python
    def draw(
        self,
        frame: np.ndarray,
        focus_score: Optional[float] = None,
        fatigue_level: Optional[str] = None,
        eye_detected: bool = True,
        face_detected: bool = True,
        light_condition: Optional[str] = None,
        calibration: Optional[CalibrationProgress] = None,
        eye_score: Optional[float] = None,
        head_score: Optional[float] = None,
        gaze_score: Optional[float] = None,
        glasses_str: Optional[str] = None,
        fps: Optional[float] = None,
        last_face_time: Optional[float] = None,  # v4.4 新增
    ) -> np.ndarray:
```

找 `_draw_status_bar` 调用后加:

```python
        # 绘制状态栏 (含 glasses)
        overlay = self._draw_status_bar(
            overlay,
            focus_score=focus_score,
            fatigue_level=fatigue_level,
            eye_detected=eye_detected,
            face_detected=face_detected,
            glasses_str=glasses_str,
        )
        # v4.4: 无脸检测红底白字横条
        overlay = self._draw_no_face_banner(overlay, face_detected, last_face_time)
```

- [ ] **Step 5: main.py 加 _last_face_time 追踪 + 传入**

打开 `main.py`. 找 `EyeFocusApp.__init__` (line 696). 在已加的 `self._paused` 字段后加:

```python
        # v4.4: 追踪最后一次检测到脸的时间 (无脸横幅倒计时)
        self._last_face_time: Optional[float] = None
```

找 `_render_frame` 方法. 找 `display = self._overlay.draw(...)` 调用 (line 987-1000 附近). 加 `last_face_time=self._last_face_time`:

```python
        display = self._overlay.draw(
            frame,
            focus_score=focus_score_val,
            fatigue_level=fatigue_level_str,
            eye_detected=face_detected,
            face_detected=face_detected,
            light_condition=light_condition_str,
            calibration=calibration_progress,
            eye_score=eye_score,
            head_score=head_score,
            gaze_score=gaze_score_val,
            glasses_str=glasses_str,
            fps=self._fps,
            last_face_time=self._last_face_time,  # v4.4 新增
        )
```

找 `process_frame` 调用前的位置 (line ~851-852), 加 _last_face_time 更新:

```python
                # v4.4: 追踪脸检测时间用于无脸横幅
                if face_detected:
                    self._last_face_time = time.time()
```

注: `face_detected` 在 `_frame_processor.process_frame` 调用后会被更新到 `self._frame_processor.latest_face_result.face_detected`. 找正确的引用点 — 可能需要从 frame_processor 读. 简化: 用 `self._frame_processor.latest_face_result.face_detected` 如果存在, 或 `face_detected` 局部变量.

- [ ] **Step 6: 跑测试确认 GREEN**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/test_gui.py::test_no_face_banner_after_5s_v4_4 -v
```

Expected: PASS

- [ ] **Step 7: 跑全套确认无回归**

```bash
.venv312/Scripts/python.exe -X utf8 -m pytest tests/ calibration/tests/ --tb=no -q
```

Expected: 575+ passed (+1, 0 回归)

- [ ] **Step 8: Commit**

```bash
git add gui/overlay.py main.py tests/test_gui.py
git commit -m "feat(gui): v4.4 无脸检测红底白字横条 (5s+ 倒计时 + 闪烁)

无脸 5s+ 后居中显示红底白字横条:
  ● 请将面部对准摄像头 (Xs) ●
1.2 字号, 0.5s 周期闪烁, 显示丢失秒数倒计时。
5s 内不显示 (避免启动一过性闪烁)。
face_detected=True 时不显示。

main.py 追踪 _last_face_time, draw() 传 last_face_time 给 overlay。

测试: test_no_face_banner_after_5s_v4_4 新增
575 → 576 passed (+1, 0 回归)"
```

---

## Task 7: 真机实测 + 推上

**Files:** 无代码变更, 只做验证

- [ ] **Step 1: 跑 60s 真机实测**

```bash
cd "D:/Users/Katysia/Desktop/EyeFocus Insight"
timeout 60 .venv312/Scripts/python.exe -X utf8 main.py 2>&1 | tail -10
```

Expected: 看到 5 项新 GUI 元素 (MODE 大圆点 / focus 圆环 70 / 状态栏 + fatigue 横条 / 无脸红底白字)
校准阶段拖窗口 → 看到 ●REC + DRAGGING 提示

- [ ] **Step 2: 确认 push 成功 (前面 6 commit 已 push, 这步只是 sanity check)**

```bash
cd "D:/Users/Katysia/Desktop/EyeFocus Insight"
/c/Program\ Files/Git/cmd/git.exe status
/c/Program\ Files/Git/cmd/git.exe log --oneline -8
```

Expected: working tree clean, 7 个 v4.4 commit (含 Task 1-6) 在最前面

- [ ] **Step 3: 更新 PHASE2_PLAN.md §2.8.3 记录 v4.4 维护**

打开 `PHASE2_PLAN.md`. 找 `### 2.8.2` 后面加 (在 `---` 分隔前):

```markdown
### 2.8.3 v1.4 v4.4 GUI 清晰化 + 拖窗口 REC 指示 (2026-06-05 用户实测反馈后)

> **记录日期**：2026-06-05
> **触发**：用户实测报 "校验阶段拖动窗口依旧停止记录" + "主程序 GUI 展示信息还是不够清晰明确"
> **设计**：[`docs/superpowers/specs/2026-06-05-v4-4-gui-clarity-and-drag-rec.md`](../superpowers/specs/2026-06-05-v4-4-gui-clarity-and-drag-rec.md)

**修了什么**:
- v4.2 校准: panel header 加 ●REC 常驻指示 + 拖窗口检测 (waitKey 200ms+) + ❄ DRAGGING 画面冻结遮罩
- 主 GUI 状态栏: 圆点 5→12, 字体 0.55→0.75, 粗体, ● 前缀
- focus 圆环: r 50→70, 数字 0.6→1.5, 8px 边框颜色按分数
- fatigue: MEDIUM 4px 黄横条, HIGH 8px 红横条闪烁 + 居中 1.2 字号红字 "⚠ 疲劳警告 ⚠"
- 无脸: 5s+ 后红底白字横条 "● 请将面部对准摄像头 (Xs) ●" 0.5s 闪烁

**测试**: 568 → 576 passed (+8 新增回归测试, 0 回归)

**用户验收**: 5 项清晰化 + 拖窗口 REC 指示, 实测可见
```

然后 commit 文档单独:

```bash
git add PHASE2_PLAN.md
git commit -m "docs(phase2): §2.8.3 v4.4 GUI 清晰化 + 拖窗口 REC 指示 记录

v4.3 维护完成后用户实测报 2 个问题:
  1. 校验阶段拖窗口时画面冻结, 误以为停止记录
  2. 主程序 GUI 信息仍不够清晰

v4.4 修法: 6 commit + 8 个测试
  - 校准阶段 ●REC + 拖窗口 DRAGGING 提示
  - MODE 状态栏 2.4x 字号
  - focus 圆环 1.4x + 8px 边框
  - fatigue MEDIUM/HIGH 醒目横条 + 闪烁
  - 无脸 5s+ 红底白字横条

576 passed, 0 回归"
```

---

## Self-Review Checklist

运行后确认:

- [x] Spec coverage: 5 GUI 改进 + 1 REC = 6 commits 覆盖
- [x] Placeholder scan: 无 TBD/TODO
- [x] Type consistency: last_face_time 在 EyeFocusApp init / _render_frame / draw() 三处一致
- [x] Commit granularity: 每 task 1 commit, 含 test+fix
- [x] Run commands: 每次 commit 前跑全套测试
