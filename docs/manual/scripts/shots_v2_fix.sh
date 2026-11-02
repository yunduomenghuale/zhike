#!/bin/bash
# v2 补截：T42 导出弹窗 / A14 挂课 / A15b 导入向导弹窗
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_v2_fix.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

# T42 导出弹窗
do_login t101 pass1234
run open "$BASE/teacher/courses/7/analytics" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('导出')>=0 && !document.querySelector('.el-loading-mask')) return 'AN_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'AN_TMO'})()" "AN_"
try_click "导出Excel"; wait_dialog; sleep 1; shot "teacher/T42-analytics-export.png"; close_dialog

# A14 班级挂课（编辑班级弹窗内含关联课程）
do_login admin A0987654
run open "$BASE/admin/classes" >>"$LOG" 2>&1; wait_page; sleep 1
assert "(function(){var b=document.querySelector('button[title=\"编辑班级\"]'); if(b){b.click();return 'EDIT_CLK'} return 'EDIT_MISS'})()" "EDIT_"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>80) return 'EDIT_DLG'}await new Promise(function(r){setTimeout(r,300)})}return 'EDIT_TMO'})()" "EDIT_DLG"
sleep 1; shot "admin/A14-class-courses.png"; close_dialog

# A15b 导入向导（选「导入学生」后）
run open "$BASE/admin/users" >>"$LOG" 2>&1; wait_page
try_click "批量导入"
assert "(async function(){for(var i=0;i<25;i++){var its=document.querySelectorAll('.el-dropdown-menu__item'); for(var j=0;j<its.length;j++){if(its[j].offsetParent!==null && its[j].innerText.indexOf('导入学生')>=0){its[j].click();return 'DD_CLK'}} await new Promise(function(r){setTimeout(r,300)})}return 'DD_MISS'})()" "DD_"
assert "(async function(){for(var i=0;i<50;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>100) return 'WIZ_OK'}await new Promise(function(r){setTimeout(r,300)})}return 'WIZ_TMO'})()" "WIZ_"
sleep 1; shot "admin/A15b-import-students.png"; close_dialog

run close >>"$LOG" 2>&1
echo "V2_FIX_DONE"
