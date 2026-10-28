#!/bin/bash
# 学生端：工作台/我的班级/学习/AI助教/资料资源/作业/考试/错题/实验（C3 S01-S17）
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_student.log"
mkdir -p "$OUT/common" "$OUT/student"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

do_login 2026001 pass1234

run open "$BASE/dashboard" >>"$LOG" 2>&1; wait_page; shot "common/C3-dashboard-student.png"

run open "$BASE/student/my-classes" >>"$LOG" 2>&1; wait_page; shot "student/S01-my-classes.png"

# 课程学习
run open "$BASE/student/courses/7/learning" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-tree-node').length>0 && !document.querySelector('.el-loading-mask')) return 'TREE_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TREE_TIMEOUT'})()" "TREE_"
shot "student/S02-learning-catalog.png"
# S03 点第1章进入连播
assert "(function(){var ns=document.querySelectorAll('.el-tree-node__content');for(var i=0;i<ns.length;i++){if(ns[i].innerText.indexOf('第1章')>=0){ns[i].click();return 'CH1_OK'}}return 'CH1_MISS'})()" "CH1_"
assert "(async function(){for(var i=0;i<60;i++){var im=document.querySelector('.lecture-page img, .ppt-page img, img[src*=ppt_pages]'); if(im && im.complete) return 'LECTURE_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'LECTURE_TIMEOUT'})()" "LECTURE_"
shot "student/S03-lecture.png"
# S04 章节总结
try_click "章节总结|AI 总结|章节 AI 总结|总结"; wait_dialog
assert "(async function(){for(var i=0;i<50;i++){var d=document.querySelector('.el-drawer, .el-dialog'); if(d && d.offsetParent!==null && d.innerText.length>200) return 'SUM_OK'; await new Promise(function(r){setTimeout(r,400)})}return 'SUM_TIMEOUT'})()" "SUM_"
shot "student/S04-chapter-summary.png"; close_dialog

# S05 AI 助教（真实提问一条）
run open "$BASE/student/courses/7/qa" >>"$LOG" 2>&1; wait_page
run eval "(function(){var t=document.querySelector('textarea'); if(t){t.value='Java 的三大平台分别是什么？请简要说明。'; t.dispatchEvent(new Event('input',{bubbles:true})); return 'QA_INPUT_OK'} return 'QA_INPUT_MISS'})()" >>"$LOG" 2>&1
try_click "发送"
assert "(async function(){for(var i=0;i<120;i++){var m=document.querySelectorAll('.markdown-body, .answer, .msg-content, .qa-answer'); for(var j=0;j<m.length;j++){if(m[j].innerText.length>120) return 'QA_ANS_OK'} await new Promise(function(r){setTimeout(r,500)})}return 'QA_ANS_TIMEOUT'})()" "QA_ANS_"
shot "student/S05-qa.png"

run open "$BASE/student/courses/7/materials" >>"$LOG" 2>&1; wait_page; shot "student/S07-materials.png"
run open "$BASE/student/courses/7/resources" >>"$LOG" 2>&1; wait_page; shot "student/S08-resources.png"

# 作业
run open "$BASE/student/courses/7/homework" >>"$LOG" 2>&1; wait_page; shot "student/S09-homework.png"
click_row_btn "课后练习" "去完成|去提交|开始|查看|提交"; wait_dialog; shot "student/S10-homework-do.png"; close_dialog
click_row_btn "作业1" "查看|结果|批改|详情"; wait_dialog; shot "student/S11-homework-result.png"; close_dialog

# 考试
run open "$BASE/student/courses/7/exams" >>"$LOG" 2>&1; wait_page; shot "student/S12-exams.png"
run open "$BASE/student/exams/27/take" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<70;i++){var t=(document.querySelector('#app')||{}).innerText||''; if((t.indexOf('单选')>=0 || t.indexOf('第1题')>=0 || document.querySelectorAll('.el-radio').length>2) && !document.querySelector('.el-loading-mask')) return 'TAKE_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TAKE_TIMEOUT'})()" "TAKE_"
shot "student/S13-exam-taking.png"
try_click "交卷"; wait_dialog; shot "student/S14-exam-submit-confirm.png"
# 取消交卷（不真交）
try_click "取消"; close_dialog
run open "$BASE/student/exams/26/review" >>"$LOG" 2>&1; wait_page; shot "student/S15-exam-review.png"

run open "$BASE/student/courses/7/wrong" >>"$LOG" 2>&1; wait_page; shot "student/S16-wrongbook.png"
run open "$BASE/student/courses/7/labs" >>"$LOG" 2>&1; wait_page; shot "student/S17-labs.png"

run close >>"$LOG" 2>&1
echo "STUDENT_DONE"
