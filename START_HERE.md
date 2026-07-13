# Codex 开始入口

本目录是“动漫圣地巡礼旅行 Agent”的完整开发交接包。不要只根据聊天摘要编码。

## 开始方式

1. 确认本目录位于专用 Git 仓库根目录；
2. 先读 `AGENTS.md`；
3. 按下列顺序阅读全部必读文档；
4. 按 `environment.yml` 创建或复用独立 Conda 环境 `anime-pilgrimage-agent`；
5. 检查 Docker/Compose，并启动 PostgreSQL + pgvector；
6. 检查本机 `.env`，只确认变量存在，不输出值；
7. 输出简短执行计划；
8. 连续完成六阶段，每阶段运行门禁并自行修复；
9. 最终以 `make verify-all` 和 `artifacts/final-verification.md` 为完成证据。

## 必读顺序

1. `docs/01_PRODUCT_SPEC.md`
2. `docs/02_ARCHITECTURE.md`
3. `docs/03_API_MCP.md`
4. `docs/04_MEMORY_CONTEXT.md`
5. `docs/05_PHASE_ACCEPTANCE.md`
6. `docs/06_DATA_SAFETY.md`
7. `docs/07_TEST_SCENARIOS.md`
8. `docs/08_DECISIONS.md`
9. `docs/09_RAG_SPEC.md`

## 已冻结的外部依赖

- LLM：用户提供的 OpenAI-compatible DeepSeek API，模型 ID 通过环境变量配置；
- 动漫目录：Bangumi API；
- 路线/地理编码：openrouteservice；
- 航班：SearchAPI Google Flights/Calendar；
- 天气：Open-Meteo，无 Key；
- 地图：MapLibre + OpenStreetMap/OpenFreeMap；
- 现场导航：Google Maps URLs，无 Key；
- 巡礼点：可替换 Provider；只有在公开规则允许时接入 Anitabi，否则使用合法导入和 Fixture。

Duffel 和 Amadeus 不是 MVP 前置依赖。

## 本地环境与 Docker

用户已允许新建独立 Conda 环境。使用：

```bash
conda env create -f environment.yml
conda activate anime-pilgrimage-agent
```

同名环境已存在时先检查，再用 `conda env update -f environment.yml --prune`；不得删除或修改其他环境。非交互 shell 使用 `conda run -n anime-pilgrimage-agent ...`。Conda 提供 Python/uv 隔离，Python 项目依赖仍由 uv lockfile 管理。

提供两种运行模式：

- **快速开发**：Conda 运行 API/MCP，pnpm 运行 Web，Docker 只运行 PostgreSQL + pgvector；
- **完整验收**：Docker Compose 构建并运行 web、api、mcp-tools、postgres。

最终 README 必须同时说明两种方式。

## 完成定义

只有以下条件全部满足才算完成：

- 六个 `make verify-phase-N` 均成功；
- `make verify-all` 成功；
- Fixture 测试、真实 API smoke、浏览器 E2E 分开报告；
- 关键页面有桌面和移动截图；
- README 能从干净数据库复现；
- 无真实密钥、无编造点位、无虚构价格；
- 未完成项如实列出。
