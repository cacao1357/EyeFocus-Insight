"""
gui/overlay.py — 实时 GUI 叠加层

在摄像头画面上叠加实时数据可视化：
- 专注度/疲劳状态显示
- 校准进度条
- 状态告警（光照/姿态异常）

使用 cv2.windowaffe 来实现窗口叠加，
支持半透明背景和实时更新。
"""

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("eyefocus.gui")


class AlertLevel(Enum):
    """告警级别"""
    NONE = "none"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class AlertMessage:
    """告警消息"""
    level: AlertLevel
    text: str
    timestamp: float


@dataclass
class CalibrationProgress:
    """校准进度"""
    current: int      # 当前帧数
    total: int        # 目标帧数
    cqs: float        # 当前 CQS 分数
    is_complete: bool


class FocusDisplayMode(Enum):
    """专注度显示模式"""
    CIRCULAR = "circular"    # 圆形进度条
    BAR = "bar"              # 水平进度条
    TEXT = "text"            # 仅文字


@dataclass
class OverlayConfig:
    """GUI 叠加配置"""
    window_name: str = "EyeFocus Insight"
    width: int = 640
    height: int = 480
    alpha: float = 0.85          # 叠加层透明度
    font: int = cv2.FONT_HERSHEY_SIMPLEX
    text_color: Tuple[int, int, int] = (255, 255, 255)
    focus_color: Tuple[int, int, int] = (0, 255, 0)
    fatigue_color: Tuple[int, int, int] = (0, 255, 255)
    alert_warning_color: Tuple[int, int, int] = (0, 165, 255)
    alert_error_color: Tuple[int, int, int] = (0, 0, 255)
    background_color: Tuple[int, int, int] = (40, 40, 40)


# ========== 校准 UI 相关 ==========

@dataclass
class CalibrationPhaseInfo:
    """校准阶段信息"""
    phase: int
    name: str
    instruction: str
    remaining: int = 0
    is_input_mode: bool = False
    round_num: int = 0
    total_rounds: int = 0
    detected_blinks: int = 0
    program_count: int = 0
    result: Optional['CalibrationResult'] = None
    input_buffer: str = ""  # 用户输入缓冲区显示


@dataclass
class CalibrationDisplayData:
    """校准显示数据"""
    is_calibrating: bool = False
    current_phase: Optional[CalibrationPhaseInfo] = None


