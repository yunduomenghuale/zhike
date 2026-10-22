#!/bin/bash
# 页面精简 E2E：删「教学质量」eyebrow + 描述/口径说明改问号图标悬停展示
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

echo "=== [2/4] reopen + wait ==="
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<60;i++){if(document.querySelector('.window-note'))return 'PAGE_READY';await new Promise(function(r){setTimeout(r,250)})}return 'PAGE_TIMEOUT'})()"

echo "=== [3/4] assert: eyebrow/desc gone + icons present ==="
$AB eval "(async function(){
  var body=document.body.innerText;
  var eyebrowGone=body.indexOf('教学质量')<0;
  var descGone=body.indexOf('学生向 AI 助手提问的检索命中')<0
            &&body.indexOf('发现课程资料覆盖盲区')<0;
  var scopeGone=body.indexOf('统计范围为本人负责课程的学生提问')<0;
  // h1 旁问号图标
  var h1=document.querySelector('.page-head h1');
  var h1Icon=h1?h1.querySelector('.qa-help'):null;
  var h1IconOk=false;
  if(h1Icon){
    var r=h1Icon.getBoundingClientRect();var cs=getComputedStyle(h1Icon);
    h1IconOk=r.width>=14&&r.height>=14&&cs.borderRadius!=='0px'&&!!h1Icon.querySelector('svg');
  }
  // window-note 旁问号图标
  var wn=document.querySelector('.window-note');
  var wnIcon=wn?wn.querySelector('.qa-help'):null;
  var ok=eyebrowGone&&descGone&&scopeGone&&h1IconOk&&!!wnIcon;
  return (ok?'DESC_CLEAN_OK':'DESC_CLEAN_FAIL')
    +' eyebrowGone='+eyebrowGone+' descGone='+descGone+' scopeGone='+scopeGone
    +' h1Icon='+(h1IconOk?'16x16-circle-svg':'missing/bad')+' windowNoteIcon='+(!!wnIcon);
})()"

echo "=== [4/4] assert: hover tooltips show the texts ==="
$AB eval "(async function(){
  async function hoverAndRead(el,expect){
    el.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true}));
    el.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));
    for(var i=0;i<25;i++){
      var pops=document.querySelectorAll('.el-popper');
      for(var j=0;j<pops.length;j++){
        var t=pops[j].textContent||'';
        var r=pops[j].getBoundingClientRect();
        if(r.height>0&&t.indexOf(expect)>=0){
          el.dispatchEvent(new MouseEvent('mouseleave',{bubbles:true}));
          return true;
        }
      }
      await new Promise(function(r){setTimeout(r,120)});
    }
    el.dispatchEvent(new MouseEvent('mouseleave',{bubbles:true}));
    return false;
  }
  var h1Icon=document.querySelector('.page-head h1 .qa-help');
  var wnIcon=document.querySelector('.window-note .qa-help');
  if(!h1Icon||!wnIcon)return 'ICONS_MISSING';
  var descOk=await hoverAndRead(h1Icon,'发现课程资料覆盖盲区');
  var scopeOk=await hoverAndRead(wnIcon,'不计入为空率分母');
  return 'TOOLTIP '+(descOk?'DESC_OK':'DESC_FAIL')+' '+(scopeOk?'SCOPE_OK':'SCOPE_FAIL');
})()"
$AB screenshot "$SHOT_DIR/qa-quality-desc-clean.png"
echo "=== done ==="
