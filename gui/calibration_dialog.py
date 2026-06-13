"""
gui/calibration_dialog.py — Qt 校准对话框 (v5.0)

v4.7 设计规范：
  - 70/30 上下布局（视频 / 白底信息面板）
  - 信息面板左右分区：左侧标题+指引 / 右侧倒计时+圆点
  - 26px 指引 / 17px 辅助 / 48px 倒计时
  - 白底黑字按钮，1.5px 灰边框，44px 高
  - 完全手动步骤推进（预告→开始→进行→完成→预告…）
  - 头部姿态每方向独立预告
  - 全宽结果页 2×2 网格展示 4 项数据
"""
import time
import statistics
from typing import Optional

import cv2
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QWidget, QSizePolicy,
)


# ── 音效 ──

def beep(freq: int, dur: int):
    try:
        import winsound
        winsound.Beep(freq, dur)
    except Exception:
        pass


# ── 统一按钮样式（v4.7：白底黑字 + 灰边框）──

BTN_PRIMARY = """
QPushButton {
  background-color: #FFFFFF; color: #000000;
  border: 1.5px solid #CCCCCC; border-radius: 8px;
  font-size: 16px; font-weight: 600; padding: 8px 24px;
  min-height: 44px;
}
QPushButton:hover { background-color: #F5F5F5; border-color: #AAAAAA; }
QPushButton:disabled {
  color: #CCCCCC; border-color: #E8E8E8;
  background-color: #FFFFFF;
}
"""

BTN_SECONDARY = """
QPushButton {
  background-color: #FFFFFF; color: #666666;
  border: 1.5px solid #DDDDDD; border-radius: 8px;
  font-size: 15px; font-weight: 500; padding: 6px 18px;
  min-height: 40px;
}
QPushButton:hover { background-color: #F5F5F5; border-color: #BBBBBB; }
QPushButton:disabled {
  color: #CCCCCC; border-color: #E8E8E8;
  background-color: #FFFFFF;
}
"""


# ═══════════════════════════════════════════════════════════════════
# CalibrationDialog
# ═══════════════════════════════════════════════════════════════════

