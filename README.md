# EyeFocus Insight

**眼动追踪与疲劳检测系统** — 基于 MediaPipe Face Mesh 实时分析专注度、疲劳和分心行为，生成个性化 HTML 报告。

![Python](https://img.shields.io/badge/Python-3.12-blue) ![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green) ![MediaPipe](https://img.shields.io/badge/MediaPipe-FaceMesh-orange) ![License](https://img.shields.io/badge/License-MIT-lightgrey)

---

## 📖 目录

- [功能](#-功能)
- [截图](#-截图)
- [系统要求](#-系统要求)
- [快速开始](#-快速开始)
- [使用指南](#-使用指南)
- [FAQ](#-faq)
- [技术栈](#-技术栈)
- [项目结构](#-项目结构)
- [进度](#-进度)
- [已知限制](#-已知限制)
- [License](#-license)

---

## ✨ 功能

### 实时监测
| 功能 | 描述 |
|------|------|
| 👁️ **眨眼检测** | EAR (Eye Aspect Ratio) 实时计算，眨眼事件追踪 |
| 🎯 **专注度分级** | 30 秒滑动窗口 → FOCUSED / NORMAL / DISTRACTED 三档 |
| 😫 **疲劳评估** | 融合眨眼率、EAR 谷值、头部稳定性的疲劳等级 |
| 👓 **眼镜检测** | blendshapes + 眼角距离双保险，自动适应是否戴镜 |
| 💡 **光照感知** | 三级亮度分类，低光照时自动降低检测阈值 |
| ➡️ **头部追踪** | yaw/pitch/roll 实时显示 + 5 帧滑动窗口平滑滤波 |
| 🔇 **分心识别** | 综合视线和面部存在检测，区分短/中/长分心事件 |
| 📉 **分心原因分析** | 实时计算头部偏移% + 眨眼异常%，分心时显示归因标签 |

### 离线分析
| 功能 | 描述 |
|------|------|
| 📊 **变点检测** | PELT 算法识别专注度变化转折点 |
| 🚨 **异常检测** | IsolationForest 标记异常行为会话 |
| 📈 **趋势分析** | STL 时间序列分解，展示长周期趋势 |
| 🎯 **因素归因** | Cohen's d 效应量评估各因素对专注度的影响 |
| 💡 **个性化建议** | 数据驱动的针对性改善建议 |

### 专注力工具
| 功能 | 描述 |
|------|------|
| 🍅 **番茄工作法** | 状态机引擎（IDLE/WORKING/BREAK/PAUSED），自定义番茄/休息时长，托盘菜单 + 面板双入口控制 |
| 🔥 **游戏化激励** | 连续打卡天数、今日专注累计时长、跨零点自动续期 |
| 🎤 **语音反馈** | pyttsx3 TTS 语音播报：阶段提醒、里程碑、疲劳预警、番茄完成提示 |
| ⏰ **智能提醒** | 定时休息提醒、长时间分心提醒、可配置间隔时间 |

### 扩展
| 功能 | 描述 |
|------|------|
| 🌐 **Web 仪表盘** | aiohttp 后台 HTTP + WebSocket 服务器，浏览器实时查看专注度圆环/指标/波线/番茄状态 |
| ⚙️ **设置面板** | 图形化 QDialog 配置（摄像头、语音、番茄时间），替代 config.yaml 手动编辑 |

### 报告与数据
| 功能 | 描述 |
|------|------|
| 📄 **HTML 报告** | 自动生成含 9 章节的详细报告，专注度/疲劳/分布/分心热力图 |
| 📊 **可视化图表** | Plotly 交互式图表：专注度波线、日历热力图（GitHub 贡献图风格）、模式饼图、异常柱状图 |
| 🗓️ **周报** | 聚合 7 天数据分析长周期趋势，含日历热力图 + 会话汇总表 |
| 📤 **CSV 导出** | 帧记录 / 专注记录一键导出为 CSV |
| 🔍 **会话历史** | SQLite 浏览历史会话，报告快速跳转 |
| 💡 **个性化建议** | 基于数据归因的针对性改善建议 |

---

## 📸 截图

<!-- TODO: 运行 `python main.py --qt` 后截取以下画面替换占位图 -->
| 校准对话框 | 监测窗口 | HTML 报告 |
|:---:|:---:|:---:|
| ![校准](docs/screenshots/calibration.png) | ![监测](docs/screenshots/monitoring.png) | ![报告](docs/screenshots/report.png) |

---

## 💻 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11（其他平台未测试） |
| Python | 3.10+（推荐 3.12） |
| 摄像头 | 任意 USB 或内置摄像头，≥ 30 FPS |
| GPU | 非必需（CPU 推理 ~7ms） |
| 内存 | ≥ 8 GB |

---

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/cacao1357/EyeFocus-Insight.git
cd EyeFocus-Insight
```

### 2. 创建虚拟环境

```bash
python -m venv .venv312
.venv312\Scripts\activate      # Windows
# source .venv312/bin/activate  # Linux/macOS
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 运行程序

**推荐方式 — Qt GUI（校准对话框 + 监测窗口）：**

```bash
python main.py --qt
```

**OpenCV 模式（轻量备选）：**

```bash
python main.py
```

### 5. 运行测试

```bash
# 全部测试（606 个）
python -m pytest tests/ calibration/tests/ --tb=line -q
```

---

## 📚 使用指南

### 校准流程

首次使用需完成校准，Qt 校准对话框引导 4 步骤：

1. **睁眼基线**（5s）— 保持自然睁眼
2. **闭眼检测**（3s）— 轻轻闭上双眼
3. **头部姿态**（4 方向 × 2s）— 上下左右转动头部
4. **眨眼计数**（8s）— 正常眨眼后输入次数

校准结果自动应用，可直接进入监测模式。

### 监测模式

- **实时数据面板**（50:50 视频/面板比例）：
  - 专注度 **FocusRing** 圆环（140×140，32px 大字）
  - 专注时长 ⏱（22px 粗体）、番茄倒计时 🍅（18px）、识别状态 🟢（16px）
  - 实时专注度波线（60s 滑动窗口渐变填充）
  - 游戏化栏 🔥（连续天数 + 今日时长，14px）
- **操控按钮**：⏸ 暂停 / ⚙ 校准（大按钮 13px）
- **番茄工作法**：面板番茄图标点击弹出菜单（开始/暂停/继续/停止/设置时间）
- **系统托盘**：右键菜单含完整番茄控制 + 最近会话子菜单 + 语音开关
- **自动行为**：人脸丢失 > 10s 自动暂停，恢复后自动继续
- **低光照提示**：环境过暗时显示警告并自动降低检测阈值

### 报告查看

关闭程序后自动生成 HTML 报告到 `reports/` 目录，双击即可在浏览器打开。

---

## ❓ FAQ

**Q: 提示"找不到摄像头"？**

检查摄像头连接，或修改 `config.py` 中的 `camera_index`（默认 0，可尝试 1、2）。

**Q: 帧率很低（< 20 FPS）？**

确保在 GPU 驱动正常的环境运行。CPU 模式下 XNNPACK 推理约 7ms，整条流水线约 15ms。

**Q: 戴眼镜检测不准？**

系统采用 blendshapes 眯眼比率 + 眼角距离双保险检测，支持手动开关：
```python
# 在 main.py 启动前设置
app._glasses_detector.set_manual_mode(GlassesMode.WITH_GLASSES)
```

**Q: 数据存储在哪里？本地还是云端？**

全部本地 SQLite 存储，**0 HTTP 请求**，不存储图像帧，保护隐私。

**Q: 番茄工作法怎么用？**

点击主窗口面板的 🍅 图标弹出菜单，选择"开始"即可。支持暂停/继续/停止，也可在托盘右键菜单操作。点击"设置时间"可自定义工作（1-120 分钟）和休息（1-60 分钟）时长。

**Q: 游戏化连续天数怎么计算的？**

系统记录每一天的首次专注会话日期。跨零点后首次监测自动续期，无需手动打卡。连续天数 = 从最近一次有记录的日期往前推算的连续日期数。

**Q: 语音反馈可以关掉吗？**

可以。在托盘右键菜单中取消勾选"🎤 语音反馈"即可关闭 TTS 播报，也可通过 `config.yaml` 中的 `voice.enabled` 配置。

**Q: 报告在哪里？**

会话结束后自动生成到 `reports/` 目录，文件名格式 `{session_id}.html`。

**Q: 如何打包成独立 exe？**

参见 [PyInstaller 打包说明](docs/DEV_GUIDE.md#pyinstaller-打包)。

---

## 🔧 技术栈

| 技术 | 用途 |
|------|------|
| **MediaPipe Face Mesh** | 478 点人脸关键点 + blendshapes |
| **OpenCV** | 摄像头采集 + 图像预处理 |
| **PyQt5** | 图形界面（校准对话框 + 监测窗口 + 系统托盘） |
| **NumPy / SciPy** | EAR 计算 + 统计分析 |
| **scikit-learn** | IsolationForest + KMeans |
| **statsmodels** | STL 时间序列分解 |
| **ruptures** | PELT 变点检测 |
| **Plotly** | 交互式图表（日历热力图/饼图/柱状图/波线） |
| **pyttsx3** | Windows SAPI5 TTS 语音反馈 |
| **SQLite** | 本地数据持久化 |

---

## 📁 项目结构

```
EyeFocus Insight/
├── main.py                     # 主程序入口（EyeFocusApp ~2200 行）
├── config.py                   # 集中配置管理
├── detector/                   # 信号采集层
│   ├── face_mesh.py            # MediaPipe FaceMesh
│   ├── eye_aspect.py           # EAR 眨眼检测 + 多信号融合
│   ├── head_pose.py            # 头部姿态
│   ├── gaze.py                 # 视线估计
│   └── light.py                # 光照检测
├── analyzer/                   # 信号分析层
│   ├── focus.py                # 专注度分析（30s 窗口 + EMA 平滑）
│   ├── fatigue.py              # 疲劳分析
│   ├── glasses.py              # 眼镜检测
│   ├── distraction.py          # 分心识别 + 原因归因
│   ├── pomodoro.py             # 🍅 番茄工作法引擎（状态机）
│   ├── voice_assistant.py      # 🎤 TTS 语音反馈
│   ├── reminder_engine.py      # ⏰ 智能提醒引擎
│   ├── gamification.py         # 🔥 游戏化激励（连续天数/今日时长）
│   ├── baseline.py             # EAR 自动基线校准
│   └── insights/               # 离线分析（PELT/IF/KMeans/STL）
├── app/                        # main.py 拆分包（strangler 模式）
│   ├── camera.py               # 摄像头管理类
│   ├── processor.py            # 帧处理流水线
│   └── calibration.py          # 校准流程回调与协调器
├── gui/                        # PyQt5 图形界面
│   ├── qt_window.py            # 监测主窗口（50:50 面板布局）
│   ├── qt_overlay.py           # FocusRing 专注圆环 + 状态波线
│   ├── settings_dialog.py      # ⚙️ 图形化设置面板（v4.22）
│   ├── tray.py                 # 系统托盘（番茄菜单/语音开关/会话历史）
│   ├── calibration_dialog.py   # 校准对话框
│   └── video_label.py          # QLabel 视频渲染
├── storage/                    # 数据持久化
│   ├── db.py                   # SQLite WAL 模式数据库
│   └── models.py               # 数据模型（Session/FrameRecord/BlinkRecord）
├── reporter/                   # HTML 报告
│   ├── report_html.py          # 报告生成 + 周报
│   ├── charts.py               # Plotly 图表（日历热力图/饼图/柱状图/波线）
│   └── insights.py             # 建议生成
├── webserver/                  # 🌐 Web 仪表盘（aiohttp + WebSocket, v4.22）
│   ├── server.py               #    HTTP + WebSocket 服务器
│   └── static/index.html       #    前端仪表盘（FocusRing/波线/指标）
├── calibration/                # 校准模块（Qt 对话框引导 4 步骤）
├── tests/                      # 测试（606+ 用例）
└── docs/                       # 文档
```

完整架构说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 📈 进度

| 版本 | 内容 | 测试 |
|------|------|:----:|
| **v3.4** | 帧处理重构（FrameProcessor） | 251 |
| **v4.0** | 10 个审计发现修复 | 275 |
| **v4.1** | insights 离线分析子包 | 284 |
| **v4.2** | calibration 模块重做 | 284 |
| **v4.3** | 集成校准 + GUI + 44 audit fixes | 556 |
| **v4.4** | GUI 清晰化（圆环/横条/无脸检测） | 580 |
| **v4.5** | Qt 校准对话框 + 眨眼验证闭环 | 580 |
| **v4.6** | Insights + 分心识别 + 建议升级 | 408 |
| **v4.7** | Qt 校准重设计 + 边界修复 | 606 |
| **v4.17** | 语音反馈 + 智能提醒 + 游戏化 + 分心归因 + 周报 | 606 |
| **v4.18** | 会话历史浏览器 + 番茄工作法 + CSV 导出 + 周报 | 606 |
| **v4.19** | 代码审查修复 + 文件归档 + 路径管理 + UI 修复 | 606 |
| **v4.20** | 报告修复 + 卡片去字 + 番茄增强 + 按钮美化 | 606 |
| **v4.21** | 面板 50:50 布局重设计 + FocusRing + QLabel 大字体 | 606 |
| **v4.22** | main.py 拆分（strangler）+ 设置面板 + Web 仪表盘 | 606 |
| **v4.23** | 黑背景 + 报告打不开 根因修复（查看终止分离） | 606 |
| **v4.24** | 日历图/gamification typo/QMenu黑背景/弹窗精简/Web增强 | 606 |

---

## ⚠️ 已知限制

- **MediaPipe WARNING**：`W0000` 日志来自 MediaPipe C++ 层（mediapipe 0.10.35），不影响功能
- **单摄像头**：无法区分"思考时视线偏移"和"真正分心"
- **头部范围**：yaw 超过 ±60° 时关键点检测精度下降
- **GUI 渲染**：CLI 环境无法验证像素输出，完整视觉验证需 Windows GUI 桌面
- **TTS 语音**：pyttsx3 基于 Windows SAPI 5，仅 Windows 平台可用
- **main.py 体量**：主文件约 2200 行，后续版本计划拆分
- **校准依赖**：首次使用必须完成校准（自动基线），未校准则专注度评分不准确

---

## 📄 License

MIT
