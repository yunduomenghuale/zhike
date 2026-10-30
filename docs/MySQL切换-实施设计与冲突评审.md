# MySQL 切换 · 实施设计与冲突评审（v2）

> 2026-10-30　范围：**仅本地开发环境**从 SQLite 切到 MySQL（`zk` 库）。生产部署（192.168.3.145 / Docker）不在本次范围。
> 前置文档：`docs/MySQL切换方案.md`（v1 排查报告）。本文修订 v1 中**已证实有误或会互相打架**的部分，并给出可逐步回退的实施顺序。

---

## 0. 本次修订要点（v1 → v2 的实质变化）

| # | v1 的写法 | v2 修订 | 依据 |
|---|---|---|---|
| 1 | 把"hys/孟燕姿 双班归属"列为切库前置阻塞 | **本地路径不需要处理**。本地是"空库全量 migrate"，`classroom/0006` 的卫兵在空表上直接通过；该冲突只存在于"在既有库上升级 schema"的路径（线上搬迁） | 卫兵代码 `check_single_class()` 查的是 `ClassStudent` 表有无重复，空表必然通过 |
| 2 | 搬迁时"清空 MySQL 自动生成的 ct/permission，再按源库 ID 重导，保证引用一致" | **改为完全不搬** `django_content_type` / `auth_permission`。源库有 4 个已删模型的孤儿 ct（`ai.aiconfiguration` / `courses.coursevideo` / `labs.labanswer` / `labs.labquestion`），重导必然要么 FK 失败、要么灌入死权限；而本项目权限体系零业务引用（`users_user_user_permissions` = 0，`users_user_groups` = 0，`auth_group` = 0，`django_admin_log` = 0），让 MySQL 的 `post_migrate` 自行生成 52 个 ct 即可，ID 差异无任何影响 | 实测本地库：M2M 三张表全 0 行；ct 56 条 vs 现有模型 52 个，差集正好 4 个孤儿 |
| 3 | 未提测试库权限 | 新增一项识别：`zk` 账号没有全局 CREATE，`manage.py test` 直接跑会卡在建 `test_zk`。解法是 `--keepdb` + 预建空 `test_zk`（源码确认 keepdb 模式不发 CREATE），**不放大任何权限** | `SHOW GRANTS` 实测只有 `zk.*`/`test_zk.*`；`db/backends/base/creation.py:204` |
| 4 | 校验清单里写"JSON 完整性 + 条数" | 明确**禁止对 JSON 列做文本 hash 比对**：MySQL 的 `json` 类型会把值重新格式化（键序、空白），同一语义的文本可能不同 | MySQL JSON 存储层规范化的既有行为 |
| 5 | 未区分"本地切换"与"线上搬迁" | 拆成**路径 A（本地，本次）** 与 **路径 B（线上，后续）**，两者的前置条件不同，不可套用 | — |

---

## 1. 现状快照（动手前的基线）

### 1.1 已产生的改动（需要你确认是否保留）

| 文件 | 状态 | 是否已激活 |
|---|---|---|
| `backend/config/settings.py` | 已改：新增 `mysql://` 分支（utf8mb4 / init_command / TEST charset / CONN_MAX_AGE） | **未激活**——`DATABASE_URL` 仍是 sqlite |
| `backend/requirements.txt` | 已改：加 `mysqlclient==2.2.7` | 未激活（生产镜像未重建） |
| `backend/.env.example` | 已改：示例值改为 mysql 形态 | 不影响运行 |
| `backend/.env` | 曾改为 mysql，**已回退为 `sqlite`** | 未激活，系统行为与改动前一致 |

- 3 个受 git 跟踪的改动均未 commit，`git checkout -- <file>` 可一键还原。
- `zk` 库已建（空表）、`test_zk` 已建（空表）、账号 `zk/zk123456` 已建并授权 `zk.*` `test_zk.*`。
- venv 已装 `mysqlclient 2.2.7`（Windows 官方 cp312 wheel，无需编译）。
- **尚未执行任何 `migrate`、未写入任何数据、未改任何业务代码。**

### 1.2 数据基线（迁移源）

| 项 | 值 |
|---|---|
| 源库 | `backend/db.sqlite3`（20 MB，58 张表含 `sqlite_sequence`） |
| 迁移记录 | 120 条（与仓库代码完全一致，`makemigrations --check` = No changes） |
| 业务数据量 | users 20 / courses 4 / chunk 185 / aicalllog 616 / question 34 / qarecord 54（全库 < 2000 行业务数据） |
| 约束合规 | 7 条条件唯一约束**全部无违反**（多班占用 0、`is_current` 1 条、全局配额 1 条、其余 0） |
| 字段形态 | datetime 全为 `TEXT 'YYYY-MM-DD HH:MM:SS.ffffff'`（UTC naive）；JSON 为 `TEXT`（中文 `\uXXXX` 转义）；Decimal 列 SQLite 侧混存 int/real/text |

### 1.3 目标库

`zk`（utf8mb4 / utf8mb4_0900_ai_ci）、MySQL 8.0.36、`lower_case_table_names=1`、`sql_mode` 含 `ONLY_FULL_GROUP_BY`。

---

## 2. 变更集（每项独立可回退）

