#!/bin/bash
# 验证修复后的 .qa-help：应为 16x16 圆形 + SVG 图标 + 生效的背景色
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

echo "=== measure fixed .qa-help ==="
$AB eval "(function(){
  var el=document.querySelector('.qa-help');
  if(!el)return 'NO_QA_HELP';
  var cs=getComputedStyle(el);
  var r=el.getBoundingClientRect();
  var svg=el.querySelector('svg');
  return 'rect='+Math.round(r.width)+'x'+Math.round(r.height)
    +' radius='+cs.borderRadius
    +' bg='+cs.backgroundColor
    +' color='+cs.color
    +' display='+cs.display
    +' svg='+(svg?'yes('+Math.round(svg.getBoundingClientRect().width)+'x'+Math.round(svg.getBoundingClientRect().height)+')':'no')
    +' text='+JSON.stringify(el.textContent);
})()"

echo "=== hover state check ==="
$AB eval "(async function(){
  var el=document.querySelector('.qa-help');
  if(!el)return 'NO_QA_HELP';
  el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));
  el.dispatchEvent(new MouseEvent('mouseenter',{bubbles:false}));
  await new Promise(function(r){setTimeout(r,300)});
  var cs=getComputedStyle(el);
  return 'hover_bg='+cs.backgroundColor+' hover_color='+cs.color;
})()"
$AB scrollintoview '.stat-cards'
$AB screenshot "$SHOT_DIR/qahelp-after-fix.png"
echo "=== verify done ==="
