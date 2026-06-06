# EyeFocus Insight — PyQt5 GUI 迁移方案

> **版本**：v1.0 | **日期**：2026-06-06
> **背景**：用户反馈 OpenCV 原生窗口存在渲染质量差、半透明叠加看不清、缺少视觉分区三大问题，决定迁移至 PyQt5。

---

## 一、技术路线

**方案**：OpenCV 捕获视频 + PyQt5 显示与 UI（非纯 PyQt5 方案）

```
CameraManager (OpenCV) → 帧队列 → PyQt5 QLabel/QPixmap 显示
                                  ↕
                            Qt Widget 叠加层 (标签、按钮、进度条)
                                  ↕
                            QSS 样式表控制视觉效果
```

- **摄像头捕获**：保留现有的 `CameraManager` / `cv2.VideoCapture`（Qt 的 QCamera 在 Windows 上不如 OpenCV 灵活）
- **显示**：PyQt5 `QMainWindow` + `QLabel`（用于视频帧）+ 叠加的 `QWidget`（按钮、标签、进度条）
- **渲染**：`QTimer` 定时器驱动帧更新（类似 OpenCV 的 waitKey 循环）
- **校准 UI**：PyQt5 `QDialog` 或 `QWidget` 替换现有的 OpenCV 校准窗口

---

## 二、架构设计

### 2.1 主窗口结构

```
EyeFocusWindow (QMainWindow)
├── Central Widget (QWidget)
│   ├── VideoLabel (自定义 QLabel, 重写 paintEvent)
│   │   └── 绘制: 摄像头帧 + QPainter 叠加文字/图形
│   ├── ModeSwitcher (QStackedWidget)
│   │   ├── 极简模式 MinimalOverlay (QWidget)
│   │   │   ├── 居中大号 FOCUS 数字 (QLabel, font-size: 72pt)
│   │   │   ├── 底部疲劳横条 (QProgressBar, 全宽, 20px)
│   │   │   └── 右下状态文字 (QLabel, Face/Eye ✓✗)
│   │   └── 完整模式 FullOverlay (QWidget)
│   │       ├── 顶部状态栏 (QWidget + 4 段 QLabel)
│   │       ├── 右下专注度圆环 (QPainter 圆形)
│   │       ├── FPS (右下角 QLabel)
│   │       └── 校准进度条 (QProgressBar)
│   └── KeyHintsBar (QWidget, 底部常驻快捷键提示)
├── 菜单栏 / 工具栏 (可选)
└── 状态栏 (QStatusBar, 显示模式/状态)
```

### 2.2 校准模块结构

```
CalibrationDialog (QDialog)
├── VideoLabel (QLabel, 摄像头画面)
├── PanelWidget (QWidget, 下半部分 UI 区)
│   ├── PhaseTitle (QLabel, 当前阶段名称/序号)
│   ├── Instruction (QLabel, 操作指引)
│   ├── TimerLabel (QLabel, 剩余时间)
│   ├── ProgressBar (QProgressBar, 阶段进度)
│   └── ButtonPanel (QHBoxLayout)
│       ├── 继续 / 开始 (QPushButton, 绿色)
│       ├── 重做 (QPushButton, 灰色)
│       ├── 跳过校准 (QPushButton, 灰色)  ← v4.4 新增
│       └── 取消 (QPushButton, 红色)
├── 输入模式 (仅眨眼计数时显示)
│   ├── QLineEdit (数字输入)
│   └── 确认按钮
└── 拖窗口检测: 覆盖 ❄ DRAGGING 遮罩
```

### 2.3 数据流

```
CameraManager._camera_read_loop
  → frame_queue (queue.Queue, maxsize=2)    ← 线程安全队列
  → EyeFocusWindow._update_frame (QTimer, ~30fps)
    → QPixmap.fromImage → VideoLabel.setPixmap
    → FrameProcessor.process_frame (同步)
    → 更新 Overlay widgets
    → update()
```

关键：摄像头读取在**独立线程**中运行（现有 `_camera_read_loop`），帧通过线程安全队列传递给 Qt 主线程。Qt 主线程处理帧 + UI 更新，不阻塞摄像头采集。

---

## 三、迁移步骤

### 阶段 A：基础框架搭建（1-2 天）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| A1 | 安装 PyQt5 (`pip install PyQt5`) | `requirements.txt` |
| A2 | 创建 `gui/qt_window.py` — `EyeFocusWindow(QMainWindow)` | 新文件 |
| A3 | 创建 `gui/qt_overlay.py` — 极简/完整模式 Overlay widgets | 新文件 |
| A4 | 创建 `gui/video_label.py` — 视频显示 QLabel | 新文件 |
| A5 | 修改 `main.py` — 集成 Qt 主循环替换 OpenCV 主循环 | `main.py` |

