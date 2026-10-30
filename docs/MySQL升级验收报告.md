# MySQL 升级验收报告

> 日期：2026-10-30　　环境：本地开发库（MySQL 8.0.36，`zk` / E2E 库 `zk_e2e`）
> 对照基线：同一份业务数据的 SQLite（`db.sqlite3.pre-mysql-20261030`，185 片段 / 20 用户 / 124 迁移）
> 结论：**通过**。四层证据全绿，发现并修复 1 处缺陷，无阻断项。

---

## 1. 结论摘要

| 层次 | 内容 | 结果 |
|---|---|---|
| L1 单元测试 | 712 个用例（12 个 app） | **712/712 通过**（SQLite 与 MySQL 各跑一遍，均全绿） |
| L2 阶段校验脚本 | P1 权限矩阵 64 断言 / P4 学籍与毕业 41 断言 / P5 安全 39 断言 | **64/64、41/41、39/39**，全部在 MySQL 独立库上跑 |
| L3 专项验收 | 新增 57 项，覆盖 8 类 MySQL 特有风险面 | **57/57 通过** |
| L4 性能基线 | 9 个关键场景，SQLite vs MySQL 同数据量 | 中位数比 0.70x~2.03x，**无超阈值项**（阈值 3x） |

修复缺陷 1 处：**作业重复提交返回 500**（既有问题，非 MySQL 引入，本次顺手修掉）。

---

## 2. 覆盖矩阵

### 2.1 L1 单元测试（712 个）

12 个 app 全量：`classroom / courses / exams / knowledge / ai / questions / homework / labs / users / platform_admin / analytics / common`。

同一个套件分别在两组配置下跑过：

- `DATABASE_URL=sqlite` → 712 OK（改动前后各一次，确认无回归）
- MySQL（`test_zk`，`--keepdb`）→ 712 OK

> 说明：MySQL 侧首次跑出现 13 个 `OperationalError 2006`，根因是 `tests_ai_task._InlineThread`
> 把 AI 任务线程改同步执行后，`close_old_connections()` 落到测试自身连接上把它关掉
> （生产里是新线程的新连接，不存在此问题）。已在测试替身里置空并加注释，非生产代码改动。

### 2.2 L2 阶段校验脚本（MySQL 独立库 `zk_e2e`）

| 脚本 | 断言数 | 结果 | 覆盖要点 |
|---|---|---|---|
| `p1_permission_matrix.py` | 64 | 64/64 | 4 角色 × 8 动作权限矩阵、教师导出 xlsx、督管班级/教师列表 |
| `p4_graduation_check.py` | 41 | 41/41 | 整班毕业/撤销、学籍门控六入口、统计分母口径、转班后历史课业 |
| `p5_security_check.py` | 39 | 39/39 | Mock 回退显性化、并发交卷行锁、JWT 吊销、限流分级、TLS 就绪件 |

E2E 库由开发库克隆（`mysqldump ... | mysql ...`），脚本自建 `P1/P4V/P5V` 前缀夹具并清理。

### 2.3 L3 专项验收（`scripts/mysql_upgrade_check.py`，57 项）

| 组 | 项数 | 关注点 | 关键结论 |
|---|---|---|---|
| G1 认证 | 5 | 登录/刷新/匿名 401/学生访问管理端 403 | JWT 吊销查库正常 |
| G2 课程章节 | 4 | 列表、章节树、学生可见范围 | `distinct()`+join 正常 |
| G3 考试 | 12 | 开考/暂存/交卷/重复交卷/成绩发布可见性 | **暂存（`select_for_update` 事务修复）200 且落库** |
| G3b 并发交卷 | 3 | 两线程同时提交同一答卷 | 结果 `[200, 400]`，**只成功一次**，无 500 |
| G4 作业 | 5 | 列表/提交/重复提交/批改/成绩可见 | 重复提交 400（修复前 500） |
| G5 向量检索 | 8 | 自召回、跨课程隔离、问答落库、空问题 | **自召回相似度 1.0000**（JSON 向量读写无损）、`cited_chunks` 为合法数组 |
| G6 统计导出 | 7 | 看板按天趋势、时区日界、xlsx 导出、班级统计、督管概览 | **UTC 20:00 记录归到北京次日**，看板 daily 出现 2026-10-16 |
| G7 分页检索 | 5 | 分页、中文搜索、大小写不敏感、排序 | `Java`/`java` 命中数一致（ci 排序规则符合预期） |
| G8 约束稳定性 | 5 | 重复入班、单班约束、AI 任务防双跑、连续请求 | 两条**生成列唯一索引**在真实写入路径上拦住重复；60 次连续请求 0 个 5xx |

### 2.4 L4 性能基线（`scripts/perf_baseline.py`，中位数 of 5）

| 场景 | SQLite (ms) | MySQL (ms) | 倍数 |
|---|---|---|---|
| 登录（JWT 签发） | 186.5 | 175.3 | 0.94x |
| 课程列表 | 13.5 | 9.4 | 0.70x |
| 章节树 tree=1 | 12.8 | 9.6 | 0.75x |
| 题库分页 20 条 | 41.7 | 46.0 | 1.10x |
| 题库搜索(icontains) | 32.1 | 36.9 | 1.15x |
| **向量检索 top5（读全部片段向量）** | 122.5 | **249.0** | **2.03x** |
| 班级学习统计 | 18.6 | 21.2 | 1.14x |
| 平台 QA 看板（按天聚合） | 26.6 | 28.2 | 1.06x |
| 班级数据导出 xlsx | 69.3 | 78.7 | 1.14x |

