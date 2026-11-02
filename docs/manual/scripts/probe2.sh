#!/bin/bash
# 侦察 v2：新版页面按钮与结构
set -u
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/probe2.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

probe() {
  run open "$BASE/$1" >>"$LOG" 2>&1
  assert "(async function(){for(var i=0;i<50;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>40 && !document.querySelector('.el-loading-mask')) return 'RDY'; await new Promise(function(r){setTimeout(r,300)})}return 'TMO'})()" "RDY|TMO" >/dev/null
  assert "(function(){var bs=Array.prototype.map.call(document.querySelectorAll('button'),function(b){return b.innerText.replace(/\\s+/g,' ').trim().slice(0,22)}).filter(function(t){return t});var st='rows='+document.querySelectorAll('.el-table__row').length+' cards='+document.querySelectorAll('.el-card').length+' tabs='+document.querySelectorAll('.el-tabs__item').length+' chips='+document.querySelectorAll('.el-tag,.el-check-tag').length;return 'P2[$2] '+st+' || '+bs.join(' | ')})()" "P2"
  assert "(function(){var ts=Array.prototype.map.call(document.querySelectorAll('.el-tabs__item'),function(t){return t.innerText.trim()});return 'TABS[$2] '+ts.join(' | ')})()" "TABS"
}

# 教师端
do_login t101 pass1234
probe "teacher/courses/7/resources" "T-resources"
probe "teacher/courses/7/questions" "T-questions"
probe "teacher/courses/7/analytics" "T-analytics"
probe "teacher/courses" "T-courses"
probe "teacher/classes" "T-classes"
probe "teacher/classes/3/students" "T-class-roster"

# 管理端
do_login admin A0987654
probe "admin/classes" "A-classes"
probe "admin/classes/3/students" "A-roster"
probe "admin/users" "A-users"
probe "admin/ai-settings" "A-ai"

# 学生端
do_login 2026001 pass1234
probe "student/my-classes" "S-courses"
probe "student/courses/7/resources" "S-resources"
probe "student/courses/7/materials" "S-materials"
probe "student/courses/7/learning" "S-learning"

run close >>"$LOG" 2>&1
echo "PROBE2_DONE"
