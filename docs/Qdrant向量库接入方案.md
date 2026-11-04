# Qdrant 向量库接入方案（v1.0，2026-11-04）

## 1. 背景与目标

现状：`apps/ai/vectorstore.py` 的 `search_chunks()` 把某课程**全部**片段读进内存逐个算余弦
（`KnowledgeChunk.embedding` 是 MySQL JSONField，1024 维 float 列表）。片段数量随课件/讲稿
页数线性增长，检索延迟与 gunicorn worker 内存一起涨，且每次请求都要把整门课的向量从
MySQL 反序列化一遍。

目标：把向量检索外置到 Qdrant（HNSW 索引 + payload 过滤），**可开关、可回滚、零重算**。

围绕四条硬约束设计：

| 约束 | 落地方式 |
|---|---|
| 不改 MySQL 表结构、不删 `embedding` 列 | `embedding` 仍是唯一真相 + 回滚依赖，Qdrant 只是副本索引 |
| 存量向量直接搬运，禁止重调 embedding API | `backfill_qdrant` 只读 `embedding` 原样 upsert |
| 过滤语义等价（章节池 / 学生可见性 / is_active） | 过滤条件收敛成 `ChunkFilter`，两后端各自翻译 + 命中后 MySQL 复验 |
| 必须可降级 | Qdrant 异常/超时/集合未回填 → 自动回落 json 并打标 |

## 2. 结构与调用链

```
services._search_relevant_chunks()          ← 召回→重排→阈值，调用方签名不变
        └── vectorstore.search_chunks(course_id, query_vec, top_k, student_access, classroom_ids, catalog_id)
                └── vectorstore.search_with_filter(ChunkFilter)   ← 降级与打标唯一入口
                        ├── RAG_VECTOR_BACKEND=json   → vector_backends.JsonBackend
                        └── RAG_VECTOR_BACKEND=qdrant → vector_backends.QdrantBackend
                                                        └── 异常/空集合 → 回落 JsonBackend + 打标
```

| 文件 | 职责 |
|---|---|
| `apps/ai/vector_backends/base.py` | `VectorBackend` 接口 + `ChunkFilter`（过滤语义唯一事实源）|
| `apps/ai/vector_backends/json_backend.py` | 现状实现原样搬迁（`filtered_queryset` 是检索语义的唯一 SQL 实现）|
| `apps/ai/vector_backends/qdrant_backend.py` | payload 构造、`ChunkFilter → Qdrant Filter` 翻译、检索/upsert/delete |
| `apps/ai/vectorstore.py` | 对外 `search_chunks`、后端选择、降级标记（`vector_meta`）|
| `apps/ai/vector_sync.py` | 双写与删除同步（`post_save` / `pre_delete` + `on_commit`）|
| `apps/ai/management/commands/backfill_qdrant.py` | 存量回填（keyset 分页 + checkpoint）|
| `apps/ai/management/commands/compare_retrieval.py` | 双读比对（重合率报告）|
| `apps/ai/tests_vectorstore.py` | 43 个用例：语义回归、双端等价、降级、双写、回填、比对 |

## 3. 过滤语义对照（改任一侧必须同步另一侧）

| 语义 | JSON 后端（Django ORM） | Qdrant payload 过滤 |
|---|---|---|
| 课程边界 | `course_id=X` | `course_id == X` |
| 旧版本课件排除 | `Q(ppt isnull) OR ppt.is_active` | `is_active == true`（写入时已按来源摊平）|
| 章节候选池 | `catalog_id=X OR (catalog isnull AND source=material)` | `should: catalog_id==X / (catalog_id==0 AND source==material)` |
| 学生·资料 | `source=material AND qa_open AND (classroom isnull OR classroom in ids)` | 同字段直接判定 |
| 学生·课件 | `ppt.is_active AND ppt.catalog.is_published` | `catalog_published == true` |
| 学生·讲稿 | `video.is_published AND video.catalog.is_published` | `video_published AND catalog_published` |
| 讲稿回滚开关 | `exclude(source=script)` | `must_not: source == script` |
| 空向量排除 | `exclude(embedding=[])` | 不写入集合（回填/双写都过滤）|

