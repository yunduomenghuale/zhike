#!/bin/bash
# 手册 v2 · 学生端新功能截图（S18-S21）
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_v2_student.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

do_login 2026001 pass1234

# S18 我的课程（新卡片布局）
run open "$BASE/student/my-classes" >>"$LOG" 2>&1; wait_page; sleep 2; shot "student/S18-my-courses.png"

# S19 课程资源（封面卡片网格 + 类型过滤）
run open "$BASE/student/courses/7/resources" >>"$LOG" 2>&1; wait_page; sleep 2; shot "student/S19-resources-grid.png"

# S20 章节练习（含题图）
run open "$BASE/student/courses/7/learning" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<50;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('章节练习')>=0 && !document.querySelector('.el-loading-mask')) return 'LRN_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'LRN_TMO'})()" "LRN_"
click_in_card "第1章" "章节练习"
assert "(async function(){for(var i=0;i<60;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>80) return 'PRAC_OK'} var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('第1题')>=0 || t.indexOf('提交答案')>=0) return 'PRAC_PAGE'; await new Promise(function(r){setTimeout(r,300)})}return 'PRAC_TMO'})()" "PRAC_"
sleep 2; shot "student/S20-chapter-practice.png"; close_dialog

# S21 学籍门控提示（休学学生 2026004 访问作业页）
do_login 2026004 Zk026004
run open "$BASE/student/courses/7/homework" >>"$LOG" 2>&1; wait_page; sleep 1; shot "student/S21-edu-gate.png"

run close >>"$LOG" 2>&1
echo "V2_STUDENT_DONE"
