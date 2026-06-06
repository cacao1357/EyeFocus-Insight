# `gui/` — OpenCV 渲染层

> v4.0+ 基础，**v4.4 大改** | 测试覆盖 ~63% + 4 个 v4.4 新增 | 状态：✅ 活跃

**职责**：**主监测 UI 渲染**——把帧数据（focus_score / fatigue_level / 关键点）叠加到 BGR frame 上显示。**校准 UI 已迁出**（v4.2 移至 `calibration/ui/panel.py`），本目录**仅**承担主监测渲染。

## 公共 API（`__init__.py` 单入口）

```python
from gui import create_focus_overlay, FocusOverlay, OverlayConfig

overlay = create_focus_overlay(OverlayConfig(
    show_fps=True,
    show_mode_indicator=True,
    show_no_face_banner=True,  # v4.4
    show_fatigue_bar=True,     # v4.4
))
frame = overlay.draw(bgr_frame, focus_score=0.75, fatigue_level="MEDIUM",
                     face_detected=True, mode="MONITORING")
```

| 公共符号 | 用途 |
|---------|------|
| `FocusOverlay` | 主渲染类（cv2 in / cv2 out）|
| `OverlayConfig` | 渲染配置 dataclass |
| `CalibrationProgress` | 校准进度数据类（**主程序不再使用**，保留向后兼容）|
| `AlertLevel` / `AlertMessage` | 报警级别 + 消息（v4.4 no-face / fatigue 切档）|
| `create_focus_overlay()` | 工厂 |

## 文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `overlay.py` | 850 | `FocusOverlay` 全部渲染逻辑（v4.4 占 5/7 commit）|

## v4.4 GUI 清晰化（5 commit）

| Commit | 改进 |
|--------|------|
| `b177538` | MODE 状态栏圆点 2.4x + 字体 1.36x + ● 前缀 |
| `63132db` | focus 圆环 r=70 + 数字 1.5x + 8px 边框颜色按分数 |
| `dbb0fd4` | fatigue 切档彩色横条（MEDIUM 黄 / HIGH 红闪烁 + 大警告）|
| `d5b2243` | no-face banner（5s 阈值 + 红底白字横条 + 闪烁）|
| `398a369` + `c99a254` | 校准 panel ●REC + 拖窗口 DRAGGING（位于 `calibration/ui/panel.py`）|

## 测试入口

```bash
pytest tests/test_gui.py -v
```

## 关键依赖

- `cv2`（OpenCV）— 字体/矩形/文字渲染
- `numpy` — 帧数据
- `main.py:717` 创建 `FocusOverlay` 实例并 `overlay.draw(frame, ...)` 每帧调用

## 已知技术债

- 与主程序 main.py 直接耦合（line 1007-1021）。属于"不重构"范畴（`docs/MODULE_INTERFACES.md` §2.6 v4.4 升至 ⭐⭐⭐ 但仍不主动重构）。
