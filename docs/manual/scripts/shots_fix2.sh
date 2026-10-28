#!/bin/bash
# 定点补截：T06 T07 T08 T15 T16 T18 T19 T22 T28 T29 T30 T33 / S03 S04 S05 S10 S11 S14
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_fix2.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

# ============ 教师端 ============
do_login t101 pass1234

# 章节页：讲稿 / 配音 / 完整讲解（第1章）
run open "$BASE/teacher/courses/7/chapters" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-tree-node').length>0 && !document.querySelector('.el-loading-mask')) return 'TREE_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TREE_TIMEOUT'})()" "TREE_"
click_in_card "第1章" "讲稿"; wait_dialog; shot "teacher/T06-scripts.png"; close_dialog
click_in_card "第1章" "配音"; wait_dialog; shot "teacher/T07-audio.png"; close_dialog
click_in_card "第1章" "完整讲解"
assert "(async function(){for(var i=0;i<50;i++){var im=document.querySelector('img[src*=ppt_pages]'); if(im && im.complete) return 'LEC_OK'; var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('退出讲解')>=0) return 'LEC_MODE'; await new Promise(function(r){setTimeout(r,300)})}return 'LEC_TIMEOUT'})()" "LEC_"
shot "teacher/T08-full-lecture.png"
try_click "退出讲解" >/dev/null

# 题库：AI 生题弹窗 + 草稿批次
run open "$BASE/teacher/courses/7/questions" >>"$LOG" 2>&1; wait_page
try_click "AI生成"; wait_dialog; shot "teacher/T15-question-aigen.png"; close_dialog
try_click "草稿批次"; wait_dialog; shot "teacher/T16a-draft-batches.png"
# 打开第一个批次预览
assert "(function(){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null){var b=ds[j].querySelector('button');var items=ds[j].querySelectorAll('.batch-row, .el-table__row, li, .el-card');if(items.length){items[0].querySelector('button')?items[0].querySelector('button').click():items[0].click();return 'BATCH_OPEN '+items.length}return 'BATCH_NOITEM'}}return 'BATCH_NODLG'})()" "BATCH_"
wait_dialog; sleep 1; shot "teacher/T16-draft-preview.png"; close_dialog

# 作业：发布作业表单 + 批改页
run open "$BASE/teacher/courses/7/homework" >>"$LOG" 2>&1; wait_page
try_click "发布作业"
assert "(async function(){for(var i=0;i<30;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null) return 'HW_DLG_OK'} var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('发布作业')>=0 && t.indexOf('作业标题')>=0) return 'HW_FORM_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'HW_TIMEOUT'})()" "HW_"
shot "teacher/T18-homework-create.png"; close_dialog
run open "$BASE/teacher/courses/7/homework" >>"$LOG" 2>&1; wait_page
click_in_card "作业1" "批改"
assert "(async function(){for(var i=0;i<40;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('提交批改')>=0 || t.indexOf('客观题已自动批改')>=0) return 'GRADE_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'GRADE_TIMEOUT'})()" "GRADE_"
shot "teacher/T19-homework-grading.png"

# 考试：新建考试表单
run open "$BASE/teacher/courses/7/exams" >>"$LOG" 2>&1; wait_page
try_click "新建考试"
assert "(async function(){for(var i=0;i<30;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null) return 'EX_DLG_OK'} var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('考试名称')>=0 || t.indexOf('新建考试')>=0) return 'EX_FORM_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'EX_TIMEOUT'})()" "EX_"
shot "teacher/T22-exam-create.png"; close_dialog

# 学习统计整页 + AI 报告（历史报告）
run open "$BASE/teacher/courses/7/analytics" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<70;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('学习统计')>=0 && t.length>200 && !document.querySelector('.el-loading-mask')) return 'AN_OK'; await new Promise(function(r){setTimeout(r,400)})}return 'AN_TIMEOUT'})()" "AN_"
sleep 2; shotfull "teacher/T28-analytics.png"
try_click "历史报告"; wait_dialog; sleep 1; shot "teacher/T30-ai-report.png"; close_dialog

