const fs = require('fs');
const path = require('path');

var DATA_DIR = path.join(__dirname, 'kb-data');
var KNOWLEDGE_FILE = path.join(DATA_DIR, 'knowledge-data.json');
var CONFIG_FILE = path.join(DATA_DIR, 'kb-config.json');
var LOG_FILE = path.join(DATA_DIR, 'kb-update-log.json');
var VERSIONS_DIR = path.join(DATA_DIR, 'knowledge-versions');
var VERSION_HISTORY_FILE = path.join(DATA_DIR, 'kb-version-history.json');
var PENDING_FILE = path.join(DATA_DIR, 'pending-items.json');
var LLM_CONFIG_FILE = path.join(DATA_DIR, 'llm-config.json');
var UPLOAD_HISTORY_FILE = path.join(DATA_DIR, 'upload-history.json');
var UPLOADS_DIR = path.join(DATA_DIR, 'uploads');

var DEFAULT_CONFIG = {
    updateFrequency: 'weekly',
    dataSourceUrl: '',
    enabled: true,
    retryMaxCount: 3,
    lastUpdateTime: null
};

function ensureDataDir() {
    if (!fs.existsSync(DATA_DIR)) {
        fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    if (!fs.existsSync(VERSIONS_DIR)) {
        fs.mkdirSync(VERSIONS_DIR, { recursive: true });
    }
    if (!fs.existsSync(UPLOADS_DIR)) {
        fs.mkdirSync(UPLOADS_DIR, { recursive: true });
    }
}

function loadKnowledge() {
    ensureDataDir();
    try {
        if (!fs.existsSync(KNOWLEDGE_FILE)) {
            return [];
        }
        var data = fs.readFileSync(KNOWLEDGE_FILE, 'utf8');
        var parsed = JSON.parse(data);
        if (!Array.isArray(parsed)) return [];
        return parsed;
    } catch (e) {
        return [];
    }
}

function saveKnowledge(data) {
    ensureDataDir();
    if (!Array.isArray(data)) {
        throw new Error('Invalid knowledge data: expected array');
    }
    try {
        JSON.parse(JSON.stringify(data));
    } catch (e) {
        throw new Error('Invalid knowledge data: JSON serialization failed');
    }
    var tempFile = KNOWLEDGE_FILE + '.tmp';
    fs.writeFileSync(tempFile, JSON.stringify(data, null, 2), 'utf8');
    var verify = fs.readFileSync(tempFile, 'utf8');
    JSON.parse(verify);
    fs.renameSync(tempFile, KNOWLEDGE_FILE);
    return true;
}

function loadConfig() {
    ensureDataDir();
    try {
        if (!fs.existsSync(CONFIG_FILE)) {
            saveConfig(DEFAULT_CONFIG);
            return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
        }
        var data = fs.readFileSync(CONFIG_FILE, 'utf8');
        return JSON.parse(data);
    } catch (e) {
        return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
    }
}

function saveConfig(config) {
    ensureDataDir();
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), 'utf8');
    return true;
}

function appendUpdateLog(entry) {
    ensureDataDir();
    var logs = [];
    try {
        if (fs.existsSync(LOG_FILE)) {
            logs = JSON.parse(fs.readFileSync(LOG_FILE, 'utf8'));
        }
    } catch (e) {
        logs = [];
    }
    if (!Array.isArray(logs)) logs = [];
    logs.push(entry);
    if (logs.length > 200) {
        logs = logs.slice(-200);
    }
    fs.writeFileSync(LOG_FILE, JSON.stringify(logs, null, 2), 'utf8');
    return true;
}

function loadUpdateLog(page, pageSize) {
    ensureDataDir();
    page = page || 1;
    pageSize = pageSize || 20;
    try {
        if (!fs.existsSync(LOG_FILE)) return { total: 0, logs: [] };
        var logs = JSON.parse(fs.readFileSync(LOG_FILE, 'utf8'));
        if (!Array.isArray(logs)) return { total: 0, logs: [] };
        var total = logs.length;
        var start = (page - 1) * pageSize;
        var items = logs.slice().reverse().slice(start, start + pageSize);
        return { total: total, logs: items };
    } catch (e) {
        return { total: 0, logs: [] };
    }
}

function loadVersionHistory() {
    ensureDataDir();
    try {
        if (!fs.existsSync(VERSION_HISTORY_FILE)) return [];
        var data = JSON.parse(fs.readFileSync(VERSION_HISTORY_FILE, 'utf8'));
        return Array.isArray(data) ? data : [];
    } catch (e) {
        return [];
    }
}

function saveVersionHistory(history) {
    ensureDataDir();
    fs.writeFileSync(VERSION_HISTORY_FILE, JSON.stringify(history, null, 2), 'utf8');
    return true;
}

function saveVersionSnapshot(versionId, knowledgeData) {
    ensureDataDir();
    var filePath = path.join(VERSIONS_DIR, versionId + '.json');
    fs.writeFileSync(filePath, JSON.stringify(knowledgeData, null, 2), 'utf8');
    return true;
}

