#!/bin/bash
# 督管增强一期·第二阶段四项修复验证（单链执行，daemon 不跨调用存活）
# 覆盖：① 视频状态文案 ② 作业/考试时间语义 ③ 抽屉表格截断 ④ AI 语音用量展示
set -u
export AB="/c/Users/张文飞/.workbuddy/binaries/node/versions/22.22.2-6/agent-browser"
SHOTS="D:/Claude_Code/智课系统V2/test/screenshots"
BASE="http://127.0.0.1:5273"
run() { env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy "$AB" "$@"; }
assert() {
  local expr="$1" out
  out=$(run eval "$expr")
  echo "$out" | grep -q "$2" || out=$(run eval "$expr")
  echo "$out"
}
wait_ms() { run eval "(async function(){await new Promise(function(r){setTimeout(r,$1)});return 'WAITED'})()" >/dev/null; }

echo "=== 1. 登录 ==="
run open "$BASE/login" >/dev/null 2>&1
run fill "input[placeholder='请输入用户名']" "admin" >/dev/null
run fill "input[placeholder='请输入密码']" "A0987654" >/dev/null
run click "button.auth-submit" >/dev/null
assert "(async function(){for(var i=0;i<40;i++){if(location.pathname.indexOf('/login')<0)return 'LOGIN_OK path='+location.pathname;await new Promise(function(r){setTimeout(r,250)})}return 'LOGIN_TIMEOUT path='+location.pathname})()" "LOGIN_OK"

echo "=== 2. 教学监管-课程抽屉（①视频状态文案 ②时间语义 ③名称列换行）==="
run open "$BASE/admin/teaching" >/dev/null 2>&1
assert "(async function(){for(var i=0;i<40;i++){if(document.querySelector('.admin-teaching .el-table__row'))return 'TEACHING_OK rows='+document.querySelectorAll('.el-table__row').length;await new Promise(function(r){setTimeout(r,250)})}return 'TEACHING_TIMEOUT path='+location.pathname})()" "TEACHING_OK"
# 首行=课程7（Java程序设计，5 视频/1 作业/1 考试）
run click ".el-table__row" >/dev/null
assert "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.course-drawer');if(d&&document.body.textContent.indexOf('章节结构')>=0)return 'COURSE_DRAWER_OK';await new Promise(function(r){setTimeout(r,250)})}return 'COURSE_DRAWER_TIMEOUT'})()" "COURSE_DRAWER_OK"
# ① 视频标签：显示「配音就绪·已发布」且全文无裸枚举 audio_ready
assert "(function(){var t=document.querySelector('.course-drawer').textContent;return 'VIDEO_TAG display='+(t.indexOf('配音就绪')>=0)+' published='+(t.indexOf('已发布')>=0)+' raw_enum='+(t.indexOf('audio_ready')>=0)})()" "display=true published=true raw_enum=false"
# ② 作业截止/考试时间语义
assert "(function(){var t=document.querySelector('.course-drawer').textContent;return 'TIME deadline='+(t.indexOf('不限制截止时间')>=0)+' exam='+(t.indexOf('此刻开始 至 不限制截止')>=0)})()" "deadline=true exam=true"
# ③ 名称列/进度列不截断（scrollWidth<=clientWidth）且允许换行
assert "(function(){var out=[];['.name-cell','.progress-cell'].forEach(function(sel){var cells=document.querySelectorAll('.course-drawer '+sel+' .cell');var bad=0,wrap=0;cells.forEach(function(c){if(c.scrollWidth>c.clientWidth+1)bad++;if(getComputedStyle(c).whiteSpace==='normal')wrap++});out.push(sel+' total='+cells.length+' truncated='+bad+' wrapped='+wrap)});return out.join(' | ')})()" "truncated=0"
run screenshot "$SHOTS/phase2-course-drawer.png" >/dev/null 2>&1 && echo "screenshot: phase2-course-drawer.png"
run eval "var b=document.querySelector('.course-drawer .drawer-close');if(b){b.click();'CLOSED'}else{'NO_BTN'}" >/dev/null
wait_ms 600

