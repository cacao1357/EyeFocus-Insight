# v4.4 GUI 清晰化 + 校验阶段拖窗口 REC 指示

> **状态**: ✅ 已完成 (v4.4) | **实装**: `gui/overlay.py`, `calibration/flow.py`
> **Spec 日期**: 2026-06-05
> **作者**: D1 + Claude Code
> **状态**: ✅ 已批准
> **关联**: v4.3 维护审查 (commit 4beff01) 后的用户实测反馈
> **问题来源**:
>   1. 校准阶段拖窗口时画面冻结, 用户误以为停止记录 (实际数据继续记, 画面只是不更新)
>   2. 主程序 GUI 信息仍不够清晰明确 (focus score 难读, fatigue 切档不醒目, 无脸提示小, MODE 模式颜色看不出)

---

## 一、目标

5 项 GUI 改进 + 1 项校准阶段 REC 指示, 共 6 个 commit + 6 个回归测试, 让用户:
- 校验阶段拖窗口时**明确知道**数据在继续记录 (●REC + DRAGGING 提示)
- 主程序 GUI **一眼看清**: MODE / focus / fatigue / 告警 / 无脸

---

## 二、范围 (Scope)

### In Scope

1. **Part A: 校验阶段 REC 指示** (calibration/flow.py)
   - panel header 加 `●REC 录制中` 常驻指示
   - 拖窗口检测 + `❄ DRAGGING 画面冻结` 提示叠加
2. **Part B: 主 GUI 清晰化** (gui/overlay.py)
   - B1: MODE 状态栏 (圆点 2.4x, 字体 1.36x, 粗体, 模式名前缀圆点)
   - B2: focus score 圆环 (半径 1.4x, 数字 2.5x, 边框颜色)
   - B3: fatigue 告警 (MEDIUM 顶部黄横条, HIGH 红横条 + 闪烁 + 居中大警告)
   - B4: 无脸检测 (红底白字横条 + 倒计时 + 闪烁)
3. **Part C: 6 个回归测试** (tests/)

### Out of Scope

- v4.2 校准模块的自有 cv2 UI 重设计 (v4.2 模块已用, 不动)
- 5 个主 GUI 项的更多视觉风格 (深色主题/动画) - 留 v4.5+
- 数据采集本身的优化 (threading 重构等) - 不在 v4.4 范围

---

## 三、详细设计

### Part A: 校验阶段 REC 指示

#### A1. 常驻 ●REC 指示

**位置**: calibration/flow.py `_render_calibration` panel header

```python
# calibration/flow.py _render_calibration 内部, panel_info 加:
panel_info["rec_indicator"] = "●REC 录制中"  # 始终显示

# 渲染时 panel 顶部 (line 145 附近):
rec_text = "●REC 录制中"
put_chinese_text(panel_img, rec_text, (10, 18), color=COLOR_RED, ...)
```

颜色: 红 `(0, 0, 255)` 或醒目绿 `(0, 200, 0)`, 待设计确认用绿 (录制中 = 安全 = 绿)

#### A2. 拖窗口检测 + 提示

**启发式** (OpenCV 不直接暴露 drag 事件):
- track `_last_render_time`: panel 渲染时间戳
- track `_last_waitkey_return_time`: waitKey 返回时间戳
- 拖窗口时: waitKey 调用频率骤降 (cv2 事件循环被 OS 拖动占用), 但 frame reading thread 仍工作
- 检测条件: `frame_time - last_waitkey_time > 200ms` 表示 waitKey 卡住了 → 拖窗口中

**实现**:
```python
# calibration/flow.py
class CalibrationFlow:
    def __init__(...):
        self._last_waitkey_time = time.time()
        self._drag_start_time: Optional[float] = None

    def _tick_once(self, ...):
        # ... 现有代码 ...
        key = cv2.waitKey(1) & 0xFF
        self._last_waitkey_time = time.time()
        # ... 现有代码 ...

    def _build_display_info(self) -> dict:
        info = {...}  # 现有
        # 拖窗口检测: 距上次 waitKey 超过 200ms
        if time.time() - self._last_waitkey_time > 0.2:
            if self._drag_start_time is None:
                self._drag_start_time = time.time()
            info["dragging"] = True
        else:
            self._drag_start_time = None
            info["dragging"] = False
        return info
```