function loadVersionSnapshot(versionId) {
    ensureDataDir();
    var filePath = path.join(VERSIONS_DIR, versionId + '.json');
    try {
        if (!fs.existsSync(filePath)) return null;
        return JSON.parse(fs.readFileSync(filePath, 'utf8'));
    } catch (e) {
        return null;
    }
}

function deleteVersionSnapshot(versionId) {
    ensureDataDir();
    var filePath = path.join(VERSIONS_DIR, versionId + '.json');
    try {
        if (fs.existsSync(filePath)) {
            fs.unlinkSync(filePath);
        }
        return true;
    } catch (e) {
        return false;
    }
}

function backupKnowledge() {
    ensureDataDir();
    var backupFile = path.join(DATA_DIR, 'rollback-backup.json');
    try {
        if (fs.existsSync(KNOWLEDGE_FILE)) {
            fs.copyFileSync(KNOWLEDGE_FILE, backupFile);
        }
        return true;
    } catch (e) {
        return false;
    }
}

function initFromStaticData(staticData) {
    ensureDataDir();
    if (!fs.existsSync(KNOWLEDGE_FILE)) {
        saveKnowledge(staticData);
    }
    if (!fs.existsSync(CONFIG_FILE)) {
        saveConfig(DEFAULT_CONFIG);
    }
    if (!fs.existsSync(LOG_FILE)) {
        fs.writeFileSync(LOG_FILE, '[]', 'utf8');
    }
    if (!fs.existsSync(VERSION_HISTORY_FILE)) {
        fs.writeFileSync(VERSION_HISTORY_FILE, '[]', 'utf8');
    }
    if (!fs.existsSync(PENDING_FILE)) {
        fs.writeFileSync(PENDING_FILE, '[]', 'utf8');
    }
    if (!fs.existsSync(LLM_CONFIG_FILE)) {
        fs.writeFileSync(LLM_CONFIG_FILE, JSON.stringify({ providers: [] }, null, 2), 'utf8');
    }
    if (!fs.existsSync(UPLOAD_HISTORY_FILE)) {
        fs.writeFileSync(UPLOAD_HISTORY_FILE, '[]', 'utf8');
    }
}

function loadPendingItems(page, pageSize) {
    ensureDataDir();
    page = page || 1;
    pageSize = pageSize || 20;
    try {
        if (!fs.existsSync(PENDING_FILE)) return { total: 0, items: [] };
        var items = JSON.parse(fs.readFileSync(PENDING_FILE, 'utf8'));
        if (!Array.isArray(items)) return { total: 0, items: [] };
        var pendingItems = items.filter(function(item) { return item.status === 'pending'; });
        var total = pendingItems.length;
        var start = (page - 1) * pageSize;
        return { total: total, items: pendingItems.slice(start, start + pageSize) };
    } catch (e) {
        return { total: 0, items: [] };
    }
}

function savePendingItems(items) {
    ensureDataDir();
    fs.writeFileSync(PENDING_FILE, JSON.stringify(items, null, 2), 'utf8');
    return true;
}

function addPendingItem(item) {
    ensureDataDir();
    var items = [];
    try {
        if (fs.existsSync(PENDING_FILE)) {
            items = JSON.parse(fs.readFileSync(PENDING_FILE, 'utf8'));
        }
    } catch (e) { items = []; }
    if (!Array.isArray(items)) items = [];
    item.id = 'p' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);
    item.createdAt = new Date().toISOString();
    item.status = 'pending';
    items.push(item);
    fs.writeFileSync(PENDING_FILE, JSON.stringify(items, null, 2), 'utf8');
    return item;
}

function addPendingItems(itemList) {
    ensureDataDir();
    var items = [];
    try {
        if (fs.existsSync(PENDING_FILE)) {
            items = JSON.parse(fs.readFileSync(PENDING_FILE, 'utf8'));
        }
    } catch (e) { items = []; }
    if (!Array.isArray(items)) items = [];
    itemList.forEach(function(item) {
        item.id = 'p' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);
        item.createdAt = new Date().toISOString();
        item.status = 'pending';
        items.push(item);
    });
    fs.writeFileSync(PENDING_FILE, JSON.stringify(items, null, 2), 'utf8');
    return itemList.length;
}

function updatePendingItem(id, updates) {
    ensureDataDir();
    var items = [];
    try {
        if (fs.existsSync(PENDING_FILE)) {
            items = JSON.parse(fs.readFileSync(PENDING_FILE, 'utf8'));
        }
    } catch (e) { return false; }
    if (!Array.isArray(items)) return false;
    var found = false;
    items = items.map(function(item) {
        if (item.id === id) {
            found = true;
            for (var k in updates) { item[k] = updates[k]; }
            item.reviewedAt = new Date().toISOString();
        }
        return item;
    });
    if (!found) return false;
    fs.writeFileSync(PENDING_FILE, JSON.stringify(items, null, 2), 'utf8');
    return true;
}

