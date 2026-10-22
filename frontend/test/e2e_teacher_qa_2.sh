#!/bin/bash
# 教师端问答质量页 E2E — 链路 2（v2）：类型筛选 + 行点击抽屉 + 课程筛选
# 修正：el-select 点击目标改为 .el-select__wrapper（EP 2.9 处理器在子元素上），可见性判断改 rect
cd "$(dirname "$0")"
SHOT_DIR="D:/Claude_Code/智课系统V2/frontend/test/screenshots"
AB="agent-browser"

echo "=== [1/10] set viewport ==="
$AB set viewport 1400 900

echo "=== [2/10] open qa-quality ==="
$AB open http://localhost:5273/teacher/qa-quality

echo "=== [3/10] wait login form ==="
$AB eval "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder=\"请输入用户名\"]'))return 'LOGIN_FORM_READY url='+location.pathname;await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_FORM_TIMEOUT url='+location.pathname})()"

echo "=== [4/10] fill + login ==="
$AB fill 'input[placeholder="请输入用户名"]' t101
$AB fill 'input[placeholder="请输入密码"]' pass1234
$AB click 'button.auth-submit'

echo "=== [5/10] wait login success ==="
$AB eval "(async function(){for(var i=0;i<50;i++){if(localStorage.getItem('access_token'))return 'LOGIN_OK';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT url='+location.pathname})()"

echo "=== [6/10] open qa-quality + wait render ==="
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<60;i++){var rows=document.querySelectorAll('.qa-issues-table .el-table__row');var cards=document.querySelectorAll('.stat-cards .stat-card');if(rows.length&&cards.length)return 'QA_PAGE_READY rows='+rows.length;await new Promise(function(r){setTimeout(r,250)})}return 'QA_PAGE_TIMEOUT url='+location.pathname})()"

echo "=== [7/10] filter: 检索为空 (expect 共 10 条) ==="
$AB eval "(async function(){
  function clickSel(sel){var input=sel.querySelector('input.el-select__input')||sel.querySelector('input');if(input){input.click();}else{var w=sel.querySelector('.el-select__wrapper')||sel;w.click();}}
  function findItem(text){
    return Array.prototype.filter.call(document.querySelectorAll('.el-select-dropdown__item'),function(el){
      var r=el.getBoundingClientRect();
      return r.height>0&&getComputedStyle(el).visibility!=='hidden'&&el.textContent.trim()===text;
    });
  }
  var selects=document.querySelectorAll('.logs-filters .el-select');
  if(!selects.length)return 'NO_SELECT';
  clickSel(selects[0]);
  var item=null;
  for(var i=0;i<30;i++){
    var items=findItem('检索为空');
    if(items.length){item=items[0];break;}
    await new Promise(function(r){setTimeout(r,150)});
  }
  if(!item)return 'EMPTY_OPTION_NOT_FOUND';
  item.click();
  for(var j=0;j<40;j++){
    var t=document.querySelector('.pager .el-pagination__total');
    if(t&&t.textContent.indexOf('10')>=0&&t.textContent.indexOf('48')<0)return 'FILTER_EMPTY_OK total='+t.textContent.trim();
    await new Promise(function(r){setTimeout(r,200)});
  }
  return 'FILTER_EMPTY_TIMEOUT last='+((document.querySelector('.pager .el-pagination__total')||{}).textContent||'none');
})()"
$AB screenshot "$SHOT_DIR/qa-quality-filter-empty.png"

echo "=== [8/10] filter: 学生差评 (expect 共 2 条) ==="
$AB eval "(async function(){
  function clickSel(sel){var input=sel.querySelector('input.el-select__input')||sel.querySelector('input');if(input){input.click();}else{var w=sel.querySelector('.el-select__wrapper')||sel;w.click();}}
  function findItem(text){
    return Array.prototype.filter.call(document.querySelectorAll('.el-select-dropdown__item'),function(el){
      var r=el.getBoundingClientRect();
      return r.height>0&&getComputedStyle(el).visibility!=='hidden'&&el.textContent.trim()===text;
    });
  }
  var selects=document.querySelectorAll('.logs-filters .el-select');
  clickSel(selects[0]);
  var item=null;
  for(var i=0;i<30;i++){
    var items=findItem('学生差评');
    if(items.length){item=items[0];break;}
    await new Promise(function(r){setTimeout(r,150)});
  }
  if(!item)return 'DISLIKED_OPTION_NOT_FOUND';
  item.click();
  for(var j=0;j<40;j++){
    var t=document.querySelector('.pager .el-pagination__total');
    if(t&&t.textContent.indexOf('共 2 条')>=0)return 'FILTER_DISLIKED_OK total='+t.textContent.trim();
    await new Promise(function(r){setTimeout(r,200)});
  }
  return 'FILTER_DISLIKED_TIMEOUT last='+((document.querySelector('.pager .el-pagination__total')||{}).textContent||'none');
})()"
$AB screenshot "$SHOT_DIR/qa-quality-filter-disliked.png"

