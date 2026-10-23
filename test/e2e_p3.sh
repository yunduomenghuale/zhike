#!/bin/bash
# P3 E2E：教师端历史报告回看 + 学生详情页 AI 章节总结查看
# 覆盖：历史报告弹窗（字段/状态）→ 点击回看（banner+正文）→ 返回当前 →
#       学生卡片进详情 → 章节总结六区渲染 → 切换章节空态。
# fixtures：backend/make_p3_fixtures.py（class 1 历史报告 + 学生 12 的 catalog 5 总结）
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_p3.log
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
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.stu-card').length) return 'STU_OK count='+document.querySelectorAll('.stu-card').length; await new Promise(r=>setTimeout(r,300))} return 'STU_TIMEOUT'})()" 'STU_OK')
echo "[students] $OUT"
echo "$OUT" | grep -q 'STU_OK' || { echo "E2E_FAIL students"; exit 1; }

# ---- 1. 历史报告弹窗：打开 + 列表字段 ----
OUT=$(eval_retry "(function(){var b=document.querySelector('.an-history-btn'); if(!b) return 'NO_BTN'; b.click(); return 'CLICKED'})()" 'CLICKED')
echo "[history-open] $OUT"
echo "$OUT" | grep -q 'CLICKED' || { echo "E2E_FAIL history-open"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var items=document.querySelectorAll('.history-item'); var vis=[]; items.forEach(function(it){if(it.getBoundingClientRect().height>0) vis.push(it)}); if(vis.length) return 'HIST_OK n='+vis.length+' head='+vis[0].querySelector('.history-item-head').innerText.replace(/\\n/g,'|')+' meta='+vis[0].querySelector('.history-item-meta').innerText.replace(/\\n/g,'|'); await new Promise(r=>setTimeout(r,300))} return 'HIST_TIMEOUT'})()" 'HIST_OK')
echo "[history-list] $OUT"
echo "$OUT" | grep -q 'HIST_OK' || { echo "E2E_FAIL history-list"; exit 1; }
echo "$OUT" | grep -q '已完成' || { echo "E2E_FAIL history-status-tag"; exit 1; }
echo "$OUT" | grep -q '分析 2 人' || { echo "E2E_FAIL history-meta"; exit 1; }
$AB screenshot test/screenshots/ai-p3-history-dialog.png >>"$LOG" 2>&1
echo "[shot] ai-p3-history-dialog.png"

# ---- 2. 点击历史项 → 回看（banner + 正文）----
OUT=$(eval_retry "(function(){var it=document.querySelector('.history-item'); if(!it) return 'NO_ITEM'; it.click(); return 'ITEM_CLICKED'})()" 'ITEM_CLICKED')
echo "[history-click] $OUT"
echo "$OUT" | grep -q 'ITEM_CLICKED' || { echo "E2E_FAIL history-click"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var ban=document.querySelector('.ai-history-banner'); var md=document.querySelector('.ai-md'); if(ban && ban.getBoundingClientRect().height>0 && md && md.innerText.indexOf('E2E-P3 历史报告')>=0) return 'VIEW_OK ban='+ban.innerText.trim(); await new Promise(r=>setTimeout(r,300))} return 'VIEW_TIMEOUT'})()" 'VIEW_OK')
echo "[history-view] $OUT"
echo "$OUT" | grep -q 'VIEW_OK' || { echo "E2E_FAIL history-view"; exit 1; }
echo "$OUT" | grep -q '正在查看历史报告' || { echo "E2E_FAIL history-banner-text"; exit 1; }
$AB screenshot test/screenshots/ai-p3-history-view.png >>"$LOG" 2>&1
echo "[shot] ai-p3-history-view.png"

# ---- 3. 返回当前报告 → banner 消失 ----
OUT=$(eval_retry "(function(){var b=document.querySelector('.ai-back-btn'); if(!b) return 'NO_BACK'; b.click(); return 'BACK_CLICKED'})()" 'BACK_CLICKED')
echo "[history-back] $OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){if(!document.querySelector('.ai-history-banner')) return 'BANNER_GONE'; await new Promise(r=>setTimeout(r,300))} return 'BANNER_STILL'})()" 'BANNER_GONE')
echo "[history-back-check] $OUT"
echo "$OUT" | grep -q 'BANNER_GONE' || { echo "E2E_FAIL history-back"; exit 1; }