判定：全部 ≤ 3x 阈值。

- **唯一显著回归是向量检索（+126ms）**，原因明确：`search_chunks` 每次把整门课片段的
  embedding（每行约 20KB JSON，本库 146 行 ≈ 3MB）读进 Python 算余弦，SQLite 是本地文件读，
  MySQL 要走 TCP + 协议解析。
- 实测优化空间有限：改成 `values_list("id", "embedding")` 只降 17%（195→161ms），
  因为瓶颈是数据体积而非列宽；而 `search_chunks` 需要完整对象做引用展示，改动收益不划算。
  **建议保持现状**，等片段数上万再上外置向量库（pgvector/Qdrant）。
- 绝对值 249ms 对问答体验影响可接受：后面还有 LLM 调用（秒级）。

---

## 3. 本轮发现并修复的缺陷

### 3.1 作业重复提交返回 500（既有缺陷，非 MySQL 引入）

- 现象：同一学生对同一作业二次 `POST /api/homework-submissions/` → `IntegrityError` →
  500 纯文本响应。前端重复点击、网络重试都会触发。
- 根因：`HomeworkSubmissionViewSet.create` 未做重复校验，靠 `unique_together(homework, student)`
  兜底，异常未被转换。
- 修复：`apps/homework/views.py` 在归属校验后前置查一次，返回 400「该作业已提交过，不能重复提交」；
  并发下仍可能撞约束，由事务回滚兜底（不会写脏数据）。
- 回归：`apps.homework` 22 个用例全绿；专项验收 G4 断言由「非 5xx」收紧为「400」。

### 3.2 其他验证中确认无问题的点（曾怀疑）

| 曾担心 | 实测 |
|---|---|
| `exclude(embedding=[])` 在 MySQL 上可能静默过滤掉全部片段 | 185/185 命中，检索正常 |
| `TruncDate` 依赖时区表，缺失会静默返回 NULL | 时区表已灌，`CONVERT_TZ` 正确，日界按东八区切 |
| 条件唯一约束在 MySQL 被 Django 静默丢弃 | 生成列唯一索引已补齐，实测拦住重复写入 |
| 排序规则收紧导致 uniqueness 冲突 | 迁移前全量预检 0 冲突，迁移顺利 |

---

## 4. 未覆盖 / 已知限制（上线前需知）

| 项 | 说明 | 影响 |
|---|---|---|
| **生产服务器未切库** | 192.168.3.145 仍是旧镜像 + SQLite 数据（94 迁移），部署件已就绪但未验证 | 本次验收只覆盖本地 |
| **并发规模未压测** | 只做了 2 线程交卷、60 次连续请求；未做 50+ 并发、长时间 soak | 生产 2 worker 场景下预期无问题，但无数据 |
| **真实 AI provider 未参与** | 验收时 AI 全部切 mock，避免计费/不稳定 | 真实调用链路在切库前已跑通，本次不重复验证 |
| **大数据量未模拟** | 库只有 1517 行 / 185 片段；未验证 10 万行的查询计划 | 向量检索已给出 2x 基线，量大需外置向量库 |
| **MySQL 备份/恢复演练** | 未做 `mysqldump` 恢复演练 | 部署阶段补 |
| **时区缓存坑** | MySQL 按名字缓存时区数据，改了 `mysql.time_zone*` 必须重启服务 | 已写入部署清单 |

---

## 5. 复跑方式

```bash
cd backend

# L1 单测（MySQL，独立 test_zk）
./venv/Scripts/python.exe manage.py test apps.<app> --keepdb

# L2 阶段校验（独立库，脚本拒绝指向 zk 主库）
E2E_DATABASE_URL="mysql://zk:zk123456@127.0.0.1:3306/zk_e2e" \
  ./venv/Scripts/python.exe scripts/p1_permission_matrix.py
E2E_DATABASE_URL="mysql://zk:zk123456@127.0.0.1:3306/zk_e2e" \
  ./venv/Scripts/python.exe scripts/p4_graduation_check.py
E2E_DATABASE_URL="mysql://zk:zk123456@127.0.0.1:3306/zk_e2e" \
  ./venv/Scripts/python.exe scripts/p5_security_check.py

# L3 专项验收（8 组 57 项）
E2E_DATABASE_URL="mysql://zk:zk123456@127.0.0.1:3306/zk_e2e" \
  ./venv/Scripts/python.exe scripts/mysql_upgrade_check.py

# L4 性能基线（两次对照）
DATABASE_URL=sqlite ./venv/Scripts/python.exe scripts/perf_baseline.py --label sqlite
./venv/Scripts/python.exe scripts/perf_baseline.py --label mysql
```

> E2E 库需先克隆开发库（脚本依赖 `t101`/`admin` 等真实账号）：
> `mysqldump -uzk -p --single-transaction --set-gtid-purged=OFF zk | mysql -uzk -p zk_e2e`
> 注意 Windows 下导入要加 `--binary-mode=1 --default-character-set=utf8mb4`，
> 否则 dump 里的 `\'` 会被当命令解析（`Unknown command '\''`）。