| 编号 | 变更 | 落点 | 激活条件 | 回退方式 | 风险 |
|---|---|---|---|---|---|
| **C0** | 建库 / 建号 / 授权 | MySQL 实例 | 立即生效 | `DROP DATABASE zk` | 无（独立库，不碰其他库） |
| **C1** | `DATABASE_URL` 支持 `mysql://` | `config/settings.py:129+` | 由 `.env` 决定 | 删分支 / 改回 `sqlite` | 低（未激活时零影响） |
| **C2** | 依赖 `mysqlclient` | `requirements.txt`、venv | pip 安装 | 卸载 | 低 |
| **C3** | 7 条条件唯一约束的 MySQL 等价实现 | 4 个新迁移：`classroom/0008`、`courses/0014`、`knowledge/0012`、`ai/0017` | `migrate` 时按 vendor 分支执行 | 迁移 `backwards` 或删表重建 | **中**（DDL 正确性、唯一性语义） |
| **C4** | 两处 `select_for_update` 缺事务 | `exams/views.py:348`、`courses/views.py:284` | 代码层，两库通用 | 还原文件 | 低（SQLite 下行为不变） |
| **C5** | 数据搬迁脚本 | `backend/scripts/sqlite_to_mysql.py`（新增，不入镜像） | 手工执行 | 删除文件 | 低 |
| **C6** | `.env` 指向 MySQL | `backend/.env` | 改完即生效 | 改回 `sqlite` | 中（激活开关） |
| **C7** | 测试库授权 | 无需改动（`--keepdb` + 预建 `test_zk`） | 立即 | 删库 | 低 |
| **C8** | 部署件（Dockerfile/compose/entrypoint） | `deploy/*` | 本次**不动** | — | 留到部署阶段 |

---

## 3. 依赖与实施顺序

```
C0 建库 ─┬─► C1 settings ─► C2 依赖 ─► C3 生成列迁移 ─► C3' SQLite migrate 对齐 ─┐
         │                                                                        ├─► 阶段2 建表 ─► 阶段3 导入 ─► 阶段4 验证
         ├─► 预建 test_zk（已有） ─────────────────────────────────────────────--┤
         └─► C5 搬迁脚本 ─────────────────────────────────────────────────────--┘
C4 事务修复（独立，可先做，SQLite 上先跑测试确认零回归）
C6 .env 切 mysql —— 必须最后一步（C1/C2/C3 全就位后才允许）
```

每个阶段结束都有 Gate（见 §6），**Gate 不通过不进入下一阶段**，且每次只激活一个变量（代码 → 建表 → 数据 → 功能）。

关键串行约束（不可调换）：
1. **C3 必须在 `migrate` 之前存在**——空库建表时就带上生成列唯一索引，导入期间即可当数据质量闸门。
2. **C6（激活开关）必须在 C1/C2/C3 全部就位后**才改，否则 `runserver` 会连到空库直接报错。
3. **C4 与数据库无关**，但必须在本轮内完成——否则切到 MySQL 后考试暂存/讲稿换版立刻 500。

---

## 4. 冲突评审（逐条给决策）

> 格式：**现象 → 为什么冲突 → 决策 → 验证**

### C-01 「条件唯一约束」在 MySQL 上静默消失
- 现象：Django `_unique_supported()` 对 `condition` + `supports_partial_indexes=False` 返回 False，`_unique_sql()` 返回 `None`，不建约束、不报错、不告警。
- 决策：改「生成列 + 普通唯一索引」，按 `vendor == "mysql"` 分支执行；`Meta.constraints` **原样保留**（SQLite 侧继续用原生部分索引）。
- 失败模式（必知）：MySQL 的 DDL 隐式提交、不可回滚。若 `ADD COLUMN` 成功而 `ADD UNIQUE KEY` 失败（数据重复），会留下"列已加、索引未建"的中间态，迁移记录也不会写入。恢复动作：手工 `ALTER TABLE ... DROP COLUMN` 后重跑。本地是空库，概率极低，但路径必须写在文档里。
- 验证：`information_schema.statistics` 必须查到 7 个索引名；SQLite 侧 `sqlite_master` 仍能看到 `WHERE` 部分索引。

### C-02 生成列会不会干扰 Django 的读写
- 现象：模型里没有这两个列，担心 INSERT 缺列报错、`SELECT *` 错位。
- 决策：Django 永远显式列出列名（`INSERT INTO t (a,b) VALUES`），SELECT 也只取模型字段，生成列对它完全不可见；`makemigrations` 只比对模型状态，不会提议删列。
- 验证：迁移后 `makemigrations --check` 必须仍是 `No changes`；对 7 张表各做一次 ORM `create → update → delete` 往返。

### C-03 生成列迁移在 SQLite 上是空操作，会不会让两库迁移记录错位
- 现象：`RunPython` 里 vendor 不为 mysql 直接 return，但迁移记录照样写入。
- 决策：这是**期望行为**——两库 `django_migrations` 保持 124 条完全一致，才能随时 `DATABASE_URL` 回切。迁移必须是"有记录、无副作用"。
- 验证：切回 SQLite 后 `showmigrations` 无未应用项，且 SQLite 功能不变。

### C-04 空库 migrate 时 `classroom/0006` 卫兵会不会拦
- 现象：v1 把"两名学生双班"当成切库阻塞项。
- 决策：**本地路径不成立**。空表 → 卫兵查无重复 → 通过。该卫兵只在"既有数据升级"时才有意义（路径 B）。
- 验证：`migrate` 一次跑完 124 个迁移，无 RuntimeError。

### C-05 导入时要不要关 `UNIQUE_CHECKS`
- 现象：关掉能显著提速（InnoDB 延迟唯一校验）。
- 决策：**只关 `FOREIGN_KEY_CHECKS`，不关 `UNIQUE_CHECKS`**。理由：唯一索引是本次迁移的数据质量闸门，关掉等于把"源库脏数据"悄悄灌进来；本地数据量 < 2000 行，性能收益可忽略。
- 验证：7 张受约束表导入时若出现 1062 必须失败中止。

### C-06 `contenttypes` / `auth_permission` 怎么搬
- 现象：v1 计划"清空重导保 ID"。
- 决策：**完全不搬**。证据：`users_user_user_permissions`=0、`users_user_groups`=0、`auth_group`=0、`auth_group_permissions`=0、`django_admin_log`=0；源库 ct 比现有模型多 4 个孤儿项。让 MySQL `post_migrate` 自行生成。
- 验证：导入后 `django_content_type` = 52 行（现有模型数）、`auth_permission` 行数 > 0，且 `users_user_user_permissions` 仍为 0。

