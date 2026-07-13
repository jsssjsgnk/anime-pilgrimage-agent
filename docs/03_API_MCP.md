# API 与 MCP 契约

## 凭证清单

项目只要求四类用户凭证：

```dotenv
LLM_API_KEY=
BANGUMI_ACCESS_TOKEN=
ORS_API_KEY=
SEARCHAPI_API_KEY=
```

LLM 另需用户服务商的 `LLM_BASE_URL` 和精确 `LLM_MODEL`；它们不是密钥。`BANGUMI_USER_AGENT` 是公开应用标识，不是密钥。

Open-Meteo、Google Maps URLs 和基础地图不需要额外 Key。Duffel/Amadeus 不得成为必需配置。

## MCP 策略

实现一个自己控制的只读 `mcp-tools` 服务。社区 MCP 可以作为设计参考，但不得未经审计直接成为核心依赖。

白名单工具：

| Tool | 输入要点 | 标准输出 |
|---|---|---|
| `search_anime_subjects` | query, limit | SubjectCandidate[] |
| `get_anime_subject` | subject_id | ConfirmedSubject |
| `fetch_pilgrimage_points` | subject_id/provider | PilgrimagePoint[] + provenance |
| `geocode_place` | text, language | PlaceCandidate[] |
| `get_route_directions` | coordinates, profile | RouteLeg |
| `get_route_matrix` | coordinates, profile | duration/distance matrix |
| `get_weather_forecast` | coordinates, dates | WeatherWindow[] |
| `search_flight_options` | airports, dates, passengers, cabin, currency | FlightOption[] |
| `search_flexible_flight_dates` | airports, date window | FareDateCandidate[] |

全部工具只读，不提供订票、支付、Bangumi 写入、任意网页抓取、shell 或文件系统能力。输入限制日期窗口、坐标、字符串长度、人数和批量大小。

Agent 通过 `langchain-mcp-adapters` 连接，只加载白名单。工具输出先经 Pydantic 验证和规范化，再进入 Agent 上下文。

## SearchAPI

- 使用 Google Flights 和 Calendar 搜索能力；
- 支持单程和往返；多城市可延后；
- 输入使用 IATA、日期、乘客、舱位、币种和地区；
- 输出保存 provider、queried_at、expires_at、价格、币种、航段、中转、时长和确认链接；
- 价格是查询时快照，UI 必须要求用户在购票平台再次确认；
- 正常测试使用 Fixture；全套真实验收的 SearchAPI 调用总数不超过 10；
- Provider 失败时只能返回人工候选或搜索链接，不能编造价格。

## Bangumi

- 使用 Bearer Token 和固定 User-Agent；
- 搜索候选后必须由用户确认 Subject ID；
- 公共读取和用户数据分开；MVP 不实现写操作；
- 缓存基本条目，但保留 fetched_at/provider/source URL。

## ORS

- 用于地理编码、directions 和 matrix；
- Route B 先生成候选顺序，再用 ORS 验证道路距离和时间；
- 失败时允许 Haversine 降级，结果必须明确标为直线估算；
- Google Maps URL 只负责现场导航跳转，不代替 ORS 的计划估算。

## Open-Meteo

- 无 Key，只读；
- 按坐标和日期查询；超出可预报范围时返回“无法提供实时预报”，不得用历史均值冒充预报；
- 天气影响作为软/硬约束必须可解释。

## 巡礼点 Provider

- 若 Anitabi 有稳定且允许的公开访问方式，封装为 `AnitabiProvider`；
- 不绕过登录、验证码、限流或站点保护；
- 始终实现 `ImportedPilgrimagePointProvider`，支持 JSON/GeoJSON；
- 测试使用小型 Fixture；
- 不批量重新分发第三方图片或完整数据库；
- 每点保留 provider、source URL、fetched_at 和可信状态。

## 缓存和错误

统一错误分类：validation、auth、quota、rate_limit、timeout、upstream、not_found、partial_data。

每个缓存项包含 provider、request fingerprint、fetched_at、expires_at、schema_version。航班短 TTL；作品和地理编码可较长；天气依预测日期决定。缓存不得包含 Authorization 或用户对话。
