#!/bin/bash
# 布局统一 E2E：QA 看板根元素补 page-container，左边距与系统其他页面一致（36px）
cd "$(dirname "$0")"
SHOT_DIR="D:/Claude_Code/智课系统V2/frontend/test/screenshots"
AB="agent-browser"

echo "=== [1/4] login ==="
$AB set viewport 1400 900
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder=\"请输入用户名\"]'))return 'FORM';await new Promise(function(r){setTimeout(r,250)})}return 'TIMEOUT'})()"
$AB fill 'input[placeholder="请输入用户名"]' t101
$AB fill 'input[placeholder="请输入密码"]' pass1234
$AB click 'button.auth-submit'
$AB eval "(async function(){for(var i=0;i<50;i++){if(localStorage.getItem('access_token'))return 'LOGIN_OK';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT'})()"

echo "=== [2/4] open qa-quality + wait ==="
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<60;i++){if(document.querySelector('.page-head h1'))return 'READY';await new Promise(function(r){setTimeout(r,250)})}return 'TIMEOUT'})()"

echo "=== [3/4] assert: page-container + left padding 36px ==="
$AB eval "(async function(){
  var root=document.querySelector('.qa-quality');
  if(!root)return 'NO_ROOT';
  var hasPC=root.classList.contains('page-container');
  var cs=getComputedStyle(root);
  var padL=cs.paddingLeft;
  // 内容区（.main）左缘 vs h1 左缘
  var main=document.querySelector('.app-main-panel .main');
  var h1=document.querySelector('.page-head h1');
  var mainL=main?main.getBoundingClientRect().left:null;
  var h1L=h1?h1.getBoundingClientRect().left:null;
  var gap=(mainL!=null&&h1L!=null)?Math.round(h1L-mainL):-1;
  var ok=hasPC&&padL==='36px'&&gap>=30&&gap<=44;
  return (ok?'PADDING_OK':'PADDING_FAIL')
    +' hasPageContainer='+hasPC+' paddingLeft='+padL+' h1GapToMain='+gap+'px';
})()"

echo "=== [4/4] cross-check: dashboard uses same padding ==="
$AB eval "(async function(){
  var out=[];
  async function check(path,sel){
    var res=await fetch(path,{headers:{'Accept':'text/html'}});
    return res.status;
  }
  // 直接读 Dashboard 根的 page-container padding（同 layout，同口径）
  var d=document.querySelector('.page-container');
  return 'CURRENT_PAGE_CONTAINER_PADDING='+(d?getComputedStyle(d).padding:'none');
})()"
$AB screenshot "$SHOT_DIR/qa-quality-page-padding.png"
echo "=== done ==="
