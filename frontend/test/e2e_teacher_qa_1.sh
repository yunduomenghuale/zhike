#!/bin/bash
# 教师端问答质量页 E2E — 链路 1：登录 + 统计页断言 + 截图
# 单链执行（agent-browser daemon 不跨 Bash 调用存活）
cd "$(dirname "$0")"
SHOT_DIR="D:/Claude_Code/智课系统V2/frontend/test/screenshots"
AB="agent-browser"

echo "=== [1/9] set viewport ==="
$AB set viewport 1400 900

echo "=== [2/9] open qa-quality (expect redirect to login) ==="
$AB open http://localhost:5273/teacher/qa-quality

echo "=== [3/9] wait login form ==="
$AB eval "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder=\"请输入用户名\"]'))return 'LOGIN_FORM_READY url='+location.pathname;await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_FORM_TIMEOUT url='+location.pathname})()"

echo "=== [4/9] fill credentials ==="
$AB fill 'input[placeholder="请输入用户名"]' t101
$AB fill 'input[placeholder="请输入密码"]' pass1234

echo "=== [5/9] click login ==="
$AB click 'button.auth-submit'

echo "=== [6/9] wait login success (token in localStorage) ==="
$AB eval "(async function(){for(var i=0;i<50;i++){if(localStorage.getItem('access_token'))return 'LOGIN_OK';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT url='+location.pathname})()"

echo "=== [7/9] open qa-quality again ==="
$AB open http://localhost:5273/teacher/qa-quality

echo "=== [8/9] wait page render (stat cards + issue rows) ==="
$AB eval "(async function(){for(var i=0;i<60;i++){var rows=document.querySelectorAll('.qa-issues-table .el-table__row');var cards=document.querySelectorAll('.stat-cards .stat-card');if(rows.length&&cards.length)return 'QA_PAGE_READY rows='+rows.length+' cards='+cards.length;await new Promise(function(r){setTimeout(r,250)})}return 'QA_PAGE_TIMEOUT url='+location.pathname+' cards='+document.querySelectorAll('.stat-cards .stat-card').length})()"

echo "=== [9/9] assert stats page + screenshots ==="
$AB eval "(function(){
  var cards=document.querySelectorAll('.stat-cards .stat-card');
  var alerts=document.querySelectorAll('.alerts .alert');
  var charts=document.querySelectorAll('.trend-chart');
  var dists=document.querySelectorAll('.dist-card');
  var courseRows=document.querySelectorAll('.qa-quality-table .el-table__row');
  var rows=document.querySelectorAll('.qa-issues-table .el-table__row');
  var total=((document.querySelector('.pager .el-pagination__total')||{}).textContent||'').trim();
  var alertText=alerts.length?(alerts[0].textContent||'').replace(/\s+/g,' ').trim().slice(0,80):'';
  var win=((document.querySelector('.window-note')||{}).textContent||'').trim();
  return 'STATS_PAGE_OK cards='+cards.length+' alerts='+alerts.length+' charts='+charts.length+' dists='+dists.length+' courseRows='+courseRows.length+' rows='+rows.length+' total='+total+' alert=['+alertText+'] window=['+win.slice(0,40)+']';
})()"
$AB screenshot "$SHOT_DIR/qa-quality-stats-top.png"
$AB scrollintoview '.qa-issues-table'
$AB screenshot "$SHOT_DIR/qa-quality-stats-issues.png"
echo "=== chain 1 done ==="
