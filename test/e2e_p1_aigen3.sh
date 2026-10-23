#!/bin/bash
# E2E 链2c（阶段5）：AI 生题「离开页面不丢失」——提交 → 离开 → 返回恢复横幅 → 完成自动开预览 → 入库
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_p1_aigen3.log
AB=agent-browser
mkdir -p test/screenshots
: > "$LOG"

eval_retry() {
  local out
  out=$($AB eval "$1" 2>>"$LOG")
  if ! echo "$out" | grep -qE "$2"; then
    out=$($AB eval "$1" 2>>"$LOG")
  fi
  echo "$out"
}
domclick() {
  eval_retry "(function(){var els=document.querySelectorAll('$1'); if(!els.length) return 'DOMCLICK_MISS $1'; els[0].click(); return 'DOMCLICK_OK'})()" 'DOMCLICK_OK'
}
mark() { echo "[$1] $2"; }
fail() { echo "E2E_FAIL $1: $2"; exit 1; }

$AB close --all >>"$LOG" 2>&1
$AB open http://127.0.0.1:5273/login >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入用户名"]' t101 >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入密码"]' pass1234 >>"$LOG" 2>&1
$AB click '.auth-submit' >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<50;i++){if(location.pathname.indexOf('/login')<0 && document.querySelector('#app')) return 'LANDED '+location.pathname; await new Promise(r=>setTimeout(r,300));} return 'LOGIN_TIMEOUT'})()" 'LANDED')
mark login "$OUT"
echo "$OUT" | grep -q 'LANDED /' || fail login "$OUT"

$AB open http://127.0.0.1:5273/teacher/courses/6/questions >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(document.querySelector('.q-btn-ai')) return 'QPAGE_READY'; await new Promise(r=>setTimeout(r,300));} return 'QPAGE_TIMEOUT'})()" 'QPAGE_READY')
mark qpage "$OUT"
echo "$OUT" | grep -q 'QPAGE_READY' || fail qpage "$OUT"

# 配置生题：单选 2 + 判断 1 + 填空 1，章节选第1章 线性表
OUT=$(domclick '.q-btn-ai')
mark open-aigen "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail open-aigen "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.ai-gen-dialog'); if(d && d.offsetParent!==null) return 'DLG_READY'; await new Promise(r=>setTimeout(r,250));} return 'DLG_TIMEOUT'})()" 'DLG_READY')
echo "$OUT" | grep -q 'DLG_READY' || fail aigen-dlg "$OUT"
$AB fill '.aig-group-row:nth-child(1) .aig-num input' '2' >>"$LOG" 2>&1
OUT=$(domclick '.aig-group-row:nth-child(3) .el-checkbox__inner')
$AB fill '.aig-group-row:nth-child(3) .aig-num input' '1' >>"$LOG" 2>&1
OUT=$(domclick '.aig-group-row:nth-child(4) .el-checkbox__inner')
$AB fill '.aig-group-row:nth-child(4) .aig-num input' '1' >>"$LOG" 2>&1
$AB click '.aig-form .el-select__wrapper' >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var pops=document.querySelectorAll('.el-select__popper'); var vis=[]; pops.forEach(function(p){var st=getComputedStyle(p); if(st.display!=='none'&&st.visibility!=='hidden'){var its=p.querySelectorAll('.el-select-dropdown__item'); if(its.length) vis.push(p)}}); if(vis.length) return 'POPPER_OK'; await new Promise(r=>setTimeout(r,200));} return 'POPPER_TIMEOUT'})()" 'POPPER_OK')
echo "$OUT" | grep -q 'POPPER_OK' || fail popper "$OUT"
OUT=$(eval_retry "(function(){var pops=document.querySelectorAll('.el-select__popper'); for(var i=0;i<pops.length;i++){var p=pops[i]; var st=getComputedStyle(p); if(st.display!=='none'&&st.visibility!=='hidden'){var its=p.querySelectorAll('.el-select-dropdown__item'); for(var j=0;j<its.length;j++){if(its[j].innerText.indexOf('第1章 线性表')>=0){its[j].click(); return 'OPT_CLICKED'}}}} return 'OPT_NOT_FOUND'})()" 'OPT_CLICKED')
echo "$OUT" | grep -q 'OPT_CLICKED' || fail opt "$OUT"
OUT=$(domclick '.ai-gen-dialog .q-btn-primary')
mark submit "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail submit "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var b=document.querySelector('.ai-active-banner'); if(b) return 'BANNER1'; await new Promise(r=>setTimeout(r,300));} return 'BANNER1_TIMEOUT'})()" 'BANNER1')
mark banner-submit "$OUT"
echo "$OUT" | grep -q 'BANNER1' || fail banner-submit "$OUT"