payload 字段（写入侧 `chunk_payload()` 是唯一实现）：

```
chunk_id, course_id, catalog_id(0=未挂章节), source(material|ppt|script),
page(0=无页码), is_active, material_id, ppt_id, video_id,
qa_open, classroom_id(0=面向全课程), catalog_published, video_published
```

两点说明：

1. **null 用 0 表示**：MySQL 的 `catalog_id/classroom_id` 可为 NULL，Qdrant 里统一写 0，
   过滤用 `match value=0`——不同 qdrant-client 版本对 `is_empty` 的支持不一致，0 更稳。
2. **payload 是副本，库才是真相**：命中后用 `filtered_queryset()` 按 id 复验一遍（顺带
   过滤已删除的 id）。payload 过期（资料刚关 `qa_open`、课件刚被换版）时以 MySQL 为准，
   学生可见性不能只靠一份副本。

### 3.1 payload 必须跟着父对象状态走（重要）

`qa_open / classroom_id / catalog_published / video_published / is_active` 都是**父对象状态的
快照**。老师发布章节、开关资料 QA、切换课件版本时，片段本身没变，但 payload 的可见性判定
已经过期 —— 而 DB 复验只能删「多余的命中」，**补不回漏掉的**，结果是学生在新发布的章节里
问问题检索不到内容。

测试环境实测复现：把课程 1 的第 2 章从「未发布」改为「已发布」后，MySQL 学生池 42 条、
Qdrant 侧 0 条（比对报告直接报 `42 个片段只在 json 侧命中`）。

因此 `vector_sync.py` 监听四个父对象的 `post_save`，`update_fields` 命中相关字段时重刷其
名下片段的 payload（只重刷、不重算向量）：

| 父对象 | 触发字段 |
|---|---|
| `Catalog` | `is_published` |
| `Material` | `qa_open`、`classroom_id`、`catalog_id` |
| `PPTResource` | `is_active`、`catalog_id` |
| `TeachingVideo` | `is_published`、`catalog_id` |

无关字段的保存（改标题、写 `parse_status`）不触发。`queryset.update()` 不发信号，
这类批量改法要用 `backfill_qdrant --course <id>` 补，`compare_retrieval` 可作为探测器
（报「仅 json 命中」即 payload 旧了）。

## 4. 配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| `RAG_VECTOR_BACKEND` | `json` | 唯一开关。`json`=现状实现（默认/回滚），`qdrant`=外置索引。取值非法按 json 处理 |
| `QDRANT_URL` | 空 | `http://qdrant:6333`（compose 内网）/ `http://ip:6333` / `local:<目录>`（本地文件模式，开发与单测用）；空 = 未配置 → 回落 json |
| `QDRANT_API_KEY` | 空 | 自建实例留空；Qdrant Cloud 必填 |
| `QDRANT_COLLECTION` | `zhike_chunks` | 集合名 |
| `QDRANT_TIMEOUT` | `3` | 检索超时（秒），超时即回落 json |
| `RAG_QDRANT_VECTOR_SIZE` | `1024` | 必须等于 embedding 维度（text-embedding-v3 / BGE-M3 都是 1024）。不符时后端明确报错，不静默写坏索引 |
| `RAG_QDRANT_BREAKER_THRESHOLD` | `3` | 连续失败多少次后熔断（窗口内不再尝试 Qdrant）|
| `RAG_QDRANT_BREAKER_SECONDS` | `30` | 熔断窗口长度；过后自动放行一次探活，成功即复位 |

集合参数：`size=1024`、`distance=Cosine`、`ID=chunk_id`（幂等 upsert）。

## 5. 上线步骤（生产 145）

```bash
# 0) 备份（库 + 代码 + dist，见 backups/backup.sh）
# 1) 起 qdrant 并重建 backend 镜像（requirements 新增 qdrant-client，首次构建会重下 torch 209MB）
cd /data/zhike-v2/deploy
docker compose up -d qdrant
docker compose build backend          # 代码是构建进镜像的，无 bind mount
docker compose up -d backend worker
```

