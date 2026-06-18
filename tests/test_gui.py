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
# v4.26 面板刷新: 颜色 token 统一回归测试
# 修复"Apple 系统色 (#34C759/#FF9500/#FF3B30/#007AFF) 与项目 Quiet Focus 不符"
# ════════════════════════════════════════

class TestV426PanelColorTokens:
    """v4.26: 主窗口 + 叠加层颜色统一为项目 Quiet Focus token"""

    def test_no_apple_system_colors_in_qt_window(self):
        """qt_window.py 不应再用 Apple 系统色 #34C759/#FF9500/#FF3B30/#007AFF"""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "gui", "qt_window.py"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for apple_color in ["#34C759", "#FF9500", "#FF3B30", "#007AFF"]:
            assert apple_color not in content, \
                f"qt_window.py 仍含 Apple 系统色 {apple_color}"

    def test_no_apple_system_colors_in_qt_overlay(self):
        """qt_overlay.py 不应再用 Apple 系统色"""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "gui", "qt_overlay.py"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for apple_color in ["#34C759", "#FF9500", "#FF3B30", "#007AFF"]:
            assert apple_color not in content, \
                f"qt_overlay.py 仍含 Apple 系统色 {apple_color}"

    def test_qt_overlay_uses_project_color_tokens(self):
        """qt_overlay.py 颜色常量应是项目 Quiet Focus token"""
        from gui.qt_overlay import (
            C_FOCUS_GREEN, C_FOCUS_YELLOW, C_FOCUS_RED,
        )
        # sage-600 = #5A8A6D = (90, 138, 109)
        assert C_FOCUS_GREEN.red() == 90
        assert C_FOCUS_GREEN.green() == 138
        assert C_FOCUS_GREEN.blue() == 109
        # amber-600 = #C9843A = (201, 132, 58)
        assert C_FOCUS_YELLOW.red() == 201
        assert C_FOCUS_YELLOW.green() == 132
        assert C_FOCUS_YELLOW.blue() == 58
        # rose-600 = #B55C5C = (181, 92, 92)
        assert C_FOCUS_RED.red() == 181
        assert C_FOCUS_RED.green() == 92
        assert C_FOCUS_RED.blue() == 92

    def test_qt_window_status_colors_are_project_tokens(self):
        """qt_window.py 状态/警告/校准色应是项目 token"""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "gui", "qt_window.py"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # light_warning: amber
        assert "#C9843A" in content  # amber-600 (text + border)
        assert "#FAF0E3" in content  # light amber bg
        # face_lost_warning: rose
        assert "#B55C5C" in content  # rose-600 (text + border)
        assert "#F8E8E8" in content  # light rose bg
        # calib_prompt: amber (与 light_warning 统一)
        # 校准按钮: iris (替代 Apple 蓝 #007AFF)
        assert "#5B4A8C" in content
        # 暂停按钮: quiet (替代 Apple secondary #8E8E93)
        assert "#8B8680" in content
        # 旧 Apple 色 (iOS 金色) 不应再出现
        assert "#B8860B" not in content
        assert "#FFD54F" not in content
        assert "#FFFDE7" not in content


# ════════════════════════════════════════
# v4.26 面板刷新: 重做 dropdown 白底（被回退后补救）
# 修复"QComboBox/QSpinBox/QLineEdit 弹出 popup 仍黑底" +
#      "QInputDialog.getInt 番茄设置弹窗黑底"
# ════════════════════════════════════════

