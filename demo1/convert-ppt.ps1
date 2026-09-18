﻿$pptFiles = @(
    "d:\个人教学相关\2026-2027学年第一学期\60426-计算机网络实验教程——基于华为eNSP-PPT课件\运输层实验.ppt",
    "d:\个人教学相关\2026-2027学年第一学期\60426-计算机网络实验教程——基于华为eNSP-PPT课件\应用层实验.ppt"
)
$outDir = "C:\Users\Admin\IDEProjects\demo1\.codeartsdoer\document_explorer"

$ppt = New-Object -ComObject PowerPoint.Application
$ppt.Visible = 0
try {
    foreach ($file in $pptFiles) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($file)
        $outPath = Join-Path $outDir "$name.pptx"
        Write-Output "Converting: $name"
        $pres = $ppt.Presentations.Open($file, 0, 0, 0)
        $pres.SaveAs($outPath, 24)
        $pres.Close()
        Write-Output "Done: $outPath"
    }
    Write-Output "All conversions complete"
} catch {
    Write-Output "Error: $_"
} finally {
    $ppt.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null
}