**panel 渲染** (PanelRenderer.draw 或 flow._render_calibration):
```python
if info.get("dragging"):
    # 半透明黑色遮罩覆盖整个 panel
    overlay = panel_img.copy()
    cv2.rectangle(overlay, (0, 0), (panel_w, panel_h), (0, 0, 0), -1)
    panel_img = cv2.addWeighted(overlay, 0.5, panel_img, 0.5, 0)
    # 中央显示 "❄ DRAGGING 画面冻结 (数据继续录制)"
    cv2.putText(panel_img, "❄ DRAGGING 画面冻结", ...)
    cv2.putText(panel_img, "(数据继续录制)", ...)
```

#### A3. 自动恢复
- 拖完窗口, waitKey 频率恢复, `_last_waitkey_time` 接近 `time.time()`, `dragging` 自动变 False
- 遮罩消失, panel 继续显示最新帧

### Part B: 主 GUI 清晰化

#### B1. MODE 状态栏 (gui/overlay.py `_draw_status_bar`)

**变更**:
- 圆点半径 5 → 12 (2.4x)
- 字体 0.55 → 0.75
- thickness 1 → 2
- 模式名前缀 ● (Unicode 圆点 25CF)

**实现**:
```python
# gui/overlay.py
def _draw_status_bar(...):
    # 替换 line 286 附近:
    cv2.circle(frame, (x + 6, y_main - 5), 12, mode_color, -1)  # 原 radius=5
    cv2.putText(frame, f"●{self._current_mode}", (x + 25, y_main),  # 原 (x + 18, ...)
                self.config.font, 0.75, mode_color, 2)  # 原 0.55, 1
```

#### B2. focus score 圆环 (`_draw_focus_display`)

**变更**:
- 半径 50 → 70
- 中心数字 字号 0.6 → 1.5
- 数字上方加 "FOCUS" 标签 (字号 0.5)
- 圆环加 8px 边框, 颜色按分数

**实现**:
```python
# gui/overlay.py _draw_focus_display
def _draw_focus_display(self, frame, focus_score, fatigue_level):
    h, w = frame.shape[:2]
    center_x = w - 90
    center_y = h - 130
    radius = 70  # 原 50

    # 圆环背景
    cv2.circle(overlay, (center_x, center_y), radius, (40, 40, 40), -1)
    # 8px 边框 (颜色按分数)
    border_color = self._focus_color(focus_score)
    cv2.circle(overlay, (center_x, center_y), radius, border_color, 8)  # 原 thickness=2
    # FOCUS 标签
    cv2.putText(frame, "FOCUS", (center_x - 30, center_y - 30),
                self.config.font, 0.5, COLOR_TEXT_MUTED, 1)
    # 中心数字 (大字)
    cv2.putText(frame, f"{focus_score:.0f}", (center_x - 30, center_y + 18),
                self.config.font, 1.5, COLOR_WHITE, 3)  # 原 0.6, 1
```

#### B3. fatigue 告警醒目 (gui/overlay.py 新增 `_draw_fatigue_alert`)

**变更**:
- MEDIUM: 顶部状态栏下方加 4px 黄色横条 (在 status bar 60px 下方)
- HIGH: 8px 红色横条 + 闪烁 (0.5s 周期) + 居中 "⚠ 疲劳警告 ⚠"

**实现**:
```python
# gui/overlay.py
def _draw_fatigue_alert(self, frame, fatigue_level):
    if fatigue_level is None or fatigue_level == "LOW":
        return frame
    h, w = frame.shape[:2]
    bar_y = self.config.status_bar_height  # 60
    if fatigue_level == "MEDIUM":
        cv2.rectangle(frame, (0, bar_y), (w, bar_y + 4), (0, 200, 220), -1)
    elif fatigue_level == "HIGH":
        # 闪烁 (基于时间)
        if int(time.time() * 2) % 2 == 0:  # 0.5s 周期
            cv2.rectangle(frame, (0, bar_y), (w, bar_y + 8), (0, 0, 220), -1)
        # 居中大警告
        cv2.putText(frame, "⚠ 疲劳警告 ⚠", (w // 2 - 100, h // 2),
                    self.config.font, 1.2, (0, 0, 255), 3)
    return frame
```

**调用点**: overlay.draw() line ~237 后:
```python
overlay = self._draw_alerts(overlay)
overlay = self._draw_fatigue_alert(overlay, fatigue_level)  # 新增
```

#### B4. 无脸检测提示 (gui/overlay.py 新增 `_draw_no_face_banner`)

**变更**:
- 红底白字横条居中
- 字号 1.2
- 显示 "● 请将面部对准摄像头 ●" + 丢失秒数倒计时
- 闪烁 (0.5s 周期)

