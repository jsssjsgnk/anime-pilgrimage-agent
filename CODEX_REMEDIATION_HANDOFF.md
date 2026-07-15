# 动漫圣地巡礼 Agent：最新版整改与升级交接说明

> 交接对象：桌面版 Codex  
> 目标仓库：`jsssjsgnk/anime-pilgrimage-agent`  
> 基准分支：`codex/publish-current-project`  
> 已审查基准提交：`c544c3b9c1010d17e3a117c73ae273c489c0af56`  
> 文档目的：Codex 应仅依赖本文件与仓库代码完成后续整改，不依赖此前 ChatGPT 对话或账号记忆。  
> 优先级原则：这是一个 **Agent 项目**。Agent 编排、上下文、工具调用、验证和重规划是主线；地图、页面和导出是承载这些能力的产品界面。

---

## 1. 项目最终定位

构建一个网页端、开放对话式、可验证、可修改的动漫圣地巡礼旅行 Agent。

系统应从用户自然语言中理解作品、日期、出发地、目的地、预算、住宿、步行偏好和必去场景，确认 Bangumi 条目，取得完整 Anitabi 点位，查询航班、公共交通、换乘、营业时间和天气，再生成可解释、可修改、可验证的多作品、多城市、多日计划。

完整旅行链路：

```text
用户所在地
→ 航班或长途交通
→ 机场/主要车站
→ 住宿基地
→ 每日巡礼区域
→ Anitabi 场景点/现实地点
→ 公共交通与步行路线
→ 出发前复核
```

系统不负责订票、付款或自动执行外部不可逆操作，只提供带来源和查询时间的候选，并要求用户确认关键选择。

---

## 2. 当前最新版已经完成的能力

以下能力已经存在，应保留并在此基础上整改：

- React + TypeScript + Vite 前端和 MapLibre 地图；
- FastAPI、Pydantic、PostgreSQL/Alembic；
- Docker Compose 和 Conda/本地开发环境边界；
- Bangumi 作品搜索与显式确认；
- 一个作品意图可确认多个 Bangumi 条目，例如多季度和剧场版；
- 一个工作区最多管理 12 个作品意图；
- 工作区内添加和移除作品，移除一部作品后保留其他作品；
- Anitabi 点位、SceneEvidence、VisitPlace、AreaCluster 的初步分层；
- PlanPatch 预览、确认、幂等键、基准版本冲突检查；
- 地点包含、排除、移动日期、顺序调整；
- 多个 ItineraryVersion、修改记录和持久化对话；
- AgentRole、RoleContext、AgentHandoff 等结构化领域模型；
- ORS、Open-Meteo、SearchAPI Flights 等 Provider/MCP 工具基础；
- RAG 文档、混合检索和派生规则基础；
- 现有前端单元测试 9/9 通过，仓库记录的 `make verify-all` 为 PASS。

不要推翻这些已完成模块；应修正主链和行为语义，并复用现有模型、Provider 和测试资产。

---

## 3. 当前最重要的问题

### 3.1 新版多作品工作区没有使用 LangGraph

当前主链实际是：

```text
TripWorkspace → /api/workspaces → WorkspaceAgent → 确定性函数
```

仓库中的旧版 LangGraph workflow 会调用 RequirementExtractor、天气、航班、ORS、Reviewer 和 RAG，但新版多作品工作区没有走这条链。

`ApplicationResources` 创建了 LLM Reviewer，却只把它传给旧 workflow；新版 `WorkspaceAgent` 只得到 tool client 和 requirement extractor。

因此仓库“存在 LangGraph”不等于当前产品“由 LangGraph 编排”。必须让新版 Workspace 成为新的 LangGraph 主链，旧 workflow 最终降为兼容层或删除，不能长期维护两套互相分离的 Agent 架构。

### 3.2 Reviewer、Replanner 和 Handoff 主要是名义存在

