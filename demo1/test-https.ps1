[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
try {
    $r = Invoke-WebRequest -Uri "https://127.0.0.1:8443/" -TimeoutSec 5 -UseBasicParsing
    Write-Output "8443 status: $($r.StatusCode)"
} catch {
    Write-Output "8443 err: $($_.Exception.Message)"
}