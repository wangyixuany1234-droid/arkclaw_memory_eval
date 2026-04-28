from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Optional

from .config import NoiseConfig
from .noise_generator import generate_noise_dialogue


QUESTION_PATTERNS = [
    r"询问[：:]\s*“([^”]+)”",
    r"询问[：:]\s*\"([^\"]+)\"",
    r"问[：:]\s*“([^”]+)”",
    r"问[：:]\s*\"([^\"]+)\"",
]

QUOTE_PATTERN = re.compile(r"[“\"]([^”\"]+)[”\"]")


def _extract_qa_question(text: str) -> (Optional[str], Optional[int]):
    """在操作步骤文本中提取最后一个“询问/问”问题。返回 (问题文本, 起始下标)。"""

    if not text:
        return None, None

    last_match = None
    for pat in QUESTION_PATTERNS:
        for m in re.finditer(pat, text):
            last_match = m
    if last_match is None:
        return None, None
    question = last_match.group(1).strip()
    return question, last_match.start()


def _parse_ingest_part(
    case_id: str,
    full_text: str,
    qa_start: Optional[int],
    noise_cfg: NoiseConfig,
) -> (List[str], str):
    """解析 ingest 部分，返回 (用户发言列表, parse_notes)。

    - 常规用例：抽取引号中的文本，作为多轮对话用户发言。
    - D04 等特殊长对话：根据描述生成噪声对话（含 1 句核心记忆）。
    """

    if not full_text:
        return [], "empty_steps_text"

    ingest_text = full_text if qa_start is None else full_text[:qa_start]
    notes = ""

    # 特殊处理 D04：长对话（15 轮）关键信息记忆
    if case_id.strip().upper() == "D04" and "15" in ingest_text and "轮" in ingest_text:
        core = "我下周要参加会计考试"
        turns = generate_noise_dialogue(core, 15, noise_cfg)
        return turns, "generated_15_turn_dialogue_with_noise"

    # 通用：抽取所有引号中的内容
    utterances = [m.strip() for m in QUOTE_PATTERN.findall(ingest_text) if m.strip()]
    if utterances:
        return utterances, "parsed_from_quotes"

    # 兜底：若前半段非空但未识别到引号，则直接作为单轮文本
    if ingest_text.strip():
        return [ingest_text.strip()], "fallback_whole_ingest_text"

    return [], "no_ingest_content"


def load_and_parse_cases(csv_path: str, noise_cfg: NoiseConfig) -> List[Dict[str, object]]:
    """加载 CSV 并解析为可执行用例结构。

    返回列表中每个元素包含：
    - case_id, memory_type, scenario, steps_text, expected, time_dimension, priority
    - ingest_messages: List[str]
    - qa_question: Optional[str]
    - parse_notes: str
    """

    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)

    cases: List[Dict[str, object]] = []

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 处理 BOM 情况
            raw_id = row.get("用例ID") or row.get("\ufeff用例ID") or ""
            case_id = str(raw_id).strip()

            memory_type = str(row.get("记忆类型", "")).strip()
            scenario = str(row.get("测试场景", "")).strip()
            steps_text = str(row.get("实际操作步骤", "")).strip()
            expected = str(row.get("预期结果", "")).strip()
            time_dimension = str(row.get("时间维度", "")).strip()
            priority = str(row.get("优先级", "")).strip()

            qa_question, qa_start = _extract_qa_question(steps_text)
            ingest_messages, parse_notes = _parse_ingest_part(
                case_id=case_id,
                full_text=steps_text,
                qa_start=qa_start,
                noise_cfg=noise_cfg,
            )

            cases.append(
                {
                    "case_id": case_id,
                    "memory_type": memory_type,
                    "scenario": scenario,
                    "steps_text": steps_text,
                    "expected": expected,
                    "time_dimension": time_dimension,
                    "priority": priority,
                    "ingest_messages": ingest_messages,
                    "qa_question": qa_question,
                    "parse_notes": parse_notes,
                }
            )

    return cases
