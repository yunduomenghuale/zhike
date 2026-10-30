# 数据库从 SQLite 切换到 MySQL —— 排查报告与切换方案

> 编写日期：2026-10-30　　适用版本：当前仓库 HEAD（业务迁移 91 个）
> 排查对象：仓库代码 + 线上库 `/data/zhike-v2/data/db.sqlite3`（192.168.3.145，138MB，94 条迁移记录）
>
> **状态：本文是 v1 排查报告，其中 3 处结论已被证伪。本地切库已按
> `docs/MySQL切换-实施设计与冲突评审.md`（v2，含实施记录附录 C）执行完毕；两文冲突时以 v2 为准。**

---

## 0. 结论摘要（先看这段）

| 项 | 结论 |
|---|---|
| 可行性 | **可行**。业务代码没有裸 SQL、没有 SQLite 专有函数，Django ORM 层迁移成本低 |
| 工作量 | 代码改造 ≈1 天，迁移脚本+预演 ≈2 天，切换窗口 ≈1 小时（停机 30 分钟足够），合计 4~5 人日 |
| 三个"切过去就炸"的 P0 | ① 7 个**条件唯一约束**在 MySQL 上被 Django 静默丢弃（不报错、不建索引）② 2 处 `select_for_update()` 在无事务中调用，SQLite 下是空操作、MySQL 下直接 500 ③ 线上库落后代码 15 个业务迁移，其中 `classroom/0006` 会因 2 名学生的双班归属**中止迁移** |
| 一个"不报错但结果全空"的坑 | `TruncDate`/`__date` 在 MySQL 下依赖时区表 `CONVERT_TZ`，表没装则返回 NULL —— QA 看板、督管趋势、导出时间筛选**静默变空** |
| 最大的隐性风险 | 生产镜像跑的是 10-27 的旧代码（无 `platform_admin/imports.py`、`classroom` 只到 0004），与仓库差 15 个迁移。**切库前必须先把这个版本差补齐**，否则两个变更叠在一起无法定位问题 |
| 建议路线 | 分两步：**先补版本到最新（SQLite 上跑完 26 个迁移）→ 观察稳定 → 再切 MySQL**（切库时零迁移差异）。不建议一步到位 |

---

## 1. 现状排查

### 1.1 当前配置

- `backend/config/settings.py:132-163`：`DATABASE_URL` 只识别 `postgres://` 前缀，其余一律落 SQLite（含 `SQLITE_PATH` 副本机制）。
- 线上 `deploy/.env.production`：`DATABASE_URL=sqlite`。
- `backend/deploy-entrypoint.sh:6-8`：把 `db.sqlite3` 软链到持久卷 `/app/data`，随后 `migrate` + `collectstatic` + gunicorn（2 workers × 2 threads）。
- 无任何 MySQL/MariaDB 驱动依赖（`requirements.txt` 里没有 `mysqlclient`/`PyMySQL`）。

### 1.2 数据规模（生产快照实测）

| 指标 | 值 |
|---|---|
| 库文件 | 138 MB / 55 张表 / 64,852 行 |
| 最大表 | `ai_aicalllog` 61,216 行（线上 61,217） |
| 第二 | `knowledge_knowledgechunk` 2,868 行（**平均每行 20.2 KB，全是 1024 维向量 JSON**，合计约 58 MB） |
| 单条最大 JSON | `courses_teachingvideo.scripts` 266 KB；`courses_pptresource.parsed_pages` 228 KB |
| 迁移记录 | 94 条，落后当前代码 26 个（15 业务 + 11 `token_blacklist`） |

数据量很小，整库搬迁 5 分钟内可完成，不需要停机分批。

### 1.3 代码层与数据库方言的耦合点（全量扫描结果）

扫描了 `cursor.execute` / `.raw()` / `RawSQL` / `extra()` / `PRAGMA` / `json_extract` / `GROUP_CONCAT` / `strftime` / `JSONField` / `UniqueConstraint` / `select_for_update` / `Trunc*` 等 30 余种模式：

**好消息：**
- 业务代码**零裸 SQL**、零 `extra()`，全部走 ORM。
- 零 SQLite 专有函数（`strftime` 只用于 Python 侧 `datetime.strftime` 格式化）。
- `apps/courses/ppt_parser.py:83-110` 的 SQLite 只是**渲染互斥锁文件**（`zhike-render-guard.sqlite`），与业务库无关，切库后继续用，无需改动。
- 无 `DurationField`/`BinaryField`/`ArrayField`/全文检索 `__search`，字符型唯一键最长 64 字符（远低于 utf8mb4 索引 3072 字节上限）。

**需要处理的（按严重度）：**

