#!/bin/bash
# E2E：手机号停止采集验证
# ① /api/auth/me/ 响应无 phone 键  ② 管理端用户管理无手机号列/表单字段
# ③ 个人中心无手机号输入框  ④ 仅填姓名（phone=NULL）即可邀请码入班
set -u
cd /d/Claude_Code/智课系统V2 || exit 1
LOG=test/e2e_phone_removal.log
AB=agent-browser
: > "$LOG"

eval_retry() {
  local out
  out=$($AB eval "$1" 2>>"$LOG")
  if ! echo "$out" | grep -qE "$2"; then out=$($AB eval "$1" 2>>"$LOG"); fi
  echo "$out"
}
mark() { echo "[$1] $2"; }
fail() { echo "E2E_FAIL $1: $2"; exit 1; }

# ---- 0. API：me 响应无 phone 键 ----
TOKEN=$(curl -s --noproxy '*' -X POST http://localhost:8005/api/auth/login/ -H 'Content-Type: application/json' -d '{"username":"t101","password":"pass1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['data']['token']['access'])")
OUT=$(curl -s --noproxy '*' http://localhost:8005/api/auth/me/ -H "Authorization: Bearer $TOKEN" | python -c "
import sys,json
d=json.load(sys.stdin)['data']
print('ME has_phone=%s keys=%s' % ('phone' in d, ','.join(sorted(d.keys()))))")
mark me-api "$OUT"
echo "$OUT" | grep -q 'has_phone=False' || fail me-api "$OUT"

# ---- 1. 仅姓名即可入班（phone=NULL 的学生） ----
OUT=$(cd backend && ./venv/Scripts/python.exe manage.py shell -c "
from apps.users.models import User
from apps.classroom.models import ClassRoom
from rest_framework.test import APIClient
u = User.objects.filter(role='student', real_name__gt='', phone__isnull=True).first()
if not u:
    print('NO_STUDENT'); raise SystemExit
c = ClassRoom.objects.filter(invite_enabled=True).exclude(students__student=u).first()
if not c:
    print('NO_CLASSROOM'); raise SystemExit
cl = APIClient(); cl.force_authenticate(user=u)
r = cl.post('/api/classes/join/', {'invite_code': c.invite_code}, format='json')
print('JOIN status=%s msg=%s' % (r.status_code, r.data.get('message')))
# 回滚：退出班级保持现场干净
from apps.classroom.models import ClassStudent
ClassStudent.objects.filter(classroom=c, student=u).delete()
print('CLEANED')" 2>&1 | grep -E 'JOIN|CLEANED|NO_')
mark join "$OUT"
echo "$OUT" | grep -q 'JOIN status=200' || fail join "$OUT"

# ---- 2. 管理端：用户管理无手机号列 + 新建表单无手机号 ----
$AB close --all >>"$LOG" 2>&1
$AB open http://127.0.0.1:5273/login >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入用户名"]' admin >>"$LOG" 2>&1
$AB fill 'input[placeholder="请输入密码"]' A0987654 >>"$LOG" 2>&1
$AB click '.auth-submit' >>"$LOG" 2>&1
eval_retry "(async function(){for(var i=0;i<50;i++){if(location.pathname.indexOf('/login')<0) return 'LANDED'; await new Promise(r=>setTimeout(r,300));} return 'TIMEOUT'})()" 'LANDED' > /dev/null
$AB open http://127.0.0.1:5273/admin/users >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<50;i++){var th=document.querySelectorAll('.user-table .el-table__header th'); if(th.length){var heads=Array.prototype.map.call(th,function(t){return t.innerText.trim()}); return 'HEADS '+JSON.stringify(heads)+' hasPhone='+heads.some(function(h){return h.indexOf('手机号')>=0});} await new Promise(r=>setTimeout(r,300));} return 'TIMEOUT'})()" 'HEADS')
mark admin-table "$OUT"
echo "$OUT" | grep -q 'hasPhone=false' || fail admin-table "$OUT"
# 新建账号弹窗无手机号字段
$AB eval "(function(){var btns=document.querySelectorAll('.head-actions .el-button'); for(var i=0;i<btns.length;i++){if(btns[i].innerText.indexOf('新建账号')>=0){btns[i].click(); return 'OK'}} return 'MISS'})()" | grep -q 'OK' || fail open-create 'button not found'
OUT=$(eval_retry "(async function(){for(var i=0;i<30;i++){var dlg=document.querySelector('.el-dialog'); if(dlg && dlg.offsetParent!==null){var labels=Array.prototype.map.call(dlg.querySelectorAll('.el-form-item__label'),function(l){return l.innerText.trim()}); return 'DLG '+JSON.stringify(labels)+' hasPhone='+labels.some(function(t){return t.indexOf('手机号')>=0});} await new Promise(r=>setTimeout(r,250));} return 'TIMEOUT'})()" 'DLG')
mark admin-create "$OUT"
echo "$OUT" | grep -q 'hasPhone=false' || fail admin-create "$OUT"
$AB screenshot test/screenshots/e2e-admin-users-nophone.png >>"$LOG" 2>&1
$AB eval "(function(){var b=document.querySelector('.el-dialog__header-btn')||document.querySelector('.el-dialog .el-dialog__close'); if(b){b.click();return 'CLOSED'} return 'NA'})()" >/dev/null 2>&1

# ---- 3. 个人中心无手机号输入框 ----
$AB open http://127.0.0.1:5273/profile >>"$LOG" 2>&1
OUT=$(eval_retry "(async function(){for(var i=0;i<50;i++){var form=document.querySelector('.settings-form'); if(form){var labels=Array.prototype.map.call(form.querySelectorAll('.el-form-item__label'),function(l){return l.innerText.trim()}); return 'PROFILE '+JSON.stringify(labels)+' hasPhone='+labels.some(function(t){return t.indexOf('手机号')>=0});} await new Promise(r=>setTimeout(r,300));} return 'TIMEOUT'})()" 'PROFILE')
mark profile "$OUT"
echo "$OUT" | grep -q 'hasPhone=false' || fail profile "$OUT"
$AB screenshot test/screenshots/e2e-profile-nophone.png >>"$LOG" 2>&1

$AB close --all >>"$LOG" 2>&1
echo "PHONE_REMOVAL_E2E_OK"