### C-07 测试库建不出来
- 现象：`zk` 只有库级授权，`manage.py test` 默认要 `CREATE DATABASE test_zk`，而 `CREATE DATABASE` 是全局权限，库级 ALL 拿不到。
- 决策：**用 `--keepdb` + 预建空 `test_zk`**，不放大任何权限。源码依据：`db/backends/base/creation.py:204` 把 `keepdb` 透传给 `_execute_create_test_db()`，后者在 `keepdb=True` 时**直接 return，不发 CREATE**；异常分支 `:208` 同样在 keepdb 时静默返回。
- 已知局限：模型/迁移变更后 keepdb 的旧 schema 会与新代码不匹配，此时需 root 执行一次 `DROP DATABASE test_zk; CREATE DATABASE test_zk CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;`，再继续 `--keepdb`。
- 备选（若嫌手工重建麻烦）：`GRANT CREATE, DROP ON *.* TO 'zk'@'%'`，本地开发库可接受，但要接受权限放大。
- 验证：`manage.py test apps.classroom --keepdb` 能跑完。

### C-08 E2E / 校验脚本会打穿主库
- 现象：`scripts/p1_permission_matrix.py`、`p4_graduation_check.py`、`p5_security_check.py` 与 `test/e2e/*.js` 都是"连上库、造数据、删数据"。它们原本靠 `SQLITE_PATH` 指副本隔离；切 MySQL 后若直连 `zk`，会把开发主库搅乱。
- 决策：E2E 一律用独立库 `zk_e2e`（同结构、空数据），通过 `DATABASE_URL` 注入；`SQLITE_PATH` 机制保留给"SQLite 历史回归"用，不删。
- 验证：跑一轮 `p5_security_check.py` 后，`zk` 的表行数不变。

### C-09 datetime 归一化
- 现象：源库 datetime 是 text（UTC naive，`2026-08-21 08:48:14.796408`）。若原样透传，MySQL `datetime(6)` 能解析；但历史数据若存在带 `+00:00` 后缀或空格缺失的形态，会静默变 `0000-00-00`（严格模式则报错）。
- 决策：脚本对 datetime 列**统一解析再写**：`datetime.fromisoformat` → 若带 tz 则转 UTC 并去 tz → 输出 `'%Y-%m-%d %H:%M:%S.%f'`；解析失败立即中止并打印 `表.列/PK/原值`。
- 验证：抽查 `users.date_joined`、`ai_aicalllog.created_at` 各 5 条，迁移前后**逐字相等**。

### C-10 JSON 列不能做文本比对
- 现象：MySQL `json` 类型会在存储时规范化（键序、空白），`SELECT` 回来的文本与源库不同。
- 决策：验收只看 ① `JSON_VALID` ② `JSON_LENGTH` ③ 抽样元素值（如向量首元素）；**不做文本 hash**。
- 验证：185 行 chunk 的 `JSON_LENGTH(embedding)=1024` 与源库一致。

### C-11 Decimal 混存
- 现象：SQLite 里 `homework_submission.score` 存的是 `integer 8`，`questions_question.score` 也是 integer；MySQL `numeric(5,1)` 能接。
- 决策：统一 `Decimal(str(v))`，禁止 float 直传（防 `8.100000000000001`）。
- 验证：`SUM(score)` 与源库差 < 0.01。

### C-12 `sql_mode` 覆盖的取舍
- 现象：`init_command` 会覆盖服务器默认（本机默认含 `ONLY_FULL_GROUP_BY`）。
- 决策：显式设 `STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ENGINE_SUBSTITUTION`，**主动放弃** `ONLY_FULL_GROUP_BY`。理由：项目有 `values().annotate()` 组合查询，保留它会在个别报表接口抛 1055；严格模式与零日期保护才是数据安全的关键。代价是失去"GROUP BY 严格校验"，属可接受。
- 验证：`SELECT @@sql_mode` 与 settings 一致；Django system check 无 `mysql.W002`。

### C-13 时区表
- 现象：`TruncDate(tzinfo=...)` / `__date` 在 MySQL 上走 `CONVERT_TZ`，时区表缺失则返回 NULL。
- 决策：装载 `mysql_tzinfo_to_sql`；Windows 本机 MySQL 安装包通常已带时区表，需实测。若缺失，退路是改为在 Python 侧按本地时区分组（改 3 处调用）。
- 验证：`SELECT CONVERT_TZ('2026-10-30 00:00:00','UTC','Asia/Shanghai')` 非 NULL。

### C-14 双库分叉
- 现象：只有一个 `DATABASE_URL`，切过去之后 SQLite 侧再有写入就分叉。
- 决策：切换后 **SQLite 冻结为只读历史快照**（备份 + 写明"勿再用 sqlite 启动跑业务"）；所有业务写入以 MySQL 为准。分叉检测：回切前先比对 `ai_aicalllog` 的 `max(id)`。
- 验证：文档 + `.env` 注释双处声明。

### C-15 自增位
- 现象：显式 PK 导入后，若自增位没跟上，后续 INSERT 会撞主键。
- 决策：InnoDB 在插入显式 PK 时会自动把 `AUTO_INCREMENT` 推到 `max+1`，但仍逐表断言。
- 验证：`information_schema.tables.auto_increment > MAX(id)`（7 张核心表）。

### C-16 大字段容量
- 现象：`parsed_pages` 228 KB、`scripts` 266 KB，担心 MySQL `TEXT` 64 KB 截断。
- 决策：Django 在 MySQL 上把 `TextField` 映射为 `longtext`（`db/backends/mysql/base.py:133`），不会截断；`JSONField` → `json`，受 `max_allowed_packet`（默认 64 MB）约束。本机默认足够，无需调参。
- 验证：导入后 `length(parsed_pages)` 与源库一致。

