var http = require('http');
var https = require('https');
var dataStore = require('./kb-data-store');
var versionManager = require('./kb-version-manager');

var isUpdating = false;
var schedulerTimer = null;
var retryCount = 0;
var RETRY_DELAYS = [60000, 180000, 300000];

function startScheduler() {
    stopScheduler();
    var config = dataStore.loadConfig();
    if (!config.enabled) return;

    var intervals = { daily: 86400000, weekly: 604800000, monthly: 2592000000 };
    var interval = intervals[config.updateFrequency] || intervals.weekly;

    schedulerTimer = setInterval(function() {
        checkAndFetch();
    }, interval);

    console.log('[KB-Updater] Scheduler started, frequency: ' + config.updateFrequency);
}

function stopScheduler() {
    if (schedulerTimer) {
        clearInterval(schedulerTimer);
        schedulerTimer = null;
    }
    console.log('[KB-Updater] Scheduler stopped');
}

function checkAndFetch() {
    if (isUpdating) {
        console.log('[KB-Updater] Update already in progress, skipping');
        return Promise.resolve({ status: 'in_progress', message: 'Update already in progress' });
    }

    isUpdating = true;
    var startTime = Date.now();
    var config = dataStore.loadConfig();

    if (!config.dataSourceUrl) {
        isUpdating = false;
        return Promise.resolve({ status: 'skipped', message: 'No data source URL configured' });
    }

    return fetchFromDataSource(config.dataSourceUrl, config.lastUpdateTime)
        .then(function(rawData) {
            retryCount = 0;
            return processUpdate(rawData, startTime, config);
        })
        .catch(function(err) {
            return handleFetchError(err, startTime, config);
        });
}

function fetchFromDataSource(url, lastUpdateTime) {
    return new Promise(function(resolve, reject) {
        var client = url.startsWith('https') ? https : http;
        var urlObj = new URL(url);
        var options = {
            hostname: urlObj.hostname,
            port: urlObj.port,
            path: urlObj.pathname + urlObj.search,
            method: 'GET',
            headers: { 'Content-Type': 'application/json' },
            timeout: 30000
        };

        if (lastUpdateTime) {
            options.headers['If-Modified-Since'] = new Date(lastUpdateTime).toUTCString();
        }

        var req = client.request(options, function(res) {
            var body = '';
            res.on('data', function(chunk) { body += chunk; });
            res.on('end', function() {
                if (res.statusCode === 304) {
                    reject(new Error('NOT_MODIFIED'));
                } else if (res.statusCode >= 200 && res.statusCode < 300) {
                    try {
                        var data = JSON.parse(body);
                        resolve(data);
                    } catch (e) {
                        reject(new Error('Invalid JSON response from data source'));
                    }
                } else {
                    reject(new Error('Data source returned status ' + res.statusCode));
                }
            });
        });

        req.on('error', function(e) { reject(e); });
        req.on('timeout', function() { req.destroy(); reject(new Error('Data source request timeout')); });
        req.end();
    });
}

function processUpdate(rawData, startTime, config) {
    var parseResult = parseAndValidate(rawData);
    var currentData = dataStore.loadKnowledge();

    if (currentData.length === 0 && Array.isArray(rawData) && rawData.length > 0) {
        currentData = rawData;
        var versionResult = { addedCount: rawData.length, updatedCount: 0, failedCount: 0, summary: 'Initial data load', status: 'success' };
    } else {
        var mergeResult = mergeKnowledge(currentData, parseResult.valid, parseResult.invalid);
        currentData = mergeResult.data;
        var versionResult = {
            addedCount: mergeResult.addedCount,
            updatedCount: mergeResult.updatedCount,
            failedCount: parseResult.invalid.length,
            summary: 'Added ' + mergeResult.addedCount + ', updated ' + mergeResult.updatedCount + ', failed ' + parseResult.invalid.length,
            status: parseResult.invalid.length > 0 ? (mergeResult.addedCount > 0 ? 'partial' : 'failed') : 'success'
        };
    }

    dataStore.saveKnowledge(currentData);
    versionManager.createVersion(currentData, versionResult);

    config.lastUpdateTime = new Date().toISOString();
    dataStore.saveConfig(config);

    var elapsed = Date.now() - startTime;
    dataStore.appendUpdateLog({
        timestamp: new Date().toISOString(),
        type: 'auto',
        status: versionResult.status,
        details: versionResult.summary,
        dataSourceUrl: config.dataSourceUrl,
        duration: elapsed,
        addedCount: versionResult.addedCount,
        updatedCount: versionResult.updatedCount,
        failedCount: versionResult.failedCount
    });

    isUpdating = false;
    return { status: versionResult.status, result: versionResult };
}

