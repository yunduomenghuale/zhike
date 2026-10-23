#!/bin/bash
# P3 E2E：教师端历史报告回看 + 学生详情页 AI 章节总结查看
# 覆盖：刷新恢复进行中分析任务（挂载即见进度 UI + reload 后仍在）→ 学生表格
#       （行渲染 + 预警筛选 + 姓名搜索 + 行展开）→ 历史报告弹窗（excerpt markdown 渲染）
#       → 点击回看（banner+正文）→ 返回当前 → 表格行进详情 → 章节总结六区渲染 → 切换章节空态。
# fixtures：backend/make_p3_fixtures.py（class 1 进行中任务 + 历史报告 + 每生 catalog 5 总结）
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

# 学生表格预警筛选：打开 select → 点包含指定文案的选项 → 等下拉收起
pick_filter() {
  local out
  out=$($AB eval "(function(){var w=document.querySelector('.stu-filter .el-select__wrapper'); if(!w) return 'NO_SELECT'; w.click(); return 'OPEN'})()" 2>>"$LOG")
  echo "$out" | grep -q 'OPEN' || { echo "E2E_FAIL filter-open"; exit 1; }
  out=$(eval_retry "(async function(){for(var i=0;i<30;i++){var opts=document.querySelectorAll('.el-select-dropdown__item'); var vis=[]; opts.forEach(function(o){if(o.getBoundingClientRect().height>0) vis.push(o)}); if(vis.length>=3){var t=null; vis.forEach(function(o){if(o.innerText.indexOf('$1')>=0) t=o}); if(t){t.click(); return 'PICKED'}} await new Promise(r=>setTimeout(r,300))} return 'OPT_TIMEOUT'})()" 'PICKED')
  echo "$out" | grep -q 'PICKED' || { echo "E2E_FAIL filter-pick"; exit 1; }
  $AB eval "(async function(){for(var i=0;i<20;i++){var vis=false; document.querySelectorAll('.el-select-dropdown__item').forEach(function(o){if(o.getBoundingClientRect().height>0) vis=true}); if(!vis) return 'DD_CLOSED'; await new Promise(r=>setTimeout(r,300))} return 'DD_TIMEOUT'})()" >>"$LOG" 2>&1
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
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(document.querySelectorAll('.stu-table .el-table__row').length) return 'STU_OK count='+document.querySelectorAll('.stu-table .el-table__row').length; await new Promise(r=>setTimeout(r,300))} return 'STU_TIMEOUT'})()" 'STU_OK')
echo "[students] $OUT"
echo "$OUT" | grep -q 'STU_OK' || { echo "E2E_FAIL students"; exit 1; }

# ---- 0.5 刷新恢复：挂载即恢复进行中任务（无需点生成即见进度 UI）----
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var tip=document.querySelector('.ai-loading-tip'); if(tip && tip.getBoundingClientRect().height>0) return 'RESUME_OK tip='+tip.innerText.trim(); await new Promise(r=>setTimeout(r,300))} return 'RESUME_TIMEOUT'})()" 'RESUME_OK')
echo "[resume-active] $OUT"
echo "$OUT" | grep -q 'RESUME_OK' || { echo "E2E_FAIL resume-active"; exit 1; }
echo "$OUT" | grep -q 'E2E-P3 恢复任务' || { echo "E2E_FAIL resume-tip-text"; exit 1; }

# ---- 0.6 刷新页面后进度 UI 仍在（reload 后重新拉起轮询）----
$AB eval "location.reload()" >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var tip=document.querySelector('.ai-loading-tip'); if(tip && tip.getBoundingClientRect().height>0 && tip.innerText.indexOf('E2E-P3 恢复任务')>=0) return 'AFTER_RELOAD_OK'; await new Promise(r=>setTimeout(r,300))} return 'RELOAD_TIMEOUT'})()" 'AFTER_RELOAD_OK')
echo "[resume-after-reload] $OUT"
echo "$OUT" | grep -q 'AFTER_RELOAD_OK' || { echo "E2E_FAIL resume-after-reload"; exit 1; }