- WorkspaceAgent 会生成 Reviewer 的 RoleContext；
- 会记录 Validator → Reviewer 的 AgentHandoff；
- 但没有真正调用 Reviewer；
- `_handoff()` 创建记录时直接写入 `completed` 或 `partial`；
- `run_bounded_replanning()` 等能力主要存在于独立模块和测试，没有接入新版运行时。

必须改为真实执行：Handoff 发出后状态为 `pending/running`，接收角色真正执行，产出结构化结果，再写 `completed/failed/partial`。不得把“准备了上下文”伪装成“Reviewer 已完成”。

### 3.3 旅行数据工具没有进入新版规划链

现有 ORS、Open-Meteo、SearchAPI Flights 主要在旧图或孤立 Provider 中。新版层级规划器没有真正使用：

- 公共交通与换乘；
- 航班对旅行窗口的约束；
- 营业时间和闭馆日；
- 天气对日程和步行成本的影响；
- ORS 实际步行矩阵对 AreaCluster 的修正。

这些信息必须进入 Planner 和 Deterministic Validator，不只是显示在结果页。

### 3.4 “批量排除”被错误地当成“清空行程”

当前行为：

```text
用户全选已排程地点并排除
→ PlaceOperation(action="exclude")
→ 加入 excluded_place_ids
→ can_plan=True
→ 自动 _execute_plan()
→ 规划器从剩余候选池补入另一批地点
```

这不是随机错误，而是错误的产品语义。排除候选、清空当前排程、删除版本、删除工作区必须是不同操作。

### 3.5 Anitabi 点位不完整

当前 `/api.anitabi.cn/bangumi/{id}/points/detail` 可能只返回 `/lite.pointsLength` 的一部分。例如 `/lite` 为 414，详情只有 74。不能把这部分数据标记为完整。

本次已决定：**直接采用 MiriaGo 的静态地图数据读取方案**，具体要求见第 7 节。

---

## 4. 新版目标 Agent 架构

### 4.1 LangGraph 主图

为新版 Workspace 建立唯一主图：

```text
START
  ↓
load_workspace_context
  ↓
requirement_agent
  ↓
confirm_requirements ──需要用户确认──→ INTERRUPT
  ↓
subject_agent
  ↓
confirm_subjects ──需要用户确认──→ INTERRUPT
  ↓
anitabi_point_agent
  ↓
place_curator
  ↓
travel_area_builder
  ↓
access_agent
  ↓
confirm_access_and_base ──需要用户确认──→ INTERRUPT
  ↓
place_facts_agent + weather_agent
  ↓
knowledge_retriever
  ↓
itinerary_planner
  ↓
deterministic_validator
  ↓
reviewer_agent
  ├── PASS → present_workspace
  └── REVISE → bounded_replanner → deterministic_validator
  ↓
await_user_patch / END
```

用户后续自然语言修改走同一个图：

```text
user_message
→ intent/patch agent
→ PlanPatch preview
→ 必要时 INTERRUPT 等待确认
→ impact-directed subgraph
→ validator
→ reviewer
→ present diff
```

不要每次修改都无条件重跑全部节点。根据 PatchImpact 只重跑被失效的节点。

### 4.2 Agent 角色与职责

#### Requirement Agent

- 从开放文本提取结构化 TripRequest；
- 识别作品、出发地、目的地、日期、住宿、预算、步行、无障碍和优先场景；
- 标出缺失、歧义和默认值；
- 不允许前端静默硬编码东京或 medium walking；
- 只对真正缺失且会改变计划的字段发起澄清。

#### Subject Agent

- 调用 Bangumi；
- 为每个作品意图返回候选；
- 支持多季度、多条目；
- 必须由用户确认；
- 不允许根据模糊名称静默选择。

#### Anitabi Point Agent

- 按每个确认的 Bangumi ID 获取完整静态点位；
- 返回数量、完整性、来源和版本；
- 不编造、不复制点位补数量。

#### Place Curator

- 将原始场景记录整理为 SceneEvidence；
- 只在有充分身份依据时合并为 CanonicalPlace；
- 保留每部作品、集数、参考图和来源；
- 对模糊合并生成待用户处理的候选，而不是自动合并。

#### Travel Area Builder