### C-17 `select_for_update` 缺事务
- 现象：SQLite 下是 no-op，MySQL 下抛 `TransactionManagementError`（`db/models/sql/compiler.py:828`）。
- 决策：`exams.save` 加 `@transaction.atomic`；`courses.generate_script` 只把换版重置那段包进 `atomic`，**AI 长调用绝不放事务内**（否则持锁 180 秒）。
- 验证：在 SQLite 上先跑 `apps.exams` 测试确认零回归；切库后点测"考试暂存"与"强制重生成讲稿"。

### C-18 向量检索性能回归
- 现象：`vectorstore.search_chunks` 每次问答把整门课的 chunk（含 20 KB 向量）全量拉进 Python。
- 决策：本次不改实现，但**验收加一条量化门槛**：单次问答检索耗时 ≤ SQLite 基线的 3 倍。本地 185 行无压力；数据涨到万级再考虑外置向量库。
- 验证：同一问题在两种库上各跑 3 次取中位数。

### C-19 回退路径
- 现象：切到 MySQL 并写入后，无法自动回灌 SQLite。
- 决策：回退窗口定义为"切换后未产生新写入"或"接受窗口内数据丢失"。因为本次是本地开发库，回退代价只是一次 `db.sqlite3` 还原，可接受。切换前先 `cp db.sqlite3 db.sqlite3.pre-mysql-<日期>`。
- 验证：回切演练（见 Gate 5）。

### C-20 迁移编号冲突
- 现象：4 个新迁移要和现有最新号衔接，否则会形成分支。
- 决策：`classroom/0008`、`courses/0014`、`knowledge/0012`、`ai/0017`（已核对各 app 现有最大编号）。
- 验证：`showmigrations --plan` 无 `<app>.<冲突>`、`makemigrations --check` 干净。

### C-21 `exclude(embedding=[])` 在 MySQL 上可能静默过滤掉全部片段
- 现象：`apps/ai/vectorstore.py:59` 用 `.exclude(embedding=[])` 过滤空向量。该写法在 SQLite 上等价于 `NOT (embedding = '[]')`；MySQL 的 `json` 列比较走 JSON 语义，且 `NOT(...)` 遇 NULL 会返回 NULL（被当 False）。一旦行为不同，**问答不会报错，只是检索不到任何片段**，表现为"AI 回答变差/参考来源为空"，极难察觉。
- 决策：不改写法，但列为**必测项**——Gate 4 必须验证"QA 提问能召回到片段且 `cited_chunks` 非空"。若证实失效，改为 `.filter(embedding__isnull=False).exclude(embedding__len=0)` 或 Python 侧过滤。
- 验证：同一条问题在两种库上提问，`cited_chunks` 条数与来源类型一致。

### C-22 新增迁移后 SQLite 与 MySQL 的迁移记录必须重新对齐
- 现象：C3 新增 4 个迁移后，SQLite 侧会立刻显示 4 个"未应用"，而 MySQL 侧是"已应用"。这会破坏"随时回切"的前提。
- 决策：C3 落地后**立刻在 SQLite 上 `migrate` 一次**（4 个迁移在 SQLite 上是 no-op，但会写入记录），让两库都回到 124 条。
- 验证：两库 `showmigrations` 均无 `[ ]`；SQLite 的 `sqlite_master` 里 7 条部分索引仍然存在（说明没被误删）。

---

## 5. 数据搬迁设计

### 5.1 搬什么 / 不搬什么

| 处理 | 表 |
|---|---|
| **搬** | 全部业务表 + `users_*` + `token_blacklist_*` + `django_session` + `django_admin_log`（0 行也搬，保持结构完整） |
| **不搬**（让 MySQL 自行生成） | `django_content_type`、`auth_permission`、`auth_group`、`auth_group_permissions`、`users_user_user_permissions`、`users_user_groups` |
| **不搬**（Django/引擎自管） | `django_migrations`（migrate 已写）、`sqlite_sequence`（InnoDB 自增） |

### 5.2 列处理规则

1. 目标列清单来自 `information_schema.columns`，**过滤 `EXTRA LIKE '%GENERATED%'`**（生成列不可写）。
2. 取源表列名与目标列名的交集；目标独有列（如生成列已排除、或新增可空列）不写，走 DEFAULT/NULL。
3. 源独有列（MySQL 已不存在的历史列）忽略并打印告警。

### 5.3 执行模型

```
SET FOREIGN_KEY_CHECKS=0（当前连接）
for table in 拓扑序:
    BEGIN; INSERT ... VALUES (...),(...) ×N; COMMIT;   # 每表一事务
失败 → 立即中止，打印表名/列名/首条失败行 PK，保留已提交表
重跑 → --reset 先 TRUNCATE 全部目标业务表再导入（幂等）
```

### 5.4 校验（导入后自动输出报告）

| 项 | 判据 |
|---|---|
| 逐表行数 | 全等（不搬的 6 张表除外） |
| 关键字段指纹 | `users.password` / `questions_question.stem` / `exams_examsubmission.answers` 按 PK 排序 sha256 相等 |
| datetime | 抽样逐字相等 |
| JSON | `JSON_VALID` 全真 + `JSON_LENGTH` 相等 + 首元素抽样 |
| 外键孤儿 | 关键链路 0 行 |
| 自增位 | `auto_increment > MAX(id)` |
| 约束存在 | 7 个 `*_mysql` 唯一索引全在 |

---

## 6. 验收门槛