function removePendingItems(ids) {
    ensureDataDir();
    var items = [];
    try {
        if (fs.existsSync(PENDING_FILE)) {
            items = JSON.parse(fs.readFileSync(PENDING_FILE, 'utf8'));
        }
    } catch (e) { return 0; }
    if (!Array.isArray(items)) return 0;
    var idSet = {};
    ids.forEach(function(id) { idSet[id] = true; });
    var before = items.length;
    items = items.filter(function(item) { return !idSet[item.id]; });
    fs.writeFileSync(PENDING_FILE, JSON.stringify(items, null, 2), 'utf8');
    return before - items.length;
}

function getPendingStats() {
    ensureDataDir();
    try {
        if (!fs.existsSync(PENDING_FILE)) return { pending: 0, approved: 0, rejected: 0, total: 0 };
        var items = JSON.parse(fs.readFileSync(PENDING_FILE, 'utf8'));
        if (!Array.isArray(items)) return { pending: 0, approved: 0, rejected: 0, total: 0 };
        var stats = { pending: 0, approved: 0, rejected: 0, total: items.length };
        items.forEach(function(item) {
            if (item.status === 'pending') stats.pending++;
            else if (item.status === 'approved') stats.approved++;
            else if (item.status === 'rejected') stats.rejected++;
        });
        return stats;
    } catch (e) {
        return { pending: 0, approved: 0, rejected: 0, total: 0 };
    }
}

function loadLlmConfig() {
    ensureDataDir();
    try {
        if (!fs.existsSync(LLM_CONFIG_FILE)) return { providers: [] };
        return JSON.parse(fs.readFileSync(LLM_CONFIG_FILE, 'utf8'));
    } catch (e) {
        return { providers: [] };
    }
}

function saveLlmConfig(config) {
    ensureDataDir();
    fs.writeFileSync(LLM_CONFIG_FILE, JSON.stringify(config, null, 2), 'utf8');
    return true;
}

function appendUploadHistory(entry) {
    ensureDataDir();
    var history = [];
    try {
        if (fs.existsSync(UPLOAD_HISTORY_FILE)) {
            history = JSON.parse(fs.readFileSync(UPLOAD_HISTORY_FILE, 'utf8'));
        }
    } catch (e) { history = []; }
    if (!Array.isArray(history)) history = [];
    history.push(entry);
    if (history.length > 100) history = history.slice(-100);
    fs.writeFileSync(UPLOAD_HISTORY_FILE, JSON.stringify(history, null, 2), 'utf8');
    return true;
}

function loadUploadHistory(page, pageSize) {
    ensureDataDir();
    page = page || 1;
    pageSize = pageSize || 20;
    try {
        if (!fs.existsSync(UPLOAD_HISTORY_FILE)) return { total: 0, items: [] };
        var items = JSON.parse(fs.readFileSync(UPLOAD_HISTORY_FILE, 'utf8'));
        if (!Array.isArray(items)) return { total: 0, items: [] };
        var total = items.length;
        var start = (page - 1) * pageSize;
        return { total: total, items: items.slice().reverse().slice(start, start + pageSize) };
    } catch (e) {
        return { total: 0, items: [] };
    }
}

function saveUploadedFile(filename, buffer) {
    ensureDataDir();
    var filePath = path.join(UPLOADS_DIR, filename);
    fs.writeFileSync(filePath, buffer);
    return filePath;
}

module.exports = {
    loadKnowledge: loadKnowledge,
    saveKnowledge: saveKnowledge,
    loadConfig: loadConfig,
    saveConfig: saveConfig,
    appendUpdateLog: appendUpdateLog,
    loadUpdateLog: loadUpdateLog,
    loadVersionHistory: loadVersionHistory,
    saveVersionHistory: saveVersionHistory,
    saveVersionSnapshot: saveVersionSnapshot,
    loadVersionSnapshot: loadVersionSnapshot,
    deleteVersionSnapshot: deleteVersionSnapshot,
    backupKnowledge: backupKnowledge,
    initFromStaticData: initFromStaticData,
    loadPendingItems: loadPendingItems,
    savePendingItems: savePendingItems,
    addPendingItem: addPendingItem,
    addPendingItems: addPendingItems,
    updatePendingItem: updatePendingItem,
    removePendingItems: removePendingItems,
    getPendingStats: getPendingStats,
    loadLlmConfig: loadLlmConfig,
    saveLlmConfig: saveLlmConfig,
    appendUploadHistory: appendUploadHistory,
    loadUploadHistory: loadUploadHistory,
    saveUploadedFile: saveUploadedFile,
    DATA_DIR: DATA_DIR,
    KNOWLEDGE_FILE: KNOWLEDGE_FILE,
    VERSIONS_DIR: VERSIONS_DIR,
    UPLOADS_DIR: UPLOADS_DIR
};