echo "=== 3. 教师监管 Tab（④用量列：token 优先）==="
run eval "var items=document.querySelectorAll('.admin-tabs .el-tabs__item');items[2].click();'TAB_TEACHERS'" >/dev/null
assert "(async function(){for(var i=0;i<30;i++){var rows=document.querySelectorAll('.admin-teaching .el-table__row');if(rows.length&&document.body.textContent.indexOf('t101')>=0)return 'TEACHER_TAB_OK rows='+rows.length;await new Promise(function(r){setTimeout(r,250)})}return 'TEACHER_TAB_TIMEOUT'})()" "TEACHER_TAB_OK"
# 表头为「用量」，t101 行显示 token 口径 21.5 万
# 表头为「用量」，t101 行显示 token 口径 21.5 万（列序：教师/课程/班级/学生/AI调用/用量/状态/活跃/注册，用量=索引5）
assert "(function(){var ths=document.querySelectorAll('.admin-teaching .el-table th .cell');var hdr='';ths.forEach(function(h){if(h.textContent.indexOf('用量')>=0)hdr='用量'});var row=null;document.querySelectorAll('.el-table__row').forEach(function(r){if(r.textContent.indexOf('t101')>=0)row=r});var usage=row?row.querySelectorAll('.el-table__cell')[5].textContent.trim():'NO_ROW';return 'USAGE_COL header='+hdr+' t101_usage='+usage})()" "header=用量 t101_usage=21.5 万"
# 点击 t101 行 → 教师详情抽屉（语音合成按字符计量）
run eval "var row=null;document.querySelectorAll('.el-table__row').forEach(function(r){if(r.textContent.indexOf('t101')>=0)row=r});if(row){row.click();'ROW_CLICKED'}else{'NO_ROW'}" >/dev/null
assert "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.teacher-drawer');if(d&&document.body.textContent.indexOf('AI 调用分布')>=0)return 'TEACHER_DRAWER_OK';await new Promise(function(r){setTimeout(r,250)})}return 'TEACHER_DRAWER_TIMEOUT'})()" "TEACHER_DRAWER_OK"
assert "(function(){var t=document.querySelector('.teacher-drawer').textContent;return 'TTS_USAGE tts='+(t.indexOf('语音合成')>=0)+' chars='+(t.indexOf('3.8 万字符')>=0)+' note='+(t.indexOf('计量口径')>=0)+' bars='+document.querySelectorAll('.teacher-drawer .el-progress').length})()" "tts=true chars=true note=true bars=4"
run screenshot "$SHOTS/phase2-teacher-drawer.png" >/dev/null 2>&1 && echo "screenshot: phase2-teacher-drawer.png"
run eval "var b=document.querySelector('.teacher-drawer .drawer-close');if(b){b.click();'CLOSED'}else{'NO_BTN'}" >/dev/null
wait_ms 600

echo "=== 4. 班级监管 Tab + 班级抽屉（③学情预警列不截断）==="
run eval "var items=document.querySelectorAll('.admin-tabs .el-tabs__item');items[1].click();'TAB_CLASSES'" >/dev/null
assert "(async function(){for(var i=0;i<30;i++){if(document.body.textContent.indexOf('作业提交率')>=0&&document.querySelectorAll('.el-table__row').length)return 'CLASS_TAB_OK';await new Promise(function(r){setTimeout(r,250)})}return 'CLASS_TAB_TIMEOUT'})()" "CLASS_TAB_OK"
run click ".el-table__row" >/dev/null
assert "(async function(){for(var i=0;i<30;i++){var d=document.querySelector('.class-drawer');if(d&&document.body.textContent.indexOf('逐学生学习进度')>=0)return 'CLASS_DRAWER_OK rows='+document.querySelectorAll('.class-drawer .el-table__row').length;await new Promise(function(r){setTimeout(r,250)})}return 'CLASS_DRAWER_TIMEOUT'})()" "CLASS_DRAWER_OK"
assert "(function(){var cells=document.querySelectorAll('.class-drawer .warn-cell .cell');var bad=0,wrap=0;cells.forEach(function(c){if(c.scrollWidth>c.clientWidth+1)bad++;if(getComputedStyle(c).whiteSpace==='normal')wrap++});return 'WARN_CELL total='+cells.length+' truncated='+bad+' wrapped='+wrap})()" "truncated=0"
run screenshot "$SHOTS/phase2-class-drawer.png" >/dev/null 2>&1 && echo "screenshot: phase2-class-drawer.png"

echo "=== 5. 教师监管 Tab 截图（用量列）==="
run eval "var b=document.querySelector('.class-drawer .drawer-close');if(b){b.click();'CLOSED'}else{'NO_BTN'}" >/dev/null
wait_ms 600
# 轮询切 tab（防瞬时空白/daemon 抖动导致 items 为空）
assert "(async function(){for(var i=0;i<40;i++){var items=document.querySelectorAll('.admin-tabs .el-tabs__item');if(items.length>2){items[2].click();return 'TAB_TEACHERS_OK count='+items.length}await new Promise(function(r){setTimeout(r,250)})}return 'TAB_TEACHERS_TIMEOUT count='+document.querySelectorAll('.admin-tabs .el-tabs__item').length})()" "TAB_TEACHERS_OK"
assert "(async function(){for(var i=0;i<30;i++){if(document.body.textContent.indexOf('t101')>=0)return 'TEACHERS_VISIBLE';await new Promise(function(r){setTimeout(r,250)})}return 'TEACHERS_TIMEOUT'})()" "TEACHERS_VISIBLE"
wait_ms 800
run screenshot "$SHOTS/phase2-teaching-teachers.png" >/dev/null 2>&1 && echo "screenshot: phase2-teaching-teachers.png"
echo "=== ALL DONE ==="