**实现**:
```python
# gui/overlay.py
def _draw_no_face_banner(self, frame, face_detected, last_face_time):
    if face_detected:
        return frame
    h, w = frame.shape[:2]
    # 5 秒后才显示 (避免一过性闪烁)
    if last_face_time is None or time.time() - last_face_time < 5.0:
        return frame
    lost_sec = int(time.time() - last_face_time)
    # 红底白字横条
    text = f"● 请将面部对准摄像头 ({lost_sec}s) ●"
    (tw, th), _ = cv2.getTextSize(text, self.config.font, 1.2, 3)
    bar_w = tw + 40
    bar_h = th + 30
    bar_x = (w - bar_w) // 2
    bar_y = h // 2 - bar_h // 2
    if int(time.time() * 2) % 2 == 0:  # 闪烁
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (0, 0, 200), -1)
    cv2.putText(frame, text, (bar_x + 20, bar_y + th + 15),
                self.config.font, 1.2, COLOR_WHITE, 3)
    return frame
```

**调用点**: overlay.draw() line ~220 后 (在 _draw_status_bar 后), 接收 `face_detected` + `last_face_time`:
```python
def draw(self, frame, face_detected=True, last_face_time=None, ...):
    ...
    overlay = self._draw_status_bar(...)
    overlay = self._draw_no_face_banner(overlay, face_detected, last_face_time)  # 新增
```

main.py 传入 `last_face_time=self._last_face_time` (新增追踪字段).

### Part C: 6 个回归测试 (tests/test_gui.py + tests/test_calibration_v4_2.py)

| 测试 | 文件 | 覆盖 |
|------|------|------|
| `test_rec_indicator_in_panel_info` | test_calibration_v4_2.py | calibration/flow.py _build_display_info 包含 rec_indicator |
| `test_dragging_detected_when_waitkey_stalls` | test_calibration_v4_2.py | 模拟 waitKey 卡住 200ms+, info["dragging"]==True |
| `test_dragging_clears_when_waitkey_resumes` | test_calibration_v4_2.py | 拖完 info["dragging"]==False |
| `test_mode_dot_radius_12` | test_gui.py | _draw_status_bar 圆点 radius=12 |
| `test_focus_circle_radius_70` | test_gui.py | _draw_focus_display 圆环 radius=70 |
| `test_fatigue_alert_high_draws_warning` | test_gui.py | fatigue=HIGH 时 _draw_fatigue_alert 绘制 "⚠ 疲劳警告 ⚠" |
| `test_no_face_banner_after_5s` | test_gui.py | 无脸 5s+ 后 _draw_no_face_banner 绘制红底白字 |

---

## 四、数据流

```
┌─────────────── v4.2 校验阶段 ───────────────┐
│ CalibrationFlow._tick_once():              │
│   1. frame = camera.read()                  │
│   2. feed_frame(ear, yaw, pitch)  ←  数据继续记录 (即使拖窗口)
│   3. cv2.waitKey(1) & 0xFF  ←  拖窗口时卡住, 但 cv2 仍返回
│      → _last_waitkey_time = time.time()    │
│   4. _build_display_info()                 │
│      → 检测 time.time() - _last_waitkey_time > 200ms → dragging=True
│   5. panel.render(info)                     │
│      → info["rec_indicator"] = "●REC 录制中"
│      → info["dragging"] 时叠加 "❄ DRAGGING 画面冻结"
│   6. cv2.imshow("EyeFocus 校准", composed)  ← 拖窗口时画面冻结
│      → 拖完补上最新帧
└──────────────────────────────────────────────┘

┌─────────────── 主程序 GUI ───────────────┐
│ EyeFocusApp._render_frame(frame):              │
│   ...                                            │
│   overlay = self._overlay.draw(                │
│       frame, focus_score, fatigue_level,        │
│       face_detected,                            │
│       last_face_time=self._last_face_time,  # 新增
│   )                                              │
│   ↓                                              │
│ FocusOverlay.draw():                            │
│   1. _draw_status_bar()        → 圆点 12px, MODE 粗体
│   2. _draw_no_face_banner()    → 5s+ 无脸红底白字
│   3. _draw_focus_display()      → 圆环 70px, 数字 1.5x
│   4. _draw_fatigue_alert()      → MEDIUM 黄色横条 / HIGH 闪烁红横条
│   5. _draw_alerts() / _draw_calibration() / ...
└──────────────────────────────────────────────┘
```

