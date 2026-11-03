var dataStore = require('./kb-data-store');
var updater = require('./kb-updater');
var versionManager = require('./kb-version-manager');
var uploadHandler = require('./kb-upload-handler');
var llmClient = require('./kb-llm-client');
var reviewManager = require('./kb-review-manager');
var dhStore = require('./kb-digital-human-store');

function handleRequest(req, res, urlPath, method, body) {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (method === 'OPTIONS') {
        res.writeHead(200);
        res.end();
        return;
    }

    var route = matchRoute(method, urlPath);
    if (!route) {
        sendJson(res, 404, { error: 'NOT_FOUND', message: 'API endpoint not found' });
        return;
    }

    try {
        route.handler(req, res, body);
    } catch (e) {
        sendJson(res, 500, { error: 'INTERNAL_ERROR', message: e.message });
    }
}

function matchRoute(method, urlPath) {
    var routes = [
        { method: 'GET', pattern: '^/api/knowledge$', handler: getKnowledge },
        { method: 'POST', pattern: '^/api/kb/manage/update$', handler: triggerUpdate },
        { method: 'GET', pattern: '^/api/kb/manage/status$', handler: getStatus },
        { method: 'GET', pattern: '^/api/kb/manage/log$', handler: getUpdateLog },
        { method: 'GET', pattern: '^/api/kb/version/list$', handler: getVersionList },
        { method: 'POST', pattern: '^/api/kb/version/rollback$', handler: rollbackVersion },
        { method: 'GET', pattern: '^/api/kb/config$', handler: getConfig },
        { method: 'PUT', pattern: '^/api/kb/config$', handler: updateConfig },
        { method: 'POST', pattern: '^/api/kb/upload$', handler: uploadFile },
        { method: 'GET', pattern: '^/api/kb/upload/history$', handler: getUploadHistory },
        { method: 'GET', pattern: '^/api/kb/llm/providers$', handler: getLlmProviders },
        { method: 'PUT', pattern: '^/api/kb/llm/providers/[^/]+$', handler: saveLlmProvider },
        { method: 'POST', pattern: '^/api/kb/llm/generate$', handler: llmGenerate },
        { method: 'POST', pattern: '^/api/kb/llm/test/[^/]+$', handler: testLlmConnection },
        { method: 'GET', pattern: '^/api/kb/pending$', handler: getPendingItems },
        { method: 'POST', pattern: '^/api/kb/pending/approve$', handler: approvePending },
        { method: 'POST', pattern: '^/api/kb/pending/reject$', handler: rejectPending },
        { method: 'PUT', pattern: '^/api/kb/pending/[^/]+$', handler: editPending },
        { method: 'GET', pattern: '^/api/kb/pending/stats$', handler: getPendingStats },
        { method: 'POST', pattern: '^/api/kb/digital-human/upload$', handler: uploadDigitalHuman },
        { method: 'GET', pattern: '^/api/kb/digital-human/list$', handler: listDigitalHuman },
        { method: 'DELETE', pattern: '^/api/kb/digital-human/[^/]+$', handler: deleteDigitalHuman },
        { method: 'GET', pattern: '^/api/kb/digital-human/video/[^/]+$', handler: serveDigitalHumanVideo }
    ];

    for (var i = 0; i < routes.length; i++) {
        if (routes[i].method === method && new RegExp(routes[i].pattern).test(urlPath)) {
            return routes[i];
        }
    }
    return null;
}

function getKnowledge(req, res) {
    var knowledge = dataStore.loadKnowledge();
    if (knowledge.length === 0) {
        sendJson(res, 200, { categories: [], source: 'empty' });
        return;
    }
    sendJson(res, 200, { categories: knowledge, source: 'api' });
}

function triggerUpdate(req, res, body) {
    if (updater.isUpdating()) {
        sendJson(res, 409, { error: 'UPDATE_IN_PROGRESS', message: 'An update is already in progress' });
        return;
    }
    updater.triggerManualUpdate().then(function(result) {
        sendJson(res, 200, result);
    }).catch(function(err) {
        sendJson(res, 500, { error: 'UPDATE_FAILED', message: err.message });
    });
}

function getStatus(req, res) {
    var status = updater.getStatus();
    sendJson(res, 200, status);
}

function getUpdateLog(req, res) {
    var urlObj = new URL(req.url, 'http://localhost');
    var page = parseInt(urlObj.searchParams.get('page')) || 1;
    var pageSize = parseInt(urlObj.searchParams.get('pageSize')) || 20;
    var result = dataStore.loadUpdateLog(page, pageSize);
    sendJson(res, 200, result);
}

function getVersionList(req, res) {
    var urlObj = new URL(req.url, 'http://localhost');
    var page = parseInt(urlObj.searchParams.get('page')) || 1;
    var pageSize = parseInt(urlObj.searchParams.get('pageSize')) || 20;
    var result = versionManager.listVersions(page, pageSize);
    sendJson(res, 200, result);
}