# ---- 0. 学生表格：行渲染 + 预警筛选 + 姓名搜索 + 行展开 ----
OUT=$(eval_retry "(function(){var rows=document.querySelectorAll('.stu-table .el-table__row'); var vis=[]; rows.forEach(function(r){if(r.getBoundingClientRect().height>0) vis.push(r)}); var cnt=document.querySelector('.stu-count'); return 'TBL_OK rows='+vis.length+' count='+(cnt?cnt.innerText.trim():'NA')+' cols='+document.querySelectorAll('.stu-table thead th').length})()" 'TBL_OK')
echo "[stu-table] $OUT"
echo "$OUT" | grep -q 'TBL_OK' || { echo "E2E_FAIL stu-table"; exit 1; }
echo "$OUT" | grep -q 'rows=2' || { echo "E2E_FAIL stu-table-rows"; exit 1; }
echo "$OUT" | grep -q 'count=共 2 人' || { echo "E2E_FAIL stu-table-count"; exit 1; }

# 筛选「有预警」：两名学生均有预警 → 仍 2 行且每行带预警标签
pick_filter '有预警'
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var rows=document.querySelectorAll('.stu-table .el-table__row'); var vis=[]; rows.forEach(function(r){if(r.getBoundingClientRect().height>0) vis.push(r)}); if(vis.length===2){var warned=0; vis.forEach(function(r){if(r.querySelector('.stu-warn-cell')) warned++}); if(warned===2) return 'FILTERED rows=2 warned=2'} await new Promise(r=>setTimeout(r,300))} return 'FILTER_TIMEOUT'})()" 'FILTERED')
echo "[stu-filter-warned] $OUT"
echo "$OUT" | grep -q 'FILTERED rows=2 warned=2' || { echo "E2E_FAIL stu-filter-warned"; exit 1; }

# 筛选「状态正常」：无匹配 → 空态
pick_filter '状态正常'
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var emp=document.querySelector('.el-empty'); if(emp && emp.getBoundingClientRect().height>0 && emp.innerText.indexOf('没有符合条件的学生')>=0 && !document.querySelector('.stu-table')) return 'EMPTY_OK'; await new Promise(r=>setTimeout(r,300))} return 'EMPTY_TIMEOUT'})()" 'EMPTY_OK')
echo "[stu-filter-normal-empty] $OUT"
echo "$OUT" | grep -q 'EMPTY_OK' || { echo "E2E_FAIL stu-filter-normal-empty"; exit 1; }

# 恢复「全部学生」→ 2 行
pick_filter '全部'
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){if(document.querySelectorAll('.stu-table .el-table__row').length===2) return 'RESTORED'; await new Promise(r=>setTimeout(r,300))} return 'RESTORE_TIMEOUT'})()" 'RESTORED')
echo "[stu-filter-reset] $OUT"
echo "$OUT" | grep -q 'RESTORED' || { echo "E2E_FAIL stu-filter-reset"; exit 1; }

# 搜索：姓名关键词收窄到 1 行（单班学生），清空恢复 2 行
OUT=$(eval_retry "(function(){var i=document.querySelector('.stu-search input'); if(!i) return 'NO_INPUT'; var d=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set; d.call(i,'单班'); i.dispatchEvent(new Event('input',{bubbles:true})); return 'FILLED'})()" 'FILLED')
echo "[stu-search-fill] $OUT"
echo "$OUT" | grep -q 'FILLED' || { echo "E2E_FAIL stu-search-fill"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var rows=document.querySelectorAll('.stu-table .el-table__row'); if(rows.length===1) return 'SEARCHED name='+rows[0].querySelector('.stu-name-t').innerText; await new Promise(r=>setTimeout(r,300))} return 'SEARCH_TIMEOUT'})()" 'SEARCHED')
echo "[stu-search] $OUT"
echo "$OUT" | grep -q 'SEARCHED name=单班学生' || { echo "E2E_FAIL stu-search"; exit 1; }

