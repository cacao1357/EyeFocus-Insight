"""
gui/calibration_dialog.py — Qt 校准对话框 (v4.13)

v4.13:
  - 按钮位置固定：主按钮(深色)始终最右
  - 头部姿态每方向 3s，上一步回上一个方向
  - 完成页新增"上一步"按钮，导航更直观
"""
import time
import statistics
from typing import Optional

import cv2
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QWidget,
)


def beep(freq: int, dur: int):
    try:
        import winsound
        winsound.Beep(freq, dur)
    except Exception:
        pass


class CalibrationDialog(QDialog):

    BTN_PRIMARY = (
        "QPushButton {"
        "  background-color: #1A1A1A; color: #FFFFFF;"
        "  border: none; border-radius: 8px;"
        "  font-size: 15px; font-weight: 600; padding: 8px 22px;"
        "  min-height: 38px;"
        "}"
        "QPushButton:hover { background-color: #333333; }"
        "QPushButton:disabled {"
        "  color: #AAAAAA; background-color: #E0E0E0;"
        "}"
    )
    BTN_SECONDARY = (
        "QPushButton {"
        "  background-color: #FFFFFF; color: #555555;"
        "  border: 1.5px solid #BBBBBB; border-radius: 8px;"
        "  font-size: 14px; font-weight: 500; padding: 6px 16px;"
        "  min-height: 38px;"
        "}"
        "QPushButton:hover { background-color: #F5F5F5; border-color: #888888; }"
    )

    STEP_DUR = 4.0          # 步骤 1/2 时长
    HEAD_DIR_DUR = 3.0      # 头部姿态每方向时长
    BLINK_DUR = 10.0        # v4.13: 眨眼计数 10s

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
        self.resize(960, 720)
        self.setMinimumSize(800, 600)
        self.setStyleSheet("background-color: #000000;")
        self.result_data: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._vid = QLabel()
        self._vid.setAlignment(Qt.AlignCenter)
        self._vid.setStyleSheet("background-color: #000000;")
        root.addWidget(self._vid, 1)

        panel = QWidget()
        panel.setStyleSheet(
            "background-color: #FFFFFF; border-top: 1px solid #E0E0E0;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(24, 10, 24, 10)
        pl.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self._title = QLabel("")
        self._title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self._title.setStyleSheet("color: #000000; border: none;")
        row1.addWidget(self._title, 1)
        self._countdown = QLabel("")
        self._countdown.setFont(QFont("Segoe UI", 32, QFont.Bold))
        self._countdown.setStyleSheet("color: #000000; border: none;")
        self._countdown.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row1.addWidget(self._countdown, 0)
        pl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self._guide = QLabel("")
        self._guide.setFont(QFont("Segoe UI", 18))
        self._guide.setStyleSheet("color: #333333; border: none;")
        row2.addWidget(self._guide, 1)
        self._stat = QLabel("")
        self._stat.setFont(QFont("Segoe UI", 15))
        self._stat.setStyleSheet("color: #666666; border: none;")
        self._stat.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row2.addWidget(self._stat, 0)
        pl.addLayout(row2)

        # ── 按钮行：dots | back_btn | skip_btn | main_btn ──
        # main_btn(深色主按钮) 始终在最右
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        self._dots = QLabel("")
        self._dots.setTextFormat(Qt.RichText)
        self._dots.setFont(QFont("Segoe UI", 16))
        self._dots.setStyleSheet("color: #CCCCCC; border: none;")
        row3.addWidget(self._dots, 1)

        self._back_btn = QPushButton("上一步")
        self._back_btn.setStyleSheet(self.BTN_SECONDARY)
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.clicked.connect(self._on_back)
        self._back_btn.hide()
        row3.addWidget(self._back_btn, 0)

        self._skip_btn = QPushButton("")
        self._skip_btn.setStyleSheet(self.BTN_SECONDARY)
        self._skip_btn.setCursor(Qt.PointingHandCursor)
        self._skip_btn.clicked.connect(self._on_skip)
        row3.addWidget(self._skip_btn, 0)

        self._main_btn = QPushButton("")
        self._main_btn.setStyleSheet(self.BTN_PRIMARY)
        self._main_btn.setCursor(Qt.PointingHandCursor)
        self._main_btn.clicked.connect(self._on_main)
        row3.addWidget(self._main_btn, 0)

        pl.addLayout(row3)
        root.addWidget(panel, 0)

        self._cam = None
        self._own_cam = True
        self._fd = fd
        self._ed = ed
        self._own_fd = fd is None
        self._own_ed = ed is None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._phase = 0
        self._kind = ""
        self._t0 = 0.0
        self._dur = 0.0
        self._collected = []
        self._sub = 0
        self._next = 1
        self._done_phase = 0
        self._blink_start_count = 0
        self._blink_round = 0          # 当前第几轮验证
        self._blink_match_streak = 0   # 连续一致次数（需要3次）

        self._r_ear = 0.25
        self._r_closed = 0.08
        self._r_blink = 15.0
        self._r_yaw = 0.0
        self._r_pitch = 0.0
        self._user_blinks = 0
        self._head_yaws: list = []     # 当前方向原始 yaw
        self._head_pitches: list = []  # 当前方向原始 pitch
        self._head_peaks: list = []    # [(dir_name, max_abs_yaw, max_abs_pitch)]
        self._cal_start_time = 0.0     # 校准开始时间戳（步骤1起算）

        self._set_welcome_ui()

    # ════════════════════════════════════════
    #  资源管理
    # ════════════════════════════════════════

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

    # ════════════════════════════════════════
    #  显示辅助
    # ════════════════════════════════════════

    def _set_dots(self, active: int):
        parts = []
        for i in range(4):
            n = i + 1
            if n < active:
                parts.append('<span style="color:#34C759;">●</span>')
            elif n == active:
                parts.append('<span style="color:#34C759;">●</span>')
            else:
                parts.append('<span style="color:#CCCCCC;">○</span>')
        self._dots.setText(" ".join(parts))

    def _set_welcome_ui(self):
        self._phase = 0
        self._kind = ""
        self._title.setText("准备开始校准")
        self._guide.setText("请面对摄像头，确保光线充足")
        self._stat.setText("约 30 秒 · 4 个步骤")
        self._countdown.setText("")
        self._dots.setText('<span style="color:#CCCCCC;">○ ○ ○ ○</span>')
        self._main_btn.setText("开始校准")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(self.BTN_PRIMARY)
        self._skip_btn.hide()
        self._back_btn.hide()

    def _set_preview_ui(self, step: int, name: str, guide: str):
        self._kind = "preview"
        self._title.setText(f"步骤 {step}/4 — {name}")
        self._guide.setText(guide)
        self._stat.setText("")
        self._countdown.setText("")
        self._set_dots(step)
        self._main_btn.setText("开始")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(self.BTN_PRIMARY)
        self._skip_btn.hide()
        # v4.13: 步骤2+且非step3首方向→显示上一步
        is_dir_first = (step == 3 and self._phase == 3 and self._sub == 0)
        if step > 1 and not is_dir_first:
            self._back_btn.show()
        else:
            self._back_btn.hide()

    def _set_running_ui(self, step: int, name: str, guide: str, stat: str):
        self._kind = "running"
        self._title.setText(f"步骤 {step}/4 — {name}")
        self._guide.setText(guide)
        self._stat.setText(stat)
        self._main_btn.setText("校准中...")
        self._main_btn.setEnabled(False)
        self._main_btn.setStyleSheet(self.BTN_PRIMARY)
        self._skip_btn.setText("取消")
        self._skip_btn.setEnabled(True)
        self._skip_btn.show()
        self._back_btn.hide()

    def _set_done_ui(self, step: int, result_text: str):
        self._kind = "done"
        self._done_phase = self._phase
        self._title.setText(f"✓ 步骤 {step}/4 完成")
        self._guide.setText(result_text)
        self._stat.setText("")
        self._countdown.setText("")
        self._main_btn.setText("继续")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(self.BTN_PRIMARY)
        self._skip_btn.setText("重测")
        self._skip_btn.setEnabled(True)
        self._skip_btn.show()
        self._back_btn.show()

    # ════════════════════════════════════════
    #  流程控制
    # ════════════════════════════════════════

    def _start(self):
        self._cal_start_time = time.time()
        self._phase = -1
        self._next = 1
        s = self.STEPS[0]
        self._set_preview_ui(s[0], s[1], s[2])

    def _start_blink_round(self):
        """开始新一轮眨眼验证（10s）"""
        self._blink_start_count = len(self._ed._blink_events) if self._ed else 0
        self._t0 = time.time()
        self._dur = self.BLINK_DUR
        r = self._blink_round
        self._set_running_ui(4, self.STEPS[3][1],
            self.STEPS[3][2],
            f"第 {r} 轮 · 已确认 {self._blink_match_streak}/3")
        beep(800, 100)

    def _begin_step(self):
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
        dname, dinst = self.HEAD_DIRS[self._sub]
        self._t0 = time.time()
        self._dur = self.HEAD_DIR_DUR
        self._set_running_ui(3, f"头部姿态 — {dname}", dinst,
                             f"方向 {self._sub + 1}/4")
        beep(800, 100)

    # ════════════════════════════════════════
    #  帧循环
    # ════════════════════════════════════════

    def _tick(self):
        if self._cam is None:
            return
        ret, frame = self._cam.read()
        if not ret:
            return

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self._vid.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._vid.setPixmap(pixmap)

        if self._kind != "running":
            return

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
            # 采信所有数据——用户已被告知闭眼，不做阈值过滤
            if ear is not None:
                self._collected.append(ear)
            self._stat.setText(f"闭眼帧 {len(self._collected)}")
        elif self._phase == 3:
            if fr and fr.face_detected:
                self._head_yaws.append(yaw)
                self._head_pitches.append(pitch)
        elif self._phase == 4:
            self._stat.setText("记录中...")

        if elapsed >= self._dur:
            self._finish_step()

    # ════════════════════════════════════════
    #  步骤完成
    # ════════════════════════════════════════

    def _finish_step(self):
        self._kind = ""
        self._countdown.setText("")
        beep(1000, 250)

        if self._phase == 1:
            if len(self._collected) >= 5:
                self._r_ear = statistics.median(self._collected)
            self._next = 2
            self._set_done_ui(1, f"睁眼基线 EAR = {self._r_ear:.3f}\n"
                              f"共采集 {len(self._collected)} 个样本")
        elif self._phase == 2:
            self._r_closed = min(self._collected) if self._collected else 0.08
            self._next = 3
            # 用睁眼/闭眼数据注入初始阈值 → 步骤3的自然眨眼检测才有据可依
            init_thr = self._r_closed + (self._r_ear - self._r_closed) * 0.35
            self._ed.ear_threshold = round(init_thr, 4)
            self._ed._has_baseline = True
            self._set_done_ui(2, f"闭眼下限 EAR = {self._r_closed:.3f}\n"
                              f"初始阈值={init_thr:.3f}\n"
                              f"共 {len(self._collected)} 帧")
        elif self._phase == 3:
            # 计算当前方向的峰值（取绝对值最大的）
            dir_name = self.HEAD_DIRS[self._sub][0]
            peak_yaw = max((abs(v) for v in self._head_yaws), default=0.0)
            peak_pitch = max((abs(v) for v in self._head_pitches), default=0.0)
            self._head_peaks.append((dir_name, peak_yaw, peak_pitch))

            self._sub += 1
            if self._sub < len(self.HEAD_DIRS):
                dname, dinst = self.HEAD_DIRS[self._sub]
                self._next = 3
                self._head_yaws = []
                self._head_pitches = []
                self._set_done_ui(3, f"方向 {self._sub}/4 完成\n"
                                  f"下一方向：{dname} {dinst}")
            else:
                all_yaws = [p[1] for p in self._head_peaks]
                all_pitches = [p[2] for p in self._head_peaks]
                self._r_yaw = max(all_yaws) if all_yaws else 0.0
                self._r_pitch = max(all_pitches) if all_pitches else 0.0

                # ── 从步骤1-3真实眨眼反推阈值 + 自然眨眼频率 ──
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

            # ── 验证对话框 ──
            DIALOG_STYLE = (
                "QDialog { background-color: #FFFFFF; }"
                "* { background-color: #FFFFFF; }"
                "QLabel { color: #000000; background-color: #FFFFFF;"
                "  font-size: 15px; font-family: 'Segoe UI'; border: none; }"
                "QPushButton { background-color: #FFFFFF; color: #555555;"
                "  border: 1.5px solid #BBBBBB; border-radius: 8px;"
                "  font-size: 14px; padding: 6px 16px; min-height: 38px; }"
                "QPushButton:hover { background-color: #F5F5F5; }"
                "QLineEdit { background-color: #FFFFFF; color: #000000;"
                "  border: 1.5px solid #BBBBBB; border-radius: 6px;"
                "  font-size: 20px; padding: 6px 10px; }"
            )

            def _show_verify_dialog(detect_n: int, round_n: int, streak: int):
                from PyQt5.QtWidgets import QDialog as _QD
                from PyQt5.QtWidgets import QHBoxLayout as _HL, QVBoxLayout as _VL, QLineEdit
                dlg = _QD(self)
                dlg.setWindowTitle(f"阈值校验 · 第{round_n}轮")
                dlg.setMinimumWidth(340)
                dlg.setStyleSheet(DIALOG_STYLE)
                dl = _VL(dlg)
                dl.setContentsMargins(24, 20, 24, 16)
                dl.setSpacing(14)
                msg = QLabel(
                    f"第 {round_n} 轮 · 已确认 {streak}/3\n"
                    f"10s 检测到 {detect_n} 次眨眼\n\n"
                    f"和你实际感觉一致吗？"
                )
                dl.addWidget(msg)
                bl = _HL()
                bl.setSpacing(10)
                bl.addStretch()
                no_btn = QPushButton("不一致，我输入")
                no_btn.setStyleSheet(
                    "QPushButton { background-color: #FFFFFF; color: #555555;"
                    "  border: 1.5px solid #BBBBBB; border-radius: 8px;"
                    "  font-size: 14px; padding: 6px 16px; min-height: 38px; }"
                    "QPushButton:hover { background-color: #F5F5F5; }"
                )
                yes_btn = QPushButton("一致")
                yes_btn.setStyleSheet(self.BTN_PRIMARY)
                bl.addWidget(no_btn)
                bl.addWidget(yes_btn)
                dl.addLayout(bl)
                no_btn.clicked.connect(lambda: dlg.done(2))
                yes_btn.clicked.connect(dlg.accept)
                result = dlg.exec_()

                if result == _QD.Accepted:
                    return detect_n  # 一致
                # 不一致：输入实际次数
                d2 = _QD(self)
                d2.setWindowTitle("输入实际次数")
                d2.setMinimumWidth(280)
                d2.setStyleSheet(DIALOG_STYLE)
                d2l = _VL(d2)
                d2l.setContentsMargins(24, 16, 24, 12)
                d2l.setSpacing(10)
                lb = QLabel("你实际眨眼多少次？")
                lb.setStyleSheet(
                    "color: #000000; background-color: #FFFFFF;"
                    "font-size: 15px; font-family: 'Segoe UI'; border: none;")
                d2l.addWidget(lb)
                le = QLineEdit(str(max(1, detect_n)))
                le.setStyleSheet(
                    "QLineEdit { background-color: #FFFFFF; color: #000000;"
                    "  border: 1.5px solid #BBBBBB; border-radius: 6px;"
                    "  font-size: 20px; padding: 6px 10px; }"
                )
                le.setAlignment(Qt.AlignCenter)
                le.setMaxLength(3)
                d2l.addWidget(le)
                d2bl = _HL()
                d2bl.setSpacing(10)
                d2bl.addStretch()
                d2_ok = QPushButton("确定")
                d2_ok.setStyleSheet(self.BTN_PRIMARY)
                d2_ok.clicked.connect(d2.accept)
                d2bl.addWidget(d2_ok)
                d2l.addLayout(d2bl)
                if d2.exec_() == _QD.Accepted:
                    try:
                        return int(le.text())
                    except ValueError:
                        return detect_n
                return detect_n

            user_n = _show_verify_dialog(detected, self._blink_round, self._blink_match_streak)

            if user_n == detected:
                self._blink_match_streak += 1
                if self._blink_match_streak >= 3:
                    # 三次连续一致 → 通过
                    self._next = 5
                    self._set_done_ui(4,
                        f"✓ 阈值 {self._ed.ear_threshold:.3f} 验证通过\n"
                        f"连续 {self._blink_match_streak} 次一致")
                    return
                # 未满3次 → 下一轮
                self._blink_round += 1
                self._start_blink_round()
                return
            else:
                # 不一致 → 修正阈值（控制步长，防极端值），归零计数器
                if self._ed.ear_threshold <= 0 or detected == 0:
                    # 阈值已失序：重置到安全中值
                    self._ed.ear_threshold = round(
                        self._r_closed + (self._r_ear - self._r_closed) * 0.4, 4)
                elif detected < user_n:
                    # 检测偏少 → 阈值偏低 → 上调（更灵敏）
                    self._ed.ear_threshold = round(
                        self._ed.ear_threshold * 1.15, 4)
                else:
                    # 检测偏多 → 阈值偏高 → 下调
                    self._ed.ear_threshold = round(
                        self._ed.ear_threshold * 0.85, 4)
                # 硬边界：阈值必须在闭眼和睁眼之间
                lo = self._r_closed * 0.9
                hi = self._r_ear * 0.85
                self._ed.ear_threshold = round(
                    max(lo, min(hi, self._ed.ear_threshold)), 4)
                self._blink_match_streak = 0
                self._blink_round += 1
                self._start_blink_round()
                return

    # ════════════════════════════════════════
    #  结果页
    # ════════════════════════════════════════

    def _show_result(self):
        self._phase = 5
        self._kind = ""
        self._countdown.setText("")
        beep(600, 500)

        self._title.setText("✓ 校准完成")
        self._guide.setText(
            f"睁眼基线 {self._r_ear:.3f}  闭眼下限 {self._r_closed:.3f}\n"
            f"左右 ±{self._r_yaw:.0f}°  上下 ±{self._r_pitch:.0f}°\n"
            f"眨眼阈值 {self._ed.ear_threshold if self._ed else 0:.3f}"
        )
        self._stat.setText("")
        self._dots.setText("")
        self._main_btn.setText("进入监测")
        self._main_btn.setEnabled(True)
        self._main_btn.setStyleSheet(self.BTN_PRIMARY)
        self._skip_btn.setText("重新校准")
        self._skip_btn.setEnabled(True)
        self._back_btn.hide()

        self.result_data = {
            "baseline_ear": self._r_ear,
            "closed_ear": self._r_closed,
            "head_yaw_range": self._r_yaw,
            "head_pitch_range": self._r_pitch,
        }

    # ════════════════════════════════════════
    #  按钮回调
    # ════════════════════════════════════════

    def _on_main(self):
        if self._phase == 0:
            self._start()
        elif self._kind == "preview":
            self._begin_step()
        elif self._kind == "done":
            p = self._next
            if p == 5:
                self._show_result()
            elif p == 3:
                if self._phase == 3 and self._sub < len(self.HEAD_DIRS):
                    dname, dinst = self.HEAD_DIRS[self._sub]
                    self._set_preview_ui(3, f"头部姿态 — {dname}", dinst)
                else:
                    self._sub = 0
                    self._head_peaks = []
                    self._set_preview_ui(3, "头部姿态", "请按提示转动头部")
            else:
                s = self.STEPS[p - 1]
                self._set_preview_ui(s[0], s[1], s[2])
        elif self._phase == 5:
            self.accept()

    def _on_skip(self):
        if self._phase == 0:
            self.reject()
        elif self._kind == "running":
            s = self.STEPS[self._phase - 1]
            if self._phase == 3:
                dname, dinst = self.HEAD_DIRS[self._sub]
                self._set_preview_ui(3, f"头部姿态 — {dname}", dinst)
            else:
                self._set_preview_ui(s[0], s[1], s[2])
        elif self._kind == "done":
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
        elif self._phase == 5:
            self._set_welcome_ui()
            self.result_data = {}
        else:
            self._timer.stop()
            self._release_resources()
            self.reject()

    def _on_back(self):
        """上一步 — 从 preview/done 返回上一个步骤的 done 页"""
        # 头部姿态中途：回上一个方向，而非上一个大阶段
        if self._phase == 3 and self._sub > 0:
            self._next = 3
            self._phase = 3
            self._kind = "done"
            self._done_phase = 3
            # 回到上一个方向
            prev_sub = self._sub - 1
            self._sub = prev_sub
            dname, _ = self.HEAD_DIRS[prev_sub]
            self._set_done_ui(3, f"方向 {prev_sub + 1}/4 完成\n"
                              f"下一方向：{dname}")
            return

        # 从 done 状态回退
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
        if target == 1:
            self._set_done_ui(1, f"睁眼基线 EAR = {self._r_ear:.3f}")
        elif target == 2:
            self._set_done_ui(2, f"闭眼下限 EAR = {self._r_closed:.3f}")
        elif target == 3:
            self._set_done_ui(3,
                f"左右 ±{self._r_yaw:.0f}°  上下 ±{self._r_pitch:.0f}°")
        elif target == 4:
            self._set_done_ui(4,
                f"阈值 {self._ed.ear_threshold if self._ed else 0:.3f} · "
                f"通过 {self._blink_match_streak}/3")

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


def run_calibration_dialog(parent=None, fd=None, ed=None) -> Optional[dict]:
    dialog = CalibrationDialog(parent, fd=fd, ed=ed)
    dialog._ensure_detectors()
    dialog._open_camera()
    dialog._start_preview()
    if dialog.exec_() == QDialog.Accepted:
        return dialog.result_data
    return None
