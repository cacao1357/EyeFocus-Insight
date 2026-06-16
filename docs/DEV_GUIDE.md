# EyeFocus Insight — 开发指南

> **版本**：v1.0 | **日期**：2026-06-13
> **适用对象**：项目开发者和贡献者

---

## 一、开发环境

### 1.1 环境搭建

```bash
# 克隆项目
git clone https://github.com/cacao1357/EyeFocus-Insight.git
cd EyeFocus-Insight

# 创建虚拟环境（Python 3.12）
python -m venv .venv312

# 激活
.venv312\Scripts\activate      # Windows
# source .venv312/bin/activate  # Linux/macOS

# 安装依赖
pip install -r requirements.txt

# 安装开发依赖
pip install pytest pytest-cov ruff mypy
```

### 1.2 硬件规格

| 硬件 | 规格 |
|------|------|
| CPU | AMD Ryzen 9 8945HX（16C/32T） |
| GPU | RTX 5070 Laptop / 8 GB GDDR7 |
| 内存 | 32 GB |
| OS | Windows 11 Home China |

### 1.3 工具链

```bash
# 运行测试
python -m pytest tests/ calibration/tests/ --tb=line -q

# 带覆盖率
python -m pytest tests/ --tb=line -q --cov=detector --cov=analyzer --cov=storage

# 指定测试
python -m pytest tests/test_glasses.py -v

# 运行主程序
python -X utf8 main.py --qt

# 测试 Qt 校准对话框
python -X utf8 test_qt_monitor.py
```

> **注意**：Windows + Git Bash 环境下，Python 命令需加 `-X utf8` 参数防止中文编码问题。

---

## 二、项目架构

### 2.1 模块结构

```
EyeFocus Insight/
├── main.py          # 主协调器（Facade 模式）
├── detector/        # 信号采集层
│   ├── face_mesh.py      # MediaPipe Face Mesh 封装
│   ├── eye_aspect.py     # EAR 计算 + 眨眼检测
│   ├── head_pose.py      # 头部姿态稳定性
│   ├── light.py          # 光照条件检测
│   ├── gaze.py           # 视线估计
│   └── euler_utils.py    # 矩阵 → Euler 角
├── analyzer/        # 信号分析层
│   ├── focus.py          # 专注度分析（30s 窗口）
│   ├── fatigue.py        # 疲劳等级评估
│   ├── glasses.py        # 眼镜检测
│   ├── distraction.py    # 分心事件分析
│   └── insights/         # 离线分析子包
├── gui/             # 用户界面层 (PyQt5)
│   ├── qt_window.py          # 监测主窗口
│   ├── calibration_dialog.py # 校准对话框
│   └── qt_overlay.py         # 圆环 + 卡片
├── storage/         # 数据持久化层 (SQLite)
├── reporter/        # 报告生成层
│   ├── report_html.py   # HTML 报告生成
│   ├── charts.py        # Matplotlib 图表
│   └── insights.py      # 建议引擎
├── calibration/     # 校准模块（v4.2，OpenCV 备用）
├── tests/           # 项目级测试
└── docs/            # 文档
```

### 2.2 模块职责

| 层 | 职责 | 输出 | 约束 |
|:--:|------|------|:----:|
| detector | 从图像提取原始信号 | 各类 dataclass | 纯函数式，不持有摄像头 |
| analyzer | 从信号推导状态 | FocusResult / FatigueResult | 30s 窗口内无状态 |
| gui | PyQt5 窗口渲染 | QWidget | 不直接访问摄像头或 DB |
| storage | 数据持久化 | SQLite | 仅通过 DatabaseManager 访问 |
| reporter | HTML 报告生成 | HTML 字符串 | 依赖 Matplotlib 渲染 |

### 2.3 模块接口规范（v4.2 范式）

**新增模块或整体重做的模块**必须遵守：

1. `__init__.py` 单一入口，只导出公共 API
2. `python -m <module>` 可独立运行
3. 资源自有管理或显式接收
4. I/O 均为 dataclass（禁止 tuple 返回）
5. 失败/取消返回 `Optional`，不抛异常
6. 单元测试不依赖 `__main__.py`

---

## 三、编码规范

### 3.1 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 类名 | PascalCase | `FocusAnalyzer`, `EyeFocusWindow` |
| 函数/方法 | snake_case | `process_frame()`, `_handle_face_lost()` |
| 常量 | UPPER_CASE | `DEFAULT_EAR_THRESHOLD` |
| 私有属性 | `_` 前缀 | `_latest_focus_result` |
| 文件/模块 | snake_case | `eye_aspect.py`, `qt_window.py` |

### 3.2 文档注释

所有公共 API 必须写 docstring：

```python
def analyze(self, ear: float, yaw: float = 0.0,
            pitch: float = 0.0, gaze_score: float = 100.0,
            brightness: float = 128.0,
            face_detected: bool = True) -> FocusResult:
    """专注度分析

    Args:
        ear: 当前帧 EAR 值
        yaw: 当前帧头部偏航角（度）
        pitch: 当前帧头部俯仰角（度）
        gaze_score: 视线集中度 (0-100)
        brightness: 当前帧亮度均值
        face_detected: 是否检测到人脸

    Returns:
        FocusResult 对象
    """
```