OUT=$(eval_retry "(function(){var i=document.querySelector('.stu-search input'); var d=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set; d.call(i,''); i.dispatchEvent(new Event('input',{bubbles:true})); return 'CLEARED'})()" 'CLEARED')
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){if(document.querySelectorAll('.stu-table .el-table__row').length===2) return 'SEARCH_CLEARED'; await new Promise(r=>setTimeout(r,300))} return 'CLEAR_TIMEOUT'})()" 'SEARCH_CLEARED')
echo "[stu-search-clear] $OUT"
echo "$OUT" | grep -q 'SEARCH_CLEARED' || { echo "E2E_FAIL stu-search-clear"; exit 1; }

# 行展开：AI 简评 / 无数据说明 / 全部预警（首行展开有内容）
OUT=$(eval_retry "(function(){var ico=document.querySelector('.stu-table .el-table__expand-icon'); if(!ico) return 'NO_EXPAND'; ico.click(); return 'EXPAND_CLICKED'})()" 'EXPAND_CLICKED')
echo "[stu-expand] $OUT"
echo "$OUT" | grep -q 'EXPAND_CLICKED' || { echo "E2E_FAIL stu-expand"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var cell=document.querySelector('.stu-table .el-table__expanded-cell'); if(cell && cell.getBoundingClientRect().height>0 && cell.innerText.trim().length>0) return 'EXPAND_OK text='+cell.innerText.trim().slice(0,20); await new Promise(r=>setTimeout(r,300))} return 'EXPAND_TIMEOUT'})()" 'EXPAND_OK')
echo "[stu-expand-check] $OUT"
echo "$OUT" | grep -q 'EXPAND_OK' || { echo "E2E_FAIL stu-expand-check"; exit 1; }
$AB screenshot test/screenshots/ai-p3-stu-table.png >>"$LOG" 2>&1
echo "[shot] ai-p3-stu-table.png"

# ---- 1. 历史报告弹窗：打开 + 列表字段 ----
OUT=$(eval_retry "(function(){var b=document.querySelector('.an-history-btn'); if(!b) return 'NO_BTN'; b.click(); return 'CLICKED'})()" 'CLICKED')
echo "[history-open] $OUT"
echo "$OUT" | grep -q 'CLICKED' || { echo "E2E_FAIL history-open"; exit 1; }

OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var items=document.querySelectorAll('.history-item'); var vis=[]; items.forEach(function(it){if(it.getBoundingClientRect().height>0) vis.push(it)}); if(vis.length){var ex=vis[0].querySelector('.history-excerpt'); return 'HIST_OK n='+vis.length+' head='+vis[0].querySelector('.history-item-head').innerText.replace(/\\n/g,'|')+' meta='+vis[0].querySelector('.history-item-meta').innerText.replace(/\\n/g,'|')+' excerptRendered='+(ex? !!ex.querySelector('h2') : 'NA')+' excerptHasHash='+(ex?ex.innerText.indexOf('#')>=0:'NA')} await new Promise(r=>setTimeout(r,300))} return 'HIST_TIMEOUT'})()" 'HIST_OK')
echo "[history-list] $OUT"
echo "$OUT" | grep -q 'HIST_OK' || { echo "E2E_FAIL history-list"; exit 1; }
echo "$OUT" | grep -q '已完成' || { echo "E2E_FAIL history-status-tag"; exit 1; }
echo "$OUT" | grep -q '分析 2 人' || { echo "E2E_FAIL history-meta"; exit 1; }
# excerpt 按 markdown 渲染：标题转为 h2 元素，且正文不再露出 ## 符号
echo "$OUT" | grep -q 'excerptRendered=true' || { echo "E2E_FAIL history-excerpt-markdown"; exit 1; }
echo "$OUT" | grep -q 'excerptHasHash=false' || { echo "E2E_FAIL history-excerpt-hash"; exit 1; }
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

# ---- 4. 学生表格行 → 详情页 AI 章节总结 ----
OUT=$(eval_retry "(function(){var row=document.querySelector('.stu-table .el-table__row'); if(!row) return 'NO_ROW'; var cell=row.querySelector('.stu-cell-name'); (cell||row).click(); return 'ROW_CLICKED'})()" 'ROW_CLICKED')
echo "[stu-row] $OUT"
echo "$OUT" | grep -q 'ROW_CLICKED' || { echo "E2E_FAIL stu-row"; exit 1; }

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
