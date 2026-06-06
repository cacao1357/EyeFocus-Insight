# `tests/` — pytest 顶层测试套件

> 默认 `pytest` testpaths | **382 测试** | 状态：✅ 全绿

**职责**：核心模块的单元/集成/回归测试。**`pytest` 默认 testpaths = `tests/`**（`pytest.ini:2`），完整套件 580 = `tests/` 382 + `calibration/tests/` 198。

## 运行

```bash
# 默认（仅 tests/，382 个）
pytest tests/                                # ~12s

# 完整套件（580 个，含 calibration/tests/，~57s）
pytest tests/ calibration/tests/             # ~57s

# 单文件
pytest tests/test_analyzer.py -v

# 含覆盖率
pytest tests/ --cov=analyzer --cov=detector --cov=storage
```

## 测试文件清单（17 + 1 手动）

| 文件 | 行数 | 范围 |
|------|------|------|
| `test_analyzer.py` | 757 | analyzer/ 全部模块（focus/glasses/fatigue/baseline）|
| `test_audit_verification.py` | 434 | v4.3 审计 58 findings 修复验证 |
| `test_common.py` | 202 | 共享工具/常量 |
| `test_detector.py` | 426 | detector/ 通用 |
| `test_face_mesh.py` | 577 | FaceMeshDetector 深度 |
| `test_glasses.py` | 541 | 眼镜检测（blendshapes + 眼角距离）|
| `test_gui.py` | 323 | gui/overlay v4.4 新增 4 测试 |
| `test_integration.py` | 997 | 端到端集成 |
| `test_light.py` | 273 | 光照检测 |
| `test_main_high_bugs.py` | 290 | main.py H-level bug 回归 |
| `test_main_medium_bugs.py` | 300 | main.py M-level bug 回归 |
| `test_reporter.py` | 779 | reporter/ 全部 |
| `test_spike_imports.py` | 117 | spike/ 模块可 import 性 |
| `test_spike_insights_common.py` | 111 | spike/insights/ 共享 |
| `test_storage.py` | 625 | storage/ 全部 |
| `test_user_calibration.py` | 286 | v3.x user_calibration fallback |
| `test_v4_2_integration.py` | 311 | v4.2 calibration 集成到 main.py |
| `manual_user_flow_test.py` | 279 | ⚠️ **手动脚本**（不以 test_ 开头，pytest 不收）|

## conftest.py

路径修复：把项目根加入 `sys.path` 让所有 test 文件能 `from analyzer import ...`。

## 已知慢测

| 测试 | 耗时 | 原因 |
|------|------|------|
| `calibration/tests/integration/test_face_detection_call.py::test_extract_metrics_with_real_detector_face_detected_true` | **43s** | 真摄像头 + MediaPipe 加载 + clearcut 远程上报失败重试 |

> 单跑 11 个 integration 慢测试总和 44s。完整 580 套件约 57s。

## 关联

- `calibration/tests/` — 198 校准专属测试（独立 testpaths，v4.2 模块隔离）
- `spike/` — 一次性探针（非 pytest 收集）
- `pytest.ini` — 全局配置（testpaths=tests, python_files=test_*.py）
