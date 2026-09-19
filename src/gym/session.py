"""训练会话编排器：P0 解析 → 锚定 → P2 生成 → 用户作答 → P3 批改 → P4 反馈 → P5 复盘。

编排是确定性的：LLM 只承担角色化职责（解析/生成/语义评审/教练/复盘），
流程控制、位置匹配、答案卡校验全部在代码里。知识锚定与 M1 事实核查
委托给 anchoring 的有界 agent 环（全项目唯一的 agent 环）。
支持 M1（瑕疵论文）与 M2（曲解论文，源文本=用户粘贴）。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from . import anchoring, prompts, taxonomy
from .grading import assemble_grading, match_positions
from .llm import LLM
from .schema import AnswerKey, FallacyItem, Grading, SessionState, UserMark
from .state import DifficultyStateMachine


def _loads(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


class TrainingSession:
    def __init__(self, llm: LLM, store=None, kb_context: str = "",
                 user_id: str = "local") -> None:
        self.llm = llm
        self.store = store
        self.user_id = user_id
        self.kb_context = kb_context or "（知识库冷启动，无检索结果）"
        self.state = SessionState()
        self.sm = DifficultyStateMachine()
        self.answer_key: AnswerKey | None = None
        self.mistake_book: list[dict[str, Any]] = []

    # ---- P0/P2：出题 -------------------------------------------------

    def start(self, topic: str, mode: str = "M1", source_text: str | None = None) -> str:
        parsed = _loads(self.llm.complete(
            prompts.load("parser.md").format(user_input=topic), "", tier="small"))
        if parsed.get("safety_flag"):
            raise ValueError(f"命题触发安全边界：{parsed.get('safety_reason', '未说明')}")
        if mode not in {"M1", "M2"}:
            raise NotImplementedError(f"模式 {mode} 在 R2 交付，当前支持 M1/M2")
        if mode == "M2" and not source_text:
            raise ValueError("M2 需要源文本：粘贴论文摘要/结论段作为 source_text")

        preferred = self._preferred_fallacy()
        if mode == "M2":
            context, anchored, anchor_trace = "（M2 源文本由用户提供，不依赖知识库锚定）", True, []
        else:
            context, anchored, anchor_trace = anchoring.anchor(
                parsed["topic"], parsed.get("keywords", []), self.store,
                self.llm, kb_context=self.kb_context)
        if mode == "M1":
            key_json = self._generate(
                "m1_generator.md", article_field="article", mode=mode,
                fmt=dict(topic=parsed["topic"], field="、".join(parsed.get("field", [])),
                         preferred_type=preferred or "无"),
                context=context)
            article, items = key_json["article"], key_json["answer_key"]
        else:
            key_json = self._generate(
                "m2_generator.md", article_field="distorted_text", mode=mode,
                fmt=dict(source_text=source_text, source_meta="用户提供的文本",
                         preferred_type=preferred or "无"),
                context=context)
            article, items = key_json["distorted_text"], key_json["answer_key"]
            for it in items:  # 还原训练：解释 = 原意 + 曲解维度
                it["explanation"] = f"原意：{it.get('original_meaning', '')}｜{it.get('explanation', '')}"

        fact_audit = key_json.pop("fact_audit", None)
        key = AnswerKey(
            mode=mode, topic=parsed["topic"], article=article,
            items=[FallacyItem(**{k: v for k, v in it.items() if k in FallacyItem.__dataclass_fields__})
                   for it in items],
            distractors=key_json.get("distractors", []),
        )
        self.answer_key = key
        self.state.round_no += 1
        if self.store:
            self.store.save_answer_key(self.state.round_no, {
                **key.to_json(), "anchored": anchored,
                "anchor_trace": anchor_trace, "fact_audit": fact_audit})
        return f"{key.article}\n\n{key_json.get('watermark', '')}"

    def _generate(self, prompt_name: str, *, article_field: str, fmt: dict,
                  context: str, mode: str = "M1") -> dict[str, Any]:
        """验收门 + 1 次重试：答案卡断言（M1/M2）+ 事实核查（仅 M1，有库时）。

        事实核查是验收门的一部分而非事后补丁：与库内共识明确矛盾的生成物
        视为不合格，永不带病入库（PLAN.md §5 的"批改公平性第一道门"在知识侧的延伸）。
        """
        fmt.update(params=json.dumps(self.sm.generation_params(self.state, scaffold=False), ensure_ascii=False),
                   taxonomy=json.dumps(taxonomy.TAXONOMY["categories"], ensure_ascii=False),
                   context=context)
        system = prompts.load(prompt_name).format(**fmt)
        last_problems: list[str] = []
        for _ in range(2):
            out = _loads(self.llm.complete(system, "", tier="large"))
            out["article"] = out[article_field]  # 校验与 AnswerKey 构造统一走 article 字段
            last_problems = taxonomy.validate_answer_key(out)
            if not last_problems and mode == "M1" and self.store:
                audit = anchoring.fact_check(out["article"], self.store, self.llm)
                out["fact_audit"] = audit
                last_problems = [f"事实核查矛盾：{c['text'][:40]}（{c.get('note', '')[:40]}）"
                                 for c in audit["contradicted"]]
            if not last_problems:
                return out
        raise RuntimeError(f"生成物两次未通过验收门（答案卡断言/事实核查），丢弃：{last_problems}")

    def _preferred_fallacy(self) -> str:
        if self.store:
            weak = self.store.weak_types(self.user_id)
            due = self.store.due_review_types(self.user_id)
            return (due or weak or [""])[0]
        weak = [m["fallacy_type"] for m in self.mistake_book if m["percent"] < 60]
        return weak[-1] if weak else ""

    # ---- P3/P4/P5：批改、反馈、复盘 -----------------------------------

    def submit(self, marks: list[UserMark]) -> tuple[Grading, str, str]:
        if self.answer_key is None:
            raise RuntimeError("先调用 start() 出题")
        key = self.answer_key

        matched = match_positions(key, marks)  # 位置分：代码判定
        hit_items = [it for it in key.items if it.id in matched["key_hits"]]
        judgements: dict[int, dict[str, bool]] = {}
        if hit_items:
            out = _loads(self.llm.complete(
                prompts.load("grader.md").format(
                    items=json.dumps([{"id": it.id, "type": it.type, "explanation": it.explanation}
                                      for it in hit_items], ensure_ascii=False),
                    marks=json.dumps([{"quote": marks[matched["key_hits"][it.id][0]].quote,
                                       "reason": marks[matched["key_hits"][it.id][0]].reason}
                                      for it in hit_items], ensure_ascii=False)),
                "", tier="small"))
            judgements = {int(k): v for k, v in out.get("judgements", {}).items()}

        grading = assemble_grading(key, marks, judgements)
        fused = self.sm.update(self.state, grading.percent)

        coach = self.llm.complete(prompts.load("coach.md").format(
            grading=json.dumps(asdict(grading), ensure_ascii=False),
            answer_key=json.dumps([asdict(it) for it in key.items], ensure_ascii=False),
            fused=fused, difficulty=self.state.difficulty), "", tier="small")
        review = self.llm.complete(prompts.load("reviewer.md").format(
            answer_key=json.dumps([asdict(it) for it in key.items], ensure_ascii=False),
            grading=json.dumps(asdict(grading), ensure_ascii=False),
            user_history=json.dumps([a.get("reason", "") for a in grading.arbitrated], ensure_ascii=False)),
            "", tier="small")

        worst_type = key.items[0].type if key.items else ""
        self.mistake_book.append({"topic": key.topic, "fallacy_type": worst_type,
                                  "percent": grading.percent, "date": ""})
        if self.store:
            self.store.add_mistake(self.user_id, key.topic, worst_type,
                                   grading.percent, date=self._today())
        return grading, coach, review

    @staticmethod
    def _today() -> str:
        from datetime import date
        return date.today().isoformat()
