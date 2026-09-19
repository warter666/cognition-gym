# 思辨健身房（cognition-gym）

AI 生成埋有逻辑谬误/刻意曲解的文章，用户找茬训练思辨能力。**确定性状态机编排 + 角色化 LLM + 代码化批改**——批改公平性靠代码保证，不靠提示词自觉。

工程化决策与取舍（为什么不用 Coze、为什么不是自治多 agent）：见 [PLAN.md](PLAN.md)。
设计依据（闭环状态机 + 答案卡）：见 `../agent_contest_extract/工作流v2/README.md`。

## 快速开始

```bash
# 演示模式（无需任何配置，内容为固定示例）
python apps/cli.py train "成瘾行为的多巴胺机制"

# M2 曲解论文（源文本=你粘贴的论文摘要）
python apps/cli.py train --m2 --source paper_abstract.txt "药物 X 的抗肿瘤效果"

# 策展：RSS/Atom 文件 → 热度卡增量入库（去重）
python apps/cli.py curate feed.rss

# 评测：离线 kappa（引擎 vs 人工标注样例）；--live 逐题真实生成查边界
python apps/cli.py eval
```

# 接真实模型（任意 OpenAI 兼容端点）
export GYM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
export GYM_API_KEY=sk-...
export GYM_MODEL_LARGE=glm-4.6      # 生成（旗舰）
export GYM_MODEL_SMALL=glm-4.5-flash # 解析/批改/复盘（小模型）
python apps/cli.py "成瘾行为的多巴胺机制"

# 本地模型（Ollama/vLLM，私网端点需显式放行）
export GYM_BASE_URL=http://127.0.0.1:11434/v1 GYM_ALLOW_PRIVATE_NETS=1
```

作答格式：每行 `原文摘句 | 理由`，空行提交。

## 测试

```bash
python -m pytest -q   # 45 个用例：状态机/路由/位置匹配/全链路/安全拒答/验收门（答案卡断言+事实核查）/锚定代理
```

## 架构一览

```
用户命题 → P0 解析(small) → 热度路由(代码) → P2 生成(large，答案卡同源双输出)
         → 用户作答 → P3 批改（位置匹配=代码，类型/解释=small）
         → P4 教练分级提示(small) → P5 复盘+变式(small) → 错题本 → 难度状态机(代码) → 下一轮
```

关键机制：
- **答案卡断言**（`taxonomy.py`）：quote 不在正文、谬误超表 → 生成物作废重试，批改公平性的硬门
- **代码化位置匹配**（`grading.py`）：difflib 相似度阈值，LLM 只判模糊语义，无法越权改分
- **难度状态机**（`state.py`）：≥90 升 / <60 降 / 连败 3 次熔断进脚手架
- **仲裁通道**（`grading.py`）：用户指出答案卡未覆盖处不扣分，复盘节点裁决，保护表达欲
- **端点安全**（`llm.py`）：http(s) 白名单 + 链路本地/私网默认拒绝（本地模型显式放行）

## 路线图

W1-W5（骨架✅ / M1✅ / 评测骨架✅ / M2+错题本✅ / 策展管线◐）→ R2：向量检索（仅桥梁概念场景）、M3 跨学科融合、web 皮、Coze 渠道皮（按需决策门）。详见 [PLAN.md](PLAN.md) §6。
