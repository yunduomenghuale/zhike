#!/bin/bash
# 手册截图 · 管理端 + 登录页（C1, A01-A09）
set -u
export AB="/c/Users/张文飞/.workbuddy/binaries/node/versions/22.22.2-6/agent-browser"
BASE="http://127.0.0.1:5273"
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
mkdir -p "$OUT/common" "$OUT/admin"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_admin.log"
: > "$LOG"

run() { env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy "$AB" "$@"; }
assert() { local out; out=$(run eval "$1" 2>>"$LOG"); echo "$out" | grep -q "$2" || out=$(run eval "$1" 2>>"$LOG"); echo "$out"; }
shot() { run screenshot "$OUT/$1" >>"$LOG" 2>&1 && echo "SHOT_OK $1" || echo "SHOT_FAIL $1"; }

wait_page() {
  assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>60 && !document.querySelector('.el-loading-mask')) return 'PG_OK '+location.pathname; await new Promise(function(r){setTimeout(r,300)})} return 'PG_TIMEOUT '+location.pathname})()" "PG_OK"
}
click_text() {
  assert "(function(){var bs=document.querySelectorAll('button');for(var i=0;i<bs.length;i++){var t=bs[i].innerText.replace(/\\s+/g,'');if(t.indexOf('$1')>=0 && bs[i].offsetParent!==null){bs[i].click();return 'BTN_OK $1'}}return 'BTN_MISS $1'})()" "BTN_OK"
}
wait_dialog() {
  assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null) return 'DLG_OK'}await new Promise(function(r){setTimeout(r,250)})}return 'DLG_TIMEOUT'})()" "DLG_OK"
}

# C1 登录页（未登录）
run close --all >>"$LOG" 2>&1
run open "$BASE/login" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder*=用户名]')) return 'LOGIN_PAGE_OK'; await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_PAGE_TIMEOUT'})()" "LOGIN_PAGE_OK"
shot "common/C1-login.png"

# admin 登录
run fill "input[placeholder='请输入用户名']" "admin" >/dev/null 2>&1
run fill "input[placeholder='请输入密码']" "A0987654" >/dev/null 2>&1
run click "button.auth-submit" >/dev/null 2>&1
assert "(async function(){for(var i=0;i<40;i++){if(location.pathname.indexOf('/login')<0)return 'LOGIN_OK '+location.pathname;await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT'})()" "LOGIN_OK"

# A01 管理概览
run open "$BASE/admin/overview" >>"$LOG" 2>&1
wait_page
shot "admin/A01-overview.png"

# A02 用户管理
run open "$BASE/admin/users" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-table__row').length>2 && !document.querySelector('.el-loading-mask')) return 'TBL_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TBL_TIMEOUT'})()" "TBL_OK"
shot "admin/A02-users.png"

# A03 新建用户弹窗
click_text "新建用户"
wait_dialog
shot "admin/A03-user-create.png"
run eval "(function(){var ds=document.querySelectorAll('.el-dialog');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null){var b=ds[j].querySelector('.el-dialog__headerbtn');if(b){b.click();return 'CLOSED'}}}return 'NO_DLG'})()" >>"$LOG" 2>&1

# A04 开放注册开关（工具栏区域，整页截）
shot "admin/A04-register-toggle.png"

# A05 教学监管
run open "$BASE/admin/teaching" >>"$LOG" 2>&1
wait_page
shot "admin/A05-teaching.png"

# A06 操作审计
run open "$BASE/admin/audit" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-table__row').length>0 && !document.querySelector('.el-loading-mask')) return 'TBL_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TBL_TIMEOUT'})()" "TBL_OK"
shot "admin/A06-audit.png"

# A07 大模型配置
run open "$BASE/admin/ai-settings" >>"$LOG" 2>&1
wait_page
shot "admin/A07-ai-settings.png"

# A08 能力编辑弹窗（点第一行「编辑」）
assert "(function(){var bs=document.querySelectorAll('button');for(var i=0;i<bs.length;i++){var t=bs[i].innerText.replace(/\\s+/g,'');if(t==='编辑' && bs[i].offsetParent!==null){bs[i].click();return 'EDIT_OK'}}return 'EDIT_MISS'})()" "EDIT_OK"
wait_dialog
shot "admin/A08-ai-edit.png"
run eval "(function(){var ds=document.querySelectorAll('.el-dialog');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null){var b=ds[j].querySelector('.el-dialog__headerbtn');if(b){b.click();return 'CLOSED'}}}return 'NO_DLG'})()" >>"$LOG" 2>&1

# A09 问答质量 tab
assert "(function(){var ts=document.querySelectorAll('.el-tabs__item');for(var i=0;i<ts.length;i++){if(ts[i].innerText.indexOf('问答质量')>=0){ts[i].click();return 'TAB_OK'}}return 'TAB_MISS'})()" "TAB_OK"
assert "(async function(){for(var i=0;i<40;i++){if(!document.querySelector('.el-loading-mask')) return 'TAB_READY'; await new Promise(function(r){setTimeout(r,300)})}return 'TAB_TIMEOUT'})()" "TAB_READY"
shot "admin/A09-qa-quality.png"

run close >>"$LOG" 2>&1
echo "ADMIN_SHOTS_DONE"