| Gate | 内容 | 不通过的处置 |
|---|---|---|
| **G1** | SQLite 基线：改动 C1/C3/C4 后，`makemigrations --check` 干净；在 SQLite 上 `migrate` 让 4 个新迁移落记录（no-op），两库同为 124 条；`apps.exams`/`apps.classroom`/`apps.courses`/`apps.knowledge`/`apps.ai` 测试全绿 | 回退本次改动，不进入下一步 |
| **G2** | 结构：`zk` 124 个迁移应用完成、7 索引存在、字符集/排序规则正确、`CONVERT_TZ` 非 NULL、`sql_mode` 符合 C-12 | 重建 `zk` 重来 |
| **G3** | 数据：§5.4 全部通过 | 修脚本重导（`--reset`） |
| **G4** | 功能：登录 → 章节树 → 讲稿生成 → 考试开考/暂存/交卷 → QA 提问 → 导出 xlsx → 看板趋势非空；检索耗时不超基线 3 倍 | 定位后再决定是否回切 |
| **G5** | 回退：`db.sqlite3` 还原 + `.env` 改回 sqlite，服务正常 | — |

---

## 7. 变更影响面（谁受影响 / 谁不受影响）

| 对象 | 受影响？ | 说明 |
|---|---|---|
| `frontend/`（Vue3） | **否** | 只经 HTTP 访问后端，API 契约不变，无需改一行 |
| `app/`（uni-app 移动端） | **否** | 同上 |
| `media/` 上传文件 | **否** | 文件仍在磁盘，DB 只存相对路径 |
| `data/models` 本地模型权重 | **否** | 与数据库无关 |
| 缓存（`login_fail_cache` / `oversight_cache` / LocMem） | **否** | 文件/内存缓存，非 DB |
| 限流计数 | **否** | LocMem，进程内 |
| `deploy/` 部署件 | **本次不动** | 留到部署阶段（Q4） |
| `scripts/p1|p4|p5_*.py` | **是** | 依赖 `SQLITE_PATH` 副本机制，需注入 `DATABASE_URL` 指向 `zk_e2e` |
| `test/e2e/*.js` | **是** | 同上，必须换独立库，否则污染主库 |
| `apps/courses/tests.py` 等 SQLite 专有用例 | **是** | 需按 vendor 跳过（切测试库后才暴露，Gate G4 逐条归类） |
| 生产服务器 | **否** | 本次不部署 |

---

## 8. 未决问题（需要你拍板，拍完我就按 §3 顺序逐项落地）

| # | 问题 | 我的建议 |
|---|---|---|
| Q1 | 已改的 3 个文件（settings / requirements / .env.example）**保留还是先回退**？ | 保留。它们未激活、可单独成 commit；回退反而要重做一遍。若要绝对干净，我可 `git checkout` 后再按批次重做 |
| Q2 | 测试库权限：`--keepdb` + 预建 `test_zk`（不放大权限）还是给 `zk` 全局 `CREATE, DROP`（省手工重建）？ | **`--keepdb`**（方案 2）。已在源码确认 keepdb 模式不发 CREATE；代价只是改 schema 后要找 root 重建一次 `test_zk` |
| Q3 | E2E / 校验脚本是否也切到 MySQL（需建 `zk_e2e` 库）？ | 是。否则 E2E 仍在 SQLite 上跑，等于没验证新库；给 `zk` 加 `zk_e2e.*` 授权即可 |
| Q4 | `deploy/`（Dockerfile 编译依赖、compose 的 mysql 服务、entrypoint 分支）现在写还是留到部署阶段？ | 留到部署阶段。本次只做代码层 + 本地验证，避免"写了但没验证"的部署件混进仓库 |

---

## 附录 A：已验证的技术事实（不是推测）

| 事实 | 依据 |
|---|---|
| 条件唯一约束在 MySQL 上被**静默跳过** | `django/db/backends/base/schema.py:1773` `_unique_supported()` return False → `:1801` `_unique_sql()` return `None` |
| `select_for_update` 在 autocommit 下抛异常 | `django/db/models/sql/compiler.py:826-832` |
| TextField → `longtext`、JSONField → `json`、DateTimeField → `datetime(6)` | `django/db/backends/mysql/base.py:113-133` |
| MySQL 支持 `STORE` 生成列 + 唯一索引 | MySQL 8.0.36 实测环境（DDL 待 Gate 2 验证） |
| 本地 7 条约束数据合规 | 直查 `db.sqlite3` 七条 SQL，全部 0 冲突 |
| 权限表零引用 | `users_user_user_permissions`/`users_user_groups`/`auth_group*`/`django_admin_log` 全 0 行 |
| 本机 MySQL 8.0.36、utf8mb4_0900_ai_ci、`lower_case_table_names=1` | `SELECT @@...` 实测 |
| `zk` 账号缺全局 CREATE | `SHOW GRANTS FOR 'zk'@'%'` 实测 |

## 附录 B：7 条约束的落地 DDL（列名/类型已按模型核对）

> 列名与可空性来自 `Model._meta` 实测，不是照抄文档：`student_id`/`course_id`/`catalog_id`/`triggered_by_id`/`user_id` 均为外键物理列名；`path` varchar(255)、`legacy_key` varchar(64)、`learn_status` varchar(16)、`is_current` tinyint(1)、`task_type`/`status` 均 NOT NULL。

