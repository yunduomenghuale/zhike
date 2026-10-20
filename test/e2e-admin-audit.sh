#!/bin/bash
# 审计页单独验证（close 后重开，需重新登录）
set -u
export AB="/c/Users/张文飞/.workbuddy/binaries/node/versions/22.22.2-6/agent-browser"
SHOTS="D:/Claude_Code/智课系统V2/test/screenshots"
BASE="http://127.0.0.1:5273"
run() { env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy "$AB" "$@"; }

assert() {
  local expr="$1" out
  out=$(run eval "$expr")
  echo "$out" | grep -q "$2" || out=$(run eval "$expr")
  echo "$out"
}

echo "=== close 后重开 ==="
run close >/dev/null 2>&1
run open "$BASE/login" >/dev/null 2>&1
run fill "input[placeholder='请输入用户名']" "admin" >/dev/null
run fill "input[placeholder='请输入密码']" "A0987654" >/dev/null
run click "button.auth-submit" >/dev/null
assert "(async function(){for(var i=0;i<40;i++){if(location.pathname.indexOf('/login')<0)return 'LOGIN_OK path='+location.pathname;await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT path='+location.pathname})()" "LOGIN_OK"

echo "=== 操作审计 ==="
run open "$BASE/admin/audit" >/dev/null 2>&1
assert "(async function(){for(var i=0;i<50;i++){var p=document.querySelector('.admin-audit');if(p&&p.querySelector('.audit-card')){var rows=p.querySelectorAll('.el-table__row').length;var changes=p.querySelectorAll('.change-item').length;var opts=p.querySelectorAll('.filter-select .el-select__item, .filter-select .el-select-dropdown__item').length;var pager=document.querySelector('.pager')?1:0;return 'AUDIT_OK rows='+rows+' changes='+changes+' pager='+pager}await new Promise(function(r){setTimeout(r,250)})}return 'AUDIT_TIMEOUT path='+location.pathname})()" "AUDIT_OK"
run screenshot "$SHOTS/admin-audit.png" >/dev/null 2>&1 && echo "screenshot: admin-audit.png"
run close >/dev/null 2>&1
echo "E2E_AUDIT_DONE"