| # | 位置 | 问题 | MySQL 下的表现 | 等级 |
|---|---|---|---|---|
| 1 | 7 处 `Meta.constraints` 的条件唯一约束 | MySQL 不支持部分索引，Django `_unique_supported()` 判 False → `_unique_sql()` 返回 `None`，**静默跳过，无异常无告警** | 数据库级唯一性凭空消失，并发/异常路径可写出重复数据 | **P0** |
| 2 | `apps/exams/views.py:348-372` `save`（考试暂存） | `select_for_update()` 在**无 `@transaction.atomic`** 中调用 | MySQL 抛 `TransactionManagementError` → 学生**考试中保存答案全部报错** | **P0** |
| 3 | `apps/courses/views.py:39-42`，调用点 `:284` | `_invalidate_teaching_video_for_new_ppt()` 内 `select_for_update()`，外层 `generate_script` 无事务（`:494` 的调用点在事务内，无问题） | 教师换版/强制重生成讲稿时 500 | **P0** |
| 4 | `apps/common/qa_stats.py:238`、`platform_admin/services.py:76/94/100`、`platform_admin/views.py:865`、`oversight_views.py:666-668` | `TruncDate(..., tzinfo=Asia/Shanghai)` 与 `created_at__date__gte` 在 MySQL 上生成 `CONVERT_TZ(col,'UTC','Asia/Shanghai')` | 未装载时区表 → 返回 NULL → **看板/趋势/导出按天统计静默为空**（不报错，最容易被忽略） | **P0** |
| 5 | 线上库 vs 仓库 | 落后 15 个业务迁移；`classroom/0006` 的 `check_single_class()` 遇重复归属直接 `raise RuntimeError` 中止 | 迁移中断（已在副本上实测复现，见 §1.4） | **P0** |
| 6 | `apps/ai/vectorstore.py:96` | 每次问答把整门课所有 chunk（含 20KB 向量）拉进 Python 算余弦 | SQLite 是本地文件读，MySQL 要过网络：2868 行≈58MB/次检索。量再涨会明显拖慢首字响应 | P1 |
| 7 | `apps/courses/tests.py:805-816`、`apps/ai/tests_ai_task.py:40`、`apps/exams/tests_p5.py:135` | 依赖 SQLite 特有行为（文件锁 `sqlite3.OperationalError`、共享缓存内存库 `SQLITE_LOCKED`） | MySQL 下用例失败或语义失效 | P1 |
| 8 | `backend/scripts/p1_permission_matrix.py`、`p4_graduation_check.py`、`p5_security_check.py` | 用 `SQLITE_PATH` 指向库副本 | 切库后校验脚本无法对 MySQL 副本跑 | P1 |
| 9 | `apps/common/qa_stats.py:271`、`platform_admin/views.py:834/1007` | 因"SQLite 无 JSON 聚合/percentile"而用 Python 侧扫描 | 能跑，但 MySQL 8 可用 `JSON_TABLE`/窗口函数下推，属优化项 | P2 |
| 10 | `apps/exams/views.py:418-426` | `except OperationalError` 文案写着"SQLite 写锁竞争" | MySQL 下不会命中，但会把死锁/锁等待超时也归为"提交繁忙"，建议细化 | P2 |

### 1.4 已实测确认的迁移卡口

在**生产快照副本**上执行 `migrate classroom`（未动线上库）：

```
RuntimeError: 存在学生同时占用多个班级的数据，无法建立单班唯一约束。
请先人工指定归属（把其中一条 learn_status 置为 transferred），再重新 migrate：
  学生 hys(id=17) 占: 计算机1班(4)、计科二班(5)
  学生 孟燕姿(id=20) 占: 计科二班(5)、计算机1班(4)
```

两人均于 2026-09-28 通过旧邀请码重复加入两个班，且都是 `active`。按"保留先入班"原则（与今日 P4+P5 部署时已确认的处置一致）：

| 学生 | 先入（保留 active） | 后入（置 `transferred`） |
|---|---|---|
| hys 黄玉钐（17） | 计算机1班（class 4，09-28 13:14） | 计科二班（class 5，09-28 13:43） |
| 孟燕姿（20） | 计科二班（class 5，09-28 13:44） | 计算机1班（class 4，09-28 13:51） |

> ⚠️ **环境口径需先对齐**：当前可访问的主机 `192.168.3.145` 上，后端镜像构建于 2026-10-26、数据库为 10-27 快照（94 条迁移），`classroom` 仅到 `0004`，且不含 `platform_admin/imports.py`；而今日 10:20-11:30 部署的 P4+P5 镜像（`b6a6fc417859`）所在主机已不可达（`124.70.107.64` 拒绝公钥登录）。**切 MySQL 前必须确认目标环境是哪一台**——若沿用已升级到 120 条迁移的那套库，本文 §5 阶段 1 可直接跳过。

### 1.5 排序规则冲突预检（已用生产数据全量跑过）

MySQL 默认 `utf8mb4_0900_ai_ci` 是大小写+重音不敏感，比 SQLite 的 `UNIQUE` 更严格。逐列检查结果：

