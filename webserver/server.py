"""
webserver/server.py — aiohttp WebSocket 实时数据推送服务

在后台线程运行，与主程序 EyeFocusApp 通过队列通信。
主程序每秒推送一次专注度数据，Web 客户端实时展示。
"""

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Set

import aiohttp.web

logger = logging.getLogger("eyefocus.webserver")


class WebDashboard:
    """Web 仪表盘 — 实时专注度数据可视化 (v4.26: +控制)

    用法：
        dashboard = WebDashboard(port=8080)
        dashboard.start()
        dashboard.broadcast({"focus_score": 85, ...})
        dashboard.on("pause", lambda: ...)
        dashboard.stop()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self._host = host
        self._port = port
        self._app: Optional[aiohttp.web.Application] = None
        self._runner: Optional[aiohttp.web.AppRunner] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws_clients: Set[aiohttp.web.WebSocketResponse] = set()
        self._latest_data: Dict[str, Any] = {"status": "initializing"}
        self._history: list = []  # 最近 120 个数据点
        self._running: bool = False
        self._db: Any = None  # 数据库引用，供历史查询用
        # v4.26: 控制回调
        self._callbacks: Dict[str, callable] = {}

    def set_db(self, db: Any) -> None:
        """设置数据库引用（用于历史会话查询）"""
        self._db = db

    # ── v4.26: 控制回调 ──

    def on(self, action: str, callback: callable) -> None:
        """注册控制回调

        Args:
            action: "pause" | "resume" | "calibrate" | "toggle_pause"
            callback: 无参函数
        """
        self._callbacks[action] = callback
        logger.debug("Web 控制: 注册回调 '%s'", action)

    def _exec_callback(self, action: str) -> bool:
        """执行控制回调，返回是否找到并执行"""
        cb = self._callbacks.get(action)
        if cb:
            try:
                cb()
                return True
            except Exception as e:
                logger.warning("Web 控制回调 '%s' 执行失败: %s", action, e)
                return False
        logger.warning("Web 控制: 未注册回调 '%s'", action)
        return False

    # ── 公共 API ──

    def start(self) -> bool:
        """在后台线程启动 Web 服务器"""
        if self._running:
            logger.warning("WebDashboard 已在运行")
            return True

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="web-dashboard",
        )
        self._thread.start()
        logger.info("Web 仪表盘启动: http://%s:%d", self._host, self._port)
        return True

    def stop(self) -> None:
        """停止 Web 服务器"""
        self._running = False
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

    def broadcast(self, data: Dict[str, Any]) -> None:
        """广播数据到所有连接的 WebSocket 客户端

        在主线程调用，线程安全。
        """
        self._latest_data = data

        # 维护历史（60s @ 1点/s）
        self._history.append(data)
        if len(self._history) > 120:
            self._history = self._history[-120:]

        # 附加上历史数据
        payload = {
            "current": data,
            "history": self._history[-60:],
            "timestamp": time.time(),
        }

        if self._loop and not self._loop.is_closed() and self._ws_clients:
            asyncio.run_coroutine_threadsafe(
                self._broadcast_ws(payload), self._loop
            )

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def is_running(self) -> bool:
        return self._running

    # ── 后台线程 ──

    def _run_loop(self) -> None:
        """后台线程：创建和运行 aiohttp 服务器"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._app = aiohttp.web.Application()

        # 路由
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/ws", self._handle_websocket)
        self._app.router.add_get("/data", self._handle_data)
        self._app.router.add_get("/api/sessions", self._handle_api_sessions)
        self._app.router.add_get("/api/session/{sid}", self._handle_api_session_detail)
        self._app.router.add_get("/api/analyze/{sid}", self._handle_api_analyze)
        self._app.router.add_get("/api/control", self._handle_api_control)  # v4.26
        self._app.router.add_post("/api/chat", self._handle_api_chat)  # v4.26
        self._app.router.add_static(
            "/static",
            os.path.join(os.path.dirname(__file__), "static"),
        )

        try:
            aiohttp.web.run_app(
                self._app,
                host=self._host,
                port=self._port,
                handle_signals=False,
                print=lambda *a: None,  # 静默 aiohttp 启动日志
            )
        except Exception as e:
            logger.error("Web 服务器异常: %s", e)
        finally:
            self._running = False

    async def _shutdown(self) -> None:
        """关闭服务器"""
        if self._runner:
            await self._runner.cleanup()
        if self._loop and not self._loop.is_closed():
            self._loop.stop()

    # ── HTTP 路由 ──

    async def _handle_index(self, request):
        """首页 — 跳转到仪表盘"""
        raise aiohttp.web.HTTPFound("/static/index.html")

    async def _handle_data(self, request):
        """REST 端点 — 获取最新数据（供 polling 备选）"""
        return aiohttp.web.json_response({
            "current": self._latest_data,
            "history": self._history[-60:],
        })

    async def _handle_api_sessions(self, request):
        """REST: 获取历史会话列表"""
        if not self._db:
            return aiohttp.web.json_response({"sessions": [], "error": "数据库未就绪"})
        try:
            sessions = self._db.list_sessions()[:50]  # 最近 50 条
            result = []
            for s in sessions:
                result.append({
                    "id": s.session_id,
                    "start": s.start_time.isoformat() if s.start_time else None,
                    "end": s.end_time.isoformat() if s.end_time else None,
                    "duration": s.duration_seconds() if s.end_time else None,
                    "is_active": s.is_active,
                    "is_calibrated": s.is_calibrated,
                    "baseline_ear": s.baseline_ear,
                })
            return aiohttp.web.json_response({"sessions": result})
        except Exception as e:
            logger.warning("获取会话列表失败: %s", e)
            return aiohttp.web.json_response({"sessions": [], "error": str(e)})

    async def _handle_api_session_detail(self, request):
        """REST: 获取指定会话的详细数据"""
        sid = request.match_info.get("sid", "")
        if not self._db or not sid:
            return aiohttp.web.json_response({"error": "参数不足"}, status=400)
        try:
            session = self._db.get_session(sid)
            if not session:
                return aiohttp.web.json_response({"error": "会话不存在"}, status=404)

            focus_records = self._db.get_focus_records(sid) or []
            fatigue_records = self._db.get_fatigue_records(sid) or []
            blink_events = self._db.get_blink_events(sid) or []

            # 计算摘要统计
            scores = [r.focus_score for r in focus_records if r.focus_score is not None]
            avg_focus = round(sum(scores) / max(1, len(scores)), 1) if scores else 0
            blink_rates = [r.blink_rate for r in focus_records if r.blink_rate is not None]
            avg_blink = round(sum(blink_rates) / max(1, len(blink_rates)), 1) if blink_rates else 0

            # 疲劳分布
            fatigue_dist = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
            for r in fatigue_records:
                level = r.fatigue_level.name if hasattr(r.fatigue_level, 'name') else str(r.fatigue_level)
                fatigue_dist[level] = fatigue_dist.get(level, 0) + 1
            fatigue_dist_pct = {}
            total_f = max(sum(fatigue_dist.values()), 1)
            for k, v in fatigue_dist.items():
                fatigue_dist_pct[k] = round(v / total_f * 100, 1)

            # 专注度分段
            dur = session.duration_seconds() or 0.0
            third = max(1, len(scores) // 3)
            seg_start = round(sum(scores[:third]) / len(scores[:third]), 1) if scores[:third] else avg_focus
            seg_mid = round(sum(scores[third:2*third]) / max(1,len(scores[third:2*third])), 1) if len(scores) > third else avg_focus
            seg_end = round(sum(scores[-third:]) / max(1,len(scores[-third:])), 1) if len(scores) >= third else avg_focus

            return aiohttp.web.json_response({
                "session": {
                    "id": session.session_id,
                    "start": session.start_time.isoformat() if session.start_time else None,
                    "end": session.end_time.isoformat() if session.end_time else None,
                    "duration": dur,
                    "is_active": session.is_active,
                    "is_calibrated": session.is_calibrated,
                },
                "summary": {
                    "avg_focus": avg_focus,
                    "avg_blink": avg_blink,
                    "duration_min": round(dur / 60, 1),
                    "record_count": len(focus_records),
                    "seg_start": seg_start,
                    "seg_mid": seg_mid,
                    "seg_end": seg_end,
                    "blink_events": len(blink_events),
                    "fatigue_distribution": fatigue_dist_pct,
                    "fatigue_level": session.fatigue_level or "LOW",
                },
                "focus_records": [
                    {"t": r.window_start, "score": r.focus_score,
                     "eye": r.eye_score, "head": r.head_score}
                    for r in focus_records
                ],
                "fatigue_records": [
                    {"t": r.timestamp, "level": r.fatigue_level, "blink_rate": r.blink_rate,
                     "score": r.cumulative_fatigue_score}
                    for r in fatigue_records
                ],
            })
        except Exception as e:
            logger.warning("获取会话详情失败: %s", e)
            return aiohttp.web.json_response({"error": str(e)}, status=500)

    async def _handle_api_analyze(self, request):
        """REST: 调用 AI 分析指定会话

        使用已配置的 LLM 后端（OpenAI/Ollama/本地等）生成分析建议。
        """
        sid = request.match_info.get("sid", "")
        if not self._db or not sid:
            return aiohttp.web.json_response({"error": "参数不足"}, status=400)
        try:
            from reporter.report_html import create_html_generator
            from config import get_yaml_value
            from concurrent.futures import ThreadPoolExecutor, TimeoutError

            generator = create_html_generator(self._db)
            html = generator.generate_report(sid)

            # 尝试获取 AI 摘要（_data 在 generate_report 后被填充）
            ai_data = getattr(generator, '_data', None)
            if not ai_data:
                return aiohttp.web.json_response({"error": "数据不足"}, status=400)

            # 调用 LLM
            backend = get_yaml_value("ai", "backend", default="template")
            result_text = ""
            if backend != "template":
                from analyzer.llm_client import create_llm_client

                kwargs = {}
                if backend == "ollama":
                    kwargs["base_url"] = get_yaml_value("ai", "ollama_url",
                                                         default="http://127.0.0.1:11434")
                elif backend == "local":
                    kwargs["model_key"] = get_yaml_value("ai", "model_key", default="qwen2.5:1.5b")

                client = create_llm_client(backend, **kwargs)
                if client.available:
                    fr = ai_data.focus_records or []
                    dur = ai_data.total_duration or 0.0
                    avg = ai_data.avg_focus or 50.0
                    third = max(1, len(fr) // 3)
                    def safe_avg(recs):
                        if not recs:
                            return avg
                        ss = [r.focus_score for r in recs if r.focus_score is not None]
                        return sum(ss)/len(ss) if ss else avg

                    llm_data = {
                        "duration": int(dur / 60),
                        "avg_focus": avg,
                        "baseline": 60,
                        "seg_start": safe_avg(fr[:third]),
                        "seg_mid": safe_avg(fr[third:2*third]) if len(fr) >= 2*third else avg,
                        "seg_end": safe_avg(fr[-third:]),
                        "distractions": len(getattr(ai_data, 'distraction_records', None) or []),
                        "head_pct": 50,
                        "gaze_pct": 50,
                        "fatigue": ai_data.fatigue_level.name if hasattr(ai_data.fatigue_level, 'name') else "LOW",
                        "pomo_count": 0,
                        "streak": 0,
                    }
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(client.analyze, llm_data)
                        result_text = fut.result(timeout=15) or ""
                else:
                    result_text = "（AI 后端不可用，请检查 Ollama 或本地模型配置）"
            else:
                # 使用内置模板
                result_text = generator._generate_ai_summary()

            return aiohttp.web.json_response({
                "session_id": sid,
                "analysis": result_text,
                "backend": backend,
            })
        except TimeoutError:
            return aiohttp.web.json_response({
                "session_id": sid,
                "analysis": "（AI 分析超时，请稍后重试）",
                "backend": "timeout",
            })
        except ImportError as e:
            return aiohttp.web.json_response({
                "session_id": sid,
                "analysis": f"（AI 模块未安装: {e}）",
                "backend": "error",
            })
        except Exception as e:
            logger.warning("AI 分析失败: %s", e)
            return aiohttp.web.json_response({
                "session_id": sid,
                "analysis": f"（AI 分析异常: {e}）",
                "backend": "error",
            })

    async def _handle_api_control(self, request):
        """REST: 控制命令（WebSocket 不可用时的降级）"""
        action = request.query.get("action", "")
        if not action:
            return aiohttp.web.json_response({"success": False, "error": "missing action"}, status=400)
        ok = self._exec_callback(action)
        return aiohttp.web.json_response({"success": ok, "action": action})

    async def _handle_websocket(self, request):
        """WebSocket 端点 — 实时推送"""
        ws = aiohttp.web.WebSocketResponse(max_msg_size=65536)
        await ws.prepare(request)

        self._ws_clients.add(ws)
        logger.info("WebSocket 客户端已连接 (%d 在线)", len(self._ws_clients))

        try:
            # 发送初始数据
            await ws.send_json({
                "type": "init",
                "current": self._latest_data,
                "history": self._history[-60:],
            })

            # v4.26: 接收客户端控制命令
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        cmd = json.loads(msg.data)
                        if isinstance(cmd, dict) and cmd.get("type") == "command":
                            action = cmd.get("action", "")
                            ok = self._exec_callback(action)
                            await ws.send_json({
                                "type": "command_result",
                                "action": action,
                                "success": ok,
                            })
                    except (json.JSONDecodeError, Exception):
                        pass
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.warning("WebSocket 错误: %s", ws.exception())

        except asyncio.CancelledError:
            pass
        finally:
            self._ws_clients.discard(ws)
            logger.info("WebSocket 客户端断开 (%d 在线)", len(self._ws_clients))

        return ws

    async def _broadcast_ws(self, payload: dict) -> None:
        """广播 JSON 到所有 WebSocket 客户端"""
        if not self._ws_clients:
            return
        dead: list = []
        for ws in self._ws_clients:
            try:
                await ws.send_json({"type": "update", **payload})
            except (ConnectionError, asyncio.CancelledError):
                dead.append(ws)
        for ws in dead:
            self._ws_clients.discard(ws)

    # ── v4.26: AI 对话 ──

    async def _handle_api_chat(self, request):
        """REST: AI 对话

        POST JSON: {session_id, question, history?}
        Returns: {answer: str}
        """
        try:
            body = await request.json()
        except Exception:
            return aiohttp.web.json_response({"error": "无效的 JSON"}, status=400)

        sid = body.get("session_id", "")
        question = body.get("question", "").strip()
        history = body.get("history", [])
        if not sid or not question:
            return aiohttp.web.json_response({"error": "缺少参数"}, status=400)

        # 获取会话数据
        from reporter.report_html import create_html_generator
        if not self._db:
            return aiohttp.web.json_response({"error": "数据库未就绪"}, status=503)

        generator = create_html_generator(self._db)
        html = generator.generate_report(sid)
        ai_data = getattr(generator, '_data', None)
        if not ai_data:
            return aiohttp.web.json_response({"error": "会话数据不足"}, status=400)

        # 构造 LLM 上下文数据
        llm_data = generator._compute_llm_data(ai_data)

        # 调用 LLM
        from config import get_yaml_value
        from analyzer.llm_client import create_llm_client
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        backend = get_yaml_value("ai", "backend", default="template")
        kwargs = {}
        if backend == "ollama":
            kwargs["base_url"] = get_yaml_value("ai", "ollama_url",
                                                 default="http://127.0.0.1:11434")
        elif backend == "local":
            kwargs["model_key"] = get_yaml_value("ai", "model_key", default="qwen2.5:1.5b")
            kwargs["n_gpu_layers"] = -1
        client = create_llm_client(backend, **kwargs)
        if not client.available:
            # 模板降级
            answer = self._template_chat_answer(question, llm_data)
            return aiohttp.web.json_response({"answer": answer, "backend": "template"})

        # 构造分析数据上下文
        s, m, e = llm_data['seg_start'], llm_data['seg_mid'], llm_data['seg_end']
        trend_desc = "上升" if e > s else ("下降" if s > e else "平稳")
        context = (
            f"## 会话数据\n"
            f"- 时长: {llm_data['duration']} 分钟\n"
            f"- 平均专注度: {llm_data['avg_focus']}/100 分\n"
            f"- 历史平均: {llm_data['hist_avg_focus']}/100 分\n"
            f"- 趋势: 前段 {s} → 中段 {m} → 后段 {e} 分 ({trend_desc})\n"
            f"- 疲劳: 高 {llm_data['fatigue_high_pct']}% / 中 {llm_data['fatigue_mid_pct']}% / 低 {llm_data['fatigue_low_pct']}%\n"
            f"- 分心: {llm_data['distractions']} 次\n"
        )

        system_prompt = (
            "你是一名专注力数据分析师。根据提供的会话数据回答用户问题。\n\n"
            "回答要求：\n"
            "1. 始终基于数据说话，引用具体数字\n"
            "2. 分析原因而非只描述现象（比如专注度下降可能是因为疲劳累积或频繁分心）\n"
            "3. 给出可执行的建议\n"
            "4. 用中文，口语化，像朋友聊天\n"
            "5. 不知道就说不知道，不要编造\n\n"
            "示例分析：\n"
            "- '你这次专注度72分，比平时高了4分。不过后半段下降了13分，看疲劳数据，高疲劳占比15%，可能是疲劳累积影响了后半程。建议下次在疲劳上升前安排一次短暂休息。'\n"
            "- '分心8次，头部偏移是主要原因。可以试着调整一下摄像头位置或者工位布局。'"
        )
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"这是本次会话的数据：\n{context}\n\n请基于以上数据回答用户的问题。"}]
        for h in history[-6:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("text", "")})
        messages.append({"role": "user", "content": question})

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(
                    self._llm_chat, client, messages, backend)
                answer = fut.result(timeout=20)
            return aiohttp.web.json_response({"answer": answer, "backend": backend})
        except TimeoutError:
            return aiohttp.web.json_response({"error": "回答超时，请重试"}, status=504)
        except Exception as e:
            logger.warning("AI 对话失败: %s", e)
            fallback = self._template_chat_answer(question, llm_data)
            return aiohttp.web.json_response({"answer": fallback, "backend": "template"})

    def _llm_chat(self, client, messages: list, backend: str) -> str:
        """调用 LLM 聊天（在线程池中运行）"""
        if backend == "ollama":
            import urllib.request, json as _json
            payload = _json.dumps({
                "model": getattr(client, '_model', 'qwen2.5:1.5b'),
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "max_tokens": 500},
            }).encode()
            req = urllib.request.Request(
                f"{client._base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = _json.loads(resp.read())
                return result.get("message", {}).get("content", "")
        elif backend == "local":
            llm = getattr(client, '_llm', None)
            if llm is None:
                client._load_model()
                llm = client._llm
            if llm:
                prompt = ""
                for m in messages:
                    role = m["role"]
                    if role == "system":
                        prompt += f"<|im_start|>system\n{m['content']}<|im_end|>\n"
                    elif role == "user":
                        prompt += f"<|im_start|>user\n{m['content']}<|im_end|>\n"
                    elif role == "assistant":
                        prompt += f"<|im_start|>assistant\n{m['content']}<|im_end|>\n"
                prompt += "<|im_start|>assistant\n"
                resp = llm(prompt, max_tokens=500, temperature=0.7,
                           stop=["<|im_end|>", "<|im_start|>"])
                return resp["choices"][0]["text"].strip()
            return ""
        return ""

    def _template_chat_answer(self, question: str, d: dict) -> str:
        """模板降级回答"""
        q = question.lower()
        avg = d.get("avg_focus", 0)
        hp = d.get("fatigue_high_pct", 0)
        dc = d.get("distractions", 0)
        dur = d.get("duration", 0)
        s, e = d.get("seg_start", avg), d.get("seg_end", avg)

        if any(w in q for w in ["怎么样", "how", "focus", "评价", "表现", "专注度"]):
            r = f"本次专注度 {avg:.0f} 分。"
            if avg >= 80: r += "表现优秀。"
            elif avg >= 65: r += "整体良好。"
            elif avg >= 50: r += "处于中等水平。"
            else: r += "偏低。"
            return r
        if any(w in q for w in ["为什么", "下降", "drop", "偏低"]):
            reasons = []
            if avg < 65: reasons.append(f"专注度偏低 ({avg:.0f} 分)")
            if s - e > 8: reasons.append(f"后半段下降 {s-e:.0f} 分")
            if hp > 20: reasons.append(f"疲劳偏多 ({hp:.0f}%)")
            if dc > 8: reasons.append(f"分心 {dc} 次")
            return "可能原因：" + "；".join(reasons) if reasons else "整体稳定。"
        if any(w in q for w in ["疲劳", "累", "tired", "fatigue"]):
            if hp > 30: return f"高疲劳占比 {hp:.0f}%，程度较高，建议休息。"
            if hp > 10: return f"有间歇性疲劳 ({hp:.0f}%)，注意起身活动。"
            return "疲劳水平正常。"
        if any(w in q for w in ["分心", "distract", "走神"]):
            if dc == 0: return "没有检测到明显分心事件。"
            return f"共 {dc} 次分心。" + (" 建议使用番茄钟。" if dc > 8 else "")
        if any(w in q for w in ["建议", "suggest", "改进"]):
            tips = []
            if avg < 55: tips.append("缩短单次工作时长")
            if hp > 20: tips.append("每小时起身活动")
            if dc > 10: tips.append("关闭通知使用番茄钟")
            return "建议：" + "；".join(tips) if tips else "表现良好，继续保持！"
        if any(w in q for w in ["时长", "多久", "long"]):
            return f"会话时长 {dur} 分钟。" + ("注意休息。" if dur >= 90 else "")
        return "可以问我：专注度、疲劳、分心、建议等问题。"
