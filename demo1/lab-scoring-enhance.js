var LabScoringEnhance = (function() {
    var startTime = null;
    var errorCount = 0;
    var errorLog = [];
    var maxAccuracyScore = 5;
    var maxEfficiencyScore = 5;
    var maxCompletionScore = 10;
    var standardMinutes = 30;
    var initialized = false;

    function init(stdMin) {
        startTime = Date.now();
        errorCount = 0;
        errorLog = [];
        initialized = true;
        if (stdMin) standardMinutes = stdMin;
    }

    function recordError(stepId, inputCmd) {
        if (!initialized) return;
        errorCount++;
        errorLog.push({ step: stepId, cmd: inputCmd, time: Date.now() });
    }

    function calculateBonus(passedStepCount, totalStepCount) {
        var accuracyScore = Math.max(0, maxAccuracyScore - errorCount);
        var elapsedMin = startTime ? (Date.now() - startTime) / 60000 : 0;
        var overTime = Math.max(0, elapsedMin - standardMinutes);
        var efficiencyScore = Math.max(0, maxEfficiencyScore - Math.floor(overTime / 3));
        var completionRatio = totalStepCount > 0 ? (passedStepCount / totalStepCount) : 0;
        var completionScore = Math.round(completionRatio * maxCompletionScore);
        return {
            accuracy: accuracyScore,
            efficiency: efficiencyScore,
            completion: completionScore,
            total: accuracyScore + efficiencyScore + completionScore,
            errorCount: errorCount,
            elapsedMinutes: Math.round(elapsedMin),
            standardMinutes: standardMinutes,
            passedStepCount: passedStepCount,
            totalStepCount: totalStepCount,
            completionRatio: completionRatio,
            errorLog: errorLog
        };
    }

    function getFinalScore(stepScore, maxStepScore, passedStepCount, totalStepCount) {
        var baseScore = Math.round(stepScore * 0.8);
        var bonus = calculateBonus(passedStepCount || 0, totalStepCount || 0);
        return {
            baseScore: baseScore,
            bonusScore: bonus.total,
            accuracyScore: bonus.accuracy,
            efficiencyScore: bonus.efficiency,
            completionScore: bonus.completion,
            totalScore: baseScore + bonus.total,
            maxScore: maxStepScore,
            errorCount: bonus.errorCount,
            elapsedMinutes: bonus.elapsedMinutes,
            passedStepCount: bonus.passedStepCount,
            totalStepCount: bonus.totalStepCount,
            details: bonus
        };
    }

    function formatDetails(scoreResult) {
        var html = '';
        html += '基础分（步骤完成）：' + scoreResult.baseScore + '/' + Math.round(scoreResult.maxScore * 0.8) + '<br>';
        html += '完成情况：' + scoreResult.completionScore + '/10';
        html += '（完成' + scoreResult.passedStepCount + '/' + scoreResult.totalStepCount + '个步骤）<br>';
        html += '操作准确性：' + scoreResult.accuracyScore + '/5';
        if (scoreResult.errorCount > 0) {
            html += '（错误尝试' + scoreResult.errorCount + '次，每次扣1分）';
        }
        html += '<br>';
        html += '完成效率：' + scoreResult.efficiencyScore + '/5';
        html += '（用时' + scoreResult.elapsedMinutes + '分钟，标准' + standardMinutes + '分钟）<br>';
        html += '<strong>总分：' + scoreResult.totalScore + '/100</strong>';
        return html;
    }

    return {
        init: init,
        recordError: recordError,
        calculateBonus: calculateBonus,
        getFinalScore: getFinalScore,
        formatDetails: formatDetails,
        isInitialized: function() { return initialized; }
    };
})();