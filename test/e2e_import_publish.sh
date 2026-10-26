#!/bin/bash
# E2E：导入弹窗上传区对齐课件上传 + 选择即上传解析 + 入库并发布全链路
# 断言：① 上传区新结构（inner/icon/title/desc）+ dragger 176px + footer 无「解析并预览」按钮
#       ② 选择文件后不点任何按钮自动上传解析并打开预览抽屉（7 题）
#       ③ 「入库后立即发布」勾选 → 全部入库 → 提示「已入库并发布」
#       ④ API 验证 5 题入库且 status=published/source=import（13/14 查重跳过）
#       ⑤ 仅删除本链创建的题目 id，批次无残留
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_import_publish.log
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

TOKEN=$(curl -s --noproxy '*' -X POST http://localhost:8005/api/auth/login/ -H 'Content-Type: application/json' -d '{"username":"t101","password":"pass1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token']['access'])")

$AB close --all >>"$LOG" 2>&1
$AB open http://127.0.0.1:5273/login >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入用户名"]' t101 >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入密码"]' pass1234 >>"$LOG" 2>&1
$AB click '.auth-submit' >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<50;i++){if(location.pathname.indexOf('/login')<0 && document.querySelector('#app')) return 'LANDED '+location.pathname; await new Promise(r=>setTimeout(r,300));} return 'LOGIN_TIMEOUT'})()" 'LANDED')
mark login "$OUT"
echo "$OUT" | grep -q 'LANDED /' || fail login "$OUT"

$AB open http://127.0.0.1:5273/teacher/courses/6/questions >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){if(document.querySelector('.q-btn-import')) return 'QPAGE_READY'; await new Promise(r=>setTimeout(r,300));} return 'QPAGE_TIMEOUT'})()" 'QPAGE_READY')
mark qpage "$OUT"
echo "$OUT" | grep -q 'QPAGE_READY' || fail qpage "$OUT"

# ============ 1. 导入弹窗：上传区结构对齐课件上传 ============
OUT=$(domclick '.q-btn-import')
mark open-import "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.import-dialog'); if(d && d.offsetParent!==null) return 'DLG_READY'; await new Promise(r=>setTimeout(r,250));} return 'DLG_TIMEOUT'})()" 'DLG_READY')
mark import-dlg "$OUT"
echo "$OUT" | grep -q 'DLG_READY' || fail import-dlg "$OUT"

# ① 新上传区结构：inner/icon/title/desc 齐全、dragger 176px、footer 只有取消（无解析按钮）
#    （并保留上一轮口径：「目标课程」字段已移除 + 课程提示行显示具体课程名）
OUT=$(eval_retry "(function(){
  var d=document.querySelector('.import-dialog');
  var inner=d.querySelector('.import-upload-inner');
  var icon=d.querySelector('.import-upload-icon');
  var title=d.querySelector('.import-upload-title');
  var desc=d.querySelector('.import-upload-desc');
  var dragger=d.querySelector('.el-upload-dragger');
  var dh=dragger?Math.round(dragger.getBoundingClientRect().height):0;
  var footerBtns=Array.prototype.map.call(d.querySelectorAll('.creation-dialog-footer .el-button'),function(b){return b.innerText.trim()});
  var hasParseBtn=footerBtns.some(function(t){return t.indexOf('解析')>=0});
  var dw=dragger?Math.round(dragger.getBoundingClientRect().width):0;
  var sel=d.querySelector('.import-form .el-select');
  var sw=sel?Math.round(sel.getBoundingClientRect().width):0;
  var labels=Array.prototype.map.call(d.querySelectorAll('.el-form-item__label'),function(l){return l.innerText.trim()});
  var hasCourse=labels.some(function(t){return t.indexOf('目标课程')>=0});
  var hint=d.querySelector('.import-course-hint');
  var hintText=hint?hint.innerText.replace(/\\s+/g,' ').trim():'';
  return 'UPUI inner='+!!inner+' icon='+!!icon+' title='+(title?title.innerText.trim():'')+' dh='+dh+' footerBtns='+JSON.stringify(footerBtns)+' hasParseBtn='+hasParseBtn+' widthEqual='+(dw===sw)+' courseField='+hasCourse+' hint='+hintText;
})()" 'UPUI')
mark upui "$OUT"
echo "$OUT" | grep -q 'inner=true' || fail upui-inner "$OUT"
echo "$OUT" | grep -q 'icon=true' || fail upui-icon "$OUT"
echo "$OUT" | grep -q 'title=拖入或选择题目文件' || fail upui-title "$OUT"
echo "$OUT" | grep -q 'dh=176' || fail upui-height "$OUT"
echo "$OUT" | grep -q 'hasParseBtn=false' || fail upui-parsebtn "$OUT"
echo "$OUT" | grep -q 'widthEqual=true' || fail upui-width "$OUT"
echo "$OUT" | grep -q 'courseField=false' || fail upui-course "$OUT"
echo "$OUT" | grep -q '导入到课程' || fail upui-hint "$OUT"
echo "$OUT" | grep -q '导入到课程：当前课程' && fail upui-hint-name "$OUT" || true
$AB screenshot test/screenshots/e2e-import-upload-v2.png >>"$LOG" 2>&1

