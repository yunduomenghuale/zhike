const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const LOG = path.join(__dirname, 'keepalive.log');
function log(msg) {
  const line = '[' + new Date().toISOString() + '] ' + msg;
  try { fs.appendFileSync(LOG, line + '\n', 'utf8'); } catch (e) {}
  console.log(line);
}

function startProcess(name, args) {
  log('启动 ' + name + ' ' + args.join(' '));
  const p = spawn('node', args, { cwd: __dirname, stdio: ['ignore', 'pipe', 'pipe'] });
  p.stdout.on('data', d => log('[' + name + ' stdout] ' + d.toString().trim()));
  p.stderr.on('data', d => log('[' + name + ' stderr] ' + d.toString().trim()));
  p.on('exit', (code, signal) => {
    log('[' + name + '] 退出 code=' + code + ' signal=' + signal + '，5秒后重启');
    setTimeout(() => startProcess(name, args), 5000);
  });
  return p;
}

process.on('uncaughtException', e => log('keepalive uncaught: ' + e.message));

startProcess('server', ['server.js']);
setTimeout(() => startProcess('static', ['static-server.js']), 3000);

// 每30秒检查服务是否可达，不可达则记录日志
setInterval(() => {
  http.get('http://127.0.0.1:3000/index.html', { timeout: 4000 }, res => {
    res.resume();
  }).on('error', () => {
    log('健康检查: 3000 不可达');
  });
}, 30000);

log('keepalive 守护启动');
