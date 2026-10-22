#!/bin/bash
# 探测 el-select 下拉交互：root/wrapper click 是否能打开 popper、rect 可见性判断是否可靠
cd "$(dirname "$0")"
AB="agent-browser"

$AB set viewport 1400 900
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder=\"请输入用户名\"]'))return 'LOGIN_FORM_READY';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_FORM_TIMEOUT'})()"
$AB fill 'input[placeholder="请输入用户名"]' t101
$AB fill 'input[placeholder="请输入密码"]' pass1234
$AB click 'button.auth-submit'
$AB eval "(async function(){for(var i=0;i<50;i++){if(localStorage.getItem('access_token'))return 'LOGIN_OK';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT'})()"
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.qa-issues-table .el-table__row').length)return 'QA_PAGE_READY';await new Promise(function(r){setTimeout(r,250)})}return 'QA_PAGE_TIMEOUT'})()"

echo "=== probe: select DOM + open dropdown ==="
$AB eval "(async function(){
  var sel=document.querySelector('.logs-filters .el-select');
  if(!sel)return 'NO_SELECT';
  var html=sel.outerHTML.replace(/\s+/g,' ').slice(0,500);
  var wrapper=sel.querySelector('.el-select__wrapper')||sel;
  var clicked=wrapper===sel?'root':'wrapper';
  wrapper.click();
  await new Promise(function(r){setTimeout(r,500)});
  var pops=Array.prototype.slice.call(document.querySelectorAll('.el-select-dropdown'));
  var info=pops.map(function(p){
    var r=p.getBoundingClientRect();
    return 'rect='+Math.round(r.width)+'x'+Math.round(r.height)+' disp='+getComputedStyle(p).display+' pos='+getComputedStyle(p).position;
  });
  var visItems=Array.prototype.filter.call(document.querySelectorAll('.el-select-dropdown__item'),function(el){
    var r=el.getBoundingClientRect();
    return r.width>0&&r.height>0&&getComputedStyle(el).visibility!=='hidden';
  });
  return 'CLICKED='+clicked+' || pops='+pops.length+' ['+info.join(' | ')+'] || visItems='+visItems.length+' texts=['+visItems.map(function(e){return e.textContent.trim()}).join(',')+'] || HTML='+html;
})()"
echo "=== probe done ==="
