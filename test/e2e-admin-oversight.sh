#!/bin/bash
# 督管增强一期：管理端三页浏览器级验证（单链执行）
set -u
export AB="/c/Users/张文飞/.workbuddy/binaries/node/versions/22.22.2-6/agent-browser"
SHOTS="D:/Claude_Code/智课系统V2/test/screenshots"
BASE="http://127.0.0.1:5273"
run() { env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy "$AB" "$@"; }

# 轮询断言助手：eval 返回扁平文本标记，失败重试一次
assert() {
  local expr="$1" out
  out=$(run eval "$expr")
  echo "$out" | grep -q "$2" || out=$(run eval "$expr")
  echo "$out"
}

echo "=== 1. 登录 ==="
run open "$BASE/login" >/dev/null 2>&1
run fill "input[placeholder='请输入用户名']" "admin" >/dev/null
run fill "input[placeholder='请输入密码']" "A0987654" >/dev/null
run click "button.auth-submit" >/dev/null
assert "(async function(){for(var i=0;i<40;i++){if(location.pathname.indexOf('/login')<0)return 'LOGIN_OK path='+location.pathname;await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT path='+location.pathname})()" "LOGIN_OK"

echo "=== 2. 管理概览 ==="
run open "$BASE/admin/overview" >/dev/null 2>&1
assert "(async function(){for(var i=0;i<40;i++){var p=document.querySelector('.admin-overview');if(p&&p.querySelector('.metric-card')){var cards=p.querySelectorAll('.metric-card').length;var chart=p.querySelectorAll('.trend-panel svg').length;var alerts=p.querySelectorAll('.alert-item').length;var delta=p.querySelectorAll('.stat-delta').length;return 'OVERVIEW_OK cards='+cards+' chart='+chart+' alerts='+alerts+' delta='+delta}await new Promise(function(r){setTimeout(r,250)})}return 'OVERVIEW_TIMEOUT path='+location.pathname})()" "OVERVIEW_OK"
run screenshot "$SHOTS/admin-overview.png" >/dev/null 2>&1 && echo "screenshot: admin-overview.png"

echo "=== 3. 教学监管-班级维度 + 行点击抽屉 ==="
run open "$BASE/admin/teaching" >/dev/null 2>&1
assert "(async function(){for(var i=0;i<40;i++){if(document.querySelector('.admin-teaching .el-table__row'))return 'TEACHING_OK rows='+document.querySelectorAll('.el-table__row').length;await new Promise(function(r){setTimeout(r,250)})}return 'TEACHING_TIMEOUT path='+location.pathname})()" "TEACHING_OK"
# 切到班级监管 tab（el-tabs 第 2 项）
run eval "var items=document.querySelectorAll('.admin-tabs .el-tabs__item');if(items.length>1){items[1].click();'TAB_CLICKED'}else{'TAB_NOT_FOUND'}" | grep -q TAB_CLICKED || run eval "var items=document.querySelectorAll('.admin-tabs .el-tabs__item');if(items.length>1){items[1].click();'TAB_CLICKED'}else{'TAB_NOT_FOUND'}"
assert "(async function(){for(var i=0;i<30;i++){var rows=document.querySelectorAll('.el-table__row');if(rows.length&&document.body.textContent.indexOf('作业提交率')>=0)return 'CLASS_TAB_OK rows='+rows.length;await new Promise(function(r){setTimeout(r,250)})}return 'CLASS_TAB_TIMEOUT'})()" "CLASS_TAB_OK"
# 点击第一行 → 班级详情抽屉
run click ".el-table__row" >/dev/null
assert "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.class-drawer');if(d&&document.body.textContent.indexOf('逐学生学习进度')>=0)return 'DRAWER_OK students_rows='+document.querySelectorAll('.class-drawer .el-table__row').length+' summary='+(document.querySelector('.class-drawer .summary-card')?1:0);await new Promise(function(r){setTimeout(r,250)})}return 'DRAWER_TIMEOUT'})()" "DRAWER_OK"
run screenshot "$SHOTS/admin-teaching-class-drawer.png" >/dev/null 2>&1 && echo "screenshot: admin-teaching-class-drawer.png"
# 关闭抽屉，切到教师监管 tab
run eval "var b=document.querySelector('.class-drawer .drawer-close');if(b){b.click();'CLOSED'}else{'NO_BTN'}" >/dev/null
run eval "var items=document.querySelectorAll('.admin-tabs .el-tabs__item');if(items.length>2){items[2].click();'TAB3_CLICKED'}else{'TAB3_NOT_FOUND'}" | grep -q TAB3_CLICKED || run eval "var items=document.querySelectorAll('.admin-tabs .el-tabs__item');if(items.length>2){items[2].click();'TAB3_CLICKED'}else{'TAB3_NOT_FOUND'}"
assert "(async function(){for(var i=0;i<30;i++){if(document.body.textContent.indexOf('AI 调用')>=0&&document.querySelectorAll('.el-table__row').length)return 'TEACHER_TAB_OK rows='+document.querySelectorAll('.el-table__row').length;await new Promise(function(r){setTimeout(r,250)})}return 'TEACHER_TAB_TIMEOUT'})()" "TEACHER_TAB_OK"
run screenshot "$SHOTS/admin-teaching-teachers.png" >/dev/null 2>&1 && echo "screenshot: admin-teaching-teachers.png"

echo "=== 4. 操作审计 ==="
run open "$BASE/admin/audit" >/dev/null 2>&1
assert "(async function(){for(var i=0;i<40;i++){var p=document.querySelector('.admin-audit');if(p&&document.querySelector('.audit-card')){var rows=p.querySelectorAll('.el-table__row').length;var changes=p.querySelectorAll('.change-item').length;var opts=p.querySelectorAll('.filter-select .el-select__item').length;return 'AUDIT_OK rows='+rows+' changes='+changes+' options='+opts}await new Promise(function(r){setTimeout(r,250)})}return 'AUDIT_TIMEOUT path='+location.pathname})()" "AUDIT_OK"
run screenshot "$SHOTS/admin-audit.png" >/dev/null 2>&1 && echo "screenshot: admin-audit.png"

echo "=== 5. 收尾 ==="
run close >/dev/null 2>&1
echo "E2E_DONE"
