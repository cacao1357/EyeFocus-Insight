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
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("eyefocus.gui")

# L-15: cv2 颜色常量 (BGR) 集中到模块顶部, 避免散落魔法数
COLOR_WHITE: Tuple[int, int, int] = (255, 255, 255)  # 纯白
COLOR_BLACK: Tuple[int, int, int] = (0, 0, 0)        # 纯黑
COLOR_GREEN: Tuple[int, int, int] = (0, 255, 0)      # 绿 (正常/检测成功)
COLOR_RED: Tuple[int, int, int] = (0, 0, 255)        # 红 (警告/未检测)
COLOR_YELLOW: Tuple[int, int, int] = (0, 255, 255)   # 黄 (MEDIUM 疲劳)
COLOR_CYAN: Tuple[int, int, int] = (255, 255, 0)     # 青 (细分: Head)
COLOR_ORANGE: Tuple[int, int, int] = (0, 165, 255)   # 橙 (WARNING 告警)
COLOR_DARK_BG: Tuple[int, int, int] = (40, 40, 40)   # 半透明状态栏背景
COLOR_PANEL_BG: Tuple[int, int, int] = (15, 15, 15)  # 校准面板背景
COLOR_BORDER_GREEN: Tuple[int, int, int] = (0, 200, 100)  # 边框绿
COLOR_PROGRESS_GREEN: Tuple[int, int, int] = (0, 200, 0)  # 进度条绿
COLOR_TEXT_LIGHT: Tuple[int, int, int] = (220, 220, 220)  # 次要文字
COLOR_TEXT_MUTED: Tuple[int, int, int] = (180, 180, 180)  # 提示文字
COLOR_TEXT_DIM: Tuple[int, int, int] = (100, 100, 100)    # 弱化文字
COLOR_AMBER: Tuple[int, int, int] = (255, 200, 0)         # 琥珀 (输入提示)
COLOR_RESULT_TEXT: Tuple[int, int, int] = (150, 150, 150) # 结果页脚

# 默认中文字体路径（Windows 系统字体）
DEFAULT_FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
# 尝试加载中文字体
try:
    _chinese_font = ImageFont.truetype(DEFAULT_FONT_PATH, 20)
    _chinese_font_small = ImageFont.truetype(DEFAULT_FONT_PATH, 16)
    _chinese_font_large = ImageFont.truetype(DEFAULT_FONT_PATH, 28)
except Exception:
    _chinese_font = None
    _chinese_font_small = None
    _chinese_font_large = None
    logger.warning("无法加载中文字体，中文可能显示为方块")


