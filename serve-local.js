/* 智课系统V2 本地前端服务：serves frontend/dist + 代理 /api、/media 到 Django 8005。
 * 用途：替代 vite dev server（其依赖优化会被环境 safe-delete 守卫拦崩）。
 * 启动：node serve-local.js  访问：http://localhost:5273
 * 注意：前端源码有改动时需先 cd frontend && npm run build 再重启本服务。
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const DIST = path.resolve(__dirname, 'frontend/dist');
const PORT = 5273;
const BACKEND = { host: '127.0.0.1', port: 8005 };

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff': 'font/woff',
  '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.map': 'application/json',
  '.webp': 'image/webp', '.gif': 'image/gif', '.pdf': 'application/pdf',
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/media')) {
    const proxy = http.request(
      {
        host: BACKEND.host, port: BACKEND.port,
        path: url.pathname + url.search, method: req.method,
        headers: { ...req.headers, host: `127.0.0.1:${BACKEND.port}` },
      },
      (pr) => {
        res.writeHead(pr.statusCode, pr.headers);
        pr.pipe(res);
      },
    );
    proxy.on('error', () => {
      if (res.headersSent) { try { res.destroy(); } catch {} return; }
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ code: 502, message: 'backend unreachable' }));
    });
    res.on('error', () => { try { proxy.destroy(); } catch {} });
    req.on('error', () => { try { proxy.destroy(); } catch {} });
    req.pipe(proxy);
    return;
  }
  // SPA：静态文件优先，否则回退 index.html
  let file = path.join(DIST, decodeURIComponent(url.pathname));
  if (!file.startsWith(DIST)) { res.writeHead(403); res.end(); return; }
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) file = path.join(DIST, 'index.html');
    fs.readFile(file, (e2, data) => {
      if (e2) { res.writeHead(404); res.end('not found'); return; }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' });
      res.end(data);
    });
  });
});

server.on('error', (e) => { console.error('server error:', e.message); process.exit(1); });
server.listen(PORT, '::', () => console.log(`zhike local server on http://localhost:${PORT} (dist + :8005)`));