class FocusOverlay:
    """实时专注度 GUI 叠加层

    使用方法：
        overlay = FocusOverlay()
        frame = overlay.draw(frame, focus_score=85.0, fatigue_level="LOW")
        cv2.imshow(overlay.config.window_name, frame)
    """

    def __init__(self, config: Optional[OverlayConfig] = None):
        """初始化 GUI 叠加层

        Args:
            config: GUI 配置，None 使用默认配置
        """
        self.config = config or OverlayConfig()
        self._alerts: list[AlertMessage] = []
        self._calibration: Optional[CalibrationProgress] = None
        self._calib_phase: Optional[CalibrationPhaseInfo] = None
        self._calib_display: Optional[CalibrationDisplayData] = None
        self._last_update: float = time.time()

    def draw(
        self,
        frame: np.ndarray,
        focus_score: Optional[float] = None,
        fatigue_level: Optional[str] = None,
        eye_detected: bool = True,
        face_detected: bool = True,
        light_condition: Optional[str] = None,
        calibration: Optional[CalibrationProgress] = None,
        eye_score: Optional[float] = None,
        head_score: Optional[float] = None,
        gaze_score: Optional[float] = None,
    ) -> np.ndarray:
        """在帧上绘制 GUI 叠加

        Args:
            frame: 原始摄像头帧
            focus_score: 专注度分数 (0-100)
            fatigue_level: 疲劳等级 ("LOW", "MEDIUM", "HIGH")
            eye_detected: 是否检测到眼睛
            face_detected: 是否检测到人脸
            light_condition: 光照条件
            calibration: 校准进度
            eye_score: 眼部专注度分量 (0-100)
            head_score: 头部姿态分量 (0-100)
            gaze_score: 视线方向分量 (0-100)

        Returns:
            叠加后的帧
        """
        if frame is None:
            return frame

        # 创建叠加层
        overlay = frame.copy()

        # 绘制状态栏
        overlay = self._draw_status_bar(
            overlay,
            focus_score=focus_score,
            fatigue_level=fatigue_level,
            eye_detected=eye_detected,
            face_detected=face_detected,
        )

        # 绘制专注度/疲劳显示
        if focus_score is not None:
            overlay = self._draw_focus_display(overlay, focus_score, fatigue_level)

        # 绘制细分分数
        if any(s is not None for s in [eye_score, head_score, gaze_score]):
            overlay = self._draw_score_breakdown(overlay, eye_score, head_score, gaze_score)

        # 绘制告警信息
        overlay = self._draw_alerts(overlay)

        # 绘制校准进度
        if calibration is not None:
            overlay = self._draw_calibration(overlay, calibration)

        # 绘制光照条件
        if light_condition is not None:
            overlay = self._draw_light_indicator(overlay, light_condition)

        # 绘制校准 UI
        if hasattr(self, '_calib_display') and self._calib_display and self._calib_display.is_calibrating:
            if self._calib_phase and self._calib_phase.result:
                frame = self._draw_calibration_result(frame)
            else:
                frame = self._draw_calibration_full(frame)

        # 混合原始帧和叠加层
        return cv2.addWeighted(overlay, self.config.alpha, frame, 1 - self.config.alpha, 0)

    def _draw_status_bar(
        self,
        frame: np.ndarray,
        focus_score: Optional[float],
        fatigue_level: Optional[str],
        eye_detected: bool,
        face_detected: bool,
    ) -> np.ndarray:
        """绘制顶部状态栏"""
        h, w = frame.shape[:2]
        bar_height = 40

        # 半透明背景
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, bar_height), (40, 40, 40), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

        # 状态图标
        status_x = 15
        y = 25

        # 人脸检测状态
        face_icon = "[✓]" if face_detected else "[✗]"
        face_color = (0, 255, 0) if face_detected else (0, 0, 255)
        cv2.putText(frame, f"Face: {face_icon}", (status_x, y),
                    self.config.font, 0.5, face_color, 1)
        status_x += 100

        # 眼睛检测状态
        eye_icon = "[✓]" if eye_detected else "[✗]"
        eye_color = (0, 255, 0) if eye_detected else (0, 0, 255)
        cv2.putText(frame, f"Eye: {eye_icon}", (status_x, y),
                    self.config.font, 0.5, eye_color, 1)
        status_x += 80

        # 专注度分数
        if focus_score is not None:
            cv2.putText(frame, f"FOCUS: {focus_score:.0f}", (status_x, y),
                        self.config.font, 0.5, self.config.focus_color, 1)
            status_x += 120

        # 疲劳等级
        if fatigue_level is not None:
            level_color = self._fatigue_color(fatigue_level)
            cv2.putText(frame, f"FATIGUE: {fatigue_level}", (status_x, y),
                        self.config.font, 0.5, level_color, 1)

        return frame

    def _draw_score_breakdown(
        self,
        frame: np.ndarray,
        eye_score: Optional[float],
        head_score: Optional[float],
        gaze_score: Optional[float],
    ) -> np.ndarray:
        """绘制细分分数（眼部/头部/视线）"""
        h, w = frame.shape[:2]

        # 左下角显示细分分数
        x = 10
        y = h - 20
        line_height = 20

        scores = [
            ("Eye", eye_score, (0, 255, 0)),
            ("Head", head_score, (255, 255, 0)),
            ("Gaze", gaze_score, (0, 255, 255)),
        ]

        for label, score, color in scores:
            text = f"{label}: "
            if score is not None:
                text += f"{score:.0f}"
                score_int = int(score)
                bar_len = max(3, score_int // 10)
                bar = "|" * bar_len + "-" * (10 - bar_len)
                text += f" [{bar}]"
            else:
                text += "N/A"

            cv2.putText(frame, text, (x, y), self.config.font, 0.4, color, 1)
            y -= line_height

        return frame

    def _draw_focus_display(
        self,
        frame: np.ndarray,
        focus_score: float,
        fatigue_level: Optional[str],
    ) -> np.ndarray:
        """绘制专注度/疲劳显示（右下角）"""
        h, w = frame.shape[:2]
        center_x = w - 80
        center_y = h - 120
        radius = 50

        # 绘制圆形背景
        overlay = frame.copy()
        cv2.circle(overlay, (center_x, center_y), radius, (40, 40, 40), -1)
        frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)

        # 绘制圆形进度条
        color = self._fatigue_color(fatigue_level) if fatigue_level else self.config.focus_color
        start_angle = -90
        end_angle = start_angle + int(3.6 * focus_score)
        cv2.ellipse(frame, (center_x, center_y), (radius - 5, radius - 5),
                    0, start_angle, end_angle, color, 8)

        # 绘制中心分数
        cv2.putText(frame, f"{focus_score:.0f}",
                    (center_x - 25, center_y + 8),
                    self.config.font, 0.8, self.config.text_color, 2)

        # 绘制疲劳等级标签
        if fatigue_level:
            label = f"{fatigue_level}"
            cv2.putText(frame, label,
                        (center_x - 30, center_y + radius + 25),
                        self.config.font, 0.5, color, 1)

        return frame

    def _draw_calibration(
        self,
        frame: np.ndarray,
        calibration: CalibrationProgress,
    ) -> np.ndarray:
        """绘制校准进度条"""
        h, w = frame.shape[:2]
        bar_width = 300
        bar_height = 30
        bar_x = (w - bar_width) // 2
        bar_y = h - 80

        # 背景
        overlay = frame.copy()
        cv2.rectangle(overlay, (bar_x - 5, bar_y - 5),
                      (bar_x + bar_width + 5, bar_y + bar_height + 5),
                      (40, 40, 40), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

        # 进度条
        progress = min(1.0, calibration.current / max(1, calibration.total))
        filled_width = int(bar_width * progress)
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + filled_width, bar_y + bar_height),
                      (0, 200, 0), -1)

        # 边框
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + bar_width, bar_y + bar_height),
                      (255, 255, 255), 2)

        # 文字
        status = "校准完成!" if calibration.is_complete else f"校准中... {calibration.current}/{calibration.total}"
        cv2.putText(frame, status, (bar_x + 10, bar_y + 22),
                    self.config.font, 0.6, self.config.text_color, 1)

        # CQS 分数
        cv2.putText(frame, f"CQS: {calibration.cqs:.2f}",
                    (bar_x + bar_width - 80, bar_y + 22),
                    self.config.font, 0.5, (0, 255, 0), 1)

        return frame

    def _draw_alerts(self, frame: np.ndarray) -> np.ndarray:
        """绘制告警消息"""
        if not self._alerts:
            return frame

        h, w = frame.shape[:2]
        y = 60

        for alert in self._alerts[-3:]:  # 最多显示3条
            color = self._alert_color(alert.level)
            cv2.putText(frame, f"[{alert.level.value.upper()}] {alert.text}",
                        (15, y), self.config.font, 0.5, color, 1)
            y += 25

        # 清理过期告警（超过5秒）
        now = time.time()
        self._alerts = [a for a in self._alerts if now - a.timestamp < 5.0]

        return frame

    def _draw_light_indicator(
        self,
        frame: np.ndarray,
        light_condition: str,
    ) -> np.ndarray:
        """绘制光照条件指示器"""
        h, w = frame.shape[:2]

        # 右上角光照指示
        x = w - 120
        y = 30

        color = (0, 255, 0) if light_condition == "NORMAL" else (0, 165, 255)
        text = f"光: {light_condition}"
        cv2.putText(frame, text, (x, y), self.config.font, 0.45, color, 1)

        return frame

    def add_alert(self, level: AlertLevel, text: str) -> None:
        """添加告警消息

        Args:
            level: 告警级别
            text: 告警文本
        """
        self._alerts.append(AlertMessage(level=level, text=text, timestamp=time.time()))
        logger.debug("添加告警: [%s] %s", level.value, text)

    def _fatigue_color(self, fatigue_level: Optional[str]) -> Tuple[int, int, int]:
        """获取疲劳等级对应颜色"""
        if fatigue_level is None:
            return self.config.text_color
        level = fatigue_level.upper()
        if level == "LOW":
            return (0, 255, 0)      # 绿色
        elif level == "MEDIUM":
            return (0, 255, 255)   # 黄色
        elif level == "HIGH":
            return (0, 0, 255)     # 红色
        return self.config.text_color

    def _alert_color(self, level: AlertLevel) -> Tuple[int, int, int]:
        """获取告警级别对应颜色"""
        if level == AlertLevel.INFO:
            return (255, 255, 255)
        elif level == AlertLevel.WARNING:
            return self.config.alert_warning_color
        elif level == AlertLevel.ERROR:
            return self.config.alert_error_color
        return self.config.text_color

    def show_calibration_phase(self, phase: int, phase_name: str, instruction: str) -> None:
        """显示校准阶段信息"""
        self._calib_phase = CalibrationPhaseInfo(
            phase=phase,
            name=phase_name,
            instruction=instruction,
        )
        self._calib_display = CalibrationDisplayData(
            is_calibrating=True,
            current_phase=self._calib_phase,
        )

    def update_calibration_countdown(self, remaining: int) -> None:
        """更新校准倒计时"""
        if self._calib_phase:
            self._calib_phase.remaining = remaining

    def show_phase_complete(self, phase: int) -> None:
        """显示阶段完成"""
        pass

    def show_blink_round(self, round_num: int, total: int, duration: int) -> None:
        """显示眨眼校准轮开始"""
        if self._calib_phase:
            self._calib_phase.round_num = round_num
            self._calib_phase.total_rounds = total
            self._calib_phase.remaining = duration
            self._calib_phase.is_input_mode = False

    def update_blink_round(self, remaining: int, detected_blinks: int) -> None:
        """更新眨眼校准轮状态"""
        if self._calib_phase:
            self._calib_phase.remaining = remaining
            self._calib_phase.detected_blinks = detected_blinks

    def show_blink_input(self, round_num: int, program_count: int) -> None:
        """显示眨眼输入框"""
        if self._calib_phase:
            self._calib_phase.round_num = round_num
            self._calib_phase.program_count = program_count
            self._calib_phase.is_input_mode = True
            self._calib_phase.input_buffer = ""  # 重置输入缓冲区显示

    def update_input_buffer(self, buffer: str) -> None:
        """更新输入缓冲区显示"""
        if self._calib_phase:
            self._calib_phase.input_buffer = buffer

    def show_calibration_result(self, result: 'CalibrationResult') -> None:
        """显示校准结果"""
        if self._calib_phase:
            self._calib_phase.result = result
            self._calib_phase.is_input_mode = False

    def hide_calibration_ui(self) -> None:
        """隐藏校准 UI"""
        self._calib_display = CalibrationDisplayData(is_calibrating=False)
        self._calib_phase = None

    def _draw_calibration_full(self, frame: np.ndarray) -> np.ndarray:
        """绘制完整校准 UI"""
        if not self._calib_display or not self._calib_display.is_calibrating:
            return frame

        h, w = frame.shape[:2]
        phase = self._calib_phase
        if not phase:
            return frame

        panel_w = 400
        panel_h = 250
        panel_x = (w - panel_w) // 2
        panel_y = (h - panel_h) // 2

        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x - 10, panel_y - 10),
                       (panel_x + panel_w + 10, panel_y + panel_h + 10),
                       (20, 20, 20), -1)
        frame = cv2.addWeighted(overlay, 0.8, frame, 0.2, 0)

        phase_text = f"[阶段 {phase.phase + 1}/6] {phase.name}"
        cv2.putText(frame, phase_text,
                    (panel_x + 20, panel_y + 35),
                    self.config.font, 0.7, (255, 255, 255), 2)

        cv2.putText(frame, phase.instruction,
                    (panel_x + 20, panel_y + 70),
                    self.config.font, 0.5, (200, 200, 200), 1)

        if not phase.is_input_mode:
            countdown_text = f"剩余: {phase.remaining} 秒"
            cv2.putText(frame, countdown_text,
                        (panel_x + 20, panel_y + 110),
                        self.config.font, 0.6, (0, 255, 0), 2)

        if phase.round_num > 0:
            round_text = f"眨眼计数: 第 {phase.round_num}/{phase.total_rounds} 轮"
            cv2.putText(frame, round_text,
                        (panel_x + 20, panel_y + 145),
                        self.config.font, 0.5, (255, 255, 0), 1)

            detected_text = f"检测到: {phase.detected_blinks} 次眨眼"
            cv2.putText(frame, detected_text,
                        (panel_x + 20, panel_y + 170),
                        self.config.font, 0.5, (0, 255, 255), 1)

        if phase.is_input_mode:
            input_text = f"请输入您的眨眼次数（程序检测到 {phase.program_count} 次）"
            cv2.putText(frame, input_text,
                        (panel_x + 20, panel_y + 145),
                        self.config.font, 0.5, (255, 200, 0), 1)

            # 显示用户输入
            if phase.input_buffer:
                buffer_text = f"您输入: {phase.input_buffer}"
                cv2.putText(frame, buffer_text,
                            (panel_x + 20, panel_y + 170),
                            self.config.font, 0.6, (0, 255, 255), 2)

            hint_text = "按数字键输入，按 Enter 确认"
            cv2.putText(frame, hint_text,
                        (panel_x + 20, panel_y + 200),
                        self.config.font, 0.4, (150, 150, 150), 1)

        cv2.putText(frame, "按 ESC 取消校准",
                    (panel_x + 20, panel_y + panel_h - 20),
                    self.config.font, 0.4, (100, 100, 100), 1)

        return frame

    def _draw_calibration_result(self, frame: np.ndarray) -> np.ndarray:
        """绘制校准结果"""
        if not self._calib_phase or not self._calib_phase.result:
            return frame

        h, w = frame.shape[:2]
        result = self._calib_phase.result

        panel_w = 450
        panel_h = 200
        panel_x = (w - panel_w) // 2
        panel_y = (h - panel_h) // 2

        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x - 10, panel_y - 10),
                       (panel_x + panel_w + 10, panel_y + panel_h + 10),
                       (30, 30, 30), -1)
        frame = cv2.addWeighted(overlay, 0.85, frame, 0.15, 0)

        cv2.putText(frame, "校准完成",
                    (panel_x + 20, panel_y + 35),
                    self.config.font, 0.8, (0, 255, 0), 2)

        ear_text = f"EAR 基线: {result.signal.ear_mean:.4f}"
        cv2.putText(frame, ear_text,
                    (panel_x + 20, panel_y + 75),
                    self.config.font, 0.5, (255, 255, 255), 1)

        threshold_text = f"眨眼阈值: {result.final_blink_threshold:.4f}"
        cv2.putText(frame, threshold_text,
                    (panel_x + 20, panel_y + 100),
                    self.config.font, 0.5, (255, 255, 255), 1)

        adj_text = f"调整因子: {result.final_adjustment_factor:.3f}"
        cv2.putText(frame, adj_text,
                    (panel_x + 20, panel_y + 125),
                    self.config.font, 0.5, (255, 255, 255), 1)

        cv2.putText(frame, "按 Enter 开始检测",
                    (panel_x + 20, panel_y + 170),
                    self.config.font, 0.5, (0, 255, 0), 1)

        return frame

    def show_window(self) -> None:
        """创建窗口"""
        cv2.namedWindow(self.config.window_name, cv2.WINDOW_NORMAL)

    def destroy_window(self) -> None:
        """销毁窗口"""
        cv2.destroyWindow(self.config.window_name)


def create_focus_overlay(config: Optional[OverlayConfig] = None) -> FocusOverlay:
    """工厂函数：创建 GUI 叠加层"""
    return FocusOverlay(config)