| 检查项 | 结果 |
|---|---|
| `users.username`（唯一，登录走 `iexact`） | 0 冲突 |
| `users.phone`（唯一，空串已转 NULL） | 0 冲突 |
| `classroom.invite_code` / `labs.token` / `courseresource.access_token` / `platformsetting.key` / `aicapabilityconfig.capability` / `labs_labtemplate.code` | 全部 0 冲突 |
| `courseresource(course,path)` 条件唯一 | 0 冲突 |
| `qasession(course,student,legacy_key)` 条件唯一 | 0 冲突 |
| `classstudent(classroom,student)` | 0 冲突 |

**结论：可以放心使用 `utf8mb4_0900_ai_ci`，不会因排序规则收紧迫使迁移失败。** 注意 `users.username` 中存在中文用户名（`孟燕姿`），中文在 ai_ci 下按码位比较，不受大小写折叠影响。

### 1.6 服务器现状（192.168.3.145，CentOS 8.3，251GB 内存 / 32 核）

- 无端口冲突：现有 MySQL 容器发布在 44318/44319，3306 空闲。
- Docker 镜像本地已有 `mysql:8.0.40 / 8.0.39 / 8.4.11` 等，**不需要联网拉取**（服务器出网仅 ~5Mbps）。
- **磁盘告警：`/` 仅剩 24GB**，MySQL 数据目录也会落在这里。本次预计占用 <2GB（数据 + binlog），但要设 `binlog_expire_logs_seconds` 并监控。

---

## 2. 目标架构与技术选型

```
compose 网络 zhike_v2_net
├── zhike_v2_mysql    mysql:8.0.40   不发布宿主端口，仅内网可达
│    数据卷 ../data/mysql，字符集 utf8mb4 / 排序规则 utf8mb4_0900_ai_ci
├── zhike_v2_backend  Django + gunicorn  DATABASE_URL=mysql://...
└── zhike_v2_frontend nginx  (不变)
```

| 决策项 | 选择 | 理由 |
|---|---|---|
| 版本 | **MySQL 8.0.40** | Django 5.1 官方支持 8.0.11+；镜像已在服务器本地；8.4 虽 LTS 但 Django 5.1 未显式背书，避开 |
| 驱动 | **mysqlclient 2.2.7** | C 实现，bulk 写入（向量片段批量落库）比 PyMySQL 快数倍；备选 PyMySQL 2.2（零系统依赖，构建更简单） |
| 字符集 | `utf8mb4` + `utf8mb4_0900_ai_ci` | 中文/emoji 完整支持；大小写不敏感与现有 `iexact` 语义一致；已用生产数据验证 0 冲突 |
| 事务隔离 | Django 默认 `read committed` | 与现有"行锁串行化交卷"设计匹配，避免 REPEATABLE READ 下的间隙锁死锁 |
| 时区 | 存 UTC（`default-time-zone=+00:00`，`USE_TZ=True` 不变） | 与现状一致；**必须额外装载 MySQL 时区表** |
| 连接 | `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS=True` | 2 worker × 2 thread，长连接减少握手；健康检查防 `wait_timeout` 断连 |

---

## 3. 改造清单（代码级）

### 3.1 `backend/config/settings.py` — 增加 MySQL 分支

在 `:132` 的 `DATABASE_URL` 判断前插入（保留 postgres / sqlite 分支不动，便于回滚）：

```python
if DATABASE_URL.startswith(("mysql://", "mysql2://")):
    from urllib.parse import unquote, urlparse

    parsed = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "127.0.0.1",
            "PORT": parsed.port or 3306,
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "charset": "utf8mb4",
                # Django 若不显式给 init_command 会自行 SET sql_mode='STRICT_TRANS_TABLES'，
                # 这里显式写全，连同 NO_ZERO_DATE 一起钉死，避免服务器侧配置漂移
                "init_command": (
                    "SET sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,"
                    "NO_ENGINE_SUBSTITUTION'"
                ),
            },
            # 测试库也走 utf8mb4，避免 CI 与生产排序规则不一致
            "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_0900_ai_ci"},
        }
    }
```

### 3.2 `backend/requirements.txt`

```python
mysqlclient==2.2.7
```

### 3.3 `deploy/Dockerfile.backend` — 加编译依赖

```dockerfile
    && apt-get install -y --no-install-recommends \
       libreoffice-impress libreoffice-writer \
       fonts-noto-cjk fonts-wqy-microhei fonts-wqy-zenhei \
       fonts-arphic-uming fonts-arphic-ukai \
       default-libmysqlclient-dev build-essential pkg-config \
```

如果希望精简镜像，可在 `pip install` 后追加 `&& apt-get purge -y default-libmysqlclient-dev build-essential pkg-config && apt-get autoremove -y`（保留 `libmariadb3` 运行库）。

### 3.4 `deploy/docker-compose.yml` — 新增 mysql 服务

