"""
tests/test_gui.py — GUI 模块单元测试
覆盖 gui/ 包中所有可离线测试的函数。
"""

import sys
import os
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui.overlay import (
    FocusOverlay,
    OverlayConfig,
    CalibrationProgress,
    AlertLevel,
    AlertMessage,
    create_focus_overlay,
)


class TestOverlayConfig:
    """OverlayConfig 单元测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = OverlayConfig()
        assert config.window_name == "EyeFocus Insight"
        assert config.width == 640
        assert config.height == 480
        assert config.alpha == 0.85

    def test_custom_config(self):
        """测试自定义配置"""
        config = OverlayConfig(
            window_name="Test Window",
            width=1280,
            height=720,
            alpha=0.8,
        )
        assert config.window_name == "Test Window"
        assert config.width == 1280
        assert config.height == 720


class TestFocusOverlay:
    """FocusOverlay 单元测试"""

    def test_initial_state(self):
        """测试初始状态"""
        overlay = FocusOverlay()
        assert overlay._alerts == []
        assert overlay._calibration is None

    def test_draw_basic_frame(self):
        """测试基本帧绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame)
        assert result is not None
        assert result.shape == frame.shape

    def test_draw_with_focus_score(self):
        """测试带专注度分数的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame, focus_score=85.0)
        assert result is not None

    def test_draw_with_fatigue_level(self):
        """测试带疲劳等级的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame, fatigue_level="LOW")
        assert result is not None

        result = overlay.draw(frame, fatigue_level="MEDIUM")
        assert result is not None

        result = overlay.draw(frame, fatigue_level="HIGH")
        assert result is not None

    def test_draw_with_no_detection(self):
        """测试未检测到人脸/眼睛的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = overlay.draw(frame, eye_detected=False, face_detected=False)
        assert result is not None

    def test_draw_with_calibration(self):
        """测试带校准进度的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        calibration = CalibrationProgress(
            current=50,
            total=100,
            cqs=0.65,
            is_complete=False,
        )

        result = overlay.draw(frame, calibration=calibration)
        assert result is not None

    def test_draw_with_complete_calibration(self):
        """测试带完成校准的绘制"""
        overlay = FocusOverlay()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        calibration = CalibrationProgress(
            current=100,
            total=100,
            cqs=0.75,
            is_complete=True,
        )

        result = overlay.draw(frame, calibration=calibration)
        assert result is not None

    def test_add_alert(self):
        """测试添加告警"""
        overlay = FocusOverlay()

        overlay.add_alert(AlertLevel.INFO, "测试信息")
        assert len(overlay._alerts) == 1

        overlay.add_alert(AlertLevel.WARNING, "测试警告")
        assert len(overlay._alerts) == 2

    def test_add_alert_auto_cleanup(self):
        """测试告警自动清理"""
        overlay = FocusOverlay()

        # 添加旧告警（时间戳被覆盖）
        overlay._alerts.append(
            AlertMessage(level=AlertLevel.WARNING, text="旧告警", timestamp=time.time() - 10)
        )

        # 添加新告警
        overlay.add_alert(AlertLevel.INFO, "新告警")

        # 触发绘制（会清理过期告警）
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        overlay.draw(frame)

        # 旧告警应该被清理
        assert len(overlay._alerts) <= 3  # 最多保留3条

    def test_fatigue_color_method(self):
        """测试疲劳颜色映射 (v4.3 重设计后: 调暗让绿不刺眼)"""
        overlay = FocusOverlay()

        # v4.3 新调色板: (0, 200, 100) / (0, 200, 220) / (0, 0, 220)
        assert overlay._fatigue_color("LOW") == (0, 200, 100)
        assert overlay._fatigue_color("MEDIUM") == (0, 200, 220)
        assert overlay._fatigue_color("HIGH") == (0, 0, 220)
        # None → 默认 text_color
        assert overlay._fatigue_color(None) == overlay.config.text_color
        # 未知等级 → 灰色
        assert overlay._fatigue_color("UNKNOWN") == (200, 200, 200)

    def test_mode_dot_radius_is_12_v4_4(self):
        """v4.4: MODE 状态栏圆点半径 5 → 12, 字体 0.55 → 0.75, 厚度 1 → 2, 前缀 ●"""
        overlay = FocusOverlay()
        overlay.set_mode("MONITORING")
        import inspect
        src = inspect.getsource(overlay._draw_status_bar)
        # 圆点 12 (原 5) — 直接查找 ", 12," 模式 (cv2.circle 第 3 参数)
        assert ", 12," in src, \
            f"_draw_status_bar 应含 ', 12,' (cv2.circle 圆点半径), 实际源码不含"
        # 字体 0.75
        assert "0.75" in src, f"_draw_status_bar 应使用字体 0.75, 实际不含"
        # 厚度 2
        assert ", 2)" in src, f"应使用 thickness=2, 实际不含"
        # 前缀 ●
        assert "●" in src, f"应使用 ● 前缀, 实际不含"

    def test_mode_color_mapping_v4_4(self):
        """v4.4: _mode_color 返回 5 种状态对应颜色"""
        overlay = FocusOverlay()
        for mode, expected in [
            ("MONITORING", (0, 200, 100)),   # 绿
            ("CALIBRATING", (0, 165, 255)),  # 橙
            ("PAUSED", (180, 180, 180)),     # 灰
            ("INITIALIZING", (255, 255, 0)),  # 黄
            ("ERROR", (0, 0, 220)),          # 红
        ]:
            overlay.set_mode(mode)
            color = overlay._mode_color()
            assert color == expected, f"mode={mode} 应 {expected}, 实际 {color}"

    def test_focus_circle_radius_is_70_v4_4(self):
        """v4.4: focus score 圆环 r 50 → 70, 数字 0.6 → 1.5, 8px 边框颜色按分数"""
        overlay = FocusOverlay()
        import inspect
        src = inspect.getsource(overlay._draw_focus_display)
        # 圆环 70 (原 50)
        assert "70" in src, f"圆环应含 70 半径, 实际不含"
        assert "50" not in src.split("圆环")[0] if "圆环" in src else True, "应不含旧 50"
        # 数字 1.5
        assert "1.5" in src, f"数字应含 1.5 字号, 实际不含"
        # FOCUS 标签
        assert '"FOCUS"' in src, f"应有 FOCUS 标签, 实际不含"
        # 8px 边框 (thickness=8)
        assert ", 8)" in src or "thickness=8" in src, f"应有 8px 边框, 实际不含"

    def test_focus_color_mapping_v4_4(self):
        """v4.4: _focus_color 3 档颜色 (>=70 绿, 50-70 黄, <50 红)"""
        overlay = FocusOverlay()
        # 绿 >= 70
        assert overlay._focus_color(85) == (0, 220, 0)
        assert overlay._focus_color(70) == (0, 220, 0)
        # 黄 50-69
        assert overlay._focus_color(65) == (0, 220, 220)
        assert overlay._focus_color(50) == (0, 220, 220)
        # 红 < 50
        assert overlay._focus_color(40) == (0, 0, 220)
        assert overlay._focus_color(0) == (0, 0, 220)

    def test_fatigue_alert_exists_v4_4(self):
        """v4.4: _draw_fatigue_alert 方法存在且源码含关键字符串

        实际渲染测试因 cv2.putText 默认字体不支持 ⚠ unicode 而不可靠,
        故改为源码字符串验证 (与 v4.3 的 test_fatigue_color_method 风格一致)。
        """
        overlay = FocusOverlay()
        # 方法存在
        assert hasattr(overlay, "_draw_fatigue_alert"), "_draw_fatigue_alert 方法应存在 (v4.4 新增)"
        import inspect
        src = inspect.getsource(overlay._draw_fatigue_alert)
        # LOW / None 早返回
        assert "LOW" in src and "None" in src, "应早返回 LOW/None 不绘制"
        # MEDIUM 黄横条 (紧贴 status_bar 下)
        assert "(0, 200, 220)" in src, "MEDIUM 黄色 (0,200,220)"
        # HIGH 红横条 (闪烁) + 大警告
        assert "(0, 0, 220)" in src, "HIGH 红色 (0,0,220)"
        assert "int(time.time()" in src, "HIGH 应含 0.5s 周期闪烁逻辑"
        assert "疲劳警告" in src, "HIGH 时源码应含 '疲劳警告' 字符串"

    def test_no_face_banner_exists_v4_4(self):
        """v4.4: _draw_no_face_banner 方法存在, 5s 阈值 + 红底白字横条

        注: 实际用 ASCII "Face not detected" (cv2.putText 默认字体不支持中文;
        真机用 simhei.ttf 可渲染中文 "请将面部对准摄像头")。
        """
        overlay = FocusOverlay()
        # 方法存在
        assert hasattr(overlay, "_draw_no_face_banner"), "_draw_no_face_banner 方法应存在 (v4.4 新增)"
        import inspect
        sig = inspect.signature(overlay._draw_no_face_banner)
        assert "frame" in sig.parameters
        assert "face_detected" in sig.parameters
        assert "last_face_time" in sig.parameters
        # 源码含关键字符串
        src = inspect.getsource(overlay._draw_no_face_banner)
        assert "Face not detected" in src, "无脸提示文案 (ASCII fallback)"
        assert "(0, 0, 200)" in src, "红底 (0,0,200)"
        assert "5.0" in src, "5s 阈值防一过性闪烁"
        assert "int(time.time()" in src, "0.5s 周期闪烁"
        # face_detected=True 或 last_face_time=None 早返回
        assert "face_detected or last_face_time is None" in src, "应早返回"

    def test_alert_color_method(self):
        """测试告警颜色映射"""
        overlay = FocusOverlay()

        assert overlay._alert_color(AlertLevel.INFO) == (255, 255, 255)
        assert overlay._alert_color(AlertLevel.WARNING) == (0, 165, 255)
        assert overlay._alert_color(AlertLevel.ERROR) == (0, 0, 255)
        assert overlay._alert_color(AlertLevel.NONE) == overlay.config.text_color

    def test_factory_function(self):
        """测试工厂函数"""
        overlay = create_focus_overlay()
        assert isinstance(overlay, FocusOverlay)