function rollbackVersion(req, res, body) {
    if (!body || !body.targetVersion) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'targetVersion is required' });
        return;
    }
    var result = versionManager.rollback(body.targetVersion);
    if (result.success) {
        sendJson(res, 200, result);
    } else {
        sendJson(res, 500, { error: 'ROLLBACK_FAILED', message: result.message });
    }
}

function getConfig(req, res) {
    var config = dataStore.loadConfig();
    sendJson(res, 200, config);
}

function updateConfig(req, res, body) {
    if (!body) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'Request body is required' });
        return;
    }

    var config = dataStore.loadConfig();

    if (body.updateFrequency && ['daily', 'weekly', 'monthly'].indexOf(body.updateFrequency) >= 0) {
        config.updateFrequency = body.updateFrequency;
    }
    if (body.dataSourceUrl !== undefined) {
        config.dataSourceUrl = body.dataSourceUrl;
    }
    if (body.enabled !== undefined) {
        config.enabled = !!body.enabled;
    }
    if (body.retryMaxCount !== undefined) {
        var count = parseInt(body.retryMaxCount);
        if (count >= 1 && count <= 5) {
            config.retryMaxCount = count;
        }
    }

    dataStore.saveConfig(config);
    updater.stopScheduler();
    if (config.enabled) {
        updater.startScheduler();
    }

    sendJson(res, 200, config);
}

function sendJson(res, statusCode, data) {
    res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(data));
}

function uploadFile(req, res) {
    uploadHandler.handleUpload(req).then(function(result) {
        sendJson(res, 200, result);
    }).catch(function(err) {
        sendJson(res, 400, { error: 'UPLOAD_FAILED', message: err.message });
    });
}

function getUploadHistory(req, res) {
    var urlObj = new URL(req.url, 'http://localhost');
    var page = parseInt(urlObj.searchParams.get('page')) || 1;
    var pageSize = parseInt(urlObj.searchParams.get('pageSize')) || 20;
    var result = dataStore.loadUploadHistory(page, pageSize);
    sendJson(res, 200, result);
}

function getLlmProviders(req, res) {
    var providers = llmClient.getAvailableProviders();
    sendJson(res, 200, { providers: providers });
}

function saveLlmProvider(req, res, body) {
    var urlParts = req.url.split('/');
    var providerId = urlParts[urlParts.length - 1];
    if (!body) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'Request body is required' });
        return;
    }
    try {
        var result = llmClient.saveProviderConfig(providerId, body);
        sendJson(res, 200, result);
    } catch (e) {
        sendJson(res, 400, { error: 'SAVE_FAILED', message: e.message });
    }
}

function llmGenerate(req, res, body) {
    if (!body || !body.provider || !body.topic) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'provider and topic are required' });
        return;
    }
    llmClient.generateKnowledge(body.provider, body.topic, body.category, body.prompt).then(function(result) {
        sendJson(res, 200, result);
    }).catch(function(err) {
        sendJson(res, 500, { error: 'GENERATE_FAILED', message: err.message });
    });
}

function testLlmConnection(req, res) {
    var urlParts = req.url.split('/');
    var providerId = urlParts[urlParts.length - 1];
    llmClient.testConnection(providerId).then(function(result) {
        sendJson(res, 200, result);
    }).catch(function(err) {
        sendJson(res, 500, { error: 'TEST_FAILED', message: err.message });
    });
}

function getPendingItems(req, res) {
    var urlObj = new URL(req.url, 'http://localhost');
    var page = parseInt(urlObj.searchParams.get('page')) || 1;
    var pageSize = parseInt(urlObj.searchParams.get('pageSize')) || 20;
    var result = reviewManager.listPending(page, pageSize);
    sendJson(res, 200, result);
}

function approvePending(req, res, body) {
    if (!body) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'Request body is required' });
        return;
    }
    if (body.ids && Array.isArray(body.ids)) {
        var result = reviewManager.approveItems(body.ids);
        sendJson(res, 200, result);
    } else if (body.id) {
        var result = reviewManager.approveItem(body.id, body.edits);
        if (result.success) sendJson(res, 200, result);
        else sendJson(res, 400, result);
    } else {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'id or ids is required' });
    }
}

function rejectPending(req, res, body) {
    if (!body) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'Request body is required' });
        return;
    }
    if (body.ids && Array.isArray(body.ids)) {
        var result = reviewManager.rejectItems(body.ids);
        sendJson(res, 200, result);
    } else if (body.id) {
        var result = reviewManager.rejectItem(body.id);
        if (result.success) sendJson(res, 200, result);
        else sendJson(res, 400, result);
    } else {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'id or ids is required' });
    }
}

function editPending(req, res, body) {
    var urlParts = req.url.split('/');
    var id = urlParts[urlParts.length - 1];
    if (!body) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'Request body is required' });
        return;
    }
    var result = reviewManager.editPendingItem(id, body);
    if (result.success) sendJson(res, 200, result);
    else sendJson(res, 400, result);
}

function getPendingStats(req, res) {
    var stats = reviewManager.getStats();
    sendJson(res, 200, stats);
}

