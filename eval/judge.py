from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

from .config import DoubaoConfig
from .types import CombinedJudgeResult, LLMJudgeResult, RuleJudgeResult


class LLMJudgeClient:
    """豆包 LLM Judge 客户端。

    默认兼容 OPENAI 风格 /chat/completions 接口，由 DoubaoConfig 提供 base_url / api_key。
    若未配置，将返回 enabled=False 的结果，由上层降级为仅规则评估。
    支持 mock 模式：模拟 LLM 评估结果。
    """

    def __init__(self, cfg: DoubaoConfig, mock_mode: bool = False) -> None:
        self._cfg = cfg
        self.mock_mode = mock_mode
        self.enabled: bool = bool(mock_mode or (cfg.base_url and cfg.api_key))

    def _build_payload(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        return {
            "model": self._cfg.model,
            "messages": messages,
        }

    def judge(
        self,
        *,
        case_id: str,
        expected: str,
        answer: Optional[str],
        memory_type: str,
        time_dimension: str,
        priority: str,
    ) -> LLMJudgeResult:
        if not self.enabled:
            return LLMJudgeResult(
                enabled=False,
                score=None,
                label=None,
                reasoning=None,
                hit_facts=[],
                missed_facts=[],
                output_summary=None,
                raw=None,
                error="llm_judge_disabled",
            )

        if self.mock_mode:
            # 模拟模式：生成模拟的 LLM 评估结果
            import random
            import time

            time.sleep(random.uniform(0.02, 0.08))

            # 简单的模拟评估逻辑
            answer_str = answer or ""
            expected_str = expected

            # 检查答案是否包含关键信息
            has_key_info = any(keyword in answer_str for keyword in ["记得", "记住", "知道", "你好", "好的"])
            is_empty = len(answer_str.strip()) == 0

            if is_empty:
                score = 0.0
                label = "fail"
                reasoning = "回复为空，没有任何内容。"
                hit_facts = []
                missed_facts = ["期望的回答内容"]
            elif has_key_info:
                score = random.uniform(8.0, 10.0)
                label = "pass"
                reasoning = "回答基本正确，包含了关键信息。"
                hit_facts = ["基本理解了问题", "给出了相关回答"]
                missed_facts = []
            else:
                score = random.uniform(4.0, 7.5)
                label = "partial"
                reasoning = "回答部分相关，但不够完整。"
                hit_facts = ["理解了部分内容"]
                missed_facts = ["缺少一些关键信息"]

            return LLMJudgeResult(
                enabled=True,
                score=score,
                label=label,
                reasoning=reasoning,
                hit_facts=hit_facts,
                missed_facts=missed_facts,
                output_summary="模拟评估完成",
                raw={"mock": True, "score": score, "label": label},
                error=None,
            )

        sys_prompt = (
            "你是一个针对对话记忆能力的自动化评估助手。"
            "给定用户问题、模型回答和期望答案，请从正确性和事实命中角度进行打分。"
            "请严格输出 JSON，且不要包含任何多余说明文字。"
        )

        user_prompt = {
            "case_id": case_id,
            "memory_type": memory_type,
            "time_dimension": time_dimension,
            "priority": priority,
            "expected_answer": expected,
            "model_answer": answer or "<<EMPTY>>",
        }

        messages = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": (
                    "请基于以下信息进行评估，并严格输出一个 JSON 对象：\n\n"
                    + json.dumps(user_prompt, ensure_ascii=False, separators=(",", ":"))
                    + "\n\nJSON 字段定义：\n"
                    "- score: 0 到 10 的整数分数（正确性与事实命中综合）。\n"
                    "- label: 'pass'、'fail' 或 'partial'。\n"
                    "- reasoning: 评估理由，中文。\n"
                    "- hit_facts: 命中的关键信息列表（字符串数组）。\n"
                    "- missed_facts: 漏掉的关键信息列表（字符串数组）。\n"
                    "- output_summary: 对模型回答整体风格和内容的简要概述。\n"
                    "请仅输出 JSON，不要加入其他任何文本。"
                ),
            },
        ]

        url = (self._cfg.base_url or "").rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._cfg.api_key}",
        }
        session_id = os.getenv("IRIS_SESSION_ID")
        if session_id:
            headers["X-Session-ID"] = session_id
        headers["X-LLM-TAG"] = "arkclaw_memory_judge"

        body = self._build_payload(messages)

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=self._cfg.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            content = None
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content")

            if not isinstance(content, str):
                return LLMJudgeResult(
                    enabled=True,
                    score=None,
                    label=None,
                    reasoning=None,
                    hit_facts=[],
                    missed_facts=[],
                    output_summary=None,
                    raw=data,
                    error="llm_response_empty",
                )

            # 期望 content 本身是 JSON 文本
            try:
                obj = json.loads(content)
            except Exception as exc:  # pragma: no cover - 依赖大模型输出
                return LLMJudgeResult(
                    enabled=True,
                    score=None,
                    label=None,
                    reasoning=None,
                    hit_facts=[],
                    missed_facts=[],
                    output_summary=None,
                    raw={"raw_text": content},
                    error=f"llm_output_not_json: {exc}",
                )

            score_val = obj.get("score")
            try:
                score = float(score_val) if score_val is not None else None
            except Exception:
                score = None

            label = obj.get("label")
            reasoning = obj.get("reasoning")
            hit_facts = obj.get("hit_facts") or []
            missed_facts = obj.get("missed_facts") or []
            output_summary = obj.get("output_summary")

            if not isinstance(hit_facts, list):
                hit_facts = [str(hit_facts)]
            hit_facts = [str(x) for x in hit_facts]

            if not isinstance(missed_facts, list):
                missed_facts = [str(missed_facts)]
            missed_facts = [str(x) for x in missed_facts]

            return LLMJudgeResult(
                enabled=True,
                score=score,
                label=str(label) if label is not None else None,
                reasoning=str(reasoning) if reasoning is not None else None,
                hit_facts=hit_facts,
                missed_facts=missed_facts,
                output_summary=str(output_summary) if output_summary is not None else None,
                raw=obj,
                error=None,
            )
        except Exception as exc:  # pragma: no cover - 网络环境相关
            return LLMJudgeResult(
                enabled=self.enabled,
                score=None,
                label=None,
                reasoning=None,
                hit_facts=[],
                missed_facts=[],
                output_summary=None,
                raw=None,
                error=f"llm_judge_exception: {exc}",
            )