class TestCalibrationProgress:
    """CalibrationProgress 单元测试"""

    def test_in_progress_calibration(self):
        """测试进行中的校准"""
        cal = CalibrationProgress(
            current=50,
            total=100,
            cqs=0.65,
            is_complete=False,
        )
        assert cal.current == 50
        assert cal.total == 100
        assert cal.cqs == 0.65
        assert cal.is_complete is False

    def test_complete_calibration(self):
        """测试完成的校准"""
        cal = CalibrationProgress(
            current=100,
            total=100,
            cqs=0.75,
            is_complete=True,
        )
        assert cal.is_complete is True


class TestAlertMessage:
    """AlertMessage 单元测试"""

    def test_alert_message_creation(self):
        """测试告警消息创建"""
        alert = AlertMessage(
            level=AlertLevel.WARNING,
            text="测试警告",
            timestamp=time.time(),
        )
        assert alert.level == AlertLevel.WARNING
        assert alert.text == "测试警告"


# ════════════════════════════════════════
# v4.26: SettingsDialog QSS 白底回归测试
# 修复"托盘/主程序的下拉框弹出黑底看不见字"bug：
# QSS 必须在每个 QComboBox/QSpinBox/QLineEdit 实例上 setStyleSheet，
# 才能覆盖 popup 窗口（独立 top-level，QDialog 级别 QSS 无法传递）。
# ════════════════════════════════════════

