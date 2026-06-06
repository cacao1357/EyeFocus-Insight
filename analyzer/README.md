# `analyzer/` — 离线分析层

> v4.0+ 稳定模块 | 测试覆盖 100% | 状态：✅ 活跃

**职责**：从帧级数据计算**焦点分数（focus）**、**疲劳等级（fatigue）**、**眼镜模式检测（glasses）**。纯函数式 / 状态式计算器，**无 I/O**（无摄像头 / 无 DB 写入），输入 ndarray，输出 dataclass / 数值。

## 公共 API（`__init__.py` 单入口）

| 工厂函数 | 返回类 | 职责 |
|---------|--------|------|
| `create_focus_analyzer()` | `FocusAnalyzer` | focus 分数：眨眼/头部姿态/视线综合 |
| `create_glasses_detector()` | `GlassesDetector` | blendshapes + 眼角距离双保险 |
| `create_fatigue_analyzer()` | `FatigueAnalyzer` | EAR/眨眼频率/头部姿态 → 疲劳切档 |

## 子模块

| 文件 | 行数 | 职责 |
|------|------|------|
| `focus.py` | 405 | focus 分数综合（EAR + 头部姿态 + 视线） |
| `glasses.py` | 339 | 眼镜模式检测（blendshapes 主 + 眼角距离兜底）|
| `fatigue.py` | 570 | 疲劳等级（LOW/MEDIUM/HIGH）+ 切档阈值 |
| `baseline.py` | 363 | 基线采集（EAR 校准用）— v4.0 内部 |
| `user_calibration.py` | 641 | ⚠️ v3.x 旧校准实现，已被 `calibration/` 取代，**保留作 v3.x fallback** |

## 使用示例

```python
from analyzer import create_focus_analyzer

analyzer = create_focus_analyzer()
score = analyzer.update(ear=0.3, yaw=5.0, pitch=-2.0, gaze_x=0.1, gaze_y=0.0)
print(f"focus = {score:.2f}")  # 0.0-1.0
```

## 测试入口

```bash
pytest tests/test_analyzer.py tests/test_focus.py tests/test_glasses.py  # 382 总套件
```

## 已知遗留

- `user_calibration.py` 是 v3.x 旧实现，**main.py 中通过 `config.calibration_mode='v3_x'` 走 fallback**。v4.4 默认 `'v4_2'`（`calibration/` 子包）。何时归档待 v4.5 决定。
- `analyzer/insights/` 离线分析子包（5 个方法）⏳ 计划中，**未实施**（PHASE2_PLAN v1.3 §2.6 T220-T231）
