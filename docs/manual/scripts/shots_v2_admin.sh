#!/bin/bash
# 手册 v2 · 管理端新功能截图（A10-A16）
set -u
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_v2_admin.log"
: > "$LOG"
source "D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_common.sh"

do_login admin A0987654

# A10 班级管理列表
run open "$BASE/admin/classes" >>"$LOG" 2>&1; wait_page; sleep 1; shot "admin/A10-classes.png"

# A11 班级学生名单（含学籍列）
run open "$BASE/admin/classes/3/students" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-table__row').length>0 && !document.querySelector('.el-loading-mask')) return 'ROSTER_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'ROSTER_TMO'})()" "ROSTER_"
sleep 1; shot "admin/A11-roster.png"

# A12 学籍变更弹窗
try_click "学籍"; wait_dialog; sleep 1; shot "admin/A12-edu-status.png"; close_dialog

# A13 整班毕业预览（只预览，不执行）
run open "$BASE/admin/classes/3/students" >>"$LOG" 2>&1; wait_page
try_click "整班毕业"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>60) return 'GRAD_DLG'}await new Promise(function(r){setTimeout(r,300)})}return 'GRAD_TMO'})()" "GRAD_"
sleep 1; shot "admin/A13-graduation.png"; close_dialog

# A14 班级挂课抽屉
run open "$BASE/admin/classes" >>"$LOG" 2>&1; wait_page
try_click "课程"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-drawer,.el-dialog');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>60) return 'CC_DLG'}await new Promise(function(r){setTimeout(r,300)})}return 'CC_TMO'})()" "CC_"
sleep 1; shot "admin/A14-class-courses.png"; close_dialog

# A15 批量导入向导
run open "$BASE/admin/users" >>"$LOG" 2>&1; wait_page
try_click "批量导入"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null && ds[j].innerText.length>60) return 'IMP_DLG'}await new Promise(function(r){setTimeout(r,300)})}return 'IMP_TMO'})()" "IMP_"
sleep 1; shot "admin/A15-import-wizard.png"; close_dialog

# A16 AI 日配额卡片
run open "$BASE/admin/ai-settings" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.indexOf('配额')>=0 && !document.querySelector('.el-loading-mask')) return 'QUOTA_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'QUOTA_TMO'})()" "QUOTA_"
assert "(function(){var bs=document.querySelectorAll('button');for(var i=0;i<bs.length;i++){if(bs[i].innerText.indexOf('保存配额')>=0){bs[i].scrollIntoView({block:'center'});return 'SCROLL_OK'}}return 'SCROLL_MISS'})()" "SCROLL_"
sleep 1; shot "admin/A16-ai-quota.png"

run close >>"$LOG" 2>&1
echo "V2_ADMIN_DONE"
