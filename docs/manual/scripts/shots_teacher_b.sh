#!/bin/bash
# 教师端 B：题库/作业/考试（T12-T24）
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_teacher_b.log"
mkdir -p "$OUT/teacher"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

do_login t101 pass1234

# 题库
run open "$BASE/teacher/courses/7/questions" >>"$LOG" 2>&1; wait_page; wait_table; shot "teacher/T12-questions.png"
try_click "新建题目"; wait_dialog; shot "teacher/T13-question-create.png"; close_dialog
try_click "导入题目"; wait_dialog; shot "teacher/T14-question-import.png"; close_dialog
try_click "AI 生成|AI生题"; wait_dialog; shot "teacher/T15-question-aigen.png"; close_dialog

# 作业
run open "$BASE/teacher/courses/7/homework" >>"$LOG" 2>&1; wait_page; wait_table; shot "teacher/T17-homework.png"
try_click "发布作业|新建作业"; wait_dialog; shot "teacher/T18-homework-create.png"; close_dialog
# T19 批改：作业1 的提交（先试列表行按钮）
click_row_btn "作业1" "批改|提交|统计|查看"; wait_dialog
shot "teacher/T19-homework-grading.png"; close_dialog
run open "$BASE/teacher/courses/7/homework/49/stats" >>"$LOG" 2>&1; wait_page; shot "teacher/T20-homework-stats.png"

# 考试
run open "$BASE/teacher/courses/7/exams" >>"$LOG" 2>&1; wait_page; wait_table; shot "teacher/T21-exams.png"
try_click "新建考试"; wait_dialog; shot "teacher/T22-exam-create.png"; close_dialog
run open "$BASE/teacher/courses/7/exams/26/stats" >>"$LOG" 2>&1; wait_page; shot "teacher/T23-exam-stats.png"

run close >>"$LOG" 2>&1
echo "TEACHER_B_DONE"
