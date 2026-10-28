#!/bin/bash
# 公共函数：source 后使用。需要脚本内先定义 OUT/LOG/BASE。
export AB="/c/Users/张文飞/.workbuddy/binaries/node/versions/22.22.2-6/agent-browser"
BASE="http://127.0.0.1:5273"
run() { env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy "$AB" "$@"; }
assert() { local out; out=$(run eval "$1" 2>>"$LOG"); echo "$out" | grep -q "$2" || out=$(run eval "$1" 2>>"$LOG"); echo "$out"; }
shot() { run screenshot "$OUT/$1" >>"$LOG" 2>&1 && echo "SHOT_OK $1" || echo "SHOT_FAIL $1"; }
shotfull() { run screenshot --full "$OUT/$1" >>"$LOG" 2>&1 && echo "SHOT_OK $1(full)" || echo "SHOT_FAIL $1"; }

wait_page() {
  assert "(async function(){for(var i=0;i<60;i++){var t=(document.querySelector('#app')||{}).innerText||''; if(t.length>60 && !document.querySelector('.el-loading-mask')) return 'PG_OK '+location.pathname; await new Promise(function(r){setTimeout(r,300)})} return 'PG_TIMEOUT '+location.pathname})()" "PG_OK"
}
wait_table() {
  assert "(async function(){for(var i=0;i<50;i++){if(document.querySelectorAll('.el-table__row').length>0 && !document.querySelector('.el-loading-mask')) return 'TBL_OK'; await new Promise(function(r){setTimeout(r,300)})}return 'TBL_TIMEOUT'})()" "TBL_"
}
try_click() {
  assert "(function(){var cands='$1'.split('|');var bs=document.querySelectorAll('button');for(var c=0;c<cands.length;c++){for(var i=0;i<bs.length;i++){var t=bs[i].innerText.replace(/\\s+/g,'');if(t.indexOf(cands[c])>=0 && bs[i].offsetParent!==null){bs[i].click();return 'BTN_OK '+cands[c]}}}return 'BTN_MISS $1'})()" "BTN_"
}
click_row_btn() { # $1=行文本 $2=按钮候选
  assert "(function(){var cands='$2'.split('|');var trs=document.querySelectorAll('.el-table__row, .item-card, li, .el-card');for(var r=0;r<trs.length;r++){if(trs[r].innerText.indexOf('$1')<0) continue;var bs=trs[r].querySelectorAll('button, a, .el-link');for(var c=0;c<cands.length;c++){for(var i=0;i<bs.length;i++){if(bs[i].innerText.replace(/\\s+/g,'').indexOf(cands[c])>=0){bs[i].click();return 'ROWBTN_OK '+cands[c]}}}return 'ROWBTN_MISSBTN $1'}return 'ROWBTN_MISSROW $1'})()" "ROWBTN_"
}
wait_dialog() {
  assert "(async function(){for(var i=0;i<40;i++){var ds=document.querySelectorAll('.el-dialog,.el-drawer,.el-message-box');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null) return 'DLG_OK'}await new Promise(function(r){setTimeout(r,250)})}return 'DLG_TIMEOUT'})()" "DLG_"
}
click_in_card() { # $1=卡片文本 $2=按钮文本（去空格后匹配）
  assert "(function(){var bs=document.querySelectorAll('button');for(var i=0;i<bs.length;i++){var t=bs[i].innerText.replace(/\\s+/g,'');if(t.indexOf('$2')<0 || bs[i].offsetParent===null) continue;var p=bs[i];for(var d=0;d<7 && p;d++){p=p.parentElement;if(p && p.innerText && p.innerText.indexOf('$1')>=0){bs[i].click();return 'CB_OK $2'}}}return 'CB_MISS $1/$2'})()" "CB_"
}
close_dialog() {
  run eval "(function(){var ds=document.querySelectorAll('.el-dialog,.el-drawer');for(var j=0;j<ds.length;j++){if(ds[j].offsetParent!==null){var b=ds[j].querySelector('.el-dialog__headerbtn,.el-drawer__close-btn');if(b){b.click()}}}return 'X'})()" >>"$LOG" 2>&1
  run eval "document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))" >>"$LOG" 2>&1
}
do_login() { # $1=user $2=pass
  run close --all >>"$LOG" 2>&1
  run open "$BASE/login" >>"$LOG" 2>&1
  assert "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder*=用户名]')) return 'LP_OK'; await new Promise(function(r){setTimeout(r,250)})}return 'LP_TIMEOUT'})()" "LP_OK"
  run fill "input[placeholder='请输入用户名']" "$1" >/dev/null 2>&1
  run fill "input[placeholder='请输入密码']" "$2" >/dev/null 2>&1
  run click "button.auth-submit" >/dev/null 2>&1
  assert "(async function(){for(var i=0;i<40;i++){if(location.pathname.indexOf('/login')<0)return 'LOGIN_OK '+location.pathname;await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT'})()" "LOGIN_OK"
}
