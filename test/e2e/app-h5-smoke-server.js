/* 移动端 H5 冒烟服务：静态serve app/dist/build/h5 + 代理 /api、/media 到 8005 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const DIST = path.resolve(__dirname, '../../app/dist/build/h5');
const PORT = 5299;
const BACKEND = { host: '127.0.0.1', port: 8005 };

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml',
};

http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/media')) {
    const proxy = http.request(
      { host: BACKEND.host, port: BACKEND.port, path: url.pathname + url.search, method: req.method, headers: { ...req.headers, host: `127.0.0.1:${BACKEND.port}` } },
      (pr) => { res.writeHead(pr.statusCode, pr.headers); pr.pipe(res); },
    );
    proxy.on('error', () => { res.writeHead(502); res.end('backend unreachable'); });
    req.pipe(proxy);
    return;
  }
  // 应用以 /m/ 为 publicPath 构建（生产子路径），冒烟时把 /m 前缀剥掉再找文件
  let reqPath = decodeURIComponent(url.pathname);
  if (reqPath === '/m' || reqPath.startsWith('/m/')) reqPath = reqPath.slice(2) || '/';
  let file = path.join(DIST, reqPath);
  if (!file.startsWith(DIST)) { res.writeHead(403); res.end(); return; }
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) file = path.join(DIST, 'index.html');
    fs.readFile(file, (e2, data) => {
      if (e2) { res.writeHead(404); res.end('not found'); return; }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream' });
      res.end(data);
    });
  });
}).listen(PORT, () => console.log('app h5 smoke server on ' + PORT));