```yaml
  mysql:
    image: mysql:8.0.40            # 服务器本地已有，无需拉取
    container_name: zhike_v2_mysql
    restart: unless-stopped
    env_file: .env.mysql
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_0900_ai_ci
      - --default-time-zone=+00:00
      - --max-allowed-packet=64M
      - --innodb-buffer-pool-size=1G
      - --slow-query-log=1
      - --long-query-time=1
      - --binlog-expire-logs-seconds=604800   # 7 天，防磁盘被 binlog 吃满
    volumes:
      - ../data/mysql:/var/lib/mysql
      - /usr/share/zoneinfo:/usr/share/zoneinfo:ro   # 供 mysql_tzinfo_to_sql 装载时区表
    # 不发布宿主端口：只经 zhike_v2_net 供 backend 访问
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "--silent"]
      interval: 10s
      timeout: 5s
      retries: 12
    mem_limit: 2g
    networks:
      - zhike_v2_net
```

`backend` 服务追加：

```yaml
    depends_on:
      mysql:
        condition: service_healthy
```

新建 `deploy/.env.mysql`（不入库）：`MYSQL_ROOT_PASSWORD=...`、`MYSQL_DATABASE=zhike_v2`、`MYSQL_USER=zhike`、`MYSQL_PASSWORD=...`，密码用 `openssl rand -base64 24` 生成。

`deploy/.env.production`：

```ini
DATABASE_URL=mysql://zhike:<pwd>@mysql:3306/zhike_v2?charset=utf8mb4
```

### 3.5 `backend/deploy-entrypoint.sh` — 按驱动分支

```sh
case "${DATABASE_URL:-sqlite}" in
  mysql*)
    echo "[entrypoint] MySQL 模式：等待数据库就绪"
    python - <<'PY'
import os, time, sys
import MySQLdb
for i in range(60):
    try:
        MySQLdb.connect(host=os.environ.get("DB_HOST", "mysql"),
                        user=os.environ["DB_USER"], passwd=os.environ["DB_PASSWORD"],
                        db=os.environ["DB_NAME"], connect_timeout=3).close()
        sys.exit(0)
    except Exception:
        time.sleep(2)
sys.exit("[entrypoint] MySQL 60 次重试仍不可用")
PY
    ;;
  *)
    mkdir -p /app/data
    touch /app/data/db.sqlite3
    ln -sf /app/data/db.sqlite3 /app/db.sqlite3
    ;;
esac
```

（若不想在 entrypoint 里解析 DATABASE_URL，可让 compose 额外传 `DB_HOST/DB_USER/DB_PASSWORD/DB_NAME` 四个变量，脚本更简单。）

### 3.6 7 个条件唯一约束的 MySQL 等价实现（P0 核心）

**必须用"生成列 + 普通唯一索引"补齐**，否则 MySQL 上这 7 条数据库级不变量全部消失：

| 模型 | 约束名 | 语义 |
|---|---|---|
| `classroom.ClassStudent` | `uniq_occupied_class_per_student` | 一个学生同时只能占一个班 |
| `courses.CourseResource` | `unique_course_resource_path` | 同课程下预置资源 path 唯一 |
| `courses.Term` | `unique_current_term` | 只能有一个当前学期 |
| `knowledge.QASession` | `uniq_qasession_legacy` | 同课程同学生旧会话键唯一 |
| `ai.AITask` | `uniqi_active_chapter_summary` | 同章节同学生只允许一个在跑的总结任务 |
| `ai.AITask` | `uniq_active_question_gen` | 同教师同课程只允许一个在跑的生成任务 |
| `ai.AIQuotaPolicy` | `uniq_ai_quota_global_default` | 全局默认配额只能有一行 |

写法（每个 app 一个 `RunPython` 迁移，`vendor == "mysql"` 才执行；SQLite/PG 侧保持原生条件索引）：

```python
# apps/classroom/migrations/0008_mysql_partial_unique.py
from django.db import migrations

SQL_UP = [
    """ALTER TABLE classroom_classstudent
         ADD COLUMN occ_student_id BIGINT
           GENERATED ALWAYS AS (CASE WHEN learn_status IN ('active','inactive')
                                     THEN student_id END) STORED,
         ADD UNIQUE KEY uniq_occupied_class_per_student_mysql (occ_student_id)""",
]
SQL_DOWN = [
    """ALTER TABLE classroom_classstudent
         DROP INDEX uniq_occupied_class_per_student_mysql,
         DROP COLUMN occ_student_id""",
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for sql in SQL_UP:
        schema_editor.execute(sql)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    for sql in SQL_DOWN:
        schema_editor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("classroom", "0007_disable_invite")]
    operations = [migrations.RunPython(forwards, backwards)]
```

其余 6 条的生成列表达式：

