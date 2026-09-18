// 学习时长追踪器
(function() {
    var pageName = window.location.pathname.split('/').pop().replace('.html', '');
    if (!pageName || pageName === 'login' || pageName === 'admin' || pageName === 'teacher' || pageName === 'user-center') return;

    var pageEnterTime = Date.now();
    var isActive = true;
    var lastActiveTime = Date.now();
    var accumulatedTime = 0;

    var countKey = 'learn-count-' + pageName;
    var currentCount = parseInt(localStorage.getItem(countKey) || '0');
    localStorage.setItem(countKey, String(currentCount + 1));
    fetch(API_BASE + '/api/learn-counts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ page: pageName, count: currentCount + 1 }) }).catch(function() {});

    function updateActivity() {
        isActive = true;
        lastActiveTime = Date.now();
    }

    document.addEventListener('mousemove', updateActivity);
    document.addEventListener('keypress', updateActivity);
    document.addEventListener('click', updateActivity);
    document.addEventListener('scroll', updateActivity);

    setInterval(function() {
        if (Date.now() - lastActiveTime > 300000) {
            isActive = false;
        }
    }, 60000);

    function saveStudyTime() {
        var currentUser = JSON.parse(localStorage.getItem('currentUser') || '{}');
        if (currentUser.type !== 'student' || !currentUser.username) return;

        var currentTime = Date.now();
        var duration = isActive ? (currentTime - pageEnterTime) / 60000 : 0;
        
        if (duration < 0.1) return;

        try {
            var detailKey = 'study-detail-' + currentUser.username;
            var details = JSON.parse(localStorage.getItem(detailKey) || '{}');
            details[pageName] = (details[pageName] || 0) + duration;
            localStorage.setItem(detailKey, JSON.stringify(details));

            fetch(API_BASE + '/api/study/detail', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ studentId: currentUser.username, detail: details })
            }).catch(function() {});

            var totalTime = Object.values(details).reduce(function(s, v) { return s + v; }, 0);
            fetch(API_BASE + '/api/study/time', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ studentId: currentUser.username, time: totalTime })
            }).catch(function() {});

            accumulatedTime += duration;
            pageEnterTime = currentTime;
        } catch (error) {
            console.error('记录学习时长失败:', error);
        }
    }

    setInterval(saveStudyTime, 30000);
    window.addEventListener('beforeunload', saveStudyTime);
    
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            saveStudyTime();
        } else {
            pageEnterTime = Date.now();
        }
    });

    window.saveCurrentStudyTime = saveStudyTime;
})();

// 自动备份机制（每5分钟）
if (typeof BackupUtils !== 'undefined') {
    setInterval(function() {
        BackupUtils.backup().catch(function(err) {
            console.error('自动备份失败:', err);
        });
    }, 300000);

    setTimeout(function() {
        BackupUtils.backup().catch(function(err) {
            console.error('初始备份失败:', err);
        });
    }, 10000);
}