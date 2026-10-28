#!/bin/bash
# 补截：A03 新建账号弹窗、A08 大模型编辑表单
set -u
export AB="/c/Users/张文飞/.workbuddy/binaries/node/versions/22.22.2-6/agent-browser"
BASE="http://127.0.0.1:5273"
OUT="D:/Claude_Code/智课系统V2/docs/manual/assets"
LOG="D:/Claude_Code/智课系统V2/docs/manual/scripts/shots_admin_fix.log"
: > "$LOG"
run() { env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy "$AB" "$@"; }
assert() { local out; out=$(run eval "$1" 2>>"$LOG"); echo "$out" | grep -q "$2" || out=$(run eval "$1" 2>>"$LOG"); echo "$out"; }
shot() { run screenshot "$OUT/$1" >>"$LOG" 2>&1 && echo "SHOT_OK $1" || echo "SHOT_FAIL $1"; }

run close --all >>"$LOG" 2>&1
run open "$BASE/login" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder*=用户名]')) return 'LP_OK'; await new Promise(function(r){setTimeout(r,250)})}return 'LP_TIMEOUT'})()" "LP_OK"
run fill "input[placeholder='请输入用户名']" "admin" >/dev/null 2>&1
run fill "input[placeholder='请输入密码']" "A0987654" >/dev/null 2>&1
run click "button.auth-submit" >/dev/null 2>&1
assert "(async function(){for(var i=0;i<40;i++){if(location.pathname.indexOf('/login')<0)return 'LOGIN_OK';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT'})()" "LOGIN_OK"

run open "$BASE/admin/users" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.el-table__row').length>2 && !document.querySelector('.el-loading-mask')) return 'TBL_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TBL_TIMEOUT'})()" "TBL_OK"
assert "(function(){var bs=document.querySelectorAll('button');for(var i=0;i<bs.length;i++){if(bs[i].innerText.replace(/\\s+/g,'').indexOf('新建账号')>=0 && bs[i].offsetParent!==null){bs[i].click();return 'BTN_OK'}}return 'BTN_MISS'})()" "BTN_OK"
assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null) return 'DLG_OK'}await new Promise(function(r){setTimeout(r,250)})}return 'DLG_TIMEOUT'})()" "DLG_OK"
shot "admin/A03-user-create.png"

run open "$BASE/admin/ai-settings" >>"$LOG" 2>&1
assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>60 && !document.querySelector('.el-loading-mask')) return 'PG_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'PG_TIMEOUT'})()" "PG_OK"
assert "(async function(){var b=null;var bs=document.querySelectorAll('button');for(var i=0;i<bs.length;i++){if(bs[i].innerText.indexOf('保存并应用')>=0){b=bs[i];break}}if(b){b.scrollIntoView({block:'center'});await new Promise(function(r){setTimeout(r,500)});return 'SCROLL_OK'}return 'SCROLL_MISS'})()" "SCROLL_OK"
shot "admin/A08-ai-edit.png"

run close >>"$LOG" 2>&1
echo "FIX_DONE"
