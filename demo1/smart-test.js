/**
 * 智能全覆盖测试程序 - 计算机网络课程辅助教学平台
 * 模拟完整业务流程：管理员→教师→学生全链路
 */
const http = require('http');
const HOST = '127.0.0.1';
const PORT = 8081;

const TOPIC_PAGES = [
    { id: 'network-classification', name: '网络分类' },
    { id: 'network-switching-demo', name: '交换方式' },
    { id: 'network-data-animation', name: '数据动画' },
    { id: 'network-delay-demo', name: '网络延迟' },
    { id: 'transmission-media-comparison', name: '传输介质' },
    { id: 'digital-signal-encoding', name: '信号编码' },
    { id: 'channel-multiplexing', name: '信道复用' },
    { id: 'csma-cd-protocol', name: 'CSMA/CD' },
    { id: 'sliding-window', name: '滑动窗口' },
    { id: 'network-device-comparison', name: '网络设备' },
    { id: 'tcp-demo', name: 'TCP演示' },
    { id: 'Mind-Map', name: '思维导图' },
];

const LAB_PAGES = [
    { id: 'switch-vlan-stp-lab', name: 'VLAN/STP实验' },
    { id: 'arp-ip-lab', name: 'ARP/IP实验' },
    { id: 'routing-ospf-lab', name: '路由OSPF实验' },
    { id: 'vlan-nat-lab', name: 'VLAN/NAT实验' },
    { id: 'tcp-udp-lab', name: 'TCP/UDP实验' },
    { id: 'app-layer-lab', name: '应用层实验' },
    { id: 'comprehensive-lab', name: '综合实验' },
];

var passCount = 0;
var failCount = 0;
var stepCount = 0;

function log(icon, msg) {
    console.log('  ' + icon + ' ' + msg);
}

function step(name) {
    stepCount++;
    console.log('\n[' + stepCount + '] ' + name);
    console.log('  ' + '='.repeat(50));
}

function check(cond, msg) {
    if (cond) { passCount++; log('✓', msg); }
    else { failCount++; log('✗', msg); }
    return cond;
}

function request(method, path, body, token) {
    return new Promise(function(resolve, reject) {
        var data = body ? JSON.stringify(body) : null;
        var headers = { 'Content-Type': 'application/json' };
        if (data) headers['Content-Length'] = Buffer.byteLength(data);
        if (token) headers['Authorization'] = 'Bearer ' + token;

        var opts = { hostname: HOST, port: PORT, path: path, method: method, headers: headers };
        var req = http.request(opts, function(res) {
            var chunks = '';
            res.on('data', function(c) { chunks += c; });
            res.on('end', function() {
                var json = null;
                try { json = JSON.parse(chunks); } catch (e) {}
                resolve({ status: res.statusCode, data: json, raw: chunks });
            });
        });
        req.on('error', reject);
        req.setTimeout(10000, function() { req.destroy(); reject(new Error('TIMEOUT')); });
        if (data) req.write(data);
        req.end();
    });
}

async function login(username, password) {
    var r = await request('POST', '/api/user/login', { username: username, password: password });
    if (r.status === 200 && r.data && r.data.token) return r.data;
    throw new Error('登录失败: ' + username + ' -> ' + r.status + ' ' + (r.data && r.data.error || r.raw));
}

