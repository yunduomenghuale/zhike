var store = require('./user-data-store');
var reportGenerator = require('./report-generator');
var fs = require('fs');
var path = require('path');
var crypto = require('crypto');

var sessions = {};

// 智课平台单点免登（SSO）：HMAC-SHA256 验签，密钥与智课平台后端的
// DEMO1_SSO_SECRET 保持一致；开发默认值仅限本地，生产用环境变量覆盖。
var SSO_SECRET = process.env.DEMO1_SSO_SECRET || 'zhike-demo1-sso-dev-secret';

function sendJson(res, code, data) {
    res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Authorization,Content-Type' });
    res.end(JSON.stringify(data));
}

function readBody(req) {
    return new Promise(function(resolve) {
        var body = '';
        req.on('data', function(c) { body += c; });
        req.on('end', function() { resolve(body); });
    });
}

function getSessionUser(req) {
    var auth = req.headers['authorization'];
    if (!auth) return null;
    var token = auth.replace('Bearer ', '');
    return sessions[token] || null;
}

function createToken() {
    return require('crypto').randomBytes(16).toString('hex');
}

function handleRoute(req, res, pathname) {
    var method = req.method;

    if (pathname === '/api/user/login' && method === 'POST') {
        return handleLogin(req, res);
    }
    if (pathname === '/api/user/sso-login' && method === 'POST') {
        return handleSsoLogin(req, res);
    }
    if (pathname === '/api/user/logout' && method === 'POST') {
        return handleLogout(req, res);
    }
    if (pathname === '/api/user/info' && method === 'GET') {
        return handleUserInfo(req, res);
    }
    if (pathname === '/api/user/change-password' && method === 'POST') {
        return handleChangePassword(req, res);
    }

    if (pathname === '/api/classes' && method === 'GET') {
        return sendJson(res, 200, { classes: store.getClasses() });
    }
    if (pathname === '/api/classes' && method === 'POST') {
        return handleCreateClass(req, res);
    }
    if (pathname.match(/^\/api\/classes\/(.+)$/) && method === 'DELETE') {
        var clsName = decodeURIComponent(pathname.replace('/api/classes/', ''));
        return handleDeleteClass(res, clsName);
    }

    if (pathname === '/api/students' && method === 'GET') {
        return sendJson(res, 200, { students: store.getStudents() });
    }
    if (pathname === '/api/students' && method === 'POST') {
        return handleCreateStudent(req, res);
    }
    if (pathname === '/api/students/batch' && method === 'POST') {
        return handleBatchImportStudents(req, res);
    }
    if (pathname.match(/^\/api\/students\/(.+)$/) && method === 'DELETE') {
        var sid = decodeURIComponent(pathname.replace('/api/students/', ''));
        return handleDeleteStudent(res, sid);
    }
    if (pathname.match(/^\/api\/students\/(.+)\/reset-password$/) && method === 'POST') {
        var sid2 = decodeURIComponent(pathname.replace('/api/students/', '').replace('/reset-password', ''));
        return handleResetPassword(res, sid2);
    }
    if (pathname.match(/^\/api\/students\/(.+)\/contact$/) && method === 'POST') {
        var sid4 = decodeURIComponent(pathname.replace('/api/students/', '').replace('/contact', ''));
        return handleUpdateStudentContact(req, res, sid4);
    }

    if (pathname === '/api/majors' && method === 'GET') {
        return sendJson(res, 200, { majors: store.getMajors() });
    }
    if (pathname === '/api/majors' && method === 'POST') {
        return handleAddMajor(req, res);
    }
    if (pathname.match(/^\/api\/majors\/(.+)$/) && method === 'DELETE') {
        var majorName = decodeURIComponent(pathname.replace('/api/majors/', ''));
        return handleDeleteMajor(res, majorName);
    }

    if (pathname === '/api/depts' && method === 'GET') {
        return sendJson(res, 200, { depts: store.getDepts() });
    }
    if (pathname === '/api/depts' && method === 'POST') {
        return handleAddDept(req, res);
    }
    if (pathname.match(/^\/api\/depts\/(.+)$/) && method === 'DELETE') {
        var deptName = decodeURIComponent(pathname.replace('/api/depts/', ''));
        return handleDeleteDept(res, deptName);
    }

    if (pathname === '/api/teachers' && method === 'GET') {
        return sendJson(res, 200, { teachers: store.getTeachers() });
    }
    if (pathname === '/api/teachers' && method === 'POST') {
        return handleCreateTeacher(req, res);
    }
    if (pathname === '/api/teachers' && method === 'PUT') {
        return handleUpdateTeacher(req, res);
    }
    if (pathname.match(/^\/api\/teachers\/(.+)$/) && method === 'DELETE') {
        var tid = decodeURIComponent(pathname.replace('/api/teachers/', ''));
        return handleDeleteTeacher(res, tid);
    }
    if (pathname.match(/^\/api\/teachers\/(.+)\/reset-password$/) && method === 'POST') {
        var tid2 = decodeURIComponent(pathname.replace('/api/teachers/', '').replace('/reset-password', ''));
        return handleResetTeacherPassword(res, tid2);
    }
    if (pathname.match(/^\/api\/teachers\/(.+)\/contact$/) && method === 'POST') {
        var tid3 = decodeURIComponent(pathname.replace('/api/teachers/', '').replace('/contact', ''));
        return handleUpdateTeacherContact(req, res, tid3);
    }

    if (pathname === '/api/lab-schedules' && method === 'GET') {
        return sendJson(res, 200, { schedules: store.getLabSchedules() });
    }
    if (pathname === '/api/lab-schedules' && method === 'POST') {
        return handleSaveLabSchedules(req, res);
    }

    if (pathname === '/api/study/detail' && method === 'GET') {
        var studentId = req.url.split('?studentId=')[1];
        if (studentId) studentId = decodeURIComponent(studentId.split('&')[0]);
        return sendJson(res, 200, { detail: store.getStudyDetail(studentId || '') });
    }
    if (pathname === '/api/study/detail' && method === 'POST') {
        return handleSaveStudyDetail(req, res);
    }
    if (pathname === '/api/study/time' && method === 'POST') {
        return handleSaveStudyTime(req, res);
    }
    if (pathname === '/api/study/login-count' && method === 'POST') {
        return handleSaveLoginCount(req, res);
    }
    if (pathname === '/api/study/all-details' && method === 'GET') {
        return sendJson(res, 200, { details: store.getAllStudyDetails() });
    }
    if (pathname === '/api/study/all-times' && method === 'GET') {
        return sendJson(res, 200, { times: store.getAllStudyTimes() });
    }

    if (pathname === '/api/lab-reports' && method === 'GET') {
        var sid3 = req.url.split('?studentId=')[1];
        if (sid3) sid3 = decodeURIComponent(sid3.split('&')[0]);
        return sendJson(res, 200, { reports: store.getLabReports(sid3 || '') });
    }
    if (pathname === '/api/lab-reports' && method === 'POST') {
        return handleSaveLabReport(req, res);
    }
    if (pathname === '/api/lab-reports/all' && method === 'GET') {
        return sendJson(res, 200, { allReports: store.getAllLabReports() });
    }

    if (pathname === '/api/generate-report' && method === 'POST') {
        return handleGenerateReport(req, res);
    }

    if (pathname.startsWith('/api/download-report/') && method === 'GET') {
        return handleDownloadReport(req, res, pathname);
    }

    if (pathname === '/api/learn-counts' && method === 'GET') {
        return sendJson(res, 200, { counts: store.getLearnCounts() });
    }
    if (pathname === '/api/learn-counts' && method === 'POST') {
        return handleSaveLearnCounts(req, res);
    }

    if (pathname === '/api/stats/overview' && method === 'GET') {
        var classes = store.getClasses();
        var students = store.getStudents();
        var times = store.getAllStudyTimes();
        var totalTime = 0;
        Object.values(times).forEach(function(t) { totalTime += t; });
        return sendJson(res, 200, { classCount: classes.length, studentCount: students.length, totalStudyTime: Math.round(totalTime) });
    }

    return false;
}

