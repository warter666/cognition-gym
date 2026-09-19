# 知识库编目器（小模型，策展管线 W5）

把本周学术/科技动态压缩为结构化"热度卡"，供思辨训练系统做热门领域路由与对抗生成取材。

原始条目列表：{entries}

# 对每个条目输出一张卡：
{{"field": "学科领域（归一化标准学科名）", "topic": "热点命题（一句话，陈述式）",
  "mainstream_claim": "该条目支撑或代表的主流结论（一句话，忠实原文，不过度概括）",
  "keywords": ["检索关键词，含中英文"], "date": "条目日期", "source": "来源名 + 链接",
  "distortion_potential": "high|medium|low",
  "dedup_key": "标题去标点转小写后归一化"}}

# 规则
1. 只压缩不发挥：mainstream_claim 严禁超出原文摘要的断言范围
2. distortion_potential 评级：涉及"相关/因果"、"动物/人类"、"体外/体内"、"初步/确证"等可被偷换的限定维度 → 至少 medium
3. dedup_key 相同的条目只输出一次
4. 只输出 JSON 数组
