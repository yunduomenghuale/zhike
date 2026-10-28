#!/bin/bash
# 侦察：列出关键页面的按钮文案与列表结构（为补截脚本提供选择器依据）
set -u
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/probe.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

probe() { # $1=url $2=tag
  run open "$BASE/$1" >>"$LOG" 2>&1
  assert "(async function(){for(var i=0;i<50;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>40 && !document.querySelector('.el-loading-mask')) return 'RDY'; await new Promise(function(r){setTimeout(r,300)})}return 'TMO'})()" "RDY|TMO" >/dev/null
  assert "(function(){var bs=Array.prototype.map.call(document.querySelectorAll('button'),function(b){return b.innerText.replace(/\\s+/g,' ').trim().slice(0,24)}).filter(function(t){return t});var struct='rows='+document.querySelectorAll('.el-table__row').length+' cards='+document.querySelectorAll('.el-card').length+' links='+document.querySelectorAll('.el-link').length+' tabs='+document.querySelectorAll('.el-tabs__item').length+' tree='+document.querySelectorAll('.el-tree-node').length;return 'PROBE[$2] '+struct+' || '+bs.join(' | ')})()" "PROBE"
}

# 学生端
do_login 2026001 pass1234
probe "student/courses/7/learning" "S-learning"
probe "student/courses/7/homework" "S-homework"
probe "student/courses/7/qa" "S-qa"
probe "student/exams/27/take" "S-take"
probe "student/courses/7/exams" "S-exams"
probe "student/courses/7/wrong" "S-wrong"

# 教师端
do_login t101 pass1234
probe "teacher/courses/7/homework" "T-homework"
probe "teacher/courses/7/questions" "T-questions"
probe "teacher/courses/7/exams" "T-exams"
probe "teacher/courses/7/analytics" "T-analytics"
probe "teacher/courses/7/analytics/students/14" "T-student-detail"
probe "teacher/classes" "T-classes"
probe "teacher/courses/7/knowledge" "T-knowledge"
probe "teacher/courses/7/chapters" "T-chapters"

run close >>"$LOG" 2>&1
echo "PROBE_DONE"
