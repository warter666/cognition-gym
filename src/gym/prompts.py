"""角色提示词：从 工作流v2/prompts 清洗迁移（去 Coze 变量语法，改 str.format 占位）。

契约与 schema.py 对齐：生成器输出 JSON 必须通过 taxonomy.validate_answer_key。
"""

PROMPTS_DIR = __import__("pathlib").Path(__file__).parent / "prompts"


def load(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")
