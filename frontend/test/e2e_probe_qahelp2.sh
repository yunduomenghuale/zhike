#!/bin/bash
# 探针 2：.qa-help 的 DOM 祖先链 + :deep 可行性
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

echo "=== ancestor chain of .qa-help ==="
$AB eval "(function(){
  var el=document.querySelector('.qa-help');
  if(!el)return 'NO_QA_HELP';
  var chain=[];
  var node=el;
  while(node&&node!==document.body){
    chain.push(node.tagName.toLowerCase()+(node.className&&typeof node.className==='string'?'.'+node.className.trim().split(/\s+/).join('.'):'')+(node.getAttribute('data-v-7a3f1c2e')?'[scoped]':''));
    node=node.parentElement;
  }
  var hasScopedAncestor=false;
  node=el.parentElement;
  while(node){
    for(var i=0;i<node.attributes.length;i++){
      if(node.attributes[i].name.indexOf('data-v-')===0){hasScopedAncestor=true;break;}
    }
    node=node.parentElement;
  }
  return 'CHAIN: '+chain.join(' < ')+' || scoped_ancestor='+hasScopedAncestor;
})()"
echo "=== probe done ==="
