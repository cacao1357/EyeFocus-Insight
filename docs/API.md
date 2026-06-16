# EyeFocus Insight — API 文档

> **版本**：v1.0 | **日期**：2026-06-13
> **范围**：各模块的公共 API（`__init__.py` 导出）

---

## 一、detector/ — 信号采集

### FaceMeshDetector `detector.face_mesh`

```python
class FaceMeshDetector:
    def __init__(self, model_path: Optional[str] = None,
                 num_faces: int = 1,
                 min_detection_confidence: float = 0.5,
                 min_presence_confidence: float = 0.5,
                 min_tracking_confidence: float = 0.5)

    def detect_from_frame(self, frame: np.ndarray,
                          timestamp_ms: int) -> FaceDetectionResult

    def close(self, timeout: float = 2.0) -> None
```

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `detect_from_frame` | `frame`: BGR np.ndarray, `timestamp_ms`: int | `FaceDetectionResult` | 检测人脸关键点 + blendshapes |
| `close` | `timeout`: 超时秒数 (默认 2.0) | None | 异步关闭，守护线程 + 超时保护 |

```python
@dataclass
class FaceDetectionResult:
    face_detected: bool          # 是否检测到人脸
    landmarks: Optional[np.ndarray]  # (478, 2) 像素坐标
    blendshapes: Optional[dict]      # MediaPipe blendshapes 字典
    yaw: Optional[float]             # 头部偏航角（度）
    pitch: Optional[float]           # 头部俯仰角（度）
    roll: Optional[float]            # 头部翻滚角（度）
    face_rect: Optional[tuple]       # 人脸矩形 (x, y, w, h)
```

### EyeAspectDetector `detector.eye_aspect`

```python
class EyeAspectDetector:
    def __init__(self, ear_threshold: float = DEFAULT_EAR_THRESHOLD,
                 ear_min: float = DEFAULT_EAR_MIN,
                 squint_threshold: float = 0.3,
                 confirm_frames: int = 1, fps: float = 30.0,
                 baseline_ear: Optional[float] = None)

    def set_baseline(self, ear: float) -> None
    def set_adjustment_factor(self, factor: float) -> None
    def set_head_pose_weight(self, weight: float) -> None
    def set_face_stability_weight(self, weight: float) -> None
    def compute(self, landmarks: np.ndarray) -> EyeAspectResult
    def get_blink_rate(self, window_seconds: float = 60.0) -> tuple[float, int]
    def get_blink_events(self, since_time: Optional[float] = None,
                         until_time: Optional[float] = None) -> list[BlinkEvent]
```

### LightDetector `detector.light`

```python
class LightDetector:
    def __init__(self, brightness_thresh_dark: float = 50.0,
                 brightness_thresh_bright: float = 100.0,
                 face_region_ratio: float = 0.15,
                 smooth_window: int = 5)

    def analyze_frame(self, frame: np.ndarray) -> LightResult
    def get_smoothed_brightness(self) -> float
    def get_smoothed_condition(self) -> LightCondition
    def is_lighting_adequate(self) -> bool
    def reset(self) -> None
```

```python
@dataclass
class LightResult:
    condition: LightCondition      # DARK / NORMAL / BRIGHT
    brightness: float              # 平均亮度 (0-255)
    brightness_std: float
    face_region_brightness: float
    is_adequate: bool              # 光照是否满足检测要求
```

### HeadPoseDetector `detector.head_pose`

```python
class HeadPoseDetector:
    def detect(self, transformation_matrix: np.ndarray,
               yaw_thresh: float = 10.0,
               pitch_thresh: float = 20.0) -> HeadPoseResult
    def compute_stability(self) -> float
```

### GazeDetector `detector.gaze`

```python
class GazeDetector:
    def detect(self, landmarks: np.ndarray,
               head_pose_yaw: float = 0.0,
               head_pose_pitch: float = 0.0) -> GazeResult
```

```python
@dataclass
class GazeResult:
    gaze_concentration: float     # 视线集中度 (0-100)
    gaze_direction: str           # "center" / "left" / "right" / "up" / "down"
    left_eye_gaze: tuple          # 左眼视线向量 (x, y, z)
    right_eye_gaze: tuple         # 右眼视线向量 (x, y, z)
```

---

## 二、analyzer/ — 信号分析

### FocusAnalyzer `analyzer.focus`

