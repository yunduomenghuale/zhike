#!/bin/bash
# E2E 链2a（阶段5）：AI 多类型生题——配置（3 题型 4 题）+ 选章节 + 提交 + 进度横幅
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_p1_aigen.log
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

# 打开 AI 生题弹窗
OUT=$(domclick '.q-btn-ai')
mark open-aigen "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail open-aigen "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.ai-gen-dialog'); if(d && d.offsetParent!==null) return 'DLG_READY'; await new Promise(r=>setTimeout(r,250));} return 'DLG_TIMEOUT'})()" 'DLG_READY')
mark aigen-dlg "$OUT"
echo "$OUT" | grep -q 'DLG_READY' || fail aigen-dlg "$OUT"

# 题型配置：单选 2 题（默认已勾选）/ 判断 1 题 / 填空 1 题
$AB fill '.aig-group-row:nth-child(1) .aig-num input' '2' >>"$LOG" 2>&1
OUT=$(domclick '.aig-group-row:nth-child(3) .el-checkbox__inner')
mark chk-judge "$OUT"
$AB fill '.aig-group-row:nth-child(3) .aig-num input' '1' >>"$LOG" 2>&1
OUT=$(domclick '.aig-group-row:nth-child(4) .el-checkbox__inner')
mark chk-blank "$OUT"
$AB fill '.aig-group-row:nth-child(4) .aig-num input' '1' >>"$LOG" 2>&1
OUT=$(eval_retry "(function(){var rows=document.querySelectorAll('.aig-group-row'); var out=[]; rows.forEach(function(r,i){var cb=r.querySelector('.el-checkbox__input'); var on=cb&&cb.className.indexOf('is-checked')>=0; var nums=r.querySelectorAll('.aig-num input'); var cv=[]; nums.forEach(function(n){cv.push(n.value)}); out.push((i+1)+':on='+(on?'Y':'N')+' nums='+cv.join('/'))}); var t=document.querySelector('.aig-total'); return 'GROUPS '+out.join(' | ')+' total='+(t?t.innerText.replace(/\\s+/g,' '):'-')})()" 'GROUPS')
mark groups "$OUT"
echo "$OUT" | grep -q '1:on=Y nums=2' || fail group-single "$OUT"
echo "$OUT" | grep -q '3:on=Y nums=1' || fail group-judge "$OUT"
echo "$OUT" | grep -q '4:on=Y nums=1' || fail group-blank "$OUT"
echo "$OUT" | grep -qE '合计 <b>4</b>|合计 4' || fail group-total "$OUT"

# 选择章节：第2章 栈和队列（EP 选项类名 .el-select-dropdown__item）
$AB click '.aig-form .el-select__wrapper' >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var pops=document.querySelectorAll('.el-select__popper'); var vis=[]; pops.forEach(function(p){var st=getComputedStyle(p); if(st.display!=='none'&&st.visibility!=='hidden'){var its=p.querySelectorAll('.el-select-dropdown__item'); if(its.length) vis.push(p)}}); if(vis.length) return 'POPPER_ITEMS_OK'; await new Promise(r=>setTimeout(r,200));} return 'POPPER_ITEMS_TIMEOUT'})()" 'POPPER_ITEMS_OK')
mark popper "$OUT"
echo "$OUT" | grep -q 'POPPER_ITEMS_OK' || fail popper "$OUT"
OUT=$(eval_retry "(function(){var pops=document.querySelectorAll('.el-select__popper'); for(var i=0;i<pops.length;i++){var p=pops[i]; var st=getComputedStyle(p); if(st.display!=='none'&&st.visibility!=='hidden'){var its=p.querySelectorAll('.el-select-dropdown__item'); for(var j=0;j<its.length;j++){if(its[j].innerText.indexOf('第2章 栈和队列')>=0){its[j].click(); return 'OPT_CLICKED'}}}} return 'OPT_NOT_FOUND'})()" 'OPT_CLICKED')
mark opt "$OUT"
echo "$OUT" | grep -q 'OPT_CLICKED' || fail opt "$OUT"

# 开始生成
OUT=$(domclick '.ai-gen-dialog .q-btn-primary')
mark submit "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail submit "$OUT"

# 弹窗关闭 + 进度横幅出现（离开页面不丢失的入口）
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var d=document.querySelector('.ai-gen-dialog'); var b=document.querySelector('.ai-active-banner'); if(b){var msg=document.querySelector('.ai-active-msg'); return 'BANNER_OK dlgOpen='+(d&&d.offsetParent!==null?'Y':'N')+' msg='+(msg?msg.innerText.slice(0,40):'-')} await new Promise(r=>setTimeout(r,300));} return 'BANNER_TIMEOUT'})()" 'BANNER_OK')
mark banner "$OUT"
echo "$OUT" | grep -q 'BANNER_OK' || fail banner "$OUT"
$AB screenshot test/screenshots/e2e-p1-aigen-banner.png >>"$LOG" 2>&1

$AB close --all >>"$LOG" 2>&1
echo "E2E_CHAIN2A_PASS"
