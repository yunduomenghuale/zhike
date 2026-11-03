Write-Output "=== 用不同地址测试 8090 ==="
foreach ($addr in @("127.0.0.1", "localhost", "0.0.0.0")) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect($addr, 8090)
        Write-Output "$addr:8090 连接成功"
        $client.Close()
    } catch {
        Write-Output "$addr:8090 失败: $($_.Exception.InnerException.Message)"
    }
}

Write-Output ""
Write-Output "=== 用不同地址测试 8443 ==="
foreach ($addr in @("127.0.0.1", "localhost", "0.0.0.0")) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect($addr, 8443)
        Write-Output "$addr:8443 连接成功"
        $client.Close()
    } catch {
        Write-Output "$addr:8443 失败: $($_.Exception.InnerException.Message)"
    }
}

Write-Output ""
Write-Output "=== 对比 8081 (Node.js) ==="
foreach ($addr in @("127.0.0.1", "localhost")) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect($addr, 8081)
        Write-Output "$addr:8081 连接成功"
        $client.Close()
    } catch {
        Write-Output "$addr:8081 失败: $($_.Exception.InnerException.Message)"
    }
}

Write-Output ""
Write-Output "=== 防火墙规则（nginx） ==="
Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like "*nginx*" -or $_.DisplayName -like "*8090*" -or $_.DisplayName -like "*8443*" } | Select-Object DisplayName, Enabled, Direction, Action