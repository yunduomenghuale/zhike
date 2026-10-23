#!/bin/bash
# E2E：导入弹窗 UI 修订验证 + docx 测试文件导入全流程
# 断言：① 「目标课程」字段已移除 + 课程提示行存在 ② 上传区宽度与章节下拉/表单内容区一致
#       ③ docx 上传解析 7 题 ④ 预览抽屉标签列对齐 ⑤ 结束 API 兜底清理批次
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_import_ui.log
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

# ============ 1. 导入弹窗 UI 断言 ============
OUT=$(domclick '.q-btn-import')
mark open-import "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.import-dialog'); if(d && d.offsetParent!==null) return 'DLG_READY'; await new Promise(r=>setTimeout(r,250));} return 'DLG_TIMEOUT'})()" 'DLG_READY')
mark import-dlg "$OUT"
echo "$OUT" | grep -q 'DLG_READY' || fail import-dlg "$OUT"

# ① 目标课程字段移除 + 课程提示行
OUT=$(eval_retry "(function(){
  var d=document.querySelector('.import-dialog');
  var labels=Array.prototype.map.call(d.querySelectorAll('.el-form-item__label'),function(l){return l.innerText.trim()});
  var hasCourse=labels.some(function(t){return t.indexOf('目标课程')>=0});
  var hint=d.querySelector('.import-course-hint');
  var hintText=hint?hint.innerText.replace(/\\s+/g,' ').trim():'';
  return 'FIELDS labels='+JSON.stringify(labels)+' courseField='+hasCourse+' hint='+hintText;
})()" 'FIELDS')
mark fields "$OUT"
echo "$OUT" | grep -q 'courseField=false' || fail fields-course "$OUT"
echo "$OUT" | grep -q '导入到课程' || fail fields-hint "$OUT"
# 课程工作台视图下提示行应显示具体课程名（非「当前课程」兜底态）
echo "$OUT" | grep -q '导入到课程：当前课程' && fail fields-hint-name "$OUT" || true

# ② 上传区宽度与章节下拉/表单内容区一致
OUT=$(eval_retry "(function(){
  var d=document.querySelector('.import-dialog');
  var dragger=d.querySelector('.el-upload-dragger');
  var sel=d.querySelector('.import-form .el-select');
  var content=d.querySelector('.import-form .el-form-item__content');
  var dw=Math.round(dragger.getBoundingClientRect().width);
  var sw=Math.round(sel.getBoundingClientRect().width);
  var cw=Math.round(content.getBoundingClientRect().width);
  var dl=Math.round(dragger.getBoundingClientRect().left);
  var sl=Math.round(sel.getBoundingClientRect().left);
  return 'WIDTHS dragger='+dw+' select='+sw+' content='+cw+' leftAlign='+(dl===sl)+' equal='+(dw===sw&&sw===cw);
})()" 'WIDTHS')
mark widths "$OUT"
echo "$OUT" | grep -q 'equal=true' || fail widths "$OUT"
echo "$OUT" | grep -q 'leftAlign=true' || fail widths-left "$OUT"
$AB screenshot test/screenshots/e2e-import-ui.png >>"$LOG" 2>&1

# ============ 2. docx 上传 → 解析 → 预览 ============
$AB upload '.import-uploader input[type=file]' 'D:/Claude_Code/智课系统V2/docs/测试文件目录/题目导入测试样例.docx' >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var n=document.querySelector('.import-uploader .el-upload-list__item-name'); if(n && n.innerText.indexOf('题目导入测试样例.docx')>=0) return 'FILE_OK'; await new Promise(r=>setTimeout(r,250));} return 'FILE_TIMEOUT'})()" 'FILE_OK')
mark upload "$OUT"
echo "$OUT" | grep -q 'FILE_OK' || fail upload "$OUT"

OUT=$(domclick '.import-dialog .q-btn-primary')
mark parse "$OUT"
OUT=$(eval_retry "(async function(){for(var i=0;i<60;i++){var d=document.querySelector('.draft-preview-drawer'); if(d){var cards=document.querySelectorAll('.dp-card'); if(cards.length) return 'DRAWER_READY cards='+cards.length;} await new Promise(r=>setTimeout(r,300));} return 'DRAWER_TIMEOUT'})()" 'DRAWER_READY')
mark drawer "$OUT"
echo "$OUT" | grep -q 'DRAWER_READY cards=7' || fail drawer "$OUT"