```sql
-- courses.CourseResource
ADD COLUMN occ_path VARCHAR(255)
  GENERATED ALWAYS AS (IF(path = '', NULL, path)) STORED,
ADD UNIQUE KEY unique_course_resource_path_mysql (course_id, occ_path);

-- courses.Term
ADD COLUMN occ_current TINYINT
  GENERATED ALWAYS AS (IF(is_current = 1, 1, NULL)) STORED,
ADD UNIQUE KEY unique_current_term_mysql (occ_current);

-- knowledge.QASession
ADD COLUMN occ_legacy_key VARCHAR(64)
  GENERATED ALWAYS AS (IF(legacy_key = '', NULL, legacy_key)) STORED,
ADD UNIQUE KEY uniq_qasession_legacy_mysql (course_id, student_id, occ_legacy_key);

-- ai.AITask（两条共用一张表，两个生成列）
ADD COLUMN occ_active_summary BIGINT
  GENERATED ALWAYS AS (IF(task_type='chapter_summary' AND status IN ('pending','running'),
                          1, NULL)) STORED,
ADD COLUMN occ_active_gen BIGINT
  GENERATED ALWAYS AS (IF(task_type='question_gen' AND status IN ('pending','running'),
                          1, NULL)) STORED,
ADD UNIQUE KEY uniqi_active_chapter_summary_mysql
  (occ_active_summary, student_id, catalog_id),
ADD UNIQUE KEY uniq_active_question_gen_mysql
  (occ_active_gen, triggered_by_id, course_id);

-- ai.AIQuotaPolicy
ADD COLUMN occ_global TINYINT
  GENERATED ALWAYS AS (IF(user_id IS NULL, 1, NULL)) STORED,
ADD UNIQUE KEY uniq_ai_quota_global_default_mysql (occ_global);
```

要点：
- **NULL 语义与 SQLite 部分索引一致**（组合键中含 NULL 时 MySQL 视为互不相同，SQLite 同样如此），无需额外处理。
- 生成列对 Django 完全透明：INSERT 显式列名、SELECT 只列模型字段，不会冲突；`makemigrations` 也不会尝试删它。
- 数据搬迁脚本必须**排除 `EXTRA LIKE '%GENERATED%'` 的列**，否则报 3105。
- `Meta.constraints` 原样保留（SQLite 下继续生效），不要删——删了本地 SQLite 的单班约束就没了。

### 3.7 两处 `select_for_update` 事务修复（P0）

```python
# apps/exams/views.py:347  考试暂存
    @action(detail=True, methods=["post"], url_path="save")
    @transaction.atomic          # ← 新增
    def save(self, request, pk=None):
```

```python
# apps/courses/views.py:284  讲稿生成路径
        if force or video.ppt_id != ppt.id:
            # 仅把「重置换版」这段写操作包进事务，绝不把后面的 AI 生成放进来
            with transaction.atomic():
                video.refresh_from_db(fields=["ppt"])
                _invalidate_teaching_video_for_new_ppt(catalog, ppt)
```

> 注意：`generate_script_pages_batched()` 是长耗时 AI 调用（可能 180s），**不能**包进事务，否则会长时间持有行锁。

### 3.8 时区表（P0，部署动作而非代码）

```bash
# 首次初始化后执行一次
sudo docker exec -i zhike_v2_mysql sh -c \
  "mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -uroot -p\$MYSQL_ROOT_PASSWORD mysql"
# 校验（必须返回非 NULL）
sudo docker exec zhike_v2_mysql mysql -uroot -p*** -e \
  "SELECT CONVERT_TZ('2026-10-30 00:00:00','UTC','Asia/Shanghai');"
```

镜像若缺 `/usr/share/zoneinfo`，已通过上面 compose 的只读挂载解决。**这条不做，看板全部按天统计都会是空的。**

### 3.9 测试与校验脚本适配（P1）

- SQLite 专属用例加 `@skipUnless(connection.vendor == "sqlite", ...)`：
  `apps/courses/tests.py:805`（文件锁）、`apps/exams/tests_p5.py:135`（共享缓存并发）、`apps/ai/tests_ai_task.py:40`。
- `scripts/p1_permission_matrix.py` / `p4_graduation_check.py` / `p5_security_check.py`：把 `SQLITE_PATH` 副本机制改为支持 `DATABASE_URL`，或迁移后针对 MySQL 副本库跑（建议后者，正好能验证真实方言差异）。

### 3.10 可选优化（P2，不在本次必做）

`vectorstore.search_chunks` 改为只取两列并限制字段宽度：

```python
rows = chunks.values_list("id", "embedding").iterator(chunk_size=500)
```
再按 id 补取命中片段的展示字段。可把单次问答传输量从 58MB 降到接近同等（向量仍是主体），真正解决要等向量库外置（pgvector/Qdrant），本次不动。

---

## 4. 数据迁移方案

### 4.1 工具

新增 `backend/scripts/sqlite_to_mysql.py`（一次性脚本，不入生产镜像），**原生 SQL 逐表搬**：