- 根据空间邻近、ORS 步行时间、车站/线路连通性形成 TravelAreaCluster；
- 不得把前端 marker cluster 当成旅行区域；
- 允许一天组合多个相邻或交通方便的区域。

#### Access Agent

- 查询航班和跨城市交通；
- 比较时间、价格、换乘、机场接驳和旅行缓冲；
- 产生候选，不自动预订；
- 选择结果必须由用户确认。

#### Place Facts Agent

- 使用 SearchAPI Google Maps/Place 获取营业时间、地址、地点状态等；
- 匹配必须保留 place ID、查询时间和置信度；
- 不能把不确定的同名地点当成硬事实。

#### Weather Agent

- 使用 Open-Meteo；
- 将降雨、极端温度等转换为结构化风险；
- 超出可靠预报窗口时标记 unknown，并要求临行前复核。

#### Itinerary Planner

- 在真实日期、时间窗、交通边、营业时间、天气、航班和用户约束下生成多个可比较方案；
- 为未入选地点生成结构化 omission reason；
- 不再使用“一天一个 AreaCluster”的硬限制。

#### Deterministic Validator

必须用普通程序验证：

- 所有地点属于候选池；
- 排除点不在行程；
- 必去点覆盖；
- 时间单调且不重叠；
- 营业时间/闭馆日；
- 交通衔接和换乘缓冲；
- 航班、机场、入住和返程缓冲；
- 每日步行上限；
- 跨城市不可达；
- 天气硬风险；
- 数据 TTL 和来源；
- Route A/候选池完整性。

#### Reviewer Agent

- 真正调用 LLM；
- 只接收经过裁剪的 ReviewerContext；
- 输出严格 Schema：`pass/revise/stop`、问题、证据引用、目标节点、建议 Patch；
- 不能覆盖 Validator 的硬错误；
- 不能编造实时事实。

#### Replanner

- 只针对具体违规重规划；
- 有最大尝试次数；
- 每次保存父版本、触发原因和 Diff；
- 无法修复时返回 partial 和明确解释，不能无限循环。

---

## 5. 上下文工程与记忆设计

### 5.1 WorkspaceState 是唯一运行事实源

LangGraph State 不保存完整网页、长对话或所有原始工具响应，只保存稳定引用和当前结构化状态：

```text
WorkspaceIdentity
TripRequirements
SubjectIntents / ConfirmedSubjects
ProviderSnapshots refs
SceneEvidence refs
CanonicalPlaces
TravelAreaClusters
AccessCandidates / selected access
BaseCandidates / selected base
LiveConstraints
KnowledgeRule refs
ItineraryVersions
ValidationReports
ReviewerAssessments
Patches / Diffs
PendingConfirmation
Warnings
StateVersion
```

### 5.2 分层记忆

必须区分：

1. **当前工作区状态**：本次旅行的权威结构化数据；
2. **对话事件**：用户和 Agent 的消息、操作和确认；
3. **用户偏好**：长期可复用但可编辑/删除，例如少走路；
4. **外部实时事实**：天气、航班、交通、营业时间，必须有 TTL；
5. **RAG 知识**：攻略、规则、官方说明、用户文档；
6. **执行审计**：AgentRun、Handoff、ToolCall、Validation，不进入普通聊天上下文。

不要读取或依赖 ChatGPT 账号中的其他记忆。项目运行时只使用项目数据库中当前 owner/workspace 允许的数据。

### 5.3 RoleContext 最小化

每个 Agent 只接收完成任务所需的字段：

- Requirement：最新用户消息 + 当前 requirements + 缺失字段；
- Subject：作品意图 + Bangumi 候选；
- Curator：相关 SceneEvidence，不接收完整对话；
- Planner：约束、地点、区域、交通矩阵和事实引用；
- Validator：计划和硬约束；
- Reviewer：计划摘要、Validator 报告、用户优先级和来源状态；
- Replanner：目标违规、受影响日期和可修改候选。

工具响应先规范化、去掉无关字段，再进入上下文。LLM 不直接接收完整原始 Provider JSON。

