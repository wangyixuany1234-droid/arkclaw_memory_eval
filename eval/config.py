from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
import os

try:  # pyyaml is optional but recommended
    import yaml  # type: ignore
except Exception:  # pragma: no cover - soft dependency
    yaml = None


@dataclass
class ArkclawConfig:
    """配置 Arkclaw Gateway Response API。

    实际调用地址和认证信息通过环境变量或 config.yaml 提供，代码不做硬编码。
    """

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    agent_id: Optional[str] = None
    model: Optional[str] = None
    timeout_seconds: int = 30


@dataclass
class DoubaoConfig:
    """配置豆包 LLM Judge。

    base_url / api_key 优先读取 DOUBAO_BASE_URL / DOUBAO_API_KEY，
    若未配置可回退到 OPENAI_BASE_URL / OPENAI_API_KEY（本环境通用网关）。
    """

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str = "doubao-1.5-pro-32k-250115"
    timeout_seconds: int = 30


@dataclass
class RuleConfig:
    """硬规则配置，如拒答/幻觉关键词、mustMention 提取阈值等。"""

    refusal_keywords: List[str] = field(
        default_factory=lambda: [
            "无法回答",
            "不能回答",
            "不方便回答",
            "对不起",
            "抱歉",
            "作为 AI",
            "作为一名 AI",
        ]
    )
    hallucination_keywords: List[str] = field(
        default_factory=lambda: [
            "纯属虚构",
            "我编造了",
            "捏造的",
            "并不存在的",
        ]
    )
    must_mention_min_length: int = 2


@dataclass
class NoiseConfig:
    """噪声对话生成配置，用于 D04 等长对话场景。"""

    enabled: bool = True
    topics: List[str] = field(
        default_factory=lambda: [
            "今天天气不错，你那边怎么样？",
            "最近在追一部电视剧，剧情特别精彩。",
            "周末打算去公园散步放松一下。",
            "最近工作有点忙，不过还算充实。",
            "在考虑要不要开始健身，感觉身体需要锻炼。",
            "昨天尝试了一家新的餐厅，味道还不错。",
            "最近在看一本关于心理学的书，很有意思。",
            "上周和朋友去爬山，风景特别好。",
            "在学习一门新的编程语言，感觉很有挑战。",
            "准备给房间换一套新的布置，提升一下氛围。",
            "最近在练习做菜，想提高一下厨艺。",
            "偶尔会玩玩游戏放松一下心情。",
            "在考虑今年去哪里旅游比较合适。",
            "最近有点熬夜，打算调整一下作息。",
            "看到一部很感人的电影，一直念念不忘。",
        ]
    )


@dataclass
class AppConfig:
    """应用整体配置。支持从 YAML + 环境变量加载。"""

    arkclaw: ArkclawConfig = field(default_factory=ArkclawConfig)
    doubao: DoubaoConfig = field(default_factory=DoubaoConfig)
    rules: RuleConfig = field(default_factory=RuleConfig)
    noise: NoiseConfig = field(default_factory=NoiseConfig)


def _load_yaml(path: Optional[str]) -> dict:
    if not path:
        return {}
    if not os.path.exists(path):
        return {}
    if yaml is None:
        # pyyaml 未安装时，忽略 YAML 配置
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def load_config(path: Optional[str] = None) -> AppConfig:
    """加载应用配置。

    优先级：环境变量 > YAML 文件 > 代码内默认值。
    """

    raw = _load_yaml(path)

    cfg = AppConfig()

    # Arkclaw
    ark = raw.get("arkclaw", {}) if isinstance(raw.get("arkclaw"), dict) else {}
    cfg.arkclaw.base_url = os.getenv("ARKCLAW_BASE_URL") or ark.get("base_url") or cfg.arkclaw.base_url
    cfg.arkclaw.api_key = os.getenv("ARKCLAW_API_KEY") or ark.get("api_key") or cfg.arkclaw.api_key
    cfg.arkclaw.agent_id = os.getenv("ARKCLAW_AGENT_ID") or ark.get("agent_id") or cfg.arkclaw.agent_id
    cfg.arkclaw.model = ark.get("model") or cfg.arkclaw.model
    if "timeout_seconds" in ark:
        cfg.arkclaw.timeout_seconds = int(ark["timeout_seconds"])

    # Doubao LLM Judge
    db = raw.get("doubao", {}) if isinstance(raw.get("doubao"), dict) else {}
    cfg.doubao.base_url = (
        os.getenv("DOUBAO_BASE_URL")
        or db.get("base_url")
        or os.getenv("OPENAI_BASE_URL")
        or cfg.doubao.base_url
    )
    cfg.doubao.api_key = (
        os.getenv("DOUBAO_API_KEY")
        or db.get("api_key")
        or os.getenv("OPENAI_API_KEY")
        or cfg.doubao.api_key
    )
    cfg.doubao.model = db.get("model") or cfg.doubao.model
    if "timeout_seconds" in db:
        cfg.doubao.timeout_seconds = int(db["timeout_seconds"])

    # 规则配置覆盖
    rules_raw = raw.get("rules", {}) if isinstance(raw.get("rules"), dict) else {}
    if "refusal_keywords" in rules_raw and isinstance(rules_raw["refusal_keywords"], list):
        cfg.rules.refusal_keywords = list(map(str, rules_raw["refusal_keywords"]))
    if "hallucination_keywords" in rules_raw and isinstance(rules_raw["hallucination_keywords"], list):
        cfg.rules.hallucination_keywords = list(map(str, rules_raw["hallucination_keywords"]))
    if "must_mention_min_length" in rules_raw:
        cfg.rules.must_mention_min_length = int(rules_raw["must_mention_min_length"])

    # 噪声配置覆盖
    noise_raw = raw.get("noise", {}) if isinstance(raw.get("noise"), dict) else {}
    if "enabled" in noise_raw:
        cfg.noise.enabled = bool(noise_raw["enabled"])
    if "topics" in noise_raw and isinstance(noise_raw["topics"], list):
        cfg.noise.topics = list(map(str, noise_raw["topics"]))

    return cfg