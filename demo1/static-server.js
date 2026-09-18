const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

process.on('uncaughtException', function(err) {
    console.error('[Static Server Uncaught]', err.message);
});
process.on('unhandledRejection', function(err) {
    console.error('[Static Server Rejection]', err);
});

const ROOT_DIR = __dirname;
const HTTP_PORT = 3000;
const API_BACKEND = { hostname: '127.0.0.1', port: 8081 };

const MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.htm': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.pdf': 'application/pdf',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.eot': 'application/vnd.ms-fontobject',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.xls': 'application/vnd.ms-excel',
    '.map': 'application/json; charset=utf-8',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.ogg': 'audio/ogg',
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.txt': 'text/plain; charset=utf-8',
    '.xml': 'application/xml; charset=utf-8'
};

function getMimeType(filePath) {
    return MIME_TYPES[path.extname(filePath).toLowerCase()] || 'application/octet-stream';
}

function serveStaticFile(req, res, filePath) {
    fs.stat(filePath, function(err, stats) {
        if (err || !stats.isFile()) {
            serve404(res);
            return;
        }
        const ext = path.extname(filePath).toLowerCase();
        const mimeType = getMimeType(filePath);

        res.setHeader('Content-Type', mimeType);

        if (ext === '.html' || ext === '.htm' || ext === '.css' || ext === '.js') {
            res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
        } else if (['.jpg', '.jpeg', '.png', '.gif', '.ico', '.svg', '.woff', '.woff2', '.ttf', '.eot'].indexOf(ext) >= 0) {
            res.setHeader('Cache-Control', 'public, max-age=3600');
        }

        const rangeHeader = req.headers['range'];
        if (rangeHeader) {
            const total = stats.size;
            const parts = rangeHeader.replace(/bytes=/, '').split('-');
            const start = parseInt(parts[0], 10);
            const end = parts[1] ? parseInt(parts[1], 10) : total - 1;
            res.writeHead(206, {
                'Content-Range': 'bytes ' + start + '-' + end + '/' + total,
                'Accept-Ranges': 'bytes',
                'Content-Length': (end - start + 1)
            });
            fs.createReadStream(filePath, { start: start, end: end }).pipe(res);
        } else {
            res.writeHead(200);
            fs.createReadStream(filePath).pipe(res);
        }
    });
}

function serve404(res) {
    const p404 = path.join(ROOT_DIR, '404.html');
    fs.stat(p404, function(e) {
        if (!e) {
            res.writeHead(404, { 'Content-Type': 'text/html; charset=utf-8' });
            fs.createReadStream(p404).pipe(res);
        } else {
            res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
            res.end('404 Not Found');
        }
    });
}

function proxyToBackend(req, res) {
    const options = {
        hostname: API_BACKEND.hostname,
        port: API_BACKEND.port,
        path: req.url,
        method: req.method,
        headers: Object.assign({}, req.headers, {
            host: API_BACKEND.hostname + ':' + API_BACKEND.port,
            'x-real-ip': req.socket.remoteAddress,
            'x-forwarded-for': req.headers['x-forwarded-for'] || req.socket.remoteAddress,
            'x-forwarded-proto': 'http'
        })
    };

    const proxyReq = http.request(options, function(proxyRes) {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
    });
    proxyReq.on('error', function(e) {
        if (!res.headersSent) {
            res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: 'Backend unavailable', detail: e.message }));
        }
    });
    req.pipe(proxyReq);
}

const httpServer = http.createServer(function(req, res) {
    const parsed = url.parse(req.url);
    let urlPath = decodeURIComponent(parsed.pathname);

    if (urlPath.indexOf('/api/') === 0) {
        proxyToBackend(req, res);
        return;
    }

    if (urlPath === '/') urlPath = '/index.html';

    const filePath = path.join(ROOT_DIR, urlPath);
    const realPath = path.resolve(filePath);
    const realRoot = path.resolve(ROOT_DIR);
    if (realPath.indexOf(realRoot) !== 0) {
        serve404(res);
        return;
    }

    serveStaticFile(req, res, filePath);
});

httpServer.on('error', function(e) {
    console.error('[static-server] HTTP error: ' + e.message);
});

httpServer.listen(HTTP_PORT, '0.0.0.0', function() {
    console.log('[static-server] HTTP  ' + HTTP_PORT + ' (static + /api proxy -> ' + API_BACKEND.hostname + ':' + API_BACKEND.port + ') -> root: ' + ROOT_DIR);
});

console.log('[static-server] 纯HTTP模式提供静态文件与反代服务');