### 5.4 对话压缩

- 保存完整规范化 ConversationEvent；
- Prompt 只注入最近必要消息、当前状态摘要和未解决决定；
- 超过预算后生成可追溯摘要；
- 关键用户确认、拒绝和硬约束永不因摘要丢失；
- 不以“最近 50 条”作为唯一记忆策略。

---

## 6. Handoff 与运行记录

### 6.1 Handoff 状态机

```text
pending → running → completed
                  ↘ partial
                  ↘ failed
                  ↘ cancelled
```

Handoff 至少包含：

- `handoff_id/run_id`；
- sender/receiver；
- task type 和 goal；
- 输入实体引用和版本；
- 期望输出 Schema；
- 状态；
- 实际结果引用；
- warning/error；
- created/started/completed timestamps；
- retry count；
- correlation/parent handoff ID。

只有接收节点真实完成并成功验证输出后，才能标记 completed。

### 6.2 可观测性边界

本轮不把 OpenTelemetry 作为项目主任务或验收阻塞项。保留项目内部结构化 RunLog、ToolCall 和 Handoff 即可。不要为了 Trace 平台牺牲 Agent、规划或产品功能。

---

## 7. Anitabi 完整点位：直接采用 MiriaGo 方案

参考：

- `BilyHurington/MiriaGo/lib/data/anitabi_client.dart`
- `BilyHurington/MiriaGo/lib/data/anitabi_static_data_reader.dart`
- `BilyHurington/MiriaGo/test/anitabi_client_test.dart`

### 7.1 静态索引

读取：

```text
https://www.anitabi.cn/d/g.json
```

备用：

```text
https://anitabi.cn/d/g.json
```

解析：

```text
[works, page_size, version]
```

作品压缩记录中读取 Bangumi ID、标题、城市、中心点、缩放和压缩点位数组。压缩点位数组按四项一组建立：

```text
point_id → latitude, longitude
```

### 7.2 详情页

目标作品在索引中的位置为 `work_index`：

```python
guessed_page = work_index // page_size
```

读取：

```text
https://www.anitabi.cn/d/g{guessed_page}.json?v={version}
```

若推算页没有目标作品，遍历其他页查找，处理索引和分页短暂不同步。

将分页中的点位详情与 `g.json` 的 point ID/坐标合并，生成完整 PointRecord。

### 7.3 Provider 策略

```text
Anitabi static g.json/gN.json
→ 失败时退回 documented detail endpoint
→ fallback 结果必须 is_complete=false
```

静态成功：

```json
{
  "provider": "anitabi_static",
  "is_complete": true,
  "expected_count": 414,
  "loaded_count": 414,
  "data_version": "...",
  "warnings": []
}
```

不得猜测 `/points/detail` 分页，不得复制或编造点位满足数量。

### 7.4 唯一标识与多作品

原始点位 ID：

```text
anitabi:{bangumi_id}:{point_id}
```

不同作品/季度即使坐标相同，也先保留不同 SceneEvidence。CanonicalPlace Resolver 后续再判断现实地点身份。

### 7.5 缓存与防护

- `g.json` 按 version 缓存；
- `gN.json` 按 page + version 缓存；
- 版本变化后旧分页失效；
- 提供 clear/refresh；
- 只允许 `g.json`、`g数字.json`；
- 域名白名单、超时、有限重试、响应体限制；
- 独立 `AnitabiStaticAdapter`，不要把压缩格式解析写进 Planner；
- 静态资源结构不稳定，必须保存 source/version，并允许以后替换 Adapter。

建议配置：

```env
ANITABI_STATIC_BASE_URL=https://www.anitabi.cn/d
ANITABI_STATIC_FALLBACK_URL=https://anitabi.cn/d
ANITABI_STATIC_CACHE_TTL_SECONDS=21600
```

---

## 8. 三种聚类必须分开

### 8.1 MapMarkerCluster

- 只用于地图缩放时的视觉聚合；
- 随 zoom 变化；
- 不持久化为旅行区域；
- 不参与 Planner。

