[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
Write-Output "=== 测试 8090 ==="
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8090/" -TimeoutSec 5 -UseBasicParsing
    Write-Output "8090 status: $($r.StatusCode)"
} catch { Write-Output "8090 err: $($_.Exception.Message)" }

Write-Output "=== 测试 8443 ==="
try {
    $r = Invoke-WebRequest -Uri "https://127.0.0.1:8443/" -TimeoutSec 5 -UseBasicParsing
    Write-Output "8443 status: $($r.StatusCode)"
} catch { Write-Output "8443 err: $($_.Exception.Message)" }

Write-Output "=== 测试 8443/login.html ==="
try {
    $r = Invoke-WebRequest -Uri "https://127.0.0.1:8443/login.html" -TimeoutSec 5 -UseBasicParsing
    Write-Output "8443/login status: $($r.StatusCode), length=$($r.Content.Length)"
} catch { Write-Output "8443/login err: $($_.Exception.Message)" }

Write-Output "=== TCP 8443 ==="
$t = Test-NetConnection -ComputerName 127.0.0.1 -Port 8443 -WarningAction SilentlyContinue
Write-Output "TcpTestSucceeded: $($t.TcpTestSucceeded)"