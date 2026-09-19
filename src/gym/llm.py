"""LLM 接口：生产用 OpenAI 兼容端点（stdlib 实现，零依赖），测试用 MockLLM。

模型分层：generation=旗舰，parse/grade/review=small。成本差异一个量级。
端点安全：仅允许 http(s)；解析后 IP 属链路本地/私网/环回时默认拒绝——
本地 vLLM/Ollama 场景须显式设置 GYM_ALLOW_PRIVATE_NETS=1，防 SSRF/云元数据。
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

_ALLOWED_SCHEMES = {"http", "https"}


class LLM(Protocol):
    """角色调用的最小接口。tier: large=生成旗舰 / small=解析·批改·复盘。"""

    def complete(self, system: str, user: str, *, tier: str = "small") -> str: ...


def validate_endpoint(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError(f"非法 LLM 端点（仅允许 http/https）：{url}")
    allow_private = os.environ.get("GYM_ALLOW_PRIVATE_NETS") == "1"
    infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip == ipaddress.ip_address("0.0.0.0") or ip.is_link_local:  # nosec B104 — 字符串比较（拒绝未指定地址），非接口绑定
            raise ValueError(f"端点解析到禁止地址（链路本地/未指定）：{ip}")
        if not allow_private and (ip.is_loopback or ip.is_private):
            raise ValueError(f"端点解析到私网/环回地址 {ip}；本地模型请设置 GYM_ALLOW_PRIVATE_NETS=1")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # 防 DNS rebinding 后跟随跳转
        raise urllib.error.HTTPError(args[1], 302, "redirect not allowed", {}, None)


class OpenAICompatLLM:
    """任意 OpenAI 兼容端点（GLM/DeepSeek/OpenAI/本地 vLLM 均可）。

    环境变量：GYM_BASE_URL、GYM_API_KEY、GYM_MODEL_LARGE、GYM_MODEL_SMALL、
    GYM_ALLOW_PRIVATE_NETS（使用本地模型时置 1）
    """

    def __init__(self) -> None:
        self.base_url = os.environ["GYM_BASE_URL"].rstrip("/")
        validate_endpoint(self.base_url)
        self.api_key = os.environ["GYM_API_KEY"]
        self.models = {"large": os.environ.get("GYM_MODEL_LARGE", "gpt-4o"),
                       "small": os.environ.get("GYM_MODEL_SMALL", "gpt-4o-mini")}
        self._opener = urllib.request.build_opener(_NoRedirect)

    def complete(self, system: str, user: str, *, tier: str = "small") -> str:
        body = json.dumps({
            "model": self.models[tier],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.7 if tier == "large" else 0.2,
            "response_format": {"type": "json_object"} if tier != "large" else None,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with self._opener.open(req, timeout=120) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]


class MockLLM:
    """按角色关键词返回定死的 JSON，供全链路测试与无 key 演示。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, system: str, user: str, *, tier: str = "small") -> str:
        self.calls.append(system[:40])
        if "检索查询改写器" in system:
            return json.dumps({"query_terms": ["多巴胺", "成瘾", "快乐分子"]}, ensure_ascii=False)
        if "锚定充分性评审" in system:
            return json.dumps({"sufficient": True, "reason": "共识卡覆盖出题所需的核心事实框架"},
                              ensure_ascii=False)
        if "声明抽取" in system:
            return json.dumps({"claims": [
                {"id": 1, "text": "戒断症状在停止使用后数日内出现", "terms": ["戒断症状", "停止使用"]},
                {"id": 2, "text": "成瘾者脑内多巴胺水平异常", "terms": ["成瘾者", "多巴胺"]},
            ]}, ensure_ascii=False)
        if "核对判定" in system:
            return json.dumps({"verdicts": {"1": "consistent", "2": "consistent"}, "notes": {}},
                              ensure_ascii=False)
        if "对抗性知识生成器" in system:
            return json.dumps(_FIXTURE_GENERATION, ensure_ascii=False)
        if "文献曲解生成器" in system:
            return json.dumps(_FIXTURE_M2, ensure_ascii=False)
        if "知识库编目器" in system:
            return json.dumps(_FIXTURE_CARDS, ensure_ascii=False)
        if "批改语义评审" in system:
            return json.dumps({"judgements": {1: {"type": True, "explanation": True},
                                              2: {"type": True, "explanation": True}}}, ensure_ascii=False)
        if "思辨教练" in system:
            return "【教练反馈】做对了，继续。"
        if "复盘引导者" in system:
            return "【复盘】论证链已复原，变式见上。"
        if "命题解析器" in system:
            return json.dumps({"topic": "多巴胺与成瘾", "field": ["神经科学"],
                               "mode": "auto", "difficulty_hint": None,
                               "keywords": ["多巴胺", "成瘾", "dopamine"], "safety_flag": False,
                               "safety_reason": ""}, ensure_ascii=False)
        raise ValueError("MockLLM: 未知角色提示词")