echo "=== [9/10] click first row => drawer detail ==="
$AB eval "(async function(){
  var rows=document.querySelectorAll('.qa-issues-table .el-table__row');
  if(!rows.length)return 'NO_ROWS';
  rows[0].click();
  for(var i=0;i<40;i++){
    var d=document.querySelector('.issue-detail');
    if(d){
      var q=((d.querySelector('.detail-text')||{}).textContent||'').trim();
      var hasBad=d.textContent.indexOf('无用')>=0;
      var hasEmptyCite=d.querySelector('.empty-cite')?true:false;
      return 'DRAWER_OK feedback_bad='+hasBad+' emptyCite='+hasEmptyCite+' question='+q.slice(0,24);
    }
    await new Promise(function(r){setTimeout(r,150)});
  }
  return 'DRAWER_TIMEOUT';
})()"
$AB screenshot "$SHOT_DIR/qa-quality-drawer.png"

echo "=== [10/10] reset type=all + course filter (expect 共 40 条) ==="
$AB eval "(async function(){
  function clickSel(sel){var input=sel.querySelector('input.el-select__input')||sel.querySelector('input');if(input){input.click();}else{var w=sel.querySelector('.el-select__wrapper')||sel;w.click();}}
  function findItem(text){
    return Array.prototype.filter.call(document.querySelectorAll('.el-select-dropdown__item'),function(el){
      var r=el.getBoundingClientRect();
      return r.height>0&&getComputedStyle(el).visibility!=='hidden'&&el.textContent.trim()===text;
    });
  }
  var selects=document.querySelectorAll('.logs-filters .el-select');
  clickSel(selects[0]);
  var opt=null;
  for(var i=0;i<30;i++){
    var items=findItem('全部问题');
    if(items.length){opt=items[0];break;}
    await new Promise(function(r){setTimeout(r,150)});
  }
  if(!opt)return 'ALL_OPTION_NOT_FOUND';
  opt.click();
  for(var j=0;j<40;j++){
    var t=document.querySelector('.pager .el-pagination__total');
    if(t&&t.textContent.indexOf('共 48 条')>=0)break;
    await new Promise(function(r){setTimeout(r,200)});
  }
  return 'RESET_ALL_DONE';
})()"
$AB eval "(async function(){
  function clickSel(sel){var input=sel.querySelector('input.el-select__input')||sel.querySelector('input');if(input){input.click();}else{var w=sel.querySelector('.el-select__wrapper')||sel;w.click();}}
  var selects=document.querySelectorAll('.logs-filters .el-select');
  clickSel(selects[1]);
  var opt=null;
  for(var i=0;i<30;i++){
    var items=Array.prototype.filter.call(document.querySelectorAll('.el-select-dropdown__item'),function(el){
      var r=el.getBoundingClientRect();
      return r.height>0&&getComputedStyle(el).visibility!=='hidden'&&el.textContent.trim().indexOf('真实测试课程')===0;
    });
    if(items.length){opt=items[0];break;}
    await new Promise(function(r){setTimeout(r,150)});
  }
  if(!opt)return 'COURSE_OPTION_NOT_FOUND';
  opt.click();
  for(var j=0;j<40;j++){
    var t=document.querySelector('.pager .el-pagination__total');
    if(t&&t.textContent.indexOf('40')>=0)return 'COURSE_FILTER_OK total='+t.textContent.trim();
    await new Promise(function(r){setTimeout(r,200)});
  }
  return 'COURSE_FILTER_TIMEOUT last='+((document.querySelector('.pager .el-pagination__total')||{}).textContent||'none');
})()"
$AB screenshot "$SHOT_DIR/qa-quality-course-filter.png"
echo "=== chain 2 done ==="