### 8.2 CanonicalPlace Resolution

目标：多个作品场景点是否属于同一现实地点。

修复当前高风险规则：不得因为 `source_label/origin` 相同且距离在 100 米内就直接合并。`origin` 是来源，不是地点身份。

建议判定：

- 相同 Anitabi point ID：相同原始记录；
- 相同可靠外部 place ID：可合并；
- 极近距离 + 高名称/地址/车站出口一致性：可合并；
- 名称或出口冲突：必须拆分；
- 其余近邻：标记 ambiguous，等待用户或 Curator 决定。

不要全量 O(n²) 比较。先使用空间索引/H3/geohash/PostGIS `ST_DWithin` 生成邻近候选，再做身份比较。

### 8.3 TravelAreaCluster

目标：决定哪些 CanonicalPlace 适合在一个步行/交通片区游览。

流程：

1. 坐标粗分区；
2. ORS 步行矩阵校正；
3. SearchAPI 公共交通连接补充；
4. 车站、线路、河流/山路等现实阻隔修正；
5. 得到稳定、有算法版本的 TravelAreaCluster。

修复当前 DBSCAN 边界点处理。噪声点以后成为核心簇边界时必须能够加入该簇，结果不应依赖 UUID 遍历顺序。

---

## 9. 实时旅行 Provider 与 API

用户已准备：

```env
LLM_API_KEY=
BANGUMI_API_KEY=
ORS_API_KEY=
SEARCHAPI_API_KEY=
```

另保留符合 Bangumi 规范的 User-Agent；它不是 API Key：

```env
BANGUMI_USER_AGENT=<github-user>/anime-pilgrimage-agent/0.1.0
```

### 9.1 SearchAPI 一个 Key 覆盖

扩展现有 SearchAPI Provider：

#### 航班

```text
engine=google_flights
engine=google_flights_calendar
```

#### 公共交通与换乘

```text
engine=google_maps_directions
travel_mode=transit
time=depart_at:<timestamp> | arrive_by:<timestamp> | last_available
route=best | fewer_transfers | less_walking | wheelchair_accessible
prefer=bus/subway/train/tram_and_light_rail
```

规范化返回：

- 起终点；
- 出发/到达时间和时区；
- 总耗时；
- 每段步行/线路/车辆；
- 换乘次数和等待；
- 站点；
- provider；
- 查询时间和 TTL；
- 原始来源链接。

Transit 不支持带 waypoint 的一次性请求，因此区域间和关键地点间按边查询，Planner 在内部组合。

#### 营业时间和地点事实

```text
engine=google_maps
engine=google_maps_place
```

规范化：place ID、名称、地址、坐标、星期营业窗口、临时关闭状态、查询时间、匹配置信度。

### 9.2 ORS

用于：

- 地理编码；
- 步行/骑行/驾车 directions；
- 小规模路线矩阵；
- AreaCluster 步行时间校正。

ORS 不承担公共交通时刻和换乘。

### 9.3 Open-Meteo

继续使用现有 Provider，无额外 Key。返回逐日风险，并明确预报可用窗口。长期旅行先标 unknown/气候参考，临近出发时重新查询。

### 9.4 Provider 通用规则

- Provider response 必须规范化为 ToolOutcome；
- 每条实时事实有 source、retrieved_at、expires_at；
- 缓存避免重复扣配额；
- 测试默认 fixture，live smoke 显式开启；
- SearchAPI 配额不足时不能编造；
- 所有票价、时刻、天气和营业时间在出发前提示复核。

---

## 10. 新规划器

### 10.1 不再一天一个 Area

移除：

```python
selected_areas = reachable_areas[:len(windows)]
```

一天可以组合多个区域，只要真实交通、营业时间和用户约束允许。

### 10.2 时间依赖图

建立分层候选图：

```text
Access edges：航班/长途交通
Inter-area edges：公共交通/驾车
Intra-area edges：步行/短途交通
Visit nodes：地点访问及营业时间窗
Base nodes：酒店/车站/机场
```