```sql
-- 1) classroom.ClassStudent：一个学生最多一条占用关系
ALTER TABLE classroom_classstudent
  ADD COLUMN occ_student_id BIGINT
    GENERATED ALWAYS AS (CASE WHEN learn_status IN ('active','inactive')
                              THEN student_id END) STORED,
  ADD UNIQUE KEY uniq_occupied_class_per_student_mysql (occ_student_id);

-- 2) courses.CourseResource：(course, path) 唯一，仅 path 非空时
ALTER TABLE courses_courseresource
  ADD COLUMN occ_path VARCHAR(255)
    GENERATED ALWAYS AS (IF(path = '', NULL, path)) STORED,
  ADD UNIQUE KEY unique_course_resource_path_mysql (course_id, occ_path);

-- 3) courses.Term：只能有一个当前学期
ALTER TABLE courses_term
  ADD COLUMN occ_current TINYINT
    GENERATED ALWAYS AS (IF(is_current = 1, 1, NULL)) STORED,
  ADD UNIQUE KEY unique_current_term_mysql (occ_current);

-- 4) knowledge.QASession：(course, student, legacy_key) 唯一，仅 legacy_key 非空时
ALTER TABLE knowledge_qasession
  ADD COLUMN occ_legacy_key VARCHAR(64)
    GENERATED ALWAYS AS (IF(legacy_key = '', NULL, legacy_key)) STORED,
  ADD UNIQUE KEY uniq_qasession_legacy_mysql (course_id, student_id, occ_legacy_key);

-- 5/6) ai.AITask：两类任务各自"进行中"最多一条
ALTER TABLE ai_aitask
  ADD COLUMN occ_active_summary BIGINT
    GENERATED ALWAYS AS (IF(task_type='chapter_summary'
                            AND status IN ('pending','running'), 1, NULL)) STORED,
  ADD COLUMN occ_active_gen BIGINT
    GENERATED ALWAYS AS (IF(task_type='question_gen'
                            AND status IN ('pending','running'), 1, NULL)) STORED,
  ADD UNIQUE KEY uniqi_active_chapter_summary_mysql
    (occ_active_summary, student_id, catalog_id),
  ADD UNIQUE KEY uniq_active_question_gen_mysql
    (occ_active_gen, triggered_by_id, course_id);

-- 7) ai.AIQuotaPolicy：全局默认（user_id IS NULL）最多一行
--    注：OneToOne 已自带 UNIQUE(user_id)，但 MySQL 允许多个 NULL，故必须单列这条
ALTER TABLE ai_aiquotapolicy
  ADD COLUMN occ_global TINYINT
    GENERATED ALWAYS AS (IF(user_id IS NULL, 1, NULL)) STORED,
  ADD UNIQUE KEY uniq_ai_quota_global_default_mysql (occ_global);
```

三条实现注意：

1. **单条 ALTER 同时加列+加索引**在 MySQL 8.0 支持；若某版本报 `3106`，拆成两条语句（先 `ADD COLUMN`，再 `ADD UNIQUE KEY`）即可，语义不变。
2. **组合键中含 NULL 的行互不冲突**（MySQL 唯一索引对 NULL 的处理），与 SQLite 部分唯一索引的 NULL 语义完全一致——所以 `AITask` 的 `student_id`/`catalog_id`/`triggered_by_id` 可空不需要额外 `COALESCE`。
3. **索引长度**：最长单列为 `occ_path` varchar(255)×4B=1020B，加 `course_id` 8B 共 1028B，远低于 InnoDB 3072B 上限。

---

## 附录 C：实施记录（2026-10-30，本地已完成）

### C.1 结果

| 项 | 结果 |
|---|---|
| 目标库 | 本机 MySQL 8.0.36，`zk`（utf8mb4_0900_ai_ci），124 个迁移全建成 |
| 表结构 | 57 表，7 个 `*_mysql` 唯一索引全部就位，字符集全一致 |
| 数据 | 50 张表 / 1517 行搬迁完成；行数、文本指纹、JSON 长度、外键孤儿、自增位全部校验通过 |
| 测试 | **SQLite 712 个全绿 → MySQL 712 个全绿** |
| E2E | `p5_security_check.py` 走独立库 `zk_e2e`：**39/39 PASS**（含并发交卷行锁、限流分级、JWT 吊销） |
| 回切 | `DATABASE_URL=sqlite` 实测可用（20 用户 / 124 迁移），旧库冻结为 `db.sqlite3.pre-mysql-20261030` |

### C.2 实施中被证伪 / 新发现的 4 个问题（均已修）

1. **迁移里的 DDL 不能在事务中执行**
   `migrate` 默认把每个迁移包在 atomic 里，而 MySQL 的 DDL 不可回滚，`schema_editor.execute()` 直接抛
   `TransactionManagementError: Executing DDL statements ... can't perform a rollback`。
   修法：4 个生成列迁移加 `atomic = False`，配合幂等（先查 information_schema）保证中途失败可原地重跑。

2. **Windows 的 `mysql_tzinfo_to_sql` 只读 TZif v1 块**
   现代 tzdata（含 PyPI `tzdata` 包）是 v2/slim，v1 头计数全 0 → 工具生成 `offset=0` 的空时区，
   `CONVERT_TZ` 原样返回。改用自研 `scripts/load_mysql_timezone.py` 直接解析 TZif v2。
   注意 `mysql.time_zone_transition.Transition_time` 是 **bigint（unix 秒）**，不是 TIMESTAMP。

3. **`EXTRA='DEFAULT_GENERATED'` 被误判成生成列**
   搬迁脚本原先按 "GENERATED" 子串过滤，把 JSON 默认值表达式也算进去了，会导致
   `exams_examsubmission.subjective_scores` / `question_layout` / `knowledge_qarecord.context_snapshot`
   整列漏搬（静默丢数据）。改为只认 `STORED GENERATED` / `VIRTUAL GENERATED`，
   并对"源库有值但目标无列"打 `!!` 告警。

4. **内联线程的 `close_old_connections()` 会关掉测试连接**
   `tests_ai_task._InlineThread` 把 AI 任务线程改同步执行，`_run_task` 入口的
   `close_old_connections()` 于是作用到测试自身连接（被 TestCase 的 atomic 包着、autocommit 已关），
   `close_if_unusable_or_obsolete()` 判定不一致直接关连接 → 13 个用例报 `MySQLdb.OperationalError 2006`。
   真线程里拿到的是全新连接、本就不需要清理，故在测试替身里置为空操作（生产代码未动）。