```python
class FocusAnalyzer:
    def __init__(self, baseline_ear: float = 0.25,
                 baseline_yaw_std: float = 3.0,
                 baseline_pitch_std: float = 3.0,
                 eye_weight: float = 0.35,
                 head_weight: float = 0.30,
                 gaze_weight: float = 0.35,
                 window_size: float = 30.0,
                 fps: float = 30.0)

    def set_baseline(self, ear: float,
                     yaw_std: Optional[float] = None,
                     pitch_std: Optional[float] = None) -> None
    def set_blink_detector(self, blink_detector) -> None
    def analyze(self, ear: float, yaw: float = 0.0, pitch: float = 0.0,
                gaze_score: float = 100.0, brightness: float = 128.0,
                face_detected: bool = True) -> FocusResult
    def get_window_summary(self) -> Optional[FocusRecord]
```

```python
@dataclass
class FocusResult:
    focus_level: FocusLevel       # FOCUSED / NORMAL / DISTRACTED
    eye_openness: float           # 0.0-1.0
    eye_stability: float          # 0.0-1.0
    blink_rate: float             # 次/分钟
    is_attentive: bool
    focus_score: float            # 85 / 55 / 25（映射值）
```

### FatigueAnalyzer `analyzer.fatigue`

```python
class FatigueAnalyzer:
    def __init__(self, blink_rate_window: float = 60.0,
                 fatugue_history_window: int = 300)
    def analyze(self, blink_rate: float, ear_nadir: Optional[float],
                head_stability: float, avg_ear: float,
                blink_flag: bool) -> FatigueResult
```

### GlassesDetector `analyzer.glasses`

```python
class GlassesDetector:
    def __init__(self, squint_ratio_thresh: float = 0.85,
                 inner_canthus_ratio_thresh: float = 0.5,
                 squint_weight: float = 0.6, distance_weight: float = 0.4)

    def detect(self, landmarks: Optional[np.ndarray] = None,
               blendshapes: Optional[dict] = None) -> GlassesDetectionResult
    def set_manual_mode(self, mode: GlassesMode) -> None
    def clear_manual_mode(self) -> None
    def get_glasses_rate(self) -> float
    def reset(self) -> None
```

### DistractionAnalyzer `analyzer.distraction`

```python
def analyze_distraction(db: DatabaseManager, session_id: str) -> DistractionResult
```

```python
@dataclass
class DistractionEvent:
    start_time: float
    end_time: float
    duration: float
    category: str                 # short(3-15s) / medium(15-60s) / long(60s+)
    face_detected: bool
    gaze_score: Optional[float]

@dataclass
class DistractionResult:
    total_events: int
    total_duration: float
    distraction_ratio: float
    categories: dict              # {"short": N, "medium": N, "long": N}
    events: list[DistractionEvent]
    pattern_type: str             # frequent_short / intermittent / long_breaks
    heatmap: list[dict]
    distraction_rate: float
```

### Insights Pipeline `analyzer.insights`

```python
def run_pipeline(db: DatabaseManager, session_id: str) -> InsightsResult

@dataclass
class InsightsResult:
    pelt_result: dict             # 变点检测
    anomaly_result: dict          # 异常会话
    cluster_result: dict          # 行为聚类
    stl_result: dict              # 时间序列分解
    attributions: list            # 因素归因
    session_features: SessionFeatures
```

---

## 三、storage/ — 数据存储

### DatabaseManager `storage.database`

```python
class DatabaseManager:
    def __init__(self, db_path: str)

    # 会话管理
    def create_session(self, start_time: datetime,
                       is_active: bool = True) -> str
    def get_session(self, session_id: str) -> Optional[Session]
    def update_session(self, session_id: str, **kwargs) -> bool
    def list_sessions(self, limit: int = 100) -> list[Session]
    def close_session(self, session_id: str) -> None

    # 帧数据
    def save_frame_record(self, record: FrameRecord) -> int
    def get_frame_records(self, session_id: str) -> list[FrameRecord]
    def get_recent_frames(self, session_id: str,
                          limit: int = 1000) -> list[FrameRecord]

    # 疲劳数据
    def save_fatigue_record(self, record: FatigueRecord) -> int
    def get_fatigue_records(self, session_id: str) -> list[FatigueRecord]

    # 查询
    def get_all_sessions(self) -> list[Session]
    def query(self, sql: str, params: tuple = ()) -> list[dict]
    def close(self) -> None
```

