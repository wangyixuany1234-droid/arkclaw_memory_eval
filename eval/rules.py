from __future__ import annotations

import re
from typing import List, Optional

from .config import RuleConfig
from .types import RuleJudgeResult


_PUNCT_PATTERN = re.compile(r"[，,。；;：:\s、]")


def extract_must_mention_keywords(expected: str, cfg: RuleConfig) -> List[str]:
    """从预期结果中粗略抽取 mustMention 关键词集。

    策略偏保守：
    - 按常见中文/英文标点与空白切分。
    - 过滤过短片段（长度 < must_mention_min_length）。
    - 保留原文片段，后续仅做包含性判断，不做语义理解。
    """

    if not expected:
        return []
    parts = _PUNCT_PATTERN.split(expected)
    return [p.strip() for p in parts if len(p.strip()) >= cfg.must_mention_min_length]


def rule_based_judge(
    expected: str,
    answer: Optional[str],
    cfg: RuleConfig,
    *,
    timeout: bool = False,
    aborted: bool = False,
) -> RuleJudgeResult:
    """基于硬规则对单条 QA 结果进行打分与归因。

    返回 RuleJudgeResult，score 取值 0-10，label 为 pass/partial/fail。
    """

    ans = (answer or "").strip()
    empty = ans == ""

    must_keywords = extract_must_mention_keywords(expected or "", cfg)

    lower_ans = ans.lower()
    has_refusal = any(k.lower() in lower_ans for k in cfg.refusal_keywords) if ans else False
    has_hallucination = any(k.lower() in lower_ans for k in cfg.hallucination_keywords) if ans else False

    hit_keywords: List[str] = []
    if ans and must_keywords:
        for k in must_keywords:
            if k and k in ans:
                hit_keywords.append(k)

    missed_must = bool(must_keywords) and len(hit_keywords) < len(must_keywords)

    # 简单打分规则：
    # - 空回复：0 分
    # - 有内容基础分 10 分
    # - 每类问题扣分：missed_must / refusal / hallucination 各 -3 分
    # - timeout / aborted 额外各 -2 分
    # 分数下限 0，上限 10
    if empty:
        score = 0.0
    else:
        score = 10.0
        if missed_must:
            score -= 3.0
        if has_refusal:
            score -= 3.0
        if has_hallucination:
            score -= 3.0
        if timeout:
            score -= 2.0
        if aborted:
            score -= 2.0
        if score < 0.0:
            score = 0.0

    # 标签：
    # - score >= 8: pass
    # - 4 <= score < 8: partial
    # - <4: fail
    if score >= 8.0 and not empty:
        label = "pass"
    elif score >= 4.0 and not empty:
        label = "partial"
    else:
        label = "fail"

    return RuleJudgeResult(
        score=score,
        label=label,
        empty_response=empty,
        timeout=timeout,
        aborted=aborted,
        has_refusal=has_refusal,
        has_hallucination=has_hallucination,
        missed_must_mention=missed_must,
        must_mention_keywords=must_keywords,
        hit_keywords=hit_keywords,
        length=len(ans),
    )
