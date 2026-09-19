"""gym CLI：train / curate / eval 三个子命令。

无 GYM_* 环境变量时以 MockLLM 演示模式运行（体验流程用，内容为固定示例）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .llm import MockLLM, OpenAICompatLLM
from .schema import UserMark
from .session import TrainingSession
from .storage import Store


def _make_llm():
    if {"GYM_BASE_URL", "GYM_API_KEY"} <= set(os.environ):
        return OpenAICompatLLM()
    print("（未配置 GYM_* 环境变量，进入 MockLLM 演示模式）")
    return MockLLM()


def _read_marks() -> list[UserMark]:
    print("请标注可疑句，格式：摘句 | 理由（每行一条，空行结束）")
    marks = []
    while True:
        try:
            line = input("你> ").strip()
        except EOFError:
            break
        if not line:
            break
        quote, _, reason = line.partition("|")
        marks.append(UserMark(quote=quote.strip(), reason=reason.strip()))
    return marks


def cmd_train(args: argparse.Namespace) -> None:
    store = Store(args.db)
    llm = _make_llm()
    session = TrainingSession(llm, store=store)
    topic = " ".join(args.topic).strip() or "成瘾行为的多巴胺机制"
    mode = "M2" if args.m2 else "M1"
    source_text = Path(args.source).read_text(encoding="utf-8") if args.source else None
    if args.source and not source_text:
        raise SystemExit(f"源文件为空：{args.source}")

    print(f"\n[P2 出题] 命题：{topic}（模式 {mode}，难度 {session.state.difficulty}）\n")
    print(session.start(topic, mode=mode, source_text=source_text))
    marks = _read_marks()
    grading, coach, review = session.submit(marks)
    print(f"\n[P3 批改] {grading.percent}%（明细：{grading.per_item}）")
    print(f"\n[P4 教练]\n{coach}")
    print(f"\n[P5 复盘]\n{review}")
    print(f"\n[状态] 难度={session.state.difficulty} 连败={session.state.streak_fail} "
          f"轮次={session.state.round_no}（错题本已写入 {args.db}）")
    store.close()


def cmd_curate(args: argparse.Namespace) -> None:
    from .curator import curate
    store = Store(args.db)
    xml_text = Path(args.feed).read_text(encoding="utf-8")
    report = curate(store, xml_text, _make_llm())
    print(json.dumps(report, ensure_ascii=False))
    print(f"[热度卡] 库内各领域条目：{store.field_freq()}")
    store.close()


def cmd_eval(args: argparse.Namespace) -> None:
    from .evals import eval_generation, eval_grading_agreement, eval_retrieval
    llm = _make_llm()
    root = Path(__file__).resolve().parents[2] / "evals"

    if args.retrieval:
        golden = json.loads((root / "retrieval_golden.json").read_text(encoding="utf-8"))
        store = Store(args.db)
        report = eval_retrieval(store, golden)
        store.close()
        print("检索质量回归（黄金集 recall@k / MRR，门禁 ≥0.8）：")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if args.live:
        topics = json.loads((root / "golden_topics.json").read_text(encoding="utf-8"))
        print(json.dumps(eval_generation(llm, topics), ensure_ascii=False, indent=2))
        return
    labeled = json.loads((root / "agreement_sample.json").read_text(encoding="utf-8"))
    print("批改一致性（引擎 vs 人工标注）：")
    print(json.dumps(eval_grading_agreement(llm, labeled), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gym", description="思辨健身房")
    parser.add_argument("--db", default="gym.db", help="SQLite 路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(p: argparse.ArgumentParser) -> None:  # 子命令后也可用 --db
        p.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p_train = sub.add_parser("train", help="训练一轮（默认 M1；--m2 曲解论文）")
    add(p_train)
    p_train.add_argument("topic", nargs="*", help="训练命题")
    p_train.add_argument("--m2", action="store_true", help="曲解论文模式")
    p_train.add_argument("--source", help="M2 源文本文件路径")

    p_curate = sub.add_parser("curate", help="策展：RSS/Atom 文件 → 热度卡入库")
    add(p_curate)
    p_curate.add_argument("feed", help="RSS/Atom XML 文件路径")

    p_eval = sub.add_parser("eval", help="评测（默认离线 kappa；--live 生成评测；--retrieval 检索回归）")
    add(p_eval)
    p_eval.add_argument("--live", action="store_true", help="逐题真实生成并检查边界")
    p_eval.add_argument("--retrieval", action="store_true", help="黄金集 recall@k / MRR 回归")

    args = parser.parse_args(argv)
    if not hasattr(args, "db"):
        args.db = "gym.db"
    {"train": cmd_train, "curate": cmd_curate, "eval": cmd_eval}[args.cmd](args)