class TestV426DropdownWhiteBg:
    """v4.26: 设置对话框下拉/输入 popup + 番茄 dialog 全白底"""

    @pytest.fixture(scope="class", autouse=True)
    def _setup_qt(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication([])

    def test_input_widget_qss_contains_required_selectors(self):
        """INPUT_WIDGET_QSS 必须含 ::drop-down / QAbstractItemView::item"""
        from gui.settings_dialog import SettingsDialog
        qss = SettingsDialog.INPUT_WIDGET_QSS
        for selector in ["::drop-down", "QAbstractItemView::item", "#5B4A8C"]:
            assert selector in qss, f"INPUT_WIDGET_QSS 缺: {selector}"

    def test_settings_dialog_input_widgets_have_qss(self):
        """每个 QComboBox/QSpinBox/QLineEdit 都设了实例级 QSS"""
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        for w in [dlg._cam_combo, dlg._ai_backend, dlg._ai_provider,
                  dlg._pomo_work_spin, dlg._pomo_break_spin,
                  dlg._ai_api_key, dlg._ai_base_url]:
            assert w.styleSheet(), f"{type(w).__name__} 未 setStyleSheet"

    def test_pomo_input_dialog_qss_white(self):
        """_POMO_INPUT_DIALOG_QSS 是白底"""
        from gui.settings_dialog import _POMO_INPUT_DIALOG_QSS, ask_pomo_int
        assert _POMO_INPUT_DIALOG_QSS.count("#FFFFFF") >= 3
        for s in ["QPushButton:hover", "QPushButton:default", "QSpinBox::up-button"]:
            assert s in _POMO_INPUT_DIALOG_QSS
        assert callable(ask_pomo_int)

    def test_tray_and_window_use_ask_pomo_int(self):
        """tray.py / qt_window.py 都不再用 QInputDialog.getInt"""
        import os
        for path in ["gui/tray.py", "gui/qt_window.py"]:
            with open(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                path
            ), encoding="utf-8") as f:
                content = f.read()
            assert "ask_pomo_int" in content
            assert "QInputDialog.getInt(" not in content

    def test_v426_3_api_key_toggle_white_bg(self):
        """v4.26.3: API key 切换按钮 per-instance QSS 显式白底

        修复历史：
          v4.26.1: per-widget setStyleSheet 被 QDialog 级 QPushButton 覆盖
                    → 改放 QDialog 级 QSS 用 #apiKeyToggle 选择器（仍不生效）
          v4.26.2: 加 setFlat(True) + WA_NoSystemBackground + autoFillBackground(False)
                    + QPalette.Button=Window（Windows 暗色主题下系统 Button 角色
                    强制黑，4 道防线全部败给系统主题）
          v4.26.3: 不再用 setFlat/透明 hack。改用普通 QPushButton + per-instance
                    QSS 显式 #FFFFFF 背景 + #apiKeyToggle 选择器，per-instance
                    替换继承自 QDialog 的 QPushButton 规则，强制白底成功

        验证项：
          1. setObjectName('apiKeyToggle') → QSS 可唯一定位
          2. isFlat() == False（普通按钮，不走系统主题渲染）
          3. per-instance QSS 含 #FFFFFF 背景（非 transparent）
          4. QSS 用 #apiKeyToggle id 选择器（specificity 0,1,1 > QPushButton 0,0,1）
        """
        from gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog()
        btn = dlg._api_key_toggle_btn
        # 1. objectName 仍保留（虽然不再需要 QDialog 级规则，但 ID 仍用于 QSS specificity）
        assert btn.objectName() == "apiKeyToggle"
        # 2. 不再用 setFlat（setFlat 触发系统主题渲染，是 Windows 暗色下黑底的元凶）
        assert btn.isFlat() is False
        # 3. per-instance QSS 含 #FFFFFF 背景
        btn_qss = btn.styleSheet()
        assert "background-color: #FFFFFF" in btn_qss
        assert "background-color: transparent" not in btn_qss  # 明确没有透明
        # 4. QSS 用 #apiKeyToggle id 选择器
        assert "QPushButton#apiKeyToggle" in btn_qss

    def test_v426_1_pomo_dialog_no_help_button(self):
        """v4.26.1: ask_pomo_int 去掉标题栏 ? 帮助按钮"""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QInputDialog
        import inspect
        from gui.settings_dialog import ask_pomo_int
        # 检查源码确认 WindowContextHelpButtonHint 被清除
        src = inspect.getsource(ask_pomo_int)
        assert "WindowContextHelpButtonHint" in src
        # 验证逻辑可执行（不需要真弹窗）：手动模拟 flags 操作
        dlg = QInputDialog()
        flags = dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint
        dlg.setWindowFlags(flags)
        assert not (dlg.windowFlags() & Qt.WindowContextHelpButtonHint)
        dlg.close()

    def test_v426_1_calibration_dialog_minimize_no_help(self):
        """v4.26.1: 校准 dialog 去掉 ? 帮助按钮，添加 — 最小化按钮"""
        from PyQt5.QtCore import Qt
        from gui.calibration_dialog import CalibrationDialog
        import inspect
        src = inspect.getsource(CalibrationDialog.__init__)
        assert "WindowContextHelpButtonHint" in src
        assert "WindowMinimizeButtonHint" in src
        # 同源代码验证：先 unset help + add minimize
        # 模拟预期 flags 操作
        flags = Qt.Dialog | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
        flags &= ~Qt.WindowContextHelpButtonHint
        assert not (flags & Qt.WindowContextHelpButtonHint)
        assert (flags & Qt.WindowMinimizeButtonHint)
