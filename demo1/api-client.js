var ApiClient = (function() {
    var API_BASE = '';
    if (typeof window !== 'undefined' && window.location) {
        if (window.location.protocol === 'file:') {
            API_BASE = 'http://localhost:8090';
        } else {
            API_BASE = '';
        }
    }

    var MAX_RETRIES = 3;
    var RETRY_DELAY = 1000;
    var TIMEOUT = 15000;

    function sleep(ms) {
        return new Promise(function(resolve) { setTimeout(resolve, ms); });
    }

    function fetchWithTimeout(url, options, timeout) {
        return new Promise(function(resolve, reject) {
            var controller = null;
            if (typeof AbortController !== 'undefined') {
                controller = new AbortController();
                options = options || {};
                options.signal = controller.signal;
            }

            var timer = setTimeout(function() {
                if (controller) controller.abort();
                reject(new Error('请求超时'));
            }, timeout || TIMEOUT);

            fetch(url, options).then(function(response) {
                clearTimeout(timer);
                resolve(response);
            }).catch(function(err) {
                clearTimeout(timer);
                reject(err);
            });
        });
    }

    function getAuthToken() {
        try { return localStorage.getItem('authToken') || ''; } catch(e) { return ''; }
    }

    function buildHeaders(customHeaders) {
        var headers = { 'Content-Type': 'application/json' };
        var token = getAuthToken();
        if (token) headers['Authorization'] = 'Bearer ' + token;
        if (customHeaders) {
            Object.keys(customHeaders).forEach(function(k) {
                headers[k] = customHeaders[k];
            });
        }
        return headers;
    }

    async function request(method, url, data, options) {
        options = options || {};
        var retries = options.retries !== undefined ? options.retries : MAX_RETRIES;
        var retryDelay = options.retryDelay || RETRY_DELAY;
        var timeout = options.timeout || TIMEOUT;
        var suppressError = options.suppressError || false;

        var fullUrl = API_BASE + url;
        var fetchOptions = { method: method, headers: buildHeaders(options.headers) };

        if (data && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
            fetchOptions.body = JSON.stringify(data);
        }

        var lastError = null;

        for (var attempt = 0; attempt <= retries; attempt++) {
            try {
                var response = await fetchWithTimeout(fullUrl, fetchOptions, timeout);

                if (response.status === 502 || response.status === 503 || response.status === 504) {
                    lastError = new Error('服务器暂时不可用(HTTP ' + response.status + ')');
                    if (attempt < retries) {
                        if (!suppressError) showTransientError('服务器正在重启，请稍候...');
                        await sleep(retryDelay * (attempt + 1));
                        continue;
                    }
                }

                var result;
                try {
                    result = await response.json();
                } catch(e) {
                    lastError = new Error('响应解析失败');
                    if (attempt < retries) {
                        await sleep(retryDelay);
                        continue;
                    }
                    throw lastError;
                }

                if (!response.ok) {
                    var errMsg = result.error || result.message || ('请求失败(HTTP ' + response.status + ')');
                    if (!suppressError) showTransientError(errMsg);
                    return { success: false, error: errMsg, status: response.status, data: result };
                }

                hideTransientError();
                return { success: true, data: result, status: response.status };

            } catch(err) {
                lastError = err;
                if (attempt < retries) {
                    if (!suppressError && attempt === 0) showTransientError('网络连接中，自动重试...');
                    await sleep(retryDelay * (attempt + 1));
                }
            }
        }

        if (!suppressError) showPersistentError('网络错误：无法连接服务器。请确认服务已启动。');
        return { success: false, error: lastError ? lastError.message : '网络错误', status: 0 };
    }

    var transientTimer = null;

    function showTransientError(msg) {
        var el = getOrCreateErrorBanner();
        el.className = 'api-error-banner transient';
        el.textContent = msg;
        el.style.display = 'block';
        if (transientTimer) clearTimeout(transientTimer);
        transientTimer = setTimeout(function() {
            if (el.className.indexOf('transient') >= 0) el.style.display = 'none';
        }, 3000);
    }

    function showPersistentError(msg) {
        var el = getOrCreateErrorBanner();
        el.className = 'api-error-banner persistent';
        el.textContent = msg;
        el.style.display = 'block';
    }

    function hideTransientError() {
        var el = document.getElementById('api-error-banner');
        if (el && el.className.indexOf('transient') >= 0) {
            el.style.display = 'none';
        }
    }

    function getOrCreateErrorBanner() {
        var el = document.getElementById('api-error-banner');
        if (!el) {
            el = document.createElement('div');
            el.id = 'api-error-banner';
            el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px 20px;text-align:center;font-size:14px;color:#fff;background:#e74c3c;box-shadow:0 2px 8px rgba(0,0,0,0.3);display:none;transition:opacity 0.3s;';
            if (document.body) {
                document.body.appendChild(el);
            } else {
                document.addEventListener('DOMContentLoaded', function() {
                    document.body.appendChild(el);
                });
            }
        }
        return el;
    }

    return {
        get: function(url, options) { return request('GET', url, null, options); },
        post: function(url, data, options) { return request('POST', url, data, options); },
        put: function(url, data, options) { return request('PUT', url, data, options); },
        delete: function(url, options) { return request('DELETE', url, null, options); },
        patch: function(url, data, options) { return request('PATCH', url, data, options); },
        API_BASE: API_BASE,
        request: request
    };
})();

if (typeof window !== 'undefined') {
    window.ApiClient = ApiClient;
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ApiClient;
}