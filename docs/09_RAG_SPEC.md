# RAG 模块详细规格

RAG 是独立产品模块，与 Conda 开发环境和 Docker 基础设施无关。它只处理攻略、礼仪、访问规则、换乘经验和场景背景等非结构化知识。

## 1. 数据边界

进入 RAG：

- 官方公告、场所规定、地方旅游指南；
- 车站换乘、区域访问和拍摄礼仪；
- 用户合法上传的旅行笔记；
- 作品背景、场景解读和人工整理攻略。

不进入 RAG：

- Bangumi ID、标题和别名；
- 巡礼点坐标及 Route A 成员；
- 航班、路线矩阵、天气和 Google Maps URL；
- 已结构化的营业时间、约束和用户确认。

结构化或实时事实只能通过 Provider/数据库获取，RAG 不能覆盖。

## 2. 固定技术选择

| 能力 | 选择 |
|---|---|
| 文本提取 | Markdown/TXT；PDF 使用 pypdf，MVP 不做 OCR |
| Dense embedding | 本地 `intfloat/multilingual-e5-small`，384 维 |
| Dense 存储 | PostgreSQL + pgvector，cosine distance |
| Lexical | bm25s，应用层持久化索引 |
| 中日文词元 | Unicode NFKC + 拉丁词元 + CJK 字符 bigram + 作品别名 |
| 融合 | Reciprocal Rank Fusion，k=60 |

E5 的查询和文本分别加 `query: `、`passage: ` 前缀并归一化。MVP 使用 pgvector exact search；只有 chunks 超过约 10,000 且基准证明必要时再添加 HNSW。

技术依据：

- https://huggingface.co/intfloat/multilingual-e5-small
- https://github.com/pgvector/pgvector
- https://github.com/xhluca/bm25s

## 3. Codex 自主准备测试资料

阶段 5 允许 Codex 联网搜索少量公开资料，建立 RAG 测试集。优先顺序：

1. 官方场所规定和公告；
2. 地方政府/旅游协会；
3. 铁路、地铁等交通运营方；
4. 动画或联动活动官方页面；
5. 许可证明确的开放资料。

要求：

- 只研究与 2～3 个验收场景相关的小语料；
- 不批量抓站，不绕过登录、验证码、robots、限流或付费墙；
- 不复制整页文章或完整图片；
- 测试 Fixture 使用自行概括的短摘要、必要的短摘录或明确标注的合成文本；
- 每份资料保存 URL、标题、发布/访问日期、来源类型、权威等级、语言和内容 hash；
- 来源页面不允许仓库再分发时，只保存元数据和测试用合成等价文本；
- 自动测试不得每次联网重新搜索，必须使用固定 Fixture；
- 实时联网检索只作为独立 smoke，并在报告中与 Fixture 结果分开；
- 找不到合规资料时使用 `source_type=synthetic_test`，不得冒充真实规定。

建议目录：

```text
fixtures/rag/
  manifest.yaml
  documents/
  golden_queries.jsonl
  expected_relevance.json
```

`manifest.yaml` 记录来源、许可/使用说明、摘要生成方式、抓取日期和 SHA-256。

## 4. 数据模型

`knowledge_documents`：

```text
id, namespace, owner_user_id, trip_id
title, source_url, source_type, authority_level
author, language, published_at, accessed_at
valid_from, valid_until
subject_ids, location_tags, point_ids
content_sha256, status, extraction_warning
created_at, updated_at
```

`knowledge_chunks`：

```text
id, document_id, ordinal
section_path, page_start, page_end
text, token_count, lexical_tokens
embedding VECTOR(384), metadata, created_at
```

`namespace + content_sha256` 唯一，重复上传不重复生成 embedding。

## 5. 权限命名空间

- `curated`：项目维护的公共资料；
- `user:{user_id}`：某用户明确上传的私人资料；
- `trip:{trip_id}`：只属于当前旅行的临时资料。

检索只能访问 `curated + 当前 user + 当前 trip`。SQL 必须使用服务端验证后的 namespace filter，Agent 无权指定任意 user ID。删除文档后必须从 dense、BM25 和引用结果同步消失。

## 6. 文档摄取

