"""
webserver — EyeFocus Insight Web 仪表盘

提供：
- HTTP 静态文件服务（前端仪表盘）
- WebSocket 实时推送专注度数据
- 后台线程运行，不阻塞主程序

用法：
    from webserver import WebDashboard

    dashboard = WebDashboard(port=8080)
    dashboard.start()

    # 主循环中推送数据
    dashboard.broadcast({
        "focus_score": 78.5,
        "ear": 0.25,
        "fatigue": "normal",
        ...
    })

    dashboard.stop()
"""

from .server import WebDashboard

__all__ = ["WebDashboard"]
