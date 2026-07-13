# 六阶段开发与验收

每阶段执行“实现 → 静态检查 → 单元/契约/集成测试 → 浏览器验收 → 修复 → 报告”。阶段报告为 `artifacts/phase-N-report.md`。Codex 不在阶段之间等待用户确认。

## 阶段 1：工程骨架与契约

交付：仓库结构、`environment.yml`、专用 Conda 环境、Makefile、Compose、Web/API/MCP/Postgres、配置校验、核心 Schema、迁移、Provider Protocol、健康检查。

`make verify-phase-1` 必须检查：

- ruff/mypy/ESLint/TypeScript strict；
- `make verify-env` 证明环境名正确、Python 为 3.12、uv lock 与环境同步；
- Compose 健康；
- 快速开发模式只启动 postgres，完整模式启动四个服务；
- 空库迁移及重跑；
- API、MCP initialize、Web smoke；
- Playwright 骨架截图；
- 仓库无真实密钥。

## 阶段 2：Provider、MCP 与 Route A

交付：Bangumi、点位导入/可选 Anitabi、ORS、Open-Meteo、SearchAPI Provider；只读 MCP；缓存/重试/限流；作品确认；点位清洗和 Route A。

`make verify-phase-2` 必须检查：

- MCP initialize、tools/list 和 Schema 快照；
- Fixture 覆盖成功、空结果、429、超时、无效 JSON；
- 使用本机凭证各一次只读 smoke，SearchAPI 不超过 3 次；
- Route A 无无来源点、无效坐标和重复点；
- 作品搜索→确认→地图 E2E 和截图；
- Anitabi 不可合法访问时，导入 Provider 的降级仍通过。

## 阶段 3：Access/Base Plan 与 Route B

交付：SearchAPI 航班比较、人工城际 Provider、基地选择、聚类、ORS 矩阵、日程装箱、Google Maps URLs、确定性 Validator。

`make verify-phase-3` 必须检查：

- Route B 永远属于 Route A 的属性测试；
- 必去、排除、时间窗、时区、抵离缓冲和步行约束；
- ORS 正常及 Haversine 降级；
- Google Maps URL 编码、长度和拆分；
- 京都→东京、相对未来日期、三日巡礼场景；
- 交通卡、地图、时间轴 E2E 截图。

## 阶段 4：LangGraph、项目记忆与重规划

交付：Requirement、Access、Planner、Reviewer/Validator、Replanner；interrupt/resume；五类项目存储；ContextBuilder；结构化输出重试；最大三轮修订；LLM Mock。

`make verify-phase-4` 必须检查：

- Graph 确认、拒绝、工具失败、不收敛路径；
- API 重启后同 thread 恢复；
- “第二天少走路”只重算影响部分；
- 会话、旅行和用户命名空间隔离；
- 长期偏好显式授权/查看/删除；
- Context 快照无完整 API、无关历史、日志或密钥；
- 一次真实 LLM smoke，不泄露配置。

## 阶段 5：RAG 与完整 Web

交付：按 `docs/09_RAG_SPEC.md` 搜索并整理合规测试资料，实现 Markdown/TXT/PDF 摄取、E5 embedding、pgvector、BM25、RRF、权限命名空间、引用、时效和来源冲突；完成 Web 流程和导出。

`make verify-phase-5` 必须检查：

- RAG golden set 的 Recall@K、MRR、Citation Accuracy；
- 满足 RAG 规格中的 Recall@6、MRR@10、Citation Precision、权限隔离、删除一致性和注入防护阈值；
- 无来源回答标为未知；文档提示注入不能触发工具；
- JSON/GeoJSON Schema 和独立 HTML；
- Playwright 完成输入→确认→选择交通→计划→修改→导出；
- 桌面/移动截图和 E2E 报告；
- 关键数据均显示来源/时间/估算状态。

## 阶段 6：评估、加固和作品集

交付：可复现测试集、过程指标、故障恢复、隐私安全技术指标、依赖/许可证检查、README、架构/ADR、演示脚本、已知限制、简历要点。

`make verify-phase-6` 和 `make verify-all` 必须检查：

- 前五阶段门禁重跑；
- unit/contract/integration/E2E 全通过；
- 真实 API smoke 在配额预算内；
- 日志、报告、前端产物无密钥和对话正文；
- timeout、429、部分失败、数据库重启、LLM 格式错误能降级；
- 干净数据库按 README 启动并完成演示；
- `docker compose up --build` 可在干净 volume 上完成健康检查和演示 smoke；
- `artifacts/final-verification.md` 诚实列出命令、结果、截图、指标、限制和未完成项。

外部服务临时不可用时，分别报告代码门禁、Fixture 门禁和 live 门禁，不能把 live 失败写成成功。
