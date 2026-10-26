#!/bin/bash
# E2E：题目预览页/手动弹窗表单布局修复验证
# 断言：① 手动弹窗表单真实渲染（:model 修复前为空白）② top 模式 label 在控件上方
#       ③ 预览抽屉 72px 标签列对齐（所有行 label/content left 一致）④ 选项行 input 占满
#       ⑤ 答案按钮两态等宽（文案切换不抖动）
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_layout.log
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
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(document.querySelector('.q-btn-import')) return 'QPAGE_READY rows='+document.querySelectorAll('.q-row').length; await new Promise(r=>setTimeout(r,300));} return 'QPAGE_TIMEOUT'})()" 'QPAGE_READY')
mark qpage "$OUT"
echo "$OUT" | grep -q 'QPAGE_READY' || fail qpage "$OUT"

# ============ 1. 手动新建弹窗：表单真实渲染 + top 模式标签在上 ============
OUT=$(domclick '.q-btn-primary')
mark open-create "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.question-form-dialog'); if(d){var b=d.querySelector('.el-dialog__body'); if(b && b.offsetParent!==null) return 'CDLG_READY';} await new Promise(r=>setTimeout(r,250));} return 'CDLG_TIMEOUT'})()" 'CDLG_READY')
mark create-dlg "$OUT"
echo "$OUT" | grep -q 'CDLG_READY' || fail create-dlg "$OUT"

# 表单字段真实渲染（:model 修复前 props.model 为 undefined，此处为空白/报错）
OUT=$(eval_retry "(function(){var d=document.querySelector('.question-form-dialog'); var ta=d.querySelectorAll('.el-textarea__inner').length; var sel=d.querySelectorAll('.el-select__wrapper').length; var qff=!!d.querySelector('.qff'); return 'CFIELDS textarea='+ta+' select='+sel+' qff='+qff})()" 'CFIELDS')
mark create-fields "$OUT"
echo "$OUT" | grep -qE 'textarea=[1-9].*select=[1-9].*qff=true' || fail create-fields "$OUT"

# top 模式：label 在控件上方（label 底部 <= content 顶部）
OUT=$(eval_retry "(function(){var d=document.querySelector('.question-form-dialog'); var items=d.querySelectorAll('.qff .el-form-item'); if(!items.length) return 'NO_ITEMS'; var ok=true, n=0; items.forEach(function(it){var l=it.querySelector('.el-form-item__label'); var c=it.querySelector('.el-form-item__content'); if(!l||!c) return; var lb=l.getBoundingClientRect(), cb=c.getBoundingClientRect(); if(lb.bottom > cb.top + 1) ok=false; n++;}); return 'TOPMODE ok='+ok+' items='+n})()" 'TOPMODE')
mark create-top "$OUT"
echo "$OUT" | grep -q 'TOPMODE ok=true' || fail create-top "$OUT"
$AB screenshot test/screenshots/e2e-layout-create.png >>"$LOG" 2>&1
OUT=$(domclick '.question-form-dialog .creation-dialog-close')
mark create-close "$OUT"

# ============ 2. 导入 → 预览抽屉：标签列对齐 + 选项行占满 ============
OUT=$(domclick '.q-btn-import')
mark open-import "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.import-dialog'); if(d && d.offsetParent!==null) return 'DLG_READY'; await new Promise(r=>setTimeout(r,250));} return 'DLG_TIMEOUT'})()" 'DLG_READY')
mark import-dlg "$OUT"
echo "$OUT" | grep -q 'DLG_READY' || fail import-dlg "$OUT"

$AB upload '.import-uploader input[type=file]' 'D:/Claude_Code/智课系统V2/test/e2e/import-e2e-v1.txt' >>"$LOG" 2>&1
# 选择即上传解析（无「解析并预览」按钮）：等预览抽屉自动打开
OUT=$(eval_retry "(async function(){for(var i=0;i<80;i++){var d=document.querySelector('.draft-preview-drawer'); if(d){var cards=document.querySelectorAll('.dp-card'); if(cards.length) return 'DRAWER_READY cards='+cards.length;} await new Promise(r=>setTimeout(r,250));} return 'DRAWER_TIMEOUT'})()" 'DRAWER_READY')
mark drawer "$OUT"
echo "$OUT" | grep -q 'DRAWER_READY cards=7' || fail drawer "$OUT"