边至少包含 mode、duration、departure/arrival、walking distance、transfer count、source 和 TTL。

### 10.3 约束

硬约束：

- 日期和时区；
- 航班/列车窗口；
- 营业时间和闭馆；
- 必去/排除；
- 每日时间；
- 最大步行；
- 城市可达性；
- 交通衔接缓冲；
- 用户锁定的日期和顺序。

软目标：

- 作品和场景优先级；
- 覆盖数量；
- 少换乘；
- 少步行；
- 少费用；
- 少跨区往返；
- 天气适配；
- 计划稳定性（局部修改尽量不扰动其他天）。

可以使用启发式 + OR-Tools CP-SAT/VRP，但 LLM 不负责算时间、路径或约束满足。LLM 负责解释偏好、生成候选 Patch 和说明取舍。

### 10.4 多个方案

至少生成真正不同的可比较方案：

- balanced；
- low_walking；
- primary_subject_first；
- fewer_transfers；
- weather_resilient；
- budget_focused（数据足够时）。

每个方案必须独立验证，并展示差异，不只是同一算法换一个分数权重名称。

---

## 11. PlanPatch、删除、撤销与版本

### 11.1 新增明确操作

```text
clear_schedule          清空整个当前排程，保留候选池
clear_day               清空指定日期，保留候选池
exclude_place           从候选池排除并重规划
include_place           恢复候选资格
remove_visit            从当前行程移除，但不自动永久排除
delete_itinerary_version
restore_itinerary_version
archive_workspace
delete_workspace
```

`clear_schedule` 后不得自动从剩余候选补位。状态应变为 `ready_to_plan`，等待用户选择地点或要求重新生成。

### 11.2 工作区彻底删除

增加：

```http
DELETE /api/workspaces/{trip_id}
```

必须验证 owner/thread namespace，并事务性清理：

- Trip/Workspace state；
- Conversation events；
- Itinerary versions；
- Patches/Diffs；
- RoleContexts/Handoffs/Runs；
- workspace projection tables；
- trip-scoped RAG associations/derived rules；
- 对应 graph checkpoints。

知识文档如果属于用户公共命名空间，不得因删除一个 trip 而误删；只删除 trip 关联。

前端“关闭”与“永久删除”分开。关闭只退出当前页面；永久删除必须二次确认。

### 11.3 撤销与恢复

- 每次 applied patch 产生 inverse metadata 或可恢复快照；
- 支持恢复历史 ItineraryVersion；
- 乐观并发继续使用 expected_base_version；
- 恢复本身也产生新版本，不能破坏审计历史。

---

## 12. RAG 设计

### 12.1 不进入 RAG

- Bangumi ID；
- Anitabi 原始点位/坐标；
- 航班和公共交通实时结果；
- 天气；
- 当前营业时间；
- 时间、距离和费用计算。

这些属于结构化 ProviderSnapshot。

### 12.2 适合 RAG

- 官方场所规则；
- 拍摄礼仪和安全；
- 用户上传的攻略、Markdown、TXT、PDF；
- 车站换乘经验；
- 作品背景和场景解释；
- 长期稳定的访问注意事项。

### 12.3 检索闭环

```text
Planner/用户问题
→ workspace + work + area + place metadata filter
→ BM25 + vector
→ fusion/rerank
→ Top-K evidence
→ 派生 proposed rule
→ 用户或可信策略接受
→ active constraint
→ Planner/Validator
```

前端补充文档上传、检索证据和规则确认界面。每条规则必须能看到证据和来源，能够停用/删除。

Codex 可以使用公开、可再分发的小型测试资料构造 RAG fixture，但不得把测试文本冒充真实旅行事实。

---

## 13. 前端整改

前端服务 Agent，不要重新变成大表单，也不要只剩受限按钮。

### 13.1 创建工作区

移除硬编码：

```typescript
origin: "东京"
destination: "东京"
walking_preference: "medium"
```

自然语言先进入 Requirement Agent，再显示可编辑条件卡：

