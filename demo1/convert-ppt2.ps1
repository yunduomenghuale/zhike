$src = "d:\个人教学相关\2026-2027学年第一学期\60426-计算机网络实验教程——基于华为eNSP-PPT课件\应用层实验.ppt"
$dst = "C:\Users\Admin\IDEProjects\demo1\.codeartsdoer\document_explorer\应用层实验.pptx"
Write-Output "Source: $src"
Write-Output "Dest: $dst"
Write-Output "Source exists: $(Test-Path $src)"
$ppt = New-Object -ComObject PowerPoint.Application
$ppt.Visible = 0
try {
    $pres = $ppt.Presentations.Open($src, 0, 0, 0)
    $pres.SaveAs($dst, 24)
    $pres.Close()
    Write-Output "Converted successfully"
} catch {
    Write-Output "Error: $_"
} finally {
    $ppt.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null
}