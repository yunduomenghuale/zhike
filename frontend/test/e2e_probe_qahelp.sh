#!/bin/bash
# 探针：量 .qa-help 实际计算样式 + 截特写
cd "$(dirname "$0")"
AB="agent-browser"
SHOT_DIR="D:/Claude_Code/智课系统V2/frontend/test/screenshots"

$AB set viewport 1400 900
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder=\"请输入用户名\"]'))return 'LOGIN_FORM_READY';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_FORM_TIMEOUT'})()"
$AB fill 'input[placeholder="请输入用户名"]' t101
$AB fill 'input[placeholder="请输入密码"]' pass1234
$AB click 'button.auth-submit'
$AB eval "(async function(){for(var i=0;i<50;i++){if(localStorage.getItem('access_token'))return 'LOGIN_OK';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT'})()"
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.qa-issues-table .el-table__row').length)return 'QA_PAGE_READY';await new Promise(function(r){setTimeout(r,250)})}return 'QA_PAGE_TIMEOUT'})()"

echo "=== measure .qa-help ==="
$AB eval "(function(){
  var el=document.querySelector('.qa-help');
  if(!el)return 'NO_QA_HELP';
  var cs=getComputedStyle(el);
  var r=el.getBoundingClientRect();
  var svg=el.querySelector('svg');
  return 'rect='+Math.round(r.width)+'x'+Math.round(r.height)
    +' radius='+cs.borderRadius
    +' bg='+cs.backgroundColor
    +' border='+cs.borderTopWidth+' '+cs.borderTopColor
    +' color='+cs.color
    +' fontSize='+cs.fontSize
    +' display='+cs.display
    +' svg='+(svg?'yes('+Math.round(svg.getBoundingClientRect().width)+'px)':'no')
    +' text='+JSON.stringify(el.textContent);
})()"
$AB scrollintoview '.stat-cards'
$AB screenshot "$SHOT_DIR/probe-qahelp-before.png"
echo "=== probe done ==="