- 作品；
- 出发地/目的地；
- 日期；
- 住宿基地；
- 预算；
- 步行偏好和上限；
- 无障碍；
- 必去场景；
- 需要确认/系统默认字段。

### 13.2 工作区布局

推荐保留混合主动式界面：

- 左侧/底部：连续对话和待确认事项；
- 中央：地图，可切换全部点位、候选、排程、排除；
- 右侧：条件卡、方案、版本、证据和修改影响；
- 移动端使用同一信息结构的分页/抽屉。

### 13.3 自然语言修改

支持意图示例：

- “清空当前行程，但保留这些候选”；
- “第二天不要安排任何地点”；
- “少走一点，接受多坐一次地铁”；
- “把轻音少女相关地点优先放到第一天”；
- “撤销刚才修改”；
- “恢复 v3”；
- “删除整个旅行”；
- “雨天把室内地点放前面”；
- “不要自动补其他地点”。

所有修改先显示影响范围；高影响操作确认后执行。

### 13.4 身份边界

开发版可继续使用本地用户，但不要把 `local-web-user` 和固定 thread 永久硬编码在组件内部。通过开发 session provider 注入，并为未来认证保留接口。生产认证不是本轮阻塞项。

---

## 14. API 与模型建议

新增或完善：

```http
POST   /api/workspaces
GET    /api/workspaces
GET    /api/workspaces/{trip_id}
DELETE /api/workspaces/{trip_id}

POST   /api/workspaces/{trip_id}/messages
POST   /api/workspaces/{trip_id}/resume

POST   /api/workspaces/{trip_id}/patches/preview
POST   /api/workspaces/{trip_id}/patches/{patch_id}/apply
POST   /api/workspaces/{trip_id}/patches/{patch_id}/cancel

POST   /api/workspaces/{trip_id}/schedule/clear
POST   /api/workspaces/{trip_id}/days/{day}/clear
POST   /api/workspaces/{trip_id}/itineraries/{version}/restore
DELETE /api/workspaces/{trip_id}/itineraries/{version}

GET    /api/workspaces/{trip_id}/runs
GET    /api/workspaces/{trip_id}/handoffs
GET    /api/workspaces/{trip_id}/evidence
GET    /api/workspaces/{trip_id}/provider-snapshots
```

外部 Provider 通过 MCP/tool boundary 暴露：

```text
search_anime_subjects
fetch_anitabi_static_points
geocode_place
get_walking_matrix
get_route_directions
search_transit_options
search_flight_options
search_flexible_flight_dates
get_place_facts
get_weather_forecast
search_knowledge
```

MCP 用于 Agent 调用工具；内部 Agent 之间的协作由 LangGraph State、Command/Interrupt 和 typed Handoff 完成，不需要为了展示 A2A 而引入外部 A2A 协议。

---

## 15. 实施顺序（不要求刻意包装为六阶段）

Codex 应按依赖关系持续完成，并在每项后运行相关验收：

1. **建立回归基线**：锁定 `c544c3b`，运行现有 Python、Web、API、Compose 测试，记录真实失败；
2. **Anitabi 完整点位**：实现 MiriaGo 静态 Adapter、完整性和缓存；
3. **修复行为语义**：clear/remove/exclude/delete/restore，解决“清空后自动补位”；
4. **重建新版 LangGraph 主链**：把 WorkspaceState、interrupt、checkpoint、真实 Handoff 接入；
5. **接入真实 Agent**：Requirement、Reviewer、Replanner，避免伪 completed；
6. **旅行 Provider 接入**：SearchAPI transit/place、现有 flights、ORS、Open-Meteo；
7. **修正地点解析与聚类**：三层聚类、空间索引、ORS/Transit 校正；
8. **升级时间依赖规划器和 Validator**；
9. **补齐上下文、记忆、RAG 闭环**；
10. **重构前端为真正 mixed-initiative workspace**；
11. **最终端到端、移动端、Docker、Conda 和失败降级验收**。

如某项依赖外部实时配额，使用 fixture 完成 CI，并将 live smoke 标记为明确的独立验收，不能伪造 PASS。