# 离开页面（去工作台）→ 再回题库页：横幅应恢复（active 端点续轮询）
$AB open http://127.0.0.1:5273/dashboard >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){if(location.pathname==='/dashboard') return 'ON_DASH'; await new Promise(r=>setTimeout(r,300));} return 'DASH_TIMEOUT'})()" 'ON_DASH')
mark leave "$OUT"
$AB open http://127.0.0.1:5273/teacher/courses/6/questions >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var b=document.querySelector('.ai-active-banner'); if(b){var msg=document.querySelector('.ai-active-msg'); return 'RECOVER_BANNER msg='+(msg?msg.innerText.slice(0,40):'-')} await new Promise(r=>setTimeout(r,300));} return 'RECOVER_TIMEOUT'})()" 'RECOVER_BANNER')
mark recover "$OUT"
echo "$OUT" | grep -q 'RECOVER_BANNER' || fail recover "$OUT"
$AB screenshot test/screenshots/e2e-p1-aigen-recover-banner.png >>"$LOG" 2>&1

# 等终态自动打开预览
OUT=$(eval_retry "(async function(){for(var i=0;i<110;i++){var d=document.querySelector('.draft-preview-drawer'); if(d && document.querySelectorAll('.dp-card').length) return 'AUTO_OPEN cards='+document.querySelectorAll('.dp-card').length; await new Promise(r=>setTimeout(r,1000));} return 'AUTO_TIMEOUT'})()" 'AUTO_OPEN')
mark auto-open "$OUT"
echo "$OUT" | grep -q 'AUTO_OPEN' || fail auto-open "$OUT"
OUT=$(eval_retry "(function(){var tag=document.querySelector('.dp-origin-tag'); var sel=document.querySelector('.dp-summary .el-select__wrapper'); return 'PREVIEW origin='+(tag?tag.innerText.trim():'-')+' catalog='+(sel?sel.innerText.replace(/\\s+/g,' ').trim():'-')})()" 'PREVIEW')
mark preview "$OUT"
echo "$OUT" | grep -q 'origin=AI 生成' || fail origin "$OUT"
echo "$OUT" | grep -q 'catalog=第1章 线性表' || fail catalog-preset "$OUT"
$AB screenshot test/screenshots/e2e-p1-aigen-recover-preview.png >>"$LOG" 2>&1

# 入库
OUT=$(domclick '.dp-footer-actions .el-button--primary')
mark save "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var ms=document.querySelector('.el-message'); if(ms && ms.innerText.indexOf('已入库')>=0) return 'SAVED '+ms.innerText.replace(/\\s+/g,' ').slice(0,60); await new Promise(r=>setTimeout(r,300));} return 'SAVE_TIMEOUT'})()" 'SAVED')
mark save-msg "$OUT"
echo "$OUT" | grep -q 'SAVED' || fail save-msg "$OUT"
SAVED_N=$(echo "$OUT" | grep -o '已入库 [0-9]*' | grep -o '[0-9]*' | head -1)
EXPECT=$((13 + ${SAVED_N:-0}))
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var rows=document.querySelectorAll('.q-row'); var d=document.querySelector('.draft-preview-drawer'); var hidden=true; if(d){var st=getComputedStyle(d); var ov=d.closest('.el-overlay'); var ovs=ov?getComputedStyle(ov):null; hidden=st.display==='none'||(ovs&&ovs.display==='none')||d.getBoundingClientRect().width===0} if(rows.length===$EXPECT && hidden) return 'ROWS'+rows.length; await new Promise(r=>setTimeout(r,300));} return 'ROWS_MISMATCH count='+document.querySelectorAll('.q-row').length+' expect=$EXPECT'})()" "ROWS$EXPECT")
mark rows "$OUT"
echo "$OUT" | grep -q "ROWS$EXPECT" || fail rows "$OUT"

$AB close --all >>"$LOG" 2>&1
echo "E2E_CHAIN2C_PASS"
