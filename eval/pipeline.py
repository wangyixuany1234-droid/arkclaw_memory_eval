from __future__ import annotations

import csv
import json
import os
import time
import uuid
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .arkclaw_client import ArkclawClient
from .config import AppConfig
from .csv_loader import load_and_parse_cases
from .judge import LLMJudgeClient, combine_judge_results
from .rules import rule_based_judge
from .types import ArkclawCallResult, CombinedJudgeResult, TokenUsage


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _aggregate_tokens(usages: List[Optional[TokenUsage]]) -> Dict[str, Optional[int]]:
    total_in = 0
    total_out = 0
    total = 0
    has_any = False
    for u in usages:
        if not u:
            continue
        has_any = True
        if u.input_tokens is not None:
            total_in += int(u.input_tokens)
        if u.output_tokens is not None:
            total_out += int(u.output_tokens)
        if u.total_tokens is not None:
            total += int(u.total_tokens)
    if not has_any:
        return {"input": None, "output": None, "total": None}
    return {"input": total_in, "output": total_out, "total": total}


def run_pipeline(
    *,
    csv_path: str,
    cfg: AppConfig,
    filter_priorities: Optional[Set[str]] = None,
    filter_types: Optional[Set[str]] = None,
    filter_times: Optional[Set[str]] = None,
    steps: Set[str],  # ingest / qa / judge
    new_session_mode: str,  # ingest | qa | none
    iteration_tag: str,
    output_dir: str,
) -> Tuple[str, str]:
    """执行 ingest → qa → judge 全流程，并产出结果文件。

    返回 (results_jsonl_path, summary_csv_path)。
    """

    _ensure_dir(output_dir)
    cases_raw = load_and_parse_cases(csv_path, cfg.noise)

    # 过滤
    def _match_filters(c: Dict[str, object]) -> bool:
        if filter_priorities and str(c.get("priority")) not in filter_priorities:
            return False
        if filter_types and str(c.get("memory_type")) not in filter_types:
            return False
        if filter_times and str(c.get("time_dimension")) not in filter_times:
            return False
        return True

    cases = [c for c in cases_raw if _match_filters(c)]

    ark_client = ArkclawClient(cfg.arkclaw)
    llm_judge_client = LLMJudgeClient(cfg.doubao)

    results_jsonl_path = os.path.join(output_dir, "results.jsonl")
    summary_csv_path = os.path.join(output_dir, "summary.csv")
    cases_dir = os.path.join(output_dir, "cases")
    _ensure_dir(cases_dir)

    # 打开结果输出文件
    results_f = open(results_jsonl_path, "w", encoding="utf-8")
    summary_f = open(summary_csv_path, "w", encoding="utf-8", newline="")

    summary_writer = csv.writer(summary_f)
    summary_writer.writerow(
        [
            "caseId",
            "title",
            "memoryType",
            "timeDimension",
            "priority",
            "success",  # pass/fail/partial
            "avgScore",
            "llmScore",
            "ruleScore",
            "passCount",
            "failCount",
            "turnCount",
            "iterationTag",
            "ingestMs",
            "qaMs",
            "judgeMs",
            "totalMs",
            "ingestInputTokens",
            "ingestOutputTokens",
            "ingestTotalTokens",
            "qaInputTokens",
            "qaOutputTokens",
            "qaTotalTokens",
            "judgeInputTokens",
            "judgeOutputTokens",
            "judgeTotalTokens",
            "llmJudgeEnabled",
        ]
    )

    def _new_session_for(step: str) -> bool:
        return new_session_mode == step

    for case in cases:
        case_id = str(case.get("case_id"))
        memory_type = str(case.get("memory_type"))
        scenario = str(case.get("scenario"))
        time_dimension = str(case.get("time_dimension"))
        priority = str(case.get("priority"))
        ingest_messages: List[str] = list(case.get("ingest_messages") or [])  # type: ignore[arg-type]
        qa_question: Optional[str] = case.get("qa_question") or None  # type: ignore[assignment]

        session_key = f"{case_id}-{iteration_tag}-{uuid.uuid4().hex[:8]}"

        dialogue_records: List[Dict[str, object]] = []
        all_raw_events: List[Dict[str, object]] = []

        ingest_ms = 0
        qa_ms = 0
        judge_ms = 0

        ingest_usages: List[Optional[TokenUsage]] = []
        qa_usages: List[Optional[TokenUsage]] = []
        judge_usages: List[Optional[TokenUsage]] = []  # 目前未使用，占位

        qa_answer: Optional[str] = None
        qa_call: Optional[ArkclawCallResult] = None

        # ingest 阶段
        if "ingest" in steps and ingest_messages:
            for idx, msg in enumerate(ingest_messages):
                call = ark_client.call(
                    user_content=msg,
                    session_key=session_key,
                    new_session=_new_session_for("ingest") and idx == 0,
                    metadata={"step": "ingest", "case_id": case_id, "turn_index": idx + 1},
                )
                ingest_ms += int(call.duration_ms)
                ingest_usages.append(call.token_usage)
                all_raw_events.append(call.to_dict())

                # 每轮记录 user / assistant
                dialogue_records.append(
                    {
                        "step": "ingest",
                        "turn_index": idx + 1,
                        "role": "user",
                        "content": msg,
                        "duration_ms": call.duration_ms,
                        "token_usage": {
                            "input_tokens": call.token_usage.input_tokens if call.token_usage else None,
                            "output_tokens": None,
                            "total_tokens": call.token_usage.total_tokens if call.token_usage else None,
                        },
                    }
                )
                dialogue_records.append(
                    {
                        "step": "ingest",
                        "turn_index": idx + 1,
                        "role": "assistant",
                        "content": call.assistant_content,
                        "duration_ms": call.duration_ms,
                        "token_usage": {
                            "input_tokens": None,
                            "output_tokens": call.token_usage.output_tokens if call.token_usage else None,
                            "total_tokens": call.token_usage.total_tokens if call.token_usage else None,
                        },
                    }
                )

        # qa 阶段
        if "qa" in steps and qa_question:
            qa_call = ark_client.call(
                user_content=qa_question,
                session_key=session_key,
                new_session=_new_session_for("qa"),
                metadata={"step": "qa", "case_id": case_id},
            )
            qa_ms += int(qa_call.duration_ms)
            qa_usages.append(qa_call.token_usage)
            all_raw_events.append(qa_call.to_dict())

            qa_answer = qa_call.assistant_content

            dialogue_records.append(
                {
                    "step": "qa",
                    "turn_index": 1,
                    "role": "user",
                    "content": qa_question,
                    "duration_ms": qa_call.duration_ms,
                    "token_usage": {
                        "input_tokens": qa_call.token_usage.input_tokens if qa_call.token_usage else None,
                        "output_tokens": None,
                        "total_tokens": qa_call.token_usage.total_tokens if qa_call.token_usage else None,
                    },
                }
            )
            dialogue_records.append(
                {
                    "step": "qa",
                    "turn_index": 1,
                    "role": "assistant",
                    "content": qa_call.assistant_content,
                    "duration_ms": qa_call.duration_ms,
                    "token_usage": {
                        "input_tokens": None,
                        "output_tokens": qa_call.token_usage.output_tokens if qa_call.token_usage else None,
                        "total_tokens": qa_call.token_usage.total_tokens if qa_call.token_usage else None,
                    },
                }
            )

        # judge 阶段
        combined_result: Optional[CombinedJudgeResult] = None
        if "judge" in steps:
            start_judge = time.time()
            rule_res = rule_based_judge(
                expected=str(case.get("expected") or ""),
                answer=qa_answer,
                cfg=cfg.rules,
                timeout=bool(qa_call.timeout) if qa_call else False,
                aborted=bool(qa_call.aborted) if qa_call else False,
            )
            llm_res = llm_judge_client.judge(
                case_id=case_id,
                expected=str(case.get("expected") or ""),
                answer=qa_answer,
                memory_type=memory_type,
                time_dimension=time_dimension,
                priority=priority,
            )
            combined_result = combine_judge_results(rule_res, llm_res)
            judge_ms += int((time.time() - start_judge) * 1000)

        total_ms = ingest_ms + qa_ms + judge_ms

        ingest_tok = _aggregate_tokens(ingest_usages)
        qa_tok = _aggregate_tokens(qa_usages)
        judge_tok = _aggregate_tokens(judge_usages)

        # case 级结果对象
        result_record: Dict[str, object] = {
            "case_meta": {
                "case_id": case_id,
                "memory_type": memory_type,
                "scenario": scenario,
                "time_dimension": time_dimension,
                "priority": priority,
                "iterationTag": iteration_tag,
            },
            "sessionKey": session_key,
            "stepsExecuted": sorted(list(steps)),
            "dialogue": dialogue_records,
            "rawEvents": all_raw_events,
            "timing": {
                "ingest_ms": ingest_ms,
                "qa_ms": qa_ms,
                "judge_ms": judge_ms,
                "total_ms": total_ms,
            },
            "tokens": {
                "ingest": ingest_tok,
                "qa": qa_tok,
                "judge": judge_tok,
            },
            "arkclawEnabled": ark_client.enabled,
            "llmJudgeEnabled": llm_judge_client.enabled,
        }

        if combined_result is not None:
            result_record["judge"] = combined_result.to_dict()
        else:
            result_record["judge"] = None

        # 写入中间 case 文件
        case_path = os.path.join(cases_dir, f"{case_id}.json")
        with open(case_path, "w", encoding="utf-8") as cf:
            cf.write(json.dumps(result_record, ensure_ascii=False, separators=(",", ":")))

        # 写入 results.jsonl
        results_f.write(json.dumps(result_record, ensure_ascii=False, separators=(",", ":")) + "\n")

        # 写入 summary.csv
        if combined_result is not None:
            final_label = combined_result.final_label
            llm_score = combined_result.llm.score
            rule_score = combined_result.rule.score
            scores = [s for s in [llm_score, rule_score] if s is not None]
            avg_score = sum(scores) / len(scores) if scores else ""
            llm_score_val = llm_score if llm_score is not None else ""
            rule_score_val = rule_score if rule_score is not None else ""
        else:
            final_label = "fail"
            avg_score = ""
            llm_score_val = ""
            rule_score_val = ""

        pass_count = 1 if final_label == "pass" else 0
        fail_count = 1 if final_label == "fail" else 0
        turn_count = len([d for d in dialogue_records if d.get("role") == "user"])  # 用户轮数

        summary_writer.writerow(
            [
                case_id,
                scenario,
                memory_type,
                time_dimension,
                priority,
                final_label,
                avg_score,
                llm_score_val,
                rule_score_val,
                pass_count,
                fail_count,
                turn_count,
                iteration_tag,
                ingest_ms,
                qa_ms,
                judge_ms,
                total_ms,
                ingest_tok["input"],
                ingest_tok["output"],
                ingest_tok["total"],
                qa_tok["input"],
                qa_tok["output"],
                qa_tok["total"],
                judge_tok["input"],
                judge_tok["output"],
                judge_tok["total"],
                llm_judge_client.enabled,
            ]
        )

    results_f.close()
    summary_f.close()

    return results_jsonl_path, summary_csv_path
