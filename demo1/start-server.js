const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const pidFile = path.join(__dirname, '.server-pid');
let oldPid = 0;
try { oldPid = parseInt(fs.readFileSync(pidFile, 'utf8')); } catch(e) {}

if (oldPid) {
    try { process.kill(oldPid); } catch(e) {}
}

const child = spawn('node', ['server.js'], {
    cwd: __dirname,
    detached: true,
    stdio: 'ignore'
});
child.unref();

fs.writeFileSync(pidFile, String(child.pid));
console.log('Server started with PID:', child.pid);