class CalibrationDialog(QDialog):
    """Qt 校准对话框 (v4.7 重设计)

    70% 摄像头 + 30% 白底信息面板。
    5 状态状态机：welcome → preview → running → done → result
    """

    # ── 步骤常量 ──
    STEP_DUR = 4.0          # 步骤 1/2 时长（睁眼基线 / 闭眼检测）
    HEAD_DIR_DUR = 3.0      # 头部姿态每方向时长
    BLINK_DUR = 10.0        # 眨眼计数 10s

    STEPS = [
        (1, "睁眼基线", "请自然睁眼，保持正常坐姿"),
        (2, "闭眼检测", "请轻轻闭上双眼"),
        (3, "头部姿态", None),
        (4, "眨眼计数", "正常眨眼，心里默数次数"),
    ]
    HEAD_DIRS = [
        ("向上看", "抬头看天花板"),
        ("向下看", "低头看地面"),
        ("向左看", "转头看左边"),
        ("向右看", "转头看右边"),
    ]

    def __init__(self, parent=None, fd=None, ed=None):
        super().__init__(parent)
        self.setWindowTitle("EyeFocus 用户校准")
        self.resize(960, 750)
        self.setMinimumSize(800, 650)
        self.setStyleSheet("background-color: #000000;")
        self.result_data: dict = {}

        # ── 字体 ──
        self._font_title = QFont("Segoe UI", 18, QFont.Bold)
        self._font_guide = QFont("Segoe UI", 16)
        self._font_stat = QFont("Segoe UI", 13)
        self._font_countdown = QFont("Segoe UI", 36, QFont.Bold)
        self._font_dots = QFont("Segoe UI", 14)

        # ── 布局：视频 70% + 信息面板 30% ──
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 视频区
        self._vid = QLabel()
        self._vid.setAlignment(Qt.AlignCenter)
        self._vid.setStyleSheet("background-color: #000000;")
        self._vid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._vid, 7)

        # ── 信息面板 ──
        panel = QWidget()
        panel.setObjectName("InfoPanel")
        panel.setStyleSheet("""
            QWidget#InfoPanel {
                background-color: #FFFFFF;
                border: 1.5px solid #E0E0E0;
                border-radius: 8px;
            }
        """)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(16, 8, 16, 8)
        pl.setSpacing(4)

        # 内容行：左（标题+指引）+ 右（倒计时+圆点）
        content = QHBoxLayout()
        content.setSpacing(12)

        # ── 左侧：标题 + 指引 + 统计 ──
        left_col = QVBoxLayout()
        left_col.setSpacing(2)

        self._title = QLabel("")
        self._title.setFont(self._font_title)
        self._title.setStyleSheet("color: #000000; border: none; background: transparent;")
        left_col.addWidget(self._title)

        self._guide = QLabel("")
        self._guide.setFont(self._font_guide)
        self._guide.setStyleSheet("color: #333333; border: none; background: transparent;")
        self._guide.setWordWrap(True)
        left_col.addWidget(self._guide)

        self._stat = QLabel("")
        self._stat.setFont(self._font_stat)
        self._stat.setStyleSheet("color: #666666; border: none; background: transparent;")
        left_col.addWidget(self._stat)
        left_col.addStretch(1)

        content.addLayout(left_col, 1)

        # ── 右侧：倒计时 + 圆点 ──
        right_col = QVBoxLayout()
        right_col.setAlignment(Qt.AlignCenter)
        right_col.setSpacing(4)

        self._countdown = QLabel("")
        self._countdown.setFont(self._font_countdown)
        self._countdown.setStyleSheet("color: #000000; border: none; background: transparent;")
        self._countdown.setAlignment(Qt.AlignCenter)
        right_col.addWidget(self._countdown)

        self._dots = QLabel("")
        self._dots.setTextFormat(Qt.RichText)
        self._dots.setFont(self._font_dots)
        self._dots.setStyleSheet("color: #CCCCCC; border: none; background: transparent;")
        self._dots.setAlignment(Qt.AlignCenter)
        right_col.addWidget(self._dots)

        content.addLayout(right_col, 0)
        pl.addLayout(content, 1)

        # ── 按钮行：stretch | back_btn | skip_btn | main_btn ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 4, 0, 0)

        # 占位（将按钮推到右侧）
        btn_row.addStretch(1)

        self._back_btn = QPushButton("上一步")
        self._back_btn.setStyleSheet(BTN_SECONDARY)
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.clicked.connect(self._on_back)
        self._back_btn.hide()
        btn_row.addWidget(self._back_btn, 0)

        self._skip_btn = QPushButton("")
        self._skip_btn.setStyleSheet(BTN_SECONDARY)
        self._skip_btn.setCursor(Qt.PointingHandCursor)
        self._skip_btn.clicked.connect(self._on_skip)
        btn_row.addWidget(self._skip_btn, 0)

        self._main_btn = QPushButton("")
        self._main_btn.setStyleSheet(BTN_PRIMARY)
        self._main_btn.setCursor(Qt.PointingHandCursor)
        self._main_btn.clicked.connect(self._on_main)
        btn_row.addWidget(self._main_btn, 0)

        pl.addLayout(btn_row)
        root.addWidget(panel, 3)

        # ── 状态变量 ──
        self._cam = None
        self._own_cam = True
        self._fd = fd
        self._ed = ed
        self._own_fd = fd is None
        self._own_ed = ed is None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        # 状态机
        self._phase = 0          # 0=welcome, 1-4=steps, 5=result
        self._kind = ""          # "welcome" / "preview" / "running" / "done" / "result"
        self._t0 = 0.0
        self._dur = 0.0
        self._collected = []
        self._sub = 0            # 头部方向索引
        self._next = 1           # 下一步编号（1-5）
        self._done_phase = 0     # 最近完成的 phase（用于上一步）

        # 眨眼验证
        self._blink_start_count = 0
        self._blink_round = 0
        self._blink_match_streak = 0

        # 校准结果
        self._r_ear = 0.25
        self._r_closed = 0.08
        self._r_blink = 15.0
        self._r_yaw = 0.0
        self._r_pitch = 0.0
        self._user_blinks = 0
        self._head_yaws = []
        self._head_pitches = []
        self._head_peaks = []
        self._cal_start_time = 0.0

        self._set_welcome_ui()

    # ══════════════════════════════════════════════════════════════
    #  资源管理
    # ══════════════════════════════════════════════════════════════

    def _open_camera(self) -> bool:
        if self._cam is not None:
            return True
        self._cam = cv2.VideoCapture(0)
        if not self._cam.isOpened():
            self._cam = None
            return False
        self._cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._own_cam = True
        return True

    def _start_preview(self):
        self._timer.start(33)

    def _ensure_detectors(self):
        from detector.face_mesh import create_face_mesh_detector
        from detector.eye_aspect import create_eye_aspect_detector
        if self._fd is None:
            self._fd = create_face_mesh_detector()
            self._own_fd = True
        if self._ed is None:
            self._ed = create_eye_aspect_detector()
            self._own_ed = True

    # ══════════════════════════════════════════════════════════════
    #  UI 辅助
    # ══════════════════════════════════════════════════════════════

    def _set_dots(self, active: int):
        """active: 当前步骤编号 1-4"""
        parts = []
        for i in range(4):
            n = i + 1
            if n <= active:
                parts.append('<span style="color:#34C759;">●</span>')
            else:
                parts.append('<span style="color:#CCCCCC;">○</span>')
        self._dots.setText(" ".join(parts))

    def _set_welcome_ui(self):
        self._phase = 0
        self._kind = "welcome"
        self._title.setText("准备开始校准")
        self._guide.setText("请面对摄像头，确保光线充足")
        self._stat.setText("约 30 秒 · 4 个步骤")
        self._countdown.setText("")
        self._dots.setText('<span style="color:#CCCCCC;">○ ○ ○ ○</span>')
        self._main_btn.setText("开始校准")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(BTN_PRIMARY)
        self._skip_btn.hide()
        self._back_btn.hide()

    def _set_preview_ui(self, step: int, name: str, guide: str):
        """显示步骤预告 — 等待用户点击「开始」"""
        self._kind = "preview"
        self._title.setText(f"步骤 {step}/4 — {name}")
        self._guide.setText(guide)
        self._stat.setText("")
        self._countdown.setText("")
        self._set_dots(step)
        self._main_btn.setText("开始")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(BTN_PRIMARY)
        # 预览态：显示取消按钮
        self._skip_btn.setText("取消")
        self._skip_btn.setEnabled(True)
        self._skip_btn.show()
        # 上一步按钮
        is_dir_first = (step == 3 and self._phase == 3 and self._sub == 0)
        if step > 1 and not is_dir_first:
            self._back_btn.show()
        else:
            self._back_btn.hide()

    def _set_running_ui(self, step: int, name: str, guide: str, stat: str):
        """显示进行中 UI"""
        self._kind = "running"
        self._title.setText(f"步骤 {step}/4 — {name}")
        self._guide.setText(guide)
        self._stat.setText(stat)
        self._main_btn.setText("校准中…")
        self._main_btn.setEnabled(False)
        self._main_btn.setStyleSheet(BTN_PRIMARY)
        self._skip_btn.setText("取消")
        self._skip_btn.setEnabled(True)
        self._skip_btn.show()
        self._back_btn.hide()

    def _set_done_ui(self, step: int, result_text: str):
        """显示步骤完成 — 用户需点击「继续」或「重测」"""
        self._kind = "done"
        self._done_phase = self._phase
        self._title.setText(f"✓ 步骤 {step}/4 完成")
        self._guide.setText(result_text)
        self._stat.setText("")
        self._countdown.setText("")
        self._main_btn.setText("继续")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(BTN_PRIMARY)
        self._skip_btn.setText("重测")
        self._skip_btn.setEnabled(True)
        self._skip_btn.show()
        self._back_btn.show()

    def _show_result_page(self):
        """全宽结果页：4 项数据 + [重新校准] [进入监测]"""
        self._phase = 5
        self._kind = "result"
        self._countdown.setText("")
        beep(600, 500)

        # 重写 panel 内容为结果页
        self._title.setText("✓ 校准完成")
        self._guide.setText("")

        # 用 stat 区展示 2×2 网格
        self._stat.setText(
            f"睁眼基线 EAR    {self._r_ear:.3f}       │"
            f"  闭眼下限 EAR    {self._r_closed:.3f}\n"
            f"头部左右范围  ±{self._r_yaw:.0f}°       │"
            f"  头部上下范围  ±{self._r_pitch:.0f}°"
        )
        self._dots.setText("")

        self._main_btn.setText("进入监测")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(BTN_PRIMARY)
        self._skip_btn.setText("重新校准")
        self._skip_btn.setEnabled(True)
        self._skip_btn.show()
        self._back_btn.hide()

        self.result_data = {
            "baseline_ear": self._r_ear,
            "closed_ear": self._r_closed,
            "head_yaw_range": self._r_yaw,
            "head_pitch_range": self._r_pitch,
        }

    # ══════════════════════════════════════════════════════════════
    #  流程控制
    # ══════════════════════════════════════════════════════════════

    def _start(self):
        """欢迎 → 步骤 1 预告"""
        self._cal_start_time = time.time()
        self._phase = -1
        self._next = 1
        s = self.STEPS[0]
        self._set_preview_ui(s[0], s[1], s[2])

    def _begin_step(self):
        """开始当前步骤的数据采集"""
        p = self._next
        if p == 1:
            self._phase = 1
            self._collected = []
            self._t0 = time.time()
            self._dur = self.STEP_DUR
            self._set_running_ui(1, self.STEPS[0][1], self.STEPS[0][2], "")
            beep(800, 100)
        elif p == 2:
            self._phase = 2
            self._collected = []
            self._t0 = time.time()
            self._dur = self.STEP_DUR
            self._set_running_ui(2, self.STEPS[1][1], self.STEPS[1][2], "")
            beep(800, 100)
        elif p == 3:
            if self._phase != 3:
                self._phase = 3
                self._sub = 0
                self._head_peaks = []
            self._head_yaws = []
            self._head_pitches = []
            self._begin_head_dir()
        elif p == 4:
            self._phase = 4
            self._blink_round = 1
            self._blink_match_streak = 0
            self._start_blink_round()

    def _begin_head_dir(self):
        """开始当前方向（_sub）的头部姿态采集"""
        dname, dinst = self.HEAD_DIRS[self._sub]
        self._t0 = time.time()
        self._dur = self.HEAD_DIR_DUR
        self._set_running_ui(3, f"头部姿态 — {dname}", dinst,
                             f"方向 {self._sub + 1}/4")
        beep(800, 100)

    def _start_blink_round(self):
        """开始新一轮眨眼验证（10s）"""
        self._blink_start_count = len(self._ed._blink_events) if self._ed else 0
        self._t0 = time.time()
        self._dur = self.BLINK_DUR
        r = self._blink_round
        self._set_running_ui(4, self.STEPS[3][1], self.STEPS[3][2],
                             f"第 {r} 轮 · 已确认 {self._blink_match_streak}/3")
        beep(800, 100)

    # ══════════════════════════════════════════════════════════════
    #  帧循环
    # ══════════════════════════════════════════════════════════════

    def _tick(self):
        if self._cam is None:
            return
        ret, frame = self._cam.read()
        if not ret:
            return

        # 显示摄像头画面
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self._vid.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._vid.setPixmap(pixmap)

        if self._kind != "running":
            return

        # ── 运行中：数据采集 ──
        elapsed = time.time() - self._t0
        remaining = max(0, int(self._dur - elapsed + 1))
        self._countdown.setText(str(remaining))

        ts = int(time.time() * 1000)
        fr = self._fd.detect_from_frame(frame, ts)
        ear = None
        yaw = 0.0
        pitch = 0.0
        er = None
        if fr and fr.face_detected:
            er = self._ed.compute(fr.landmarks)
            ear = er.ear_avg
            yaw = fr.yaw or 0.0
            pitch = fr.pitch or 0.0

        if self._phase == 1:
            if ear is not None and ear > 0.15 and not er.is_blink:
                self._collected.append(ear)
            self._stat.setText(f"已采集 {len(self._collected)} 个样本")
        elif self._phase == 2:
            if ear is not None:
                self._collected.append(ear)
            self._stat.setText(f"闭眼帧 {len(self._collected)}")
        elif self._phase == 3:
            if fr and fr.face_detected:
                self._head_yaws.append(yaw)
                self._head_pitches.append(pitch)
        elif self._phase == 4:
            self._stat.setText("记录中…")

        if elapsed >= self._dur:
            self._finish_step()

    # ══════════════════════════════════════════════════════════════
    #  步骤完成
    # ══════════════════════════════════════════════════════════════

    def _finish_step(self):
        self._kind = ""
        self._countdown.setText("")
        beep(1000, 250)

        if self._phase == 1:
            if len(self._collected) >= 5:
                self._r_ear = statistics.median(self._collected)
            self._next = 2
            self._set_done_ui(1,
                f"睁眼基线 EAR = {self._r_ear:.3f}\n"
                f"共采集 {len(self._collected)} 个样本")

        elif self._phase == 2:
            self._r_closed = min(self._collected) if self._collected else 0.08
            self._next = 3
            init_thr = self._r_closed + (self._r_ear - self._r_closed) * 0.35
            self._ed.ear_threshold = round(init_thr, 4)
            self._ed._has_baseline = True
            self._set_done_ui(2,
                f"闭眼下限 EAR = {self._r_closed:.3f}\n"
                f"初始阈值 = {init_thr:.3f}\n"
                f"共 {len(self._collected)} 帧")

        elif self._phase == 3:
            dir_name = self.HEAD_DIRS[self._sub][0]
            peak_yaw = max((abs(v) for v in self._head_yaws), default=0.0)
            peak_pitch = max((abs(v) for v in self._head_pitches), default=0.0)
            self._head_peaks.append((dir_name, peak_yaw, peak_pitch))

            self._sub += 1
            if self._sub < len(self.HEAD_DIRS):
                # 还有下一个方向 → 去下一方向预告
                self._next = 3
                next_name, next_inst = self.HEAD_DIRS[self._sub]
                self._set_done_ui(3,
                    f"{dir_name} 完成\n"
                    f"下一方向：{next_name} {next_inst}")
            else:
                # 全部 4 方向完成
                all_yaws = [p[1] for p in self._head_peaks]
                all_pitches = [p[2] for p in self._head_peaks]
                self._r_yaw = max(all_yaws) if all_yaws else 0.0
                self._r_pitch = max(all_pitches) if all_pitches else 0.0

                # 从自然眨眼反推阈值
                nadirs = []
                natural_count = 0
                for e in self._ed._blink_events if self._ed else []:
                    if e.is_confirmed and e.ear_nadir > 0:
                        if self._r_closed <= e.ear_nadir <= self._r_ear * 1.1:
                            nadirs.append(e.ear_nadir)
                        natural_count += 1

                if len(nadirs) >= 2:
                    sorted_n = sorted(nadirs)
                    p75_idx = min(int(len(sorted_n) * 0.75), len(sorted_n) - 1)
                    p75_nadir = sorted_n[p75_idx]
                    self._ed.ear_threshold = round(p75_nadir * 1.1, 4)
                    self._ed._has_baseline = True
                    thr_source = f"自然眨眼({len(nadirs)}次, P75={p75_nadir:.3f})"
                else:
                    blink_thr = self._r_closed + (self._r_ear - self._r_closed) * 0.35
                    self._ed.ear_threshold = round(blink_thr, 4)
                    self._ed._has_baseline = True
                    thr_source = "睁闭眼插值"

                self._next = 4
                self._set_done_ui(3,
                    f"头部姿态完成\n"
                    f"左右 ±{self._r_yaw:.0f}°  上下 ±{self._r_pitch:.0f}°")

        elif self._phase == 4:
            current = len(self._ed._blink_events) if self._ed else 0
            detected = max(0, current - self._blink_start_count)

            user_n = self._show_verify_dialog(detected)
            if user_n == detected:
                self._blink_match_streak += 1
                if self._blink_match_streak >= 3:
                    self._next = 5
                    self._set_done_ui(4,
                        f"✓ 阈值 {self._ed.ear_threshold:.3f} 验证通过\n"
                        f"连续 {self._blink_match_streak} 次一致")
                    return
                self._blink_round += 1
                self._start_blink_round()
                return
            else:
                if self._ed.ear_threshold <= 0 or detected == 0:
                    self._ed.ear_threshold = round(
                        self._r_closed + (self._r_ear - self._r_closed) * 0.4, 4)
                elif detected < user_n:
                    self._ed.ear_threshold = round(
                        self._ed.ear_threshold * 1.15, 4)
                else:
                    self._ed.ear_threshold = round(
                        self._ed.ear_threshold * 0.85, 4)
                lo = self._r_closed * 0.9
                hi = self._r_ear * 0.85
                self._ed.ear_threshold = round(
                    max(lo, min(hi, self._ed.ear_threshold)), 4)
                self._blink_match_streak = 0
                self._blink_round += 1
                self._start_blink_round()
                return

    # ── 眨眼验证对话框 ──

    def _show_verify_dialog(self, detected: int) -> int:
        """显示一致/不一致对话框，返回用户确认的眨眼次数"""
        from PyQt5.QtWidgets import (
            QDialog as _QD, QHBoxLayout as _HL, QVBoxLayout as _VL,
            QLabel as _QL, QLineEdit,
        )
        DLG_STYLE = """
            QDialog { background-color: #FFFFFF; }
            * { background-color: #FFFFFF; }
            QLabel { color: #000000; background-color: #FFFFFF;
              font-size: 15px; font-family: 'Segoe UI'; border: none; }
            QPushButton { background-color: #FFFFFF; color: #555555;
              border: 1.5px solid #BBBBBB; border-radius: 8px;
              font-size: 14px; padding: 6px 16px; min-height: 38px; }
            QPushButton:hover { background-color: #F5F5F5; }
            QLineEdit { background-color: #FFFFFF; color: #000000;
              border: 1.5px solid #BBBBBB; border-radius: 6px;
              font-size: 20px; padding: 6px 10px; }
        """

        dlg = _QD(self)
        dlg.setWindowTitle(f"阈值校验 · 第{self._blink_round}轮")
        dlg.setMinimumWidth(480)
        dlg.setStyleSheet(DLG_STYLE)
        dl = _VL(dlg)
        dl.setContentsMargins(32, 24, 32, 20)
        dl.setSpacing(16)
        msg = _QL(
            f"第 {self._blink_round} 轮 · 已确认 {self._blink_match_streak}/3\n"
            f"10s 检测到 {detected} 次眨眼\n\n"
            f"和你实际感觉一致吗？"
        )
        msg.setStyleSheet("color: #000000; font-size: 20px; border: none; background: transparent;")
        dl.addWidget(msg)
        bl = _HL()
        bl.setSpacing(10)
        bl.addStretch()
        no_btn = QPushButton("不一致，我输入")
        no_btn.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #555555;"
            "  border: 1.5px solid #BBBBBB; border-radius: 8px;"
            "  font-size: 16px; padding: 8px 20px; min-height: 42px; }"
            "QPushButton:hover { background-color: #F5F5F5; }"
        )
        yes_btn = QPushButton("一致")
        yes_btn.setStyleSheet(BTN_PRIMARY)
        bl.addWidget(no_btn)
        bl.addWidget(yes_btn)
        dl.addLayout(bl)
        no_btn.clicked.connect(lambda: dlg.done(2))
        yes_btn.clicked.connect(dlg.accept)
        result = dlg.exec_()

        if result == _QD.Accepted:
            return detected

        d2 = _QD(self)
        d2.setWindowTitle("输入实际次数")
        d2.setMinimumWidth(400)
        d2.setStyleSheet(DLG_STYLE)
        d2l = _VL(d2)
        d2l.setContentsMargins(32, 20, 32, 16)
        d2l.setSpacing(14)
        lb = _QL("你实际眨眼多少次？")
        lb.setStyleSheet(
            "color: #000000; background-color: #FFFFFF;"
            "font-size: 20px; font-family: 'Segoe UI'; border: none;")
        d2l.addWidget(lb)
        le = QLineEdit(str(max(1, detected)))
        le.setStyleSheet(
            "QLineEdit { background-color: #FFFFFF; color: #000000;"
            "  border: 1.5px solid #BBBBBB; border-radius: 6px;"
            "  font-size: 24px; padding: 8px 12px; }"
        )
        le.setAlignment(Qt.AlignCenter)
        le.setMaxLength(3)
        d2l.addWidget(le)
        d2bl = _HL()
        d2bl.setSpacing(10)
        d2bl.addStretch()
        d2_ok = QPushButton("确定")
        d2_ok.setStyleSheet(BTN_PRIMARY)
        d2_ok.clicked.connect(d2.accept)
        d2bl.addWidget(d2_ok)
        d2l.addLayout(d2bl)
        if d2.exec_() == _QD.Accepted:
            try:
                return int(le.text())
            except ValueError:
                return detected
        return detected

    # ══════════════════════════════════════════════════════════════
    #  按钮回调
    # ══════════════════════════════════════════════════════════════

    def _on_main(self):
        """主按钮逻辑"""
        if self._phase == 0 and self._kind == "welcome":
            self._start()
        elif self._kind == "preview":
            self._begin_step()
        elif self._kind == "done":
            p = self._next
            if p == 5:
                self._show_result_page()
            elif p == 3 and self._sub < len(self.HEAD_DIRS):
                # 头部姿态下一方向
                dname, dinst = self.HEAD_DIRS[self._sub]
                self._set_preview_ui(3, f"头部姿态 — {dname}", dinst)
            elif p == 4:
                s = self.STEPS[3]
                self._set_preview_ui(4, s[1], s[2])
            else:
                s = self.STEPS[p - 1] if 0 <= p - 1 < len(self.STEPS) else (p, "", "")
                self._set_preview_ui(s[0], s[1], s[2])
        elif self._phase == 5 and self._kind == "result":
            self.accept()

    def _on_skip(self):
        """次要按钮逻辑"""
        if self._phase == 0:
            self.reject()
        elif self._kind == "running":
            # 取消当前步骤 → 回预览
            s = self.STEPS[self._phase - 1] if 0 <= self._phase - 1 < len(self.STEPS) else None
            if self._phase == 3:
                dname, dinst = self.HEAD_DIRS[self._sub]
                self._set_preview_ui(3, f"头部姿态 — {dname}", dinst)
            elif s:
                self._set_preview_ui(s[0], s[1], s[2])
        elif self._kind == "done":
            # 重测
            p = self._done_phase
            self._next = p
            if p == 3:
                self._phase = 3
                self._sub = 0
                self._head_peaks = []
                self._head_yaws = []
                self._head_pitches = []
                self._begin_head_dir()
            else:
                self._phase = p
                self._collected = []
                if p == 4:
                    self._blink_round = 1
                    self._blink_match_streak = 0
                    self._start_blink_round()
                    return
                self._t0 = time.time()
                self._dur = self.STEP_DUR
                s = self.STEPS[p - 1]
                self._set_running_ui(s[0], s[1], s[2], "")
                beep(800, 100)
        elif self._phase == 5 and self._kind == "result":
            self._set_welcome_ui()
            self.result_data = {}
        else:
            self._timer.stop()
            self._release_resources()
            self.reject()

    def _on_back(self):
        """上一步 — 从预览/完成返回上一步"""
        if self._phase == 3 and self._sub > 0:
            self._next = 3
            self._phase = 3
            self._kind = "done"
            self._done_phase = 3
            prev_sub = self._sub - 1
            self._sub = prev_sub
            dname, _ = self.HEAD_DIRS[prev_sub]
            self._set_done_ui(3, f"方向 {prev_sub + 1}/4 完成\n下一方向：{dname}")
            return

        if self._kind == "done":
            target = self._done_phase - 1
        elif self._kind == "preview":
            target = self._next - 1
        else:
            return

        if target <= 0:
            return
        self._next = target
        self._phase = target
        self._kind = "done"
        self._done_phase = target
        texts = {
            1: f"睁眼基线 EAR = {self._r_ear:.3f}",
            2: f"闭眼下限 EAR = {self._r_closed:.3f}",
            3: f"左右 ±{self._r_yaw:.0f}°  上下 ±{self._r_pitch:.0f}°",
            4: f"阈值 {self._ed.ear_threshold if self._ed else 0:.3f} · "
               f"通过 {self._blink_match_streak}/3",
        }
        self._set_done_ui(target, texts.get(target, ""))

    # ══════════════════════════════════════════════════════════════
    #  资源清理
    # ══════════════════════════════════════════════════════════════

    def _release_resources(self):
        if self._cam and self._own_cam:
            self._cam.release()
            self._cam = None
        if self._fd and self._own_fd:
            self._fd.close()
            self._fd = None
        if self._ed and self._own_ed:
            self._ed.close()
            self._ed = None

    def closeEvent(self, event):
        self._timer.stop()
        self._release_resources()
        event.accept()


# ═══════════════════════════════════════════════════════════════════
#  公共 API
# ═══════════════════════════════════════════════════════════════════

def run_calibration_dialog(parent=None, fd=None, ed=None) -> Optional[dict]:
    """运行校准对话框（共享检测器模式）

    Args:
        parent: 父窗口（可选）
        fd: FaceMeshDetector 实例（共享，为 None 则自动创建）
        ed: EyeAspectDetector 实例（共享，为 None 则自动创建）

    Returns:
        dict with baseline_ear/closed_ear/head_yaw_range/head_pitch_range，或 None（取消）
    """
    dialog = CalibrationDialog(parent, fd=fd, ed=ed)
    dialog._ensure_detectors()
    dialog._open_camera()
    dialog._start_preview()
    if dialog.exec_() == QDialog.Accepted:
        return dialog.result_data
    return None
