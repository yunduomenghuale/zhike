#!/bin/bash
# 探测班级详情抽屉表格溢出形态：裁剪 or 可滚动
set -u
export AB="/c/Users/张文飞/.workbuddy/binaries/node/versions/22.22.2-6/agent-browser"
BASE="http://127.0.0.1:5273"
run() { env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy "$AB" "$@"; }

run open "$BASE/login" >/dev/null 2>&1
run fill "input[placeholder='请输入用户名']" "admin" >/dev/null
run fill "input[placeholder='请输入密码']" "A0987654" >/dev/null
run click "button.auth-submit" >/dev/null
run open "$BASE/admin/teaching" >/dev/null 2>&1
run eval "var items=document.querySelectorAll('.admin-tabs .el-tabs__item');if(items.length>1){items[1].click();'TAB_CLASS'}" >/dev/null
sleep 1
run click ".el-table__row" >/dev/null
run eval "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.class-drawer');if(d&&document.body.textContent.indexOf('逐学生学习进度')>=0){
  var body=d.querySelector('.el-drawer__body');
  var tbl=d.querySelector('.el-table');
  var wrap=d.querySelector('.el-scrollbar__wrap')||d.querySelector('.el-table__inner-wrapper');
  var r=body.getBoundingClientRect();
  var msg='PROBE bodyClient='+body.clientWidth+' bodyScroll='+body.scrollWidth;
  if(tbl){var tr=tbl.getBoundingClientRect();msg+=' tableW='+Math.round(tr.width)+' tableRight='+Math.round(tr.right)+' bodyRight='+Math.round(r.right)}
  msg+=' bodyOverflowX='+(body.scrollWidth>body.clientWidth);
  return msg}await new Promise(function(r){setTimeout(r,250)})}return 'PROBE_TIMEOUT'})()"
run close >/dev/null 2>&1
echo PROBE_DONE
