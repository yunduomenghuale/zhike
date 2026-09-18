const https = require('https');
const fs = require('fs');

const PORT = 8443;
const HOST = 'localhost';
let pass = 0, fail = 0;
const cleanup = [];

function log(test, ok, detail) {
    const icon = ok ? '[OK]' : '[XX]';
    console.log((ok ? pass++ : fail++, icon + ' ' + test + (detail ? ' => ' + detail : '')));
    if (!ok) console.log('    !!! FAIL: ' + test);
}

function req(method, path, body, token) {
    return new Promise((resolve, reject) => {
        const data = body ? JSON.stringify(body) : null;
        const headers = {};
        if (data) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = Buffer.byteLength(data); }
        if (token) headers['Authorization'] = 'Bearer ' + token;
        const r = https.request({ hostname: HOST, port: PORT, path, method, headers, rejectUnauthorized: false, timeout: 10000 }, (res) => {
            let d = '';
            res.on('data', c => d += c);
            res.on('end', () => {
                try { resolve({ status: res.statusCode, json: d ? JSON.parse(d) : {}, raw: d }); }
                catch (e) { resolve({ status: res.statusCode, json: {}, raw: d }); }
            });
        });
        r.on('error', reject);
        r.on('timeout', () => reject(new Error('timeout')));
        if (data) r.write(data);
        r.end();
    });
}

