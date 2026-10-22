#!/bin/bash
# 引用来源分布归一 E2E：ppt+script 与 script+ppt 合并为「讲解稿+课件」，raw key 不裸奔
cd "$(dirname "$0")"
SHOT_DIR="D:/Claude_Code/智课系统V2/frontend/test/screenshots"
AB="agent-browser"

echo "=== [1/5] set viewport ==="
$AB set viewport 1400 900

echo "=== [2/5] open + login ==="
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<40;i++){if(document.querySelector('input[placeholder=\"请输入用户名\"]'))return 'LOGIN_FORM_READY';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_FORM_TIMEOUT'})()"
$AB fill 'input[placeholder="请输入用户名"]' t101
$AB fill 'input[placeholder="请输入密码"]' pass1234
$AB click 'button.auth-submit'
$AB eval "(async function(){for(var i=0;i<50;i++){if(localStorage.getItem('access_token'))return 'LOGIN_OK';await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT'})()"

echo "=== [3/5] reopen + wait page ready ==="
$AB open http://localhost:5273/teacher/qa-quality
$AB eval "(async function(){for(var i=0;i<60;i++){var rows=document.querySelectorAll('.dist-row.dist-static');if(rows.length)return 'DIST_READY rows='+rows.length;await new Promise(function(r){setTimeout(r,250)})}return 'DIST_TIMEOUT url='+location.pathname})()"

echo "=== [4/5] assert source distribution ==="
$AB eval "(async function(){
  for(var i=0;i<40;i++){if(document.querySelectorAll('.dist-row').length)break;await new Promise(function(r){setTimeout(r,200)})}
  // 定位「引用来源分布」卡（h3 标题匹配），避免混入「上下文降级分布」卡的 dist-row
  var srcCard=null;var cards=document.querySelectorAll('section,div');
  for(var k=0;k<cards.length;k++){
    var h=cards[k].querySelector?cards[k].querySelector('h3'):null;
    if(h&&h.textContent.indexOf('引用来源分布')>=0){srcCard=cards[k];break;}
  }
  if(!srcCard)return 'NO_SRC_CARD';
  var rows=Array.prototype.map.call(srcCard.querySelectorAll('.dist-row'),function(el){
    return {label:(el.querySelector('.dist-name')||{}).textContent.trim(),
            count:Number((el.querySelector('.dist-calls')||{}).textContent.trim())};
  });
  var rawKeyLeak=srcCard.textContent.indexOf('ppt+script')>=0
              ||srcCard.textContent.indexOf('script+ppt')>=0;
  var legal={'知识库资料':1,'讲解稿':1,'课件 PPT':1,'讲解稿+课件':1,'其他':1};
  var allLegal=rows.every(function(r){return legal[r.label];});
  var merged=rows.filter(function(r){return r.label==='讲解稿+课件'});
  var ok=!rawKeyLeak&&allLegal&&merged.length===1&&merged[0].count>=3;
  return (ok?'SOURCE_MERGE_OK':'SOURCE_MERGE_FAIL')
    +' rawKeyLeak='+rawKeyLeak+' allLegal='+allLegal
    +' rows='+JSON.stringify(rows);
})()"
$AB screenshot "$SHOT_DIR/qa-quality-source-merged.png"

echo "=== [5/5] check by_source API directly ==="
curl -s --noproxy '*' http://localhost:8005/api/qa-quality-stats/ -H "Authorization: Bearer $(curl -s --noproxy '*' -X POST http://localhost:8005/api/auth/login/ -H 'Content-Type: application/json' -d '{"username":"t101","password":"pass1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token']['access'])")" 2>/dev/null | head -c 200
echo ""
echo "=== done ==="
