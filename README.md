# EyeFocus Insight

**眼动追踪与疲劳检测系统** — 基于 MediaPipe Face Mesh 实时分析专注度、疲劳和分心行为，生成个性化 HTML 报告。

![Python](https://img.shields.io/badge/Python-3.12-blue) ![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green) ![MediaPipe](https://img.shields.io/badge/MediaPipe-FaceMesh-orange) ![License](https://img.shields.io/badge/License-MIT-lightgrey) ![Privacy](https://img.shields.io/badge/Privacy-Local%20Only-success)

---

## 目录

- [功能](#-功能)
- [截图](#-截图)
- [系统要求](#-系统要求)
- [快速开始](#-快速开始)
- [使用指南](#-使用指南)
- [FAQ](#-faq)
- [技术栈](#-技术栈)
- [项目结构](#-项目结构)
- [隐私与数据](#-隐私与数据)
- [贡献](#-贡献)
- [路线图](#-路线图)
- [已知限制](#-已知限制)
- [致谢](#-致谢)
- [License](#-license)

---

## ✨ 功能

### 实时监测
| 功能 | 描述 |
|------|------|
| 👁️ **眨眼检测** | EAR (Eye Aspect Ratio) 实时计算，眨眼事件追踪 |
| 🎯 **专注度分级** | 30 秒滑动窗口 → FOCUSED / NORMAL / DISTRACTED 三档，信号驱动 EMA 恢复 |
| 😫 **疲劳评估** | 信号驱动衰减 + PERCLOS 锚点插值 + 持续睁眼加速恢复 |
| 👓 **眼镜检测** | blendshapes + 眼角距离双保险，自动适应是否戴镜 |
| 💡 **光照感知** | 三级亮度分类，低光照时自动降低检测阈值 |
| ➡️ **头部追踪** | yaw/pitch/roll 实时显示 + 滑动窗口平滑滤波 |
| 🎯 **视线追踪** | 纯瞳孔偏移视线估计 + 个人虹膜基线校准 |
| 🔇 **分心识别** | 综合视线和面部存在检测，区分短/中/长分心事件 |

### 离线分析
| 功能 | 描述 |
|------|------|
| 📊 **变点检测** | PELT 算法识别专注度变化转折点 |
| 🚨 **异常检测** | IsolationForest 标记异常行为会话 |
| 📈 **趋势分析** | STL 时间序列分解，展示长周期趋势 |
| 🎯 **因素归因** | Cohen's d 效应量评估各因素对专注度的影响 |

### 专注力工具
| 功能 | 描述 |
|------|------|
| 🍅 **番茄工作法** | 状态机引擎（IDLE/WORKING/BREAK/PAUSED），自定义时长，托盘气泡通知 |
| 🔥 **游戏化激励** | 连续打卡天数、今日专注累计时长、跨零点自动续期 |
| ⏰ **智能提醒** | 定时休息提醒、长时间分心提醒、可配置间隔时间 |

### AI 分析（可选）
| 功能 | 描述 |
|------|------|
| 🤖 **AI 分析摘要** | 内置模板 / Ollama 本地 / llama-cpp-python 三种后端 |
| 📥 **本地推理** | 可选 Ollama 或 llama-cpp-python 本地推理，零网络请求 |
| ⚙️ **一键切换** | 系统托盘菜单一键切换 AI 后端 |
| 🛡️ **超时保护** | LLM 调用 15s 超时自动降级，不影响主流程 |

### 扩展
| 功能 | 描述 |
|------|------|
| 🌐 **Web 仪表盘** | aiohttp 后台 HTTP + WebSocket 服务器，浏览器实时查看 |
| ⚙️ **设置面板** | 图形化 QDialog 配置，替代 config.yaml 手动编辑 |

### 报告与数据
| 功能 | 描述 |
|------|------|
| 📄 **HTML 报告** | 3 Tab 概览/数据/建议，专注度趋势+疲劳+眨眼+日历热力图 |
| 📊 **可视化图表** | Plotly 交互式图表：降采样趋势线、间隙自适应标记点、宽柱眨眼图 |
| 🗓️ **周报** | 聚合 7 天数据分析长周期趋势 |
| 📤 **CSV 导出** | 帧记录 / 专注记录一键导出为 CSV |
| 🔍 **会话历史** | SQLite 浏览历史会话，报告快速跳转 |

---

## 📸 截图

| 校准对话框 | 监测窗口 | HTML 报告 |
|:---:|:---:|:---:|
| ![校准](docs/screenshots/calibration.png) | ![监测](docs/screenshots/monitoring.png) | ![报告](docs/screenshots/report.png) |

> 截图可通过运行 `python main.py --qt` 后获取。

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

### 5.（可选）下载本地 AI 模型

如需要使用本地 AI 分析功能，需额外下载模型文件：

```bash
python scripts/download_model.py
```

### 6. 运行测试

```bash
python -m pytest tests/ calibration/tests/ --tb=line -q
```

---

## 📚 使用指南

### 校准流程

首次使用需完成校准，Qt 校准对话框引导 4 步骤：

1. **睁眼基线** — 保持自然睁眼
2. **闭眼检测** — 轻轻闭上双眼
3. **头部姿态** — 上下左右转动头部
4. **眨眼计数** — 正常眨眼后输入次数

校准结果自动应用，可直接进入监测模式。

### 监测模式

- **实时数据面板**：专注度 FocusRing 圆环 / 专注时长 / 番茄倒计时 / 实时波线 / 游戏化栏
- **操控按钮**：⏸ 暂停 / ⚙ 校准
- **番茄工作法**：面板番茄图标点击弹出菜单（开始/暂停/继续/停止/设置时间）
- **系统托盘**：右键菜单含完整番茄控制 + 最近会话子菜单
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

系统采用 blendshapes 眯眼比率 + 眼角距离双保险检测，也支持手动模式切换。

**Q: 数据存储在哪里？本地还是云端？**

全部本地 SQLite 存储，**0 HTTP 请求**，不存储图像帧。详见 [隐私与数据](#-隐私与数据)。

**Q: 番茄工作法怎么用？**

点击主窗口面板的 🍅 图标弹出菜单，选择"开始"即可。支持暂停/继续/停止，也可在托盘右键菜单操作。

**Q: 如何打包成独立 exe？**

参见 [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md#pyinstaller-打包)。

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
| **SQLite** | 本地数据持久化 |

---

## 📁 项目结构

```
EyeFocus Insight/
├── main.py                     # 主程序入口（EyeFocusApp）
├── config.py                   # 集中配置管理
├── detector/                   # 信号采集层（face_mesh / eye_aspect / head_pose / gaze / light）
├── analyzer/                   # 信号分析层（focus / fatigue / glasses / distraction / pomodoro ...）
├── app/                        # main.py 拆分包（camera / processor / calibration）
├── gui/                        # PyQt5 图形界面
├── storage/                    # 数据持久化（SQLite WAL）
├── reporter/                   # HTML 报告生成
├── webserver/                  # 🌐 Web 仪表盘（aiohttp + WebSocket）
├── calibration/                # 校准模块（Qt 对话框引导 4 步骤）
├── tests/                      # 测试（621+ 用例，pytest 全绿）
└── docs/                       # 文档（ARCHITECTURE / USER_GUIDE / API / DEV_GUIDE ...）
```

完整架构说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 🔒 隐私与数据

EyeFocus Insight 的核心设计原则：**数据不出本机**。

### 数据存储

- **本地 SQLite**（`data/eyefocus.db`，WAL 模式）
- **不存储图像帧**，仅存元数据（EAR、yaw、pitch、focus_score 等数值）
- 配置文件、数据库、报告默认存于项目目录内

### 网络请求

- **0 主动 HTTP 请求**（除用户主动启用的功能外）
- **AI 分析可选**：模板版无网络请求；Ollama / llama-cpp-python 仅访问本地回环
- **Web 仪表盘**：仅监听本地端口（默认 `127.0.0.1:8765`）

### 配置中的密钥

- `.env.example` 是占位模板，**不含真实密钥**
- 真实密钥请存于 `.env`（已在 `.gitignore`）
- 云端 API 后端已自 v4.27 起移除

### 摄像头数据流

```
摄像头 → 内存（推理）→ SQLite（数值）→ HTML 报告
                       ↓
                  永不上传
```

---

## 🤝 贡献

欢迎贡献！建议流程：

1. **Fork** 本仓库
2. 创建特性分支（`git checkout -b feat/your-feature`）
3. 提交前运行测试：`pytest tests/ calibration/tests/`
4. 提交（建议一个特性一个 commit）
5. 发起 **Pull Request**

### 提交流程约定

- 提交信息格式：`<type>(<scope>): <summary>`，subject ≤ 70 字
- type：`feat` / `fix` / `docs` / `refactor` / `test` / `chore`
- 测试门禁：新增模块需带测试；覆盖率不下降

详见 [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md) 与 [docs/MODULE_INTERFACES.md](docs/MODULE_INTERFACES.md)。

---

## 🗺️ 路线图

持续迭代方向（详细见各模块代码注释与 `docs/CURRENT_STATE.md`）：

- 多模态融合（脑电 / 微表情）以更好区分"思考"与"分心"
- 跨平台支持（macOS / Linux）
- 报告导出 PDF 格式
- 多人 / 多设备云同步（**默认关闭**，需用户主动开启）

---

## ⚠️ 已知限制

- **MediaPipe WARNING**：`W0000` 日志来自 MediaPipe C++ 层（mediapipe 0.10.35），不影响功能
- **单摄像头**：无法区分"思考时视线偏移"和"真正分心"
- **头部范围**：yaw 超过 ±60° 时关键点检测精度下降
- **平台**：当前仅在 Windows 10/11 实测验证
- **校准依赖**：首次使用必须完成校准（自动基线），未校准则专注度评分不准确

---

## 🙏 致谢

- **MediaPipe** — Google 开源的 478 点 Face Mesh 模型与 blendshapes
- **EAR 算法** — Soukupová & Čech (2016)
- **PELT 算法** — Killick et al. (2012)
- **STL 分解** — Cleveland et al. (1990)
- **IsolationForest** — Liu et al. (2008)
- **Plotly** — 交互式图表渲染
- **PyQt5** — 跨平台 GUI 框架

---

## 📄 License

本项目采用 **MIT License** — 详见 [LICENSE](LICENSE) 文件。

```
MIT License

Copyright (c) 2026 EyeFocus Insight Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```