from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

import requests

from .config import ArkclawConfig
from .types import ArkclawCallResult, DialogueEvent, RawEventsSummary, TokenUsage


class ArkclawClient:
    """Arkclaw Gateway Response API 客户端封装。

    设计原则：
    - 不假设具体业务逻辑，仅假设接口符合 Arkclaw Response API（/v1/responses）协议。
    - 不硬编码 base_url / api_key，由 ArkclawConfig 提供（最终来自环境变量或 YAML）。
    - 当未配置 base_url 或 api_key 时，不进行真实调用，仅返回 enabled=False 的占位结果，
    - 以便在本地 / 无网关环境下仍然可以跑通评估流水线和报表。
    - 支持 mock 模式：即使无真实网关也能生成模拟响应，用于演示报表功能。
    """

    def __init__(self, cfg: ArkclawConfig, mock_mode: bool = False) -> None:
        self._cfg = cfg
        self.mock_mode = mock_mode
        self.enabled: bool = bool(mock_mode or (cfg.base_url and cfg.api_key))

    def call(
        self,
        user_content: str,
        session_key: str,
        *,
        new_session: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArkclawCallResult:
        """发送单轮 user -> assistant 调用。

        - user_content: 用户输入内容（单轮）
        - session_key: 评估框架生成的会话键，将通过 header 传给网关
        - new_session: 是否显式请求新 session（通过自定义 Header 传递，具体语义由实际网关解释）
        - metadata: 额外透传信息，可选
        """

        if not self.enabled:
            # 架构完整但未配置 Arkclaw 网关时，占位返回
            return ArkclawCallResult(
                enabled=False,
                skipped_reason="arkclaw_not_configured",
                success=False,
                timeout=False,
                aborted=False,
                user_content=user_content,
                assistant_content=None,
                session_key=session_key,
                run_id=None,
                duration_ms=0,
                token_usage=None,
                raw_events=[],
                events_summary=RawEventsSummary(
                    streaming_delta_count=0,
                    final_message=None,
                    aborted=False,
                    error="arkclaw_not_configured",
                    run_id=None,
                    session_key=session_key,
                ),
                error_message="Arkclaw base_url / api_key 未配置，跳过真实调用。",
            )

        if self.mock_mode:
            # 模拟模式：生成模拟响应，用于演示报表功能
            import random
            import time

            start_ms = int(time.time() * 1000)
            time.sleep(random.uniform(0.05, 0.2))  # 模拟网络延迟

            # 根据用户输入生成模拟回复
            mock_response = self._generate_mock_response(user_content)

            duration_ms = int(time.time() * 1000) - start_ms

            mock_token_usage = TokenUsage(
                input_tokens=len(user_content),
                output_tokens=len(mock_response),
                total_tokens=len(user_content) + len(mock_response),
            )

            events = [
                DialogueEvent(
                    type="request",
                    timestamp_ms=start_ms,
                    data={"input_preview": user_content[:100], "mock": True},
                ),
                DialogueEvent(
                    type="response_final",
                    timestamp_ms=start_ms + duration_ms,
                    data={"content_preview": mock_response[:100], "mock": True},
                ),
            ]

            return ArkclawCallResult(
                enabled=True,
                skipped_reason=None,
                success=True,
                timeout=False,
                aborted=False,
                user_content=user_content,
                assistant_content=mock_response,
                session_key=session_key,
                run_id=f"mock-run-{uuid.uuid4().hex[:8]}",
                duration_ms=duration_ms,
                token_usage=mock_token_usage,
                raw_events=events,
                events_summary=RawEventsSummary(
                    streaming_delta_count=0,
                    final_message=mock_response,
                    aborted=False,
                    error=None,
                    run_id=f"mock-run-{uuid.uuid4().hex[:8]}",
                    session_key=session_key,
                ),
                error_message=None,
            )

        # 按 /v1/responses 协议构造 URL，默认假定 base_url 已包含 /v1
        url = (self._cfg.base_url or "").rstrip("/") + "/responses"

        # 请求头：保留 Authorization / Content-Type，并新增 Arkclaw 特有小写头
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._cfg.api_key}",
            "x-openclaw-agent-id": self._cfg.agent_id or "main",
            "x-session-key": session_key,
        }
        if new_session:
            headers["x-new-session"] = "true"

        # 请求体：/v1/responses 协议使用 {model, input, metadata?}
        body: Dict[str, Any] = {
            "model": self._cfg.model or "openclaw",
            "input": user_content,
        }
        if metadata:
            body["metadata"] = metadata

        events: List[DialogueEvent] = []
        start_ms = int(time.time() * 1000)

        def _now_ms() -> int:
            return int(time.time() * 1000)

        # 记录请求事件，仅保留必要的预览信息
        events.append(
            DialogueEvent(
                type="request",
                timestamp_ms=_now_ms(),
                data={
                    "url": url,
                    # 不记录敏感 header
                    "body_preview": {
                        "model": body.get("model"),
                        "input_preview": user_content[:200],
                    },
                },
            )
        )

        success = False
        timeout = False
        aborted = False
        error_message: Optional[str] = None
        assistant_content: Optional[str] = None
        run_id: Optional[str] = None
        usage: Optional[TokenUsage] = None

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=self._cfg.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()

            # run_id 按响应 id 字段
            run_id = data.get("id")

            # 在 output 中找到第一个 type == "message" 的项，再在其 content 中找 type == "output_text" 的 text
            output_items = data.get("output") or []
            if isinstance(output_items, list):
                for item in output_items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") != "message":
                        continue
                    contents = item.get("content") or []
                    if not isinstance(contents, list):
                        continue
                    for c in contents:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "output_text":
                            text = c.get("text")
                            if isinstance(text, str):
                                assistant_content = text
                                break
                    if assistant_content is not None:
                        break

            usage_obj = data.get("usage") or {}
            if isinstance(usage_obj, dict):
                usage = TokenUsage(
                    input_tokens=usage_obj.get("input_tokens"),
                    output_tokens=usage_obj.get("output_tokens"),
                    total_tokens=usage_obj.get("total_tokens"),
                )

            success = True

            events.append(
                DialogueEvent(
                    type="response_final",
                    timestamp_ms=_now_ms(),
                    data={
                        "status_code": resp.status_code,
                        "run_id": run_id,
                        "content_preview": (assistant_content or "")[:200],
                        "usage": usage_obj,
                    },
                )
            )
        except requests.Timeout:
            timeout = True
            error_message = "Arkclaw 请求超时"
            events.append(
                DialogueEvent(
                    type="error",
                    timestamp_ms=_now_ms(),
                    data={"error": error_message},
                )
            )
        except Exception as exc:  # pragma: no cover - 网络环境相关
            aborted = True
            error_message = f"Arkclaw 调用异常: {exc}"
            events.append(
                DialogueEvent(
                    type="error",
                    timestamp_ms=_now_ms(),
                    data={"error": str(exc)},
                )
            )

        duration_ms = _now_ms() - start_ms

        events_summary = RawEventsSummary(
            streaming_delta_count=0,
            final_message=assistant_content,
            aborted=aborted,
            error=error_message,
            run_id=run_id,
            session_key=session_key,
        )

        return ArkclawCallResult(
            enabled=True,
            skipped_reason=None,
            success=success,
            timeout=timeout,
            aborted=aborted,
            user_content=user_content,
            assistant_content=assistant_content,
            session_key=session_key,
            run_id=run_id,
            duration_ms=duration_ms,
            token_usage=usage,
            raw_events=events,
            events_summary=events_summary,
            error_message=error_message,
        )

    def _generate_mock_response(self, user_content: str) -> str:
        """根据用户输入生成模拟响应"""
        import random

        # 简单的关键词匹配来生成模拟回复
        content_lower = user_content.lower()

        if "记住" in user_content or "记得" in user_content:
            return "好的，我已经记住了这些信息。"
        elif "偏好" in user_content or "喜欢" in user_content:
            if "奶茶" in user_content or "三分糖" in user_content:
                return "我记得你喝奶茶只爱三分糖、少冰。"
            elif "香菜" in user_content:
                return "我记得你不喜欢吃香菜。"
            else:
                return f"我记住了你的偏好信息。"
        elif "任务" in user_content or "帮我" in user_content:
            if "银行" in user_content or "办卡" in user_content:
                return "我记得你明天上午10点要去银行办卡。"
            else:
                return f"好的，我会帮你记住这个任务。"
        elif "工号" in user_content or "部门" in user_content:
            if "6688" in user_content and "测试" in user_content:
                return "你的工号是6688，部门是测试部。"
            else:
                return "我记住了你的信息。"
        elif "天气" in user_content:
            return "今天天气不错，阳光明媚。"
        elif "你好" in user_content or "hi" in content_lower:
            return "你好！有什么我可以帮助你的吗？"
        else:
            # 随机返回一些通用回复
            generic_responses = [
                "好的，我理解了。",
                "这是一个有趣的问题。",
                "让我想想...",
                "我已经记录了这些信息。",
                "没问题，我会记住的。",
            ]
            return random.choice(generic_responses)