def put_chinese_text(img: np.ndarray, text: str, position: Tuple[int, int],
                     font: ImageFont.FreeTypeFont = None, color: Tuple[int, int, int] = COLOR_WHITE) -> np.ndarray:
    """在图像上绘制中文文本（使用 PIL）

    Args:
        img: OpenCV 图像 (BGR)
        text: 文本内容
        position: (x, y) 位置
        font: PIL 字体对象
        color: BGR 颜色

    Returns:
        绘制后的图像
    """
    if _chinese_font is None:
        return img  # 无字体支持时返回原图

    font_obj = font or _chinese_font

    # 转换为 PIL 图像
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    # 绘制文本
    draw.text(position, text, font=font_obj, fill=color[::-1])  # PIL 使用 RGB

    # 转换回 OpenCV 图像
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


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
    """GUI 叠加配置

    v4.3 重设计:
      - show_score_breakdown (默认 False): 控制左下角 3 行 Eye/Head/Gaze 细分显示
        关闭后只剩 1 行 Eye 分数 (主分数 = 综合 focus)
      - show_fps (默认 True): 右下角 FPS 显示
      - status_bar_height: 60 (原 40, 容纳 4 段信息)
    """
    window_name: str = "EyeFocus Insight"
    width: int = 640
    height: int = 480
    alpha: float = 0.85          # 叠加层透明度
    font: int = cv2.FONT_HERSHEY_SIMPLEX
    text_color: Tuple[int, int, int] = COLOR_WHITE
    focus_color: Tuple[int, int, int] = (0, 255, 0)
    fatigue_color: Tuple[int, int, int] = (0, 255, 255)
    alert_warning_color: Tuple[int, int, int] = (0, 165, 255)
    alert_error_color: Tuple[int, int, int] = (0, 0, 255)
    background_color: Tuple[int, int, int] = (40, 40, 40)
    # v4.3 新增配置
    show_score_breakdown: bool = False  # 默认关, 减少信息过载
    show_fps: bool = True
    status_bar_height: int = 60  # 容纳 MODE + face/eye + focus + fatigue + glasses
    # v4.4: 极简模式 (默认开启), Tab 键切换
    minimal_mode: bool = True


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
        # v4.3: 顶层 MODE 状态 (MONITORING / CALIBRATING / PAUSED)
        self._current_mode: str = "INITIALIZING"

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
        glasses_str: Optional[str] = None,
        fps: Optional[float] = None,
        last_face_time: Optional[float] = None,  # v4.4: 无脸横幅 (BUG-1 修复)
    ) -> np.ndarray:
        """在帧上绘制 GUI 叠加

        v4.3 重设计: 顶部单行 4 段状态栏 (MODE + face/eye + FOCUS + FATIGUE + GLASSES),
        移除左下 3 行细分分数 (默认关, 需 config.show_score_breakdown=True),
        FPS 移右下角避免与状态栏重叠, glasses 合并入状态栏。
        v4.4: 末尾调 _draw_no_face_banner, 5s+ 无脸 → 红底白字横条闪烁。

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
            glasses_str: 眼镜状态字符串 (e.g. "ON" / "OFF")
            fps: 帧率, 显式传入而非 main.py 单独 putText
            last_face_time: 最后一次检测到人脸的时间戳 (v4.4 no-face banner)

        Returns:
            叠加后的帧
        """
        if frame is None:
            return frame

        # v4.4: 极简模式 (Tab切换, 默认开启) — 居中大数字 + 底部疲劳条
        if self.config.minimal_mode and self._current_mode != "CALIBRATING":
            result = self._draw_minimal_layout(
                frame, focus_score, fatigue_level, face_detected, eye_detected,
            )
            # 极简模式下也画无脸横幅
            if last_face_time is not None:
                result = self._draw_no_face_banner(result, face_detected, last_face_time)
            return result

        # 创建叠加层 (完整模式, 沿用 v4.3 布局)
        overlay = frame.copy()

        # 绘制状态栏 (含 glasses)
        overlay = self._draw_status_bar(
            overlay,
            focus_score=focus_score,
            fatigue_level=fatigue_level,
            eye_detected=eye_detected,
            face_detected=face_detected,
            glasses_str=glasses_str,
        )

        # 绘制专注度/疲劳显示 (右下大圆)
        if focus_score is not None:
            overlay = self._draw_focus_display(overlay, focus_score, fatigue_level)

        # 绘制细分分数 (v4.3 默认关, 需 config.show_score_breakdown=True)
        if self.config.show_score_breakdown and any(s is not None for s in [eye_score, head_score, gaze_score]):
            overlay = self._draw_score_breakdown(overlay, eye_score, head_score, gaze_score)

        # 绘制告警信息
        overlay = self._draw_alerts(overlay)

        # 绘制校准进度
        if calibration is not None:
            overlay = self._draw_calibration(overlay, calibration)

        # 绘制光照条件
        if light_condition is not None:
            overlay = self._draw_light_indicator(overlay, light_condition)

        # 绘制校准 UI（v3.x 路径，v4.2 走自己的 CalibrationFlow 面板）
        if hasattr(self, '_calib_display') and self._calib_display and self._calib_display.is_calibrating:
            if self._calib_phase and self._calib_phase.result:
                overlay = self._draw_calibration_result(overlay)
            else:
                overlay = self._draw_calibration_full(overlay)

        # 混合原始帧和叠加层
        result = cv2.addWeighted(overlay, self.config.alpha, frame, 1 - self.config.alpha, 0)

        # v4.3: FPS 移右下角 (避免与状态栏重叠), 由 main.py 显式传入 fps
        if self.config.show_fps and fps is not None:
            h, w = result.shape[:2]
            fps_text = f"FPS {fps:.0f}"
            (tw, th), _ = cv2.getTextSize(fps_text, self.config.font, 0.45, 1)
            cv2.putText(result, fps_text, (w - tw - 12, h - 12),
                        self.config.font, 0.45, COLOR_TEXT_MUTED, 1)

        # v4.4: 无脸横幅 (5s+ 倒计时 + 闪烁) — BUG-1 真机测试发现
        if last_face_time is not None:
            result = self._draw_no_face_banner(result, face_detected, last_face_time)

        return result

    def set_mode(self, mode: str) -> None:
        """设置顶层 MODE 状态, 用于状态栏指示器

        Args:
            mode: "MONITORING" / "CALIBRATING" / "PAUSED" / "INITIALIZING" / "ERROR"
        """
        valid = ("MONITORING", "CALIBRATING", "PAUSED", "INITIALIZING", "ERROR")
        if mode not in valid:
            logger.warning("set_mode: 未知 mode '%s', 用 'INITIALIZING' 兜底", mode)
            mode = "INITIALIZING"
        self._current_mode = mode

    # v4.4: Tab键切换极简/完整模式
    def toggle_mode(self) -> None:
        """切换极简/完整模式"""
        self.config.minimal_mode = not self.config.minimal_mode

    def _draw_status_bar(
        self,
        frame: np.ndarray,
        focus_score: Optional[float],
        fatigue_level: Optional[str],
        eye_detected: bool,
        face_detected: bool,
        glasses_str: Optional[str] = None,
    ) -> np.ndarray:
        """v4.3 重设计: 顶部单行 4 段状态栏 (避免重叠)

        4 段布局 (640 宽窗口):
          [左 0-220]   MODE 指示器 + Face + Eye
          [中左 220-380] FOCUS 分数
          [中右 380-540] FATIGUE 等级
          [右 540-640]  Glasses 状态
        """
        h, w = frame.shape[:2]
        bar_height = self.config.status_bar_height  # 60

        # v4.26: ROI 局部 blend 替代全帧 copy+addWeighted
        roi = frame[0:bar_height, :]
        bg = np.full_like(roi, self.config.background_color)
        frame[0:bar_height, :] = cv2.addWeighted(bg, 0.75, roi, 0.25, 0)
        # 底部细线分隔
        cv2.line(frame, (0, bar_height), (w, bar_height), (80, 80, 80), 1)

        y_main = 28        # 主文字基线
        y_indicator = 48   # MODE 指示器副文字 (颜色提示)
        # v4.4: 字体 0.55 → 0.75, 厚度 1 → 2, 让 MODE 一眼看清
        font_main = 0.75
        thickness = 2
        text_color = self.config.text_color
        muted_color = COLOR_TEXT_MUTED

        # === Zone 1: 左 0-220 (MODE + Face + Eye) ===
        x = 12
        # MODE 指示器 (圆点 + 文字) — v4.4: 圆点 5 → 12, 字体 0.75 粗体, ● 前缀
        mode_color = self._mode_color()
        cv2.circle(frame, (x + 6, y_main - 5), 12, mode_color, -1)
        cv2.putText(frame, f"●{self._current_mode}", (x + 25, y_main),
                    self.config.font, font_main, mode_color, thickness)
        x += 25 + len(f"●{self._current_mode}") * 11 + 15

        # Face / Eye 图标 (小)
        face_icon = "Face" + ("✓" if face_detected else "✗")
        face_color = (0, 200, 0) if face_detected else (0, 0, 220)
        cv2.putText(frame, face_icon, (x, y_main),
                    self.config.font, 0.45, face_color, 1)
        x += len(face_icon) * 8 + 10

        eye_icon = "Eye" + ("✓" if eye_detected else "✗")
        eye_color = (0, 200, 0) if eye_detected else (0, 0, 220)
        cv2.putText(frame, eye_icon, (x, y_main),
                    self.config.font, 0.45, eye_color, 1)

        # === Zone 2: 中左 FOCUS ===
        if focus_score is not None:
            focus_text = f"FOCUS  {focus_score:.0f}"
            focus_color = self._focus_color(focus_score)
            x_focus = 240
            cv2.putText(frame, focus_text, (x_focus, y_main),
                        self.config.font, 0.6, focus_color, 2)

        # === Zone 3: 中右 FATIGUE ===
        if fatigue_level is not None:
            fatigue_text = f"FATIGUE  {fatigue_level}"
            fatigue_color = self._fatigue_color(fatigue_level)
            x_fatigue = 380
            cv2.putText(frame, fatigue_text, (x_fatigue, y_main),
                        self.config.font, 0.55, fatigue_color, 2)

        # === Zone 4: 右 Glasses ===
        if glasses_str:
            glasses_text = f"👓 {glasses_str}"
            # 用 putText 不能直接画 emoji, 用 ASCII 替代
            glasses_text = f"GLASSES  {glasses_str}"
            glasses_color = muted_color
            # 右对齐: 距右边 12px
            (tw, th), _ = cv2.getTextSize(glasses_text, self.config.font, 0.45, 1)
            x_glasses = w - tw - 12
            cv2.putText(frame, glasses_text, (x_glasses, y_main),
                        self.config.font, 0.45, glasses_color, 1)

        return frame

    def _mode_color(self) -> Tuple[int, int, int]:
        """MODE 状态对应颜色 (BGR)"""
        return {
            "MONITORING": (0, 200, 100),    # 绿
            "CALIBRATING": (0, 165, 255),   # 橙
            "PAUSED": (180, 180, 180),       # 灰
            "INITIALIZING": (255, 255, 0),   # 黄
            "ERROR": (0, 0, 220),            # 红
        }.get(self._current_mode, (200, 200, 200))

    # ========== v4.4 极简模式 (Tab切换, 默认) ==========

    def _draw_minimal_layout(
        self,
        frame: np.ndarray,
        focus_score: Optional[float],
        fatigue_level: Optional[str],
        face_detected: bool,
        eye_detected: bool,
    ) -> np.ndarray:
        """极简模式: 居中大号专注度数字 + 底部疲劳条 + 右下状态"""
        h, w = frame.shape[:2]
        result = frame.copy()

        # 居中大号专注度数字
        if focus_score is not None:
            score_text = f"{focus_score:.0f}"
            label_text = "FOCUS"
            # 分数 (font 3.0, 大号)
            (tw, th), _ = cv2.getTextSize(score_text, self.config.font, 3.0, 4)
            cx = (w - tw) // 2
            cy = h // 2 - 30
            # 阴影
            cv2.putText(result, score_text, (cx + 2, cy + 2),
                        self.config.font, 3.0, (0, 0, 0), 4)
            # 主数字 (颜色按分数)
            score_color = self._focus_color(focus_score)
            cv2.putText(result, score_text, (cx, cy),
                        self.config.font, 3.0, score_color, 4)
            # FOCUS 标签
            (lw, lh), _ = cv2.getTextSize(label_text, self.config.font, 0.5, 1)
            cv2.putText(result, label_text, ((w - lw) // 2, cy - 15),
                        self.config.font, 0.5, COLOR_TEXT_MUTED, 1)

        # 底部疲劳横条 (全宽)
        if fatigue_level is not None:
            bar_y = h - 50
            bar_h = 16
            bar_color = self._fatigue_color(fatigue_level)
            # 背景条 (灰)
            cv2.rectangle(result, (0, bar_y), (w, bar_y + bar_h), (40, 40, 40), -1)
            # 填充条 (按等级比例)
            ratios = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 1.0}
            fill = ratios.get(fatigue_level, 0.3)
            cv2.rectangle(result, (0, bar_y), (int(w * fill), bar_y + bar_h), bar_color, -1)
            # 边框
            cv2.rectangle(result, (0, bar_y), (w, bar_y + bar_h), (80, 80, 80), 1)
            # 文字
            cv2.putText(result, f"FATIGUE {fatigue_level}", (12, bar_y - 6),
                        self.config.font, 0.45, bar_color, 1)

        # 右下人脸/眼睛状态
        status_parts = []
        status_parts.append(f"Face {'✓' if face_detected else '✗'}")
        status_parts.append(f"Eyes {'✓' if eye_detected else '✗'}")
        status_text = "  ".join(status_parts)
        (sw, sh), _ = cv2.getTextSize(status_text, self.config.font, 0.45, 1)
        cv2.putText(result, status_text, (w - sw - 12, h - 16),
                    self.config.font, 0.45, COLOR_TEXT_MUTED, 1)

        return result

    def _focus_color(self, score: float) -> Tuple[int, int, int]:
        """FOCUS 分数对应颜色 (绿 > 70, 黄 50-70, 红 < 50)"""
        if score >= 70:
            return (0, 220, 0)     # 绿 (专注)
        if score >= 50:
            return (0, 220, 220)   # 黄 (中等)
        return (0, 0, 220)         # 红 (走神)

    def _fatigue_color(self, level) -> Tuple[int, int, int]:
        """FATIGUE 等级对应颜色 (BGR)"""
        if level is None:
            return self.config.text_color
        return {
            "LOW": (0, 200, 100),
            "MEDIUM": (0, 200, 220),
            "HIGH": (0, 0, 220),
        }.get(level, (200, 200, 200))

    def _draw_fatigue_alert(self, frame: np.ndarray, fatigue_level: Optional[str]) -> np.ndarray:
        """v4.4: fatigue 切档醒目提示

        Args:
            frame: 当前帧
            fatigue_level: "LOW" / "MEDIUM" / "HIGH" / None

        Returns:
            绘制后的帧
        """
        if fatigue_level is None or fatigue_level == "LOW":
            return frame
        h, w = frame.shape[:2]
        bar_y = self.config.status_bar_height  # 60, 紧贴状态栏下方
        if fatigue_level == "MEDIUM":
            # 4px 黄色横条 (0, 200, 220)
            cv2.rectangle(frame, (0, bar_y), (w, bar_y + 4), (0, 200, 220), -1)
        elif fatigue_level == "HIGH":
            # 8px 红色横条, 0.5s 周期闪烁
            if int(time.time() * 2) % 2 == 0:
                cv2.rectangle(frame, (0, bar_y), (w, bar_y + 8), (0, 0, 220), -1)
            # 居中大警告
            warn_text = "⚠ 疲劳警告 ⚠"
            (tw, th), _ = cv2.getTextSize(warn_text, self.config.font, 1.2, 3)
            cv2.putText(frame, warn_text, ((w - tw) // 2, h // 2),
                        self.config.font, 1.2, (0, 0, 255), 3)
        return frame

    def _draw_no_face_banner(
        self,
        frame: np.ndarray,
        face_detected: bool,
        last_face_time: Optional[float],
    ) -> np.ndarray:
        """v4.4: 无脸检测红底白字横条 (5s+ 倒计时 + 闪烁)

        Args:
            frame: 当前帧
            face_detected: 本帧是否检测到人脸
            last_face_time: 最后一次检测到人脸的时间戳 (None 表示从未检测到)
        """
        if face_detected or last_face_time is None:
            return frame
        # 5s 阈值, 避免启动时一过性闪烁
        if time.time() - last_face_time < 5.0:
            return frame

        lost_sec = int(time.time() - last_face_time)
        h, w = frame.shape[:2]
        # 用 ASCII 替代中文 (cv2.putText 默认字体不支持中文; 真机用 simhei.ttf)
        text = f"Face not detected ({lost_sec}s)"
        (tw, th), _ = cv2.getTextSize(text, self.config.font, 1.2, 3)
        bar_w = tw + 40
        bar_h = th + 30
        bar_x = (w - bar_w) // 2
        bar_y = h // 2 - bar_h // 2
        # 0.5s 周期闪烁
        if int(time.time() * 2) % 2 == 0:
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (0, 0, 200), -1)
        cv2.putText(frame, text, (bar_x + 20, bar_y + th + 15),
                    self.config.font, 1.2, COLOR_WHITE, 3)
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
        """v4.4: 绘制专注度/疲劳显示（右下角）

        圆环 r=70 (原 50), 数字 1.5x 字号 (原 0.8), 8px 边框颜色按分数。
        """
        h, w = frame.shape[:2]
        # v4.4: 圆环 r 50 → 70 (1.4x)
        center_x = w - 90
        center_y = h - 130
        radius = 70

        # v4.26: ROI 局部 blend 替代全帧 copy+addWeighted
        x1 = max(0, center_x - radius - 10)
        y1 = max(0, center_y - radius - 10)
        x2 = min(w, center_x + radius + 10)
        y2 = min(h, center_y + radius + 10)
        roi = frame[y1:y2, x1:x2].copy()
        cv2.circle(roi, (center_x - x1, center_y - y1), radius, (40, 40, 40), -1)
        frame[y1:y2, x1:x2] = cv2.addWeighted(roi, 0.6, frame[y1:y2, x1:x2], 0.4, 0)

        # v4.4: 8px 边框, 颜色按分数 (绿/黄/红)
        border_color = self._focus_color(focus_score)
        cv2.circle(frame, (center_x, center_y), radius, border_color, 8)

        # 绘制圆形进度条
        color = self._fatigue_color(fatigue_level) if fatigue_level else self.config.focus_color
        start_angle = -90
        end_angle = start_angle + int(3.6 * focus_score)
        cv2.ellipse(frame, (center_x, center_y), (radius - 5, radius - 5),
                    0, start_angle, end_angle, color, 8)

        # v4.4: 中心数字 1.5x 字号 (原 0.8), 上方 "FOCUS" 标签
        cv2.putText(frame, "FOCUS", (center_x - 30, center_y - 30),
                    self.config.font, 0.5, COLOR_TEXT_MUTED, 1)
        cv2.putText(frame, f"{focus_score:.0f}", (center_x - 45, center_y + 18),
                    self.config.font, 1.5, COLOR_WHITE, 3)

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

        # v4.26: ROI 局部 blend 替代全帧 copy+addWeighted
        pad = 8
        ry1 = max(0, bar_y - pad)
        ry2 = min(h, bar_y + bar_height + pad)
        rx1 = max(0, bar_x - pad)
        rx2 = min(w, bar_x + bar_width + pad)
        roi = frame[ry1:ry2, rx1:rx2].copy()
        cv2.rectangle(roi, (bar_x - rx1, bar_y - ry1),
                      (bar_x + bar_width - rx1, bar_y + bar_height - ry1),
                      (40, 40, 40), -1)
        frame[ry1:ry2, rx1:rx2] = cv2.addWeighted(roi, 0.7, frame[ry1:ry2, rx1:rx2], 0.3, 0)

        # 进度条
        progress = min(1.0, calibration.current / max(1, calibration.total))
        filled_width = int(bar_width * progress)
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + filled_width, bar_y + bar_height),
                      (0, 200, 0), -1)

        # 边框
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + bar_width, bar_y + bar_height),
                      COLOR_WHITE, 2)

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

    def _alert_color(self, level: AlertLevel) -> Tuple[int, int, int]:
        """获取告警级别对应颜色"""
        if level == AlertLevel.INFO:
            return COLOR_WHITE
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
        """绘制完整校准 UI - 底部条形设计，不遮挡人脸"""
        if not self._calib_display or not self._calib_display.is_calibrating:
            return frame

        h, w = frame.shape[:2]
        phase = self._calib_phase
        if not phase:
            return frame

        # 底部条形面板设计（缩小高度以减少遮挡）
        bar_h = 80  # 从 120 缩小到 80
        bar_y = h - bar_h - 10  # 底部留边距
        bar_x = 10
        bar_w = w - 20

        # 底部深色条形背景
        cv2.rectangle(frame,
                      (bar_x, bar_y),
                      (bar_x + bar_w, bar_y + bar_h),
                      (15, 15, 15), -1)

        # 顶部边框线（青色）
        cv2.line(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y), (0, 200, 100), 2)

        # 左侧：阶段信息
        phase_text = f"[{phase.phase + 1}/6] {phase.name}"
        frame = put_chinese_text(frame, phase_text,
                                (bar_x + 15, bar_y + 30), _chinese_font_large, (0, 255, 0))

        # 指示文字
        frame = put_chinese_text(frame, phase.instruction,
                                (bar_x + 15, bar_y + 60), _chinese_font, (220, 220, 220))

        # 右侧：状态信息
        if not phase.is_input_mode:
            # 倒计时显示（统一使用中文）
            countdown_text = f"剩余 {phase.remaining}s"
            frame = put_chinese_text(frame, countdown_text,
                                    (bar_x + bar_w - 150, bar_y + 40), _chinese_font_large, (0, 255, 0))
        else:
            # 输入模式
            input_text = f"检测到 {phase.program_count} 次眨眼"
            frame = put_chinese_text(frame, input_text,
                                    (bar_x + bar_w - 280, bar_y + 30), _chinese_font, (255, 200, 0))

            if phase.input_buffer:
                buffer_text = f"您输入: {phase.input_buffer}"
                frame = put_chinese_text(frame, buffer_text,
                                        (bar_x + bar_w - 280, bar_y + 65), _chinese_font_large, (0, 255, 255))

            frame = put_chinese_text(frame, "数字键输入，Enter确认",
                                    (bar_x + bar_w - 280, bar_y + 95), _chinese_font_small, (180, 180, 180))

        # 眨眼计数（中间显示）
        if phase.round_num > 0 and not phase.is_input_mode:
            round_text = f"眨眼 {phase.round_num}/{phase.total_rounds} 轮"
            frame = put_chinese_text(frame, round_text,
                                    (bar_x + bar_w // 2 - 80, bar_y + 40), _chinese_font, (255, 255, 0))
            detected_text = f"已检测: {phase.detected_blinks} 次"
            frame = put_chinese_text(frame, detected_text,
                                    (bar_x + bar_w // 2 - 80, bar_y + 70), _chinese_font, (0, 255, 255))

        # 底部操作提示（使用中文）
        hint_text = "按 ESC 或 Q 退出校准"
        frame = put_chinese_text(frame, hint_text,
                                (bar_x + 15, bar_y + bar_h - 15), _chinese_font_small, (100, 100, 100))

        return frame

    def _draw_calibration_result(self, frame: np.ndarray) -> np.ndarray:
        """绘制校准结果 - 底部条形设计"""
        if not self._calib_phase or not self._calib_phase.result:
            return frame

        h, w = frame.shape[:2]
        result = self._calib_phase.result

        # 底部条形面板
        bar_h = 100
        bar_y = h - bar_h - 10
        bar_x = 10
        bar_w = w - 20

        # 深色背景
        cv2.rectangle(frame,
                      (bar_x, bar_y),
                      (bar_x + bar_w, bar_y + bar_h),
                      (15, 15, 15), -1)

        # 顶部边框线（绿色表示成功）
        cv2.line(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y), (0, 255, 0), 2)

        # 标题
        frame = put_chinese_text(frame, "校准完成",
                                (bar_x + 15, bar_y + 30), _chinese_font_large, (0, 255, 0))

        # 参数显示（统一使用中文 PIL）
        params = [
            f"EAR: {result.signal.ear_mean:.3f}",
            f"眨眼阈值: {result.final_blink_threshold:.3f}",
            f"眯眼阈值: {result.final_squint_threshold:.3f}",
            f"调整: {result.final_adjustment_factor:.2f}x"
        ]

        x_pos = bar_x + 15
        for param in params:
            frame = put_chinese_text(frame, param,
                                    (x_pos, bar_y + 65), _chinese_font, COLOR_WHITE)
            x_pos += 160

        # 继续提示
        frame = put_chinese_text(frame, "按任意键继续...",
                                (bar_x + bar_w - 150, bar_y + 90), _chinese_font_small, (150, 150, 150))

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