支持 `.md`、`.txt`、文本型 `.pdf`；单文件最多 10 MiB，PDF 最多 200 页。禁止执行宏、脚本、外链资源或嵌入附件。扫描 PDF 文本不足时返回 `needs_ocr`，不生成空 chunks。

Pipeline：

```text
权限/文件校验
→ SHA-256 去重
→ 安全文本提取
→ Unicode NFKC/空白规范化
→ 保留标题、章节、页码
→ 语义分块
→ lexical tokenization
→ passage embedding
→ 事务写入 PostgreSQL
→ 重建对应 namespace 的 BM25 索引
```

分块规则：目标 450 tokens，范围 300～600，overlap 80；优先章节和段落边界；小于 80 tokens 的尾块合并；每块保留来源锚点。Token 数必须使用 embedding tokenizer 计算。

## 7. 检索

`KnowledgeQuery` 至少包含 question、服务端注入的 user/trip、subject/aliases、location tags、point IDs、知识类型、旅行日期和 top_k。

流程：

1. 权限 namespace filter；
2. subject/location/point/source/有效期 metadata pre-filter；
3. 原问题加已确认作品和地点别名；
4. E5 dense top 30；
5. BM25 top 30；
6. `RRF(k=60)` 融合；
7. authority/freshness 轻量重排；
8. 每文档最多 2 chunks，最终 top 6。

```text
rrf_score = sum(1 / (60 + rank_i))
```

权威等级只能用于同等相关性排序，不能让不相关官方文档压过相关普通资料。已过 `valid_until` 的硬规则默认排除；未知时效必须标记。

## 8. Evidence 与引用

每条 `RetrievedEvidence` 包含：chunk/document ID、excerpt、title、URL、source type、authority、日期、section/page、dense/BM25 rank、RRF score、freshness。

给 LLM 时包裹为不可信数据：

```text
<untrusted_evidence id="K-...">
...
</untrusted_evidence>
```

可核验声明必须引用本次检索的 Evidence ID。UI 渲染标题、章节/页码、来源链接和访问日期。无来源、过期或冲突时标为未知/需确认。

## 9. 权威、时效和冲突

```text
5 官方公告/场所规定
4 场所官网/政府/旅游协会/交通运营方
3 结构化点位说明
2 人工筛选社区攻略
1 普通用户笔记
0 未知或 synthetic_test
```

拍照、进入限制、营业时间等硬事实优先要求 authority >= 4。低权威证据只能作为社区经验。冲突时生成 `EvidenceConflict`，同时显示双方来源、日期和等级，不由 LLM 静默选择。

## 10. Prompt Injection 防护

- 文档、网页摘要和 MCP 数据全部是不可信数据；
- 文本中的指令只作为内容，不能改变系统规则；
- RAG 生成节点没有 MCP、shell、外部写入工具；
- Validator 检查引用属于本次 Evidence；
- HTML/script 清理不是唯一防线；
- 恶意文档测试要求工具调用为 0、密钥泄漏为 0。

## 11. API

```text
POST   /api/knowledge/documents
GET    /api/knowledge/documents
GET    /api/knowledge/documents/{id}
DELETE /api/knowledge/documents/{id}
POST   /api/knowledge/search
POST   /api/knowledge/evaluate   # 仅开发/测试
```

UI 不暴露 embedding、其他用户 namespace 或不必要的内部分数。

## 12. 降级

- embedding 首次下载失败：报告阻塞，Fixture 的非 embedding 测试继续；
- BM25 索引缺失：重建，不静默只用 dense；
- PDF 无文本：返回 `needs_ocr`；
- pgvector 不可用：健康检查失败，不用随机/LIKE 冒充 hybrid；
- 检索为空：返回 `insufficient_evidence`；
- 资料过期：不能作为硬规则。

## 13. Golden Set 与门禁

至少 24 个查询：6 个官方规则、6 个换乘/区域经验、6 个中日文作品/场景问题、6 个无答案/过期/权限/注入案例。

最低门禁：

```text
Recall@6 >= 0.80
MRR@10 >= 0.70
Citation Precision >= 0.90
跨 namespace 泄漏 = 0
恶意文档触发工具 = 0
删除后残留结果 = 0
无证据问题虚构率 <= 0.10
```

报告模型 revision、语料 hash、参数和失败查询。不得只报告平均值而隐藏失败案例。
