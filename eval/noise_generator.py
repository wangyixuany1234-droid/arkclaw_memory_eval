from __future__ import annotations

from typing import List

from .config import NoiseConfig


def generate_noise_dialogue(
    core_sentence: str,
    total_turns: int,
    noise_cfg: NoiseConfig,
) -> List[str]:
    """生成包含 1 句核心记忆 + 若干噪声对话的多轮对话序列。

    - core_sentence: 必须出现在对话中的关键记忆句，如 “我下周要参加会计考试”。
    - total_turns: 总轮数，例如 D04 要求的 15 轮。
    - noise_cfg.topics: 作为噪声对话内容的模板句列表。

    返回：长度为 total_turns 的用户发言列表，顺序固定且可复现。
    """

    if total_turns <= 1:
        return [core_sentence]

    topics = list(noise_cfg.topics) if noise_cfg.enabled and noise_cfg.topics else []
    if len(topics) < total_turns - 1:
        # 若内置主题不足，循环补齐
        while len(topics) < total_turns - 1:
            topics.extend(topics or ["今天过得怎么样？"])
    topics = topics[: total_turns - 1]

    # 固定将核心句放在靠前的位置，避免随机带来的不可复现
    insert_index = min(4, total_turns - 1)  # 第 5 轮（索引 4）

    result: List[str] = []
    noise_iter = iter(topics)
    for i in range(total_turns):
        if i == insert_index:
            result.append(core_sentence)
        else:
            result.append(next(noise_iter))
    return result
