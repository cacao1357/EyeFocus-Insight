
import sqlite3
import time
import cv2
import numpy as np
from storage.db import DatabaseManager, create_database_manager
from storage.models import BlinkEvent, FrameRecord
from detector.face_mesh import FaceMeshDetector, create_face_mesh_detector
from detector.eye_aspect import EyeAspectDetector, create_eye_aspect_detector
from detector.gaze import GazeDetector, create_gaze_detector
from detector.light import LightDetector, create_light_detector
from config import CAMERA

print("Initializing 3-min test...")

# Clean test DB
db = create_database_manager("data/test_3min.db")
db.initialize()
session_id = db.create_session()
print(f"Session: {session_id}")

# Init detectors
face_detector = create_face_mesh_detector()
eye_detector = create_eye_aspect_detector()
gaze_detector = create_gaze_detector()
light_detector = create_light_detector()

cap = cv2.VideoCapture(CAMERA.index)
if not cap.isOpened():
    print("ERROR: Cannot open camera")
    sys.exit(1)

start_time = time.time()
frame_count = 0
last_written_blink_count = 0
blink_detected_count = 0

print("Running 3-minute test (please blink naturally)...")

while time.time() - start_time < 180:  # 3 minutes
    ret, frame = cap.read()
    if not ret:
        continue
    
    timestamp_ms = int(time.time() * 1000)
    face_result = face_detector.detect_from_frame(frame, timestamp_ms)
    
    if not face_result.face_detected:
        continue
    
    landmarks = face_result.landmarks
    
    # EAR 计算
    eye_result = eye_detector.compute(landmarks)
    
    # 光照
    light_result = light_detector.analyze_frame(frame)
    
    # 视线
    gaze_result = gaze_detector.detect(
        landmarks=landmarks,
        head_pose_yaw=face_result.yaw or 0.0,
        head_pose_pitch=face_result.pitch or 0.0,
    )
    gaze_score = gaze_result.gaze_score if gaze_result else 100.0
    
    # 存储帧
    frame_record = FrameRecord(
        session_id=session_id,
        timestamp=time.time(),
        ear_left=eye_result.ear_left,
        ear_right=eye_result.ear_right,
        ear_avg=eye_result.ear_avg,
        yaw=face_result.yaw or 0.0,
        pitch=face_result.pitch or 0.0,
        roll=face_result.roll or 0.0,
        gaze_score=gaze_score,
        brightness=light_result.brightness,
        face_detected=face_result.face_detected,
        blendshapes=face_result.blendshapes,
    )
    db.write_frame(session_id, frame_record)
    
    # 存储眨眼事件
    blink_events = eye_detector.get_blink_events()
    new_blinks = blink_events[last_written_blink_count:]
    for event in new_blinks:
        db.write_blink_event(
            session_id,
            BlinkEvent(
                session_id=session_id,
                start_timestamp=event.start_time,
                end_timestamp=event.end_time,
                duration_seconds=event.duration,
                ear_nadir=event.ear_nadir,
            )
        )
        blink_detected_count += 1
    last_written_blink_count = len(blink_events)
    
    frame_count += 1
    
    if frame_count % 300 == 0:
        elapsed = time.time() - start_time
        print(f"  {elapsed:.0f}s: frames={frame_count}, blinks_detected={blink_detected_count}, blinks_written={last_written_blink_count}")

cap.release()
cv2.destroyAllWindows()

print()
print("=" * 50)
print("RESULTS")
print("=" * 50)
print(f"Frames: {frame_count}")
print(f"Blinks detected by algorithm: {blink_detected_count}")
print(f"Blinks in DB: {last_written_blink_count}")

# Verify no duplicates in DB
cur = db._conn.cursor()
cur.execute("SELECT COUNT(*) FROM blink_events")
db_blinks = cur.fetchone()[0]
cur.execute("SELECT COUNT(DISTINCT id) FROM blink_events")
distinct = cur.fetchone()[0]
print(f"DB blink count: {db_blinks}")
print(f"Distinct IDs: {distinct}")
print(f"Duplicates: {db_blinks - distinct}")

db.close()
print("Test complete!")
