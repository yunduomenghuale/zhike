#!/bin/bash
# E2E 链1（阶段5）：文档导入 → 解析预览 → 行内编辑 → 防抖回传 → 关闭重开 → 选章节 → 批量入库
# agent-browser 单链执行（daemon 不跨 Bash 调用存活）；全程 >> log
# 经验：弹窗/抽屉存在开关动画，坐标点击易 miss——弹窗内按钮一律 DOM click（eval）
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_p1_import.log
AB=agent-browser
mkdir -p test/screenshots
: > "$LOG"

eval_retry() { # $1=expr $2=marker(ERE) → 输出命中 marker 的 eval 结果（gotcha 8 重试）
  local out
  out=$($AB eval "$1" 2>>"$LOG")
  if ! echo "$out" | grep -qE "$2"; then
    out=$($AB eval "$1" 2>>"$LOG")
  fi
  echo "$out"
}
domclick() { # $1=selector：DOM click 并返回标记（弹窗内按钮防动画 miss）
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

# 直达题库页（课程 6 = 数据结构B，基线 2 题）
$AB open http://127.0.0.1:5273/teacher/courses/6/questions >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(document.querySelector('.q-btn-import')) return 'QPAGE_READY rows='+document.querySelectorAll('.q-row').length; await new Promise(r=>setTimeout(r,300));} return 'QPAGE_TIMEOUT'})()" 'QPAGE_READY')
mark qpage "$OUT"
echo "$OUT" | grep -q 'QPAGE_READY' || fail qpage "$OUT"

# 打开导入弹窗
OUT=$(domclick '.q-btn-import')
mark open-import "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail open-import "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.import-dialog'); if(d && d.offsetParent!==null) return 'DLG_READY'; await new Promise(r=>setTimeout(r,250));} return 'DLG_TIMEOUT'})()" 'DLG_READY')
mark import-dlg "$OUT"
echo "$OUT" | grep -q 'DLG_READY' || fail import-dlg "$OUT"

# 上传测试文档（Windows 绝对路径；隐藏 input 亦可经 CDP 设置）
$AB upload '.import-uploader input[type=file]' 'D:/Claude_Code/智课系统V2/test/e2e/import-e2e-v1.txt' >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var n=document.querySelector('.import-uploader .el-upload-list__item-name'); if(n && n.innerText.indexOf('import-e2e-v1.txt')>=0) return 'FILE_OK'; await new Promise(r=>setTimeout(r,250));} return 'FILE_TIMEOUT'})()" 'FILE_OK')
mark upload "$OUT"
echo "$OUT" | grep -q 'FILE_OK' || fail upload "$OUT"

# 解析并预览（DOM click）
OUT=$(domclick '.import-dialog .q-btn-primary')
mark parse "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail parse "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){var d=document.querySelector('.draft-preview-drawer'); if(d){var cards=document.querySelectorAll('.dp-card'); if(cards.length) return 'DRAWER_READY cards='+cards.length;} await new Promise(r=>setTimeout(r,300));} return 'DRAWER_TIMEOUT'})()" 'DRAWER_READY')
mark drawer "$OUT"
echo "$OUT" | grep -q 'DRAWER_READY' || fail drawer "$OUT"
echo "$OUT" | grep -q 'cards=7' || fail drawer-cards "$OUT"
$AB screenshot test/screenshots/e2e-p1-import-drawer.png >>"$LOG" 2>&1

# 编辑第 1 题题干（触发 600ms 防抖回传）
$AB fill '.dp-list .dp-card:nth-child(1) .el-textarea__inner' '顺序表中访问第 i 个元素的时间复杂度为？（E2E 编辑标记）' >>"$LOG" 2>&1
OUT=$(eval_retry "(function(){var t=document.querySelector('.dp-list .dp-card:nth-child(1) .el-textarea__inner'); return t && t.value.indexOf('E2E 编辑标记')>=0 ? 'EDIT_OK' : 'EDIT_MISS'})()" 'EDIT_OK')
mark edit "$OUT"
echo "$OUT" | grep -q 'EDIT_OK' || fail edit "$OUT"
$AB eval "new Promise(r=>setTimeout(r,1500))" >>"$LOG" 2>&1