### 3.3 错误处理

- **不吞异常**：仅在预期可能失败的地方使用 try/except
- **日志级别**：常态信息用 `logger.info`，异常用 `logger.exception`，调试用 `logger.debug`
- **资源清理**：使用 try/finally 或 context manager

---

## 四、测试

### 4.1 测试结构

```
tests/
├── test_glasses.py         # 眼镜检测单元测试
├── test_light.py           # 光照检测单元测试
├── test_face_mesh.py       # FaceMesh 单元测试
├── test_distraction.py     # 分心识别单元测试
├── test_insights_unit.py   # Insights 单元测试
├── test_insights_integration.py  # Insights 集成测试
├── test_main_high_bugs.py  # main.py 高优 bug 回归
├── test_main_medium_bugs.py      # main.py 中优 bug 回归
├── test_common.py          # 通用测试
└── ...

calibration/tests/
├── unit/                   # 单元测试
└── integration/            # 集成测试
```

### 4.2 测试规范

- **基线冻结**：改动 ≥ 2 文件时，开工前确认基线 `pytest tests/ --tb=no -q`
- **禁止改测试让红灯变绿**（除非测试本身有 bug）
- 单元测试不依赖 `__main__.py`
- Mock MediaPipe detector 避免实际推理

### 4.3 全量测试

```bash
# 完整套件（606 个）
python -m pytest tests/ calibration/tests/ --tb=line -q

# 仅 tests/
python -m pytest tests/ --tb=line -q

# 仅某模块
python -m pytest tests/test_glasses.py -v
```

---

## 五、Git 协作

### 5.1 分支策略

- **main**：稳定分支，直接合并
- 功能分支合并后立即删除

### 5.2 Commit Message

```
type(scope): summary (≤ 70 字符)

body（可详细，空行分隔）
```

| type | 使用场景 |
|------|---------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构 |
| `test` | 测试相关 |
| `docs` | 文档 |
| `chore` | 构建/工具 |

示例：
```
feat(glasses): blendshapes + 眼角距离双保险检测

实现两种独立方法：
1. blendshapes 眯眼比率 > 0.85
2. 内侧眼角/瞳孔距离比值 > 0.5
AND-with-confidence 融合，≥ 0.6 才报"戴眼镜"
```

### 5.3 推送前检查

```bash
# 1. 测试全绿
python -m pytest tests/ --tb=line -q

# 2. Git 卫生（无 .venv/*.pyc/.coverage 入库）
git ls-files | python -c "..."

# 3. .git 体积 < 5 MB
du -sh .git

# 4. requirements.txt vs import 一致
# 5. 更新 README（API 变更/依赖变更/配置变更）
# 6. 更新 CLAUDE.md 版本号
```

---

## 六、PyInstaller 打包

### 6.1 打包命令

```bash
pip install pyinstaller
pyinstaller eyefocus.spec
```

### 6.2 注意事项

| 问题 | 处理 |
|------|------|
| MediaPipe 隐藏导入 | `--hidden-import mediapipe.python.solutions.face_mesh` |
| PyQt5 插件路径 | spec 文件指定 `QT_QPA_PLATFORM_PLUGIN_PATH` |
| face_landmarker.task 模型 | `--add-data "face_landmarker.task;."` |
| sklearn 子模块 | `--hidden-import sklearn.ensemble` |
| scipy 子模块 | `--hidden-import scipy.stats` |
| statsmodels 子模块 | `--hidden-import statsmodels.tsa.seasonal` |
| ruptures | `--hidden-import ruptures` |

预计打包后体积：~250-350 MB（含 MediaPipe + PyQt5 + sklearn + matplotlib）

---

## 七、关键技术决策

### 7.1 为什么选 MediaPipe 而非 dlib/OpenCV？

| 对比项 | MediaPipe | dlib | OpenCV |
|--------|:---------:|:----:|:------:|
| 关键点数 | 478 | 68 | 无专用模型 |
| 推理速度 (CPU) | ~7ms | ~30ms | N/A |
| Blendshapes | ✅ 内置 | ❌ | ❌ |
| Python 接口 | ✅ | ✅ | ✅ |
| 模型大小 | ~10MB | ~60MB | 无 |

### 7.2 为什么用 PyQt5 替代 OpenCV HighGUI？

| 问题 | OpenCV | PyQt5 |
|------|:------:|:-----:|
| 中文显示 | ❌ | ✅ |
| 按钮交互 | waitKey 轮询 | 信号/槽 |
| 布局系统 | 手动坐标 | QLayout |
| 模态对话框 | ❌ | ✅ QDialog |
| 圆角/渐变 | 手动 paint | QPainterPath |

### 7.3 为什么专注度只有 3 档？

**诚实原则**：单一 EAR 信号信息量有限，强行输出 0-100 分数是"自欺"。3 档分类（FOCUSED/NORMAL/DISTRACTED）配合 30s 窗口统计，是信号精度和可用性的最佳平衡。

---

## 八、版本记录

| 版本 | 日期 | 变更内容 |
|:----:|:----:|---------|
| v1.0 | 2026-06-13 | 初始版本 |