_FIXTURE_GENERATION = {
    "article": ("[第1段] 多巴胺常被称为快乐分子，但这一说法并不准确。\n"
                "[第2段] 研究显示成瘾者脑内多巴胺水平异常，因此所有成瘾行为都源于多巴胺。\n"
                "[第3段] 戒断症状在停止使用后数日内出现。\n"
                "[第4段] 某康复项目中 90% 的成功者都坚持了运动，可见运动足以戒除任何成瘾。\n"
                "[第5段] 综上，成瘾不过是意志力问题。"),
    "answer_key": [
        {"id": 1, "type": "false_cause", "severity": "L1", "paragraph": 2,
         "quote": "因此所有成瘾行为都源于多巴胺",
         "explanation": "相关不等于因果：多巴胺异常与成瘾相关，但不能推出'所有成瘾都源于多巴胺'。"},
        {"id": 2, "type": "hasty_generalization", "severity": "L1", "paragraph": 4,
         "quote": "可见运动足以戒除任何成瘾",
         "explanation": "幸存者样本：只统计了成功的 90%，未考虑失败者，且'足以戒除任何'过度概括。"},
    ],
    "distractors": ["戒断症状在停止使用后数日内出现。"],
    "fallacy_count": 2,
    "watermark": "本文由思辨训练系统生成，为教学目的刻意埋入 2 处逻辑谬误，请勿外传引用。",
}

_FIXTURE_M2 = {
    "distorted_text": ("[第1段] 原文指出：在雄性小鼠模型中，药物 X 使肿瘤体积缩小了 40%。\n"
                       "[第2段] 由此可见，药物 X 能使人类的肿瘤体积缩小 40%。\n"
                       "[第3段] 原文同时提示该结果尚未在临床试验中重复。\n"
                       "[第4段] 综上所述，药物 X 对人类肿瘤的疗效已经确证。"),
    "answer_key": [
        {"id": 1, "type": "scope_shift", "severity": "L2", "paragraph": 2,
         "quote": "由此可见，药物 X 能使人类的肿瘤体积缩小 40%",
         "original_meaning": "原文仅报告雄性小鼠模型中肿瘤缩小 40%，未涉及人类。",
         "explanation": "曲解维度：范围（小鼠→人类）"},
        {"id": 2, "type": "hasty_generalization", "severity": "L2", "paragraph": 4,
         "quote": "药物 X 对人类肿瘤的疗效已经确证",
         "original_meaning": "原文明确提示结果尚未在临床试验中重复。",
         "explanation": "曲解维度：确证程度（初步→确证）"},
    ],
    "distractors": ["原文同时提示该结果尚未在临床试验中重复。"],
    "watermark": "本文为思辨训练生成的曲解版本（来源：用户提供的文本），共含 2 处刻意曲解，请以原文为准。",
}

_FIXTURE_CARDS = [
    {"field": "计算机科学", "topic": "大模型推理成本持续下降",
     "mainstream_claim": "近一月多篇论文报告推理成本较去年下降一个量级",
     "keywords": ["大模型", "推理成本", "LLM"], "date": "2026-09-10",
     "source": "arXiv cs.CL", "distortion_potential": "medium",
     "dedup_key": "大模型推理成本持续下降"},
    {"field": "神经科学", "topic": "睡眠与记忆巩固的因果证据增强",
     "mainstream_claim": "新研究在小鼠模型中增强睡眠—记忆巩固的因果证据",
     "keywords": ["睡眠", "记忆巩固", "memory"], "date": "2026-09-15",
     "source": "Nature", "distortion_potential": "high",
     "dedup_key": "睡眠与记忆巩固的因果证据增强"},
]
