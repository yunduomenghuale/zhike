#!/bin/bash
# 教师端 C：资源/实验/学情/班级/问答质量（T25-T34）
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_teacher_c.log"
mkdir -p "$OUT/teacher"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

do_login t101 pass1234

# 教学资源
run open "$BASE/teacher/courses/7/resources" >>"$LOG" 2>&1; wait_page; shot "teacher/T25-resources.png"
click_row_btn "" "预览|播放|查看"; sleep 2; shot "teacher/T26-resource-viewer.png"
run eval "history.back()" >>"$LOG" 2>&1 || true

# 虚拟实验
run open "$BASE/teacher/courses/7/labs" >>"$LOG" 2>&1; wait_page; shot "teacher/T27-labs.png"

# 学习统计（整页）
run open "$BASE/teacher/courses/7/analytics" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<70;i++){if(document.querySelectorAll('canvas').length>0 && !document.querySelector('.el-loading-mask')) return 'CHART_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'CHART_TIMEOUT'})()" "CHART_"
shotfull "teacher/T28-analytics.png"
try_click "章节总结|章节 AI 总结"; wait_dialog; shot "teacher/T29-chapter-summary.png"; close_dialog
try_click "AI 报告|AI学情报告|生成报告|学情报告"; wait_dialog; shot "teacher/T30-ai-report.png"; close_dialog

# 学生详情（2026001 = id 14）
run open "$BASE/teacher/courses/7/analytics/students/14" >>"$LOG" 2>&1; wait_page; shot "teacher/T31-student-detail.png"

# 班级管理
run open "$BASE/teacher/classes" >>"$LOG" 2>&1; wait_page; shot "teacher/T32-classes.png"
click_row_btn "计科2026届-A班" "学生|管理|学生管理"; wait_dialog; shot "teacher/T33-class-students.png"; close_dialog

# 问答质量看板
run open "$BASE/teacher/qa-quality" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<70;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>100 && !document.querySelector('.el-loading-mask')) return 'QA_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'QA_TIMEOUT'})()" "QA_"
shotfull "teacher/T34-qa-quality.png"

run close >>"$LOG" 2>&1
echo "TEACHER_C_DONE"
