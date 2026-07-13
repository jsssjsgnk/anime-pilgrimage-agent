# 验收场景与指标

测试时钟固定后，所有旅行日期以 `today + N days` 生成，避免样例过期。真实 API 只用于少量 smoke；完整回归使用脱敏 Fixture。

## S1：日本国内抵达与少步行巡礼

输入语义：京都出发，东京三天，《孤独摇滚！》，预算中等，少走路，特定集数优先。

验证：

- Bangumi 候选确认；
- 铁路人工候选和航班搜索可同时表达，但不得强迫乘飞机；
- Route A 完整，Route B 是子集；
- 第二天步行限制；
- 抵达/返程缓冲；
- 用户修改“第二天再少走 30%”只重算相关部分。

## S2：国际航班与时区

使用 Fixture 构造跨时区出发地到东京的往返航班，旅行日期为 `today + 60 days`。

验证：

- 当地出发/到达时间和时区；
- 过夜航班、转机、总时长和价格币种；
- 抵达太晚时不安排当天巡礼；
- 返程缓冲不足触发 violation；
- SearchAPI 不可用时不保留旧价格冒充实时价格。

## S3：Provider 部分失败和数据不足

注入 ORS 429、天气超出预报范围、点位 Provider 部分分页失败、LLM 非法 JSON。

验证：

- ORS 降级为 Haversine 并标注；
- 天气显示未知而非编造；
- Route A 标记不完整并阻止“100% 完整”声明；
- LLM 有限重试后返回结构化错误；
- 页面仍可显示已有数据并给出恢复动作。

## 指标

### 作品与点位

- Bangumi ID Accuracy、Hit@K、Recall@K；
- Point Recall/Precision、Invalid Coordinate Rate、Source Completeness；
- Route B Must-Visit Coverage、点位幻觉率。

### 计划

- 时间约束、抵离缓冲、步行限制满足率；
- 未选点理由正确率；
- Reviewer 收敛轮数；
- 局部重规划稳定性。

### RAG

- Recall@K、MRR、Citation Accuracy、Faithfulness；
- 来源冲突识别；
- 提示注入阻断率。

RAG 测试资料允许 Codex 在阶段 5 从公开官方来源自行研究并整理；固定语料结构、24 类查询、版权边界和阈值以 `docs/09_RAG_SPEC.md` 为准。

### 系统

- 工具成功/失败恢复率、Schema 错误率；
- API 调用数、cache hit、延迟、token 数量估算；
- E2E 成功率和无密钥扫描。

领域 Validator 分支覆盖率目标至少 90%，后端整体至少 80%。覆盖率目标不能通过排除关键文件实现。
