#!/bin/bash
# 补截3：T31/T29 学生详情（带班级参数）+ S11 作业批改结果
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_fix3.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

# 教师端：学生详情（课程空间路由需 query.class 带班级）
do_login t101 pass1234
run open "$BASE/teacher/courses/7/analytics/students/14?class=3" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>200 && t.indexOf('未找到')<0 && !document.querySelector('.el-loading-mask')) return 'SD_OK len='+t.length; if(t.indexOf('未找到')>=0) return 'SD_NODATA'; await new Promise(function(r){setTimeout(r,400)})}return 'SD_TIMEOUT'})()" "SD_"
sleep 1; shotfull "teacher/T31-student-detail.png"
assert "(function(){var all=document.querySelectorAll('h1,h2,h3,h4,.section-title,.card-title,div,span');for(var i=0;i<all.length;i++){var tx=(all[i].innerText||'').trim();if(tx==='章节总结'||tx==='章节 AI 总结'||tx.indexOf('章节学习总结')===0){all[i].scrollIntoView({block:'start'});return 'SUMPART_OK:'+tx.slice(0,12)}}return 'SUMPART_MISS'})()" "SUMPART_"
sleep 1; shot "teacher/T29-chapter-summary.png"

# 学生端：作业批改结果
do_login 2026001 pass1234
run open "$BASE/student/courses/7/homework" >>"$LOG" 2>&1; wait_page
click_in_card "作业1" "查看结果"
assert "(async function(){for(var i=0;i<40;i++){var t=(document.querySelector('#app')||{}).innerText||''; if((t.indexOf('评语')>=0 || t.indexOf('得分')>=0 || t.indexOf('批改')>=0) && t.indexOf('作业1')>=0 && t.length>150) return 'HWR_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'HWR_TIMEOUT'})()" "HWR_"
shot "student/S11-homework-result.png"

run close >>"$LOG" 2>&1
echo "FIX3_DONE"