def combine_judge_results(rule: RuleJudgeResult, llm: LLMJudgeResult) -> CombinedJudgeResult:
    """综合 LLM 与规则结果，生成最终结论与失败归因。"""

    failure_reasons: List[str] = []

    if rule.empty_response:
        failure_reasons.append("empty_response")
    if rule.timeout:
        failure_reasons.append("timeout")
    if rule.aborted:
        failure_reasons.append("aborted")
    if rule.missed_must_mention:
        failure_reasons.append("missed_mustMention")
    if rule.has_refusal:
        failure_reasons.append("refusal")
    if rule.has_hallucination:
        failure_reasons.append("hallucination")

    if not llm.enabled:
        failure_reasons.append("llm_judge_disabled")

    # 合成 label & score：优先 LLM，其次规则
    if llm.enabled and llm.label is not None and llm.score is not None:
        final_label = str(llm.label)
        final_score = float(llm.score)
        if final_label == "fail" and final_score < 5:
            failure_reasons.append("llm_low_score")
    else:
        final_label = rule.label
        final_score = rule.score
        if final_label == "fail" and final_score < 5:
            failure_reasons.append("rule_low_score")

    return CombinedJudgeResult(
        final_label=final_label,
        final_score=final_score,
        llm=llm,
        rule=rule,
        failure_reasons=failure_reasons,
    )