async function run() {
    var ts = Date.now();
    var teacherId = 'T' + ts;
    var teacherName = '测试教师_' + ts;
    var teacherPwd = 'test123';
    var classId = '测试班_' + ts;
    var students = [];
    for (var i = 1; i <= 3; i++) {
        students.push({
            id: 'S' + ts + '_' + i,
            name: '测试学生' + i,
            major: '计算机科学与技术',
            classname: classId
        });
    }

    console.log('╔══════════════════════════════════════════════════════════╗');
    console.log('║  智能全覆盖测试 - 计算机网络课程辅助教学平台            ║');
    console.log('║  流程: 管理员→创建教师→教师登录→班级→学生→作业→实验  ║');
    console.log('╚══════════════════════════════════════════════════════════╝');

    // ========== 1. 管理员登录 ==========
    step('管理员登录');
    var admin = await login('admin', 'admin123');
    check(admin.token, '管理员Token获取成功');
    check(admin.user.type === 'admin', '用户类型: admin');
    log('i', '管理员: ' + admin.user.name);

    // ========== 2. 创建教师账号 ==========
    step('创建教师账号');
    var r = await request('POST', '/api/teachers', {
        id: teacherId, name: teacherName, dept: '计算机系', phone: '13800001234', password: teacherPwd
    }, admin.token);
    check(r.status === 200, '教师创建成功: ' + teacherName);
    if (r.status !== 200) log('!', '错误: ' + r.raw);

    // ========== 3. 教师登录 ==========
    step('教师登录');
    var teacher = await login(teacherId, teacherPwd);
    check(teacher.token, '教师Token获取成功');
    check(teacher.user.type === 'teacher', '用户类型: teacher');
    log('i', '教师: ' + teacher.user.name);

    // ========== 4. 创建班级 ==========
    step('创建班级');
    r = await request('POST', '/api/classes', { name: classId }, teacher.token);
    check(r.status === 200, '班级创建成功: ' + classId);

    // ========== 5. 添加学生 ==========
    step('添加学生 (' + students.length + '名)');
    for (var s of students) {
        r = await request('POST', '/api/students', {
            id: s.id, name: s.name, major: s.major, classname: s.classname
        }, teacher.token);
        check(r.status === 200, '学生添加成功: ' + s.name + ' (' + s.id + ')');
    }

    // ========== 6. 查看题库章节 ==========
    step('查看题库章节');
    r = await request('GET', '/api/questions/chapters', null, teacher.token);
    check(r.status === 200, '获取章节列表成功');
    var chapters = r.data && r.data.chapters || [];
    check(chapters.length >= 6, '共' + chapters.length + '个章节');
    chapters.forEach(function(ch) {
        log('i', '  ' + ch.id + ' | ' + ch.name + ' | ' + ch.questionCount + '题');
    });

    // ========== 7. 布置作业（按章节） ==========
    step('布置作业（选择第1章+第4章）');
    var ch1 = chapters.find(function(c) { return c.id === 'ch1'; });
    var ch4 = chapters.find(function(c) { return c.id === 'ch4'; });
    r = await request('POST', '/api/assignments', {
        title: '测试作业_' + ts,
        chapters: ['ch1', 'ch4'],
        startTime: new Date().toISOString(),
        endTime: new Date(Date.now() + 7 * 86400000).toISOString(),
        duration: 60
    }, teacher.token);
    check(r.status === 200, '作业布置成功');
    var assignment = r.data && r.data.assignment;
    if (assignment) {
        log('i', '作业ID: ' + assignment.id + ' | 题目数: ' + assignment.questionCount);
    }

    // ========== 8. 设置实验开放时间 ==========
    step('设置实验开放时间');
    var schedules = {};
    LAB_PAGES.forEach(function(lab, i) {
        schedules[lab.id] = {
            open: true,
            startTime: new Date().toISOString(),
            endTime: new Date(Date.now() + 30 * 86400000).toISOString()
        };
    });
    r = await request('POST', '/api/lab-schedules', { schedules: schedules }, teacher.token);
    check(r.status === 200, '实验开放时间设置成功 (' + LAB_PAGES.length + '个实验)');

    // ========== 9. 学生登录并完成所有学习 ==========
    for (var si = 0; si < students.length; si++) {
        var stu = students[si];
        step('学生' + (si + 1) + '登录: ' + stu.name);

        var student = await login(stu.id, stu.id);
        check(student.token, '学生Token获取成功');
        check(student.user.type === 'student', '用户类型: student');

        // ----- 10. 完成所有专题学习 -----
        step(stu.name + ' - 完成专题学习 (' + TOPIC_PAGES.length + '个模块)');
        var studyDetail = {};
        var totalTime = 0;
        for (var pi = 0; pi < TOPIC_PAGES.length; pi++) {
            var page = TOPIC_PAGES[pi];
            var time = Math.floor(Math.random() * 20) + 10;
            studyDetail[page.id] = time;
            totalTime += time;
        }
        studyDetail['index'] = Math.floor(Math.random() * 30) + 20;
        totalTime += studyDetail['index'];

        r = await request('POST', '/api/study/detail', {
            studentId: stu.id, detail: studyDetail
        }, student.token);
        check(r.status === 200, '学习记录保存成功');

        r = await request('POST', '/api/study/time', {
            studentId: stu.id, time: totalTime
        }, student.token);
        check(r.status === 200, '学习时长保存: ' + totalTime + '分钟');

        r = await request('POST', '/api/study/login-count', {
            studentId: stu.id, count: Math.floor(Math.random() * 10) + 5
        }, student.token);
        check(r.status === 200, '登录次数保存成功');

        log('i', '专题学习: ' + TOPIC_PAGES.length + '模块, 总时长' + totalTime + '分钟');

        // ----- 11. 完成所有实验 -----
        step(stu.name + ' - 完成虚拟仿真实验 (' + LAB_PAGES.length + '个)');
        var labReports = [];
        for (var li = 0; li < LAB_PAGES.length; li++) {
            var lab = LAB_PAGES[li];
            var score = Math.floor(Math.random() * 30) + 70;
            labReports.push({
                labId: lab.id,
                labName: lab.name,
                score: score,
                submitTime: new Date().toISOString(),
                content: '实验报告: ' + lab.name + ' - 完成所有步骤，结果正确'
            });
        }
        r = await request('POST', '/api/lab-reports', {
            studentId: stu.id,
            replace: true,
            reports: labReports
        }, student.token);
        check(r.status === 200, '实验报告提交成功');
        log('i', '实验完成: ' + labReports.length + '个, 平均分' +
            Math.round(labReports.reduce(function(a, b) { return a + b.score; }, 0) / labReports.length));

        // ----- 12. 获取作业题目 -----
        if (assignment) {
            step(stu.name + ' - 获取作业题目');
            r = await request('GET', '/api/quiz/questions/' + assignment.id, null, student.token);
            check(r.status === 200, '获取作业题目成功');
            var questions = r.data && r.data.questions || [];
            check(questions.length > 0, '共' + questions.length + '道题');

            // ----- 13. 答题并提交 -----
            step(stu.name + ' - 答题并提交作业');
            var answers = {};
            var correctCount = 0;
            questions.forEach(function(q) {
                if (q.type === 'choice') {
                    var ans = Math.floor(Math.random() * 4);
                    answers[q.id] = ans;
                    if (ans === q.answer) correctCount++;
                } else if (q.type === 'judge') {
                    var ans = Math.random() > 0.5;
                    answers[q.id] = ans;
                    if (ans === q.answer) correctCount++;
                } else if (q.type === 'fill') {
                    answers[q.id] = String(q.answer).split(/[，,、\/\s]/)[0] || '测试答案';
                } else if (q.type === 'short') {
                    answers[q.id] = '这是测试答案，包含部分关键词：' + String(q.answer || '').substring(0, 20);
                }
            });

            r = await request('POST', '/api/quiz/submit', {
                assignmentId: assignment.id,
                studentId: stu.id,
                answers: answers
            }, student.token);
            check(r.status === 200, '作业提交成功');
            if (r.status === 200 && r.data) {
                log('i', '得分: ' + r.data.score + '分 | 正确: ' + r.data.correctCount + '/' + r.data.totalQuestions);
            }
            if (r.status !== 200) log('!', '提交失败: ' + r.raw);

            // ----- 14. 查看作业结果 -----
            step(stu.name + ' - 查看作业结果');
            r = await request('GET', '/api/quiz/result/' + assignment.id + '?studentId=' + stu.id, null, student.token);
            check(r.status === 200, '获取作业结果成功');
            if (r.data && r.data.submission) {
                log('i', '最终得分: ' + r.data.submission.score + '分');
            }

            // ----- 15. 查看我的所有提交 -----
            r = await request('GET', '/api/quiz/my-submissions?studentId=' + stu.id, null, student.token);
            check(r.status === 200, '获取我的提交列表成功');
        }
    }

    // ========== 16. 教师查看所有成绩 ==========
    step('教师查看所有成绩');
    r = await request('GET', '/api/quiz/all-results', null, teacher.token);
    check(r.status === 200, '获取所有成绩成功');
    if (r.data && r.data.results) {
        r.data.results.forEach(function(res) {
            if (res.submissionCount > 0) {
                log('i', '作业: ' + res.assignment.title + ' | 提交数: ' + res.submissionCount);
                res.submissions.forEach(function(sub) {
                    log('i', '  学生' + sub.studentId + ': ' + sub.score + '分');
                });
            }
        });
    }

    // ========== 17. 教师复核主观题 ==========
    step('教师复核主观题');
    if (assignment) {
        for (var stu2 of students) {
            r = await request('GET', '/api/quiz/review/' + assignment.id + '?studentId=' + stu2.id, null, teacher.token);
            if (r.status === 200 && r.data && r.data.submission) {
                var sub = r.data.submission;
                var reviewQuestions = sub.results.filter(function(res) {
                    return res.pendingReview || (res.similarity !== null && res.partialScore < 1 && !res.reviewed);
                });
                if (reviewQuestions.length > 0) {
                    var reviews = reviewQuestions.map(function(res) {
                        return {
                            questionId: res.questionId,
                            partialScore: res.partialScore >= 0.8 ? 1 : (res.partialScore >= 0.5 ? 0.7 : 0.3),
                            comment: '教师复核: 答案基本正确'
                        };
                    });
                    r = await request('POST', '/api/quiz/review', {
                        assignmentId: assignment.id,
                        studentId: stu2.id,
                        reviews: reviews
                    }, teacher.token);
                    check(r.status === 200, stu2.name + ' 复核成功' + (r.data ? ' -> ' + r.data.score + '分' : ''));
                } else {
                    log('i', stu2.name + ' 无需复核的主观题');
                }
            }
        }
    }

    // ========== 18. 教师查看学习统计 ==========
    step('教师查看学习统计');
    r = await request('GET', '/api/study/all-details', null, teacher.token);
    check(r.status === 200, '获取所有学习详情成功');

    r = await request('GET', '/api/study/all-times', null, teacher.token);
    check(r.status === 200, '获取所有学习时长成功');
    if (r.data && r.data.times) {
        Object.keys(r.data.times).forEach(function(sid) {
            if (sid.startsWith('S' + ts)) {
                log('i', sid + ': ' + r.data.times[sid] + '分钟');
            }
        });
    }

    r = await request('GET', '/api/lab-reports/all', null, teacher.token);
    check(r.status === 200, '获取所有实验报告成功');

    // ========== 19. 管理员查看统计总览 ==========
    step('管理员查看统计总览');
    r = await request('GET', '/api/stats/overview', null, admin.token);
    check(r.status === 200, '获取统计总览成功');
    if (r.data) {
        log('i', '班级总数: ' + r.data.classCount);
        log('i', '学生总数: ' + r.data.studentCount);
        log('i', '总学习时长: ' + r.data.totalStudyTime + '分钟');
    }

    // ========== 20. 验证学生信息 ==========
    step('验证学生信息');
    r = await request('GET', '/api/students', null, teacher.token);
    check(r.status === 200, '获取学生列表成功');
    if (r.data && r.data.students) {
        var newStudents = r.data.students.filter(function(s) {
            return s.id.startsWith('S' + ts);
        });
        check(newStudents.length === students.length, '新增学生' + newStudents.length + '名');
    }

    // ========== 21. 验证教师列表 ==========
    step('验证教师列表');
    r = await request('GET', '/api/teachers', null, admin.token);
    check(r.status === 200, '获取教师列表成功');
    if (r.data && r.data.teachers) {
        var newTeacher = r.data.teachers.find(function(t) { return t.id === teacherId; });
        check(!!newTeacher, '新教师存在: ' + teacherName);
    }

    // ========== 清理测试数据 ==========
    step('清理测试数据');
    for (var stu3 of students) {
        r = await request('DELETE', '/api/students/' + stu3.id, null, teacher.token);
        check(r.status === 200, '删除学生: ' + stu3.name);
    }
    r = await request('DELETE', '/api/classes/' + encodeURIComponent(classId), null, teacher.token);
    check(r.status === 200, '删除班级: ' + classId);

    r = await request('DELETE', '/api/teachers/' + teacherId, null, admin.token);
    check(r.status === 200, '删除教师: ' + teacherName);

    if (assignment) {
        r = await request('DELETE', '/api/assignments/' + assignment.id, null, teacher.token);
        check(r.status === 200, '删除作业: ' + assignment.title);
    }

    // ========== 结果汇总 ==========
    console.log('\n');
    console.log('╔══════════════════════════════════════════════════════════╗');
    console.log('║  测试完成 - 结果汇总                                    ║');
    console.log('╠══════════════════════════════════════════════════════════╣');
    var passLine = '║  通过: ' + passCount + '  失败: ' + failCount + '  总计: ' + (passCount + failCount);
    while (passLine.length < 59) passLine += ' ';
    passLine += '║';
    console.log(passLine);
    var rateLine = '║  通过率: ' + Math.round(passCount / (passCount + failCount) * 100) + '%';
    while (rateLine.length < 59) rateLine += ' ';
    rateLine += '║';
    console.log(rateLine);
    console.log('╚══════════════════════════════════════════════════════════╝');

    if (failCount > 0) {
        console.log('\n⚠ 有 ' + failCount + ' 个测试失败！');
        process.exit(1);
    } else {
        console.log('\n✓ 全部测试通过！');
        process.exit(0);
    }
}

run().catch(function(err) {
    console.error('\n✗ 测试程序异常: ' + err.message);
    console.error(err.stack);
    process.exit(2);
});