> **注意**：`deploy/.env.production` 不入库（`.gitignore` 的 `*.env.*`），服务器上那份
> 需手工补上这几行（值见下表）：
>
> ```
> RAG_VECTOR_BACKEND=json
> QDRANT_URL=http://qdrant:6333
> QDRANT_API_KEY=
> QDRANT_COLLECTION=zhike_chunks
> QDRANT_TIMEOUT=3
> RAG_QDRANT_VECTOR_SIZE=1024
> ```

```bash
# 2) 回填存量向量（不重算 embedding，可按课程灰度）
docker compose exec backend python manage.py backfill_qdrant --dry-run
docker compose exec backend python manage.py backfill_qdrant --course 7
docker compose exec backend python manage.py backfill_qdrant      # 全量，自动续跑

# 3) 双读比对（≥95% 才算通过；命令不达标会非 0 退出）
docker compose exec backend python manage.py compare_retrieval --course 7 --from-chunks 10 --top-k 15

# 4) 切换：deploy/.env.production 改 RAG_VECTOR_BACKEND=qdrant
docker compose up -d backend worker    # 必须两个都重启（backend 检索、worker 双写）

# 5) 观察：日志里的 [rag] 降级行、QA 记录 context_snapshot.vector、问答质量看板「为空率」
```

## 6. 降级与观测

三种触发条件都会**自动回落 json 并打标**（`search_with_filter` 唯一出口）：

1. Qdrant 连不上 / 超时 / 认证失败 / 集合维度不符（抛异常）；
2. 集合里没有该课程任何向量但 MySQL 有片段 —— 判定为「未回填」（部署期最危险的空结果，
   不处理会让问答静默变成「资料不足」）；
3. `RAG_VECTOR_BACKEND` 取值非法或 `QDRANT_URL` 未配置。

响应与落库标记（沿用 provider 回退的显性化思路，语义独立）：

| 位置 | 字段 |
|---|---|
| `POST /api/qa-records/ask` | `vector_backend`（json/qdrant）、`vector_fallback`（bool）、`vector_fallback_reason` |
| `ask-stream` 的 `meta` 事件 | 同上三个字段 |
| `QARecord.context_snapshot.vector` | `{backend, fallback, reason}`，可在管理端按记录追溯 |

降级标记是**请求级粘性**的：章节内检索降过一次级，随后退回全课程检索成功，也不会把标记抹掉。

### 6.1 熔断：故障期不再逐请求空试

Qdrant 挂掉后，每个请求仍会先试一次（连接失败 + DNS 解析）。测试环境实测：降级状态下
检索 p50 2.8s、**p95 11.7s**（正常走 json 是 2.2s / 2.3s），故障期把延迟打穿。

因此加了进程内熔断（`RAG_QDRANT_BREAKER_THRESHOLD=3` / `RAG_QDRANT_BREAKER_SECONDS=30`）：
连续失败 3 次后，30 秒内直接走 json、不再发请求，窗口过后自动放行探活，成功即复位。
加入熔断后同一场景实测 p50 2.2s、p95 2.5s —— 与纯 json 路径一致，故障代价归零。

## 7. 运维命令

```bash
# 回填：分页 1000/批（keyset: id > last_id ORDER BY id），每批落 checkpoint
python manage.py backfill_qdrant [--course ID] [--batch-size 1000]
                                 [--start-after ID] [--reset] [--no-resume]
                                 [--no-checkpoint] [--checkpoint PATH]
                                 [--dry-run] [--timeout 60]

# 比对：同一 query、同一个查询向量（只 embed 一次）、绕开重排
python manage.py compare_retrieval --course ID [--catalog ID] [--student]
                                   [--classroom ID ...] [--top-k 15] [--tie-margin 50]
                                   [--queries "q1;q2" | --queries-file f.txt | --from-chunks N]
                                   [--out report.md] [--json-out report.json]
```

