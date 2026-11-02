#!/bin/bash
# 手册 v2 · 教师端新功能截图（T35-T44）
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_v2_teacher.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

TOKEN=$(curl -s --noproxy '*' -X POST http://localhost:8005/api/auth/login/ -H 'Content-Type: application/json' \
  -d '{"username":"t101","password":"pass1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token']['access'])")

do_login t101 pass1234

# T35 资源库（类型标签 + 数量徽标 + 行内按钮）
run open "$BASE/teacher/courses/7/resources" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-table__row').length>0 && !document.querySelector('.el-loading-mask')) return 'RES_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'RES_TMO'})()" "RES_"
shot "teacher/T35-resource-library.png"

# T36 添加资源弹窗
try_click "添加资源"; wait_dialog; sleep 1; shot "teacher/T36-resource-add.png"; close_dialog

# T37 资源预览（导图，走签名 URL 直接打开查看器）
URL=$(curl -s --noproxy '*' -X POST http://localhost:8005/api/course-resources/37/sign/ -H "Authorization: Bearer $TOKEN" \
  | python -c "import sys,json;d=json.load(sys.stdin).get('data',{});print(d.get('url',''))" 2>/dev/null)
echo "sign url: $URL" >> "$LOG"
if [ -n "$URL" ]; then
  case "$URL" in
    http*) FULL="$URL" ;;
    *) FULL="$BASE$URL" ;;
  esac
  run open "$FULL" >>"$LOG" 2>&1
  sleep 3
  shot "teacher/T37-resource-preview.png"
fi

# T38 课程卡片（复用入口）
run open "$BASE/teacher/courses" >>"$LOG" 2>&1; wait_page; sleep 1; shot "teacher/T38-course-cards.png"

# T39 复用课程弹窗
assert "(function(){var b=document.querySelector('button[title=\"复用课程\"]'); if(b){b.click();return 'REUSE_CLK'} return 'REUSE_MISS'})()" "REUSE_"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>60) return 'REUSE_DLG'}await new Promise(function(r){setTimeout(r,300)})}return 'REUSE_TMO'})()" "REUSE_DLG"
sleep 1; shot "teacher/T39-course-reuse.png"; close_dialog

# T40 题库列表（用途标签）
run open "$BASE/teacher/courses/7/questions" >>"$LOG" 2>&1; wait_page; sleep 1; shot "teacher/T40-question-list.png"

# T41 新建题目（用途多选 + 题图上传）
try_click "新建题目"; wait_dialog; sleep 1; shot "teacher/T41-question-create.png"; close_dialog

# T42 学情导出弹窗
run open "$BASE/teacher/courses/7/analytics" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('导出')>=0 && !document.querySelector('.el-loading-mask')) return 'AN_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'AN_TMO'})()" "AN_"
try_click "导出 Excel"; wait_dialog; sleep 1; shot "teacher/T42-analytics-export.png"; close_dialog

# T43 班级列表（只读）
run open "$BASE/teacher/classes" >>"$LOG" 2>&1; wait_page; sleep 1; shot "teacher/T43-classes-readonly.png"

# T44 班级学生名单（独立页）
run open "$BASE/teacher/classes/3/students" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-table__row').length>0 && !document.querySelector('.el-loading-mask')) return 'ROSTER_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'ROSTER_TMO'})()" "ROSTER_"
sleep 1; shot "teacher/T44-class-roster.png"

run close >>"$LOG" 2>&1
echo "V2_TEACHER_DONE"