# ============ 2. 选择即上传解析（不点任何按钮）→ 预览抽屉自动打开 ============
$AB upload '.import-uploader input[type=file]' 'D:/Claude_Code/智课系统V2/docs/测试文件目录/题目导入测试样例.docx' >>"$LOG" 2>&1
# 进度面板可能短暂出现（小文件解析快）：轮询记录是否出现过阶段文字，同时等抽屉打开
OUT=$(eval_retry "(async function(){
  var sawProgress=false;
  for(var i=0;i<80;i++){
    var p=document.querySelector('.import-upload-progress-stage');
    if(p && p.innerText.indexOf('正在')>=0) sawProgress=true;
    var d=document.querySelector('.draft-preview-drawer');
    if(d){var cards=document.querySelectorAll('.dp-card'); if(cards.length) return 'DRAWER_READY cards='+cards.length+' sawProgress='+sawProgress;}
    await new Promise(r=>setTimeout(r,200));
  }
  return 'DRAWER_TIMEOUT sawProgress='+sawProgress;
})()" 'DRAWER_READY')
mark auto-import "$OUT"
echo "$OUT" | grep -q 'DRAWER_READY cards=7' || fail auto-import "$OUT"
echo "$OUT" | grep -q 'sawProgress=true' || mark progress-note '小文件解析过快未捕获进度面板（非阻断）'
$AB screenshot test/screenshots/e2e-import-publish-drawer.png >>"$LOG" 2>&1

# ============ 3. 勾选「入库后立即发布」→ 选章节 → 入库勾选 ============
# 按钮合并口径：footer 仅有「入库勾选的 N 题」（primary），无「全部入库」
OUT=$(eval_retry "(function(){
  var btns=Array.prototype.map.call(document.querySelectorAll('.dp-footer-actions .el-button'),function(b){return b.innerText.trim()});
  var hasAll=btns.some(function(t){return t.indexOf('全部入库')>=0});
  var checkedBtns=btns.filter(function(t){return t.indexOf('入库勾选')>=0});
  var primary=document.querySelectorAll('.dp-footer-actions .el-button--primary').length;
  return 'MERGE btns='+JSON.stringify(btns)+' hasAll='+hasAll+' checkedBtnCount='+checkedBtns.length+' primaryCount='+primary;
})()" 'MERGE')
mark merge "$OUT"
echo "$OUT" | grep -q 'hasAll=false' || fail merge-all "$OUT"
echo "$OUT" | grep -q 'checkedBtnCount=1' || fail merge-checked "$OUT"
echo "$OUT" | grep -q 'primaryCount=1' || fail merge-primary "$OUT"

OUT=$(eval_retry "(function(){
  var c=document.querySelector('.dp-publish-check');
  return 'PUBCHECK exists='+!!c+' text='+(c?c.innerText.trim():'');
})()" 'PUBCHECK')
mark pubcheck "$OUT"
echo "$OUT" | grep -q 'exists=true' || fail pubcheck "$OUT"
echo "$OUT" | grep -q '入库后立即发布' || fail pubcheck-text "$OUT"
OUT=$(domclick '.dp-publish-check')
mark pubcheck-tick "$OUT"

# 入库章节：EP 2.14 点击处理器在 .el-select__wrapper；选项 .el-select-dropdown__item 轮询可见后 DOM click
OUT=$(domclick '.draft-preview-drawer .dp-summary .el-select__wrapper')
mark catalog-open "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var items=document.querySelectorAll('.el-select-dropdown__item'); for(var j=0;j<items.length;j++){var r=items[j].getBoundingClientRect(); if(r.height>0){items[j].click(); return 'CATALOG_PICKED '+items[j].innerText.trim();}} await new Promise(r=>setTimeout(r,200));} return 'CATALOG_TIMEOUT'})()" 'CATALOG_PICKED')
mark catalog "$OUT"
echo "$OUT" | grep -q 'CATALOG_PICKED' || fail catalog "$OUT"

