#!/bin/bash
# P1e 回归：教师端班级 AI 学情分析轮询（useAiTaskPolling seq 守卫修复验证）
# 背景：P2f E2E 发现 start() 先取 mySeq 再 stop()（递增 seq）导致首个 tick 永不调度，
# 轮询静默失效；本脚本验证修复后教师端提交→轮询→渐进渲染→终态全链路恢复。
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_p1e_regression.log
AB=agent-browser
mkdir -p test/screenshots
: > "$LOG"

eval_retry() {
  local out
  out=$($AB eval "$1" 2>>"$LOG")
  if ! echo "$out" | grep -q "$2"; then
    out=$($AB eval "$1" 2>>"$LOG")
  fi
  echo "$out"
}

$AB close --all >>"$LOG" 2>&1
$AB open http://127.0.0.1:5273/login >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入用户名"]' t101 >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入密码"]' pass1234 >>"$LOG" 2>&1
$AB click '.auth-submit' >>"$LOG" 2>&1

OUT=$(eval_retry "(async function(){for(var i=0;i<50;i++){if(location.protocol==='http:' && location.pathname.indexOf('/login')<0 && document.querySelector('#app')) return 'LANDED '+location.pathname; await new Promise(r=>setTimeout(r,300))} return 'LOGIN_TIMEOUT'})()" 'LANDED')
echo "[login] $OUT"
echo "$OUT" | grep -q 'LANDED /' || { echo "E2E_FAIL login"; exit 1; }

$AB open http://127.0.0.1:5273/teacher/analytics >>"$LOG" 2>&1
# 等学生卡片加载（页面自动选第一个班级）
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.stu-card').length) return 'STU_OK count='+document.querySelectorAll('.stu-card').length; await new Promise(r=>setTimeout(r,300))} return 'STU_TIMEOUT'})()" 'STU_OK')
echo "[students] $OUT"
echo "$OUT" | grep -q 'STU_OK' || { echo "E2E_FAIL students"; exit 1; }

# 提交分析
OUT=$(eval_retry "(function(){var b=document.querySelector('.an-primary-btn'); if(!b) return 'NO_BTN'; b.click(); return 'CLICKED '+b.innerText.trim()})()" 'CLICKED')
echo "[submit] $OUT"

# 加载态：轮询拿到 task.progress.message（证明轮询在工作）
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var tip=document.querySelector('.ai-loading-tip'); if(tip && tip.innerText.indexOf('AI 正在分析班级数据，请稍候')<0 && tip.innerText.trim().length>0) return 'TIP '+tip.innerText.trim(); await new Promise(r=>setTimeout(r,300))} return 'TIP_TIMEOUT'})()" 'TIP ')
echo "[loading-tip] $OUT"
$AB screenshot test/screenshots/ai-analytics-loading-regression.png >>"$LOG" 2>&1
echo "[shot] ai-analytics-loading-regression.png"

# 终态：报告头出现 + 五大节标题 + 简评卡片
READY=""
for i in $(seq 1 60); do
  OUT=$($AB eval "(async function(){await new Promise(r=>setTimeout(r,3000)); var head=document.querySelector('.ai-head-title'); var md=document.querySelector('.ai-md'); if(head && md){var t=md.innerText; var secs=['整体学情','知识点掌握分析','学生分层画像','风险预警','教学干预建议'].filter(function(s){return t.indexOf(s)>=0}); if(secs.length===5) return 'READY secs=5 comments='+document.querySelectorAll('.stu-ai').length} return 'WAIT'})()" 2>>"$LOG")
  if echo "$OUT" | grep -q 'READY'; then READY=1; echo "[terminal] poll#$i $OUT"; break; fi
done
[ -n "$READY" ] || { echo "E2E_FAIL terminal (polling may still be broken)"; exit 1; }
$AB screenshot test/screenshots/ai-analytics-final-regression.png >>"$LOG" 2>&1
echo "[shot] ai-analytics-final-regression.png"

echo "E2E_P1E_REGRESSION_OK"
