$src = "d:\个人教学相关\2026-2027学年第一学期\《计算机网络教程（第7版微课版）》典型教学案例\附件2 典型教学案例 可靠数据传输原理\可靠传输-课堂教学设计.doc"
$dst = "C:\Users\Admin\IDEProjects\demo1\.codeartsdoer\document_explorer\可靠传输-课堂教学设计.docx"
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($src, $false, $true)
    $doc.SaveAs2($dst, 16)
    $doc.Close()
    Write-Output "Converted to: $dst"
} catch {
    Write-Output "Error: $_"
} finally {
    $word.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
}