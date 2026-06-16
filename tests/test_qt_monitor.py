"""
test_qt_monitor.py — PyQt5 监测模式 (v4.6.2)

v4.6.2:
  - 看门狗线程：检测主线程卡死并报告
  - 定期 GC：防止内存累积导致大停顿
  - 校准对接：释放资源→校准→应用基线→恢复
  - 资源清理：MediaPipe Image 显式释放
"""
import sys, os, time, threading, csv, gc
from datetime import datetime
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_qt_plugins = os.path.abspath('.venv312/Lib/site-packages/PyQt5/Qt5/plugins')
if os.path.isdir(_qt_plugins):
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', _qt_plugins)

from gui import EyeFocusWindow, FrameBuffer
from detector.face_mesh import create_face_mesh_detector
from detector.eye_aspect import create_eye_aspect_detector
from analyzer.focus import create_focus_analyzer
from analyzer.fatigue import create_fatigue_analyzer

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
import cv2
import numpy as np


# ═══════════════════════════════════════════════════
# v4.6.2: 主线程卡死看门狗
# ═══════════════════════════════════════════════════

class Watchdog:
    """后台线程监控帧处理——若超时未更新则报告"""

    def __init__(self, timeout_seconds: float = 3.0):
        self._timeout = timeout_seconds
        self._last_heartbeat = time.time()
        self._lock = threading.Lock()
        self._running = True
        self._warnings: deque = deque(maxlen=20)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def heartbeat(self):
        with self._lock:
            self._last_heartbeat = time.time()

    def _loop(self):
        while self._running:
            time.sleep(1.0)
            with self._lock:
                gap = time.time() - self._last_heartbeat
            if gap > self._timeout:
                msg = f"⚠ 主线程卡死 {gap:.1f}s! (阈值 {self._timeout}s)"
                self._warnings.append((time.time(), msg))
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()

    def stop(self):
        self._running = False

    @property
    def warning_count(self) -> int:
        return len(self._warnings)


# ═══════════════════════════════════════════════════
# CSV 数据记录器
# ═══════════════════════════════════════════════════

class DataLogger:
    """每秒记录一行监测数据到 CSV"""

    COLUMNS = [
        "timestamp", "elapsed_s",
        "focus_level", "fatigue_indicator",
        "ear", "blink_rate", "prolonged_closures_3min",
        "face_detected"
    ]

    def __init__(self, output_dir: str = "data"):
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = os.path.join(output_dir, f"monitoring_{ts}.csv")
        self._file = open(self._path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(self.COLUMNS)
        self._start_time = time.time()
        self._last_write_second = -1
        print(f"数据记录: {self._path}")

    def log(self, focus_level, fatigue_indicator, ear, blink_rate,
            prolonged_count, face_detected):
        current_second = int(time.time() - self._start_time)
        if current_second <= self._last_write_second:
            return
        self._last_write_second = current_second
        self._writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            current_second,
            focus_level.value if hasattr(focus_level, 'value') else str(focus_level),
            fatigue_indicator.value if hasattr(fatigue_indicator, 'value') else str(fatigue_indicator),
            f"{ear:.4f}" if ear is not None else "",
            f"{blink_rate:.2f}" if blink_rate else "0",
            prolonged_count,
            "1" if face_detected else "0",
        ])
        self._file.flush()

    @property
    def path(self) -> str:
        return self._path

    def close(self):
        if self._file and not self._file.closed:
            self._file.close()
            print(f"数据已保存: {self._path} ({self._last_write_second + 1} 行)")


# ═══════════════════════════════════════════════════
# 后台摄像头
# ═══════════════════════════════════════════════════

