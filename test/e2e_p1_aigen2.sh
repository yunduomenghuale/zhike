#!/bin/bash
# E2E 链2b（阶段5）：AI 生题刷新恢复 + 完成自动开预览 + 批量入库
# 覆盖：离开页面后重新进入 → active 端点恢复轮询（横幅）→ 终态自动打开草稿预览
#       → 章节预设（批次继承任务章节）→ 全部入库 → 列表刷新
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_p1_aigen2.log
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

# 重新进入题库页：任务仍在跑 → 恢复横幅；已完成 → 打开草稿批次弹窗可见批次行
$AB open http://127.0.0.1:5273/teacher/courses/6/questions >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var b=document.querySelector('.ai-active-banner'); if(b) return 'RECOVER_BANNER'; await new Promise(r=>setTimeout(r,300));} return 'NO_BANNER'})()" 'RECOVER_BANNER|NO_BANNER')
mark recover "$OUT"
if echo "$OUT" | grep -q 'RECOVER_BANNER'; then
  # 恢复横幅（离开页面不丢失的核心证据）
  $AB screenshot test/screenshots/e2e-p1-aigen-recover.png >>"$LOG" 2>&1
  # 轮询直到终态自动打开预览（onSuccess → openPreview(batch_id)）
  OUT=$(eval_retry "(async function(){for(var i=0;i<110;i++){var d=document.querySelector('.draft-preview-drawer'); if(d && document.querySelectorAll('.dp-card').length) return 'AUTO_OPEN cards='+document.querySelectorAll('.dp-card').length; var e=document.querySelector('.el-message--error'); if(e) return 'ERR_MSG '+e.innerText.slice(0,60); await new Promise(r=>setTimeout(r,1000));} return 'AUTO_TIMEOUT'})()" 'AUTO_OPEN|ERR_MSG')
  mark auto-open "$OUT"
  echo "$OUT" | grep -q 'AUTO_OPEN' || fail auto-open "$OUT"
else
  # 任务已完成：从批次列表进入预览
  mark auto-open "BATCHLIST_PATH（任务在刷新前已完成）"
  OUT=$(domclick '.q-btn-batch')
  OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var r=document.querySelector('.batch-row'); if(r) return 'BATCHDLG'; await new Promise(r=>setTimeout(r,250));} return 'BATCHDLG_TIMEOUT'})()" 'BATCHDLG')
  echo "$OUT" | grep -q 'BATCHDLG' || fail batchdlg "$OUT"
  OUT=$(domclick '.batch-row-actions .el-button--primary')
  OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var d=document.querySelector('.draft-preview-drawer'); if(d && document.querySelectorAll('.dp-card').length) return 'AUTO_OPEN cards='+document.querySelectorAll('.dp-card').length; await new Promise(r=>setTimeout(r,300));} return 'AUTO_TIMEOUT'})()" 'AUTO_OPEN')
  echo "$OUT" | grep -q 'AUTO_OPEN' || fail auto-open "$OUT"
fi

# 预览断言：来源标签 = AI 生成；章节预设（批次继承任务章节）
OUT=$(eval_retry "(function(){var tag=document.querySelector('.dp-origin-tag'); var sel=document.querySelector('.dp-summary .el-select__wrapper'); var cards=document.querySelectorAll('.dp-card'); var stats=document.querySelector('.dp-stats'); return 'PREVIEW origin='+(tag?tag.innerText.trim():'-')+' catalog='+(sel?sel.innerText.replace(/\\s+/g,' ').trim():'-')+' cards='+cards.length+' stats='+(stats?stats.innerText.replace(/\\s+/g,' ').slice(0,60):'-')})()" 'PREVIEW')
mark preview "$OUT"
echo "$OUT" | grep -q 'origin=AI 生成' || fail origin "$OUT"
echo "$OUT" | grep -q 'catalog=第2章 栈和队列' || fail catalog-preset "$OUT"
CARDS=$(echo "$OUT" | grep -o 'cards=[0-9]*' | grep -o '[0-9]*')
mark cards "$CARDS"
[ "${CARDS:-0}" -ge 3 ] || fail cards "期望 ≥3（3 组配置），实际 $CARDS"
$AB screenshot test/screenshots/e2e-p1-aigen-preview.png >>"$LOG" 2>&1

# 全部入库（章节已预设，按钮应直接可用）
OUT=$(eval_retry "(function(){var b=document.querySelector('.dp-footer-actions .el-button--primary'); return b?('disabled='+b.disabled):'BTN_MISS'})()" 'disabled=')
mark save-btn "$OUT"
echo "$OUT" | grep -q 'disabled=false' || fail save-btn "$OUT"
OUT=$(domclick '.dp-footer-actions .el-button--primary')
mark save "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var ms=document.querySelector('.el-message'); if(ms && ms.innerText.indexOf('已入库')>=0) return 'SAVED '+ms.innerText.replace(/\\s+/g,' ').slice(0,70); await new Promise(r=>setTimeout(r,300));} return 'SAVE_TIMEOUT'})()" 'SAVED')
mark save-msg "$OUT"
echo "$OUT" | grep -q 'SAVED' || fail save-msg "$OUT"
SAVED_N=$(echo "$OUT" | grep -o '已入库 [0-9]*' | grep -o '[0-9]*' | head -1)
mark saved-n "${SAVED_N:-?}"

# 列表刷新：基线 9 + 本次入库数；抽屉关闭（查可见性）
EXPECT=$((9 + ${SAVED_N:-0}))
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var rows=document.querySelectorAll('.q-row'); var d=document.querySelector('.draft-preview-drawer'); var hidden=true; if(d){var st=getComputedStyle(d); var ov=d.closest('.el-overlay'); var ovs=ov?getComputedStyle(ov):null; hidden=st.display==='none'||(ovs&&ovs.display==='none')||d.getBoundingClientRect().width===0} if(rows.length===$EXPECT && hidden) return 'ROWS'+rows.length; await new Promise(r=>setTimeout(r,300));} return 'ROWS_MISMATCH count='+document.querySelectorAll('.q-row').length+' expect=$EXPECT'})()" "ROWS$EXPECT")
mark rows "$OUT"
echo "$OUT" | grep -q "ROWS$EXPECT" || fail rows "$OUT"
$AB screenshot test/screenshots/e2e-p1-aigen-saved.png >>"$LOG" 2>&1

$AB close --all >>"$LOG" 2>&1
echo "E2E_CHAIN2B_PASS"
