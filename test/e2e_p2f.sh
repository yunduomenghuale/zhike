#!/bin/bash
# P2f 学生端章节 AI 总结抽屉 E2E（agent-browser 单链，daemon 不跨 Bash 调用存活）
# 覆盖：行内入口按钮文案 / 查看总结抽屉内容 / 无总结自动生成（生成中→就绪）/ 截图存证
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_p2f.log
AB=agent-browser
mkdir -p test/screenshots
: > "$LOG"

eval_retry() { # $1=expr $2=marker  → 输出命中 marker 的 eval 结果（gotcha 8 重试）
  local out
  out=$($AB eval "$1" 2>>"$LOG")
  if ! echo "$out" | grep -q "$2"; then
    out=$($AB eval "$1" 2>>"$LOG")
  fi
  echo "$out"
}

$AB close --all >>"$LOG" 2>&1
$AB open http://127.0.0.1:5273/login >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入用户名"]' 2026001 >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入密码"]' pass1234 >>"$LOG" 2>&1
$AB click '.auth-submit' >>"$LOG" 2>&1

OUT=$(eval_retry "(async function(){for(var i=0;i<50;i++){if(location.protocol==='http:' && location.pathname.indexOf('/login')<0 && document.querySelector('#app')) return 'LANDED '+location.pathname; await new Promise(r=>setTimeout(r,300))} return 'LOGIN_TIMEOUT '+location.protocol+' '+location.pathname})()" 'LANDED')
echo "[login] $OUT"
echo "$OUT" | grep -q 'LANDED /' || { echo "E2E_FAIL login"; exit 1; }

# 直达课程学习页（课程 7 = Java程序设计）
$AB open http://127.0.0.1:5273/student/courses/7/learning >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){var rows=document.querySelectorAll('.tree-node .node-title'); if(rows.length) return 'ROWS_OK count='+rows.length; await new Promise(r=>setTimeout(r,300))} return 'ROWS_TIMEOUT'})()" 'ROWS_OK')
echo "[rows] $OUT"
echo "$OUT" | grep -q 'ROWS_OK' || { echo "E2E_FAIL rows"; exit 1; }

# 第1章行按钮文案（入口：AI 总结 / 查看总结 均可）
OUT=$(eval_retry "(function(){var rows=document.querySelectorAll('.tree-node'); for(var i=0;i<rows.length;i++){var t=rows[i].querySelector('.node-title'); if(t && t.innerText.indexOf('Java语言概述')>=0){var btns=rows[i].querySelectorAll('.node-action-btn'); var labels=[]; btns.forEach(function(b){labels.push(b.innerText.trim())}); return 'CH1 labels='+labels.join('|')}} return 'CH1_NOT_FOUND'})()" 'CH1 ')
echo "[ch1] $OUT"
echo "$OUT" | grep -qE 'AI 总结|查看总结' || { echo "E2E_FAIL ch1 button label"; exit 1; }

# 点击总结入口按钮 → 抽屉展示已有总结
OUT=$(eval_retry "(function(){var rows=document.querySelectorAll('.tree-node'); for(var i=0;i<rows.length;i++){var t=rows[i].querySelector('.node-title'); if(t && t.innerText.indexOf('Java语言概述')>=0){var btns=rows[i].querySelectorAll('.node-action-btn'); for(var j=0;j<btns.length;j++){if(btns[j].innerText.indexOf('总结')>=0){btns[j].click(); return 'CLICKED'}} return 'BTN_NOT_FOUND'}} return 'CH1_NOT_FOUND'})()" 'CLICKED')
echo "[ch1-click] $OUT"

# 等抽屉渲染出内容区块
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var d=document.querySelector('.summary-drawer'); if(d){var body=d.querySelector('.summary-body'); if(body && body.innerText.indexOf('本章概览')>=0 && body.innerText.indexOf('下一步')>=0){var secs=['本章概览','知识点掌握','薄弱点','学习亮点','提升建议','下一步'].filter(function(s){return body.innerText.indexOf(s)>=0}); return 'DRAWER_OK sections='+secs.join('/')}}} await new Promise(r=>setTimeout(r,300)); return 'DRAWER_TIMEOUT'})()" 'DRAWER_OK')
echo "[drawer] $OUT"
echo "$OUT" | grep -q 'DRAWER_OK' || { echo "E2E_FAIL drawer content"; exit 1; }