为什么不用 `dumpdata/loaddata`：
- `auto_now_add` / `auto_now` 会在 `bulk_create` 时被改成"当前时间"，历史时间戳全丢；
- JSONField 经 `dumpdata` 序列化后体积翻倍，速度慢一个数量级。

为什么不用 ORM 双库搬运：需临时把 `created_at.auto_now_add=False` 打进字段实例，隐蔽且易错。

脚本流程：

1. 读 MySQL `information_schema.columns`，得到每张表的真实列清单（**排除生成列**）与列类型。
2. 读 SQLite `table_info`，按列名取交集，缺列（MySQL 新增、SQLite 没有）填 `DEFAULT`/`NULL`。
3. `SET FOREIGN_KEY_CHECKS=0; SET UNIQUE_CHECKS=0;`
4. 逐表 `cursor.executemany(f"INSERT INTO {t} ({cols}) VALUES ({ph})", batch)`，`batch_size=1000`。
5. 类型映射（SQLite 无类型，只能按 MySQL 列类型回推）：

| MySQL 列类型 | SQLite 值处理 |
|---|---|
| `datetime(6)` / `date` | 原样传字符串 `'YYYY-MM-DD HH:MM:SS.ffffff'`（UTC，与 `USE_TZ` 一致），MySQL 自行解析 |
| `json` | 原样传 JSON 文本，MySQL 校验格式；空值传 `None` |
| `decimal` | `Decimal(str(v))`，防 float 精度漂移（成绩/分数） |
| `tinyint(1)`（布尔） | `bool(v)` → 0/1 |
| 整数/字符串/`text` | 原样 |

6. 恢复 `FOREIGN_KEY_CHECKS=1; UNIQUE_CHECKS=1;`
7. 自增位：InnoDB 在插入显式 PK 后会自动把 `AUTO_INCREMENT` 推到 `max(id)+1`，脚本结尾仍逐表断言 `SHOW TABLE STATUS` 的 `Auto_increment > MAX(id)`。
8. **不搬 `django_migrations`**（MySQL 侧由 `migrate` 自己写入）与 `sqlite_sequence`。
9. `auth_permission` / `django_content_type`：先清空 `migrate` 自动生成的行，再按源库 ID 导入，保证 `auth_user_user_permissions` 等引用一致（两边迁移序列相同，ID 本应天然一致，清空重导是为兜底）。

### 4.2 迁移顺序

```
备份 → 副本上修 2 例归属 → 副本上 migrate 到最新（SQLite 侧验证）
     → MySQL 空库 migrate（26 个迁移全跑）
     → 生成列迁移（0008 系列）
     → 搬数据 → 校验 → 切换
```

MySQL 侧从**空库全量 migrate**，而不是"复制表结构"——保证 `django_migrations` 与代码完全对齐，后续 `migrate` 幂等。

---

## 5. 切换执行手册

### 阶段 0：必须先拍板的 4 件事（阻塞项）

1. **切库的目标环境是哪一台？** 目前 `192.168.3.145:8088`（旧镜像 + 10-27 数据，94 条迁移）可访问；今日部署到 `124.70.107.64` 的 P4+P5 版本已不可达。目标库决定阶段 1 是否还需要补版本。
2. **两名学生归属**：沿用"保留先入班"（hys→计算机1班、孟燕姿→计科二班，各把后入置 `transferred`）是否认可？脚本只改状态并写 `status_note` 留痕，不替业务做决定。
3. **是否同意"先补版本、再切库"两步走？**（推荐；若目标环境已是 120 条迁移，则阶段 1 自然跳过）
4. **停机窗口**：建议工作日晚间，30 分钟（预计实际 10 分钟内完成）。

### 阶段 1：补版本（在 SQLite 上，独立于 MySQL）

```bash
# 1) 线上库冷备（停容器后 cp，保证一致）
sudo docker stop zhike_v2_backend
cp /data/zhike-v2/data/db.sqlite3 \
   /data/zhike-v2/data/db.sqlite3.bak-$(date +%Y%m%d-%H%M)
# 2) 按拍板结果修正 2 例归属（改 transferred，写 status_note 留痕）
# 3) 起新镜像，entrypoint 自动 migrate；观察 classroom/0006 通过
# 4) 冒烟：登录 / 班级学生列表 / 学籍门控 / 导入向导
```

完成后线上应为 120 条迁移记录、代码为当前仓库版本，稳定观察 2~3 天后进入阶段 2。

### 阶段 2：MySQL 预演（不碰线上）

在**开发机**用同一份生产快照跑通全链路：起 MySQL 容器 → migrate → 搬数据 → 跑校验 → 跑 E2E。预演通过率 100% 才进阶段 3。

### 阶段 3：正式切换（停机 30 分钟）

