var LabReportGenerator = (function() {
    var conclusionText = '';
    var generatedFiles = null;

    function init() {
        if (document.getElementById('conclusionModal')) return;

        var modalHtml = '<div class="modal-overlay" id="conclusionModal">' +
            '<div class="modal-box" style="max-width:600px;">' +
            '<h2>填写实验结论</h2>' +
            '<p style="font-size:14px;color:#666;margin-bottom:10px;">请填写本次实验的结论和心得体会，提交后将自动生成实验报告（DOCX和PDF格式）。</p>' +
            '<textarea id="conclusionInput" rows="6" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;font-size:14px;font-family:inherit;resize:vertical;" placeholder="请输入实验结论..."></textarea>' +
            '<div style="margin-top:15px;text-align:center;">' +
            '<button class="btn btn-primary" onclick="LabReportGenerator.submitConclusion()" style="margin-right:10px;">提交并生成报告</button>' +
            '<button class="btn" onclick="LabReportGenerator.cancelConclusion()">取消</button>' +
            '</div>' +
            '</div>' +
            '</div>';

        var reportModalHtml = '<div class="modal-overlay" id="reportDownloadModal">' +
            '<div class="modal-box" style="max-width:500px;">' +
            '<h2>实验报告已生成</h2>' +
            '<p style="font-size:14px;color:#666;margin-bottom:15px;">您的实验报告已成功生成，请选择下载格式：</p>' +
            '<div style="display:flex;justify-content:center"center;gap:15px;margin:20px 0;">' +
            '<a id="downloadPdfLink" href="#" style="display:inline-block;padding:12px 30px;background:linear-gradient(135deg,#dc2626,#b91c1c);color:white;border-radius:10px;text-decoration:none;font-size:16px;">下载 PDF</a>' +
            '<a id="downloadDocxLink" href="#" style="display:inline-block;padding:12px 30px;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:white;border-radius:10px;text-decoration:none;font-size:16px;">下载 DOCX</a>' +
            '</div>' +
            '<button class="btn btn-primary" onclick="document.getElementById(\'reportDownloadModal\').classList.remove(\'show\')" style="margin-top:10px;">关闭</button>' +
            '</div>' +
            '</div>';

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        document.body.insertAdjacentHTML('beforeend', reportModalHtml);

        document.getElementById('conclusionInput').addEventListener('paste', function(e) {
            e.preventDefault();
        });
    }

    function showConclusionDialog() {
        init();
        document.getElementById('conclusionInput').value = '';
        document.getElementById('conclusionModal').classList.add('show');
    }

    function cancelConclusion() {
        document.getElementById('conclusionModal').classList.remove('show');
    }

    async function submitConclusion() {
        var conclusion = document.getElementById('conclusionInput').value.trim();
        if (!conclusion) {
            alert('请填写实验结论后再提交');
            return;
        }

        conclusionText = conclusion;
        document.getElementById('conclusionModal').classList.remove('show');

        var currentUser = JSON.parse(localStorage.getItem('currentUser') || '{}');
        if (!currentUser.username) {
            alert('请先登录');
            return;
        }

        var labId = document.body.getAttribute('data-lab-id') || '';
        if (!labId) {
            var path = window.location.pathname;
            labId = path.substring(path.lastIndexOf('/') + 1).replace('.html', '');
        }

        var stepsText = '';
        if (typeof STEPS !== 'undefined' && typeof stepResults !== 'undefined') {
            for (var i = 0; i < STEPS.length; i++) {
                var s = STEPS[i];
                if (stepResults[s.id] === 'pass') {
                    stepsText += '步骤' + s.id + '. ' + s.title + '\n';
                }
            }
        }

        var scoreResult = null;
        if (typeof LabScoringEnhance !== 'undefined') {
            var passedSteps = 0;
            var totalSteps = 0;
            if (typeof STEPS !== 'undefined' && typeof stepResults !== 'undefined') {
                totalSteps = STEPS.length;
                for (var si = 0; si < STEPS.length; si++) {
                    if (stepResults[STEPS[si].id] === 'pass') passedSteps++;
                }
            }
            scoreResult = LabScoringEnhance.getFinalScore(
                typeof totalScore !== 'undefined' ? totalScore : 0, 100, passedSteps, totalSteps
            );
        }

        var reportData = {
            labId: labId,
            totalScore: scoreResult ? scoreResult.totalScore : (typeof totalScore !== 'undefined' ? totalScore : 0),
            baseScore: scoreResult ? scoreResult.baseScore : 0,
            comprehensiveScore: scoreResult ? (scoreResult.completionScore + scoreResult.accuracyScore + scoreResult.efficiencyScore) : 0,
            studentId: currentUser.username,
            studentName: currentUser.name || currentUser.username,
            className: currentUser.className || '',
            experimentDate: new Date().toLocaleDateString('zh-CN'),
            steps: stepsText,
            conclusion: conclusionText
        };

        try {
            var token = localStorage.getItem('authToken') || '';
            var res = await fetch(API_BASE + '/api/generate-report', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                body: JSON.stringify(reportData)
            });
            var result = await res.json();

            if (result.error) {
                alert('报告生成失败: ' + result.error);
                return;
            }

            generatedFiles = result;

            var pdfLink = document.getElementById('downloadPdfLink');
            var docxLink = document.getElementById('downloadDocxLink');

            pdfLink.href = API_BASE + '/api/download-report/' + result.pdfFileName;
            docxLink.href = API_BASE + '/api/download-report/' + result.docxFileName;

            pdfLink.target = '_blank';
            docxLink.target = '_blank';

            document.getElementById('reportDownloadModal').classList.add('show');
        } catch (e) {
            alert('报告生成失败: ' + e.message);
        }
    }

    return {
        init: init,
        showConclusionDialog: showConclusionDialog,
        submitConclusion: submitConclusion,
        cancelConclusion: cancelConclusion
    };
})();