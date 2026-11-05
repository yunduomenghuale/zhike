# Stage 1 证据：数据模型 + 迁移 + null 安全 + 报告双分支

> 日期：2026-11-05　分支：feature/ai-queue　前置：Stage 0 已完成（eaa021c/fd8589a）

## 一、改动摘要

| 文件 | 改动 |
| --- | --- |
| `backend/apps/labs/models.py` | `Lab.template` 改 nullable/blank；新增 `PageSource`（template/custom）、`page_source`/`report_note`/`last_debug`；`effective_standard_minutes`/`effective_random_config` 改 null 安全（无模板兜底 30/{}}）；新增 `LabPage`（OneToOne→Lab `custom_page`、kind/entry/original_name/size/sha256/uploaded_by、`_lab_page_path` 存 `lab_pages/{lab_id}/{uuid}.html`）；`LabSubmission` 新增 `grading_source`/`grade_raw`/`grade_raw_digest`/`graded_at` |
| `backend/apps/labs/migrations/0006_lab_custom_page_grading.py` | makemigrations 自动生成（AlterField template + 7 AddField + CreateModel LabPage），无 RunPython，存量行由默认值覆盖 |
| `backend/apps/labs/gate.py` | 硬引用修复①：`_lab_page_relpath` 对 `template_id=None` 返回 None，`read_page` 优雅返回 None（custom 门控三分流属 Stage 2，本期门控页返回 404 友好页不崩） |
| `backend/apps/labs/views.py` | 硬引用修复②：`bridge_validate` 的 `lab.template.code` 兜底 `custom-{lab.id}`、`expected` 无模板时 `{}`，响应补 `page_source`；`publish` 加页面来源前置校验（custom 必须先有 `custom_page`，template 必须绑定模板） |
| `backend/apps/labs/serializers.py` | 硬引用修复③：`template_code/template_title/page_url` 三个 source 穿透字段改 SerializerMethodField（None 安全）；`validate()` 双分支（custom 清 template / template 强制要求模板）；`LabSubmissionSerializer` 新增 `grading_source/grade_raw_digest/graded_at` 字段 + `grade_raw` SerializerMethodField 角色裁剪（教师/平台管理员可见，学生 `None`，C8） |
| `backend/apps/labs/report_generator.py` | 硬引用修复④：报告文件名 `template.code` 兜底 `custom-{lab.id}`；`build_report_context` 加 `score_mode`（external/steps）；**双分支**：external 下步骤清单输出「（不适用：自定义实验，平台不记录步骤明细）」、评分明细只出「总分 / 满分 + 用时」，docx 与 pdf 两处 `/80 /5 /5 /10` 硬编码均走 steps 分支 |
| `backend/apps/labs/tests.py` | 新增 `LabCustomModelTest` 3 用例（见下） |

**偏离说明**：执行方案 Stage 1 改动清单未显式列 `publish` 前置校验，但设计文档 §五（入库版 line 227）明确「publish 前置校验：custom 必须有 custom_page；template 必须 template 不为空」，且 Stage 1 验收要求「无模板 lab 走完创建→发布全链路」，故一并实现并单测覆盖（发布前无页面 400）。

## 二、命令与输出（真实执行，落文件）

1. `makemigrations labs -n lab_custom_page_grading` → 生成 0006（9 项操作）。输出：`stage1-makemigrations.log`。
2. 本地 `migrate labs` → `Applying labs.0006_lab_custom_page_grading... OK`。`makemigrations --check --dry-run` → `No changes detected` exit 0。输出：`stage1-migrate-local.log` / `stage1-migrate-check.log`。
3. 本地单测 `manage.py test apps.labs --keepdb -v 2` → **Ran 13 tests in 3.034s，OK**（存量 10 + 新增 3 全绿；首次跑发现 `bytes` 字面量含中文 SyntaxError，改 str.encode("utf-8") 后通过——现象/原因/修法已记录）。输出：`stage1-unit.log`。
   - 新增用例：`test_custom_lab_full_chain_no_template`（创建→发布校验→传页模型→发布→start→bridge-validate→external 成绩写入→grade_raw 教师可见/学生 None→结论→生成报告→**docx 用 python-docx 真实打开**断言「总分：86.5 / 100」「用时：12 分钟」、无「基础分」、步骤标「不适用」；**pdf 用 pypdf 真实解析**断言含「总分」不含「基础分」；文件名含 `custom-{id}`）；`test_template_mode_still_requires_template`；`test_custom_lab_clears_template_on_create`。