```bash
# 1) 冻结写入
sudo docker stop zhike_v2_backend

# 2) 备份 SQLite（同阶段 1），并记录 md5
md5sum /data/zhike-v2/data/db.sqlite3

# 3) 起 MySQL（首次建库，root 密码来自 .env.mysql）
cd /data/zhike-v2/deploy && sudo docker compose up -d mysql
sudo docker compose ps mysql          # 等 healthy

# 4) 装载时区表（只需一次）
sudo docker exec -i zhike_v2_mysql sh -c \
  "mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -uroot -p\$MYSQL_ROOT_PASSWORD mysql"
# 校验 CONVERT_TZ 非 NULL

# 5) 建库表 + 生成列约束
#    在容器内执行（镜像已含 mysqlclient）
sudo docker run --rm --network zhike_v2_net \
  --env-file .env.production -e DATABASE_URL=mysql://... \
  -v /data/zhike-v2/data:/app/data \
  zhike-v2-backend python manage.py migrate --noinput

# 6) 搬数据（在临时容器里跑脚本，源库只读挂载）
sudo docker run --rm --network zhike_v2_net --env-file .env.production \
  -v /data/zhike-v2/data:/app/data:ro \
  zhike-v2-backend python scripts/sqlite_to_mysql.py \
    --source /app/data/db.sqlite3 --dry-run     # 先演练报告
# 确认后去掉 --dry-run 正式搬

# 7) 校验（见 §6），全部通过才继续

# 8) 起后端（新镜像 + DATABASE_URL 指向 mysql）
sudo docker compose up -d backend
sudo docker compose logs -f backend | tail -30

# 9) 冒烟，通过后解冻
```

### 阶段 4：切换后 7 天

- 每日 `mysqldump --single-transaction --routines --triggers` 到 `/data/zhike-v2/backup/`，保留 7 份。
- 打开慢查询日志观察 `long_query_time=1` 的语句（重点看 `vectorstore` 全表读）。
- SQLite 原库与旧镜像 `zhike-v2-backend:pre-mysql` 保留 30 天再清理。

---

## 6. 校验清单（缺一不可）

**结构类**

```sql
-- 字符集/排序规则
SELECT table_name, table_collation FROM information_schema.tables
 WHERE table_schema='zhike_v2' AND table_collation <> 'utf8mb4_0900_ai_ci';   -- 应为 0 行

-- 时区表
SELECT CONVERT_TZ('2026-10-30 00:00:00','UTC','Asia/Shanghai');               -- 非 NULL

-- 7 个生成列唯一索引全部存在
SELECT DISTINCT index_name FROM information_schema.statistics
 WHERE table_schema='zhike_v2' AND index_name LIKE '%_mysql';
-- 期望：uniq_occupied_class_per_student_mysql / unique_course_resource_path_mysql /
--       unique_current_term_mysql / uniq_qasession_legacy_mysql /
--       uniqi_active_chapter_summary_mysql / uniq_active_question_gen_mysql /
--       uniq_ai_quota_global_default_mysql

-- 外键孤儿（抽查关键链路）
SELECT COUNT(*) FROM classroom_classstudent cs
  LEFT JOIN users_user u ON u.id=cs.student_id WHERE u.id IS NULL;             -- 0
SELECT COUNT(*) FROM knowledge_knowledgechunk k
  LEFT JOIN courses_course c ON c.id=k.course_id WHERE c.id IS NULL;           -- 0

-- 自增位
SELECT table_name, auto_increment FROM information_schema.tables
 WHERE table_schema='zhike_v2' AND auto_increment IS NOT NULL LIMIT 10;       -- 均 > max(id)
```

**数据类**

| 校验 | 方法 | 通过标准 |
|---|---|---|
| 逐表行数 | 脚本对比 55 张表 `COUNT(*)` | 全等 |
| 关键表内容指纹 | 对 `users/users.password`、`questions_question.stem`、`exams_examsubmission.answers` 按 id 排序取 sha256 | 全等 |
| JSON 完整性 | `SELECT COUNT(*) FROM knowledge_knowledgechunk WHERE NOT JSON_VALID(embedding)` | 0 |
| 向量条数 | `SELECT COUNT(*) FROM knowledge_knowledgechunk WHERE JSON_LENGTH(embedding)=1024` | 与源库 1024 维行数相等 |
| 成绩汇总 | 各考试 `SUM(score)`、作业平均分 | 与源库差 < 0.01 |
| 密码可用 | 用 admin 真实密码走登录接口 | 200 且发 token |
| 时间戳未漂移 | 抽 `users_user.date_joined`、`ai_aicalllog.created_at` 各 5 条 | 与源库逐字相等 |

**功能冒烟（E2E）**

登录 → 章节树 → 讲稿生成（含换版重置）→ 学生连播进度 → QA 提问（引用来源）→ 考试**开考/暂存/交卷** → 作业提交附件 → 实验三入口 → 班级学习数据导出 xlsx → 管理端 QA 看板（**重点看趋势图日期分组是否为空**）→ 督管概览。

