const http = require('http');
const fs = require('fs');
const path = require('path');

process.on('uncaughtException', function(err) {
    console.error('[Uncaught Exception]', err.message, err.stack);
});
process.on('unhandledRejection', function(err) {
    console.error('[Unhandled Rejection]', err);
});

const kbApiRouter = require('./kb-api-router');
const kbDataStore = require('./kb-data-store');
const kbUpdater = require('./kb-updater');
const userApiRouter = require('./user-api-router');
const userDataStore = require('./user-data-store');
const quizApiRouter = require('./quiz-api-router');

var config = {};
try {
    var configContent = fs.readFileSync(path.join(__dirname, 'config.js'), 'utf8');
    configContent.replace(/HOST\s*:\s*['"]([^'"]+)['"]/, function(m, v) { config.HOST = v; });
    configContent.replace(/PORT\s*:\s*(\d+)/, function(m, v) { config.PORT = parseInt(v); });
} catch (e) {
    config.HOST = '127.0.0.1';
    config.PORT = 8080;
}

var MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.pdf': 'application/pdf',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.eot': 'application/vnd.ms-fontobject'
};

var server = http.createServer(function(req, res) {
    var urlPath = req.url.split('?')[0];
    if (urlPath === '/') urlPath = '/index.html';

    if (urlPath.indexOf('/api/') === 0) {
        if (urlPath.indexOf('/api/user/') === 0 || urlPath.indexOf('/api/classes') === 0 ||
            urlPath.indexOf('/api/students') === 0 || urlPath.indexOf('/api/majors') === 0 ||
            urlPath.indexOf('/api/teachers') === 0 || urlPath.indexOf('/api/depts') === 0 ||
            urlPath.indexOf('/api/lab-schedules') === 0 || urlPath.indexOf('/api/study/') === 0 ||
            urlPath.indexOf('/api/lab-reports') === 0 || urlPath.indexOf('/api/learn-counts') === 0 ||
            urlPath.indexOf('/api/stats/') === 0 || urlPath.indexOf('/api/generate-report') === 0 ||
            urlPath.indexOf('/api/download-report/') === 0) {
            try {
                var userResult = userApiRouter.handleRoute(req, res, urlPath);
                if (userResult && typeof userResult.then === 'function') {
                    userResult.catch(function(err) {
                        console.error('[User API Error]', err);
                        try { res.writeHead(500, {'Content-Type':'application/json','Access-Control-Allow-Origin':'*'}); res.end(JSON.stringify({error:'服务器内部错误'})); } catch(e) {}
                    });
                } else if (userResult === false) {
                    res.writeHead(404, {'Content-Type':'application/json','Access-Control-Allow-Origin':'*'});
                    res.end(JSON.stringify({error:'API not found'}));
                }
            } catch(err) {
                res.writeHead(500, {'Content-Type':'application/json','Access-Control-Allow-Origin':'*'});
                res.end(JSON.stringify({error:'服务器内部错误'}));
            }
            return;
        }
        if (urlPath.indexOf('/api/questions') === 0 || urlPath.indexOf('/api/assignments') === 0 ||
            urlPath.indexOf('/api/quiz/') === 0) {
            try {
                var result = quizApiRouter.handleRoute(req, res, urlPath, req.method);
                if (result && typeof result.then === 'function') {
                    result.catch(function(err) {
                        console.error('[Quiz API Error]', err);
                        try { res.writeHead(500, {'Content-Type':'application/json','Access-Control-Allow-Origin':'*'}); res.end(JSON.stringify({error:'服务器内部错误'})); } catch(e) {}
                    });
                } else if (result === false) {
                    res.writeHead(404, {'Content-Type':'application/json','Access-Control-Allow-Origin':'*'});
                    res.end(JSON.stringify({error:'API not found'}));
                }
            } catch(err) {
                res.writeHead(500, {'Content-Type':'application/json','Access-Control-Allow-Origin':'*'});
                res.end(JSON.stringify({error:'服务器内部错误'}));
            }
            return;
        }
        var contentType = req.headers['content-type'] || '';
        if (contentType.indexOf('multipart/form-data') >= 0) {
            kbApiRouter.handleRequest(req, res, urlPath, req.method, null);
            return;
        }
        var body = '';
        req.on('data', function(chunk) { body += chunk; });
        req.on('end', function() {
            var parsedBody = null;
            if (body && (req.method === 'POST' || req.method === 'PUT')) {
                try { parsedBody = JSON.parse(body); } catch (e) { parsedBody = null; }
            }
            kbApiRouter.handleRequest(req, res, urlPath, req.method, parsedBody);
        });
        return;
    }

    var filePath = path.join(__dirname, urlPath);
    var ext = path.extname(filePath).toLowerCase();

    fs.readFile(filePath, function(err, data) {
        if (err) {
            res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
            res.end('<h1>404 - 页面未找到</h1><p>请检查URL是否正确</p>');
            return;
        }

        var contentType = MIME_TYPES[ext] || 'application/octet-stream';
        res.writeHead(200, {
            'Content-Type': contentType,
            'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=3600',
            'Access-Control-Allow-Origin': '*'
        });
        res.end(data);
    });
});

server.listen(config.PORT, config.HOST, function() {
    var staticKnowledge = [];
    try {
        var kbContent = fs.readFileSync(path.join(__dirname, 'chat-knowledge.js'), 'utf8');
        var match = kbContent.match(/var\s+ChatKnowledge\s*=\s*(\[[\s\S]*\]);/);
        if (match) {
            staticKnowledge = eval('(' + match[1] + ')');
        }
    } catch (e) {
        console.log('  Warning: Could not load static knowledge data');
    }
    kbDataStore.initFromStaticData(staticKnowledge);
    kbUpdater.startScheduler();
    userDataStore.initDefaultAdmin().then(function() {
        console.log('  用户数据已初始化');
    });

    console.log('========================================');
    console.log('  网络学习小伴侣 已启动');
    console.log('  访问地址: http://' + config.HOST + ':' + config.PORT);
    console.log('  按 Ctrl+C 停止服务器');
    console.log('========================================');
});