# 入库勾选（合并后的唯一 primary 按钮，默认全选即全部入库）
OUT=$(domclick '.dp-footer .el-button--primary')
mark save-all "$OUT"
# 等成功提示「已入库并发布」+ 抽屉关闭
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var msgs=document.querySelectorAll('.el-message'); for(var j=0;j<msgs.length;j++){if(msgs[j].innerText.indexOf('已入库并发布')>=0) return 'PUBLISH_MSG_OK '+msgs[j].innerText.replace(/\\s+/g,' ').trim();} await new Promise(r=>setTimeout(r,250));} return 'MSG_TIMEOUT'})()" 'PUBLISH_MSG_OK')
mark publish-msg "$OUT"
echo "$OUT" | grep -q 'PUBLISH_MSG_OK' || fail publish-msg "$OUT"

# 注意：查重跳过的 2 题按设计保留在批次内（可改题干重试），抽屉不自动关闭；
# 本链不再使用剩余草稿 → drawer 内放弃批次（同时覆盖放弃路径），随后抽屉关闭
OUT=$(eval_retry "(function(){var btns=document.querySelectorAll('.dp-footer .el-button'); var t=null; btns.forEach(function(b){if(b.innerText.indexOf('放弃批次')>=0) t=b;}); if(!t) return 'DOMCLICK_MISS discard'; t.click(); return 'DOMCLICK_OK'})()" 'DOMCLICK_OK')
mark discard "$OUT"
echo "$OUT" | grep -q 'DOMCLICK_OK' || fail discard "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var b=document.querySelector('.el-message-box'); if(b && b.offsetParent!==null) return 'CONFIRM_READY'; await new Promise(r=>setTimeout(r,250));} return 'CONFIRM_TIMEOUT'})()" 'CONFIRM_READY')
mark confirm "$OUT"
echo "$OUT" | grep -q 'CONFIRM_READY' || fail confirm "$OUT"
OUT=$(domclick '.el-message-box .el-button--primary')
mark confirm-ok "$OUT"
# EP 2.14 el-drawer 关闭后根本身 display 保持 flex，不可见性由外层 overlay 控制 → 查 offsetParent
OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var d=document.querySelector('.draft-preview-drawer'); if(d && d.offsetParent===null) return 'DRAWER_CLOSED'; await new Promise(r=>setTimeout(r,250));} return 'CLOSE_TIMEOUT'})()" 'DRAWER_CLOSED')
mark drawer-closed "$OUT"
echo "$OUT" | grep -q 'DRAWER_CLOSED' || fail drawer-closed "$OUT"

# ============ 4. API 验证：5 题入库且 published/import（13/14 查重跳过） ============
VERIFY=$(curl -s --noproxy '*' "http://localhost:8005/api/questions/?course=6&page_size=100" -H "Authorization: Bearer $TOKEN" | python -c "
import sys,json
d=json.load(sys.stdin); data=d.get('data',d)
rows=(data.get('results') if isinstance(data,dict) else data) or []
new=[r for r in rows if r['id'] not in (13,14)]
pub=[r for r in new if r['status']=='published' and r['source']=='import']
print('NEW=%d PUBLISHED_IMPORT=%d IDS=%s' % (len(new), len(pub), ','.join(str(r['id']) for r in new)))")
mark api-verify "$VERIFY"
NEW_IDS=$(echo "$VERIFY" | sed -E 's/.*IDS=([0-9,]*).*/\1/')
echo "$VERIFY" | grep -q 'NEW=5 PUBLISHED_IMPORT=5' || fail api-verify "$VERIFY"

# ============ 5. 清理：只删本链创建的题目 id + 批次残留检查 ============
IFS=',' read -ra IDA <<< "$NEW_IDS"
for id in "${IDA[@]}"; do
  [ -n "$id" ] && curl -s --noproxy '*' -X DELETE "http://localhost:8005/api/questions/$id/" -H "Authorization: Bearer $TOKEN" > /dev/null && echo "[cleanup] deleted question $id"
done
LEFT=$(curl -s --noproxy '*' "http://localhost:8005/api/question-draft-batches/?course=6&status=parsed" -H "Authorization: Bearer $TOKEN" | python -c "import sys,json;d=json.load(sys.stdin);data=d.get('data',d);rows=(data.get('results') if isinstance(data,dict) else data) or [];print(len(rows))")
mark batch-left "parsed_batches=$LEFT"
[ "$LEFT" = "0" ] || fail batch-left "残留 parsed 批次 $LEFT 个"
FINAL=$(curl -s --noproxy '*' "http://localhost:8005/api/questions/?course=6&page_size=100" -H "Authorization: Bearer $TOKEN" | python -c "import sys,json;d=json.load(sys.stdin);data=d.get('data',d);rows=(data.get('results') if isinstance(data,dict) else data) or [];print(' '.join(str(r['id']) for r in rows))")
mark final-questions "$FINAL"
[ "$FINAL" = "13 14" ] || [ "$FINAL" = "14 13" ] || fail final-questions "清理后题目异常：$FINAL"
echo "IMPORT_PUBLISH_E2E_OK"