另有两处配套调整：`SILENCED_SYSTEM_CHECKS = ["models.W036"]`（7 条条件约束的告警已由生成列补偿，显式静音避免刷屏误导）；测试期 `CONN_MAX_AGE=0`（消除长跑中按龄关连接的假失败）。

### C.3 时区缓存问题（已闭环）

`mysql.time_zone*` 四张表数据刷入后（598 时区 / 18138 条跃迁），`Asia/Chongqing`、`PRC`、`Asia/Hong_Kong`、`Europe/Paris`、`America/New_York` 均返回正确偏移，唯独 `Asia/Shanghai` 返回 +0。
原因：首次导入（当时是工具生成的 offset=0 空数据）期间探测过这个名字，**MySQL 按名字缓存了那次结果**；
同一个 tz_id 换个别名（`Asia/Shanghai_Probe`）立即返回正确的 +8，证明表数据本身无误。

处置：重启一次 MySQL 服务（服务端缓存只在启动时重建）。重启后验证结果：

| 验证项 | 结果 |
|---|---|
| `CONVERT_TZ('2026-10-30 00:00:00','UTC','Asia/Shanghai')` | `2026-10-30 08:00:00` ✅ |
| Django 生成的 SQL | `DATE(CONVERT_TZ(created_at, UTC, Asia/Shanghai))` ✅ |
| 端到端样本（造一条 `2026-10-15 20:00 UTC`） | 北京日分组 `2026-10-16`、UTC 分组 `2026-10-15`，**正确归到次日** ✅ |
| 真实数据分组对比 | UTC 与北京分组结果一致——因为现有数据没有 UTC≥16 点的记录（实测 0 条），不是偏移失效 |

结论：看板按天统计、督管趋势、导出时间筛选的日界已按东八区正确切分，**无遗留项**。

（备忘：这是 MySQL 服务端按名字缓存时区数据的行为，`FLUSH TABLES` 清不掉，只能重启；换机器/部署 Docker 后重新灌时区不受影响，因为那是首次加载。）

### C.4 日常命令（切换后）

```bash
# 启动后端（默认读 .env 里的 mysql 连接：zk@127.0.0.1:3306/zk）
cd backend && ./venv/Scripts/python.exe manage.py runserver 8005

# 跑测试（用独立 test_zk；--keepdb 免建库权限；改迁移后先 drop test_zk 再跑）
./venv/Scripts/python.exe manage.py test apps.<app> --keepdb

# E2E / 校验脚本走独立库（脚本会拒绝指向 zk / test_zk）
E2E_DATABASE_URL="mysql://zk:zk123456@127.0.0.1:3306/zk_e2e" \
  ./venv/Scripts/python.exe scripts/p5_security_check.py

# 灌时区数据（换机器 / 部署到 Docker 后必做一次）
./venv/Scripts/python.exe scripts/load_mysql_timezone.py --user root --password ***

# 回切 SQLite（两库数据不互通，仅用于对照/回退）
# 改 .env：注释 mysql 行、放开 DATABASE_URL=sqlite
```

---

## 附录 D：生产环境切换记录（192.168.3.145，2026-10-30）

### D.1 环境拓扑（与本地完全不同，先摸清再动手）

| 项 | 实际情况 |
|---|---|
| 应用 | `/data/zhike-v2/`，容器 `zhike_v2_backend` / `zhike_v2_frontend`，对外 8088 |
| 切换前代码 | 镜像 `b6a6fc417859`（2026-10-30 11:41 构建，已含 P4+P5），SQLite **120 迁移** |
| 切换前数据 | `data/db.sqlite3` 144MB：13 用户（含 wgy id=13）/ 8 课程 / 2868 片段 |
| 目标数据库 | `192.10.0.3:3306/zk` = 容器 **`test-mysql80`**（MySQL 8.0.22），在 `bnet-test` 网络 |
| 目标库状态 | `zk` **已存在且 0 张表**；字符集 utf8mb4 / utf8mb4_0900_ai_ci；**时区表已灌好**（1826 条，CONVERT_TZ 正确） |

**关键发现（会卡住整个方案）**：`192.10.0.0/16` 是本机某个 Docker bridge 的网段（网关 192.10.0.1），
所以 `192.10.0.3` 不是外部机器，而是**另一个项目的 MySQL 容器**。宿主机能连、**zhike 容器连不上**（超时）——
因为它只接在 `zhike_v2_net`，跨 bridge 没有路由。
解决：compose 里给 backend 同时挂 `bnet-test`（external），容器重建后自动获得 192.10.0.5，直连数据库。

### D.2 镜像构建的坑（用户问过"是不是很慢"）

`requirements.txt` 从 31 行变成 33 行（加 mysqlclient）→ Docker 的 `COPY requirements.txt` 层失效 →
后面的 `pip install -r requirements.txt` 整层重跑：**重新下载 torch 209MB + 全套依赖**，
而 torch 走 `download.pytorch.org`（国内极慢），日志 5 分钟无进展；apt 的 LibreOffice 也要重装。

采用**第三条路**（不是"全家桶重建"，也不是"本地打包上传"）：

```dockerfile
# deploy/Dockerfile.fast（服务器上保留，不入库）
FROM zhike-v2-backend:p5base          # 现有生产镜像 tag 出来，已含 LibreOffice/字体/torch/全部依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
      default-libmysqlclient-dev build-essential pkg-config \
 && pip install --no-cache-dir mysqlclient==2.2.7 -i https://pypi.tuna.tsinghua.edu.cn/simple \
 && apt-get purge -y build-essential pkg-config default-libmysqlclient-dev \
 && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY . /app
```

**53 秒**构建完成（vs 卡住 15 分钟）。代价：这镜像的底座是旧的完整构建，若将来 `requirements.txt`
新增其他依赖，**必须改回 `Dockerfile.backend` 完整构建**，不能继续用 fast。

