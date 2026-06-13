"""test_distraction.py — 分心识别模块单元测试 (v4.1)

验证 analyzer/distraction.py 在合成帧数据上的正确性。
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import numpy as np
from unittest.mock import MagicMock

from analyzer.distraction import (
    analyze_distraction, DistractionResult, DistractionEvent,
    _is_distracted, _detect_events, _build_heatmap, _classify_pattern,
    GAZE_DISTRACTED_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════════
#  _is_distracted
# ═══════════════════════════════════════════════════════════════════

class TestIsDistracted:
    def test_high_gaze_face_present(self):
        """高 gaze_score + 有脸 → 不分心"""
        assert not _is_distracted(90.0, True)

    def test_low_gaze_face_present(self):
        """低 gaze_score + 有脸 → 分心"""
        assert _is_distracted(20.0, True)

    def test_high_gaze_no_face(self):
        """无脸 → 分心"""
        assert _is_distracted(90.0, False)

    def test_boundary_above(self):
        """阈值以上 → 不分心"""
        assert not _is_distracted(GAZE_DISTRACTED_THRESHOLD + 1, True)

    def test_boundary_below(self):
        """阈值以下 → 分心"""
        assert _is_distracted(GAZE_DISTRACTED_THRESHOLD - 1, True)


# ═══════════════════════════════════════════════════════════════════
#  _detect_events
# ═══════════════════════════════════════════════════════════════════

class TestDetectEvents:
    def test_no_distraction(self):
        """全集中 → 空事件列表"""
        frames = [(float(i), 90.0, True) for i in range(100)]
        events = _detect_events(frames)
        assert events == []

    def test_single_short_event(self):
        """单次短分心应被检出"""
        frames = [(float(i), 90.0, True) for i in range(30)]   # 集中
        frames += [(float(i), 20.0, True) for i in range(30, 40)]  # 分心 10s
        frames += [(float(i), 90.0, True) for i in range(40, 60)]
        events = _detect_events(frames)
        assert len(events) >= 1
        assert events[0].category == "short"
        assert 8 <= events[0].duration_seconds <= 12

    def test_long_event(self):
        """长分心应标记为 long"""
        frames = [(float(i), 20.0, True) for i in range(120)]  # 120s 分心
        events = _detect_events(frames)
        assert len(events) >= 1
        assert events[0].category == "long"

    def test_event_merge_gap(self):
        """间隔小于 MIN_EVENT_GAP_SEC 的应合并"""
        frames = []
        # 分心 5s → 集中 1s → 分心 5s (间隔 1s < 3s 应合并)
        for i in range(10):
            gaze = 20.0 if i < 5 or i >= 6 else 90.0
            frames.append((float(i), gaze, True))
        events = _detect_events(frames)
        assert len(events) == 1

    def test_ignore_short_burst(self):
        """< 3s 的分心不计为事件"""
        frames = [(float(i), 20.0, True) for i in range(2)]  # 仅 2s
        events = _detect_events(frames)
        assert len(events) == 0


# ═══════════════════════════════════════════════════════════════════
#  _build_heatmap
# ═══════════════════════════════════════════════════════════════════

class TestBuildHeatmap:
    def test_no_frames(self):
        """空帧 → 空热力图"""
        h, labels = _build_heatmap([], [])
        assert h == []
        assert labels == []

    def test_minute_boundaries(self):
        """每分钟应有对应的分心比例"""
        # 3 分钟数据: 第1分钟全分心, 第2分钟全集中, 第3分钟各半
        frames = []
        for i in range(180):
            ts = float(i)
            if i < 60:
                gaze = 20.0  # 分心
            elif i < 120:
                gaze = 90.0  # 集中
            else:
                gaze = 20.0 if i < 150 else 90.0
            frames.append((ts, gaze, True))
        h, labels = _build_heatmap(frames, [])
        assert len(h) == 3
        assert h[0] == 1.0  # 全分心
        assert h[1] == 0.0  # 全集中
        assert 0.4 <= h[2] <= 0.6  # 约一半


# ═══════════════════════════════════════════════════════════════════
#  _classify_pattern
# ═══════════════════════════════════════════════════════════════════

class TestClassifyPattern:
    def test_frequent_short(self):
        """频繁短分心 → pattern_type = frequent_short"""
        r = DistractionResult(detected=True, total_events=5,
                              total_distraction_seconds=40.0,
                              distraction_ratio=0.1,
                              n_frames_total=100, n_frames_distracted=10,
                              short_events=4, medium_events=1, long_events=0)
        _classify_pattern(r)
        assert r.pattern_type == "frequent_short"

    def test_long_breaks(self):
        """长分心 → pattern_type = long_breaks"""
        r = DistractionResult(detected=True, total_events=2,
                              total_distraction_seconds=180.0,
                              distraction_ratio=0.3,
                              n_frames_total=100, n_frames_distracted=30,
                              short_events=0, medium_events=1, long_events=1)
        _classify_pattern(r)
        assert r.pattern_type == "long_breaks"

    def test_intermittent(self):
        """其余 → intermittent"""
        r = DistractionResult(detected=True, total_events=3,
                              total_distraction_seconds=60.0,
                              distraction_ratio=0.1,
                              n_frames_total=100, n_frames_distracted=10,
                              short_events=1, medium_events=2, long_events=0)
        _classify_pattern(r)
        assert r.pattern_type == "intermittent"

    def test_no_events(self):
        """无事件 → pattern 不变"""
        r = DistractionResult(detected=False, total_events=0,
                              total_distraction_seconds=0.0,
                              distraction_ratio=0.0,
                              n_frames_total=0, n_frames_distracted=0)
        _classify_pattern(r)
        assert r.pattern_type is None


# ═══════════════════════════════════════════════════════════════════
#  analyze_distraction 集成
# ═══════════════════════════════════════════════════════════════════

class TestAnalyzeDistraction:
    def _make_mock_db(self, frames_data: list) -> MagicMock:
        """创建 mock DB，返回指定帧数据。"""
        db = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = frames_data
        db._get_cursor.return_value.__enter__.return_value = cursor
        return db

    def test_no_data(self):
        """无帧数据 → detected=False"""
        db = self._make_mock_db([])
        result = analyze_distraction(db, "test_session")
        assert not result.detected

    def test_fully_focused(self):
        """全集中 → detected=False"""
        frames = [{"timestamp": float(i), "gaze_score": 90.0, "face_detected": 1}
                   for i in range(100)]
        db = self._make_mock_db(frames)
        result = analyze_distraction(db, "test_session")
        assert not result.detected

    def test_partial_distraction(self):
        """部分分心 → detected=True + 正确统计"""
        frames = []
        for i in range(100):
            gaze = 20.0 if 30 <= i < 50 else 90.0  # 20s 分心
            frames.append({"timestamp": float(i), "gaze_score": gaze, "face_detected": 1})
        db = self._make_mock_db(frames)
        result = analyze_distraction(db, "test_session")
        assert result.detected
        assert result.total_events >= 1
        assert result.n_frames_total == 100
        assert result.n_frames_distracted == 20
        assert 0.19 <= result.distraction_ratio <= 0.21

    def test_heatmap_length(self):
        """热力图长度应与会话分钟数一致"""
        frames = [{"timestamp": float(i), "gaze_score": 90.0, "face_detected": 1}
                   for i in range(180)]  # 3 分钟
        db = self._make_mock_db(frames)
        result = analyze_distraction(db, "test_session")
        assert len(result.heatmap) >= 2
        assert len(result.heatmap_labels) == len(result.heatmap)