> 其中"考试暂存"和"讲稿换版重置"是本次两处事务修复的直接命中点，必须单独点测。

---

## 7. 回滚方案

| 阶段 | 回滚动作 | 数据损失 |
|---|---|---|
| 阶段 1（补版本，SQLite） | 停容器 → 还原 `db.sqlite3.bak-*` → 回滚镜像 tag | 版本升级期间产生的数据（若有） |
| 阶段 3 切换中（未解冻写入） | `DATABASE_URL` 改回 `sqlite` → 重建 backend | **零损失**（期间禁写） |
| 切换后 7 天内 | 需反向导出 MySQL→SQLite（脚本另一方向，约半天开发）；或接受切换窗口内新数据丢失 | 视导出范围 |

因此**切换窗口内必须保持后端停机**，这是"零损失回滚"的前提。

---

## 8. 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 生成列方案漏掉某个写入路径 | 低 | 出现重复数据 | 7 条约束全部补齐 + 并发用例覆盖；服务层单入口（`classroom/services.py`）已存在 |
| 时区表未装/装失败 | 中 | 看板按天统计全空，且**不报错** | 校验 SQL 强制断言 `CONVERT_TZ` 非 NULL，纳入切换 checklist |
| `ONLY_FULL_GROUP_BY` 与某处 `.values().annotate()` 冲突 | 中低 | 个别报表接口 500 | 预演阶段跑全量 E2E 即可暴露；必要时 `init_command` 里临时去掉该模式 |
| 考试交卷从"无锁"变"真行锁"，并发下 `innodb_lock_wait_timeout`（默认 50s）拖长请求 | 低 | 极端并发交卷变慢 | 交卷本就串行化，量级（单场 <100 人）无压力；监控慢查询 |
| 磁盘 24GB 余量被 binlog/备份吃满 | 中 | MySQL 拒绝写入 | `binlog_expire_logs_seconds=604800`、`max-binlog-size=256M`、每日备份保留 7 份并加磁盘告警 |
| 服务器为多项目共用（40+ 容器），资源争抢 | 中 | 偶发慢查询 | `mem_limit: 2g`、`innodb_buffer_pool_size=1G`，避开业务高峰切换 |
| 搬运脚本把 JSON 写坏 | 低 | 问答/讲稿数据不可用 | `JSON_VALID` 全量校验 + 干跑模式报告 |

---

## 9. 待拍板事项（回复这 4 条即可开工）

1. **目标环境**：切 `192.168.3.145` 这套（旧镜像 + 10-27 数据，需先补 26 个迁移），还是等 P4+P5 那套库恢复/迁移过来后再切？
2. **两名学生归属**：认可"保留先入班"（hys→计算机1班、孟燕姿→计科二班）吗？
3. **MySQL 版本**：确认用 `mysql:8.0.40`（服务器本地已有镜像，零下载）？
4. **停机窗口**：建议本周内任一晚 20:00-21:00，是否可行？

---

## 附录 A：本次排查覆盖范围

- `backend/config/settings.py`（数据库/时区/缓存/静态媒体配置）
- `backend/apps/*/models.py` 全部 45 个业务模型（字段类型、唯一约束、索引、排序）
- `backend/apps/*/migrations/*.py` 91 个迁移（RunPython 数据迁移逐个核对）
- `backend/apps/*/views.py`、`services.py`、`vectorstore.py`、`qa_stats.py`、`export.py`、`access.py`
- `deploy/Dockerfile.backend`、`docker-compose.yml`、`.env.production`、`deploy-entrypoint.sh`
- `backend/scripts/*.py` 校验脚本、`backend/apps/*/tests*.py` 中与 SQLite 强绑定的用例
- 生产快照 55 张表全量数据（排序规则冲突、超长字段、JSON 体积、重复键、迁移状态）

## 附录 B：排查中发现的独立问题（与 MySQL 无关，但建议同期处理）

1. **版本口径不一致**：可访问的 `192.168.3.145` 上镜像是 10-26 构建、库是 10-27 快照（94 条迁移），缺 `platform_admin/imports.py`（P2 导入向导）、`classroom` 仅到 `0004`；而今日 10:20-11:30 部署的 P4+P5 镜像在 `124.70.107.64`，该机现已拒绝登录。**建议先厘清"哪一套是主"，再谈存储切换**，否则切完 MySQL 可能切的是旧版本数据。
2. `apps/exams/views.py:418` 的 `except OperationalError` 注释与文案仍指向 SQLite 写锁，MySQL 下会把锁等待超时也归为"提交繁忙"，建议改为区分 `IntegrityError` / 死锁（1213）/ 锁等待超时（1205）。
3. `apps/common/models.py:7` 文档注释仍写"可平滑迁移到 PostgreSQL"，与本次 MySQL 决策不符，顺手更正。