> 为什么不用"本地打包镜像上传"：本机 Docker Desktop 未启动；即便启动也要在本机重新拉同样 200MB+ 依赖；
> 现镜像 3.5GB，压缩后约 1GB，5Mbps 上传约 20-25 分钟，不比 fast 构建快。

### D.3 执行步骤（停机约 2 分钟）

1. 备份：`data/backups/db-pre-mysql-20261030-1420.sqlite3`（切换前）、`db-pre-mysql-final-20261030-1435.sqlite3`（停机后定稿）+ `deploy.bak-20261030-1420`
2. 源码：`git archive HEAD backend deploy` 打包上传（1.7MB），解压覆盖；服务器 `.env`、`data/`、`media/` 均不受影响（gitignore）
3. compose：mysql 服务加 `profiles: ["embedded-mysql"]`（默认不启）、backend 去掉 `depends_on`、挂 `bnet-test`
4. 镜像：tag 旧镜像为 `p5base` → `Dockerfile.fast` 构建（53s）
5. **演练**：新建 `zk_rehearsal` → migrate（124 迁移）→ 搬数据 → 校验全绿 → 删库（不碰生产）
6. 停 backend（冻结写入）→ 最终备份 → 对 `zk` 执行 migrate + 搬数据（校验全绿）
7. 改 `.env.production` 的 `DATABASE_URL`（保留 sqlite 行作回滚点）→ `docker compose up -d backend`（重建容器以应用新网络）
8. 冒烟 + 清理

### D.4 验证结果

| 项 | 结果 |
|---|---|
| 容器 | `Up`，网络 `bnet-test=192.10.0.5` / `zhike_v2_net=172.18.0.2` |
| entrypoint | `等待 MySQL 可连接` → `MySQL 就绪（第 1 次尝试）` → `No migrations to apply` → gunicorn 正常 |
| Django 视角 | `vendor=mysql, db=zk, host=192.10.0.3` |
| 数据 | 13 用户（wgy id=13 在位）/ 8 课程 / 2868 片段 / 124 迁移，与源库逐表校验一致 |
| 登录 | `wgy / wgy123147` 200，返回「王国勇 / 教师」，课程列表 2 门 |
| 首页 | 8088 → 200 |
| 停写证据 | SQLite 文件 mtime 停在 13:42（停机时刻），MySQL 表 update_time 14:36 |
| 容器日志 | 无 error / traceback |

### D.5 回滚（1 分钟内）

```bash
cd /data/zhike-v2/deploy
sed -i 's|^DATABASE_URL=mysql.*|DATABASE_URL=sqlite|' .env.production
sudo docker compose up -d backend      # 旧库 data/db.sqlite3 全程未动
```
镜像回滚：`docker tag zhike-v2-backend:p5base zhike-v2-backend:latest && docker compose up -d backend`

### D.6 遗留 / 待办

| 项 | 说明 |
|---|---|
| MySQL 账号 | 当前用 `root/test@2021`（用户指定）。共享实例上建议后续建 `zhike@'192.10.0.5'` 专用账号，只授 `zk.*` |
| `Dockerfile.fast` | 仅存在于服务器，用于本次加速；**新增依赖时必须回到完整构建** |
| 本地 compose 变更 | 加了 `bnet-test`（external）与 mysql profile，服务器与仓库已一致；本地无该网络，用 runserver 开发不受影响 |
| 备份清理 | `data/backups/` 已有 3 份 144MB SQLite（10:21 / 14:20 / 14:35），确认稳定后可删旧的 |
| 生产备份策略 | 从 SQLite `VACUUM INTO` 改为 `mysqldump`，尚未配置定时任务 |

### D.7 备份策略（切换后，已落地）

原脚本是 `VACUUM INTO` 备份 SQLite + media rsync，切库后 SQLite 已冻结，改为 **mysqldump 逻辑备份**。

| 项 | 说明 |
|---|---|
| 备份内容 | `zk` 整库逻辑备份：**建表语句 + 全部数据**（`--routines --triggers` 带上存储过程/触发器，恢复才完整） |
| 一致性 | `--single-transaction`（InnoDB 一致性快照，**不锁表**，业务在线可跑）+ `--quick`（逐行取，不整表进内存） |
| 执行方式 | 宿主机没装 mysql 客户端 → 借 `mysql:8.0` 镜像在 `bnet-test` 网络内跑 mysqldump；密码走 `MYSQL_PWD` 环境变量，不出现在 `ps` 里 |
| 压缩 | gzip，当前 **27MB/份**（144MB 的 SQLite 转成 MySQL 后 JSON 更紧凑） |
| 频率 | **每天 03:30**（凌晨低峰，`crontab -l` 可见） |
| 保留 | **14 天**，`find -mtime +14 -delete` 自动清理；峰值占用约 380MB |
| 三重校验 | gzip 完整性 + 文件非空 + 含建表语句（挡住"连不上库却生成空壳"的假成功） |
| 日志 | 追加到 `/data/zhike-v2/backups/backup.log` |
| media | 仍走 `rsync -a` 增量，**不带 `--delete`**（主目录误删不连带删备份） |
| 恢复验证 | 实测把备份导入临时库 `zk_restore_test`：**57 表 / 13 用户 / 2868 片段**，与生产一致，验证后删库 |

脚本：服务器 `/data/zhike-v2/backups/backup.sh`，仓库留档 `deploy/backup-mysql.sh`（旧 SQLite 版备份为 `backup.sh.sqlite-era`）。

手工恢复（把某天的备份导回 `zk`）：

```bash
zcat /data/zhike-v2/data/backups/mysql/db-20261030.sql.gz \
  | sudo docker exec -i test-mysql80 sh -c 'mysql -uroot -p"test@2021" zk'
```



