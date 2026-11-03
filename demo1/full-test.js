const http = require('http');
const fs = require('fs');
const path = require('path');

const HOST = '127.0.0.1';
const FRONT_PORT = 3000;
const API_PORT = 8081;

let passed = 0;
let failed = 0;
const failures = [];

function log(ok, name, detail) {
    const tag = ok ? 'PASS' : 'FAIL';
    console.log(`[${tag}] ${name}${detail ? ' — ' + detail : ''}`);
    if (ok) passed++;
    else { failed++; failures.push(name + (detail ? ' — ' + detail : '')); }
}

function httpReq(port, urlPath, opts = {}) {
    return new Promise((resolve) => {
        const req = http.request({
            host: HOST,
            port: port,
            path: urlPath,
            method: opts.method || 'GET',
            headers: opts.headers || {},
            timeout: 5000
        }, (res) => {
            let body = '';
            res.on('data', (chunk) => body += chunk);
            res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
        });
        req.on('error', (e) => resolve({ error: e.message }));
        req.on('timeout', () => { req.destroy(); resolve({ error: 'timeout' }); });
        if (opts.body) req.write(opts.body);
        req.end();
    });
}

async function runTests() {
    console.log('========================================');
    console.log('  网络学习小伴侣 — 全面功能测试');
    console.log('========================================\n');

    // === 1. 服务进程状态 ===
    console.log('--- 1. 服务进程状态 ---');
    try {
        const tasks = require('child_process').execSync('tasklist /FI "IMAGENAME eq node.exe" /FO CSV', { encoding: 'utf8' });
        const nodeCount = (tasks.match(/node\.exe/gi) || []).length;
        log(nodeCount >= 2, 'Node进程数量', `检测到 ${nodeCount} 个 node.exe 进程`);
    } catch (e) {
        log(false, 'Node进程检测', e.message);
    }

    // === 2. 前端页面访问 (3000端口) ===
    console.log('\n--- 2. 前端页面访问 (port 3000) ---');

    const pages = [
        { path: '/', name: '首页', expectStatus: 200, expectContains: '<html' },
        { path: '/index.html', name: '首页(直接)', expectStatus: 200, expectContains: '<html' },
        { path: '/login.html', name: '登录页', expectStatus: 200, expectContains: '登录' },
        { path: '/teacher.html', name: '教师控制台', expectStatus: 200, expectContains: '<html' },
        { path: '/quiz.html', name: '测验页', expectStatus: 200, expectContains: '<html' },
        { path: '/user-center.html', name: '用户中心', expectStatus: 200, expectContains: '<html' },
        { path: '/force-change-password.html', name: '强制改密页', expectStatus: 200, expectContains: '<html' },
        { path: '/labs/lab-guide.html', name: '实验指南页', expectStatus: 200, expectContains: '<html' },
        { path: '/labs/tcp-udp-lab.html', name: 'TCP/UDP实验', expectStatus: 200, expectContains: '<html' },
        { path: '/mindmap/index.html', name: '思维导图首页', expectStatus: 200, expectContains: '<html' },
        { path: '/auth-check.js', name: 'auth-check.js', expectStatus: 200, expectContains: 'function' },
        { path: '/api-client.js', name: 'api-client.js', expectStatus: 200, expectContains: 'function' },
        { path: '/utils.js', name: 'utils.js', expectStatus: 200, expectContains: 'function' },
        { path: '/config.js', name: 'config.js', expectStatus: 200 },
        { path: '/404.html', name: '404页面', expectStatus: 200, expectContains: '404' },
    ];

    for (const p of pages) {
        const res = await httpReq(FRONT_PORT, p.path);
        if (res.error) {
            log(false, p.name, '连接错误: ' + res.error);
        } else if (res.status !== p.expectStatus) {
            log(false, p.name, `状态码 ${res.status} (期望 ${p.expectStatus})`);
        } else if (p.expectContains && !res.body.toLowerCase().includes(p.expectContains.toLowerCase())) {
            log(false, p.name, `内容不含 "${p.expectContains}"`);
        } else {
            log(true, p.name, `状态码 ${res.status}`);
        }
    }

    // === 3. 404验证 ===
    console.log('\n--- 3. 404验证 ---');
    const res404 = await httpReq(FRONT_PORT, '/nonexistent-page.html');
    log(res404.status === 404, '不存在页面返回404', `状态码 ${res404.status}`);

    const resAdmin = await httpReq(FRONT_PORT, '/admin.html');
    log(resAdmin.status === 404, 'admin.html已不存在(404)', `状态码 ${resAdmin.status}`);

    // === 4. API端点测试 (直接8081端口) ===
    console.log('\n--- 4. API端点测试 (port 8081) ---');

    // 4.1 班级列表
    const resClasses = await httpReq(API_PORT, '/api/classes');
    log(resClasses.status === 200, 'API班级列表', `状态码 ${resClasses.status}`);

    // 4.2 学生列表
    const resStudents = await httpReq(API_PORT, '/api/students');
    log(resStudents.status === 200, 'API学生列表', `状态码 ${resStudents.status}`);

    // 4.3 题目章节
    const resChapters = await httpReq(API_PORT, '/api/questions/chapters');
    log(resChapters.status === 200, 'API题目章节', `状态码 ${resChapters.status}`);

    // 4.4 系部列表
    const resDepts = await httpReq(API_PORT, '/api/depts');
    log(resDepts.status === 200, 'API系部列表', `状态码 ${resDepts.status}`);

    // 4.5 专业列表
    const resMajors = await httpReq(API_PORT, '/api/majors');
    log(resMajors.status === 200, 'API专业列表', `状态码 ${resMajors.status}`);

    // 4.6 教师列表
    const resTeachers = await httpReq(API_PORT, '/api/teachers');
    log(resTeachers.status === 200, 'API教师列表', `状态码 ${resTeachers.status}`);

    // === 5. API反代测试 (3000 -> 8081) ===
    console.log('\n--- 5. API反代测试 (3000 -> 8081) ---');

    const resProxyClasses = await httpReq(FRONT_PORT, '/api/classes');
    log(resProxyClasses.status === 200, '反代班级列表', `状态码 ${resProxyClasses.status}`);

    const resProxyStudents = await httpReq(FRONT_PORT, '/api/students');
    log(resProxyStudents.status === 200, '反代学生列表', `状态码 ${resProxyStudents.status}`);

    const resProxyChapters = await httpReq(FRONT_PORT, '/api/questions/chapters');
    log(resProxyChapters.status === 200, '反代题目章节', `状态码 ${resProxyChapters.status}`);

    // === 6. Admin登录流程测试 ===
    console.log('\n--- 6. Admin登录流程测试 ---');

    // 6.1 admin登录API
    const loginBody = JSON.stringify({ username: 'admin', password: 'admin123' });
    const resLogin = await httpReq(API_PORT, '/api/user/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(loginBody) },
        body: loginBody
    });

    let adminToken = null;
    if (resLogin.error) {
        log(false, 'Admin登录API', '连接错误: ' + resLogin.error);
    } else if (resLogin.status !== 200) {
        log(false, 'Admin登录API', `状态码 ${resLogin.status}, body: ${resLogin.body.substring(0, 200)}`);
    } else {
        try {
            const loginData = JSON.parse(resLogin.body);
            if (loginData.token && loginData.user && loginData.user.type === 'admin') {
                log(true, 'Admin登录API', `登录成功, user.type=${loginData.user.type}`);
                adminToken = loginData.token;
            } else {
                log(false, 'Admin登录API', `返回: ${resLogin.body.substring(0, 200)}`);
            }
        } catch (e) {
            log(false, 'Admin登录API', 'JSON解析失败: ' + e.message);
        }
    }

    // 6.2 验证login.html中admin跳转到teacher.html
    const loginHtml = fs.readFileSync(path.join(__dirname, 'login.html'), 'utf8');
    const hasAdminTeacherRedirect = loginHtml.includes("user.type === 'admin'") &&
                                     loginHtml.includes("window.location.href = 'teacher.html'");
    log(hasAdminTeacherRedirect, 'login.html admin跳转teacher.html', '源码检查');

    // 6.3 验证没有admin.html引用
    const noAdminHtmlInLogin = !loginHtml.includes("'admin.html'") && !loginHtml.includes('"admin.html"');
    log(noAdminHtmlInLogin, 'login.html无admin.html引用', '源码检查');

    // 6.4 验证auth-check.js中admin跳转
    const authCheckJs = fs.readFileSync(path.join(__dirname, 'auth-check.js'), 'utf8');
    const authCheckHasTeacher = authCheckJs.includes("teacher.html");
    const authCheckNoAdmin = !authCheckJs.includes("'admin.html'") && !authCheckJs.includes('"admin.html"');
    log(authCheckHasTeacher && authCheckNoAdmin, 'auth-check.js admin跳转teacher.html', '源码检查');

    // 6.5 验证force-change-password.html中admin跳转
    const fcpHtml = fs.readFileSync(path.join(__dirname, 'force-change-password.html'), 'utf8');
    const fcpHasTeacher = fcpHtml.includes("currentUser.type === 'admin'") &&
                          fcpHtml.includes("window.location.href = 'teacher.html'");
    log(fcpHasTeacher, 'force-change-password.html admin跳转teacher.html', '源码检查');

    const fcpNoAdmin = !fcpHtml.includes("'admin.html'") && !fcpHtml.includes('"admin.html"');
    log(fcpNoAdmin, 'force-change-password.html无admin.html引用', '源码检查');

    // === 7. Teacher页面admin权限验证 ===
    console.log('\n--- 7. Teacher页面admin权限验证 ---');
    const teacherHtml = fs.readFileSync(path.join(__dirname, 'teacher.html'), 'utf8');
    // teacher.html 中 checkTeacher() 允许 admin 访问
    const hasAdminAccess = teacherHtml.includes("user.type !== 'teacher' && user.type !== 'admin'");
    log(hasAdminAccess, 'teacher.html允许admin访问', '源码检查');

    // === 8. HTTPS相关文件清理验证 ===
    console.log('\n--- 8. HTTPS清理验证 ---');
    const certCheckExists = fs.existsSync(path.join(__dirname, 'cert-check.html'));
    log(!certCheckExists, 'cert-check.html已删除', certCheckExists ? '仍存在' : '已删除');

    const installCertExists = fs.existsSync(path.join(__dirname, 'install-cert.html'));
    log(!installCertExists, 'install-cert.html已删除', installCertExists ? '仍存在' : '已删除');

    // === 9. 关键配置验证 ===
    console.log('\n--- 9. 关键配置验证 ---');
    const configJs = fs.readFileSync(path.join(__dirname, 'config.js'), 'utf8');
    const configHasLocalhost = configJs.includes("127.0.0.1");
    log(configHasLocalhost, 'config.js使用127.0.0.1', '源码检查');

    const staticServerJs = fs.readFileSync(path.join(__dirname, 'static-server.js'), 'utf8');
    const hasPort3000 = staticServerJs.includes("3000");
    log(hasPort3000, 'static-server.js监听3000端口', '源码检查');

    const hasApiProxy = staticServerJs.includes("/api/") && staticServerJs.includes("8081");
    log(hasApiProxy, 'static-server.js配置API反代到8081', '源码检查');

    // === 10. keepalive守护验证 ===
    console.log('\n--- 10. keepalive守护验证 ---');
    const keepaliveJs = fs.readFileSync(path.join(__dirname, 'keepalive.js'), 'utf8');
    const hasKeepalive3000 = keepaliveJs.includes("3000");
    log(hasKeepalive3000, 'keepalive.js健康检查3000端口', '源码检查');

    const hasServerJs = keepaliveJs.includes("server.js");
    log(hasServerJs, 'keepalive.js守护server.js', '源码检查');

    const hasStaticServer = keepaliveJs.includes("static-server.js");
    log(hasStaticServer, 'keepalive.js守护static-server.js', '源码检查');

    // === 11. 全局admin.html引用扫描 ===
    console.log('\n--- 11. 全局admin.html引用扫描 ---');
    const htmlJsFiles = [];
    function scanDir(dir) {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
            const fullPath = path.join(dir, entry.name);
            if (entry.isDirectory()) {
                if (entry.name === 'node_modules' || entry.name === '.codeartsdoer') continue;
                scanDir(fullPath);
            } else if (entry.name.endsWith('.html') || entry.name.endsWith('.js')) {
                htmlJsFiles.push(fullPath);
            }
        }
    }
    scanDir(__dirname);

    let adminHtmlRefs = 0;
    const refFiles = [];
    for (const f of htmlJsFiles) {
        if (path.basename(f) === 'full-test.js') continue;
        const content = fs.readFileSync(f, 'utf8');
        if (content.includes('admin.html')) {
            adminHtmlRefs++;
            refFiles.push(path.relative(__dirname, f));
        }
    }
    log(adminHtmlRefs === 0, '无admin.html引用(全局扫描)', adminHtmlRefs > 0 ? `发现引用: ${refFiles.join(', ')}` : '全部清除');

    // === 总结 ===
    console.log('\n========================================');
    console.log(`  测试结果: ${passed} 通过, ${failed} 失败`);
    console.log('========================================');
    if (failures.length > 0) {
        console.log('\n失败项:');
        failures.forEach((f, i) => console.log(`  ${i + 1}. ${f}`));
    }
    console.log('');

    process.exit(failed > 0 ? 1 : 0);
}

runTests().catch((e) => {
    console.error('测试脚本异常:', e);
    process.exit(2);
});
