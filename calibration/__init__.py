"""calibration — 独立用户辅助校准模块（v4.2）

公共 API：仅一个入口
    from calibration import run
    result = run(session_id, config, db)
"""
from calibration.result import (
    CalibrationResult, CalibrationSignal, BlinkCalibrationRound,
)
from calibration.config import CalibrationConfig

__all__ = ["run", "CalibrationResult", "CalibrationSignal",
           "BlinkCalibrationRound", "CalibrationConfig"]


def run(
    session_id: str,
    config: "CalibrationConfig | None" = None,
    db=None,
):
    """运行完整校准流程，返回 Optional[CalibrationResult]。"""
    from calibration.flow import CalibrationFlow
    cfg = config or CalibrationConfig()
    flow = CalibrationFlow(session_id=session_id, config=cfg)
    return flow.run()