---

## 16. 必须覆盖的关键验收场景

### Agent

1. 新工作区请求实际进入 LangGraph，而不是直接调用单体 WorkspaceAgent；
2. Reviewer 被真实调用，并可根据 Validator 报告返回 revise；
3. Replanner 只改受影响日期，未受影响日期保持稳定；
4. Handoff 状态和时间反映真实执行；
5. 中断确认后刷新页面可恢复；
6. LLM 不可用时返回可解释降级，不伪装为已审查。

### Anitabi

1. detail 为 1、静态为 3 时最终加载 3；
2. 正确解析 g.json/gN.json/version；
3. 推算页错误时扫描其他页；
4. 版本变化使旧缓存失效；
5. 静态失败 fallback detail 时 `is_complete=false`；
6. 多作品同坐标仍保留多条 SceneEvidence；
7. 前端显示 loaded/expected/source/version。

### 删除与修改

1. `clear_schedule` 后行程为空且不自动补位；
2. `exclude_place` 后才允许从其他候选重规划；
3. 清空单日不影响其他日；
4. 可撤销并恢复历史版本；
5. 删除工作区后关联状态、对话、版本、运行记录和 checkpoint 不可再读取；
6. 用户公共知识文档不会被误删。

### 旅行约束

1. 同一天可安排多个交通可达 Area；
2. 关闭地点不会被安排；
3. 公共交通换乘和步行段进入时间轴；
4. 少换乘/少步行偏好产生真实差异；
5. 航班抵达过晚时当天不安排巡礼；
6. 返程前保留配置化缓冲；
7. 雨天方案能调整室内/室外顺序；
8. Provider 超时或配额不足时明确 partial/unknown。

### 前端

1. 输入“京都出发、住新宿、尽量少走路”不再被覆盖为东京/medium；
2. 多作品、多季度确认可用；
3. 可以清空、撤销、恢复和永久删除；
4. 方案差异、来源、更新时间、警告可见；
5. 桌面和移动端无水平溢出；
6. 刷新后恢复当前工作区、待确认操作和对话。

---

## 17. 完成定义

只有同时满足以下条件，才能声称项目从“确定性工作区原型”升级为“Agent 项目”：

- 新版多作品工作区由 LangGraph 编排；
- Requirement/Reviewer/Replanner 至少三类 LLM Agent 真实运行；
- Agent 间使用结构化 Context 和真实 Handoff；
- Validator 的硬约束真实执行；
- Anitabi 点位采用 MiriaGo 静态方案并披露完整性；
- SearchAPI 公共交通、航班、营业时间，ORS 和 Open-Meteo 进入规划链；
- 支持清空、撤销、恢复和彻底删除；
- 多作品、多区域、多日计划不再受“一天一个区域”限制；
- RAG 与结构化实时事实边界正确；
- 前端支持开放对话 + 可编辑条件卡 + 地图/时间轴；
- 测试覆盖正常流程、失败降级和数据删除；
- 文档中的能力声明与真实运行路径一致。

如果某项尚未完成，必须写入 `KNOWN_LIMITATIONS.md`，不得通过生成 Handoff、测试 fixture 或静态截图把未运行的能力描述为已完成。

---

## 18. 给 Codex 的执行要求

1. 先阅读 `AGENTS.md`、README、当前 API/Agent/Planning/Provider/Frontend 代码和已有测试；
2. 保护用户已有改动，不重置工作树；
3. 每次修改前明确影响范围，优先复用现有模型；
4. 不为了保持旧接口而继续复制两套核心架构；兼容端点应薄封装新主链；
5. 所有外部事实有来源、时间和 TTL；
6. 不提交 `.env`、API Key、个人地址和私密旅行数据；
7. 不执行预订、付款或外部消息；
8. 每个工作项完成后运行相关单元、API、Web、E2E 和 Compose 验收；
9. 最终运行仓库完整验证，并提供通过/失败/未验证三类真实报告；
10. 提交结果时汇总：实现内容、架构变化、迁移、API 变更、测试证据、剩余限制。