4. 存量回归 `manage.py test apps.analytics apps.classroom --keepdb` → **Ran 87 tests，OK**。输出：`stage1-regression.log`。
5. 本地后端重启冒烟：8005 `/api/labs/` 200，序列化含 `page_source`/`report_note`/`last_debug` 新字段，存量实验 `template_code` 等照常返回。
6. **8092 部署**（bind mount，无 compose build）：7 个文件传 /tmp → sudo 备份旧文件至 `/data/zhike-queue-verify/backups/stage1-src-20261105_170341` → sudo 覆盖 + chown，md5 校验一致；`migrate labs` → 0006 OK；`docker restart zhike_qv_backend zhike_qv_worker`（compose restart 首试无输出未生效，改用 docker restart 确认 Up 11 seconds）。
7. 8092 验证：`django_migrations` 含 `labs/0006`（applied 2026-11-05 09:03:58）；`labs_lab` 存量 1 条（template/published）无损；test_admin 访问 `/api/labs/`、`/api/lab-submissions/`、`/api/lab-templates/` 全 200；班级导出 `/api/analytics/class/1/export/` 200（12KB xlsx，PK 魔数正确）；真实浏览器冒烟 **7/7 ALL_PASS**（test_admin 实验管理页 + B2204011 门控页，LabBridge 注入、步骤渲染、无控制台错误）。输出：`stage1-8092-smoke.log`；截图 `test/screenshots/stage1-8092-admin-labs.png`（教师列表：实验一已发布、排课「计算机一班·立即开放～不限制」）、`stage1-8092-student-gate.png`（学生门控页：拓扑图 + 步骤 1–14 渲染完整）。

### 调试记录（现象 → 原因 → 修法）

| # | 现象 | 原因 | 修法 |
| --- | --- | --- | --- |
| 1 | 新测试导入崩 `SyntaxError: bytes can only contain ASCII literal characters` | Python bytes 字面量不允许非 ASCII（测试 HTML 含中文） | HTML 定义改 str，使用处 `.encode("utf-8")` |
| 2 | SFTP 直写 `/data/zhike-queue-verify/backend/...` 全部 `Permission denied` | 目标文件属 root（容器映射 uid 写入历史），lymatrix2020 无权覆盖 | 先传 /tmp，ssh sudo 备份→覆盖→chown 197609:197121，md5 校验 |
| 3 | `compose -f restart backend worker` 后容器仍 Up 29 hours | 管道吞输出且 restart 未生效（原因未深究，直接换确定路径） | 改用 `sudo docker restart zhike_qv_backend zhike_qv_worker` 并 `docker ps` 确认 Up 秒级 |

## 三、逐条验收结论

| 门槛 | 结论 |
| --- | --- |
| 本地 + 8092 零 500 | ✅ labs/submissions/templates/export 全 200；浏览器 7/7 |
| `0006` 两库均已应用 | ✅ 本地 zk + 8092 zk_queue_verify（django_migrations 可查） |
| 报告双分支目检通过 | ✅ docx（python-docx 打开）与 pdf（pypdf 解析）均只出总分+用时、无步骤表、无 /80 /5 /5 /10 |
| 预置实验零回归 | ✅ LabGateTest 4 用例 + LabFlowTest 3 + LabReportTest 1 全绿；8092 预置实验门控页渲染与 Stage 0 一致 |
| makemigrations --check 零输出 | ✅ |

**结论：Stage 1 验收全绿，允许进入 Stage 2。**