# 关闭抽屉 → 从草稿批次列表重开（验证编辑已落库：服务端 drafts 被 PATCH）
OUT=$(domclick '.dp-close')
mark close-drawer "$OUT"
$AB eval "new Promise(r=>setTimeout(r,800))" >>"$LOG" 2>&1
OUT=$(domclick '.q-btn-batch')
mark open-batches "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var r=document.querySelector('.batch-row'); if(r) return 'BATCHDLG_READY '+r.innerText.replace(/\\s+/g,' ').slice(0,80); await new Promise(r=>setTimeout(r,250));} return 'BATCHDLG_TIMEOUT'})()" 'BATCHDLG_READY')
mark batch-dlg "$OUT"
echo "$OUT" | grep -q 'BATCHDLG_READY' || fail batch-dlg "$OUT"
$AB screenshot test/screenshots/e2e-p1-batch-list.png >>"$LOG" 2>&1

OUT=$(domclick '.batch-row-actions .el-button--primary')
mark reopen "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var d=document.querySelector('.draft-preview-drawer'); if(d){var cards=document.querySelectorAll('.dp-card'); if(cards.length){var t=cards[0].querySelector('.el-textarea__inner'); return 'REOPEN_READY cards='+cards.length+' persisted='+(t&&t.value.indexOf('E2E 编辑标记')>=0?'Y':'N')}} await new Promise(r=>setTimeout(r,300));} return 'REOPEN_TIMEOUT'})()" 'REOPEN_READY')
mark reopen-ready "$OUT"
echo "$OUT" | grep -q 'REOPEN_READY' || fail reopen-ready "$OUT"
echo "$OUT" | grep -q 'persisted=Y' || fail persist "$OUT"

# 选择入库章节（EP 2.14 选项类名 .el-select-dropdown__item；DOM click 选项最稳）
$AB click '.dp-summary .el-select__wrapper' >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var pops=document.querySelectorAll('.el-select__popper'); var vis=[]; pops.forEach(function(p){var st=getComputedStyle(p); if(st.display!=='none'&&st.visibility!=='hidden'){var its=p.querySelectorAll('.el-select-dropdown__item'); if(its.length) vis.push(p)}}); if(vis.length) return 'POPPER_ITEMS_OK'; await new Promise(r=>setTimeout(r,200));} return 'POPPER_ITEMS_TIMEOUT'})()" 'POPPER_ITEMS_OK')
mark popper "$OUT"
echo "$OUT" | grep -q 'POPPER_ITEMS_OK' || fail popper "$OUT"
OUT=$(eval_retry "(function(){var pops=document.querySelectorAll('.el-select__popper'); for(var i=0;i<pops.length;i++){var p=pops[i]; var st=getComputedStyle(p); if(st.display!=='none'&&st.visibility!=='hidden'){var its=p.querySelectorAll('.el-select-dropdown__item'); for(var j=0;j<its.length;j++){if(its[j].innerText.indexOf('第1章 线性表')>=0){its[j].click(); return 'OPT_CLICKED'}}}} return 'OPT_NOT_FOUND'})()" 'OPT_CLICKED|OPT_NOT_FOUND')
mark opt "$OUT"
echo "$OUT" | grep -q 'OPT_CLICKED' || fail opt "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var b=document.querySelector('.dp-footer-actions .el-button--primary'); var sel=document.querySelector('.dp-summary .el-select__wrapper'); if(b && !b.disabled) return 'SAVE_ENABLED seltext='+(sel?sel.innerText.replace(/\\s+/g,' '):'-'); await new Promise(r=>setTimeout(r,250));} return 'SAVE_DISABLED'})()" 'SAVE_ENABLED')
mark catalog "$OUT"
echo "$OUT" | grep -q 'SAVE_ENABLED' || fail catalog "$OUT"