### 阶段 B：监测模式 UI（1-2 天）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| B1 | 极简模式：居中专注度数字 + 底部疲劳条 + 右下状态 | `gui/qt_overlay.py` |
| B2 | 完整模式：顶栏 4 段状态 + 右下圆环 + FPS | `gui/qt_overlay.py` |
| B3 | Tab 切换模式 | `gui/qt_window.py` |
| B4 | Q/ESC/P 快捷键处理（Qt 原生 keyPressEvent） | `gui/qt_window.py` |
| B5 | 底栏快捷键提示 | `gui/qt_window.py` |
| B6 | 主窗口 × 按钮关闭处理 | `gui/qt_window.py` |

### 阶段 C：校准模块 UI（2-3 天）

| 步骤 | 内容 | 涉及文件 |
|------|------|---------|
| C1 | 创建 `calibration/qt_ui/` 包 | 新目录 |
| C2 | `CalibrationDialog(QDialog)` — 校准主窗口 | `calibration/qt_ui/dialog.py` |
| C3 | `PhasePanel(QWidget)` — 阶段信息面板 | `calibration/qt_ui/panel.py` |
| C4 | `BlinkInputPanel(QWidget)` — 眨眼输入面板 | `calibration/qt_ui/input.py` |
| C5 | 按钮样式 QSS（绿/红/灰主题） | `calibration/qt_ui/styles.py` |
| C6 | 集成到 `calibration/flow.py` | `calibration/flow.py` |

### 阶段 D：集成与测试（1 天）

| 步骤 | 内容 |
|------|------|
| D1 | 替换 `main.py` 中 `cv2.imshow` + `cv2.waitKey` 主循环为 Qt 事件循环 |
| D2 | 无脸横幅 / 疲劳警告 / 校准进度条迁移 |
| D3 | 全量回归测试（580+ 项） |
| D4 | 真机实测 |

---

## 四、关键视觉规范

### 4.1 颜色主题

| 用途 | 颜色 (HEX) | RGB |
|------|-----------|-----|
| 背景 | `#1a1a1a` | (26,26,26) |
| 卡片/面板背景 | `#2d2d2d` | (45,45,45) |
| 主要文字 | `#ffffff` | (255,255,255) |
| 次要文字 | `#a0a0a0` | (160,160,160) |
| 专注度高 (FOCUS≥70) | `#00dc82` | (0,220,130) |
| 专注度中 (50-70) | `#ffc107` | (255,193,7) |
| 专注度低 (<50) | `#ff4444` | (255,68,68) |
| 疲劳 LOW | `#00c853` | (0,200,83) |
| 疲劳 MEDIUM | `#ffd600` | (255,214,0) |
| 疲劳 HIGH | `#ff1744` | (255,23,68) |
| 按钮主要 (绿) | `#00c853` | (0,200,83) |
| 按钮危险 (红) | `#d50000` | (213,0,0) |
| 按钮中性 (灰) | `#757575` | (117,117,117) |

### 4.2 字体与字号

| 元素 | 字号 | 粗细 | 字体 |
|------|------|------|------|
| 极简模式 FOCUS 数字 | **72pt** | Bold | Arial / 微软雅黑 |
| FOCUS 标签 | 16pt | Normal | 微软雅黑 |
| 顶栏状态文字 | 14pt | Normal | 微软雅黑 |
| 校准阶段标题 | 24pt | Bold | 微软雅黑 |
| 按键提示 | 10pt | Normal | 微软雅黑 |
| 按钮文字 | 12pt | Bold | 微软雅黑 |

### 4.3 布局规范

- **边距**：12px 统一边距
- **按钮大小**：最小 120×40px，圆角 6px
- **面板间距**：8px
- **疲劳横条高度**：16px（极简模式）/ 8px（完整模式）
- **确认弹窗**：居中 60% 不透明黑色遮罩 + 白色/橙色文字

---

## 五、遗留问题与注意事项

1. **pyttsx3 冲突**：PyQt5 和 pyttsx3 可能因事件循环冲突。解决：保持 `audio_enabled=False`（仅蜂鸣）
2. **帧传递性能**：`queue.Queue` 传递 numpy 数组（通过 `np.array` 序列化），实测 ~1ms 延迟，可接受
3. **GPU 加速**：Qt 默认使用 CPU 渲染。如果 FPS 下降，可考虑使用 `QOpenGLWidget` 代替 `QLabel`
4. **旧代码清理**：迁移完成后删除 `gui/overlay.py` 中的完整模式代码（极简模式保留前半部分）
5. **测试覆盖**：为 Qt widget 添加 pytest-qt 测试

---

## 六、验证标准

- [ ] 主程序启动显示 Qt 窗口，视频流流畅 (≥25fps)
- [ ] Tab 切换极简/完整模式，切换无闪烁
- [ ] 校准窗口打开/关闭，无黑屏切换
- [ ] Q/ESC 快捷键在 Qt 窗口正常工作
- [ ] 按钮鼠标点击正常
- [ ] 580 项 pytest 全绿
- [ ] 中文文字正常显示
