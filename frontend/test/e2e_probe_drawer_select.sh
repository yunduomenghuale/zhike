#!/bin/bash
# 聚焦探针：抽屉打开后 el-select 下拉为何打不开
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

echo "=== A: open drawer first ==="
$AB eval "(async function(){
  var rows=document.querySelectorAll('.qa-issues-table .el-table__row');
  if(!rows.length)return 'NO_ROWS';
  rows[0].click();
  for(var i=0;i<40;i++){
    if(document.querySelector('.issue-detail'))return 'DRAWER_OPEN';
    await new Promise(function(r){setTimeout(r,150)});
  }
  return 'DRAWER_TIMEOUT';
})()"

echo "=== B: with drawer open, click select wrapper + dump state ==="
$AB eval "(async function(){
  var sel=document.querySelector('.logs-filters .el-select');
  if(!sel)return 'NO_SELECT';
  var w=sel.querySelector('.el-select__wrapper')||sel;
  var wrapperRect=w.getBoundingClientRect();
  w.click();
  await new Promise(function(r){setTimeout(r,500)});
  var pops=Array.prototype.slice.call(document.querySelectorAll('.el-select-dropdown'));
  var info=pops.map(function(p){
    var r=p.getBoundingClientRect();
    var items=p.querySelectorAll('.el-select-dropdown__item');
    return 'pop '+Math.round(r.width)+'x'+Math.round(r.height)+'@'+Math.round(r.top)+' items='+items.length+' vis='+Array.prototype.filter.call(items,function(el){return el.getBoundingClientRect().height>0}).length;
  });
  var overlay=document.querySelector('.el-overlay');
  var ovInfo=overlay?('overlay rect='+Math.round(overlay.getBoundingClientRect().width)+'x'+Math.round(overlay.getBoundingClientRect().height)+' z='+getComputedStyle(overlay).zIndex):'no-overlay';
  return 'WRAPPER_RECT='+Math.round(wrapperRect.width)+'x'+Math.round(wrapperRect.height)+' pops='+pops.length+' ['+info.join(' | ')+'] '+ovInfo;
})()"

echo "=== C: try clicking the INPUT inside select instead ==="
$AB eval "(async function(){
  var sel=document.querySelector('.logs-filters .el-select');
  var input=sel.querySelector('input.el-select__input')||sel.querySelector('input');
  input.click();
  await new Promise(function(r){setTimeout(r,500)});
  var visItems=Array.prototype.filter.call(document.querySelectorAll('.el-select-dropdown__item'),function(el){
    return el.getBoundingClientRect().height>0;
  });
  return 'INPUT_CLICK visItems='+visItems.length+' texts=['+visItems.map(function(e){return e.textContent.trim()}).join(',')+']';
})()"
echo "=== probe done ==="
