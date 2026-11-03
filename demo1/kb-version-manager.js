var dataStore = require('./kb-data-store');

function createVersion(knowledgeData, updateResult) {
    var history = dataStore.loadVersionHistory();
    var versionNum = history.length + 1;
    var versionId = 'v' + versionNum;

    var record = {
        versionId: versionId,
        updateTime: new Date().toISOString(),
        addedCount: updateResult.addedCount || 0,
        updatedCount: updateResult.updatedCount || 0,
        failedCount: updateResult.failedCount || 0,
        summary: updateResult.summary || '',
        status: updateResult.status || 'success'
    };

    dataStore.saveVersionSnapshot(versionId, knowledgeData);
    history.push(record);
    dataStore.saveVersionHistory(history);

    cleanupOldVersions(history);

    return record;
}

function listVersions(page, pageSize) {
    var history = dataStore.loadVersionHistory();
    page = page || 1;
    pageSize = pageSize || 20;
    var total = history.length;
    var start = (page - 1) * pageSize;
    var items = history.slice().reverse().slice(start, start + pageSize);
    return { total: total, versions: items };
}

function getVersion(versionId) {
    var history = dataStore.loadVersionHistory();
    var record = history.find(function(v) { return v.versionId === versionId; });
    if (!record) return null;

    var snapshotData = dataStore.loadVersionSnapshot(versionId);
    if (!snapshotData) return null;

    return { record: record, data: snapshotData };
}

function rollback(targetVersionId) {
    var target = getVersion(targetVersionId);
    if (!target) {
        return { success: false, message: 'Target version not found or snapshot corrupted' };
    }

    var currentData = dataStore.loadKnowledge();
    dataStore.backupKnowledge();

    try {
        dataStore.saveKnowledge(target.data);

        var history = dataStore.loadVersionHistory();
        var rollbackRecord = {
            versionId: 'v' + (history.length + 1),
            updateTime: new Date().toISOString(),
            addedCount: 0,
            updatedCount: 0,
            failedCount: 0,
            summary: 'Rollback to ' + targetVersionId,
            status: 'success'
        };
        dataStore.saveVersionSnapshot(rollbackRecord.versionId, target.data);
        history.push(rollbackRecord);
        dataStore.saveVersionHistory(history);

        return { success: true, record: rollbackRecord };
    } catch (e) {
        try {
            var backupFile = require('path').join(dataStore.DATA_DIR, 'rollback-backup.json');
            var fs = require('fs');
            if (fs.existsSync(backupFile)) {
                var backupData = JSON.parse(fs.readFileSync(backupFile, 'utf8'));
                dataStore.saveKnowledge(backupData);
            }
        } catch (restoreErr) {
            // keep current state if restore fails
        }
        return { success: false, message: 'Rollback failed: ' + e.message };
    }
}

function cleanupOldVersions(history) {
    var MAX_VERSIONS = 50;
    if (history.length <= MAX_VERSIONS) return;

    var toDelete = history.slice(0, history.length - MAX_VERSIONS);
    toDelete.forEach(function(v) {
        dataStore.deleteVersionSnapshot(v.versionId);
    });

    var remaining = history.slice(history.length - MAX_VERSIONS);
    dataStore.saveVersionHistory(remaining);
}

module.exports = {
    createVersion: createVersion,
    listVersions: listVersions,
    getVersion: getVersion,
    rollback: rollback
};