function uploadDigitalHuman(req, res) {
    var contentType = req.headers['content-type'] || '';
    if (contentType.indexOf('multipart/form-data') < 0) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'Multipart form data required' });
        return;
    }
    var boundaryMatch = contentType.match(/boundary=(.+)/);
    if (!boundaryMatch) {
        sendJson(res, 400, { error: 'BAD_REQUEST', message: 'Boundary not found' });
        return;
    }
    var boundary = boundaryMatch[1].replace(/"/g, '');
    var chunks = [];
    var totalSize = 0;
    req.on('data', function(chunk) {
        totalSize += chunk.length;
        if (totalSize > 500 * 1024 * 1024) {
            sendJson(res, 400, { error: 'TOO_LARGE', message: 'File size exceeds 500MB limit' });
            return;
        }
        chunks.push(chunk);
    });
    req.on('end', function() {
        try {
            var buffer = Buffer.concat(chunks);
            var boundaryBuf = Buffer.from('--' + boundary);
            var parts = [];
            var start = 0;
            while (true) {
                var idx = buffer.indexOf(boundaryBuf, start);
                if (idx === -1) break;
                if (start > 0) {
                    var partData = buffer.slice(start, idx - 2);
                    var headerEndIdx = partData.indexOf('\r\n\r\n');
                    if (headerEndIdx !== -1) {
                        var headerStr = partData.slice(0, headerEndIdx).toString('utf8');
                        var bodyBuffer = partData.slice(headerEndIdx + 4);
                        if (bodyBuffer.length >= 2 && bodyBuffer[bodyBuffer.length - 2] === 0x0D && bodyBuffer[bodyBuffer.length - 1] === 0x0A) {
                            bodyBuffer = bodyBuffer.slice(0, -2);
                        }
                        var nameMatch = headerStr.match(/name="([^"]+)"/);
                        var filenameMatch = headerStr.match(/filename="([^"]+)"/);
                        var pName = nameMatch ? nameMatch[1] : '';
                        var pFilename = filenameMatch ? filenameMatch[1] : '';
                        if (pFilename) {
                            parts.push({ name: pName, filename: pFilename, data: bodyBuffer });
                        } else {
                            parts.push({ name: pName, value: bodyBuffer.toString('utf8') });
                        }
                    }
                }
                start = idx + boundaryBuf.length + 2;
            }

            var filePart = null;
            var description = '';
            parts.forEach(function(p) {
                if (p.filename && p.data) filePart = p;
                if (p.name === 'description' && p.value) description = p.value;
            });

            if (!filePart) {
                sendJson(res, 400, { error: 'NO_FILE', message: 'No video file provided' });
                return;
            }
            var allowedExts = ['.mp4', '.webm', '.ogg', '.mov', '.avi'];
            var ext = require('path').extname(filePart.filename).toLowerCase();
            if (allowedExts.indexOf(ext) < 0) {
                sendJson(res, 400, { error: 'INVALID_TYPE', message: 'Unsupported video format. Allowed: ' + allowedExts.join(', ') });
                return;
            }
            var savedName = Date.now() + '_' + filePart.filename;
            var savedPath = require('path').join(dhStore.VIDEOS_DIR, savedName);
            require('fs').writeFileSync(savedPath, filePart.data);

            var item = dhStore.addVideo(savedName, filePart.filename, description, filePart.data.length);
            sendJson(res, 200, { success: true, video: item });
        } catch (e) {
            sendJson(res, 400, { error: 'UPLOAD_FAILED', message: e.message });
        }
    });
    req.on('error', function(e) {
        sendJson(res, 400, { error: 'UPLOAD_FAILED', message: e.message });
    });
}

function listDigitalHuman(req, res) {
    var urlObj = new URL(req.url, 'http://localhost');
    var page = parseInt(urlObj.searchParams.get('page')) || 1;
    var pageSize = parseInt(urlObj.searchParams.get('pageSize')) || 20;
    var result = dhStore.listVideos(page, pageSize);
    sendJson(res, 200, result);
}

function deleteDigitalHuman(req, res) {
    var urlParts = req.url.split('/');
    var id = urlParts[urlParts.length - 1];
    var result = dhStore.deleteVideo(id);
    if (result.success) sendJson(res, 200, result);
    else sendJson(res, 400, result);
}

function serveDigitalHumanVideo(req, res) {
    var urlParts = req.url.split('/');
    var filename = decodeURIComponent(urlParts[urlParts.length - 1]);
    var filePath = dhStore.getVideoPath(filename);
    if (!require('fs').existsSync(filePath)) {
        res.writeHead(404);
        res.end('Not found');
        return;
    }
    var stat = require('fs').statSync(filePath);
    var ext = require('path').extname(filename).toLowerCase();
    var mimeMap = { '.mp4': 'video/mp4', '.webm': 'video/webm', '.ogg': 'video/ogg', '.mov': 'video/quicktime', '.avi': 'video/x-msvideo' };
    res.writeHead(200, {
        'Content-Type': mimeMap[ext] || 'video/mp4',
        'Content-Length': stat.size,
        'Accept-Ranges': 'bytes',
        'Access-Control-Allow-Origin': '*'
    });
    require('fs').createReadStream(filePath).pipe(res);
}

module.exports = { handleRequest: handleRequest };