- checkpoint 默认 `backend/data/qdrant-backfill-state.json`（生产是 `/app/data/...`，
  bind mount 持久化，容器重建不丢）。跑完自动删除；中断后重跑自动从 `last_id` 续。
- `upsert` 本身幂等（ID=chunk_id），所以 checkpoint 丢了全量重跑也**不会重复、不会丢**。
- 比对报告默认落 `backend/rag_reports/compare_retrieval_<时间戳>.md` + 同名 `.json`。
- **同分容差**：同一段文本被重复入库时（测试库实测：同一份课件挂到 8 个章节，同一页文本
  入 8 次库，向量完全相同），两套后端分数一模一样，top-k 截断落在并列组中间时各自取到
  不同成员，严格按 id 比会出现 93.3% 的「假不达标」。所以报告同时给两个口径：
  - 严格 top-k 重合率（id 集合）；
  - 同分容差重合率（以两边第 k 名中较低分数为门槛，比较门槛以上的集合，并列组整组计入）
  —— 达标判定用后者，`--tie-margin 50` 控制比较时多取的条数。
- **两条都不返回候选**（如课程章节全未发布 → 学生池为空）记 100% 并单独计数（不含在
  「不达标」里）：这条查询什么都没验证，但不该被当成后端不一致。
- 同一门课、同一视角，两套后端**都为空**时用 `--student` 复核过；「仅 json 命中」非空
  才是真问题（未回填 / payload 过期）。

## 8. 已知限制

1. **写路径只覆盖 ORM**：`loaddata`、裸 SQL `UPDATE`、`queryset.update()` 改可见性字段都不会
   同步 Qdrant（`queryset.update` 不发 `post_save`）。发现手段是 `compare_retrieval` 报
   「仅 json 命中」，修法：对应片段 `chunk.save()` 或按课程重跑 `backfill_qdrant --course`。
2. 回填只搬「维度正确且非空」的向量；历史 Mock 64 维假向量会被跳过并以非 0 退出码报出来，
   需先用 `rebuild_vectors` 重新生成真实向量。
3. 单集合 + `course_id` 过滤，不做按课程分集合/分片（当前量级不需要，也避免集合数爆炸）。
4. 未实现孤儿点清理（`--prune`）；Qdrant 里比 MySQL 多的点不会影响检索（命中后被复验
   丢弃），需要时用 `compare_retrieval` 的 `only_qdrant_ids` 定位后手工 `delete`。
5. 双写失败只 `warning` 不重试：Qdrant 写入异常时该片段暂时只能在 json 侧命中，
   下次重建/回填补齐（向量库是加速层，不能让上传入库跟着失败）。
6. **同分并列**：同一段文本重复入库时分数完全并列，top-k 截断落在并列组中间，两套后端会
   各取组成员。这对问答质量无影响（分数相同），比对时用同分容差口径。
7. 熔断是**进程级**的：gunicorn 多 worker 各自熔断，故障初期最多「worker 数 × 阈值」次
   白试；跨进程共享需要 Redis，当前不值得引入。

## 9. 实测记录（2026-11-04，本地 185 片段 / 课程 5、7）

回填（`local:` 文件模式，非容器，脚本口径与生产一致）：

```
目标集合：zhike_chunks_dev（size=1024, distance=Cosine） · 地址 local:D:/tmp/qdrant-local
范围 all：待搬运 185 个片段
  id<=1043 读取 100/185 · 写入 100
  id<=1250 读取 185/185 · 写入 185
回填完成：读取 185 · 写入 185 · 跳过 0 · 耗时 1.2s · 集合当前点数 185
```

双读比对（`--from-chunks 6 --top-k 15`，3 组过滤：全课程 / 章节池 + 学生 / 学生）：

```
平均重合率 100.0% · 最低 100.0% · ≥95% 的查询 6/6
同片段分数最大偏差：0.0（原样搬运 → 只应有浮点误差）
仅 json 命中：0 个   仅 qdrant 命中：0 个
```

降级实测（`QDRANT_URL=http://127.0.0.1:6399`，无服务）：