function handleFetchError(err, startTime, config) {
    var maxRetry = config.retryMaxCount || 3;
    var logEntry = {
        timestamp: new Date().toISOString(),
        type: 'auto',
        status: 'failed',
        details: err.message,
        dataSourceUrl: config.dataSourceUrl,
        duration: Date.now() - startTime,
        retryAttempt: retryCount + 1
    };

    if (err.message === 'NOT_MODIFIED') {
        logEntry.status = 'not_modified';
        logEntry.details = 'No new data available';
        dataStore.appendUpdateLog(logEntry);
        isUpdating = false;
        return { status: 'not_modified', message: 'No new data available' };
    }

    if (retryCount < maxRetry - 1) {
        retryCount++;
        var delay = RETRY_DELAYS[Math.min(retryCount - 1, RETRY_DELAYS.length - 1)];
        logEntry.details += ' (retry ' + retryCount + '/' + maxRetry + ', next in ' + (delay / 1000) + 's)';
        dataStore.appendUpdateLog(logEntry);

        setTimeout(function() {
            checkAndFetch();
        }, delay);

        isUpdating = false;
        return { status: 'retrying', message: 'Retry ' + retryCount + '/' + maxRetry, nextRetryIn: delay };
    }

    retryCount = 0;
    logEntry.details += ' (all retries exhausted)';
    dataStore.appendUpdateLog(logEntry);
    isUpdating = false;
    return { status: 'failed', message: 'Data source unreachable after ' + maxRetry + ' retries: ' + err.message };
}

function parseAndValidate(rawData) {
    var valid = [];
    var invalid = [];

    if (!rawData || !Array.isArray(rawData)) {
        return { valid: [], invalid: [{ error: 'Root data is not an array' }] };
    }

    rawData.forEach(function(category) {
        if (!category || !category.category || typeof category.category !== 'string') {
            invalid.push({ error: 'Missing or invalid category name', data: category });
            return;
        }
        if (!Array.isArray(category.items)) {
            invalid.push({ error: 'Missing or invalid items array for category: ' + category.category, data: category });
            return;
        }

        var validItems = [];
        category.items.forEach(function(item) {
            if (!item || !item.q || typeof item.q !== 'string' || !item.a || typeof item.a !== 'string') {
                invalid.push({ error: 'Missing q or a field in category: ' + category.category, data: item });
                return;
            }
            if (item.a.indexOf('<script') >= 0 || item.q.indexOf('<script') >= 0) {
                invalid.push({ error: 'Malicious content detected in category: ' + category.category, data: item });
                return;
            }
            validItems.push(item);
        });

        if (validItems.length > 0) {
            valid.push({
                category: category.category,
                items: validItems
            });
        }
    });

    return { valid: valid, invalid: invalid };
}

function mergeKnowledge(currentData, incrementalData, invalidItems) {
    var addedCount = 0;
    var updatedCount = 0;

    incrementalData.forEach(function(newCat) {
        var existingCat = currentData.find(function(c) { return c.category === newCat.category; });
        if (!existingCat) {
            var catCopy = { category: newCat.category, items: newCat.items.map(function(item) {
                var copy = { q: item.q, a: item.a };
                if (item.tags) copy.tags = item.tags;
                if (item.source) copy.source = item.source;
                if (item.year) copy.year = item.year;
                if (item.track) copy.track = item.track;
                if (item.pendingDelete) copy.pendingDelete = item.pendingDelete;
                return copy;
            })};
            currentData.push(catCopy);
            addedCount += newCat.items.length;
        } else {
            newCat.items.forEach(function(newItem) {
                if (newItem.pendingDelete) {
                    return;
                }
                var existingItem = existingCat.items.find(function(i) { return i.q === newItem.q; });
                if (!existingItem) {
                    var copy = { q: newItem.q, a: newItem.a };
                    if (newItem.tags) copy.tags = newItem.tags;
                    if (newItem.source) copy.source = newItem.source;
                    if (newItem.year) copy.year = newItem.year;
                    if (newItem.track) copy.track = newItem.track;
                    existingCat.items.push(copy);
                    addedCount++;
                } else {
                    if (existingItem.a !== newItem.a) {
                        existingItem.a = newItem.a;
                        if (newItem.tags) existingItem.tags = newItem.tags;
                        if (newItem.source) existingItem.source = newItem.source;
                        if (newItem.year) existingItem.year = newItem.year;
                        if (newItem.track) existingItem.track = newItem.track;
                        updatedCount++;
                    }
                }
            });
        }
    });

    return { data: currentData, addedCount: addedCount, updatedCount: updatedCount };
}

function triggerManualUpdate() {
    if (isUpdating) {
        return Promise.resolve({ status: 'conflict', message: 'Update already in progress' });
    }
    return checkAndFetch().then(function(result) {
        if (result.status !== 'in_progress') {
            var logEntry = {
                timestamp: new Date().toISOString(),
                type: 'manual',
                status: result.status,
                details: result.message || result.result && result.result.summary || ''
            };
            dataStore.appendUpdateLog(logEntry);
        }
        return result;
    });
}

function getStatus() {
    var config = dataStore.loadConfig();
    var knowledge = dataStore.loadKnowledge();
    var versionHistory = dataStore.loadVersionHistory();
    var totalItems = 0;
    knowledge.forEach(function(cat) {
        totalItems += cat.items.length;
    });

    return {
        currentVersion: versionHistory.length > 0 ? versionHistory[versionHistory.length - 1].versionId : 'v0',
        lastUpdateTime: config.lastUpdateTime,
        totalCategories: knowledge.length,
        totalItems: totalItems,
        isUpdating: isUpdating,
        autoUpdateEnabled: config.enabled,
        updateFrequency: config.updateFrequency
    };
}

module.exports = {
    startScheduler: startScheduler,
    stopScheduler: stopScheduler,
    checkAndFetch: checkAndFetch,
    triggerManualUpdate: triggerManualUpdate,
    getStatus: getStatus,
    isUpdating: function() { return isUpdating; }
};