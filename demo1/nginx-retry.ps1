Write-Output "=== 确保 nginx 完全停止 ==="
Get-Process -Name "nginx" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
if (Test-Path "C:\nginx\logs\nginx.pid") { Remove-Item "C:\nginx\logs\nginx.pid" -Force }

Write-Output "=== 启动 nginx ==="
Start-Process -FilePath "C:\nginx\nginx.exe" -ArgumentList "-p","C:\nginx" -WindowStyle Hidden
Start-Sleep -Seconds 4

Write-Output "=== nginx 进程 ==="
Get-Process -Name "nginx" -ErrorAction SilentlyContinue | Format-Table Id, StartTime

Write-Output "=== 端口监听 ==="
netstat -ano | Select-String "LISTENING" | Select-String ":8090|:8443"

Write-Output "=== 用 Node.js 连接测试 8090 ==="
node -e "const net=require('net');const c=net.connect(8090,'127.0.0.1',()=>{console.log('8090 连接成功');c.end();process.exit(0)});c.on('error',e=>{console.log('8090 失败:',e.message);process.exit(1)})"
Start-Sleep -Seconds 1

Write-Output "=== 用 Node.js 连接测试 8443 ==="
node -e "const net=require('net');const c=net.connect(8443,'127.0.0.1',()=>{console.log('8443 连接成功');c.end();process.exit(0)});c.on('error',e=>{console.log('8443 失败:',e.message);process.exit(1)})"