# 全部入库（DOM click）——预期 6 题入库 + 1 题与题库已有题干重复被跳过（查重设计行为，草稿保留）
OUT=$(domclick '.dp-footer-actions .el-button--primary')
mark save "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var ms=document.querySelector('.el-message'); if(ms && ms.innerText.indexOf('已入库 6 题')>=0) return 'SAVED6 '+ms.innerText.replace(/\\s+/g,' ').slice(0,70); await new Promise(r=>setTimeout(r,300));} return 'SAVE_TIMEOUT'})()" 'SAVED6')
mark save-msg "$OUT"
echo "$OUT" | grep -q 'SAVED6' || fail save "$OUT"
echo "$OUT" | grep -q '跳过 1 题' || fail dedup "$OUT"

# 跳过项留批次内可修正：改写题干后重试入库（查重复试路径）
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var cards=document.querySelectorAll('.dp-card'); if(cards.length===1) return 'REMAIN1'; await new Promise(r=>setTimeout(r,300));} return 'REMAIN_MISMATCH n='+document.querySelectorAll('.dp-card').length})()" 'REMAIN1')
mark remain "$OUT"
echo "$OUT" | grep -q 'REMAIN1' || fail remain "$OUT"
$AB fill '.dp-list .dp-card:nth-child(1) .el-textarea__inner' '栈的特点是后进先出（LIFO）。（E2E 查重后改写）' >>"$LOG" 2>&1
$AB eval "new Promise(r=>setTimeout(r,1500))" >>"$LOG" 2>&1
OUT=$(domclick '.dp-footer-actions .el-button:not(.el-button--primary)')
mark retry-save "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var ms=document.querySelectorAll('.el-message'); var txt=[]; ms.forEach(function(m){txt.push(m.innerText)}); var all=txt.join(' '); if(all.indexOf('已入库 1 题')>=0 || all.indexOf('批次已全部入库')>=0) return 'RETRY_SAVED'; await new Promise(r=>setTimeout(r,300));} return 'RETRY_TIMEOUT'})()" 'RETRY_SAVED')
mark retry-msg "$OUT"
echo "$OUT" | grep -q 'RETRY_SAVED' || fail retry-msg "$OUT"

# 抽屉应自动关闭（EP drawer 关闭后元素仍在 DOM，需查可见性）+ 列表刷新为 9 题（基线 2 + 导入 7）
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var rows=document.querySelectorAll('.q-row'); var d=document.querySelector('.draft-preview-drawer'); var hidden=true; if(d){var st=getComputedStyle(d); var ov=d.closest('.el-overlay'); var ovs=ov?getComputedStyle(ov):null; hidden=st.display==='none'||(ovs&&ovs.display==='none')||d.getBoundingClientRect().width===0} if(rows.length===9 && hidden) return 'ROWS9'; await new Promise(r=>setTimeout(r,300));} var d2=document.querySelector('.draft-preview-drawer'); var st2=d2?getComputedStyle(d2):null; var ov2=d2?d2.closest('.el-overlay'):null; var ovs2=ov2?getComputedStyle(ov2):null; return 'ROWS_MISMATCH count='+document.querySelectorAll('.q-row').length+' drawerDisplay='+(st2?st2.display:'gone')+' overlayDisplay='+(ovs2?ovs2.display:'gone')})()" 'ROWS9')
mark rows "$OUT"
echo "$OUT" | grep -q 'ROWS9' || fail rows "$OUT"
$AB screenshot test/screenshots/e2e-p1-import-saved.png >>"$LOG" 2>&1

$AB close --all >>"$LOG" 2>&1
echo "E2E_CHAIN1_PASS"