class CameraReader:
    """后台线程持续读取摄像头"""

    def __init__(self, camera_index: int = 0):
        self._cap = cv2.VideoCapture(camera_index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._running = True
        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            ret, frame = self._cap.read()
            if ret:
                with self._lock:
                    self._latest_frame = frame
            else:
                time.sleep(0.005)

    def get_frame(self) -> np.ndarray | None:
        with self._lock:
            return self._latest_frame

    def release(self) -> None:
        self._running = False
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._cap.release()


# ═══════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════

def main():
    # ⚠️ QApplication 必须在任何 Qt 窗口之前创建
    app = QApplication(sys.argv)

    # ── v4.12: 检测器只创建一次（校准+监测共享，防止重复初始化致精度丢失）──
    print("初始化检测器...")
    fd = create_face_mesh_detector()
    ed = create_eye_aspect_detector()

    # ── 先运行校准（传入检测器共享实例）──
    from gui.calibration_dialog import run_calibration_dialog
    calib_result = run_calibration_dialog(fd=fd, ed=ed)

    # ── 创建分析器（使用同一检测器实例）──
    focus_analyzer = create_focus_analyzer()
    focus_analyzer.set_blink_detector(ed)
    fatigue_analyzer = create_fatigue_analyzer()
    fatigue_analyzer.start()
    face_detector = [fd]  # 保持兼容性

    # 校准完成后重新打开摄像头
    camera = None
    for attempt in range(3):
        cam = CameraReader(0)
        time.sleep(0.5)
        if cam.get_frame() is not None:
            camera = cam
            print(f"摄像头就绪 (尝试 {attempt + 1})")
            break
        print(f"摄像头未就绪，重试 {attempt + 1}/3...")
        cam.release()
        time.sleep(0.5)

    if camera is None:
        print("⚠ 摄像头无法打开")
        face_detector[0].close()
        return
    frame_buffer = FrameBuffer()
    window = EyeFocusWindow(frame_buffer, show_calibrate=False)  # 已校准，不显示校准按钮
    window.setWindowTitle("EyeFocus Insight")
    window.exit_requested.connect(app.quit)

    # 自动基线变量（必须在 calib_result 检查前初始化）
    auto_baseline_done = [False]
    auto_baseline_start = [time.time()]
    auto_baseline_samples = []

    # v4.13: 应用校准结果
    # 校准模块已产生个性化阈值（基于睁眼+闭眼实测值），不覆写公式值
    if calib_result:
        baseline_ear = calib_result.get("baseline_ear", 0.25)
        closed_ear = calib_result.get("closed_ear", 0.08)
        head_yaw = calib_result.get("head_yaw_range", 0.0)
        head_pitch = calib_result.get("head_pitch_range", 0.0)

        # 专注度分析器：EAR 基线 + 头部姿态范围
        focus_analyzer.set_baseline(
            ear=baseline_ear,
            yaw_std=head_yaw / 2.0 if head_yaw > 0 else None,
            pitch_std=head_pitch / 2.0 if head_pitch > 0 else None,
        )
        # 眨眼阈值：已在校准步骤2/3中注入 _ed，不调 set_baseline

        auto_baseline_done[0] = True
        print(f"校准基线已应用: EAR={baseline_ear:.3f} 闭眼={closed_ear:.3f} "
              f"头±{head_yaw:.0f}°/{head_pitch:.0f}°")
    else:
        print("校准已跳过 — 将使用自动基线")

    # 看门狗 + 数据记录
    wd = Watchdog(timeout_seconds=3.0)
    dl = DataLogger(output_dir="data")
    gc_counter = [0]
    gc_interval = 300

    # FPS 等状态
    fps_counter = [0]
    fps_last = [time.time()]
    fps_val = [0.0]
    focus_start_time = [None]
    frame_busy = [False]
    skip_count = [0]

    # ── 帧处理 ──
    def update_frame():
        if frame_busy[0]:
            skip_count[0] += 1
            return
        frame_busy[0] = True
        try:
            f = camera.get_frame() if camera else None
            if f is None:
                return
            frame_buffer.write(f)

            timestamp_ms = int(time.time() * 1000)
            face_result = face_detector[0].detect_from_frame(f, timestamp_ms)

            if face_result and face_result.face_detected:
                eye_result = ed.compute(face_result.landmarks)
                ear = eye_result.ear_avg
                closure_type = ed.get_closure_type()

                # 自动基线 (15s)
                if not auto_baseline_done[0]:
                    elapsed = time.time() - auto_baseline_start[0]
                    if elapsed < 15.0:
                        if closure_type == "open" and ear > 0.15:
                            auto_baseline_samples.append(ear)
                    else:
                        if len(auto_baseline_samples) >= 30:
                            import statistics
                            median_ear = statistics.median(auto_baseline_samples)
                            focus_analyzer.set_baseline(ear=median_ear)
                            ed.set_baseline(ear=median_ear)
                            print(f"基线同步: EAR={median_ear:.3f} (n={len(auto_baseline_samples)})")
                        auto_baseline_done[0] = True

                focus_result = focus_analyzer.analyze(
                    ear=ear, yaw=face_result.yaw or 0.0,
                    pitch=face_result.pitch or 0.0, face_detected=True)
                fatigue_result = fatigue_analyzer.analyze(
                    closure_type=closure_type,
                    blink_rate=focus_result.blink_rate if focus_result else 0,
                    avg_ear=ear)

                fl = focus_result.focus_level if focus_result else None
                fi = fatigue_result.fatigue_indicator if fatigue_result else None

                now = time.time()
                if focus_start_time[0] is None:
                    focus_start_time[0] = now
                dur = (now - focus_start_time[0]) / 60.0

                dl.log(fl, fi, ear,
                       focus_result.blink_rate if focus_result else 0,
                       fatigue_result.prolonged_closures_3min if fatigue_result else 0,
                       True)

                window.update_data(
                    focus_level=fl, fatigue_indicator=fi,
                    focus_duration_minutes=dur,
                    face_detected=True, eye_detected=True, fps=fps_val[0])
            else:
                focus_start_time[0] = None
                dl.log(None, None, None, 0, 0, False)
                window.update_data(
                    focus_level=None, fatigue_indicator=None,
                    focus_duration_minutes=None,
                    face_detected=False, eye_detected=False, fps=fps_val[0])

            # FPS + GC
            fps_counter[0] += 1
            gc_counter[0] += 1
            elapsed = time.time() - fps_last[0]
            if elapsed >= 1.0:
                fps_val[0] = fps_counter[0] / elapsed
                fps_counter[0] = 0
                fps_last[0] = time.time()
            if gc_counter[0] >= gc_interval:
                gc.collect()
                gc_counter[0] = 0

            # 看门狗心跳
            wd.heartbeat()

        except Exception as e:
            import traceback
            sys.stderr.write(f"Frame error: {e}\n")
            traceback.print_exc()
        finally:
            frame_busy[0] = False

    timer = QTimer()
    timer.timeout.connect(update_frame)
    timer.start(33)

    window.start()
    window.show()
    window.raise_()
    window.activateWindow()
    print(f"窗口已启动 — 暂停·校准 按钮可用 | 看门狗={wd._timeout}s | GC={gc_interval}帧")

    app.exec_()

    # 清理
    timer.stop()
    wd.stop()
    dl.close()
    if camera is not None:
        camera.release()
    face_detector[0].close()
    gc.collect()
    print(f"已退出 (跳过:{skip_count[0]} 看门狗警告:{wd.warning_count})")


if __name__ == "__main__":
    main()