```
hits 5 [0.002, -0.0, -0.004, ...]                ← 仍有结果，问答可用
meta {'backend': 'json', 'fallback': True, 'reason': 'Qdrant 检索不可用，已回落 MySQL 检索：...'}
```

未回填集合（集合存在但无该课程向量）：

```
meta {'backend': 'json', 'fallback': True, 'reason': 'Qdrant 集合中该课程尚无向量（未回填），已回落 MySQL 检索'}
```

测试：`manage.py test apps.ai.tests_vectorstore --keepdb` → 43 passed；
`manage.py test apps.ai apps.knowledge --keepdb` → 258 passed；
全量 `manage.py test --keepdb` 见交付说明。

## 10. 测试环境实测（192.168.3.145:8092 / compose 项目 zhike_qv）

部署形态与生产**不同**：测试栈把 `/data/zhike-queue-verify/backend` bind mount 到 `/app`，
代码改文件即生效；qdrant-client 用「FROM zhike-v2-backend + pip install」的薄层镜像
`zhike-v2-backend:qdrant`（正式环境仍用 `:latest`，由 requirements 正常构建）。

数据：1258 个片段 / 4 门课（课程 1: 690、2: 244、9: 244、12: 80），全部 1024 维。

回填：

```
范围 all：待搬运 1258 个片段
  id<=1310 读取 1000/1258 · 写入 1000
  id<=1728 读取 1258/1258 · 写入 1258
回填完成：读取 1258 · 写入 1258 · 跳过 0 · 耗时 7.9s · 集合当前点数 1258   （进程总耗时 12.7s）
```

双读比对（课程 1 全量 10 问、课程 2 学生视角 8 问、课程 1 第 2 章学生视角 5 问）：
同分容差重合率 **100%**，严格 top-15 重合率 97.5%（8 问中 2 问受并列影响），
同片段分数最大偏差 1e-7（Qdrant 内部 float32 存储）。

### 10.1 上限检测（检索层，容器内直接量）

课程 1：MySQL 候选池 690 条，集合 1258 点；top_k=15；每档 40~60 次请求，10 条查询向量预计算。

| 后端 | 并发 | p50 | p95 | p99 | QPS |
|---|---|---|---|---|---|
| json（现状） | 1 | **2204.9ms** | 2289.4ms | 2298.3ms | 0.5 |
| json | 4 | 5195.7ms | 6338.0ms | 6379.9ms | 0.7 |
| json | 8 | 10344.3ms | 11705.9ms | 11752.4ms | 0.8 |
| json | 16 | 20308.1ms | 24481.0ms | 26215.7ms | 0.7 |
| qdrant（完整后端：检索+回填详情） | 1 | **21.6ms** | 24.5ms | 25.3ms | 46.2 |
| qdrant | 4 | 56.9ms | 106.7ms | 113.0ms | 63.8 |
| qdrant | 8 | 111.2ms | 160.2ms | 177.6ms | **67.7（饱和）** |
| qdrant | 16 | 215.2ms | 311.1ms | 340.2ms | 60.4 |
| qdrant 纯向量（不回表） | 1 | 8.4ms | 10.4ms | 10.5ms | 112.1 |
| qdrant 纯向量 | 8 | 30.7ms | 46.7ms | 55.1ms | **216.6（饱和）** |

结论：
1. 现状 json 后端在 690 片段的课程上**单次检索 2.2 秒、整体吞吐 0.8 QPS**，且并发越高延迟线性
   恶化（GIL + 每次把 7MB 向量 JSON 反序列化）——这不是「Qdrant 更快」的问题，是现状已经
   不可用（一次问答在检索上就花 2 秒）。
2. Qdrant 换上后端到端 p50 21.6ms、饱和 ~68 QPS，**提升约 80 倍**。
3. 瓶颈已经转移到「命中后回 MySQL 取详情」：纯向量只要 8.4ms / 216 QPS，端到端 21.6ms /
   68 QPS。已做一项优化：回表时 `defer("embedding")`（15 条命中原本要白传 150KB 向量），
   实测 p50 53ms → 21.6ms、饱和 35 → 68 QPS。

