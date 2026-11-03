(function() {
    var API_BASE = '';

    function apiGet(url, callback) {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', API_BASE + url, true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 502 || xhr.status === 503) { callback(null, '服务未启动，请联系管理员'); return; }
                if (xhr.status === 200) {
                    try { callback(JSON.parse(xhr.responseText)); } catch (e) { callback(null); }
                }
            }
        };
        xhr.send();
    }

    function apiPost(url, body, callback) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API_BASE + url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 502 || xhr.status === 503) { callback({ error: 'SERVICE_DOWN', message: '服务未启动，请联系管理员' }, xhr.status); return; }
                try { callback(JSON.parse(xhr.responseText), xhr.status); } catch (e) { callback(null, xhr.status); }
            }
        };
        xhr.send(JSON.stringify(body));
    }

    function apiPut(url, body, callback) {
        var xhr = new XMLHttpRequest();
        xhr.open('PUT', API_BASE + url, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4 && xhr.status === 200) {
                try { callback(JSON.parse(xhr.responseText)); } catch (e) { callback(null); }
            }
        };
        xhr.send(JSON.stringify(body));
    }

    window.loadKbStatus = function() {
        apiGet('/api/kb/manage/status', function(data) {
            if (!data) return;
            var el = document.getElementById('kb-status');
            if (!el) return;
            el.innerHTML =
                '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px;margin-bottom:20px;">' +
                '<div style="background:linear-gradient(135deg,#4a90e2,#357abd);padding:15px;border-radius:10px;color:white;text-align:center;">' +
                '<div style="font-size:24px;font-weight:bold;">' + escapeHtml(data.currentVersion || 'v0') + '</div>' +
                '<div style="font-size:12px;opacity:0.9;">当前版本</div></div>' +
                '<div style="background:linear-gradient(135deg,#2ecc71,#27ae60);padding:15px;border-radius:10px;color:white;text-align:center;">' +
                '<div style="font-size:24px;font-weight:bold;">' + (data.totalCategories || 0) + '</div>' +
                '<div style="font-size:12px;opacity:0.9;">知识分类</div></div>' +
                '<div style="background:linear-gradient(135deg,#e67e22,#d35400);padding:15px;border-radius:10px;color:white;text-align:center;">' +
                '<div style="font-size:24px;font-weight:bold;">' + (data.totalItems || 0) + '</div>' +
                '<div style="font-size:12px;opacity:0.9;">知识条目</div></div>' +
                '<div style="background:linear-gradient(135deg,#9b59b6,#8e44ad);padding:15px;border-radius:10px;color:white;text-align:center;">' +
                '<div style="font-size:24px;font-weight:bold;">' + (data.autoUpdateEnabled ? '已启用' : '已禁用') + '</div>' +
                '<div style="font-size:12px;opacity:0.9;">自动更新</div></div>' +
                '</div>' +
                '<div style="color:#666;font-size:13px;">最近更新：' + (data.lastUpdateTime ? new Date(data.lastUpdateTime).toLocaleString() : '暂无') + ' | 更新频率：' + ({ daily: '每天', weekly: '每周', monthly: '每月' }[data.updateFrequency] || data.updateFrequency) + '</div>';
        });
    };

    window.triggerKbUpdate = function() {
        var btn = document.getElementById('kb-update-btn');
        if (btn) { btn.disabled = true; btn.textContent = '更新中...'; }
        apiPost('/api/kb/manage/update', {}, function(data, status) {
            if (btn) { btn.disabled = false; btn.textContent = '立即更新'; }
            if (status === 409) {
                alert('更新正在进行中，请稍后再试');
                return;
            }
            if (data) {
                if (data.status === 'success' || data.status === 'partial') {
                    alert('更新完成：' + (data.result ? data.result.summary : '成功'));
                } else if (data.status === 'not_modified') {
                    alert('知识库已是最新，无需更新');
                } else {
                    alert('更新结果：' + (data.message || JSON.stringify(data)));
                }
            } else {
                alert('更新请求失败');
            }
            loadKbStatus();
            loadKbUpdateLog();
        });
    };

    window.loadKbUpdateLog = function(page) {
        page = page || 1;
        apiGet('/api/kb/manage/log?page=' + page + '&pageSize=10', function(data) {
            if (!data) return;
            var el = document.getElementById('kb-update-log');
            if (!el) return;
            if (!data.logs || data.logs.length === 0) {
                el.innerHTML = '<div style="text-align:center;color:#999;padding:30px;">暂无更新日志</div>';
                return;
            }
            var html = '<table style="width:100%;border-collapse:collapse;"><thead><tr>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">时间</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">类型</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">状态</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">详情</th>' +
                '</tr></thead><tbody>';
            data.logs.forEach(function(log) {
                var statusColor = log.status === 'success' ? '#2ecc71' : log.status === 'failed' ? '#e74c3c' : '#f39c12';
                html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
                    '<td style="padding:8px;">' + (log.timestamp ? new Date(log.timestamp).toLocaleString() : '-') + '</td>' +
                    '<td style="padding:8px;">' + ({ auto: '自动', manual: '手动' }[log.type] || log.type) + '</td>' +
                    '<td style="padding:8px;color:' + statusColor + ';">' + escapeHtml(log.status) + '</td>' +
                    '<td style="padding:8px;font-size:12px;">' + escapeHtml(log.details || '-') + '</td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
            if (data.total > 10) {
                var totalPages = Math.ceil(data.total / 10);
                html += '<div style="text-align:center;margin-top:10px;">';
                for (var i = 1; i <= Math.min(totalPages, 5); i++) {
                    html += '<button onclick="loadKbUpdateLog(' + i + ')" style="margin:2px;padding:4px 10px;' + (i === page ? 'background:#4a90e2;color:white;' : '') + '">' + i + '</button>';
                }
                html += '</div>';
            }
            el.innerHTML = html;
        });
    };

    window.loadKbVersionList = function(page) {
        page = page || 1;
        apiGet('/api/kb/version/list?page=' + page + '&pageSize=10', function(data) {
            if (!data) return;
            var el = document.getElementById('kb-version-list');
            if (!el) return;
            if (!data.versions || data.versions.length === 0) {
                el.innerHTML = '<div style="text-align:center;color:#999;padding:30px;">暂无版本记录</div>';
                return;
            }
            var html = '<table style="width:100%;border-collapse:collapse;"><thead><tr>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">版本</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">更新时间</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">新增</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">更新</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">状态</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">操作</th>' +
                '</tr></thead><tbody>';
            data.versions.forEach(function(v) {
                var statusColor = v.status === 'success' ? '#2ecc71' : v.status === 'failed' ? '#e74c3c' : '#f39c12';
                html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
                    '<td style="padding:8px;">' + escapeHtml(v.versionId) + '</td>' +
                    '<td style="padding:8px;">' + (v.updateTime ? new Date(v.updateTime).toLocaleString() : '-') + '</td>' +
                    '<td style="padding:8px;">' + (v.addedCount || 0) + '</td>' +
                    '<td style="padding:8px;">' + (v.updatedCount || 0) + '</td>' +
                    '<td style="padding:8px;color:' + statusColor + ';">' + escapeHtml(v.status) + '</td>' +
                    '<td style="padding:8px;"><button onclick="rollbackKbVersion(\'' + escapeHtml(v.versionId) + '\')" style="padding:4px 10px;background:#e67e22;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;">回滚</button></td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;
        });
    };

    window.rollbackKbVersion = function(targetVersion) {
        if (!confirm('确定要回滚到版本 ' + targetVersion + ' 吗？当前知识库将被替换。')) return;
        apiPost('/api/kb/version/rollback', { targetVersion: targetVersion }, function(data, status) {
            if (data && data.success) {
                alert('回滚成功，已恢复到版本 ' + targetVersion);
                loadKbStatus();
                loadKbVersionList();
            } else {
                alert('回滚失败：' + (data && data.message ? data.message : '未知错误'));
            }
        });
    };

    window.loadKbConfig = function() {
        apiGet('/api/kb/config', function(data) {
            if (!data) return;
            var el = document.getElementById('kb-config-form');
            if (!el) return;
            el.innerHTML =
                '<div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;">' +
                '<div><label style="display:block;margin-bottom:5px;font-weight:bold;">数据源地址</label>' +
                '<input type="text" id="kb-datasource-url" value="' + escapeHtml(data.dataSourceUrl || '') + '" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;" placeholder="http://example.com/api/knowledge"></div>' +
                '<div><label style="display:block;margin-bottom:5px;font-weight:bold;">更新频率</label>' +
                '<select id="kb-update-frequency" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;">' +
                '<option value="daily"' + (data.updateFrequency === 'daily' ? ' selected' : '') + '>每天</option>' +
                '<option value="weekly"' + (data.updateFrequency === 'weekly' ? ' selected' : '') + '>每周</option>' +
                '<option value="monthly"' + (data.updateFrequency === 'monthly' ? ' selected' : '') + '>每月</option>' +
                '</select></div>' +
                '<div><label style="display:block;margin-bottom:5px;font-weight:bold;">启用自动更新</label>' +
                '<select id="kb-auto-enabled" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;">' +
                '<option value="true"' + (data.enabled ? ' selected' : '') + '>启用</option>' +
                '<option value="false"' + (!data.enabled ? ' selected' : '') + '>禁用</option>' +
                '</select></div>' +
                '<div><label style="display:block;margin-bottom:5px;font-weight:bold;">最大重试次数</label>' +
                '<input type="number" id="kb-retry-count" value="' + (data.retryMaxCount || 3) + '" min="1" max="5" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;"></div>' +
                '</div>' +
                '<div style="margin-top:15px;text-align:right;"><button onclick="saveKbConfig()" style="padding:8px 20px;background:#4a90e2;color:white;border:none;border-radius:4px;cursor:pointer;">保存配置</button></div>';
        });
    };

    window.saveKbConfig = function() {
        var config = {
            dataSourceUrl: document.getElementById('kb-datasource-url').value.trim(),
            updateFrequency: document.getElementById('kb-update-frequency').value,
            enabled: document.getElementById('kb-auto-enabled').value === 'true',
            retryMaxCount: parseInt(document.getElementById('kb-retry-count').value) || 3
        };
        apiPut('/api/kb/config', config, function(data) {
            if (data) {
                alert('配置已保存');
                loadKbStatus();
            } else {
                alert('保存配置失败');
            }
        });
    };

    function escapeHtml(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    window.initKbAdmin = function() {
        loadKbStatus();
        loadKbUpdateLog();
        loadKbVersionList();
        loadKbConfig();
        loadPendingItems();
        loadLlmProviders();
        loadUploadHistory();
        loadDigitalHumanVideos();
    };

    window.uploadKbFile = function() {
        var fileInput = document.getElementById('kb-upload-file');
        var categoryInput = document.getElementById('kb-upload-category');
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) { alert('请选择文件'); return; }
        var file = fileInput.files[0];
        var category = categoryInput ? categoryInput.value.trim() : '';
        var formData = new FormData();
        formData.append('file', file);
        if (category) formData.append('category', category);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API_BASE + '/api/kb/upload', true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                try {
                    var result = JSON.parse(xhr.responseText);
                    if (xhr.status === 200) {
                        alert('上传成功！解析' + result.totalParsed + '条，有效' + result.validItems + '条，待审核' + result.addedToPending + '条');
                        fileInput.value = '';
                        loadPendingItems();
                        loadUploadHistory();
                        loadKbStatus();
                    } else {
                        alert('上传失败：' + (result.message || '未知错误'));
                    }
                } catch (e) { alert('上传失败：' + (e.message || '解析响应失败') + ' (HTTP ' + xhr.status + ')'); }
            }
        };
        xhr.send(formData);
    };

    window.loadPendingItems = function(page) {
        page = page || 1;
        apiGet('/api/kb/pending?page=' + page + '&pageSize=10', function(data) {
            if (!data) return;
            var el = document.getElementById('kb-pending-list');
            if (!el) return;
            if (!data.items || data.items.length === 0) {
                el.innerHTML = '<div style="text-align:center;color:#999;padding:30px;">暂无待审核条目</div>';
                return;
            }
            var html = '<table style="width:100%;border-collapse:collapse;"><thead><tr>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">问题</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">分类</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">来源</th>' +
                '<th style="padding:8px;text-align:left;border-bottom:1px solid #e0e0e0;background:#4a90e2;color:white;">操作</th>' +
                '</tr></thead><tbody>';
            data.items.forEach(function(item) {
                if (item.status !== 'pending') return;
                var sourceLabel = item.source === 'llm' ? '大模型' : item.source === 'upload' ? '文档上传' : item.source;
                html += '<tr style="border-bottom:1px solid #f0f0f0;">' +
                    '<td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(item.q) + '">' + escapeHtml(item.q) + '</td>' +
                    '<td style="padding:8px;">' + escapeHtml(item.category) + '</td>' +
                    '<td style="padding:8px;">' + sourceLabel + '</td>' +
                    '<td style="padding:8px;"><button onclick="approvePendingItem(\'' + item.id + '\')" style="padding:4px 10px;background:#2ecc71;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;margin-right:4px;">通过</button>' +
                    '<button onclick="rejectPendingItem(\'' + item.id + '\')" style="padding:4px 10px;background:#e74c3c;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;">拒绝</button></td>' +
                    '</tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;
        });
    };

    window.approvePendingItem = function(id) {
        apiPost('/api/kb/pending/approve', { id: id }, function(data) {
            if (data && data.success) {
                alert('审核通过');
                loadPendingItems();
                loadKbStatus();
            } else {
                alert('审核失败：' + (data ? data.message : '未知错误'));
            }
        });
    };

    window.rejectPendingItem = function(id) {
        if (!confirm('确定拒绝此条目？')) return;
        apiPost('/api/kb/pending/reject', { id: id }, function(data) {
            if (data && data.success) {
                loadPendingItems();
            } else {
                alert('操作失败');
            }
        });
    };

    window.loadLlmProviders = function() {
        apiGet('/api/kb/llm/providers', function(data) {
            if (!data) return;
            var el = document.getElementById('kb-llm-config');
            if (!el) return;
            var html = '';
            data.providers.forEach(function(p) {
                html += '<div style="background:#f8f9fa;border-radius:8px;padding:15px;margin-bottom:15px;border:1px solid #e0e0e0;">' +
                    '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">' +
                    '<h4 style="margin:0;color:#333;">' + escapeHtml(p.name) + '</h4>' +
                    '<span style="padding:4px 10px;border-radius:4px;font-size:12px;color:white;background:' + (p.configured ? '#2ecc71' : '#e74c3c') + ';">' + (p.configured ? '已配置' : '未配置') + '</span></div>' +
                    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">' +
                    '<div><label style="font-size:12px;color:#666;">API Key</label><input type="password" id="llm-key-' + p.id + '" placeholder="输入API密钥" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;font-size:13px;"></div>' +
                    '<div><label style="font-size:12px;color:#666;">模型</label><select id="llm-model-' + p.id + '" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;font-size:13px;">';
                p.models.forEach(function(m) {
                    html += '<option value="' + m + '"' + (m === p.model ? ' selected' : '') + '>' + m + '</option>';
                });
                html += '</select></div></div>' +
                    '<div style="margin-top:10px;text-align:right;">' +
                    '<button onclick="saveLlmProviderConfig(\'' + p.id + '\')" style="padding:6px 15px;background:#4a90e2;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;margin-right:5px;">保存</button>' +
                    '<button onclick="testLlmConnection(\'' + p.id + '\')" style="padding:6px 15px;background:#f39c12;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;">测试连接</button></div></div>';
            });
            el.innerHTML = html;
        });
    };

    window.saveLlmProviderConfig = function(providerId) {
        var keyInput = document.getElementById('llm-key-' + providerId);
        var modelSelect = document.getElementById('llm-model-' + providerId);
        var body = { model: modelSelect.value };
        if (keyInput.value.trim()) body.apiKey = keyInput.value.trim();
        apiPut('/api/kb/llm/providers/' + providerId, body, function(data) {
            if (data) {
                alert('配置已保存');
                loadLlmProviders();
            } else {
                alert('保存失败');
            }
        });
    };

    window.testLlmConnection = function(providerId) {
        apiPost('/api/kb/llm/test/' + providerId, {}, function(data) {
            if (data && data.success) alert('连接成功！');
            else alert('连接失败：' + (data ? data.error : '未知错误'));
        });
    };

    window.llmGenerate = function() {
        var provider = document.getElementById('llm-gen-provider');
        var topic = document.getElementById('llm-gen-topic');
        var category = document.getElementById('llm-gen-category');
        if (!provider || !topic || !topic.value.trim()) { alert('请填写主题'); return; }
        var body = { provider: provider.value, topic: topic.value.trim(), category: category ? category.value.trim() : '' };
        var btn = document.getElementById('llm-gen-btn');
        if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }
        apiPost('/api/kb/llm/generate', body, function(data) {
            if (btn) { btn.disabled = false; btn.textContent = '生成知识'; }
            if (data && data.generatedItems) {
                alert('生成完成！' + data.generatedItems + '条已加入待审核，Token消耗：' + (data.tokens ? data.tokens.total : 0));
                loadPendingItems();
                loadKbStatus();
            } else {
                alert('生成失败：' + (data ? data.message || JSON.stringify(data) : '未知错误'));
            }
        });
    };

    window.loadUploadHistory = function(page) {
        page = page || 1;
        apiGet('/api/kb/upload/history?page=' + page + '&pageSize=5', function(data) {
            if (!data) return;
            var el = document.getElementById('kb-upload-history');
            if (!el) return;
            if (!data.items || data.items.length === 0) {
                el.innerHTML = '<div style="text-align:center;color:#999;padding:15px;">暂无上传记录</div>';
                return;
            }
            var html = '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead><tr>' +
                '<th style="padding:6px;text-align:left;border-bottom:1px solid #e0e0e0;">时间</th>' +
                '<th style="padding:6px;text-align:left;border-bottom:1px solid #e0e0e0;">文件名</th>' +
                '<th style="padding:6px;text-align:left;border-bottom:1px solid #e0e0e0;">有效/总数</th>' +
                '<th style="padding:6px;text-align:left;border-bottom:1px solid #e0e0e0;">待审核</th>' +
                '</tr></thead><tbody>';
            data.items.forEach(function(item) {
                html += '<tr><td style="padding:6px;">' + new Date(item.timestamp).toLocaleString() + '</td>' +
                    '<td style="padding:6px;">' + escapeHtml(item.filename) + '</td>' +
                    '<td style="padding:6px;">' + item.validItems + '/' + item.totalParsed + '</td>' +
                    '<td style="padding:6px;">' + item.addedToPending + '</td></tr>';
            });
            html += '</tbody></table>';
            el.innerHTML = html;
        });
    };

    window.uploadDigitalHumanVideo = function() {
        var fileInput = document.getElementById('dh-video-file');
        var descInput = document.getElementById('dh-video-desc');
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) { alert('请选择视频文件'); return; }
        var file = fileInput.files[0];
        var description = descInput ? descInput.value.trim() : '';
        var formData = new FormData();
        formData.append('file', file);
        if (description) formData.append('description', description);
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API_BASE + '/api/kb/digital-human/upload', true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 502 || xhr.status === 503) { alert('服务未启动，请联系管理员'); return; }
                try {
                    var result = JSON.parse(xhr.responseText);
                    if (xhr.status === 200 && result.success) {
                        alert('上传成功！');
                        fileInput.value = '';
                        if (descInput) descInput.value = '';
                        loadDigitalHumanVideos();
                    } else {
                        alert('上传失败：' + (result.message || '未知错误'));
                    }
                } catch (e) { alert('上传失败：' + (e.message || '') + ' (HTTP ' + xhr.status + ')'); }
            }
        };
        xhr.send(formData);
    };

    window.deleteDigitalHumanVideo = function(id) {
        if (!confirm('确定要删除该视频吗？删除后不可恢复。')) return;
        var xhr = new XMLHttpRequest();
        xhr.open('DELETE', API_BASE + '/api/kb/digital-human/' + id, true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                try {
                    var result = JSON.parse(xhr.responseText);
                    if (result.success) { alert('删除成功'); loadDigitalHumanVideos(); }
                    else alert('删除失败：' + (result.message || ''));
                } catch (e) { alert('删除失败'); }
            }
        };
        xhr.send();
    };

    window.loadDigitalHumanVideos = function() {
        var el = document.getElementById('dh-video-list');
        if (!el) return;
        apiGet('/api/kb/digital-human/list?page=1&pageSize=50', function(data) {
            if (!data || !data.items || data.items.length === 0) {
                el.innerHTML = '<div style="text-align:center;color:#999;padding:30px;">暂无视频，请上传</div>';
                return;
            }
            var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:15px;margin-top:15px;">';
            data.items.forEach(function(item) {
                var sizeMB = (item.fileSize / 1024 / 1024).toFixed(1);
                var date = new Date(item.createdAt).toLocaleString();
                html += '<div style="border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;">' +
                    '<video src="' + API_BASE + '/api/kb/digital-human/video/' + encodeURIComponent(item.filename) + '" controls style="width:100%;max-height:200px;background:#000;"></video>' +
                    '<div style="padding:10px;">' +
                    '<div style="font-weight:bold;font-size:13px;margin-bottom:4px;">' + escapeHtml(item.originalName) + '</div>' +
                    (item.description ? '<div style="font-size:12px;color:#666;margin-bottom:6px;line-height:1.5;">' + escapeHtml(item.description) + '</div>' : '') +
                    '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                    '<span style="font-size:11px;color:#999;">' + date + ' · ' + sizeMB + 'MB</span>' +
                    '<button onclick="deleteDigitalHumanVideo(\'' + item.id + '\')" style="padding:4px 10px;background:#e74c3c;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;">删除</button>' +
                    '</div></div></div>';
            });
            html += '</div>';
            el.innerHTML = html;
        });
    };
})();