async function handleLogin(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var username = (data.username || '').trim();
        var password = (data.password || '').trim();
        if (!username || !password) { sendJson(res, 400, { error: '用户名和密码不能为空' }); return; }
        var users = store.getUsers();
        var userKey = username;
        if (username.startsWith('student_') || username.startsWith('teacher_')) userKey = username;
        else if (users[username]) userKey = username;
        else if (users['teacher_' + username]) userKey = 'teacher_' + username;
        else if (users['student_' + username]) userKey = 'student_' + username;
        else userKey = username;

        var user = users[userKey];
        if (!user) { sendJson(res, 401, { error: '用户不存在' }); return; }
        var hash = await store.hashPassword(password);
        if (user.passwordHash !== hash) { sendJson(res, 401, { error: '密码错误' }); return; }
        var token = createToken();
        sessions[token] = { username: user.username, type: user.type, name: user.name, typeName: user.typeName, icon: user.icon };
        var loginCounts = readFile2('login-counts.json') || {};
        if (user.type === 'student') {
            loginCounts[user.username] = (loginCounts[user.username] || 0) + 1;
            writeFile2('login-counts.json', loginCounts);
        }
        sendJson(res, 200, { token: token, user: { username: user.username, type: user.type, name: user.name, typeName: user.typeName, icon: user.icon, firstLogin: user.firstLogin === true } });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleSsoLogin(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var ticket = String(data.ticket || '');
        var dot = ticket.lastIndexOf('.');
        if (dot <= 0) { sendJson(res, 400, { error: '免登票据格式无效' }); return; }

        var payloadB64 = ticket.slice(0, dot);
        var sig = ticket.slice(dot + 1);
        var expected = crypto.createHmac('sha256', SSO_SECRET).update(payloadB64).digest('hex');
        var sigBuf = Buffer.from(String(sig));
        var expBuf = Buffer.from(expected);
        if (sigBuf.length !== expBuf.length || !crypto.timingSafeEqual(sigBuf, expBuf)) {
            sendJson(res, 401, { error: '免登票据签名无效' }); return;
        }

        var payload = JSON.parse(Buffer.from(payloadB64, 'base64').toString('utf8'));
        if (!payload.u || !payload.exp) { sendJson(res, 400, { error: '免登票据内容无效' }); return; }
        if (Date.now() / 1000 > payload.exp) { sendJson(res, 401, { error: '免登票据已过期，请从智课平台重新进入' }); return; }

        // 角色映射：智课平台 teacher/student/admin -> 本平台账号类型
        var type = payload.r === 'admin' ? 'admin' : (payload.r === 'teacher' ? 'teacher' : 'student');
        var typeName = type === 'admin' ? '管理员' : (type === 'teacher' ? '教师' : '学生');
        var userKey = type + '_' + payload.u;

        // 首次免登自动开通本地账号（无密码，仅能通过 SSO 进入）
        var users = store.getUsers();
        var user = users[userKey];
        if (!user) {
            user = {
                username: payload.u,
                passwordHash: '',
                type: type,
                typeName: typeName,
                icon: type === 'student' ? '🎓' : (type === 'teacher' ? '👨‍🏫' : '⚙️'),
                name: payload.n || payload.u,
                firstLogin: false,
                sso: true
            };
            users[userKey] = user;
            store.saveUsers(users);
        } else if (payload.n && user.name !== payload.n) {
            user.name = payload.n;
            store.saveUsers(users);
        }

        var token = createToken();
        sessions[token] = { username: user.username, type: user.type, name: user.name, typeName: user.typeName, icon: user.icon };
        if (user.type === 'student') {
            var loginCounts = readFile2('login-counts.json') || {};
            loginCounts[user.username] = (loginCounts[user.username] || 0) + 1;
            writeFile2('login-counts.json', loginCounts);
        }
        sendJson(res, 200, { token: token, user: { username: user.username, type: user.type, name: user.name, typeName: user.typeName, icon: user.icon, firstLogin: false } });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

function readFile2(name) {
    var p = require('path').join(require('path').join(__dirname, 'user-data'), name);
    if (!require('fs').existsSync(p)) return null;
    try { return JSON.parse(require('fs').readFileSync(p, 'utf8')); }
    catch (e) { return null; }
}

function writeFile2(name, data) {
    var p = require('path').join(require('path').join(__dirname, 'user-data'), name);
    require('fs').writeFileSync(p, JSON.stringify(data, null, 2), 'utf8');
}

function handleLogout(req, res) {
    var auth = req.headers['authorization'];
    if (auth) { var token = auth.replace('Bearer ', ''); delete sessions[token]; }
    sendJson(res, 200, { message: '已退出登录' });
}

function handleUserInfo(req, res) {
    var user = getSessionUser(req);
    if (!user) { sendJson(res, 401, { error: '未登录' }); return; }
    var result = { username: user.username, type: user.type, name: user.name, typeName: user.typeName, icon: user.icon };
    if (user.type === 'student') {
        var students = store.getStudents();
        var s = students.find(function(st) { return st.id === user.username; });
        if (s) {
            result.loginCount = store.getLoginCount(user.username);
            result.totalStudyTime = store.getStudyTime(user.username);
        }
    }
    sendJson(res, 200, { user: result });
}

async function handleChangePassword(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var username = data.username;
        var oldPassword = data.oldPassword;
        var newPassword = data.newPassword;
        var users = store.getUsers();
        var userKey = username;
        if (username.startsWith('student_') || username.startsWith('teacher_')) userKey = username;
        else if (users[username]) userKey = username;
        else if (users['teacher_' + username]) userKey = 'teacher_' + username;
        else if (users['student_' + username]) userKey = 'student_' + username;
        else userKey = username;
        var user = users[userKey];
        if (!user) { sendJson(res, 404, { error: '用户不存在' }); return; }
        var oldHash = await store.hashPassword(oldPassword);
        if (user.passwordHash !== oldHash) { sendJson(res, 401, { error: '原密码错误' }); return; }
        var newHash = await store.hashPassword(newPassword);
        user.passwordHash = newHash;
        user.firstLogin = false;
        store.saveUsers(users);
        sendJson(res, 200, { message: '密码修改成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleCreateClass(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var name = (data.name || '').trim();
        if (!name) { sendJson(res, 400, { error: '班级名称不能为空' }); return; }
        var classes = store.getClasses();
        if (classes.find(function(c) { return c.name === name; })) { sendJson(res, 400, { error: '班级已存在' }); return; }
        classes.push({ name: name, createTime: new Date().toISOString() });
        store.saveClasses(classes);
        sendJson(res, 200, { message: '创建成功', classes: classes });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

function handleDeleteClass(res, name) {
    var classes = store.getClasses();
    classes = classes.filter(function(c) { return c.name !== name; });
    store.saveClasses(classes);
    var students = store.getStudents();
    students = students.filter(function(s) { return s.classname !== name; });
    store.saveStudents(students);
    sendJson(res, 200, { message: '删除成功', classes: classes, students: students });
}

async function handleCreateStudent(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var sid = (data.id || '').trim();
        var sname = (data.name || '').trim();
        var smajor = (data.major || '').trim();
        var sclass = (data.classname || '').trim();
        if (!sid || !sname || !smajor || !sclass) { sendJson(res, 400, { error: '请填写完整信息' }); return; }
        var students = store.getStudents();
        if (students.find(function(s) { return s.id === sid; })) { sendJson(res, 400, { error: '学号已存在' }); return; }
        students.push({ id: sid, name: sname, major: smajor, classname: sclass, loginCount: 0, totalStudyTime: 0 });
        store.saveStudents(students);
        var users = store.getUsers();
        var hash = await store.hashPassword(sid);
        users['student_' + sid] = { username: sid, passwordHash: hash, type: 'student', typeName: '学生', icon: '👨‍🎓', name: sname, firstLogin: true };
        store.saveUsers(users);
        sendJson(res, 200, { message: '添加成功', students: students });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleBatchImportStudents(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var classname = data.classname;
        var items = data.students;
        if (!classname || !items || !items.length) { sendJson(res, 400, { error: '参数不完整' }); return; }
        var students = store.getStudents();
        var users = store.getUsers();
        var added = 0;
        for (var i = 0; i < items.length; i++) {
            var row = items[i];
            var sid = String(row['学号'] || row.id || '').trim();
            var sname = String(row['姓名'] || row.name || '').trim();
            var smajor = String(row['专业'] || row.major || '').trim();
            if (!sid || !sname) continue;
            if (students.find(function(s) { return s.id === sid; })) continue;
            students.push({ id: sid, name: sname, major: smajor, classname: classname, loginCount: 0, totalStudyTime: 0 });
            var hash = await store.hashPassword(sid);
            users['student_' + sid] = { username: sid, passwordHash: hash, type: 'student', typeName: '学生', icon: '👨‍🎓', name: sname, firstLogin: true };
            added++;
        }
        store.saveStudents(students);
        store.saveUsers(users);
        sendJson(res, 200, { message: '导入成功，新增' + added + '名学生', added: added, students: students });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

function handleDeleteStudent(res, id) {
    var students = store.getStudents();
    students = students.filter(function(s) { return s.id !== id; });
    store.saveStudents(students);
    var users = store.getUsers();
    delete users['student_' + id];
    store.saveUsers(users);
    sendJson(res, 200, { message: '删除成功', students: students });
}

async function handleResetPassword(res, id) {
    var users = store.getUsers();
    var userKey = 'student_' + id;
    if (!users[userKey]) { sendJson(res, 404, { error: '未找到该学生账号' }); return; }
    var hash = await store.hashPassword(id);
    users[userKey].passwordHash = hash;
    users[userKey].firstLogin = true;
    store.saveUsers(users);
    sendJson(res, 200, { message: '密码已重置为学号' });
}

async function handleSaveLabSchedules(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        store.saveLabSchedules(data.schedules || {});
        sendJson(res, 200, { message: '保存成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleSaveStudyDetail(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        store.saveStudyDetail(data.studentId, data.detail);
        sendJson(res, 200, { message: '保存成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleSaveStudyTime(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        store.saveStudyTime(data.studentId, data.time);
        var students = store.getStudents();
        var s = students.find(function(st) { return st.id === data.studentId; });
        if (s) { s.totalStudyTime = data.time; store.saveStudents(students); }
        sendJson(res, 200, { message: '保存成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleSaveLoginCount(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        store.saveLoginCount(data.studentId, data.count);
        var students = store.getStudents();
        var s = students.find(function(st) { return st.id === data.studentId; });
        if (s) { s.loginCount = data.count; store.saveStudents(students); }
        sendJson(res, 200, { message: '保存成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleSaveLabReport(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var reports = store.getLabReports(data.studentId);
        if (data.replace) {
            reports = data.reports || [];
        } else {
            reports.push(data.report);
        }
        store.saveLabReports(data.studentId, reports);
        sendJson(res, 200, { message: '保存成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleSaveLearnCounts(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        store.saveLearnCounts(data.counts || {});
        sendJson(res, 200, { message: '保存成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleAddMajor(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var name = (data.name || '').trim();
        if (!name) { sendJson(res, 400, { error: '专业名称不能为空' }); return; }
        var majors = store.getMajors();
        if (majors.indexOf(name) >= 0) { sendJson(res, 400, { error: '该专业已存在' }); return; }
        majors.push(name);
        store.saveMajors(majors);
        sendJson(res, 200, { message: '添加成功', majors: majors });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

function handleDeleteMajor(res, name) {
    var majors = store.getMajors();
    majors = majors.filter(function(m) { return m !== name; });
    store.saveMajors(majors);
    sendJson(res, 200, { message: '删除成功', majors: majors });
}

async function handleAddDept(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var name = (data.name || '').trim();
        if (!name) { sendJson(res, 400, { error: '组织名称不能为空' }); return; }
        var depts = store.getDepts();
        if (depts.indexOf(name) >= 0) { sendJson(res, 400, { error: '该组织已存在' }); return; }
        depts.push(name);
        store.saveDepts(depts);
        sendJson(res, 200, { message: '添加成功', depts: depts });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

function handleDeleteDept(res, name) {
    var depts = store.getDepts();
    depts = depts.filter(function(d) { return d !== name; });
    store.saveDepts(depts);
    sendJson(res, 200, { message: '删除成功', depts: depts });
}

async function handleCreateTeacher(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var id = (data.id || '').trim();
        var name = (data.name || '').trim();
        var dept = (data.dept || '').trim();
        var phone = (data.phone || '').trim();
        var password = (data.password || '').trim();
        if (!id || !name || !dept) { sendJson(res, 400, { error: '请填写完整信息' }); return; }
        if (!password) { sendJson(res, 400, { error: '请设置登录密码' }); return; }
        var teachers = store.getTeachers();
        if (teachers.find(function(t) { return t.id === id; })) { sendJson(res, 400, { error: '工号已存在' }); return; }
        var hash = await store.hashPassword(password);
        teachers.push({ id: id, name: name, dept: dept, phone: phone, passwordHash: hash, createTime: new Date().toISOString() });
        store.saveTeachers(teachers);
        var users = store.getUsers();
        users['teacher_' + id] = { username: id, passwordHash: hash, type: 'teacher', typeName: '教师', icon: '👨‍🏫', name: name, firstLogin: true };
        store.saveUsers(users);
        sendJson(res, 200, { message: '添加成功', teachers: teachers });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleUpdateTeacher(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var id = (data.id || '').trim();
        var name = (data.name || '').trim();
        var dept = (data.dept || '').trim();
        var phone = (data.phone || '').trim();
        var password = (data.password || '').trim();
        var teachers = store.getTeachers();
        var idx = teachers.findIndex(function(t) { return t.id === id; });
        if (idx < 0) { sendJson(res, 404, { error: '教师不存在' }); return; }
        teachers[idx].name = name;
        teachers[idx].dept = dept;
        teachers[idx].phone = phone;
        if (password) {
            var hash = await store.hashPassword(password);
            teachers[idx].passwordHash = hash;
            var users = store.getUsers();
            var userKey = 'teacher_' + id;
            if (users[userKey]) { users[userKey].passwordHash = hash; users[userKey].name = name; users[userKey].firstLogin = false; store.saveUsers(users); }
        } else {
            var users2 = store.getUsers();
            var userKey2 = 'teacher_' + id;
            if (users2[userKey2]) { users2[userKey2].name = name; store.saveUsers(users2); }
        }
        store.saveTeachers(teachers);
        sendJson(res, 200, { message: '更新成功', teachers: teachers });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

function handleDeleteTeacher(res, id) {
    var teachers = store.getTeachers();
    teachers = teachers.filter(function(t) { return t.id !== id; });
    store.saveTeachers(teachers);
    var users = store.getUsers();
    delete users['teacher_' + id];
    store.saveUsers(users);
    sendJson(res, 200, { message: '删除成功', teachers: teachers });
}

async function handleResetTeacherPassword(res, id) {
    var users = store.getUsers();
    var userKey = 'teacher_' + id;
    if (!users[userKey]) { sendJson(res, 404, { error: '未找到该教师账号' }); return; }
    var hash = await store.hashPassword(id);
    users[userKey].passwordHash = hash;
    users[userKey].firstLogin = true;
    store.saveUsers(users);
    var teachers = store.getTeachers();
    var idx = teachers.findIndex(function(t) { return t.id === id; });
    if (idx >= 0) { teachers[idx].passwordHash = hash; store.saveTeachers(teachers); }
    sendJson(res, 200, { message: '密码已重置为工号' });
}

async function handleUpdateTeacherContact(req, res, id) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var teachers = store.getTeachers();
        var idx = teachers.findIndex(function(t) { return t.id === id; });
        if (idx < 0) { sendJson(res, 404, { error: '教师不存在' }); return; }
        if (data.phone !== undefined) teachers[idx].phone = data.phone;
        if (data.email !== undefined) teachers[idx].email = data.email;
        store.saveTeachers(teachers);
        sendJson(res, 200, { message: '更新成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleUpdateStudentContact(req, res, id) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var students = store.getStudents();
        var idx = students.findIndex(function(s) { return s.id === id; });
        if (idx < 0) { sendJson(res, 404, { error: '学生不存在' }); return; }
        if (data.phone !== undefined) students[idx].phone = data.phone;
        if (data.email !== undefined) students[idx].email = data.email;
        store.saveStudents(students);
        sendJson(res, 200, { message: '更新成功' });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

async function handleGenerateReport(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);

        var students = store.getStudents();
        var student = students.find(function(s) { return s.id === data.studentId; }) || {};

        var reportData = {
            labId: data.labId || '',
            totalScore: data.totalScore || 0,
            baseScore: data.baseScore || 0,
            comprehensiveScore: data.comprehensiveScore || 0,
            studentId: data.studentId || '',
            studentName: student.name || data.studentName || '',
            className: student.classname || data.className || '',
            experimentDate: data.experimentDate || new Date().toLocaleDateString('zh-CN'),
            steps: data.steps || '',
            conclusion: data.conclusion || ''
        };

        var result = reportGenerator.generateReport(reportData);
        sendJson(res, 200, {
            message: '报告生成成功',
            docxFileName: result.docxFileName,
            pdfFileName: result.pdfFileName
        });
    } catch (e) {
        sendJson(res, 500, { error: e.message });
    }
}

function handleDownloadReport(req, res, pathname) {
    var fileName = pathname.replace('/api/download-report/', '');
    var filePath = path.join(__dirname, 'reports', fileName);

    if (!fs.existsSync(filePath)) {
        sendJson(res, 404, { error: '文件不存在' });
        return;
    }

    var ext = path.extname(fileName).toLowerCase();
    var contentType = ext === '.pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

    fs.readFile(filePath, function(err, data) {
        if (err) {
            sendJson(res, 500, { error: '读取文件失败' });
            return;
        }
        res.writeHead(200, {
            'Content-Type': contentType,
            'Content-Disposition': 'attachment; filename="' + encodeURIComponent(fileName) + '"',
            'Content-Length': data.length,
            'Access-Control-Allow-Origin': '*'
        });
        res.end(data);
    });
}

module.exports = { handleRoute: handleRoute };