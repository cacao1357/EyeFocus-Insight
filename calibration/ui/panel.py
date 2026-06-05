"""calibration/ui/panel.py — UI 区渲染 + 按钮布局

按 FlowState 渲染对应 UI（PIL 中文 + cv2 矩形）。
所有按钮位置由 get_buttons 暴露，input_handler 据此做鼠标命中。

设计依据：spec §2.4 + 决策 C2/F1（鼠标主导 + 实时反馈）。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# 字体路径（沿用 gui/overlay.py 现有路径）
_FONT_PATH = "C:/Windows/Fonts/simhei.ttf"
try:
    _FONT_LARGE = ImageFont.truetype(_FONT_PATH, 28)
    _FONT_MED = ImageFont.truetype(_FONT_PATH, 20)
    _FONT_SMALL = ImageFont.truetype(_FONT_PATH, 16)
except Exception:
    _FONT_LARGE = _FONT_MED = _FONT_SMALL = None


class FlowState(Enum):
    WAITING_TO_START_PHASE = "waiting_start"
    PHASE_RUNNING = "running"
    PHASE_SUMMARY_SUCCESS = "summary_success"
    PHASE_SUMMARY_FAILED = "summary_failed"
    BLINK_INPUT_AWAITING = "blink_input"
    FINAL_SUMMARY = "final_summary"


class UIAction(Enum):
    NONE = "none"
    PROCEED = "proceed"
    RETRY_PHASE = "retry"
    SKIP_PHASE = "skip"
    CANCEL = "cancel"
    DIGIT = "digit"
    BACKSPACE = "backspace"
    SUBMIT = "submit"


@dataclass
class Button:
    label: str
    rect: Tuple[int, int, int, int]    # (x, y, w, h)
    action: UIAction
    style: str = "primary"             # "primary" 绿 / "danger" 红 / "neutral" 灰
    digit_value: Optional[str] = None  # 仅当 action=DIGIT

    def contains(self, x: int, y: int) -> bool:
        bx, by, bw, bh = self.rect
        return bx <= x < bx + bw and by <= y < by + bh


@dataclass
class PhaseDisplayInfo:
    state: FlowState
    phase_index: int           # 1-5
    phase_total: int           # 5
    phase_name: str
    instruction: str
    remaining_sec: float = 0.0
    sample_count: int = 0
    quality_hint: str = ""
    summary_text: str = ""
    program_blink_count: int = 0
    user_input_buffer: str = ""
    final_summary: Dict[str, Any] = field(default_factory=dict)
    # v4.4 新增: 常驻 REC 指示 + 拖窗口检测
    rec_indicator: str = "●REC 录制中"  # 始终显示
    dragging: bool = False                  # 拖窗口时为 True


_STYLE_COLOR = {
    "primary": (50, 200, 70),    # 绿 (BGR)
    "danger":  (50, 50, 220),    # 红
    "neutral": (120, 120, 120),  # 灰
}


class Panel:
    """UI 区渲染器。"""

    def __init__(self, width: int = 640, height: int = 240):
        self.width = width
        self.height = height

    def render(self, info: PhaseDisplayInfo) -> np.ndarray:
        """生成 (height, width, 3) BGR 图像。"""
        img = np.full((self.height, self.width, 3), 20, dtype=np.uint8)  # 深色背景
        # 顶部边框
        cv2.line(img, (0, 0), (self.width, 0), (0, 200, 100), 2)

        # v4.4: 顶部 ●REC 录制中 指示 (绿底白字, 让用户知道数据在记录)
        if info.rec_indicator and _FONT_SMALL:
            self._put_text(img, info.rec_indicator, (10, 10), _FONT_SMALL, (0, 0, 0), bg_color=(0, 200, 100))

        # v4.4: 拖窗口时叠加 ❄ DRAGGING 画面冻结 遮罩
        if info.dragging:
            h, w = img.shape[:2]
            overlay = img.copy()
            cv2.rectangle(overlay, (0, 0), (w, h), (0, 0, 0), -1)
            img[:] = cv2.addWeighted(overlay, 0.4, img, 0.6, 0)
            if _FONT_LARGE:
                self._put_text(img, "❄ DRAGGING 画面冻结", (w // 2 - 110, h // 2 - 20),
                               _FONT_LARGE, (100, 200, 255))
                self._put_text(img, "(数据继续录制)", (w // 2 - 80, h // 2 + 20),
                               _FONT_MED, (200, 200, 200))

        if info.state == FlowState.WAITING_TO_START_PHASE:
            self._render_waiting(img, info)
        elif info.state == FlowState.PHASE_RUNNING:
            self._render_running(img, info)
        elif info.state == FlowState.PHASE_SUMMARY_SUCCESS:
            self._render_summary(img, info, success=True)
        elif info.state == FlowState.PHASE_SUMMARY_FAILED:
            self._render_summary(img, info, success=False)
        elif info.state == FlowState.BLINK_INPUT_AWAITING:
            self._render_blink_input(img, info)
        elif info.state == FlowState.FINAL_SUMMARY:
            self._render_final(img, info)

        # 渲染所有按钮
        for btn in self.get_buttons(info):
            self._draw_button(img, btn)

        return img

    def get_buttons(self, info: PhaseDisplayInfo) -> List[Button]:
        """返回当前状态下所有可点击按钮。"""
        if info.state == FlowState.WAITING_TO_START_PHASE:
            return [
                Button("▶ 开始", (40, 170, 160, 50), UIAction.PROCEED, "primary"),
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.PHASE_RUNNING:
            return [
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.PHASE_SUMMARY_SUCCESS:
            return [
                Button("▶ 继续", (40, 170, 160, 50), UIAction.PROCEED, "primary"),
                Button("↺ 重做", (240, 170, 160, 50), UIAction.RETRY_PHASE, "neutral"),
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.PHASE_SUMMARY_FAILED:
            return [
                Button("↺ 重做", (40, 170, 160, 50), UIAction.RETRY_PHASE, "neutral"),
                Button("→ 跳过", (240, 170, 160, 50), UIAction.SKIP_PHASE, "neutral"),
                Button("取消", (440, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        if info.state == FlowState.BLINK_INPUT_AWAITING:
            return self._build_keypad_buttons()
        if info.state == FlowState.FINAL_SUMMARY:
            return [
                Button("▶ 继续 → 主监测", (20, 170, 240, 50), UIAction.PROCEED, "primary"),
                Button("↺ 重新校准", (280, 170, 160, 50), UIAction.RETRY_PHASE, "neutral"),
                Button("退出", (460, 170, 160, 50), UIAction.CANCEL, "danger"),
            ]
        return []

    def _build_keypad_buttons(self) -> List[Button]:
        """0-9 数字键盘 + 退格 + 确认 + 取消。"""
        btns: List[Button] = []
        # 3×4 网格：7 8 9 / 4 5 6 / 1 2 3 / 0 . .
        digits = [
            ("7", 0, 0), ("8", 1, 0), ("9", 2, 0),
            ("4", 0, 1), ("5", 1, 1), ("6", 2, 1),
            ("1", 0, 2), ("2", 1, 2), ("3", 2, 2),
            ("0", 1, 3),
        ]
        bw, bh = 50, 40
        x0, y0 = 60, 70
        gap = 6
        for d, cx, cy in digits:
            x = x0 + cx * (bw + gap)
            y = y0 + cy * (bh + gap)
            btns.append(Button(d, (x, y, bw, bh), UIAction.DIGIT, "neutral", digit_value=d))
        # 退格 / 确认 / 取消（右侧）
        btns.append(Button("⌫ 退格", (260, 70, 110, 40), UIAction.BACKSPACE, "neutral"))
        btns.append(Button("✓ 确认", (260, 120, 110, 40), UIAction.SUBMIT, "primary"))
        btns.append(Button("取消", (260, 170, 110, 40), UIAction.CANCEL, "danger"))
        return btns

    def _draw_button(self, img: np.ndarray, btn: Button) -> None:
        x, y, w, h = btn.rect
        color = _STYLE_COLOR.get(btn.style, (100, 100, 100))
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
        # 文字（PIL）
        if _FONT_MED:
            self._put_text(img, btn.label, (x + 10, y + 8), _FONT_MED, (255, 255, 255))

    def _put_text(self, img: np.ndarray, text: str, pos: Tuple[int, int],
                  font, color_bgr: Tuple[int, int, int],
                  bg_color: Optional[Tuple[int, int, int]] = None) -> None:
        # v4.4: 可选背景色 (给 REC 指示器加绿底)
        if bg_color is not None:
            pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil)
            # 用 textbbox 算文字尺寸画背景
            try:
                bbox = draw.textbbox(pos, text, font=font)
                pad = 4
                cv2.rectangle(img,
                              (bbox[0] - pad, bbox[1] - pad),
                              (bbox[2] + pad, bbox[3] + pad),
                              bg_color, -1)
            except Exception:
                pass  # textbbox 失败时降级到无背景
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        draw.text(pos, text, font=font, fill=color_bgr[::-1])
        img[:] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    def _render_waiting(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, f"[阶段 {info.phase_index}/{info.phase_total}] {info.phase_name}",
                           (20, 20), _FONT_LARGE, (0, 255, 100))
            self._put_text(img, info.instruction, (20, 70), _FONT_MED, (220, 220, 220))
            self._put_text(img, "准备好了吗？点'开始'", (20, 110), _FONT_SMALL, (180, 180, 180))

    def _render_running(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, f"[阶段 {info.phase_index}/{info.phase_total}] {info.phase_name}",
                           (20, 20), _FONT_LARGE, (0, 255, 100))
            self._put_text(img, f"剩余 {info.remaining_sec:.1f}s", (450, 20),
                           _FONT_LARGE, (255, 200, 0))
            self._put_text(img, info.quality_hint, (20, 70), _FONT_MED, (220, 220, 220))
            if info.sample_count > 0:
                self._put_text(img, f"📊 已采集 {info.sample_count} 样本",
                               (20, 110), _FONT_SMALL, (0, 200, 255))

    def _render_summary(self, img: np.ndarray, info: PhaseDisplayInfo, success: bool) -> None:
        color = (0, 255, 100) if success else (50, 50, 230)
        icon = "✓" if success else "✗"
        if _FONT_LARGE:
            self._put_text(img, f"{icon} 阶段 {info.phase_index} {'完成' if success else '失败'}",
                           (20, 20), _FONT_LARGE, color)
            self._put_text(img, info.summary_text, (20, 70), _FONT_MED, (220, 220, 220))

    def _render_blink_input(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, f"程序检测到 {info.program_blink_count} 次",
                           (20, 10), _FONT_MED, (255, 200, 0))
            self._put_text(img, f"你的实际次数：[ {info.user_input_buffer} ]_",
                           (20, 40), _FONT_LARGE, (0, 255, 255))

    def _render_final(self, img: np.ndarray, info: PhaseDisplayInfo) -> None:
        if _FONT_LARGE:
            self._put_text(img, "✅ 校准完成", (20, 10), _FONT_LARGE, (0, 255, 100))
            y = 50
            for k, v in info.final_summary.items():
                self._put_text(img, f"{k}: {v}", (20, y), _FONT_SMALL, (220, 220, 220))
                y += 22