async function run() {
    const T = 'TEST' + Date.now().toString().slice(-6);
    console.log('========================================');
    console.log('  全流程端到端模拟测试  ' + new Date().toLocaleString());
    console.log('  测试标识: ' + T);
    console.log('========================================\n');

    // ==================== 管理员流程 ====================
    console.log('--- [1] 管理员流程 ---');

    // 1.1 管理员登录
    let adminToken = null;
    try {
        const r = await req('POST', '/api/user/login', { username: 'admin', password: 'admin123' });
        log('管理员登录', r.status === 200 && r.json.token, 'token获取成功');
        adminToken = r.json.token;
    } catch (e) { log('管理员登录', false, e.message); }

    // 1.2 添加系部
    const deptName = '网络工程系_' + T;
    try {
        const r = await req('POST', '/api/depts', { name: deptName }, adminToken);
        log('添加系部', r.status === 200, deptName);
        cleanup.push({ type: 'dept', name: deptName });
    } catch (e) { log('添加系部', false, e.message); }

    // 1.3 添加专业
    const majorName = '网络工程_' + T;
    try {
        const r = await req('POST', '/api/majors', { name: majorName }, adminToken);
        log('添加专业', r.status === 200, majorName);
        cleanup.push({ type: 'major', name: majorName });
    } catch (e) { log('添加专业', false, e.message); }

    // 1.4 添加教师
    const teacherId = 'T' + T;
    const teacherPwd = 'Teacher@' + T;
    try {
        const r = await req('POST', '/api/teachers', { id: teacherId, name: '测试教师', dept: deptName, phone: '13800000000', password: teacherPwd }, adminToken);
        log('添加教师', r.status === 200, '工号=' + teacherId);
        cleanup.push({ type: 'teacher', id: teacherId });
    } catch (e) { log('添加教师', false, e.message); }

    // 1.5 验证教师firstLogin=true
    try {
        const r = await req('POST', '/api/user/login', { username: teacherId, password: teacherPwd });
        log('教师首次登录firstLogin=true', r.json.user && r.json.user.firstLogin === true, 'firstLogin=' + r.json.user.firstLogin);
    } catch (e) { log('教师首次登录', false, e.message); }

    // 1.6 查看统计概览
    try {
        const r = await req('GET', '/api/stats/overview', null, adminToken);
        log('管理员查看统计概览', r.status === 200, 'status=' + r.status);
    } catch (e) { log('管理员查看统计概览', false, e.message); }

    // 1.7 查看所有教师
    try {
        const r = await req('GET', '/api/teachers', null, adminToken);
        log('查看教师列表', r.status === 200, 'count=' + (r.json.teachers ? r.json.teachers.length : '?'));
    } catch (e) { log('查看教师列表', false, e.message); }

    // ==================== 教师流程 ====================
    console.log('\n--- [2] 教师流程 ---');

    // 2.1 教师首次登录
    let teacherToken = null;
    try {
        const r = await req('POST', '/api/user/login', { username: teacherId, password: teacherPwd });
        log('教师首次登录', r.status === 200, 'firstLogin=' + r.json.user.firstLogin);
        teacherToken = r.json.token;
    } catch (e) { log('教师首次登录', false, e.message); }

    // 2.2 教师修改密码
    const teacherNewPwd = 'NewTeacher@2026';
    try {
        const r = await req('POST', '/api/user/change-password', { username: teacherId, oldPassword: teacherPwd, newPassword: teacherNewPwd }, teacherToken);
        log('教师修改密码', r.status === 200, r.json.message);
    } catch (e) { log('教师修改密码', false, e.message); }

    // 2.3 教师重新登录
    try {
        const r = await req('POST', '/api/user/login', { username: teacherId, password: teacherNewPwd });
        log('教师重新登录(改密后)', r.status === 200 && r.json.user.firstLogin === false, 'firstLogin=' + r.json.user.firstLogin);
        teacherToken = r.json.token;
    } catch (e) { log('教师重新登录', false, e.message); }

    // 2.4 添加班级
    const className = '网络' + T.slice(-4) + '班';
    try {
        const r = await req('POST', '/api/classes', { name: className }, teacherToken);
        log('教师添加班级', r.status === 200, className);
        cleanup.push({ type: 'class', name: className });
    } catch (e) { log('教师添加班级', false, e.message); }

    // 2.5 添加学生1
    const student1Id = 'S1' + T;
    try {
        const r = await req('POST', '/api/students', { id: student1Id, name: '张三', major: majorName, classname: className }, teacherToken);
        log('教师添加学生1', r.status === 200, '学号=' + student1Id);
        cleanup.push({ type: 'student', id: student1Id });
    } catch (e) { log('教师添加学生1', false, e.message); }

    // 2.6 添加学生2
    const student2Id = 'S2' + T;
    try {
        const r = await req('POST', '/api/students', { id: student2Id, name: '李四', major: majorName, classname: className }, teacherToken);
        log('教师添加学生2', r.status === 200, '学号=' + student2Id);
        cleanup.push({ type: 'student', id: student2Id });
    } catch (e) { log('教师添加学生2', false, e.message); }

    // 2.7 获取题库章节
    let chapters = [];
    try {
        const r = await req('GET', '/api/questions/chapters', null, teacherToken);
        chapters = r.json.chapters || r.json.data || [];
        log('获取题库章节', r.status === 200, '章节数=' + chapters.length);
    } catch (e) { log('获取题库章节', false, e.message); }

    // 2.8 获取章节题目
    if (chapters.length > 0) {
        try {
            const chId = chapters[0].id || chapters[0].chapterId || 1;
            const r = await req('GET', '/api/questions/chapter/' + chId, null, teacherToken);
            log('获取章节题目', r.status === 200, 'status=' + r.status);
        } catch (e) { log('获取章节题目', false, e.message); }
    }

    // 2.9 布置作业
    let assignmentId = null;
    try {
        const chId = chapters.length > 0 ? (chapters[0].id || chapters[0].chapterId || 1) : 1;
        const r = await req('POST', '/api/assignments', {
            title: '测试作业_' + T,
            chapters: [chId],
            startTime: new Date().toISOString().slice(0, 16),
            endTime: new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 16),
            duration: 60
        }, teacherToken);
        assignmentId = r.json.assignment ? r.json.assignment.id : null;
        log('教师布置作业', r.status === 200 && assignmentId, '作业ID=' + assignmentId + ' 题数=' + (r.json.assignment ? r.json.assignment.questionCount : '?'));
        if (assignmentId) cleanup.push({ type: 'assignment', id: assignmentId });
    } catch (e) { log('教师布置作业', false, e.message); }

    // 2.10 保存实验排课
    try {
        const r = await req('POST', '/api/lab-schedules', {
            schedules: {
                'comprehensive-lab': { class: className, teacher: teacherId, time: '2026-10-01 14:00', lab: '综合实验' },
                'app-layer-lab': { class: className, teacher: teacherId, time: '2026-10-08 14:00', lab: '应用层实验' }
            }
        }, teacherToken);
        log('教师布置实验排课', r.status === 200, r.json.message || 'ok');
    } catch (e) { log('教师布置实验排课', false, e.message); }

    // ==================== 学生流程 ====================
    console.log('\n--- [3] 学生1流程 ---');

    // 3.1 学生首次登录
    let studentToken = null;
    try {
        const r = await req('POST', '/api/user/login', { username: student1Id, password: student1Id });
        log('学生首次登录', r.status === 200 && r.json.user.firstLogin === true, 'firstLogin=' + r.json.user.firstLogin);
        studentToken = r.json.token;
    } catch (e) { log('学生首次登录', false, e.message); }

    // 3.2 学生修改密码
    const studentNewPwd = 'Student@2026';
    try {
        const r = await req('POST', '/api/user/change-password', { username: student1Id, oldPassword: student1Id, newPassword: studentNewPwd }, studentToken);
        log('学生修改密码', r.status === 200, r.json.message);
    } catch (e) { log('学生修改密码', false, e.message); }

    // 3.3 学生重新登录
    try {
        const r = await req('POST', '/api/user/login', { username: student1Id, password: studentNewPwd });
        log('学生重新登录(改密后)', r.status === 200 && r.json.user.firstLogin === false, 'firstLogin=' + r.json.user.firstLogin);
        studentToken = r.json.token;
    } catch (e) { log('学生重新登录', false, e.message); }

    // 3.4 获取作业列表
    let assignments = [];
    try {
        const r = await req('GET', '/api/assignments', null, studentToken);
        assignments = r.json.assignments || r.json.data || [];
        log('学生获取作业列表', r.status === 200, '作业数=' + assignments.length);
    } catch (e) { log('学生获取作业列表', false, e.message); }

    // 3.5 获取作业题目并提交
    if (assignmentId) {
        try {
            const r = await req('GET', '/api/quiz/questions/' + assignmentId, null, studentToken);
            const questions = r.json.questions || r.json.data || [];
            log('学生获取作业题目', r.status === 200, '题目数=' + questions.length);

            // 构造答案提交
            if (questions.length > 0) {
                const answers = {};
                questions.forEach(function(q, i) {
                    const qid = q.id;
                    if (q.type === 'choice') {
                        answers[qid] = 0;
                    } else if (q.type === 'judge') {
                        answers[qid] = true;
                    } else {
                        answers[qid] = '测试答案内容';
                    }
                });

                const sr = await req('POST', '/api/quiz/submit', {
                    assignmentId: assignmentId,
                    studentId: student1Id,
                    answers: answers
                }, studentToken);
                log('学生提交作业', sr.status === 200, sr.json.message || sr.json.score != null ? '得分=' + (sr.json.score || 0) : 'ok');
            }
        } catch (e) { log('学生获取/提交作业', false, e.message); }
    }

    // 3.6 保存实验报告
    try {
        const r = await req('POST', '/api/lab-reports', {
            studentId: student1Id,
            labId: 'comprehensive-lab',
            labName: '综合实验：网络配置与VLAN',
            steps: [
                { step: 1, description: '设备连接', result: '成功', time: '5min' },
                { step: 2, description: 'VLAN配置', result: '成功', time: '10min' },
                { step: 3, description: '路由配置', result: '成功', time: '15min' }
            ],
            score: 90,
            submitTime: new Date().toISOString()
        }, studentToken);
        log('学生提交实验报告', r.status === 200, r.json.message || 'ok');
    } catch (e) { log('学生提交实验报告', false, e.message); }

    // 3.7 上报学习时长和详情（专题学习）
    try {
        const r = await req('POST', '/api/study/detail', {
            studentId: student1Id,
            detail: {
                'network-classification': 15.5,
                'transport-layer': 20.3,
                'index': 5.2
            }
        }, studentToken);
        log('学生上报学习详情(专题学习)', r.status === 200, r.json.message || 'ok');
    } catch (e) { log('学生上报学习详情', false, e.message); }

    try {
        const r = await req('POST', '/api/study/time', {
            studentId: student1Id,
            time: 41.0
        }, studentToken);
        log('学生上报学习总时长', r.status === 200, r.json.message || 'ok');
    } catch (e) { log('学生上报学习总时长', false, e.message); }

    // 3.8 上报学习次数
    try {
        const r = await req('POST', '/api/learn-counts', {
            page: 'index',
            studentId: student1Id
        }, studentToken);
        log('学生上报学习次数', r.status === 200, r.json.message || 'ok');
    } catch (e) { log('学生上报学习次数', false, e.message); }

    // 3.9 使用网络学习小伴侣（获取知识库）
    try {
        const r = await req('GET', '/api/knowledge', null, studentToken);
        const cats = r.json.categories || r.json.data || r.json;
        const catCount = Array.isArray(cats) ? cats.length : Object.keys(cats).length;
        log('学生使用网络学习小伴侣(知识库)', r.status === 200, '分类数=' + catCount);
    } catch (e) { log('学生使用网络学习小伴侣', false, e.message); }

    // 3.10 查看自己的提交记录
    try {
        const r = await req('GET', '/api/quiz/my-submissions?studentId=' + student1Id, null, studentToken);
        log('学生查看我的提交记录', r.status === 200, 'status=' + r.status);
    } catch (e) { log('学生查看我的提交记录', false, e.message); }

    // ==================== 学生2流程（简化） ====================
    console.log('\n--- [4] 学生2流程 ---');
    let student2Token = null;
    try {
        const r = await req('POST', '/api/user/login', { username: student2Id, password: student2Id });
        log('学生2首次登录', r.status === 200, 'firstLogin=' + r.json.user.firstLogin);
        student2Token = r.json.token;
    } catch (e) { log('学生2首次登录', false, e.message); }

    try {
        const r = await req('POST', '/api/user/change-password', { username: student2Id, oldPassword: student2Id, newPassword: 'Student@2026' }, student2Token);
        log('学生2修改密码', r.status === 200, r.json.message);
    } catch (e) { log('学生2修改密码', false, e.message); }

    try {
        const r = await req('POST', '/api/user/login', { username: student2Id, password: 'Student@2026' });
        log('学生2重新登录', r.status === 200, 'firstLogin=' + r.json.user.firstLogin);
        student2Token = r.json.token;
    } catch (e) { log('学生2重新登录', false, e.message); }

    // 学生2也做作业
    if (assignmentId) {
        try {
            const r = await req('GET', '/api/quiz/questions/' + assignmentId, null, student2Token);
            const questions = r.json.questions || r.json.data || [];
            if (questions.length > 0) {
                const answers = {};
                questions.forEach(function(q, i) {
                    const qid = q.id;
                    if (q.type === 'choice') {
                        answers[qid] = 1;
                    } else if (q.type === 'judge') {
                        answers[qid] = false;
                    } else {
                        answers[qid] = '学生2的测试答案';
                    }
                });
                const sr = await req('POST', '/api/quiz/submit', { assignmentId: assignmentId, studentId: student2Id, answers: answers }, student2Token);
                log('学生2提交作业', sr.status === 200, sr.json.message || 'ok');
            } else {
                log('学生2提交作业', true, '无题目跳过');
            }
        } catch (e) { log('学生2提交作业', false, e.message); }
    }

    // 学生2上报学习
    try {
        await req('POST', '/api/study/detail', { studentId: student2Id, detail: { 'network-classification': 10.0, 'index': 3.0 } }, student2Token);
        await req('POST', '/api/study/time', { studentId: student2Id, time: 13.0 }, student2Token);
        log('学生2上报学习记录', true, 'ok');
    } catch (e) { log('学生2上报学习记录', false, e.message); }

    // ==================== 教师查询学习情况 ====================
    console.log('\n--- [5] 教师查询学习情况 ---');

    // 5.1 查看所有学生学习详情
    try {
        const r = await req('GET', '/api/study/all-details', null, teacherToken);
        log('教师查看所有学生学习详情', r.status === 200, 'status=' + r.status);
    } catch (e) { log('教师查看所有学生学习详情', false, e.message); }

    // 5.2 查看所有学生学习时长
    try {
        const r = await req('GET', '/api/study/all-times', null, teacherToken);
        log('教师查看所有学生学习时长', r.status === 200, 'status=' + r.status);
    } catch (e) { log('教师查看所有学生学习时长', false, e.message); }

    // 5.3 查看所有作业结果
    try {
        const r = await req('GET', '/api/quiz/all-results', null, teacherToken);
        log('教师查看所有作业结果', r.status === 200, 'status=' + r.status);
    } catch (e) { log('教师查看所有作业结果', false, e.message); }

    // 5.4 查看所有实验报告
    try {
        const r = await req('GET', '/api/lab-reports/all', null, teacherToken);
        log('教师查看所有实验报告', r.status === 200, 'status=' + r.status);
    } catch (e) { log('教师查看所有实验报告', false, e.message); }

    // 5.5 查看指定学生学习详情
    try {
        const r = await req('GET', '/api/study/detail?studentId=' + student1Id, null, teacherToken);
        log('教师查看指定学生学习详情', r.status === 200, 'status=' + r.status);
    } catch (e) { log('教师查看指定学生学习详情', false, e.message); }

    // 5.6 查看指定学生实验报告
    try {
        const r = await req('GET', '/api/lab-reports?studentId=' + student1Id, null, teacherToken);
        log('教师查看指定学生实验报告', r.status === 200, 'status=' + r.status);
    } catch (e) { log('教师查看指定学生实验报告', false, e.message); }

    // 5.7 查看学生列表
    try {
        const r = await req('GET', '/api/students', null, teacherToken);
        log('教师查看学生列表', r.status === 200, 'count=' + (r.json.students ? r.json.students.length : '?'));
    } catch (e) { log('教师查看学生列表', false, e.message); }

    // 5.8 查看班级列表
    try {
        const r = await req('GET', '/api/classes', null, teacherToken);
        log('教师查看班级列表', r.status === 200, 'count=' + (r.json.classes ? r.json.classes.length : '?'));
    } catch (e) { log('教师查看班级列表', false, e.message); }

    // 5.9 教师复核作业
    if (assignmentId) {
        try {
            const r = await req('GET', '/api/quiz/all-results', null, teacherToken);
            const results = r.json.results || r.json.data || [];
            if (results.length > 0) {
                const reviewTarget = results[0];
                const rr = await req('POST', '/api/quiz/review', {
                    submissionId: reviewTarget.id || reviewTarget.submissionId,
                    studentId: reviewTarget.studentId || student1Id,
                    assignmentId: assignmentId,
                    review: '已复核',
                    adjustScore: 0,
                    comment: '测试复核评论'
                }, teacherToken);
                log('教师复核作业', rr.status === 200, rr.json.message || 'ok');
            } else {
                log('教师复核作业', true, '无提交记录跳过');
            }
        } catch (e) { log('教师复核作业', false, e.message); }
    }

    // ==================== 管理员查看全局 ====================
    console.log('\n--- [6] 管理员查看全局 ---');

    try {
        const r = await req('GET', '/api/stats/overview', null, adminToken);
        log('管理员查看全局统计', r.status === 200, 'status=' + r.status);
    } catch (e) { log('管理员查看全局统计', false, e.message); }

    try {
        const r = await req('GET', '/api/study/all-details', null, adminToken);
        log('管理员查看全局学习详情', r.status === 200, 'status=' + r.status);
    } catch (e) { log('管理员查看全局学习详情', false, e.message); }

    // ==================== 清理测试数据 ====================
    console.log('\n--- [7] 清理测试数据 ---');

    for (const item of cleanup) {
        try {
            let r;
            if (item.type === 'student') r = await req('DELETE', '/api/students/' + item.id, null, teacherToken);
            else if (item.type === 'teacher') r = await req('DELETE', '/api/teachers/' + item.id, null, adminToken);
            else if (item.type === 'class') r = await req('DELETE', '/api/classes/' + encodeURIComponent(item.name), null, teacherToken);
            else if (item.type === 'major') r = await req('DELETE', '/api/majors/' + encodeURIComponent(item.name), null, adminToken);
            else if (item.type === 'dept') r = await req('DELETE', '/api/depts/' + encodeURIComponent(item.name), null, adminToken);
            else if (item.type === 'assignment') r = await req('DELETE', '/api/assignments/' + item.id, null, teacherToken);
            log('清理 ' + item.type + ': ' + (item.id || item.name), r && r.status === 200, 'status=' + (r ? r.status : '?'));
        } catch (e) { log('清理 ' + item.type + ': ' + (item.id || item.name), false, e.message); }
    }

    // ==================== 汇总 ====================
    console.log('\n========================================');
    console.log('  全流程模拟结果');
    console.log('========================================');
    console.log('  通过: ' + pass);
    console.log('  失败: ' + fail);
    console.log('  总计: ' + (pass + fail));
    console.log('  结果: ' + (fail === 0 ? 'ALL PASS ✅' : 'HAS FAILURES ❌'));
    console.log('========================================');

    process.exit(fail > 0 ? 1 : 0);
}

run().catch(e => { console.error('Fatal:', e); process.exit(1); });