### 数据模型 `storage.models`

```python
@dataclass
class Session:
    id: str                      # UUID
    start_time: datetime
    end_time: Optional[datetime]
    is_active: bool
    is_calibrated: bool
    baseline_ear: Optional[float]
    baseline_blink_rate: Optional[float]

@dataclass
class FrameRecord:
    session_id: str
    timestamp: float
    ear_left: float
    ear_right: float
    ear_avg: float
    yaw: float
    pitch: float
    roll: float
    gaze_score: float
    face_detected: bool
    is_blink: bool

@dataclass
class FatigueRecord:
    session_id: str
    timestamp: float
    fatigue_level: str            # LOW / MEDIUM / HIGH
    blink_rate: float
    avg_ear: float
    head_stability: float
```

---

## 四、gui/ — 用户界面

### EyeFocusWindow `gui.qt_window`

```python
class EyeFocusWindow(QMainWindow):
    exit_requested = pyqtSignal()
    calibrate_requested = pyqtSignal()

    def __init__(self, frame_buffer: FrameBuffer,
                 parent: Optional[QWidget] = None,
                 show_calibrate: bool = True)

    def start(self) -> None
    def stop(self) -> None
    def set_paused(self, paused: bool) -> None
    def is_paused(self) -> bool
    def set_face_lost_warning(self, visible: bool) -> None
    def update_data(self, focus_score=..., fatigue_level=...,
                    focus_level=..., fatigue_indicator=...,
                    focus_duration_minutes=..., face_detected=...,
                    eye_detected=..., fps=..., light_condition=...) -> None
    def update_data_from_processor(self, frame_processor, fps) -> None
```

### CalibrationDialog `gui.calibration_dialog`

```python
def run_calibration_dialog(fd: FaceMeshDetector,
                           ed: EyeAspectDetector) -> Optional[dict]
```

返回 `{"baseline_ear": float, "head_yaw_range": float, "head_pitch_range": float}`

### FocusRing `gui.qt_overlay`

```python
class FocusRing(QWidget):
    def update_data(self, focus_score=..., fatigue_level=...,
                    focus_level=..., fatigue_indicator=...) -> None
```

### StatusCard `gui.qt_overlay`

```python
class StatusCard(QWidget):
    def update_data(self, main_text="--", label_text="",
                    emoji="", status="ok") -> None
```

### FrameBuffer `gui.video_label`

```python
class FrameBuffer:
    def write(self, frame: np.ndarray) -> None
    def read(self) -> Optional[np.ndarray]
```

---

## 五、reporter/ — 报告生成

### HTMLReportGenerator `reporter.report_html`

```python
def create_html_generator(db: DatabaseManager) -> HTMLReportGenerator

class HTMLReportGenerator:
    def generate_report_with_insights(self, session_id: str) -> str
    def generate_report(self, session_id: str) -> str
```

### Charts `reporter.charts`

```python
def generate_focus_chart(session_id: str, db: DatabaseManager) -> str
def generate_fatigue_chart(session_id: str, db: DatabaseManager) -> str
def generate_distribution_chart(session_id: str, db: DatabaseManager) -> str
def generate_distraction_heatmap(heatmap: list, labels: list,
                                  pattern_type: str) -> str
```

各函数返回 base64 PNG 字符串（data:image/png;base64,...）。

### Insights `reporter.insights`

```python
def analyze_with_attributions(db, session_id, all_sessions) -> list[Insight]
def attribution_findings_to_insights(findings: list) -> list[Insight]
```

---

## 六、config.py — 配置

```python
@dataclass(frozen=True)
class CameraConfig:    index=0, min_fps=25.0
class FaceMeshConfig:  model_filename="face_landmarker.task", num_faces=1, ...
class HeadPoseConfig:  yaw_thresh=10.0, pitch_thresh=20.0, ...
class EyeConfig:       left_indices=..., right_indices=..., ear_min=0.08
class BaselineConfig:  collection_duration=7.0, trim_ratio=0.10, min_valid_frames=30, cqs_threshold=0.60
```

---

## 七、版本记录

| 版本 | 日期 | 变更内容 |
|:----:|:----:|---------|
| v1.0 | 2026-06-13 | 初始版本 |
