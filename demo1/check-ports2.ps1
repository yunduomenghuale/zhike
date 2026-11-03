Write-Output "=== node 进程 ==="
Get-Process -Name "node" -ErrorAction SilentlyContinue | Format-Table Id, StartTime, WorkingSet

Write-Output "=== 端口监听 ==="
netstat -ano | Select-String "LISTENING" | Select-String ":8090|:8443|:8081"

Write-Output "=== 用 Node.js 直接连接 8090 ==="
node -e "const net=require('net');const c=net.connect(8090,'127.0.0.1',()=>{console.log('8090 OK');c.end();process.exit(0)});c.on('error',e=>{console.log('8090 ERR:',e.message);process.exit(1)});setTimeout(()=>{console.log('8090 TIMEOUT');process.exit(2)},5000)"

Write-Output "=== 用 Node.js 直接连接 8443 ==="
node -e "const net=require('net');const c=net.connect(8443,'127.0.0.1',()=>{console.log('8443 OK');c.end();process.exit(0)});c.on('error',e=>{console.log('8443 ERR:',e.message);process.exit(1)});setTimeout(()=>{console.log('8443 TIMEOUT');process.exit(2)},5000)"

Write-Output "=== 用 Node.js 直接连接 8081 ==="
node -e "const net=require('net');const c=net.connect(8081,'127.0.0.1',()=>{console.log('8081 OK');c.end();process.exit(0)});c.on('error',e=>{console.log('8081 ERR:',e.message);process.exit(1)});setTimeout(()=>{console.log('8081 TIMEOUT');process.exit(2)},5000)"