# 预览页布局：标签列对齐（72px）
OUT=$(eval_retry "(function(){
  var drawer=document.querySelector('.draft-preview-drawer');
  var cards=drawer.querySelectorAll('.dp-card');
  var labelLefts={}, contentLefts={};
  cards.forEach(function(card){
    card.querySelectorAll('.el-form-item').forEach(function(it){
      var l=it.querySelector('.el-form-item__label');
      var c=it.querySelector('.el-form-item__content');
      if(!l||!c) return;
      var lx=Math.round(l.getBoundingClientRect().left);
      var cx=Math.round(c.getBoundingClientRect().left);
      labelLefts[lx]=(labelLefts[lx]||0)+1;
      contentLefts[cx]=(contentLefts[cx]||0)+1;
    });
  });
  var lk=Object.keys(labelLefts), ck=Object.keys(contentLefts);
  return 'ALIGN ok='+(lk.length===1&&ck.length===1)+' labelKeys='+lk.join('|')+' contentKeys='+ck.join('|');
})()" 'ALIGN')
mark align "$OUT"
echo "$OUT" | grep -q 'ALIGN ok=true' || fail align "$OUT"
$AB screenshot test/screenshots/e2e-import-docx-preview.png >>"$LOG" 2>&1

# ============ 3. 清理：drawer 内放弃批次（含 API 兜底） ============
OUT=$(eval_retry "(function(){var btns=document.querySelectorAll('.dp-footer .el-button'); var t=null; btns.forEach(function(b){if(b.innerText.indexOf('放弃批次')>=0) t=b;}); if(!t) return 'DOMCLICK_MISS discard'; t.click(); return 'DOMCLICK_OK'})()" 'DOMCLICK_OK')
mark discard "$OUT"
DISCARD_OK=0
if echo "$OUT" | grep -q 'DOMCLICK_OK'; then
  OUT=$(eval_retry "(async function(){for(var i=0;i<20;i++){var b=document.querySelector('.el-message-box'); if(b && b.offsetParent!==null) return 'CONFIRM_READY'; await new Promise(r=>setTimeout(r,250));} return 'CONFIRM_TIMEOUT'})()" 'CONFIRM_READY')
  mark confirm "$OUT"
  if echo "$OUT" | grep -q 'CONFIRM_READY'; then
    OUT=$(domclick '.el-message-box .el-button--primary')
    mark confirm-ok "$OUT"
    # EP 2.14 el-drawer 关闭后根本身 display 保持 flex，不可见性由外层 overlay 控制 → 查 offsetParent
    OUT=$(eval_retry "(async function(){for(var i=0;i<40;i++){var d=document.querySelector('.draft-preview-drawer'); if(d && d.offsetParent===null) return 'DRAWER_CLOSED'; await new Promise(r=>setTimeout(r,250));} return 'CLOSE_TIMEOUT'})()" 'DRAWER_CLOSED')
    mark closed "$OUT"
    echo "$OUT" | grep -q 'DRAWER_CLOSED' && DISCARD_OK=1
  fi
fi

# API 兜底清理（无论 drawer discard 是否生效，确保不遗留 E2E 数据）
TOKEN=$(curl -s --noproxy '*' -X POST http://localhost:8005/api/auth/login/ -H 'Content-Type: application/json' -d '{"username":"t101","password":"pass1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token']['access'])")
IDS=$(curl -s --noproxy '*' "http://localhost:8005/api/question-draft-batches/?course=6&status=parsed" -H "Authorization: Bearer $TOKEN" | python -c "import sys,json;d=json.load(sys.stdin);print(' '.join(str(r['id']) for r in (d.get('results') or [])))")
for id in $IDS; do
  curl -s --noproxy '*' -X DELETE "http://localhost:8005/api/question-draft-batches/$id/" -H "Authorization: Bearer $TOKEN" > /dev/null
  echo "[cleanup] deleted batch $id"
done
[ $DISCARD_OK -eq 1 ] && echo "DISCARD_PATH_OK" || echo "DISCARD_PATH_FALLBACK_API"
echo "IMPORT_UI_E2E_OK"
