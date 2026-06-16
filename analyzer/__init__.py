# analyzer package
from analyzer.focus import FocusAnalyzer, create_focus_analyzer
from analyzer.glasses import GlassesDetector, create_glasses_detector
from analyzer.fatigue import FatigueAnalyzer, create_fatigue_analyzer
from analyzer.voice_assistant import VoiceAssistant, create_voice_assistant
from analyzer.reminder_engine import ReminderEngine, create_reminder_engine
from analyzer.gamification import GamificationEngine, create_gamification_engine

# v4.1 Distraction 分心识别
try:
    from analyzer.distraction import analyze_distraction, DistractionResult as _DistractionResult
    _HAS_DISTRACTION = True
except ImportError:
    _HAS_DISTRACTION = False

# v4.1 Insights 离线分析（可选导入）
try:
    from analyzer.insights import run_pipeline, InsightsResult, SessionFeatures
    _HAS_INSIGHTS = True
except ImportError:
    _HAS_INSIGHTS = False

__all__ = [
    "FocusAnalyzer",
    "create_focus_analyzer",
    "GlassesDetector",
    "create_glasses_detector",
    "FatigueAnalyzer",
    "create_fatigue_analyzer",
]
if _HAS_DISTRACTION:
    __all__ += ["analyze_distraction"]
if _HAS_INSIGHTS:
    __all__ += ["run_pipeline", "InsightsResult", "SessionFeatures"]