# 学生详情（章节总结区在页内）
run open "$BASE/teacher/courses/7/analytics/students/14" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>150 && !document.querySelector('.el-loading-mask')) return 'SD_OK'; await new Promise(function(r){setTimeout(r,400)})}return 'SD_TIMEOUT'})()" "SD_"
sleep 1; shotfull "teacher/T31-student-detail.png"
assert "(function(){var els=document.querySelectorAll('h2,h3,h4,.section-title,div');for(var i=0;i<els.length;i++){if(els[i].innerText && els[i].innerText.trim().indexOf('章节总结')===0){els[i].scrollIntoView({block:'start'});return 'SUMPART_OK'}}return 'SUMPART_MISS'})()" "SUMPART_"
sleep 1; shot "teacher/T29-chapter-summary.png"

# 班级学生管理
run open "$BASE/teacher/classes" >>"$LOG" 2>&1; wait_page
click_in_card "计科2026届-A班" "学生"; wait_dialog; sleep 1; shot "teacher/T33-class-students.png"; close_dialog

# ============ 学生端 ============
do_login 2026001 pass1234

# S03 完整讲解连播
run open "$BASE/student/courses/7/learning" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<50;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('完整讲解')>=0 && !document.querySelector('.el-loading-mask')) return 'LRN_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'LRN_TIMEOUT'})()" "LRN_"
shot "student/S02-learning-catalog.png"
click_in_card "第1章" "完整讲解"
assert "(async function(){for(var i=0;i<60;i++){var im=document.querySelector('img[src*=ppt_pages]'); if(im && im.complete && im.naturalWidth>100) return 'LEC_OK'; var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('退出讲解')>=0) return 'LEC_MODE'; await new Promise(function(r){setTimeout(r,300)})}return 'LEC_TIMEOUT'})()" "LEC_"
sleep 1; shot "student/S03-lecture.png"
# S04 AI 总结（在学习页点）
try_click "退出讲解" >/dev/null
click_in_card "第1章" "AI总结"; wait_dialog
assert "(async function(){for(var i=0;i<60;i++){var d=document.querySelector('.el-drawer,.el-dialog'); if(d && d.offsetParent!==null && d.innerText.length>180) return 'SUM_OK'; await new Promise(function(r){setTimeout(r,400)})}return 'SUM_TIMEOUT'})()" "SUM_"
shot "student/S04-chapter-summary.png"; close_dialog

# S05 AI 助教：点快捷问题真实提问
run open "$BASE/student/courses/7/qa" >>"$LOG" 2>&1; wait_page
try_click "这门课程主要讲哪些内容"
assert "(async function(){for(var i=0;i<150;i++){var body=document.body.innerText||''; var m=document.querySelectorAll('.markdown-body'); for(var j=0;j<m.length;j++){if(m[j].innerText.length>150) return 'QA_ANS_OK len='+m[j].innerText.length} await new Promise(function(r){setTimeout(r,500)})}return 'QA_ANS_TIMEOUT'})()" "QA_ANS_"
sleep 1; shot "student/S05-qa.png"

# S10/S11 作业
run open "$BASE/student/courses/7/homework" >>"$LOG" 2>&1; wait_page
click_in_card "课后练习" "查看作业"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>100) return 'HW_OK'} await new Promise(function(r){setTimeout(r,300)})}return 'HW_TIMEOUT'})()" "HW_"
shot "student/S10-homework-do.png"; close_dialog
wait_page
click_in_card "作业1" "查看结果"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>80) return 'HWR_OK'} await new Promise(function(r){setTimeout(r,300)})}return 'HWR_TIMEOUT'})()" "HWR_"
shot "student/S11-homework-result.png"; close_dialog

# S14 交卷确认（取消，不真交）
run open "$BASE/student/exams/27/take" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<70;i++){if(document.querySelectorAll('.el-radio').length>2 && !document.querySelector('.el-loading-mask')) return 'TAKE_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TAKE_TIMEOUT'})()" "TAKE_"
try_click "提交答卷"; wait_dialog; shot "student/S14-exam-submit-confirm.png"
try_click "取消" >/dev/null; close_dialog

run close >>"$LOG" 2>&1
echo "FIX2_DONE"
