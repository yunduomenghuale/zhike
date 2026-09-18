const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const SERVER_FILE = path.join(__dirname, 'server.js');
const LOG_FILE = path.join(__dirname, 'server-watchdog.log');
const PID_FILE = path.join(__dirname, 'server.pid');
const MAX_RESTARTS = 50;
const RESTART_DELAY = 2000;
const HEALTH_CHECK_INTERVAL = 10000;
const HEALTH_CHECK_URL = { hostname: '127.0.0.1', port: 8081, path: '/api/knowledge', timeout: 5000 };

let restartCount = 0;
let lastRestartTime = 0;
let serverProcess = null;
let isShuttingDown = false;

function log(msg) {
    var ts = new Date().toISOString();
    var line = '[' + ts + '] ' + msg;
    console.log(line);
    fs.appendFileSync(LOG_FILE, line + '\n', 'utf8');
}

function writePid(pid) {
    try { fs.writeFileSync(PID_FILE, String(pid), 'utf8'); } catch(e) {}
}

function clearPid() {
    try { if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE); } catch(e) {}
}

function startServer() {
    if (isShuttingDown) return;
    
    log('Starting server.js (PID pending)...');
    
    serverProcess = spawn('node', [SERVER_FILE], {
        cwd: __dirname,
        stdio: ['ignore', 'pipe', 'pipe']
    });
    
    writePid(serverProcess.pid);
    log('Server started with PID: ' + serverProcess.pid);
    
    serverProcess.stdout.on('data', function(data) {
        var lines = data.toString().trim().split('\n');
        lines.forEach(function(line) {
            if (line.trim()) log('[SERVER] ' + line.trim());
        });
    });
    
    serverProcess.stderr.on('data', function(data) {
        var lines = data.toString().trim().split('\n');
        lines.forEach(function(line) {
            if (line.trim()) log('[SERVER-ERR] ' + line.trim());
        });
    });
    
    serverProcess.on('exit', function(code, signal) {
        clearPid();
        if (isShuttingDown) {
            log('Server stopped by watchdog shutdown. Exit code: ' + code);
            return;
        }
        
        log('Server exited unexpectedly! Code: ' + code + ', Signal: ' + signal);
        
        var now = Date.now();
        if (now - lastRestartTime < 5000) {
            restartCount++;
        } else {
            restartCount = 1;
        }
        lastRestartTime = now;
        
        if (restartCount > MAX_RESTARTS) {
            log('ERROR: Max restarts (' + MAX_RESTARTS + ') exceeded. Stopping watchdog.');
            process.exit(1);
        }
        
        log('Restarting server in ' + RESTART_DELAY + 'ms... (attempt ' + restartCount + '/' + MAX_RESTARTS + ')');
        setTimeout(startServer, RESTART_DELAY);
    });
    
    serverProcess.on('error', function(err) {
        log('Failed to start server: ' + err.message);
        setTimeout(startServer, RESTART_DELAY);
    });
}

function healthCheck() {
    if (isShuttingDown || !serverProcess || serverProcess.killed) return;
    
    var req = http.get(HEALTH_CHECK_URL, function(res) {
        if (res.statusCode !== 200) {
            log('Health check WARNING: HTTP ' + res.statusCode);
        }
        res.resume();
    });
    
    req.on('error', function(e) {
        log('Health check FAILED: ' + e.message + ' - server may be down');
    });
    
    req.on('timeout', function() {
        log('Health check TIMEOUT - server may be hung');
        req.destroy();
    });
}

process.on('SIGINT', function() {
    log('Watchdog received SIGINT, shutting down...');
    isShuttingDown = true;
    if (serverProcess) {
        serverProcess.kill('SIGINT');
        setTimeout(function() {
            if (serverProcess && !serverProcess.killed) {
                serverProcess.kill('SIGTERM');
            }
            process.exit(0);
        }, 3000);
    } else {
        process.exit(0);
    }
});

process.on('SIGTERM', function() {
    log('Watchdog received SIGTERM, shutting down...');
    isShuttingDown = true;
    if (serverProcess) serverProcess.kill('SIGTERM');
    setTimeout(function() { process.exit(0); }, 2000);
});

process.on('uncaughtException', function(err) {
    log('Watchdog uncaughtException: ' + err.message);
});

log('========================================');
log('  Watchdog for 网络学习小伴侣');
log('  Monitoring server.js on port 8081');
log('  Max restarts: ' + MAX_RESTARTS);
log('  Health check interval: ' + HEALTH_CHECK_INTERVAL + 'ms');
log('========================================');

startServer();
setInterval(healthCheck, HEALTH_CHECK_INTERVAL);