# 断言内容要素：薄弱红标签 / 知识点徽章 / 降级提示无
OUT=$(eval_retry "(function(){var d=document.querySelector('.summary-drawer'); if(!d) return 'NO_DRAWER'; var body=d.querySelector('.summary-body'); var weak=d.querySelectorAll('.weak-tag').length; var kp=d.querySelectorAll('.kp-item').length; var degraded=body.innerText.indexOf('统计数据自动生成')>=0; var title=d.querySelector('.summary-head h2'); return 'CONTENT weakTags='+weak+' kpItems='+kp+' degraded='+degraded+' title='+(title?title.innerText:'?')})()" 'CONTENT ')
echo "[content] $OUT"
# 打开过后入口应变「查看总结」
OUT=$(eval_retry "(function(){var rows=document.querySelectorAll('.tree-node'); for(var i=0;i<rows.length;i++){var t=rows[i].querySelector('.node-title'); if(t && t.innerText.indexOf('Java语言概述')>=0){var btns=rows[i].querySelectorAll('.node-action-btn'); for(var j=0;j<btns.length;j++){if(btns[j].innerText.indexOf('总结')>=0) return 'LABEL '+btns[j].innerText.trim()} return 'BTN_NOT_FOUND'}} return 'CH1_NOT_FOUND'})()" 'LABEL ')
echo "[label-after-open] $OUT"
echo "$OUT" | grep -q '查看总结' || { echo "E2E_FAIL label after open"; exit 1; }
$AB screenshot test/screenshots/ai-chapter-summary-ready.png >>"$LOG" 2>&1
echo "[shot] ai-chapter-summary-ready.png"

# 关闭抽屉，改测第2章（无总结 → 自动生成）
OUT=$(eval_retry "(function(){var d=document.querySelector('.summary-drawer'); if(d){var c=d.querySelector('.summary-close'); if(c){c.click(); return 'CLOSED'}} return 'NO_CLOSE'})()" 'CLOSED')
echo "[close] $OUT"

OUT=$(eval_retry "(function(){var rows=document.querySelectorAll('.tree-node'); for(var i=0;i<rows.length;i++){var t=rows[i].querySelector('.node-title'); if(t && t.innerText.indexOf('Java语言编程基础')>=0){var btns=rows[i].querySelectorAll('.node-action-btn'); for(var j=0;j<btns.length;j++){if(btns[j].innerText.indexOf('AI 总结')>=0){btns[j].click(); return 'CLICKED'}} return 'BTN_NOT_FOUND'}} return 'CH2_NOT_FOUND'})()" 'CLICKED')
echo "[ch2-click] $OUT"

# 生成中态（先截图），随后链内多次 3s 短轮询至就绪（真实 Provider 数十秒）
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.summary-drawer'); if(d && d.innerText.indexOf('AI 正在生成本章学习总结')>=0) return 'GENERATING'; if(d && d.querySelector('.summary-body') && d.querySelector('.summary-body').innerText.indexOf('本章概览')>=0) return 'ALREADY_READY'; await new Promise(r=>setTimeout(r,300))} return 'GEN_TIMEOUT'})()" 'GENERATING\|ALREADY_READY')
echo "[ch2-generating] $OUT"
$AB screenshot test/screenshots/ai-chapter-summary-generating.png >>"$LOG" 2>&1
echo "[shot] ai-chapter-summary-generating.png"

# 多次 3s 短 eval 轮询至就绪（避免单次长 eval 拖挂 daemon）
READY=""
for i in $(seq 1 30); do
  OUT=$($AB eval "(async function(){await new Promise(r=>setTimeout(r,3000)); var d=document.querySelector('.summary-drawer'); if(d && d.querySelector('.summary-body') && d.querySelector('.summary-body').innerText.indexOf('本章概览')>=0 && d.querySelector('.summary-body').innerText.indexOf('下一步')>=0) return 'READY'; return 'WAIT'})()" 2>>"$LOG")
  if echo "$OUT" | grep -q 'READY'; then READY=1; echo "[ch2-ready] poll#$i READY"; break; fi
done
[ -n "$READY" ] || { echo "E2E_FAIL ch2 not ready"; exit 1; }

OUT=$(eval_retry "(function(){var d=document.querySelector('.summary-drawer'); var body=d.querySelector('.summary-body'); var rows=document.querySelectorAll('.tree-node'); var badge=''; for(var i=0;i<rows.length;i++){var t=rows[i].querySelector('.node-title'); if(t && t.innerText.indexOf('Java语言编程基础')>=0){var tags=rows[i].querySelectorAll('.el-tag'); var labels=[]; tags.forEach(function(x){labels.push(x.innerText.trim())}); badge=labels.join('|')}} return 'FINAL badges='+badge+' degraded='+(body.innerText.indexOf('统计数据自动生成')>=0)})()" 'FINAL ')
echo "[final] $OUT"
$AB screenshot test/screenshots/ai-chapter-summary-ch2-ready.png >>"$LOG" 2>&1
echo "[shot] ai-chapter-summary-ch2-ready.png"

echo "E2E_P2F_OK"