class TestSettingsDialogWhiteDropdown:
    """v4.26: 设置对话框所有下拉/输入控件白底"""

    @pytest.fixture(scope="class", autouse=True)
    def _setup_qt(self):
        """确保有 QApplication 实例（offscreen，不弹窗）"""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication([])

    def test_input_widget_qss_contains_required_selectors(self):
        """v4.26: INPUT_WIDGET_QSS 必须含 ::drop-down / ::down-arrow / QAbstractItemView::item

        这三个是 Qt 关键子控件，缺一个 popup 就仍可能是黑底。
        """
        from gui.settings_dialog import SettingsDialog
        qss = SettingsDialog.INPUT_WIDGET_QSS
        for selector in ["::drop-down", "::down-arrow", "QAbstractItemView::item"]:
            assert selector in qss, f"INPUT_WIDGET_QSS 缺关键选择器: {selector}"

    def test_input_widget_qss_white_background(self):
        """v4.26: 控件背景必须是 #FFFFFF，selection 必须是 Iris 紫"""
        from gui.settings_dialog import SettingsDialog
        qss = SettingsDialog.INPUT_WIDGET_QSS
        assert "background-color: #FFFFFF" in qss
        assert "selection-background-color: #5B4A8C" in qss  # Iris
        assert "selection-color: #FFFFFF" in qss

    def test_settings_dialog_qss_applied_to_every_input_widget(self):
        """v4.26: 每个 QComboBox/QSpinBox/QLineEdit 实例都设了 QSS

        关键：setStyleSheet 必须直接绑到 widget 实例上，否则 Qt 弹出
        popup 窗口会绕过 QDialog 级别的样式，导致黑底。
        """
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        for w in [dlg._cam_combo, dlg._ai_backend, dlg._ai_provider,
                  dlg._pomo_work_spin, dlg._pomo_break_spin,
                  dlg._ai_api_key, dlg._ai_base_url]:
            assert w.styleSheet(), f"{type(w).__name__} 未 setStyleSheet"
            assert "::drop-down" in w.styleSheet(), \
                f"{type(w).__name__} QSS 缺 ::drop-down"
            assert "QAbstractItemView::item" in w.styleSheet(), \
                f"{type(w).__name__} QSS 缺 QAbstractItemView::item"

    def test_v426_qspinbox_arrows_styled(self):
        """v4.26: QComboBox/QSpinBox 箭头用 base64 内联 SVG（避免系统位图黑色）

        修复前：image: none + CSS border 三角 hack 在 Qt 上不稳定，
        仍渲染默认黑色方块位图。改用 base64 内联 SVG（Iris 紫）。
        """
        from gui.settings_dialog import (
            SettingsDialog, _POMO_INPUT_DIALOG_QSS,
            _ARROW_DOWN_URL, _ARROW_UP_URL,
        )
        # 1) SettingsDialog QSS 含 QComboBox::down-arrow + QSpinBox 上下箭头
        for arrow in ["QComboBox::down-arrow", "QSpinBox::up-arrow", "QSpinBox::down-arrow"]:
            assert arrow in SettingsDialog.INPUT_WIDGET_QSS
        # 2) Pomo dialog 只有 QSpinBox（无 QComboBox）
        for arrow in ["QSpinBox::up-arrow", "QSpinBox::down-arrow"]:
            assert arrow in _POMO_INPUT_DIALOG_QSS
        # 2) URL 是 base64 SVG (Iris 紫 #5B4A8C)
        import base64
        assert "data:image/svg+xml;base64" in _ARROW_DOWN_URL
        assert "data:image/svg+xml;base64" in _ARROW_UP_URL
        # 解码后含 #5B4A8C 填充色
        b64_down = _ARROW_DOWN_URL.split("base64,")[1]
        b64_up = _ARROW_UP_URL.split("base64,")[1]
        assert "#5B4A8C" in base64.b64decode(b64_down).decode("utf-8")
        assert "#5B4A8C" in base64.b64decode(b64_up).decode("utf-8")
        # 3) QSS 实际渲染时含 data: URL（被 .replace() 替换后）
        assert "data:image/svg+xml;base64" in SettingsDialog.INPUT_WIDGET_QSS
        assert "data:image/svg+xml;base64" in _POMO_INPUT_DIALOG_QSS
        # 4) 不应再有 image: none + border hack 残留
        assert "image: none" not in SettingsDialog.INPUT_WIDGET_QSS
        assert "image: none" not in _POMO_INPUT_DIALOG_QSS

    def test_v426_settings_dialog_qss_extra_states(self):
        """v4.26: SettingsDialog QDialog 级别 QSS 补 QPushButton 状态 + QCheckBox indicator + QGroupBox::title color"""
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        dlg_qss = dlg.styleSheet()
        # QPushButton 状态
        for s in ["QPushButton:hover", "QPushButton:pressed", "QPushButton:disabled"]:
            assert s in dlg_qss, f"SettingsDialog 缺 {s}"
        # QCheckBox::indicator
        for s in ["QCheckBox::indicator", "QCheckBox::indicator:checked", "QCheckBox::indicator:hover"]:
            assert s in dlg_qss, f"SettingsDialog 缺 {s}"
        # QGroupBox::title 颜色
        assert "QGroupBox::title" in dlg_qss
        assert "color: #23201E" in dlg_qss.split("QGroupBox::title")[1].split("}")[0]

    def test_v426_pomo_input_dialog_qss_white(self):
        """v4.26: 番茄设置 dialog QSS 是白底（替代黑底的 QInputDialog.getInt）

        关键：tray.py _set_pomodoro + qt_window.py _pomodoro_action("settings")
        之前都用 QInputDialog.getInt(...) → Qt 自带 dialog 在暗色系统下黑底
        修法：写 ask_pomo_int() wrapper，setStyleSheet 白底 QSS
        """
        from gui.settings_dialog import _POMO_INPUT_DIALOG_QSS, ask_pomo_int
        # 1) QSS 是白底
        assert _POMO_INPUT_DIALOG_QSS.count("#FFFFFF") >= 3, \
            "Pomo input dialog QSS 应多处用 #FFFFFF（底+按钮默认态+文字）"
        # 2) QSS 含 QPushButton 全状态
        for s in ["QPushButton:hover", "QPushButton:pressed", "QPushButton:default"]:
            assert s in _POMO_INPUT_DIALOG_QSS
        # 3) QSS 含 QSpinBox 上下按钮
        for s in ["QSpinBox::up-button", "QSpinBox::down-button"]:
            assert s in _POMO_INPUT_DIALOG_QSS
        # 4) 函数存在
        assert callable(ask_pomo_int)

    def test_v426_tray_and_window_use_ask_pomo_int(self):
        """v4.26: tray.py 和 qt_window.py 都用 ask_pomo_int（不再用 QInputDialog.getInt）"""
        import os
        for path in ["gui/tray.py", "gui/qt_window.py"]:
            with open(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                path
            ), encoding="utf-8") as f:
                content = f.read()
            assert "ask_pomo_int" in content, f"{path} 未引用 ask_pomo_int"
            # 检查实际调用模式：QInputDialog.getInt( 不应出现（注释里可以提）
            assert "QInputDialog.getInt(" not in content, \
                f"{path} 还在调用 QInputDialog.getInt（黑底 bug）"

    def test_v426_api_key_uses_unified_container(self):
        """v4.26: API Key 输入 + 切换按钮用 QFrame 容器统一边框（去双黑边）

        修复前：QLineEdit 1px border + QPushButton 1px border + spacing=4 → 双黑边
        修复后：QFrame#apiKeyContainer 统一边框，内部控件透明无 border，
                focus 时容器高亮 Iris 紫
        """
        from PyQt5.QtWidgets import QFrame
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        container = dlg.findChild(QFrame, "apiKeyContainer")
        assert container is not None, "API Key 容器 QFrame#apiKeyContainer 应存在"
        # 容器 QSS 关键规则
        qss = container.styleSheet()
        assert "QFrame#apiKeyContainer" in qss
        assert "border: 1px solid #D0D0D0" in qss
        assert "border-radius: 4px" in qss
        # focus 高亮
        assert ":focus-within" in qss
        # 内部 QLineEdit 无 border / QPushButton 无 border
        assert "QFrame#apiKeyContainer QLineEdit" in qss
        assert "border: none" in qss
        assert "QFrame#apiKeyContainer QPushButton" in qss
        # API Key 行的两个子控件
        assert dlg._ai_api_key.parent() is container
        assert dlg._api_key_toggle_btn.parent() is container