# ---- 4. 学生卡片 → 详情页 AI 章节总结 ----
OUT=$(eval_retry "(function(){var c=document.querySelector('.stu-card'); if(!c) return 'NO_CARD'; c.click(); return 'CARD_CLICKED'})()" 'CARD_CLICKED')
echo "[stu-card] $OUT"
echo "$OUT" | grep -q 'CARD_CLICKED' || { echo "E2E_FAIL stu-card"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(location.pathname.indexOf('/students/')>=0 && document.querySelector('.sum-body')) return 'SUM_OK'; await new Promise(r=>setTimeout(r,300))} return 'SUM_TIMEOUT'})()" 'SUM_OK')
echo "[summary-load] $OUT"
echo "$OUT" | grep -q 'SUM_OK' || { echo "E2E_FAIL summary-load"; exit 1; }

OUT=$(eval_retry "(function(){var b=document.querySelector('.sum-body'); if(!b) return 'NO_BODY'; var t=b.innerText; var weak=document.querySelectorAll('.weak-tag').length; var kp=document.querySelectorAll('.kp-item').length; var sg=document.querySelectorAll('.sum-list li').length; var next=document.querySelector('.sum-next'); var ok=t.indexOf('E2E-P3 总结')>=0 && t.indexOf('递归终止条件')>=0 && weak>=2 && kp===2 && sg>=5 && next && next.innerText.indexOf('下一步')>=0; return ok?'BODY_OK weak='+weak+' kp='+kp+' sg='+sg:'BODY_BAD weak='+weak+' kp='+kp+' sg='+sg+' hasNext='+(!!next)})()" 'BODY_OK')
echo "[summary-body] $OUT"
echo "$OUT" | grep -q 'BODY_OK' || { echo "E2E_FAIL summary-body"; exit 1; }
$AB screenshot test/screenshots/ai-p3-student-summary.png >>"$LOG" 2>&1
echo "[shot] ai-p3-student-summary.png"

# ---- 5. 切换章节 → 空态 ----
OUT=$(eval_retry "(function(){var w=document.querySelector('.sum-chapter-select .el-select__wrapper'); if(!w) return 'NO_SELECT'; w.click(); return 'SELECT_OPENED'})()" 'SELECT_OPENED')
echo "[chapter-select] $OUT"
echo "$OUT" | grep -q 'SELECT_OPENED' || { echo "E2E_FAIL chapter-select"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var opts=document.querySelectorAll('.el-select-dropdown__item'); var vis=[]; opts.forEach(function(o){if(o.getBoundingClientRect().height>0) vis.push(o)}); if(vis.length>=2){vis[1].click(); return 'OPT_CLICKED n='+vis.length} await new Promise(r=>setTimeout(r,300))} return 'OPT_TIMEOUT'})()" 'OPT_CLICKED')
echo "[chapter-pick] $OUT"
echo "$OUT" | grep -q 'OPT_CLICKED' || { echo "E2E_FAIL chapter-pick"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){if(location.pathname.indexOf('/students/')<0) return 'LEFT_PAGE'; var emp=document.querySelector('.sum-wrap .el-empty__description'); if(emp && emp.innerText.indexOf('该生尚未生成本章')>=0) return 'EMPTY_OK'; await new Promise(r=>setTimeout(r,300))} return 'EMPTY_TIMEOUT'})()" 'EMPTY_OK')
echo "[chapter-empty] $OUT"
echo "$OUT" | grep -q 'EMPTY_OK' || { echo "E2E_FAIL chapter-empty"; exit 1; }
$AB screenshot test/screenshots/ai-p3-summary-empty.png >>"$LOG" 2>&1
echo "[shot] ai-p3-summary-empty.png"

echo "E2E_P3_OK"