### 10.2 HTTP 端到端（经 8092 → nginx → gunicorn）

| 场景 | 结果 |
|---|---|
| Qdrant 正常 · 管理员提问（章节内） | 200 · `vector_backend=qdrant` · 5 条引用 · 14.9s（含 LLM） |
| Qdrant 正常 · 学生提问 | 200 · `vector_backend=qdrant` · 1 条引用（该章仅讲稿兜底） |
| **停掉 Qdrant 容器** · 提问 | 200 · `vector_backend=json` · `vector_fallback=true` · 8 条引用 · 理由带回响应 |
| 重新启动 Qdrant · 提问 | 200 · `vector_backend=qdrant` · 6 条引用 · 8.6s |
| Qdrant 停机 + 熔断生效后的检索延迟 | p50 2.2s / p95 2.5s（等于纯 json，无额外代价） |
| Qdrant 容器重启后数据 | 1258 点仍在（bind mount 卷持久化） |

问答耗时以 LLM 为主（6~26s），检索只占其中 20ms~2s。

### 10.3 生产上线记录（2026-11-04，145:8088 / compose 项目 `deploy`）

按第 5 节流程执行，实测踩到三处，记为下次的检查项：

1. **端口**：测试栈与生产栈同机，两边都绑 `127.0.0.1:6333` 会冲突。生产占标准 6333，
   测试栈改 `127.0.0.1:6433`（容器间仍走各自网络的服务名，不受影响）。
2. **镜像构建**：`docker builder prune -f` 腾出 8GB 后，apt/pip 层缓存全丢，构建退化为
   全量（apt + pip 含 torch 209MB，约 15 分钟）。若只是想缩小镜像可用
   `--build-arg PRELOAD_MODELS=false`，但**生产 `/data/zhike-v2/data/models` 已有 5.5GB 模型**，
   预载层其实是冗余的；真正省时间的做法是保留 builder 缓存，别在构建前 prune。
3. **历史假向量**：回填发现 **275 个片段是 64 维 Mock 向量**（全部来自课程 5 的资料 10），
   维度不符被跳过、命令非 0 退出。处理：`rebuild_vectors --material 10`（真实模型重算，
   275 → 251 片段，一次 embedding 成本可忽略）后重跑回填，`跳过 0`。

上线结果：

```
镜像 zhike-v2-backend:latest（含 qdrant-client 1.15.1）· 回滚标签 pre-qdrant-20261104
回填：读取 4890 · 写入 4890 · 跳过 0 · 耗时 33.7s · 集合点数 4890
比对：课程 10 全量 8/8 = 100%；课程 5 学生视角 6/6 = 100%（严格口径同为 100%）
切换后：_gather_course_context → {'backend': 'qdrant', 'fallback': False}，8 条引用
完整问答（含 LLM）：答案正常、degraded=0、日志无 [rag] 降级行
```

回滚件：`docker-compose.yml.bak-qdrant-*`、`.env.production.bak-qdrant-*`、
`backups/backend-pre-qdrant-*.tar.gz`、镜像 `zhike-v2-backend:pre-qdrant-20261104`。

## 11. 回滚

**一句话：`deploy/.env.production` 改回 `RAG_VECTOR_BACKEND=json`，重启 backend 与 worker。**

向量本来就在 MySQL 的 `embedding` 列里，Qdrant 只是副本，回滚不涉及任何数据迁移；
容器可以继续留着（不占用检索路径），也可以 `docker compose stop qdrant` 彻底停掉。

镜像级回滚（连代码一起退，例如 Qdrant 相关代码本身出问题）：

```bash
cd /data/zhike-v2/deploy
sudo docker tag zhike-v2-backend:pre-qdrant-20261104 zhike-v2-backend:latest
sudo docker compose -p deploy -f docker-compose.yml up -d backend worker
```

代码级回滚（服务器非 git 仓）：`sudo tar xzf backups/backend-pre-qdrant-*.tar.gz -C /data/zhike-v2/`。