---

## 五、错误处理

| 错误场景 | 处理 |
|---------|------|
| last_face_time 为 None (程序刚启动) | 不显示 no_face_banner (避免启动时闪烁) |
| waitKey 返回时间异常 (系统卡顿) | dragging 阈值 200ms 防误触 |
| fatigue_level 字符串未知 | _draw_fatigue_alert 不绘制 |
| 旧 test 期望旧的圆点/圆环尺寸 | 同步更新 test_gui.py 中相关断言 |

---

## 六、测试计划

### 6.1 单元测试 (TDD)

按 Part C 表格加 7 个测试, 跑全套 575+ passed, 零回归.

### 6.2 真机实测

- 跑 `python main.py` 5 分钟 (校准 + 主监测)
- 校准阶段拖窗口 → 确认 ●REC + DRAGGING 提示
- 主监测中疲劳切到 MEDIUM/HIGH → 确认横条
- 移开摄像头让人脸丢失 → 确认红底白字横条
- 5 项指标都要目视清晰

### 6.3 验收

- 远端 main 推上后, 用户跑 5min 确认 5 项清晰
- 旧 v4.3 568 passed 不回归

---

## 七、文件变更清单

| 文件 | 变更 |
|------|------|
| calibration/flow.py | 加 `_last_waitkey_time` / `_drag_start_time` 追踪 + `_build_display_info` 加 `rec_indicator` 和 `dragging` |
| calibration/panel.py (或 flow._render_calibration) | panel 顶部加 `●REC` 文字 + dragging 时叠加遮罩 |
| gui/overlay.py | 重设计 _draw_status_bar (圆点 12, 字体 0.75) / _draw_focus_display (圆环 70) / 新增 _draw_fatigue_alert / 新增 _draw_no_face_banner |
| main.py | `_render_frame` 调 `_draw_fatigue_alert` 和 `_draw_no_face_banner` + 追踪 `self._last_face_time` |
| tests/test_calibration_v4_2.py | 加 3 个测试: rec_indicator / dragging detected / dragging clears |
| tests/test_gui.py | 加 4 个测试: mode dot radius / focus circle radius / fatigue alert / no face banner |

预计 6 commit (test+fix 配对), 工作量 2-3 小时.

---

## 八、版本管理

- 不需要 bump 文档版本 (CLAUDE.md §1.5)
- 留作 v4.3 维护的后续 v4.4 小版本
- 在 PHASE2_PLAN.md §2.8.3 增一段记录 v4.4 GUI 清晰化 + 拖窗口 REC
- AUDIT_v4.3.md 仍适用 (审计范围不变)

---

## 九、风险与缓解

| 风险 | 缓解 |
|------|------|
| 闪烁动画干扰用户 | 用 0.5s 周期 (不闪得人头晕) + 闪烁时同时显示静态大文字 |
| 圆环 70px 可能超出窗口边 | 仅对小窗口 (≤480 高) 检测, 自动缩小; 默认 480 高度够 |
| 拖窗口检测 200ms 阈值太短 | 设为可调 config, 默认 200ms 平衡灵敏度 |
| 旧测试因新尺寸失败 | 同步更新 test_gui.py 断言 |

---

## 十、Lesson (来自 v4.3 集成残留 _paused bug)

v4.3 维护删 `_paused` 字段时没检查下游 `_render_frame` 引用, 导致拖窗口崩溃。
本次 v4.4 同样涉及 _render_frame 改造, 需在删字段前 grep 验证下游消费者。

---

## 附录 A: 旧 GUI vs 新 GUI 对比

| 元素 | 旧 v4.3 | 新 v4.4 |
|------|---------|---------|
| 状态栏圆点 | r=5 | **r=12** |
| 状态栏字体 | 0.55 | **0.75** |
| 状态栏模式 | "MONITORING" | "● MONITORING" |
| focus 圆环 | r=50, 数字 0.6 | **r=70, 数字 1.5** |
| focus 边框 | 2px | **8px (颜色按分数)** |
| fatigue 切换 | 文字颜色变 | **+ 顶部彩色横条 + HIGH 闪烁** |
| 无脸提示 | 小字居中 | **红底白字大横条 + 倒计时 + 闪烁** |
| 校准阶段 | 无 REC 指示 | **●REC 录制中 (常驻)** |
| 校准拖窗口 | 画面冻结无提示 | **+ ❄ DRAGGING 画面冻结 提示** |