# 核心断言：所有卡片所有行的 label left / content left 各自唯一（72px 标签列对齐）
OUT=$(eval_retry "(function(){
  var drawer=document.querySelector('.draft-preview-drawer');
  var cards=drawer.querySelectorAll('.dp-card');
  var labelLefts={}, contentLefts={}, optInfo=[];
  cards.forEach(function(card,ci){
    card.querySelectorAll('.el-form-item').forEach(function(it){
      var l=it.querySelector('.el-form-item__label');
      var c=it.querySelector('.el-form-item__content');
      if(!l||!c) return;
      var lx=Math.round(l.getBoundingClientRect().left);
      var cx=Math.round(c.getBoundingClientRect().left);
      labelLefts[lx]=(labelLefts[lx]||0)+1;
      contentLefts[cx]=(contentLefts[cx]||0)+1;
    });
    var row=card.querySelector('.opt-row');
    if(row){
      var ir=row.querySelector('.el-input');
      var btn=row.querySelector('.opt-correct-btn');
      optInfo.push(ci+':input='+(ir?Math.round(ir.getBoundingClientRect().width):-1)+',btn='+(btn?Math.round(btn.getBoundingClientRect().width):-1));
    }
  });
  var lk=Object.keys(labelLefts), ck=Object.keys(contentLefts);
  return 'ALIGN ok='+(lk.length===1&&ck.length===1)+' labelKeys='+lk.join('|')+' contentKeys='+ck.join('|')+' opt='+optInfo.join(' ; ');
})()" 'ALIGN')
mark align "$OUT"
echo "$OUT" | grep -q 'ALIGN ok=true' || fail align "$OUT"
# 选项 input 占满（flex:1，宽度应 >400px）
echo "$OUT" | grep -qE 'input=[4-9][0-9][0-9]' || fail align-input "$OUT"

# 答案按钮两态等宽（点击后文案「设为答案」↔「✓ 正确答案」，宽度不变）
OUT1=$(eval_retry "(function(){var card=document.querySelector('.draft-preview-drawer .dp-card'); var btn=card.querySelector('.opt-correct-btn'); var w=Math.round(btn.getBoundingClientRect().width); btn.click(); return 'BTN_W1 '+w})()" 'BTN_W1')
mark btn-before "$OUT1"
OUT2=$(eval_retry "(function(){var card=document.querySelector('.draft-preview-drawer .dp-card'); var btn=card.querySelector('.opt-correct-btn'); return 'BTN_W2 '+Math.round(btn.getBoundingClientRect().width)+' txt='+btn.innerText.trim()})()" 'BTN_W2')
mark btn-after "$OUT2"
W1=$(echo "$OUT1" | sed -E 's/.*BTN_W1 ([0-9]+).*/\1/')
W2=$(echo "$OUT2" | sed -E 's/.*BTN_W2 ([0-9]+).*/\1/')
[ -n "$W1" ] && [ -n "$W2" ] && [ "$W1" = "$W2" ] || fail btn-width "W1=$W1 W2=$W2"

$AB screenshot test/screenshots/e2e-layout-preview.png >>"$LOG" 2>&1

# ============ 3. 清理：放弃批次（不留 E2E 数据） ============
OUT=$(eval_retry "(function(){var btns=document.querySelectorAll('.dp-footer .el-button'); var t=null; btns.forEach(function(b){if(b.innerText.indexOf('放弃批次')>=0) t=b;}); if(!t) return 'DOMCLICK_MISS discard'; t.click(); return 'DOMCLICK_OK'})()" 'DOMCLICK_OK')
mark discard "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail discard "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var b=document.querySelector('.el-message-box'); if(b && b.offsetParent!==null) return 'CONFIRM_READY'; await new Promise(r=>setTimeout(r,250));} return 'CONFIRM_TIMEOUT'})()" 'CONFIRM_READY')
mark confirm "$OUT"
echo "$OUT" | grep -q 'CONFIRM_READY' || fail confirm "$OUT"
OUT=$(domclick '.el-message-box .el-button--primary')
mark confirm-ok "$OUT"
# EP 2.14 el-drawer 关闭后根本身 display 保持 flex，不可见性由外层 overlay 控制 → 查 offsetParent
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.draft-preview-drawer'); if(d && d.offsetParent===null) return 'DRAWER_CLOSED'; await new Promise(r=>setTimeout(r,250));} return 'CLOSE_TIMEOUT'})()" 'DRAWER_CLOSED')
mark closed "$OUT"
echo "$OUT" | grep -q 'DRAWER_CLOSED' || fail closed "$OUT"

echo "LAYOUT_E2E_OK"
