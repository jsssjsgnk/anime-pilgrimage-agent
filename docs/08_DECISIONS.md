# 已冻结决策与待验证事项

## 已冻结

1. React/TypeScript Web，FastAPI/Pydantic 后端，LangGraph 编排；
2. PostgreSQL + pgvector；本地多语言 embedding，不新增 embedding API Key；
3. SearchAPI 替代 Duffel/Amadeus；只搜索，不预订；
4. ORS 是路线估算主 Provider，Google Maps URL 是现场导航；
5. MCP 用于标准化只读外部工具边界；实现自己控制的 MCP 服务；
6. Route A 全量候选、Route B 可执行子集；
7. 确定性程序负责约束，LLM 负责语言、解释和修订；
8. 五类项目内记忆，长期偏好需显式授权；不涉及 ChatGPT 账号记忆；
9. 六阶段由 Codex 连续实施并自行验收；
10. 不自动付款、出票、预订或批量抓取社区平台。
11. 允许创建专用 Conda 环境 `anime-pilgrimage-agent`；Conda 隔离 Python，uv 锁定依赖。
12. Docker Compose 用于 PostgreSQL + pgvector 和最终完整验收；日常开发不强制所有进程容器化。
13. RAG 使用本地 multilingual-e5-small + pgvector exact cosine + bm25s + RRF；Codex 可研究公开资料制作固定测试语料，但实时结构化事实不进入 RAG。

## 待 Codex 在实现中验证

- 用户 DeepSeek 服务的 OpenAI-compatible 细节、结构化输出和工具调用能力；
- Bangumi 当前 API Schema、限流和 User-Agent 规则；
- SearchAPI 当前字段、Calendar 流程和免费额度；
- ORS 当前 matrix/directions 限额；
- Anitabi 是否存在稳定且允许的公开读取方式；
- MapLibre 底图的开发/展示使用条款；
- 所选本地多语言 embedding 模型的体积、许可证和中日文效果。

验证时优先官方文档。结果写入 `docs/adr/`，但除非出现阻塞，不改变已冻结的产品边界。

## 允许的降级

- Anitabi 不可用 → 合法 JSON/GeoJSON 导入 + Fixture；
- SearchAPI 不可用 → 人工候选/搜索链接，无价格；
- ORS 不可用 → Haversine 并明确标注；
- 天气超出范围 → 未知/稍后查询；
- LLM 不支持稳定原生工具调用 → 显式 LangGraph 节点调用 MCP，并用 Pydantic JSON 输出；
- 外部 live smoke 临时失败 → Fixture 门禁继续，最终报告 live 失败，不伪造成功。
