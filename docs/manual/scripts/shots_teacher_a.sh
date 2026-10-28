#!/bin/bash
# 教师端 A：工作台/课程/章节/知识库/AI问答/个人中心（C2 C4 T01-T05 T09-T11）
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_teacher_a.log"
mkdir -p "$OUT/common" "$OUT/teacher"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

do_login t101 pass1234

run open "$BASE/dashboard" >>"$LOG" 2>&1; wait_page; shot "common/C2-dashboard-teacher.png"

run open "$BASE/teacher/courses" >>"$LOG" 2>&1; wait_page; shot "teacher/T01-courses.png"
try_click "手动添加|新建课程"; wait_dialog; shot "teacher/T02-course-create.png"; close_dialog

run open "$BASE/teacher/courses/7/chapters" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-tree-node').length>0 && !document.querySelector('.el-loading-mask')) return 'TREE_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TREE_TIMEOUT'})()" "TREE_"
shot "teacher/T03-chapters.png"

try_click "授课计划识别目录"; wait_dialog; shot "teacher/T04-plan-recognize.png"; close_dialog

# T05 第1章「课件」按钮（图标按钮，按节点内第1个 action 钮）
assert "(function(){var ns=document.querySelectorAll('.el-tree-node');for(var i=0;i<ns.length;i++){if(ns[i].innerText.indexOf('第1章')>=0){var bs=ns[i].querySelectorAll('.node-action-btn');if(bs.length){bs[0].click();return 'NODE_OK btns='+bs.length}return 'NODE_NOBTN'}}return 'NODE_MISS'})()" "NODE_"
wait_dialog; shot "teacher/T05-ppt-panel.png"; close_dialog

run open "$BASE/teacher/courses/7/knowledge" >>"$LOG" 2>&1; wait_page; wait_table; shot "teacher/T09-knowledge.png"
try_click "上传教辅资料|上传资料|上传"; wait_dialog; shot "teacher/T10-material-upload.png"; close_dialog

run open "$BASE/teacher/courses/7/qa" >>"$LOG" 2>&1; wait_page; shot "teacher/T11-course-qa.png"

run open "$BASE/profile" >>"$LOG" 2>&1; wait_page; shot "common/C4-profile.png"

run close >>"$LOG" 2>&1
echo "TEACHER_A_DONE"
