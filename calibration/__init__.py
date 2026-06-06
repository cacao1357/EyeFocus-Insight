"""calibration — 独立用户辅助校准模块（v4.2）

公共 API：仅一个入口
    from calibration import run, is_exit_requested
    result = run(session_id, config, db)
    if result is None and is_exit_requested():
        # 用户点 × 关闭了校准窗口, 应退出整个程序
"""
from calibration.result import (
    CalibrationResult, CalibrationSignal, BlinkCalibrationRound,
)
from calibration.config import CalibrationConfig

# v4.4: 用户点窗口×关闭时置 True, 供 main.py 判断是否退出整个程序
_exit_requested: bool = False

__all__ = ["run", "CalibrationResult", "CalibrationSignal",
           "BlinkCalibrationRound", "CalibrationConfig", "is_exit_requested"]


def is_exit_requested() -> bool:
    """用户是否通过关闭校准窗口请求退出整个程序。"""
    return _exit_requested


def run(
    session_id: str,
    config: "CalibrationConfig | None" = None,
    db=None,
):
    """运行完整校准流程，返回 Optional[CalibrationResult]。"""
    from calibration.flow import CalibrationFlow
    cfg = config or CalibrationConfig()
    flow = CalibrationFlow(session_id=session_id, config=cfg)
    result = flow.run()
    # v4.4: 同步 × 关闭标志
    global _exit_requested
    _exit_requested = flow.exit_requested
    return result
