from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TokenUsage:
    """记录一次调用的 token 用量。"""

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass
class DialogueEvent:
    """原始事件，用于可观测性回放。

    type: 事件类型，如 request/response_final/error 等。
    timestamp_ms: 自 Unix 纪元以来的毫秒数。
    data: Dict[str, Any]: 与事件相关的原始数据（经过适度裁剪）。
    """

    type: str
    timestamp_ms: int
    data: Dict[str, Any]


@dataclass
class RawEventsSummary:
    """对 rawEvents 的归纳统计，便于后续分析。"""

    streaming_delta_count: int = 0
    final_message: Optional[str] = None
    aborted: bool = False
    error: Optional[str] = None
    run_id: Optional[str] = None
    session_key: Optional[str] = None


@dataclass
class ArkclawCallResult:
    """一次 Arkclaw 调用的结果与观测信息。"""

    enabled: bool
    skipped_reason: Optional[str]
    success: bool
    timeout: bool
    aborted: bool
    user_content: str
    assistant_content: Optional[str]
    session_key: Optional[str]
    run_id: Optional[str]
    duration_ms: int
    token_usage: Optional[TokenUsage]
    raw_events: List[DialogueEvent]
    events_summary: RawEventsSummary
    error_message: Optional[str]

    def to_dict(self) -> Dict[str, Any]:  # 方便序列化
        return {
            "enabled": self.enabled,
            "skipped_reason": self.skipped_reason,
            "success": self.success,
            "timeout": self.timeout,
            "aborted": self.aborted,
            "user_content": self.user_content,
            "assistant_content": self.assistant_content,
            "session_key": self.session_key,
            "run_id": self.run_id,
            "duration_ms": self.duration_ms,
            "token_usage": asdict(self.token_usage) if self.token_usage else None,
            "rawEvents": [asdict(e) for e in self.raw_events],
            "eventsSummary": asdict(self.events_summary),
            "error_message": self.error_message,
        }


@dataclass
class LLMJudgeResult:
    """豆包 LLM Judge 的结果。"""

    enabled: bool
    score: Optional[float]
    label: Optional[str]
    reasoning: Optional[str]
    hit_facts: List[str]
    missed_facts: List[str]
    output_summary: Optional[str]
    raw: Optional[Dict[str, Any]]
    error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "score": self.score,
            "label": self.label,
            "reasoning": self.reasoning,
            "hit_facts": self.hit_facts,
            "missed_facts": self.missed_facts,
            "output_summary": self.output_summary,
            "raw": self.raw,
            "error": self.error,
        }


@dataclass
class RuleJudgeResult:
    """基于硬规则的打分与归因结果。"""

    score: float
    label: str
    empty_response: bool
    timeout: bool
    aborted: bool
    has_refusal: bool
    has_hallucination: bool
    missed_must_mention: bool
    must_mention_keywords: List[str]
    hit_keywords: List[str]
    length: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "label": self.label,
            "empty_response": self.empty_response,
            "timeout": self.timeout,
            "aborted": self.aborted,
            "has_refusal": self.has_refusal,
            "has_hallucination": self.has_hallucination,
            "missed_must_mention": self.missed_must_mention,
            "must_mention_keywords": self.must_mention_keywords,
            "hit_keywords": self.hit_keywords,
            "length": self.length,
        }


@dataclass
class CombinedJudgeResult:
    """综合 LLM + 规则的最终结论。"""

    final_label: str
    final_score: float
    llm: LLMJudgeResult
    rule: RuleJudgeResult
    failure_reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_label": self.final_label,
            "final_score": self.final_score,
            "llm": self.llm.to_dict(),
            "rule": self.rule.to_dict(),
            "failure_reasons": self.failure_reasons,
        }
