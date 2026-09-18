(function() {
    var _basePath = (function() {
        if (window.location.protocol === 'file:') return 'http://localhost:8090/';
        var path = window.location.pathname;
        if (path.indexOf('/demos/') !== -1 || path.indexOf('/labs/') !== -1) {
            return '../';
        }
        return '';
    })();

    if (!window.SiteConfig) {
        var cs = document.createElement('script');
        cs.src = _basePath + 'config.js';
        cs.async = false;
        document.head.appendChild(cs);
    }

    function checkAuth() {
        var currentUser = localStorage.getItem('currentUser');
        if (!currentUser) {
            window.location.href = _basePath + 'login.html';
            return null;
        }
        var user = JSON.parse(currentUser);
        var lastActivity = parseInt(localStorage.getItem('lastActivity') || '0');
        if (lastActivity && Date.now() - lastActivity > 30 * 60 * 1000) {
            localStorage.removeItem('currentUser');
            localStorage.removeItem('lastActivity');
            window.location.href = _basePath + 'login.html';
            return null;
        }
        localStorage.setItem('lastActivity', String(Date.now()));
        return user;
    }

    function createUserBar() {
        var user = checkAuth();
        if (!user) return;

        var userBar = document.createElement('div');
        userBar.id = 'user-info-bar';
        userBar.style.cssText = 'position:fixed;top:0;left:0;right:0;height:85px;background:linear-gradient(135deg,#3498db 0%,#2980b9 100%);color:white;display:flex;align-items:center;justify-content:space-between;padding:0 20px;box-shadow:0 2px 10px rgba(0,0,0,0.2);z-index:9999;font-family:"Microsoft YaHei",Arial,sans-serif;';

        var adminHtml = '';
        if (user.type === 'admin') {
            adminHtml = '<a href="' + _basePath + 'teacher.html" class="ubar-dropdown-item"><span class="ubar-dropdown-icon">⚙️</span><span>管理员控制台</span></a>';
        } else if (user.type === 'teacher') {
            adminHtml = '<a href="' + _basePath + 'teacher.html" class="ubar-dropdown-item"><span class="ubar-dropdown-icon">📊</span><span>教师管理页面</span></a>';
        }

        var studentStatsHtml = '';
        if (user.type === 'student') {
            studentStatsHtml = '<div class="ubar-study-stats"><span>📚 学习次数：<strong id="ubarLearnCount">0</strong> 次</span><span>⏱️ 学习时长：<strong id="ubarStudyTime">0</strong> 分钟</span></div>';
        }

        userBar.innerHTML = '<div style="display:flex;align-items:center;gap:15px;">' +
            '<a href="' + _basePath + 'index.html" style="color:white;text-decoration:none;font-weight:bold;font-size:16px;">🏠 首页</a>' +
            studentStatsHtml +
            '</div>' +
            '<div style="position:absolute;left:50%;bottom:8px;transform:translateX(-50%);text-align:center;white-space:nowrap;">' +
                '<div style="font-size:48px;font-weight:900;letter-spacing:5px;font-family:STXingkai,华文行楷,serif;background:linear-gradient(135deg,#e0f2fe,#c7d2fe,#e9d5ff,#e0f2fe);background-size:300% 300%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:ubarTitleShift 4s ease infinite;filter:drop-shadow(0 0 8px rgba(255,255,255,0.3));">计算机网络课程辅助教学平台</div>' +
                '<div style="font-size:18px;letter-spacing:2px;color:rgba(255,255,255,0.75);margin-top:1px;font-weight:400;font-style:italic;">Computer Network Course Assisted Teaching Platform</div>' +
            '</div>' +
            '<div class="ubar-user-menu">' +
                '<div class="ubar-user-button" onclick="ubarToggleDropdown()">' +
                    '<span style="font-size:24px;">' + (user.icon || '👤') + '</span>' +
                    '<div>' +
                        '<div style="font-weight:bold;font-size:14px;">' + (user.name || user.username) + '</div>' +
                        '<div style="font-size:12px;opacity:0.9;">' + (user.typeName || '') + '</div>' +
                    '</div>' +
                    '<span class="ubar-arrow">▼</span>' +
                '</div>' +
                '<div class="ubar-dropdown-menu" id="ubarDropdownMenu">' +
                    '<a href="' + _basePath + 'user-center.html" class="ubar-dropdown-item"><span class="ubar-dropdown-icon">👤</span><span>用户中心</span></a>' +
                    adminHtml +
                    '<a href="#" onclick="logout()" class="ubar-dropdown-item"><span class="ubar-dropdown-icon">🚪</span><span>退出登录</span></a>' +
                '</div>' +
            '</div>';

        document.body.insertBefore(userBar, document.body.firstChild);
        document.body.style.paddingTop = '85px';

        if (user.type === 'student') {
            updateUbarStudyStats(user.username);
        }
    }

    window.ubarToggleDropdown = function() {
        var menu = document.getElementById('ubarDropdownMenu');
        var arrow = document.querySelector('.ubar-arrow');
        if (menu.classList.contains('show')) {
            menu.classList.remove('show');
            arrow.style.transform = 'rotate(0deg)';
        } else {
            menu.classList.add('show');
            arrow.style.transform = 'rotate(180deg)';
        }
    };

    function updateUbarStudyStats(username) {
        fetch(_basePath + 'api/user/info', {
            headers: { 'Authorization': 'Bearer ' + (localStorage.getItem('authToken') || '') }
        }).then(function(r) { return r.json(); }).then(function(data) {
            if (data.user) {
                var lc = document.getElementById('ubarLearnCount');
                var st = document.getElementById('ubarStudyTime');
                if (lc) lc.textContent = data.user.loginCount || 0;
                if (st) st.textContent = Math.round(data.user.totalStudyTime || 0);
            }
        }).catch(function() {});
    }

    window.logout = function() {
        if (confirm('确定要退出登录吗？')) {
            var token = localStorage.getItem('authToken');
            if (token) {
                fetch(_basePath + 'api/user/logout', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' }
                }).catch(function() {});
            }
            localStorage.removeItem('currentUser');
            localStorage.removeItem('lastActivity');
            localStorage.removeItem('authToken');
            window.location.href = _basePath + 'login.html';
        }
    };

    window.checkAuth = checkAuth;

    var style = document.createElement('style');
    style.textContent =
        '.ubar-user-menu { position: relative; }' +
        '.ubar-user-button { display:flex;align-items:center;gap:10px;cursor:pointer;padding:5px 10px;border-radius:8px;transition:background 0.3s; }' +
        '.ubar-user-button:hover { background:rgba(255,255,255,0.15); }' +
        '.ubar-arrow { font-size:12px;transition:transform 0.3s;margin-left:5px; }' +
        '.ubar-dropdown-menu { display:none;position:absolute;top:45px;right:0;background:white;border-radius:10px;box-shadow:0 10px 40px rgba(0,0,0,0.25);min-width:200px;overflow:hidden;z-index:10001; }' +
        '.ubar-dropdown-menu.show { display:block;animation:ubarSlideDown 0.3s ease; }' +
        '@keyframes ubarSlideDown { from{opacity:0;transform:translateY(-10px);}to{opacity:1;transform:translateY(0);} }' +
        '.ubar-dropdown-item { padding:12px 20px;color:#333;text-decoration:none;display:flex;align-items:center;gap:10px;transition:all 0.3s;border-bottom:1px solid #f0f0f0;font-size:14px; }' +
        '.ubar-dropdown-item:last-child { border-bottom:none; }' +
        '.ubar-dropdown-item:hover { background:#f0f8ff;color:#4a90e2; }' +
        '.ubar-dropdown-icon { font-size:18px; }' +
        '.ubar-study-stats { display:flex;align-items:center;gap:15px;margin-left:20px;font-size:13px;background:rgba(255,255,255,0.1);padding:5px 15px;border-radius:15px; }' +
        '@keyframes ubarTitleShift { 0%{background-position:0% 50%} 50%{background-position:100% 50%} 100%{background-position:0% 50%} }';
    document.head.appendChild(style);

    var user = checkAuth();
    if (user) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', createUserBar);
        } else {
            createUserBar();
        }
    }

    document.addEventListener('click', function(e) {
        if (!e.target.closest('.ubar-user-menu')) {
            var menu = document.getElementById('ubarDropdownMenu');
            var arrow = document.querySelector('.ubar-arrow');
            if (menu) menu.classList.remove('show');
            if (arrow) arrow.style.transform = 'rotate(0deg)';
        }
    });

    document.addEventListener('mousemove', function() { localStorage.setItem('lastActivity', String(Date.now())); });
    document.addEventListener('keypress', function() { localStorage.setItem('lastActivity', String(Date.now())); });
    document.addEventListener('click', function() { localStorage.setItem('lastActivity', String(Date.now())); });
    document.addEventListener('scroll', function() { localStorage.setItem('lastActivity', String(Date.now())); });

    setInterval(function() {
        var lastActivity = parseInt(localStorage.getItem('lastActivity') || '0');
        if (lastActivity && Date.now() - lastActivity > 30 * 60 * 1000) {
            localStorage.removeItem('currentUser');
            localStorage.removeItem('lastActivity');
            alert('由于长时间未操作，您已被自动退出登录，请重新登录。');
            window.location.href = _basePath + 'login.html';
        }
    }, 60000);
})();
