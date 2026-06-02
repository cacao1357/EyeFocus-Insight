# EyeFocus Insight — 项目总体规划方案

> **版本**：v4.2 | **制定日期**：2026-05-28 | **修订日期**：2026-06-02
> **方法论**：gstack（YC Office Hours → CEO Review → Eng Review → Build → Ship）
>
> **团队规模**：3 人 | **工期**：约 29 天（含 insights Spike + calibration 重设计 + 实施） | **目标平台**：Windows 笔记本 | **项目定位**：课程/作品集

---

## 目录

1. [项目概述](#1-项目概述)
2. [功能与交付](#2-功能与交付)
3. [技术架构](#3-技术架构)
4. [项目管理](#4-项目管理)
5. [附录](#5-附录)

---

# 第一部分：项目概述

## 1. 项目概述

### 1.1 项目简介

EyeFocus Insight 是一款**个人工作状态的可量化自我认知工具**，帮助用户了解自己在屏幕前的专注程度和疲劳状态。

**一句话描述**：通过摄像头实时分析面部特征，量化你的专注度与疲劳程度，生成可执行的个性化建议。

**项目定位**：课程/作品集项目——需要展示完整的工程素养（可运行性、可维护性、可解释性），同时具备差异化创新点。

### 1.2 核心目标层次

| 层次 | 目标描述 |
|------|---------|
| **即时层** | 实时反馈当前专注度与疲劳程度，辅助用户做出休息/继续工作的决策 |
| **会话层** | 每次会话结束后输出结构化数据，形成可追溯的行为记录 |
| **跨会话层** | 对比多次会话数据，发现个人高效时段、疲劳模式、长期趋势 |
| **洞察层** | 生成可执行的个性化建议，而不仅仅是"你今天眨眼 3000 次" |
| **创新层** | 分心模式识别：自动检测分心行为（频繁视线偏离），生成分心热力图 |

### 1.3 用户痛点

```
┌─────────────────────────────────────────────────────┐
│  痛点 1："我不知道我什么时候真正在专注"               │
│  表现：一天过去感觉疲惫但说不清干了什么               │
│  解法：EAR + 头部姿态 + 视线偏离 → 专注度评分        │
├─────────────────────────────────────────────────────┤
│  痛点 2："我感觉眼睛很累，但不知道多累算'太累'"      │
│  表现：等到眼睛干涩/头痛时才意识到，已经晚了           │
│  解法：眨眼率变化 + 闭眼时长 → 疲劳分级预警          │
├─────────────────────────────────────────────────────┤
│  痛点 3："我的高效时段是早上还是下午？我不确定"       │
│  表现：凭感觉安排工作时间，经常选错时间段              │
│  解法：跨会话历史追踪 → 高效时段标注                  │
├─────────────────────────────────────────────────────┤
│  痛点 4："市面上的工具要么太贵，要么摄像头数据传到云端"│
│  表现：拒绝使用需要联网的眼动追踪工具                  │
│  解法：完全本地运行，SQLite 数据不出本机              │
└─────────────────────────────────────────────────────┘
```

### 1.4 目标用户群体

| 用户画像 | 特征 | 使用场景 |
|---------|------|---------|
| **知识工作者（核心）** | 程序员、设计师、写作者，每天面对屏幕 6-12 小时 | 想知道自己"真正专注的时间有多少"，何时应该休息 |
| **远程办公者** | 在家/咖啡厅工作，缺乏办公室社交监督 | 量化自己的工作节奏，对抗"假勤奋" |
| **学生/研究者** | 长时间阅读文献、写论文，容易视疲劳不自知 | 防止长时间用眼导致的视力下降 |
| **量化自我爱好者** | 已有运动手环、睡眠监测等习惯 | 将专注度数据与其他健康数据交叉分析 |

### 1.5 用户旅程

```
[启动程序] → [5-8秒基线校准] → [实时监测(主循环)]
    → [每帧: 人脸检测 → EAR计算 → 头部姿态 → 专注度评分 → GUI更新 → 数据写入SQLite]
    → [用户按Q退出] → [自动生成HTML报告] → [查看报告]
    → [下次启动: 加载历史数据 → 对比分析]
```

### 1.6 关键设计决策

| # | 决策问题 | 推荐方案 | 理由 |
|---|---------|---------|------|
| 1 | GUI 框架 | **OpenCV highgui** | 满足实时显示需求，Tkinter 集成复杂度高 |
| 2 | 专注度算法 | **加权启发式（可解释优先）** | 每评分可追溯到具体指标权重 |
| 3 | 报告格式 | **HTML**（含内嵌图表） | 浏览器即可打开，支持交互式图表 |
| 4 | 多用户支持 | **Phase 2 实现** | MVP 阶段单人使用即可验证核心假设 |
| 5 | 本地 Ollama 问答 | **Phase 3 可选扩展** | 不阻塞 MVP 交付 |
| 6 | 眼镜检测方案 | **Blendshapes + 眼角关键点距离双保险** | Phase 0 实测 EAR 方差法失效（眼镜反而降低方差），blendshapes 方案待 Phase 1 开发验证 |
| 7 | 光照条件感知 | **帧亮度统计 + 摄像头曝光参数** | 零成本实现，区分亮/正常/暗三级，无需深度学习 |
| 8 | 开发-生产差异化策略 | **GPU 验证 → CPU 落地** | 开发端用 RTX 5070 训练模型并验证精度，生产端提取规则/阈值，无外部依赖 |
| 9 | 离线数据分析（v4.1 新增） | **无监督 + 统计方法（聚类/变点/异常/时序/关联）** | 在 SQLite 历史数据上离线运行，不破坏生产端零模型原则；sklearn/scipy/statsmodels/ruptures 均为 pip 离线包 |
| 10 | 离线分析运行时机 | **会话结束时一次性运行** | 不影响主循环 FPS；预算 < 10s 完成 5 个方法 |
| 11 | 用户辅助校准模块隔离（v4.2 新增） | **独立 `calibration/` 子包 + 模块自有摄像头 + 单接口 `calibration.run()` 连接** | 原 T148 实测全部失效；隔离开发不影响主程序 284 测试；可独立运行 `python -m calibration` 调试 |

### 1.7 开发与生产环境差异化策略

```
开发环境（主开发者 D1）                    生产环境（目标用户设备）
─────────────────────────                ─────────────────────────
RTX 5070 Laptop GPU（8 GB VRAM）         集成显卡 / 无独显
32 GB RAM                                8-16 GB RAM
Windows 11 + CUDA 12.4                  Windows 10/11，无 CUDA
RTX 5070 可用                            CPU 推理为主

策略：
  开发端 — 训练/验证深度学习模型（GPU）
    → 提取精度有效的决策规则/阈值
    → 生产端只实现规则，无模型依赖

  示例（眼镜检测）：
    开发端：训练 blendshapes MLP → 验证精度 90%+
    生产端：使用 blendshapes 阈值规则，无模型文件
```

### 1.8 隐私与数据安全

```
数据安全原则：
  ✅ 完全本地运行 — 程序不发出任何 HTTP 请求
  ✅ 摄像头数据不出本机 — 每帧仅保留数值数据（EAR/yaw/...），不存储图像
  ✅ SQLite 文件本地存储 — 数据仅在用户主动导出时才离开本机
  ✅ 报告导出 — HTML 报告可离线打开，不依赖外部 CDN

  ❌ 不使用任何云端服务
  ❌ 不收集任何非必要数据（如 IP、系统信息、用户名）
```

---

# 第二部分：功能与交付

## 2. 功能模块划分

### 2.1 模块总览

```
EyeFocus Insight/
├── main.py                 # 主入口，编排所有模块
├── config.py               # 配置常量（阈值、权重、摄像头参数）
├── detector/
│   ├── face_mesh.py        # MediaPipe Face Mesh 初始化与关键点提取
│   ├── eye_aspect.py       # EAR 计算 / 眨眼检测
│   ├── head_pose.py         # 头部姿态估计（MediaPipe 内置矩阵）
│   ├── gaze.py             # 视线偏离判定
│   └── light.py            # 光照条件检测（帧亮度 + 曝光参数）
├── analyzer/
│   ├── baseline.py         # 自适应基线校准（7秒采集 + 统计）
│   ├── glasses.py          # 眼镜检测（blendshapes 阈值规则）
│   ├── focus.py            # 多指标融合 → 专注度评分
│   ├── fatigue.py          # 疲劳程度分级
│   ├── distraction.py      # 分心模式识别 + 分心热力图
│   └── insights/           # 【v4.1】离线数据分析子包（会话结束/报告时运行）
│       ├── features.py     #   session 级特征工程
│       ├── patterns.py     #   方法 1：聚类（KMeans）— 工作模式发现
│       ├── changepoint.py  #   方法 2：变点检测（ruptures PELT）— 专注度断崖
│       ├── temporal.py     #   方法 3：时序分解（STL）— 高效时段
│       ├── anomaly.py      #   方法 4：异常检测（IsolationForest）— 异常工作日
│       ├── attribution.py  #   方法 5：关联分析（scipy.stats）— 因素归因
│       └── pipeline.py     #   编排：5 个方法的统一入口
├── calibration/            # 【v4.2】用户辅助校准独立模块（取代原 T148）
│   ├── __init__.py         #   公共 API：run(session_id) → Optional[CalibrationResult]
│   ├── __main__.py         #   `python -m calibration` 独立运行入口
│   ├── flow.py             #   流程编排器（单线程主循环 + 状态机）
│   ├── phases/             #   5 个阶段独立类（实现统一 Phase 接口）
│   │   ├── auto_baseline.py / closed_eyes.py / squint.py /
│   │   └── head_pose.py / blink_count.py
│   ├── ui/                 #   上下分屏 UI
│   │   ├── layout.py       #     cv2.vconcat 拼合（视频 640×480 + UI 640×240）
│   │   └── panel.py        #     UI 区渲染 + 屏幕数字键盘按钮
│   ├── audio/              #   音频反馈
│   │   ├── beep.py         #     winsound 蜂鸣
│   │   └── tts.py          #     pyttsx3 中文语音（异步线程）
│   ├── input_handler.py    #   鼠标点击主导 + 键盘加速（IME 兼容）
│   ├── result.py           #   CalibrationResult dataclass（数据契约，冻结字段）
│   ├── config.py           #   CalibrationConfig（阶段时长 + 阈值参数）
│   └── _ime.py             #   Win32 IME 禁用兜底（可选，失败不影响）
├── storage/
│   ├── db.py               # SQLite 建表、写入、查询
│   └── models.py           # 数据模型定义（dataclass）
├── reporter/
│   ├── charts.py           # Matplotlib 图表生成
│   ├── report_html.py      # HTML 报告组装（v4.1 新增 4 章节）
│   └── insights.py         # 个性化建议生成（v4.1 由 attribution 驱动）
└── gui/
    └── overlay.py          # OpenCV 窗口实时显示逻辑（v4.2 校准 UI 已迁出至 calibration/ui/）
```

### 2.2 功能优先级（MoSCoW）

#### Phase 1：Must Have（MVP）

| 功能 | 模块 | 描述 | 工时 |
|------|------|------|------|
| 摄像头捕获 + 人脸检测 | `detector/face_mesh.py` | 打开摄像头，MediaPipe 提取 468 个关键点 | 4h |
| EAR 计算 + 眨眼检测 | `detector/eye_aspect.py` | 计算左右眼 EAR，判定眨眼 | 3h |
| 头部姿态估计 | `detector/head_pose.py` | MediaPipe facial_transformation_matrixes 提取欧拉角 | 2h |
| **光照条件检测** | `detector/light.py` | 帧亮度统计 + 曝光参数，每帧计算光照等级 | 1h |
| 自适应基线校准 | `analyzer/baseline.py` | 前 7 秒采集，计算 PERSONALIZED 基线值 | 3h |
| **眼镜检测** | `analyzer/glasses.py` | Blendshapes + 眼角距离双保险规则 | 2h |
| 专注度评分算法 | `analyzer/focus.py` | 加权融合 → 0-100 评分，每个指标可追溯 | 4h |
| 疲劳分级 | `analyzer/fatigue.py` | 基于眨眼率偏离基线的程度分三级 | 2h |
| SQLite 存储 | `storage/db.py` | 建表、每 0.5 秒写入一条记录 | 3h |
| OpenCV GUI | `gui/overlay.py` | 显示关键点、EAR 折线、专注度数字、光照等级 | 3h |
| 主循环编排 | `main.py` | 状态机 + 各模块串联 | 4h |
| **小计** | | | **31h** |

#### Phase 2：Should Have（重要但非阻塞）

| 功能 | 描述 | 工时 |
|------|------|------|
| 视线偏离判定 + 统计 | `detector/gaze.py` — 头部偏转超阈值累计时长 | 2h |
| 分心模式识别 | `analyzer/distraction.py` — 检测高频视线切换模式 | 4h |
| HTML 报告生成 | `reporter/report_html.py` — 专注度折线图 + 统计摘要 | 6h |
| 个性化建议引擎 | `reporter/insights.py` — 基于规则的建议（v4.1 由 attribution 驱动） | 3h |
| 跨会话数据对比 | `storage/db.py` — 多 session 聚合查询 + 趋势图表 | 3h |
| **【v4.1】共用特征工程** | `analyzer/insights/features.py` — SessionFeatures + 矩阵化 | 1.5h |
| **【v4.1】聚类工作模式** | `analyzer/insights/patterns.py` — KMeans + silhouette 自动选 k | 2h |
| **【v4.1】变点检测** | `analyzer/insights/changepoint.py` — PELT + 关键时刻提取 | 2h |
| **【v4.1】异常检测** | `analyzer/insights/anomaly.py` — IsolationForest + z-score 归因 | 1.5h |
| **【v4.1】时序分解** | `analyzer/insights/temporal.py` — STL + 高效时段 + histogram 降级 | 2h |
| **【v4.1】关联分析** | `analyzer/insights/attribution.py` — t-test + ANOVA + Cohen's d | 2h |
| **【v4.1】Pipeline 编排** | `analyzer/insights/pipeline.py` — 异常隔离 + 持久化 | 1h |
| **【v4.1】报告 4 章节集成** | `reporter/report_html.py` — 模式饼图/异常雷达/24h 折线/建议条形 | 3h |

#### Phase 3：Could Have（锦上添花）

| 功能 | 描述 | 工时 |
|------|------|------|
| EPA 辅助指标 | `detector/eye_aspect.py` — 虹膜轮廓面积作为疲劳二线指标 | 3h |
| 实时音频提醒 | 疲劳达到重度时播放本地提示音 | 1h |
| Streamlit Dashboard | 替代 OpenCV GUI，提供更丰富的数据看板 | 5h |
| 自然语言问答（Ollama） | 本地 LLM 对历史数据进行问答 | 8h |
| PyInstaller .exe 打包 | 将程序打包为 Windows .exe | 3h |
| 完整文档撰写 | README + 架构文档 + API 文档 + 用户手册 | 8h |
| 答辩 PPT 制作 | 项目背景、技术架构、核心算法、演示截图 | 6h |

#### Phase 4：Won't Have（明确不做）

| 功能 | 理由 |
|------|------|
| 云端同步 / 账号系统 | 违反"全离线"原则 |
| 移动端 App | 超出本次项目范围 |
| 多人同时监测 | 场景不存在（个人桌面工具） |
| 付费订阅 | 非商业化项目 |

## 3. 预期成果物

| 交付物 | 描述 | 验收方式 |
|--------|------|---------|
| 核心引擎 | `detector/` + `analyzer/` + `storage/` 四个模块 | 单元测试覆盖核心逻辑 |
| 主程序 | `main.py` — 启动摄像头、实时显示、记录数据 | 实际运行 ≥5 分钟会话 |
| 报告系统 | 会话结束后自动生成 HTML 报告 | 报告含折线图、统计摘要、个性化建议 |
| 依赖清单 | `requirements.txt`，全部为离线可安装的包 | `pip install - r requirements.txt` 无报错 |
| 运行说明 | 简洁的 README.md | 新用户可以照做运行 |

---

# 第三部分：技术架构

## 4. 技术栈选型

| 技术 | 版本要求 | 用途 | 选型理由 |
|------|---------|------|---------|
| Python | 3.9+ | 主语言 | 生态最全 |
| opencv-python | ≥4.8 | 摄像头捕获、图像处理、GUI 显示 | 工业级实时视频处理 |
| mediapipe | 0.10.x | 人脸关键点提取 | 468 点 Face Mesh，CPU 可达 30+ FPS |
| numpy | ≥1.24 | 数值计算 | EAR 公式、角度转换、统计数据 |
| pandas | ≥2.0 | 数据分析与聚合 | 跨会话趋势分析、报告数据整理 |
| matplotlib | ≥3.7 | 图表生成 | 折线图、柱状图，支持 Base64 嵌入 HTML |
| sqlite3 | 内置 | 数据持久化 | 零配置、零依赖、单文件数据库 |
| **scikit-learn** (v4.1) | ≥1.3 | 聚类（KMeans）+ 异常检测（IsolationForest）+ 标准化 | Phase 2 离线分析；pip 离线安装 |
| **scipy** (v4.1) | ≥1.11 | 统计检验（t-test/Spearman）+ 关联分析 | numpy 配套，体积小 |
| **statsmodels** (v4.1) | ≥0.14 | STL 时序分解 + Granger 因果（可选） | 经典统计库，纯 Python |
| **ruptures** (v4.1) | ≥1.1 | PELT 变点检测 | 单一目的库，体积约 5MB |
| **pyttsx3** (v4.2) | ≥2.90 | 中文 TTS（Windows SAPI 后端） | calibration 模块音频反馈（解决 BUG 3 闭眼盲）|

**生产端零额外依赖原则**：所有包均可通过 `pip install` 离线安装。不引入 PyTorch / TensorFlow / ONNX。

**v4.1 离线分析依赖说明**：sklearn / scipy / statsmodels / ruptures 全部为纯 Python/Cython 实现，均为 pip 离线包；PyInstaller 打包后总体积增加约 80 MB（可接受范围）；**仅在会话结束生成报告时执行**，不影响主循环 FPS。

**v4.2 校准模块依赖说明**：`pyttsx3` 后端使用 Windows 自带 SAPI 5.x 中文语音引擎，无需外部下载；初始化失败时 calibration 模块自动降级为蜂鸣-only 模式 + UI 警告。`winsound` 是 Python 内置（Windows-only），非 Windows 环境降级为 TTS-only。两者均失败时 UI 强制警告 + 阶段时长 +50% 补偿用户无音频引导。

**开发端额外依赖**（D1 主开发者专用，不影响生产部署）：

| 技术 | 用途 | 理由 |
|------|------|------|
| PyTorch + CUDA 12.4 | 模型训练、GPU 推理验证 | RTX 5070 加速开发端验证 |
| onnxruntime-gpu | 模型转换验证 | 确保 ONNX 模型在 GPU 上可运行 |

## 5. 系统架构

### 5.1 数据流架构

```
┌──────────┐    ┌─────────────────────────────────────┐
│ 摄像头    │───▶│  detector/face_mesh.py               │
│ (cv2)    │    │  → 468 个面部关键点 (np.array)      │
└──────────┘    └──────────┬──────────┬───────────────┘
                           │          │
                ┌──────────▼──┐  ┌───▼──────────────┐
                │ eye_aspect   │  │ head_pose.py     │
                │ → left_ear   │  │ → yaw, pitch,   │
                │ → right_ear  │  │   roll          │
                │ → blink_flag │  └────────┬─────────┘
                └──────┬──────┘           │
                       │                  │
            ┌──────────▼──┐  ┌───────────▼────────────┐
            │ light.py    │  │ analyzer/              │
            │ → brightness │  │ baseline.py → 基线校准 │
            │ → light_lvl │  │ glasses.py → 眼镜检测  │
            └──────────────┘  │ focus.py → 专注度     │
                              │ fatigue.py → 疲劳     │
                              └──────────┬────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  storage/db.py       │
                              │  → INSERT 每 0.5s   │
                              └──────────┬──────────┘
                                         │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐
    │ gui/overlay.py│  │ reporter/   │  │ 未来: Ollama │
    │ → 实时显示    │  │ → HTML 报告 │  │ → 自然语言   │
    └───────────────┘  └─────────────┘  └─────────────┘
```

### 5.2 状态机：会话生命周期

```
[IDLE] ──▶ [CALIBRATING] ──▶ [RUNNING] ──▶ [REPORTING] ──▶ [IDLE]
   │              │               │              │
   │         采集 7s         主循环          生成 HTML
   │         用户自然状态     实时监测         退出程序
   │
   └── 用户按 Q 退出（任何阶段均可强制退出）
```

### 5.3 单线程主循环

```
单线程主循环（每帧）：
  1. cap.read()                    → 获取帧
  2. light.py 检测光照             → 记录 light_level（亮/正常/暗）
  3. face_mesh.process(frame)      → MediaPipe 推理
  4. eye_aspect(head_pose, ...)   → EAR/姿态计算
  5. glasses.py 检测眼镜            → 记录 glasses_mode
  6. analyzer.update(...)          → 评分/分级
  7. buffer.append(record)        → 缓冲区追加
  8. IF len(buffer) >= 15:        → 每 0.5 秒批量写入 SQLite
  9. gui.render(frame, overlays)  → OpenCV imshow
  10. atexit.register(flush_buffer) → 异常退出时刷盘
```

### 5.4 缺失数据处理策略

```
人脸检测失败时的帧处理：
  ┌─ 单帧丢失（< 2 秒连续）：
  │   写入 SQLite，但 left_ear/yaw 等为 NULL
  │   专注度评分沿用最近有效值（hold-last-value 策略）
  │
  ├─ 连续丢失 2-10 秒：
  │   写入 NULL 记录，GUI 显示 "未检测到人脸"
  │   专注度评分线性衰减至 0（约 5 秒衰减周期）
  │
  └─ 连续丢失 > 10 秒：
       自动暂停会话，记录 pause_start / pause_end
       恢复检测后继续监测，基线不变
```

## 6. 核心算法设计

### 6.1 专注度评分算法

```
专注度评分 = 100 - clamp( W1 × f1(EAR偏离) + W2 × f2(视线偏离) + W3 × f3(头部不稳), 0, 100 )

其中：
  W1 = 0.35  (眨眼异常权重)      — 疲劳主要通过眨眼模式体现
  W2 = 0.35  (视线偏离权重)      — 不看屏幕 = 不专注
  W3 = 0.30  (头部不稳权重)       — 频繁晃动 = 注意力分散

滑动窗口设计：
  f1(EAR偏离)  = |当前EAR(EMA α=0.1) - 基线EAR| / 基线EAR × 100
  f2(视线偏离) = 过去10秒视线偏离帧数 / 总有效帧数 × 100
  f3(头部不稳) = 过去10秒头部角度滚动标准差 / 15° × 100

EMA 平滑：专注度最终值 = 0.15 × 瞬时评分 + 0.85 × 上一帧输出

GUI 底部信息栏示例：
  专注度: 68  [EAR: -3  |  视线: -18  |  头部: -11]  |  光照: Normal  |  眼镜: 否
```

### 6.2 基线校准算法

```
校准数据流（采集 7 秒，约 150-210 帧）：

Step 1: 去除眨眼帧 — blink_flag=1 的帧直接丢弃
Step 2: 去除大幅偏转帧 — |yaw| > 10° 或 |pitch| > 20° 的帧丢弃
Step 3: 对剩余帧取 10% 截尾均值（trimmed mean）

校准质量评分 (CQS):
  CQS 阈值 ≥ 0.60（Phase 0 实测调整）
  ratio_score = (valid_frames / total_frames) × 0.5
  cv_score    = max(0, (1 - ear_cv × 3.0)) × 0.5
  CQS         = min(1.0, ratio_score + cv_score)

  IF 帧丢弃率 > 40%:  CQS = FAIL → 提示"检测到异常动作，请重新校准"
  IF EAR标准差 > 0.05: CQS = WARN → 提示但允许继续

动态漂移补偿（仅用于疲劳判定）：
  baseline_ear(t) = 0.95 × baseline_ear(t-1) + 0.05 × recent_avg_ear
  限制：若 recent_avg_ear < baseline_ear × 0.7（真疲劳），跳过本次更新
```

### 6.3 头部姿态估计

```
方案：MediaPipe facial_transformation_matrixes（4×4 齐次矩阵）

来源：result.facial_transformation_matrixes[0]
含义：将 Canonical Face Model 映射到相机坐标系

✅ 已废弃：cv2.solvePnP + 6 锚点自定义 3D 模型
  - Phase 0 实测 yaw=-80°（完全错误）
  - 原因：自定义 3D 模型坐标与 MediaPipe 实际坐标系不匹配

✅ 正确方案：MediaPipe facial_transformation_matrixes
  - Phase 0 实测：正视 yaw_std=0.59°, pitch_std=0.49°
  - 无需额外训练或模型，生产端零成本
```

### 6.4 疲劳分级量化阈值

```
正常:   眨眼率 < 基线 × 1.3  AND  PERCLOS(闭眼时长占比) < 5%
轻度:   眨眼率 ≥ 基线 × 1.3   OR  PERCLOS ≥ 5%  (持续 15 秒以上)
重度:   眨眼率 ≥ 基线 × 1.8   OR  PERCLOS ≥ 10% (持续 15 秒以上)

PERCLOS = 最近 60 秒内闭眼(blink_flag=1)总时长 / 60
  注："持续 15 秒"条件防止喷嚏/揉眼导致的瞬时误报
```

### 6.5 眼镜/遮挡自动检测

```
⚠️ DEPRECATED — Phase 0 实测 EAR 方差法无法区分眼镜用户

  戴眼镜：EAR 方差 0.0007-0.0016（反而更低）
  不戴眼镜：EAR 方差 0.0008-0.0024（反而更高）
  原因：眼镜限制了眼动幅度，使 EAR 更稳定
  结论：阈值 0.003 对眼镜检测完全失效

✅ 新方案：Blendshapes + 眼角关键点距离双保险（Phase 1 开发验证）

  方案 A — Blendshapes 特征分类：
    输入：52 维 blendshapes 向量
    模型：MLP（开发端训练）→ 提取阈值规则（生产端）
    开发端：训练 ResNet18/MLP，验证精度 > 90%
    生产端：使用 blendshapes 均值/方差阈值，零模型文件

  方案 B — 眼角关键点距离比：
    计算：d_left  = |LM[33] - LM[133]|  （左眼角横向距离）
          d_right = |LM[362] - LM[263]| （右眼角横向距离）
    镜框遮挡时：关键点被部分遮挡，距离异常小
    阈值待 Phase 1 开发端数据确定

  方案 C — 手动模式切换 UI：
    启动时弹出"您是否佩戴眼镜？"确认框
    用户手动选择，结果存入 session 记录
    作为保底方案，与 A/B 并行存在

  生产端决策规则：
    IF 方案 A 置信度 > 85% → 使用 A 结果
    ELSE IF 方案 B 置信度 > 80% → 使用 B 结果
    ELSE → 使用方案 C（手动选择）
```

### 6.6 光照条件检测

```
目标：区分"亮/正常/暗"三级光照条件，用于：
  1. GUI 实时显示光照状态
  2. 记录到 SQLite，用于事后分析
  3. 辅助判断某些异常检测是否由光照导致

方案：帧亮度统计（零成本，每帧可计算）

def estimate_light_level(frame, cap=None):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_bright = np.mean(gray)                    # 0-255
    dark_ratio   = np.sum(gray < 50) / gray.size   # 暗像素占比

    # 摄像头曝光参数（平台相关，可选）
    gain = cap.get(cv2.CAP_PROP_GAIN) if cap else None

    # 综合判断
    if mean_bright > 100:
        return 'bright', mean_bright
    elif mean_bright > 50:
        return 'normal', mean_bright
    else:
        return 'dark', mean_bright

光照等级阈值（基于 S7 数据校准）：
  Bright：  mean_brightness > 100，FPS 稳定 33+
  Normal：  50 < mean_brightness ≤ 100，FPS 轻微下降
  Dark：    mean_brightness ≤ 50，    FPS 可能 < 20

注：不依赖深度学习，无需额外模型，生产端零成本。
```

### 6.7 分心模式识别

```
分心事件定义：
  ┌─ "短暂分心"：gaze_status='away' 持续 3-15 秒
  │
  ├─ "中长分心"：gaze_status='away' 持续 15-60 秒
  │
  └─ "长分心"：gaze_status='away' 持续 > 60 秒

分心热力图：
  1. 按分钟聚合：每一分钟计算 (away_seconds / 60) = 分心率
  2. 颜色映射：0%(绿) → 50%(黄) → 100%(红)
  3. 在 HTML 报告中渲染为横向热力条

分心模式分类：
  ┌─ "高频短促型"：短分心事件 > 10 次/小时
  ├─ "间歇中长型"：中长分心事件 3-5 次/小时
  └─ "单次长断型"：出现 > 5 分钟的长分心
```

### 6.8 眨眼检测算法改进

```
问题背景：
  Phase 0 实测发现以下场景影响眨眼检测准确性：
  1. 固定阈值问题：不同用户 EAR 基线差异大，固定阈值无法适应
  2. 眯眼误判：疲劳时眯眼（缓慢下降+持续）被误判为眨眼
  3. 头部晃动：摇头、低头时 EAR 会变化，影响眨眼判断
  4. 人员干扰：他人经过时 face_detected 变化，影响数据连续性

改进方案（三阶段）：
┌─────────────────────────────────────────────────────────────────────┐
│  阶段一：基于个人基线的动态阈值（快速修复）                            │
├─────────────────────────────────────────────────────────────────────┤
│  目标：利用 calibration 阶段采集的个人基线 EAR                         │
│                                                                      │
│  算法：                                                               │
│    眨眼阈值 = 个人基线 EAR × 0.75                                    │
│    睁眼判定 = EAR > 基线 EAR × 0.90                                  │
│                                                                      │
│  例如：                                                              │
│    校准测得基线 EAR = 0.35                                          │
│    眨眼阈值 = 0.35 × 0.75 = 0.2625                                 │
│    睁眼阈值 = 0.35 × 0.90 = 0.315                                  │
│                                                                      │
│  优点：自动适应用户个体差异，疲劳后基线下降时同步调整                   │
│  状态：待实现                                                        │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  阶段二：眯眼 vs 眨眼区分（核心改进）                                 │
├─────────────────────────────────────────────────────────────────────┤
│  目标：区分快速眨眼和缓慢眯眼                                         │
│                                                                      │
│  特征对比：                                                          │
│  ┌─────────────┬──────────────┬──────────────┐                      │
│  │  特征       │  眨眼        │  眯眼        │                      │
│  ├─────────────┼──────────────┼──────────────┤                      │
│  │  持续时间   │  100-400ms   │  > 1 秒      │                      │
│  │  EAR 下降   │  快速        │  缓慢        │                      │
│  │  EAR 恢复   │  快速        │  缓慢        │                      │
│  │  发生频率   │  15-20次/分  │  疲劳时增加  │                      │
│  └─────────────┴──────────────┴──────────────┘                      │
│                                                                      │
│  算法：                                                               │
│    1. EAR 下降阶段：检测到 EAR 低于眨眼阈值                           │
│    2. 计时开始：记录 EAR 低于阈值的时间 T_low                         │
│    3. 恢复检测：当 EAR 回到睁眼阈值以上时                              │
│    4. 分类判断：                                                     │
│       IF T_low < 400ms → 判定为眨眼                                  │
│       ELSE → 判定为眯眼（不计入眨眼事件）                            │
│                                                                      │
│  优点：解决眯眼被误判为眨眼的问题，眨眼计数更准确                      │
│  状态：待实现                                                        │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  阶段三：多信号融合的眨眼置信度（增强鲁棒性）                         │
├─────────────────────────────────────────────────────────────────────┤
│  目标：在头部晃动、人员干扰等场景下提高检测准确性                       │
│                                                                      │
│  信号融合：                                                          │
│  ┌──────────────────┬──────────────────────────────────────────┐    │
│  │  信号            │  处理方式                                  │    │
│  ├──────────────────┼──────────────────────────────────────────┤    │
│  │  头部姿态        │  yaw/pitch 超出阈值时降低眨眼置信度        │    │
│  │  EAR 变化速率    │  异常快速的 EAR 变化（如 10帧内降为0）    │    │
│  │  face_detected   │  短暂丢失(<0.5s)忽略，长时间丢失暂停检测  │    │
│  │  连续性         │  眨眼事件应分散，过密（如<0.5s间隔）报警   │    │
│  └──────────────────┴──────────────────────────────────────────┘    │
│                                                                      │
│  置信度计算：                                                        │
│    confidence = base_conf × head_pose_weight × face_stability_weight │
│                                                                      │
│    其中：                                                             │
│      base_conf = 1.0（基础置信度）                                   │
│      head_pose_weight = 1.0（姿态正常）→ 0.5（姿态异常）             │
│      face_stability_weight = 1.0（面部稳定）→ 0.3（面部晃动）         │
│                                                                      │
│  判定规则：                                                          │
│    IF confidence > 0.6 → 计入眨眼事件                                │
│    IF confidence < 0.3 → 忽略，不影响疲劳计算                        │
│    ELSE → 标记为"可疑"，单独统计                                      │
│                                                                      │
│  优点：头部晃动、人员干扰时眨眼检测仍相对准确                          │
│  状态：待实现                                                        │
└─────────────────────────────────────────────────────────────────────┘

实施优先级：
  阶段一：⭐⭐⭐（高）— 快速实现，收益大，解决固定阈值核心问题
  阶段二：⭐⭐（中）— 算法复杂度适中，解决眯眼误判关键问题
  阶段三：⭐（低）— 工作量较大，收益相对有限
```

### 6.9 离线数据分析模块（v4.1 新增）

```
目标：在会话结束时对 SQLite 历史数据做无监督统计分析，
      把"实时感知 → 报告呈现"升级为"实时感知 → 模式挖掘 → 个性化洞察"。

设计原则：
  ✅ 离线运行：仅在报告生成时调用，不影响主循环 FPS
  ✅ 无监督为主：不需要人工标注（除关联分析的统计检验）
  ✅ 全部 CPU 可跑：sklearn/scipy/statsmodels/ruptures 都是 pip 包
  ✅ 单方法失败不影响其他：pipeline 用 try/except 隔离
  ✅ 数据不足时降级：每个方法独立的降级路径

总体架构：
  会话结束 → features.py 提取特征 → 5 个方法并行 → insights 表持久化 → 报告渲染
```

#### 6.9.1 方法 1：聚类工作模式（patterns.py）

```
算法：KMeans + silhouette 自动选 k
特征：每个 session 的 7 维特征向量（focus_score 均值/std、blink_rate/baseline、
       perclos、gaze_away_ratio、head_movement、duration_minutes、hour_of_day）

流程：
  1. StandardScaler 标准化
  2. For k in [2, 6]:
       计算 silhouette_score(X, KMeans(k).fit_predict(X))
  3. 选择 silhouette 最高的 k*
  4. 生成业务标签（"早高峰高效型"/"午后疲倦型" 等）

降级触发：
  n_sessions < 10 → 不做聚类
  best_silhouette < 0.25 → 视为聚类失败

输出：mode_descriptions[mode_id]：label + 占比 + 区分特征 z-score
```

#### 6.9.2 方法 2：变点检测（changepoint.py）

```
算法：ruptures.Pelt(model="rbf") — Pruned Exact Linear Time
输入：单 session focus_score 时间序列（约 7200 点/小时）

流程：
  1. 30 秒滑动均值平滑（去高频噪声）
  2. PELT 自动检测变点：penalty = c × log(n) × σ²，c=3.0
  3. 段长 < 60s 合并到邻段
  4. 按下降幅度排序，取 top 3 关键时刻
  5. 用 focus_breakdown JSON 推断主导因子

输出：key_moments[i]：{timestamp_str, focus_before, focus_after,
                       drop_magnitude, likely_cause}
```

#### 6.9.3 方法 3：时序分解（temporal.py）

```
算法：STL (Seasonal-Trend decomposition with LOESS)
输入：跨多 session 按小时聚合的 focus_score 序列

流程：
  1. resample('1H').mean() 小时聚合
  2. ffill(limit=3) 填补缺失（最多 3 小时）
  3. STL(period=24, robust=True).fit()
  4. seasonal 部分提取日内 24 小时 pattern
  5. 找 top 3 高效时段 + top 3 低效时段

降级触发：
  n_days < 7 → histogram 降级方案
  NaN > 30% → histogram 降级方案

输出：daily_pattern[24]、peak_hours、low_hours、trend_slope
```

#### 6.9.4 方法 4：异常检测（anomaly.py）

```
算法：IsolationForest（无监督异常检测）+ z-score 归因
输入：今日 session 特征 vs 历史 session 矩阵

流程：
  1. StandardScaler.fit(historical)
  2. IsolationForest(contamination=0.1).fit(historical)
  3. anomaly_score = iso.score_samples(today)
  4. z-score 归因：(today - hist_mean) / hist_std
  5. |z| > 1.5 的特征作为归因因子

降级触发：
  n_historical < 15 → 不做异常检测

输出：is_anomaly + anomaly_score + top_factors[3]
```

#### 6.9.5 方法 5：关联分析（attribution.py）

```
算法组合：
  - Pearson/Spearman 相关：连续变量
  - Welch's t-test：分组对比（光照/眼镜）
  - ANOVA + eta²：多组对比（24 小时段）
  - Cohen's d：效应量计算

关注因素：
  1. light_level ↔ focus_score
  2. glasses_mode ↔ focus_score
  3. hour_of_day ↔ focus_score
  4. blink_rate ↔ focus_score
  5. perclos ↔ focus_score

筛选门槛：
  - p < 0.05
  - |effect_size| > 0.3
  - 单组样本 ≥ 30

输出：findings[i]：{factor, effect_size, p_value, description, suggestion}
```

#### 6.9.6 性能预算与硬件需求

| 方法 | 训练耗时 | 推理耗时 | 内存 | 笔记本要求 |
|------|---------|---------|------|----------|
| 聚类（KMeans） | < 50ms | < 1ms | < 1MB | 任何笔记本 |
| 变点检测（PELT） | 无 | 1-2s/小时 | < 50MB | 任何笔记本 |
| 时序分解（STL） | 无 | < 200ms | < 10MB | 任何笔记本 |
| 异常检测（IF） | < 500ms | < 10ms | < 5MB | 任何笔记本 |
| 关联分析 | 无 | < 1s | < 100MB | 任何笔记本 |
| **总计** | - | **< 10s** | **< 200MB** | **完全可行** |

#### 6.9.7 报告渲染（reporter 集成）

报告新增 4 个章节（无数据时章节自动隐藏）：

| 章节 | 图表 | 文字 |
|------|------|------|
| 工作模式 | 饼图（各模式占比）+ 当前 session 高亮 | "今日属于'早高峰型'（出现 12 次）" |
| 异常分析 | 雷达图（今日 vs 基线均值） | 归因因子 top 3 中文翻译 |
| 长期趋势 | 24 小时折线图（标 peak/low） | "你的高效时段：09-11 / 16-17" |
| 个性化建议 | 横向条形图（各因子 effect size） | 数据驱动的具体建议 |


## 7. 数据库 Schema

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,         -- UUID
    user_id          TEXT DEFAULT 'default',
    start_time       TIMESTAMP,
    end_time         TIMESTAMP,
    pause_start      TIMESTAMP,
    pause_end        TIMESTAMP,
    glasses_mode     INTEGER DEFAULT -1,       -- -1=未检测, 0=不戴眼镜, 1=戴眼镜
    baseline_ear     REAL,
    baseline_ear_std REAL,
    baseline_blink_rate REAL,
    baseline_yaw     REAL,
    baseline_pitch   REAL,
    baseline_roll    REAL
);

CREATE TABLE IF NOT EXISTS frames (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    left_ear        REAL,
    right_ear       REAL,
    blink_flag      INTEGER DEFAULT 0,
    perclos         REAL,
    yaw             REAL,
    pitch           REAL,
    roll            REAL,
    gaze_status     TEXT,                   -- 'screen' / 'away'
    fatigue_label   TEXT,                  -- 'normal' / 'mild' / 'severe'
    focus_score     REAL,
    focus_breakdown TEXT,                  -- JSON
    light_level     TEXT,                  -- 'bright' / 'normal' / 'dark'
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX idx_frames_session ON frames(session_id, timestamp);

-- 【v4.1 新增】离线分析结果持久化
CREATE TABLE IF NOT EXISTS insights (
    insight_id      TEXT PRIMARY KEY,         -- UUID
    session_id      TEXT NOT NULL,
    analysis_type   TEXT NOT NULL,            -- 'pattern'/'anomaly'/'changepoint'/'temporal'/'attribution'
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    result_json     TEXT NOT NULL,            -- 序列化的分析结果
    confidence      REAL,                     -- 0-1 置信度
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX idx_insights_session ON insights(session_id, analysis_type);
CREATE INDEX idx_insights_created ON insights(created_at);
```

## 8. 配置系统

```
三层配置（优先级从高到低）：
  ┌─ GUI 滑块实时修改（会话级，不持久化）
  ├─ config.yaml 用户配置（持久化，跨会话生效）
  └─ config.py 代码默认值（兜底）

主要配置项：
  camera:
    index: 0
    width: 640
    height: 480

  calibration:
    duration_seconds: 7
    trim_percent: 10
    cqs_threshold: 0.60        # Phase 0 实测调整

  glasses:
    method: blendshapes         # blendshapes / landmark_dist / manual
    blendshapes_threshold: 0.5 # 待 Phase 1 开发端确定
    landmark_dist_threshold: 0.8

  light:
    brightness_dark: 50.0
    brightness_normal: 100.0
    log_light_condition: True

  focus:
    w_ear: 0.35
    w_gaze: 0.35
    w_head: 0.30
    ema_alpha: 0.15
    gaze_threshold_degrees: 15

  fatigue:
    blink_rate_mild_multiplier: 1.3
    blink_rate_severe_multiplier: 1.8
    perclos_mild_pct: 5.0
    perclos_severe_pct: 10.0
```

## 9. 性能设计

| 瓶颈 | 策略 |
|------|------|
| MediaPipe 推理 | 每帧推理，不跳帧；目标 25+ FPS；GPU delegate 可选加速 |
| SQLite 写入 | 每 0.5 秒批量写入一次；使用 WAL 模式 |
| Matplotlib 出图 | 仅在会话结束时生成图表，不在主循环中调用 |
| 光照检测 | 每帧计算，零额外成本；结果写入 SQLite |
| 眼镜检测 | blendshapes 阈值规则，O(1) 计算，无模型推理 |

---

# 第四部分：项目管理

## 10. 时间节点与里程碑

### 10.1 总体时间线

```
Spike ─── Day 1-3 ────── Day 4-12 ─── Day 13 ─── Day 14-17 ─── Day 18-22 ────── Day 23-29
[预开发 2d]  [Phase 1 MVP 8d]  [Insights Spike 1d]  [v4.2 calibration 重设计 4d]  [Phase 2 报告+创新+离线分析 5d]  [Phase 3 交付打磨 7d]
   ▲              ▲                  ▲                  ▲                       ▲                                ▲
   │              │                  │                  │                       │                                │
技术去风险    M1: 核心引擎       Insights 原型      🔴 calibration 重设计      M2/M3: 完整会话                M5-M8: 项目交付
三人并行实测  可运行+实时显示    5 方法 PASS        14 子任务 + 测试门禁        HTML + 4 章节分析            打包+文档+PPT
                                                   + 用户 7 BUG 验收
```

### 10.2 里程碑详情

#### Spike Phase：预开发验证（Day 1-2）✅ 已完成

| 验证项 | 负责人 | 内容 | 验收标准 |
|--------|--------|------|---------|
| **S1: 硬件帧率基准测试** | D1 | MediaPipe Face Mesh，while 循环打印实时 FPS | 5 分钟平均 FPS ≥ 25 ✅ |
| **S2: 基线校准算法原型** | D1 | 采集 7s → 三级过滤 → 截尾均值 → CQS | 基线 EAR CV < 10%，CQS ≥ 0.60 ✅（6/6 PASS）|
| **S3: 头部姿态验证** | D1 | MediaPipe facial_transformation_matrixes | yaw/pitch 抖动 < ±3° ✅ |
| **S4: 异常值剔除策略验证** | D2 | 检查三级过滤逻辑 | CQS PASS 率 ≥ 80% ✅ |
| **S5: EAR 方差基线采集** | D2 | 眼镜/不戴眼镜 EAR 方差分布 | 确定检测阈值 ✅（确认失效）|
| **S6: 依赖完整性验证** | T1 | 新 venv 安装 + 运行 S1 | 所有依赖无报错 ✅ |
| **S7: 光照联合验证** | D1+D2+T1 | 四种组合下各跑 2min | FPS ≥ 20 ✅ |
| **S8: 眼镜校准扩展测试** | D1 | 戴眼镜 3 次额外校准 | CQS ≥ 0.60 ✅ |

#### Phase 1：Must Have（Day 4-12）

| 里程碑 | Day 范围 | 内容 |
|---------|----------|------|
| **M0: 环境就绪 + Git 仓库** | Day 4 | 创建仓库、分支策略、.gitignore |
| **M1a: 核心检测模块** | Day 5-7 | face_mesh + eye_aspect + head_pose + gaze + light |
| **M1b: 分析模块** | Day 6-8 | baseline（CQS）+ glasses（blendshapes）+ focus + fatigue |
| **M2a: 联调** | Day 8-9 | storage/db.py + main.py 单线程主循环 |
| **M2b: 首次集成测试** | Day 10-12 | 真实场景测试，1-2h，输出测试报告 |

#### Phase 1.6：Insights Spike 验证（Day 13）【v4.1 新增】

> 路径 A：实施前 1 天 Spike 验证 5 个分析方法在实际数据上的表现，调出推荐参数，再进入正式实施。

| 验证项 | 负责人 | 内容 | 验收标准 |
|--------|--------|------|---------|
| **S11: 聚类原型验证** | D1 | spike/s11_clustering.py — 30 mock sessions 跑 KMeans + silhouette 自动选 k | silhouette > 0.3 + 模式描述可读 |
| **S12: 变点检测原型** | D1 | spike/s12_changepoint.py — 真实 session 跑 PELT，penalty 调到每小时 3-5 变点 | "中间断崖"场景误差 < 30s |
| **S13: 异常检测原型** | D2 | spike/s13_anomaly.py — 20+ 历史 + 1 人造异常 session | 异常成功识别 + 归因 top 3 命中人造特征 |
| **S14: 时序分解原型** | D1 | spike/s14_temporal.py — 14 天合成数据（已知 pattern），跑 STL | 恢复 peak hour 误差 ≤ ±1h |
| **S15: 关联分析原型** | D2 | spike/s15_attribution.py — 现有 frames 数据跑 t-test + ANOVA | 至少 1 个 p<0.05 且 effect>0.3 finding |
| **S-SUM: 汇总** | D1 | docs/PHASE1_6_SPIKE_SUMMARY.md | 5 方法结论 + 推荐参数表 + 限制说明 |

#### Phase 2：Should Have（Day 14-22）

| 里程碑 | Day 范围 | 内容 |
|---------|----------|------|
| **M-CAL【v4.2】: calibration 模块重设计** | Day 14-17 | 🔴 严重风险任务 — T-CAL-01 ~ T-CAL-14 14 个子任务 + 测试门禁 + 用户 7 BUG 实测验收（详见 spec `docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`）|
| **M3a: 报告生成** | Day 18-19 | HTML reporter + Matplotlib 图表 |
| **M3b: 分心模式识别** | Day 18-19 | distraction.py → 热力图数据 → 报告嵌入 |
| **M3c【v4.1】: Insights 实施** | Day 19-21 | T220-T227 insights 子包完整实现 + 单元测试 |
| **M3d【v4.1】: 报告 4 章节集成** | Day 21 | T228 工作模式/异常/趋势/建议章节渲染 |
| **A4: 专注度算法真人测试** | Day 22 | 2-3 人测试数据收集，权重调优 |
| **M4: 集成测试 + Phase 2 验收** | Day 22 | T229+T230 性能 < 10s + 全覆盖 ≥ 75% |

#### Phase 3：交付与打磨（Day 23-29）

| 里程碑 | Day 范围 | 内容 |
|---------|----------|------|
| **M5: 边界测试 + 修复** | Day 23-24 | 眼镜降级、人脸丢失、低光照等边界问题 |
| **M6: 文档撰写** | Day 24-25 | ARCHITECTURE + API + README + USER_GUIDE |
| **M7: .exe 打包** | Day 25-26 | PyInstaller 打包 + 无 Python 环境测试 |
| **M8: 答辩 PPT** | Day 26-29 | 技术架构 + 核心算法 + 创新点 + 演示 |

## 11. 团队配置

| 角色 | 代号 | 核心职责 | 投入程度 |
|------|------|---------|---------|
| **主开发者** | D1 | 核心算法实现（detector/analyzer）、架构决策、GPU 开发环境搭建 | 全程主力投入 |
| **辅助开发者** | D2 | 配套模块实现（storage/gui/config）、单元测试编写、文档 | 全程辅助 + 支持 |
| **测试者** | T1 | 测试用例编写、每 Phase 真实场景验收、测试报告输出 | 每 Phase 验收 |

## 12. 风险与应对

| # | 风险 | 概率 | 影响 | 应对策略 |
|---|------|------|------|---------|
| R1 | **摄像头不可用或权限问题** | 中 | 高 | 启动时检测 `cv2.VideoCapture(0).isOpened()`，失败后尝试索引 1 |
| R2 | **MediaPipe 模型首次下载失败** | 低 | 中 | 提供离线模型文件备用方案 |
| R3 | **低光照/背光下人脸检测不稳定** | 高 | 中 | hold-last-value 策略；`detector/light.py` 记录光照等级用于事后分析；连续丢失 >10s 自动暂停 |
| R4 | **不同用户生理差异大，基线不准** | 中 | 高 | CQS 自动检测基线污染；支持手动重录 |
| R5 | **专注度评分"不准"** | 高 | 高 | GUI 实时显示扣分明细；真人测试后微调权重 |
| R6 | **戴眼镜用户关键点偏移** | 高 | 中 | ⚠️ DEPRECATED EAR 方差法；Phase 1 实现 blendshapes + 眼角距离双保险 |
| R7 | **长时间运行内存泄漏** | 低 | 中 | deque(maxlen=1000) 限制缓冲区 |
| R8 | **GUI 显示与实时性冲突** | 中 | 中 | 单线程模型，MediaPipe + imshow 在同一线程无竞态 |
| R9 | **Spike Phase 帧率不达标** | 中 | 高 | Gate Check 硬性门禁；不达标时跳帧推理 |
| R10 | **头部姿态角度抖动超过 ±3°** | 中 | 高 | ✅ 已解决：MediaPipe facial_transformation_matrixes 实测 0.59° |
| R11 | **基线校准 PASS 率过低** | 中 | 中 | 放宽过滤阈值；CQS 连续 3 次 FAIL 允许跳过校准 |
| R12 | **长时间会话 SQLite 查询性能下降** | 中 | 中 | WAL 模式；报告生成时按分钟聚合 |
| R13 | **跨平台字体渲染不一致** | 中 | 中 | 使用 Pillow 渲染中文到 numpy 数组 |
| R14 | **异常退出时缓冲区数据丢失** | 低 | 中 | `atexit.register(flush_buffer)` + `signal.signal(SIGINT, handler)` |
| R15 | **眼镜检测误判** | 中 | 中 | blendshapes + 眼角距离双保险 + 手动模式保底 |
| R16 | **三人分工协作中的代码冲突** | 中 | 中 | PR 审查强制要求另一开发者 approve |
| R17 | **文档撰写时间不足** | 中 | 高 | Phase 1 就开始并行写 docstring |
| R18 | **单元测试覆盖率不达标** | 中 | 中 | 每完成一个模块后立即写对应单测 |
| R19 | **分心模式识别效果不佳** | 高 | 中 | 分心阈值可通过 config.yaml 调节 |
| R20 | **答辩 PPT 与代码交付时间冲突** | 中 | 高 | PPT 内容与文档复用；T1 承担 PPT 初稿 |
| R21 | **开发端 GPU vs 生产端 CPU 差异** | 低 | 高 | 双轨策略：GPU 验证 → 提取规则 → CPU 落地 |
| R22 | **光照条件影响检测稳定性** | 中 | 中 | `detector/light.py` 每帧检测并记录，辅助事后分析 |
| R23 | **【v4.1】聚类数据不足导致结果不稳定** | 高 | 中 | 强制 silhouette ≥ 0.25 + n_sessions ≥ 10 双门槛；不足时降级展示 |
| R24 | **【v4.1】STL 时序分解需要长期数据** | 高 | 中 | n_days < 7 时自动降级到 histogram 方案，不报错 |
| R25 | **【v4.1】Insights pipeline 总耗时超标** | 中 | 中 | 单方法 try/except 隔离 + 性能预算 < 10s + 异步生成报告 loading 提示 |
| R26 | **【v4.1】sklearn/scipy 增加打包体积** | 低 | 低 | PyInstaller 打包后约 +80MB，仍可接受；提供 lite 版本预案 |
| R27 | **【v4.2】T148 校准模块重设计（calibration/）属高风险重构** | 高 | 极高 | 🔴 严重 — 保守开发策略：14 个子任务每个测试门禁 + D1 强制 review + main.py 集成放最后一步 + 用户 7 BUG 实测全过才签收（见 spec §6）|
| R28 | **【v4.2】Windows IME 拦截键盘** | 高 | 高 | 屏幕数字键盘鼠标点击作主输入路径（input_handler 设计），彻底消除 IME 影响；Win32 IME 禁用仅作可选兜底 |
| R29 | **【v4.2】pyttsx3 在某 Windows 版本 SAPI 失败** | 中 | 中 | calibration 模块 TTS 初始化失败时降级为 beep-only + UI 警告 + 阶段时长 +50% 补偿 |
| R30 | **【v4.2】摄像头切换（主程序 ↔ 模块）失败** | 低 | 高 | 模块入口 cv2.VideoCapture 失败时立即 return None；主程序拿到 None 后用默认基线继续主监测，不阻断 |

## 13. 验收标准

### 13.1 功能验收清单

| # | 验收项 | 通过标准 |
|---|--------|---------|
| AC1 | 程序启动后打开摄像头 | 3 秒内出现摄像头画面 |
| AC2 | 人脸关键点实时绘制 | 468 个点的网格覆盖人脸，无明显偏移 |
| AC3 | EAR 曲线实时显示 | 眨眼时 EAR 数值明显下降（如从 0.3 → 0.15） |
| AC4 | 基线校准流程 + CQS | 校准阶段持续 7 秒，有进度提示 + 质量判定 |
| AC5 | 专注度评分实时更新 + 扣分明细 | 评分数字随用户行为变化，底部栏显示三项扣分来源 |
| AC6 | 疲劳分级变化 + PERCLOS | 长时间不眨眼后疲劳等级从"正常"→"轻度"→"重度" |
| AC7 | 数据写入 SQLite | `SELECT COUNT(*) FROM frames` 返回 > 0 |
| AC8 | 5+ 分钟会话不崩溃 | 程序无异常退出，FPS 保持在 25+ |
| AC9 | 会话结束生成 HTML 报告 | 浏览器中显示图表和统计信息 |
| AC10 | 报告包含个性化建议 | 建议不空洞（非"多休息"类通用建议） |
| AC11 | `requirements.txt` 可复现环境 | `pip install -r requirements.txt` 无报错 |
| AC12 | README 可指导新用户运行 | 5 分钟内完成首次启动 |
| AC13 | 人脸丢失自动恢复 | 遮脸 <2s: 平滑过渡；2-10s: 显示提示；>10s: 自动暂停 |
| AC14 | 异常退出数据不丢失 | SQLite 中最后一条记录距退出时间 < 1 秒 |
| AC15 | 跨平台 GUI 中文正常 | "校准中…" "专注度" 等中文无乱码 |
| AC16 | 报告图表降采样 | 5 分钟会话的报告图中数据点 ≤ 300 个 |
| AC17 | 分心热力图显示 | HTML 报告中含时间轴分心热力条 |
| AC18 | 单元测试覆盖率 ≥ 60% | `pytest --cov` 总覆盖率 ≥ 60% |
| AC19 | 完整文档体系交付 | 5 份文档全部存在 |
| AC20 | PyInstaller .exe 打包运行 | .exe 双击启动全流程正常 |
| AC21 | 答辩 PPT 交付 | 15-20 页，涵盖背景/架构/算法/创新/演示 |
| AC22 | 数据隐私合规 | 代码中 0 个 HTTP 请求；不存储任何图像帧 |
| AC23 | 眼镜检测显示 | GUI 实时显示眼镜模式（是/否/未知） |
| AC24 | 光照等级显示 | GUI 实时显示光照等级（亮/正常/暗） |
| AC25 | 生产端无 GPU 依赖 | 在无独显机器上测试，FPS ≥ 25 |
| AC26 | 【v4.1】Insights pipeline 性能 | 30 sessions 历史 + 1h 当前 session 全 pipeline 耗时 < 10s |
| AC27 | 【v4.1】聚类降级 | n_sessions < 10 时报告显示"数据不足"，不报错不空白 |
| AC28 | 【v4.1】异常检测归因 | 检测到异常时报告显示 top 3 中文翻译因子 |
| AC29 | 【v4.1】时序高效时段 | 14 天数据下报告显示具体高效小时段（如 "09-11"） |
| AC30 | 【v4.1】关联分析建议 | 报告"个性化建议"章节至少包含 1 条 p<0.05 + effect>0.3 的发现 |
| AC31 | 【v4.2】calibration 模块独立运行 | `python -m calibration` 跑通完整 5 阶段并返回 CalibrationResult |
| AC32 | 【v4.2】BUG 1 修复 — 眨眼检测 | 眨眼计数轮检测到的眨眼数 > 0 且与用户实际眨眼数偏差 < 30% |
| AC33 | 【v4.2】BUG 2 修复 — UI 视频分离 | 校准 UI 完全不遮挡视频区（视频区高 480 + UI 区高 240 严格分离）|
| AC34 | 【v4.2】BUG 3 修复 — 闭眼 TTS | 闭眼阶段结束前用户听到 TTS "现在可以睁眼了"（mock TTS 测试 + 真机听音）|
| AC35 | 【v4.2】BUG 4 修复 — 头部姿态 4 指令 | 头部姿态阶段 4 个子方向各自有独立 TTS（"现在抬头/低头/向左/向右"）|
| AC36 | 【v4.2】BUG 5/6 修复 — 反馈与控制 | 每阶段进行中可见实时数据计数 + 阶段结束有摘要 + 每阶段需点"开始"才推进 |
| AC37 | 【v4.2】BUG 7 修复 — 结束反馈 | 校准完成后总结页阻塞等待用户点"继续 → 主监测"，不再"停在录像界面" |
| AC38 | 【v4.2】IME 兼容 | 微软拼音输入法激活下，用户能用鼠标点屏幕数字键盘完整完成校准（无需切英文输入法）|

### 13.2 非功能指标

| 指标 | 目标值 | 测量方式 |
|------|--------|---------|
| FPS（处理速度） | ≥ 25 FPS（CPU 目标机器）| 程序中打印每 100 帧平均 FPS |
| CPU 占用率 | ≤ 50%（4 核笔记本）| 任务管理器观察 |
| 内存占用 | ≤ 500 MB | 任务管理器观察 |
| 首次启动到显示画面 | ≤ 5 秒 | 手动计时 |
| 报告生成时间 | ≤ 10 秒（5 分钟会话）| 代码中计时打印 |
| SQLite 数据准确性 | 帧数据丢失率 < 1% | 对比实际帧数与数据库记录数 |

---

# 第五部分：附录

## 14. 技术审查 Q&A

**A1 — 专注度评分权重与函数形式**（🔴高风险）

| 子问题 | 回答 |
|--------|------|
| Q1: 权重是否基于文献？是否对人种差异敏感？ | 初始权重(W1=0.35, W2=0.35, W3=0.30)基于设计假设，非文献。但自适应基线校准解决人种 EAR 差异问题（评分基于**偏离个人基线的幅度**而非绝对值） |
| Q2: "过去10秒窗口"是滑动窗还是离散窗？ | **滑动窗 + EMA 平滑**，最终评分经 EMA(α=0.15, τ≈6.7秒)平滑 |
| Q3: 用户能否理解"为什么是68分"？ | GUI 底部栏实时显示三项扣分之和；HTML 报告中含权重说明 |

**A2 — 基线校准的统计鲁棒性**（🔴高风险）

| 子问题 | 回答 |
|--------|------|
| Q1: 用均值、中位数还是截尾均值？ | **三级过滤 + 10% 截尾均值** |
| Q2: 校准期间打哈欠/看手机如何检测？ | CQS 自动判定：帧丢弃率>40%→FAIL；EAR标准差>0.05→WARN |
| Q3: 基线是否应动态微调？ | **缓慢漂移补偿**：`baseline_ear = 0.95×old + 0.05×recent_avg_ear`（时间常数≈20分钟） |

**A3 — 头部姿态估计**（✅ 已解决 — Phase 0 spike 验证通过）

| 子问题 | 回答 |
|--------|------|
| Q1: 通用 3D 模型还是自定义锚点？ | ✅ **MediaPipe facial_transformation_matrixes**。Phase 0 spike 验证：yaw=-80° 错误（solvePnP），改用 MediaPipe 内置矩阵后正视 yaw_std=0.59° |
| Q2: 选取哪些点？ | 直接使用 `result.facial_transformation_matrixes[0]`（4×4 齐次矩阵），无需手动选择关键点 |
| Q3: 尺度归一化策略？ | MediaPipe 内部处理尺度差异，无需额外归一化 |

**A4 — 视线偏离判定的精度上限**（🟡中风险）

| 子问题 | 回答 |
|--------|------|
| Q1: 头部不动但眼球转动的漏检率？ | 本项目明确接受此限制。纯头部姿态无法检测眼球微动，yaw>15° 或 pitch>15° 判定为"视线偏离" |
| Q2: 阈值是否自适应屏幕尺寸？ | 初始固定阈值 yaw/pitch>15°，后续可扩展 |
| Q3: 看屏幕边缘是否误判？ | 存在误判风险，建议用户将主工作区放在屏幕中央 |

**A5 — 疲劳分级阈值**（🟡中风险）

| 子问题 | 回答 |
|--------|------|
| Q1: 偏离基线多少触发"轻度"/"重度"？ | 正常: 眨眼率<基线×1.3 AND PERCLOS<5%。轻度: ≥1.3 OR PERCLOS≥5%。重度: ≥1.8 OR PERCLOS≥10% |
| Q2: 是否结合 PERCLOS？ | **是**。PERCLOS 是疲劳监测的金标准指标，与眨眼率互补 |
| Q3: 固定阈值对眨眼频率低者是否误报？ | 阈值是基于**偏离个人基线的倍数**，不是绝对值 |

**B1 — 缺失数据处理策略**（🔴高风险）

| 子问题 | 回答 |
|--------|------|
| Q1: 丢帧时 SQLite 插入 NULL 还是跳过？ | **插入 NULL 但保留 timestamp + session_id**，保证时间轴完整性 |
| Q2: 连续丢帧>N秒是否暂停？ | 连续丢失>10秒 → 自动暂停会话 |
| Q3: 时序插值策略？ | hold-last-value 策略。专注度评分线性衰减至 0（约 5 秒衰减） |

**B2 — 长时间运行数据库性能**（🟡中风险）

| 子问题 | 回答 |
|--------|------|
| Q1: 8 小时 ~57,600 条记录的查询性能？ | WAL 模式下 SQLite 对百万级记录的聚合查询在秒级完成 |
| Q2: 历史数据归档策略？ | MVP 不做自动归档。若 DB 文件超过 100MB，提示用户手动备份 |

**C1 — 硬件帧率实际达标验证**（🔴高风险）

| 子问题 | 回答 |
|--------|------|
| Q1: 目标设备实际帧率？ | **Spike Phase S1 必须实测**，在开发者笔记本上跑最小脚本 5 分钟 |
| Q2: 帧率 <20 时的优化策略？ | ① 跳帧推理（每 2 帧做一次 MediaPipe）→ ② 降低 MediaPipe 模型复杂度 → ③ 降低目标至 15 FPS |

**C2 — 并发与线程安全模型**（🟡中风险）

| 子问题 | 回答 |
|--------|------|
| Q1: MediaPipe 线程安全？ | **官方不推荐多线程**，因此修正为**全线单线程模型**，纯数值运算微秒级，不阻塞主循环 |
| Q2: SQLite 写入需要 Queue/锁吗？ | 单线程模型下无需锁，deque 缓冲区暂存记录，每 15 条批量写入 |

**D1 — 眼镜/遮挡场景的自动检测**（🟡中风险 — Phase 1 开发验证）

| 子问题 | 回答 |
|--------|------|
| Q1: 如何量化"眼镜干扰"？ | Phase 0 验证失败 EAR 方差法。Phase 1 探索 blendshapes + 眼角关键点距离双保险规则 |
| Q2: 降级后权重如何重分配？ | 若检测为眼镜用户：W1(眨眼权重): 0.35→0.10, W2/W3→0.45 |

**D2 — 光照条件感知**（🟡中风险 — Phase 1 实现）

| 子问题 | 回答 |
|--------|------|
| Q1: 如何判断"亮/暗"？ | 帧亮度均值（mean_brightness > 100 → bright，< 50 → dark）+ 摄像头曝光参数辅助 |
| Q2: 光照影响哪些指标？ | 低光照可能导致 FPS 下降、人脸丢失增加，不直接影响 EAR 计算精度 |

## 15. 详细任务清单

### 15.1 Phase 0：Spike 预开发验证（Day 1-3）✅ 已完成

| 任务ID | 负责人 | 任务描述 | 验收标准 | 估时 | 状态 |
|--------|--------|---------|---------|------|------|
| T000 | D1 | 创建 GitHub 仓库，develop + main 分支，.gitignore | 仓库可 clone | - | ✅ |
| T001 | 全员 | 各自创建 Python 3.9+ venv，安装全部依赖 | pip list 确认全部安装 | - | ✅ |
| T002 | D1 | 创建项目骨架目录结构 | 目录树与架构图一致 | - | ✅ |
| T003 | D1 | 创建 requirements.txt | T1 在新 venv 中安装无报错 | - | ✅ |
| S1 | D1 | MediaPipe Face Mesh 帧率基准测试 | 5min 平均 FPS ≥ 25 | 2h | ✅ |
| S2 | D1 | 基线校准算法原型 | 基线 EAR CV < 10%, CQS ≥ 0.60 | 3h | ✅ |
| S3 | D1 | MediaPipe facial_transformation_matrixes 头部姿态验证 | yaw/pitch 抖动 < ±3° | 2h | ✅ |
| S4 | D2 | 审查 S2 的三级过滤参数 | CQS PASS 率 ≥ 80% | 1h | ✅ |
| S5 | D2 | EAR 方差基线采集（眼镜/不戴眼镜） | 确定检测阈值 | 2h | ✅ |
| S6 | T1 | 依赖完整性验证（新 venv） | 所有依赖无报错 | 1h | ✅ |
| S7 | D1+D2+T1 | 光照联合验证（4种组合） | FPS ≥ 20 | 2h | ✅ |
| S8 | D1 | 戴眼镜扩展测试（3次）| CQS ≥ 0.60 | 1h | ✅ |

### 15.2 Phase 1：Must Have — MVP（Day 4-12）

| 任务ID | 负责人 | 任务描述 | 估时 |
|--------|--------|---------|------|
| T100 | D2 | config.py + config.yaml 配置系统 | 1.5h |
| T102 | D1 | storage/models.py 数据模型 | 0.5h |
| T103-T107 | D1 | detector/face_mesh.py + eye_aspect.py | 5h |
| T108-T111 | D2 | detector/head_pose.py + gaze.py | 5h |
| T112 | D1 | detector/light.py 光照检测 | 1h |
| T113-T118 | D1 | analyzer/baseline.py + focus.py | 8h |
| T119 | D1 | analyzer/glasses.py（blendshapes 阈值规则）| 2h |
| T120-T121 | D2 | analyzer/fatigue.py | 2h |
| T122-T127 | D1 | storage/db.py | 4h |
| T128-T131 | D2 | gui/overlay.py | 4h |
| T132-T134 | D1 | main.py 主循环 + 联调 | 5h |
| T135 | D1+D2 | 联调修复 | 4h |
| T136-T142 | D2 | 单元测试 | 10h |
| T143-T144 | T1 | 集成测试 + Phase 1 验收 | 3.5h |
| **小计** | | | **51.5h** |

### 15.3 Phase 1.6：Insights Spike 验证（Day 13）【v4.1 新增】

| 任务ID | 负责人 | 任务描述 | 验收标准 | 估时 |
|--------|--------|---------|---------|------|
| S11 | D1 | spike/s11_clustering.py — KMeans + silhouette 自动选 k | silhouette > 0.3，模式描述可读 | 1.5h |
| S12 | D1 | spike/s12_changepoint.py — ruptures PELT，调 penalty | 误差 < 30s | 1h |
| S13 | D2 | spike/s13_anomaly.py — IsolationForest + 人造异常 | 异常成功识别 + 归因 top3 命中 | 1h |
| S14 | D1 | spike/s14_temporal.py — STL，合成 14 天数据 | peak hour 误差 ≤ ±1h | 1h |
| S15 | D2 | spike/s15_attribution.py — t-test + ANOVA | 至少 1 个 p<0.05 + effect>0.3 finding | 1h |
| S-SUM | D1 | docs/PHASE1_6_SPIKE_SUMMARY.md 汇总报告 | 5 方法结论 + 推荐参数 + 限制 | 1h |
| **小计** | | | | **6.5h** |

### 15.4 Phase 2：Should Have（Day 14-22）

> **【v4.2】Phase 2 启动后第一件事**：calibration 模块重设计（T-CAL-01 ~ T-CAL-14），原 T148 实测全部失效，需独立重建。其余 T200-T231 任务（insights spike + 报告 + 实施）排在 calibration 完成后。

#### 15.4.0 calibration 模块重设计（v4.2 新增，Day 14-17，约 4 天）

> ⚠️ 严重风险模块（R27）— 保守开发策略：每子任务必带测试门禁 + D1 强制 review + main.py 集成放最后一步。详见 spec `docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`。

| 任务ID | 负责人 | 任务描述 | 估时 | 覆盖率门禁 |
|--------|--------|---------|------|----------|
| T-CAL-01 | D1 | calibration/result.py — CalibrationResult dataclass（冻结字段） | 0.5h | ≥ 95% |
| T-CAL-02 | D2 | calibration/config.py — CalibrationConfig 配置 | 0.5h | ≥ 90% |
| T-CAL-03 | D1 | calibration/phases/auto_baseline.py — 阶段 0 | 1.5h | ≥ 90% + spike |
| T-CAL-04 | D1 | calibration/phases/closed_eyes.py — 阶段 1（含睁眼回升验证） | 1h | ≥ 90% + 真机 TTS |
| T-CAL-05 | D1 | calibration/phases/squint.py — 阶段 2 | 1h | ≥ 90% |
| T-CAL-06 | D1 | calibration/phases/head_pose.py — 阶段 3 (4 子阶段) | 1.5h | ≥ 85% + 4 TTS 真机 |
| T-CAL-07 | D1 | calibration/phases/blink_count.py — 阶段 4（2 轮 + 输入）| 1.5h | ≥ 85% + 真机眨眼检出 |
| T-CAL-08 | D2 | calibration/ui/layout.py — vconcat 拼合 | 0.5h | ≥ 90% |
| T-CAL-09 | D2 | calibration/ui/panel.py — UI 区渲染 + 屏幕数字键盘 | 3h | ≥ 75% + 每状态截图 review |
| T-CAL-10 | D2 | calibration/input_handler.py — 鼠标 + 键盘 + IME 兼容 | 2h | ≥ 95% + IME 实战 |
| T-CAL-11 | D2 | calibration/audio/beep.py + audio/tts.py | 1.5h | ≥ 80-85% + 真机听音 |
| T-CAL-12 | D1 | calibration/flow.py — 状态机编排 | 3h | ≥ 80% + spike 全流程 |
| T-CAL-13 | D1 | calibration/__main__.py — `python -m calibration` 独立运行 | 0.5h | 5 个 spike 全跑通 |
| T-CAL-14 | D1+T1 | main.py 集成（**最后一步**）+ 用户 7 BUG 实测验收 | 2h | 原 284 测试 0 破 + 8 个用户验收点全过 |
| **小计** | | | **20h** | 总体 ≥ 85% |

#### 15.4.1 原 Phase 2 任务（calibration 完成后启动，Day 18-22）

| 任务ID | 负责人 | 任务描述 | 估时 |
|--------|--------|---------|------|
| T200-T205 | D1 | reporter/ 报告模块 | 9h |
| T206-T207 | D2 | reporter/insights.py 个性化建议（由 attribution 驱动） | 3h |
| T208-T211 | D1 | analyzer/distraction.py 分心识别 | 4h |
| T212-T215 | D1 | 跨会话分析 + 真人测试 | 6h |
| T216-T218 | D2 | 测试补充 + 覆盖率提升 | 5h |
| **【v4.1】T220** | D1 | analyzer/insights/features.py — SessionFeatures + 矩阵化 | 1.5h |
| **【v4.1】T221** | D2 | storage/db.py + models.py — insights 表 + PRAGMA 迁移 | 0.5h |
| **【v4.1】T222** | D1 | analyzer/insights/changepoint.py — PELT 变点检测 | 2h |
| **【v4.1】T223** | D2 | analyzer/insights/anomaly.py — IsolationForest + 归因 | 1.5h |
| **【v4.1】T224** | D1 | analyzer/insights/patterns.py — KMeans + silhouette | 2h |
| **【v4.1】T225** | D1 | analyzer/insights/temporal.py — STL + histogram 降级 | 2h |
| **【v4.1】T226** | D2 | analyzer/insights/attribution.py — t-test + ANOVA + d | 2h |
| **【v4.1】T227** | D1 | analyzer/insights/pipeline.py — 编排 + try/except 隔离 | 1h |
| **【v4.1】T228** | D2 | reporter/report_html.py — 4 章节模板（饼图/雷达/折线/条形） | 3h |
| **【v4.1】T229** | D2 | tests/test_insights_*.py — 单元测试 ≥ 75% 覆盖 | 3h |
| **【v4.1】T230** | T1 | tests/test_insights_integration.py — 性能与验收 | 2h |
| **【v4.1】T231** | D1 | PROJECT_PLAN v4.1 + PHASE2_PLAN 文档同步 | 1h |
| T219 | T1 | Phase 2 整体验收 | 3h |
| **小计** | | | **53.5h** |

### 15.5 Phase 3：交付打磨（Day 23-29）

| 任务ID | 负责人 | 任务描述 | 估时 |
|--------|--------|---------|------|
| T300-T302 | D1 | 边界修复 + 眼镜模式优化 | 4h |
| T303 | D1 | 头部姿态平滑滤波 | 1h |
| T304-T305 | D2 | 低光照 GUI + 异常退出保障 | 1h |
| T306 | T1 | 全量回归测试 | 4h |
| T310-T311 | D1 | 文档 ARCHITECTURE + API | 5h |
| T312-T314 | D2 | README + USER_GUIDE + DEV_GUIDE | 4.5h |
| T315 | T1 | 文档审核 | 2h |
| T320-T321 | D1 | PyInstaller 打包 + 验收 | 5h |
| T322 | D2 | 演示视频/截图素材 | 1.5h |
| T323-T324 | D1+D2 | PPT 制作 | 6h |
| T325 | T1 | PPT 审核 + 演练 | 2h |
| T326 | 全员 | 最终验收 | 1h |

### 15.6 任务汇总

| Phase | 任务数 | D1 估时 | D2 估时 | T1 估时 | 总估时 |
|-------|--------|---------|---------|---------|--------|
| Phase 0 Spike | 11+2 | 11h | 6h | 3h | 20h |
| Phase 1 MVP | 45 | 32h | 23h | 4h | 59h |
| Phase 1.6 Insights Spike【v4.1】 | 6 | 4.5h | 2h | 0h | 6.5h |
| **Phase 2 calibration 重设计【v4.2】** | 14 | 13h | 6h | 1h | 20h |
| Phase 2 完整会话 + Insights【v4.1】 | 32 | 31h | 17.5h | 5h | 53.5h |
| Phase 3 交付 | 17 | 10h | 8h | 8h | 26h |
| **合计** | **127** | **101.5h** | **62.5h** | **21h** | **185h** |

## 16. 版本迭代记录

### v4.2 — 用户辅助校准模块独立重设计（2026-06-02）

> **变更原因**：2026-06-02 用户实测 T148 用户辅助校准模块，发现 7 个核心问题，"功能完全实现不了，需要列为严重问题"。经 brainstorm 会话深度问询，决定 **完整重设计 + 模块隔离开发**。CLAUDE.md 触发：实测数据与方案预想不符 + 关键假设被证伪 + 技术方案重大调整。
>
> **核心策略**：独立 `calibration/` 子包 + 模块自有摄像头 + 单接口连接 + 保守开发策略（14 子任务 + 测试门禁 + main.py 集成放最后一步）。
>
> **详细 spec**：`docs/superpowers/specs/2026-06-02-user-calibration-redesign.md`

#### 实测发现的 7 个核心问题（已确认）

| # | 等级 | 问题 | 根因 / 用户反馈 |
|---|------|------|----------------|
| 1 | 🔴 致命 | 眨眼检测一直 0 | BLINK_COUNTING 阶段在 tick() 内采样 EAR，节流 ≥ 1s；眨眼仅 100-400ms → 漏检 95%+ |
| 2 | 🔴 严重 | UI 与视频重叠 | 单 cv2 窗口，半透明 UI 条覆盖在视频底部 80-100px |
| 3 | 🔴 根本性 UX | 闭眼用户失明 | 闭眼时无音频提示，用户看不见 UI 倒计时 |
| 4 | 🟡 严重 UX | 头部姿态无指令 | HEAD_UP/DOWN/LEFT/RIGHT 切换无独立 UI/TTS 提示 |
| 5 | 🟡 严重 UX | 全程无有效反馈 | 没有"采集了多少 / 做得对不对 / 阶段成功了吗" |
| 6 | 🟡 严重 UX | 节奏快 + 无控制权 | 纯定时器驱动，无暂停/重试/跳过 |
| 7 | 🟡 严重 UX | 结束无及时退出 | 校准完成后停留录像界面，无"校准已完成"反馈 |

#### 9 个核心设计决策（已确认）

| ID | 决策 | 选项 |
|----|------|------|
| A | 修复范围 | 完整重设计 + 模块隔离 |
| A1 | 接口边界 | 模块自有摄像头 |
| L1 | UI 布局 | 上下分屏（视频 640×480 + UI 640×240） |
| S2 | 音频反馈 | 蜂鸣 + 中文 TTS（pyttsx3）|
| C2 | 用户控制权 | 鼠标点击主导 + 键盘加速 + 屏幕数字键盘（IME 兼容）|
| F1 | 反馈机制 | 实时计数 + 阶段摘要 + 失败诊断 |
| P2 | 阶段结构 | 5 阶段约 2 分钟 |
| E1 | 结束过渡 | 总结页 + 用户确认才返回 |
| X1 | 失败/取消契约 | Optional[CalibrationResult] 严格契约 |

#### 变更明细

| 章节 | 原始方案（v4.1） | 更新方案（v4.2） | 变更原因 |
|------|-----------------|-----------------|---------|
| §1.6 决策表 | 10 项 | 新增决策 #11 calibration 模块独立 | 模块隔离原则 |
| §2.1 模块图 | 无 calibration/ 子包 | 新增 calibration/ 完整子包（15+ 文件）| 独立子包 |
| §4 技术栈 | 无 pyttsx3 | 新增 pyttsx3 ≥ 2.90（仅 calibration 模块）+ 降级说明 | TTS 音频反馈 |
| §10 时间线 | 27 天 | 29 天，Phase 2 拆为 calibration（4d）+ insights（5d）| 新增模块 |
| §12 风险表 | R23-R26 | 新增 R27（calibration 严重风险）、R28（IME）、R29（pyttsx3）、R30（摄像头切换） | 新风险点 |
| §13 验收清单 | AC30 | 新增 AC31-AC38（calibration 独立运行 + 7 BUG 修复 + IME 兼容）| 新交付标准 |
| §15.4 Phase 2 | T200-T231 | 新增 §15.4.0 calibration（T-CAL-01 ~ T-CAL-14） | 14 子任务 |
| §15.6 汇总 | 113 任务 / 165h | 127 任务 / 185h | calibration +14 任务 +20h |
| §16 版本记录 | v4.1 末 | 新增 v4.2 条目 | 文档规范 |

#### 保守开发策略

由于 R27（严重风险），采用 **"实现 → 测试 → 门禁 → 下一步"** 严格循环：

- 每个 T-CAL-XX 子任务必须达到指定覆盖率门禁才能进入下一步
- main.py 集成（T-CAL-14）放在 14 个子任务的最后一步
- 现有 284 测试始终绿色直到最后一步
- 任一门禁未过 → 暂停，不开新子任务
- 用户实测发现 BUG 1-7 任一仍存在 → 回滚

#### 文件清理

T-CAL-14 完成后立即归档/删除：

- `analyzer/user_calibration.py` → `docs/old_schemes/legacy/user_calibration_v1.py.txt`
- `gui/overlay.py` 中校准 UI 方法（约 200 行）→ 删除
- `main.py` 中 `CalibrationFlowCallbacks` + `CalibrationCoordinator` 类 → 删除
- `storage/db.py` 中 calibration 表 → 保留（与新 result.py 兼容）

#### 版本同步

| 文档 | 原版本 | 新版本 | 说明 |
|------|--------|--------|------|
| PROJECT_PLAN.md | v4.1 | v4.2 | 本次更新（已归档 v4.1）|
| PHASE1_PLAN.md | v1.7 | v1.8 | 新增 §2.15 calibration 重设计任务清单 + 保守开发策略 |
| PHASE2_PLAN.md | v1.0 | v1.1 | 注明 calibration 应在 Phase 2 早期完成（早于 insights） |
| spec | (新) | v1.0 | `docs/superpowers/specs/2026-06-02-user-calibration-redesign.md` |

---

### v4.1 — Insights 离线数据分析子系统（2026-06-02）

> **变更原因**：在与项目负责人深入讨论后，识别出"用模型分析记录数据"是项目"洞察层"承诺的核心兑现路径，且符合所有设计原则（离线运行 + 无监督方法 + sklearn/scipy pip 可装 + 零模型文件部署）。CLAUDE.md 触发：新增功能模块（整个 `analyzer/insights/` 子包） + 技术方案重大调整（Phase 2 范围扩展）。
>
> **路径**：A — 实施前 1 天 Spike 验证（S11-S15），再进入正式实施（T220-T231）。
>
> **明确不做**：实时模型推理（违反 §1.6 决策 #2/#8）、LLM 集成（Phase 3 可选项，本版本暂不考虑）、监督学习预测疲劳（标签自循环陷阱，不建议）。

#### 变更明细

| 章节 | 原始方案（v4.0.2） | 更新方案（v4.1） | 变更原因 |
|------|-------------------|-----------------|---------|
| §1.6 设计决策 | 8 项 | 新增决策 #9 + #10（离线数据分析 + 运行时机） | 明确"离线分析"边界 |
| §2.1 模块图 | 无 insights 子包 | 新增 `analyzer/insights/` 子包（7 个模块） | 整体架构扩展 |
| §2.2 Phase 2 清单 | 5 项 | 新增 8 项 insights 相关任务 | Phase 2 范围扩展 |
| §4 技术栈 | 无 sklearn/scipy/statsmodels/ruptures | 新增 4 个依赖（仅 pip 离线包）+ 体积说明 | 离线分析依赖 |
| §6 核心算法 | §6.8 结束 | 新增 §6.9 完整章节（7 小节）| 5 方法详细算法 |
| §7 DB Schema | sessions + frames | 新增 `insights` 表 + 2 个索引 | 持久化分析结果 |
| §10.1/10.2 里程碑 | 25 天，Phase 2/3 范围 | 27 天，新增 Phase 1.6 Spike (Day 13) + Phase 2 延长 | Spike + 实施 |
| §12 风险表 | R1-R22 | 新增 R23-R26（聚类不稳/STL 数据需求/总耗时/打包体积） | 新增风险点 |
| §13 验收清单 | AC1-AC25 | 新增 AC26-AC30（性能 < 10s + 4 章节验收） | 新增交付标准 |
| §15 任务清单 | 95 任务 | 新增 Phase 1.6（S11-S15+SUM=6 任务）+ Phase 2 insights（T220-T231=12 任务）= 113 任务 | 任务扩充 |
| §16 版本记录 | v4.0.2 末 | 新增 v4.1 条目 | 文档规范 |

#### v4.1 任务摘要

**Phase 1.6（Day 13，6.5h）**：
- S11-S15：5 个方法的 spike 原型验证
- S-SUM：汇总报告 → 推荐参数表

**Phase 2 新增（Day 14-20 部分，21.5h）**：
- T220 features.py（公共特征工程）
- T221 DB Schema（insights 表 + 迁移）
- T222-T226 五个分析方法实现
- T227 pipeline.py 编排（异常隔离）
- T228 报告 4 章节集成
- T229 单测（≥ 75% 覆盖）
- T230 集成测试 + 性能验收
- T231 文档同步

#### 性能预算

| 项目 | 预算 |
|------|------|
| 5 个方法总耗时（30 sessions 历史 + 1h 当前） | **< 10s** |
| 内存峰值 | **< 200MB** |
| PyInstaller 打包体积增加 | **~80 MB** |
| 主循环 FPS 影响 | **0**（离线运行） |

#### Phase 1.6 Spike 验收门禁

S11-S15 必须**全部 PASS** 才能进入正式实施（T220-T231）。若任一 Spike 显示数据/算法问题（如 silhouette < 0.25、PELT 找不到合理 penalty），需在 S-SUM 中给出降级方案或推迟该方法到 v4.2。

#### 版本同步

| 文档 | 原版本 | 新版本 | 说明 |
|------|--------|--------|------|
| PROJECT_PLAN.md | v4.0.2 | v4.1 | 本次更新（已归档 v4.0.2） |
| PHASE1_PLAN.md | v1.6 | v1.7 | 新增 Phase 1.6 Spike S11-S15 |
| PHASE2_PLAN.md | (新建) | v1.0 | 新建 — 含 T200-T219 + T220-T231 |

---

### v3.0 — 双轨开发策略 + 光照/眼镜检测增强（2026-05-30）

> **变更原因**：基于 Phase 0 完整验证结论 + 主开发者硬件条件（RTX 5070 + 32GB）分析，引入开发-生产差异化策略

#### 迭代变更明细

| 章节 | 原始方案（v2） | 更新方案（v3） | 变更原因 |
|------|---------------|---------------|---------|
| §1.6 设计决策 | 无光照/眼镜检测/双轨策略 | 新增 3 项关键设计决策 | Phase 0 后新增需求 |
| §1.7 双轨开发策略 | 无此章节 | 新增完整章节 | 明确开发端 GPU / 生产端 CPU 差异化 |
| §2.2 Phase 1 清单 | 无 light.py / glasses.py | 新增 `detector/light.py` + `analyzer/glasses.py` | Phase 0 验证后的新增模块 |
| §4 技术栈 | 无开发端额外依赖 | 新增 PyTorch + CUDA（仅开发端）| D1 RTX 5070 可用，需明确不影响生产端 |
| §6.5 眼镜检测 | DEPRECATED，无替代方案 | blendshapes + 眼角距离双保险 + 手动保底 | Phase 0 确认失效，需新方案 |
| §6.6 光照检测 | 无此章节 | 新增帧亮度统计方案 | Phase 0 S7 揭示光照不确定性影响 |
| §7 DB Schema | 无 light_level 字段 | 新增 `light_level TEXT` 字段 | 记录光照等级用于分析 |
| §8 配置系统 | 无 light/glasses 配置项 | 新增 `light.*` + `glasses.*` 配置节 | 支持光照/眼镜检测参数调节 |
| R6 风险 | DEPRECATED，无解法 | blendshapes 双保险 + 手动保底 | Phase 0 已验证失效，需 Phase 1 解决 |
| R22 风险 | 无此风险 | 新增"光照条件影响检测稳定性" | Phase 0 光照测试揭示 |
| T112 | 无此任务 | 新增 `detector/light.py` | 光照检测作为独立模块 |
| T119 | 无此任务 | 新增 `analyzer/glasses.py` | 眼镜检测作为独立模块 |
| T300-T302 | 泛泛"眼镜模式优化" | 具体为 blendshapes + 眼角距离双保险 | 方案已明确 |
| §16 版本记录 | v1/v2 变更 | 新增 v3 变更记录 | 文档规范 |

#### v2 → v3 关键决策记录

1. **眼镜检测**：EAR 方差法 **废弃** → blendshapes + 眼角距离双保险 + 手动保底
2. **光照检测**：新增帧亮度统计方案，零成本，每帧计算
3. **双轨策略**：开发端 GPU 验证 → 生产端规则/阈值落地，零外部依赖
4. **CQS 阈值**：0.70 → 0.60（Phase 0 实测调整）
5. **头部姿态**：solvePnP → MediaPipe 内置矩阵（Phase 0 验证通过）

#### 未解决问题（Phase 1 需处理）

| 问题 | 建议方案 |
|------|---------|
| 眼镜 blendshapes 检测精度待验证 | Phase 1 开发端在 RTX 5070 训练 blendshapes MLP，提取阈值规则 |
| 眼角关键点距离阈值待确定 | Phase 1 采集眼镜/不戴眼镜各 500+ 帧确定阈值 |
| 疲劳 LSTM 模型缺数据 | Phase 1 MVP 先用启发式阈值，Phase 2 后收集数据再迭代 |
| os._exit() 用于 spike 脚本 | spike 为一次性验证脚本，Phase 1 main.py 需使用线程超时强杀等安全退出方案 |

---

### v2.0 — 基于 Phase 0 Spike 验证结果（2026-05-30）

> **变更原因**：Phase 0 spike 验证发现原有方案存在技术错误，部分假设与实测不符

#### 迭代变更明细

| 章节 | 原始方案（v1） | 更新方案（v2） | 变更原因 |
|------|---------------|---------------|---------|
| §6.3 头部姿态 3D 模型 | `cv2.solvePnP` + 6 锚点自定义 3D 模型 | MediaPipe 内置 `facial_transformation_matrixes` | Phase 0 实测 solvePnP yaw=-80°（完全错误），改用 MediaPipe 内置矩阵后 yaw_std=0.59° |
| §6.5 眼镜/遮挡自动降级 | EAR 方差 < 0.003 触发 glasses_mode | **DEPRECATED**，建议 Phase 1 探索 blendshapes 或手动切换 | Phase 0 实测戴眼镜 EAR 方差（0.00002-0.003）反而**低于**不戴眼镜（0.004-0.007），阈值 0.003 无法区分 |
| §6.2 基线校准算法 | CQS 阈值 ≥ 0.70 | CQS 阈值 ≥ 0.60 | Phase 0 三次校准最高 CQS 仅 0.629，无一次达标 0.70 |
| R6 风险 | 校准阶段自动检测 glasses_mode | **DEPRECATED**，需 Phase 1 重新设计眼镜检测方案 | 同上，眼镜检测方案失效 |
| R10 风险 | solvePnP 抖动超过 ±3° → 增加锚点 + 中值滤波 | **已解决** — MediaPipe 方案抖动仅 0.59° | 技术方案替换后问题消失 |
| R15 风险 | EAR 方差阈值 0.003 | **DEPRECATED** | 同眼镜检测问题 |

#### v1 → v2 关键决策记录

1. **头部姿态**：solvePnP → MediaPipe 内置矩阵
2. **眼镜检测**：EAR 方差法 **废弃**，等待 Phase 1 重新设计
3. **CQS 阈值**：0.70 → 0.60（基于实测数据调整）

---

### v3.1 — 版本同步更新（2026-05-30）

> **变更原因**：同步更新 PHASE0_PLAN.md 和 PHASE0_SUMMARY.md 版本至 v3.0；确认 MediaPipe pip 包为 CPU Only，GPU 加速不适用

#### 变更明细

| 文档 | 原版本 | 新版本 | 变更内容 |
|------|--------|--------|---------|
| PHASE0_PLAN.md | v2.0 | v3.0 | 与 PROJECT_PLAN v3.0 同步 |
| PHASE0_SUMMARY.md | v1.0 | v3.0 | 与 PROJECT_PLAN v3.0 同步 |
| PROJECT_PLAN.md | v3.0 | v3.1 | 版本记录更新 |

#### MediaPipe GPU 确认结论

| 项目 | 实际情况 | 影响 |
|------|---------|------|
| pip 安装版 | **CPU Only** | GPU processing is disabled in build flags |
| XNNPACK | ✅ 可用（CPU 加速）| 实测 32.97 FPS > 25 FPS 目标 |
| GPU Delegate | **桌面版不可用** | 需要源码编译，当前不适用 |

---

### v3.2 — Blendshapes 眼镜检测验证（2026-05-30）

> **变更原因**：补充测试 S9/S10 验证 Blendshapes 可有效区分眼镜状态

#### 变更明细

| 章节 | 变更内容 |
|------|---------|
| §6.5 眼镜检测 | Blendshapes 验证有效，眯眼比率为最佳特征（0.40 vs 0.91） |
| Phase 0 | 新增 S9（Blendshapes 采集）和 S10（EPA 分析） |
| Phase 0 产出物 | 新增 `s9_blendshapes_analysis.txt` 和 `s10_epa_analysis.txt` |

#### Blendshapes 眼镜检测关键发现

| 特征 | 不戴眼镜 | 戴眼镜 | 区分度 |
|------|---------|--------|--------|
| 眯眼比率 | 0.40 | 0.91 | **最佳** |
| 眨眼频率 | 0.008 | 0.042 | +425% |
| 眼睛睁开度 | 0.09 | 0.02 | -78% |

---

### v3.3 — 眨眼检测算法改进（2026-05-30）

> **变更原因**：修复眨眼检测固定阈值问题，增加眯眼/眨眼区分和多信号融合

#### 变更明细

| 章节 | 原始方案 | 更新方案 | 变更原因 |
|------|---------|---------|---------|
| §6.4 疲劳分级 | 固定阈值 0.21 | 动态阈值（基线×0.75） | 用户眨眼 EAR 0.23-0.24 高于固定阈值 0.21，导致大量漏检 |
| §6.4 | 无眯眼区分 | 增加眯眼/眨眼时间窗口区分 | 眯眼（>1秒）被误判为眨眼 |
| §6.8 新增 | 无 | 三阶段眨眼检测改进 | 系统性解决固定阈值、眯眼误判、头部晃动问题 |

#### 眨眼检测改进内容

| 阶段 | 改进内容 | 状态 |
|------|---------|------|
| 阶段一 | 基于个人基线的动态阈值（基线×0.75） | 待实现 |
| 阶段二 | 眯眼 vs 眨眼区分（时间窗口 400ms） | 待实现 |
| 阶段三 | 多信号融合眨眼置信度（头部姿态+面部稳定性） | 待实现 |

#### 关键实测数据

| 问题 | 实测数据 |
|------|---------|
| 固定阈值漏检 | 1小时仅检测83次眨眼（正常应为1000+次） |
| 用户眨眼 EAR 范围 | 0.23-0.24（阈值0.21以下才触发） |
| 修复后眨眼检测 | 20秒检测11次 = 33次/分钟（正常范围） |

---

### v3.4 — 用户辅助多轮校准（2026-05-31）

> **变更原因**：T148 用户辅助校准模块设计完成，需同步更新总方案

#### 变更明细

| 章节 | 原始方案 | 更新方案 | 变更原因 |
|------|---------|---------|---------|
| §6 新增 | 无 | T148 用户多轮校准 | 算法精度不足，需用户参与校准 |

#### T148 6阶段校准流程

| 阶段 | 名称 | 时长 | 说明 |
|------|------|------|------|
| 0 | 自动基线采集 | 7秒 | EAR均值、yaw/pitch均值、眼镜模式 |
| 1 | 闭眼校准 | 5秒 | 请闭眼保持，采集 ear_min |
| 2 | 睁眼恢复 | 3秒 | 请睁眼，验证 EAR 恢复 |
| 3 | 眯眼校准 | 8秒 | 请故意眯眼 2-3秒，采集眯眼阈值 |
| 4 | 头部姿态 | 12秒 | 抬头3s + 低头3s + 左转3s + 右转3s |
| 5 | 眨眼计数 | 3轮×20秒 | 用户计数 vs 程序检测对比 |

**总时长**：约 87 秒（< 90 秒要求）

#### 设计文档

- `docs/T148_USER_CALIBRATION_DESIGN.md` — T148 详细设计
- `docs/superpowers/plans/2026-05-31-t148-user-calibration-plan.md` — 实现计划

#### 版本同步

| 文档 | 原版本 | 新版本 | 说明 |
|------|--------|--------|------|
| PHASE1_PLAN.md | v1.2 | v1.3 | T148 设计同步 |
| PROJECT_PLAN.md | v3.3 | v3.4 | 本次更新 |

---

### v1.0 — 初始版本（2026-05-29）

> **状态**：已被 v3.2 替代

原始方案包含：
- `cv2.solvePnP` + 6 锚点头部姿态估计（**已验证失败**）
- EAR 方差眼镜检测（**已验证失效**）
- CQS 阈值 0.70（**实测未达标**）

---

### v4.0 — 10-发现审计修复（2026-06-01）

> **变更原因**：v3.3 → v3.4 重构（提交 11814cf）遗留双管道与多个接线未闭合 bug。Major bump，CLAUDE.md 触发：实测数据与方案预想不符 + 关键假设被证伪 + 技术方案重大调整。
>
> **审计范围**：HEAD~1..HEAD 重构后全项目代码。10 个发现：🔴×5 严重、🟡×4 中等、🟢×1 轻微。

#### 变更明细

| 章节 | 原始方案（v3.4） | 更新方案（v4.0） | 变更原因 |
|------|----------------|-----------------|---------|
| §6 核心算法 | `baseline_blink_rate` 字段从未应用于 `FatigueAnalyzer` | 校准完成 → `_fatigue_analyzer.set_baseline_blink_rate` 链路接通；DB 加 `baseline_blink_rate` 列 | Issue #2 — 100% 用户疲劳评分基于固定 15/min 基线 |
| §6 核心算法 | 眼镜双保险为 OR（任一触发即报） | 改 AND-with-confidence（任一方法 confidence≥0.6） | Issue #7 — 共享失败模式（眯眼即误报） |
| §6 校准数据 | `_run_auto_calib` 与 `add_frame` 双重采集 | FrameProcessor 每帧调 `add_frame`；`tick()` 仅做倒计时+阶段切换 | Issue #3+#4 — 7s 校准仅 ~7 样本（原设计 210）；`on_phase_complete` 双触发 |
| §7 DB Schema | `sessions` 表无 `baseline_blink_rate` 列 | T154 PRAGMA 检查 + ALTER TABLE 迁移新增 | Issue #2 — 需持久化校准基线 |
| §15.6 任务清单 | (无) | 新增 T149-T162（10 个修复 + 1 审计验证） | 本版本 |
| §16 版本记录 | v3.4 | 新增 v4.0 记录 | 文档规范 |

#### T149-T162 任务摘要

| 任务 | 文件 | 估时 | 说明 |
|------|------|------|------|
| T149 | PROJECT_PLAN.md + docs/old_schemes/ | 0.5h | 归档 v3.4 + bump v4.0 |
| T150 | PHASE1_PLAN.md | 0.25h | bump v1.4 + 新增版本记录行 |
| T151 | main.py | 0.5h | 删除 `EyeFocusApp._process_frame` (159 行) + 17 死属性 |
| T152 | tests/test_integration.py | 1.0h | 11 处 `_process_frame` → `_frame_processor.process_frame`；恢复 add_frame 断言 |
| T153 | main.py | 0.25h | main.py:808-813 私有属性 → FrameProcessor 公共属性 |
| T154 | storage/db.py, models.py | 0.75h | PRAGMA 检查 + ALTER TABLE 新增 `baseline_blink_rate` 列 |
| T155 | main.py | 0.5h | FrameProcessor.process_frame 在 AUTO_CALIB 调 `add_frame` |
| T156 | analyzer/user_calibration.py | 0.5h | 删除 `_run_auto_calib`；新增 `_finalize_auto_calib` |
| T157 | analyzer/user_calibration.py, models.py | 0.5h | CalibrationResult 加字段；_compute_result 计算基线 |
| T158 | main.py | 0.5h | `_apply_calibration_result` 调 `set_baseline_blink_rate` |
| T159 | tests/test_light.py | 0.25h | 帧路径边界测试 100.0 → NORMAL、100.1 → BRIGHT |
| T160 | analyzer/glasses.py, tests/test_glasses.py | 1.0h | AND-with-confidence；DEFAULT_GLASSES_CONFIDENCE_THRESHOLD=0.6 |
| T161 | tests/test_glasses.py, analyzer/glasses.py | 0.25h | 测试改名 + 删自标记注释 + 边界测试 |
| T162 | tests/test_audit_verification.py (新) | 1.0h | 一次性验证 10 个审计点 |

#### 新增测试

- T-NEW-01/02/07 in tests/test_integration.py
- T-NEW-03/04/05/06 in tests/test_user_calibration.py
- T-NEW-08 in tests/test_storage.py
- T-NEW-09 in tests/test_light.py
- T-NEW-10/11 in tests/test_glasses.py
- T-NEW-12 in tests/test_audit_verification.py

#### 风险表更新

| ID | 风险 | v4.0 缓解 |
|----|------|----------|
| R-new-1 | 重构遗留双管道 | T151+T152：删除 `_process_frame`，FrameProcessor 单一来源 |
| R-new-2 | `set_baseline_blink_rate` 未接线 | T154+T157+T158：DB 列 + CalibrationResult 字段 + 应用调用 |
| R-new-3 | 校准数据流退化 | T155+T156：每帧 add_frame + 删 _run_auto_calib |
| R-new-4 | 校准测试被掏空 | T152：恢复 add_frame 断言；T162 验证 |
| R-new-5 | 光照亮度边界未测 | T159：帧路径边界测试 |
| R-new-6 | 眼镜双保险同向 | T160：AND-with-confidence |
| R-new-7 | 眼镜测试名实不符 | T161：改名 + 删自标记 |
| R-new-8 | `_frame_count` 私有直达 | T153：使用 FrameProcessor 公共属性 |

#### Phase 1.5 眼镜检测实测计划（延后）

- 采集戴眼镜/不戴眼镜各 500+ 帧，确定 `inner_canthus_ratio_thresh` 阈值
- 实测 3 名戴眼镜用户 + 3 名不戴眼镜用户
- 目标：v4.0 完成后实测，移除"如有问题请反转"自标记
- 不阻塞 v4.0 合并

#### 版本同步

| 文档 | 原版本 | 新版本 | 说明 |
|------|--------|--------|------|
| PROJECT_PLAN.md | v3.4 | v4.0 | 本次更新（已归档 v3.4 → docs/old_schemes/PROJECT_PLAN_v3.4.md） |
| PHASE1_PLAN.md | v1.3 | v1.4 | T149-T162 任务同步 |

---

### v4.0.1 — 环境实测 bug 修复（2026-06-01）

> **变更原因**：v4.0 实测阶段（RTX 5070 + 真实摄像头）发现 2 个 v4.0 审计漏掉的 bug。Minor bump，CLAUDE.md 触发：实测数据与方案预想不符。
>
> **新增任务**：T163 (B1 critical) + T164 (B2 medium)，由实测发现并立即修复。

#### 变更明细

| 任务 | 文件 | 修复内容 | 验证 |
|------|------|---------|------|
| T163 | `storage/db.py:282` | `create_session()` 用 `datetime` 微秒无去重 → 100 次同微秒 97% 失败。改用 `datetime + uuid4(12 hex)`，并 5 次 IntegrityError 重试 | 100 次实测全成功，ID unique；test_create_session_rapid_unique 通过 |
| T164 | `analyzer/user_calibration.py:378` | `_get_current_phase_duration` 用 `phases["head_pose"] / 4` KeyError。兼容 `head_yaw + head_pitch` 双字段 | test_head_pose_phase_with_yaw_pitch_only 通过；无 head_pose key 校准流程不崩 |

#### 影响

- 修复 B1：阻塞主程序"启动时检查未结束 session → 续期"路径的潜在 UNIQUE 冲突崩溃
- 修复 B2：校准流程中 HEAD 阶段崩溃的兜底（用户用 `head_yaw/head_pitch` 单字段配置时）

#### 验证

- ✅ 279/279 测试通过（275 + 4 个回归）
- ✅ 实测 100 次 create_session 全成功
- ✅ 实测无 head_pose key 校准全流程通过
- ✅ 已归档 v4.0 → `docs/old_schemes/PROJECT_PLAN_v4.0.md`

#### 版本同步

| 文档 | 原版本 | 新版本 | 说明 |
|------|--------|--------|------|
| PROJECT_PLAN.md | v4.0 | v4.0.1 | T163+T164 bug 修复（已归档 v4.0） |
| PHASE1_PLAN.md | v1.4 | v1.5 | T163+T164 任务同步 |

---

### v4.0.2 — 用户体验实测 bug 修复（2026-06-01）

> **变更原因**：v4.0.1 实测阶段（CLI 启动 + 摄像头 5 秒运行）发现 4 个 UX bug。Minor bump，CLAUDE.md 触发：实测数据与方案预想不符。
>
> **新增任务**：T165 (B3 high) + T166 (B4 medium) + T167 (B5 low) + T168 (B6 low)。

#### 变更明细

| 任务 | 文件 | 修复内容 | 验证 |
|------|------|---------|------|
| T165 | `main.py:766` | `initialize()` 末尾调 `_camera_manager.start()` 验证摄像头，无效时返回 False + 明确错误日志 + shutdown 已分配资源 | test_initialize_returns_false_when_camera_unavailable 通过；实测 index=99 → False + "无法打开摄像头 (index 99)" |
| T166 | `main.py:22-27` | import mediapipe 之前设 `GLOG_logtostderr=0` + `ABSL_CPP_MIN_LOG_LEVEL=3` + `MEDIAPIPE_DISABLE_GPU=1` 屏蔽 telemetry | 实测 Python 层无 clearcut 上报日志 |
| T167 | `analyzer/user_calibration.py:301-326` | `_get_phase_info` 动态从 `phases` dict 渲染秒数，不再硬编码 "5 秒"/"3 秒"/"2-3 秒" | test_default_phase_info_no_hardcoded_seconds + test_custom_phase_info_uses_custom_seconds 通过 |
| T168 | `main.py:1131-1143` | `main()` 顶部 `logging.getLogger("mediapipe").setLevel(ERROR)` + `absl` ERROR 级别 + 统一日志格式 | 实测仅项目日志出现，absl/mediapipe 噪声屏蔽 |

#### 影响

- 修复 B3：用户启动后黑屏无错的致命问题 → 立即明确错误"无法打开摄像头 (index X)"
- 修复 B4：减少 MediaPipe Google telemetry 上报（隐私 + 网络请求）
- 修复 B5：校准文案与配置同步（修改 phases dict 自动反映到 UI）
- 修复 B6：控制台日志风格统一

#### 已知限制

- B4 部分有效：MediaPipe C++ 层 `W0000` 警告仍出现（absl/Python 层已禁，C++ glog 需 `--logtostderr=0` 但 Python tasks 0.10.35 似乎绕过此 env var；不影响功能）

#### 验证

- ✅ 284/284 测试通过（279 + 5 个回归）
- ✅ 实测 B3-B6 修复全部生效

#### 版本同步

| 文档 | 原版本 | 新版本 | 说明 |
|------|--------|--------|------|
| PROJECT_PLAN.md | v4.0.1 | v4.0.2 | T165-T168 UX 修复（已归档 v4.0.1） |
| PHASE1_PLAN.md | v1.5 | v1.6 | T165-T168 任务同步 |

---

> **计划已完整细化至函数级别，共 95 个任务。**
>
> 开发启动命令：`git init && python main.py`（待创建）
