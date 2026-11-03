var dataStore = require('./kb-data-store');
var versionManager = require('./kb-version-manager');

function listPending(page, pageSize) {
    return dataStore.loadPendingItems(page, pageSize);
}

function approveItem(id, edits) {
    var result = dataStore.loadPendingItems(1, 9999);
    var allItems = [];
    try {
        var fs = require('fs');
        var path = require('path');
        var pendingFile = path.join(dataStore.DATA_DIR, 'pending-items.json');
        allItems = JSON.parse(fs.readFileSync(pendingFile, 'utf8'));
    } catch (e) { return { success: false, message: 'Failed to load pending items' }; }

    var target = allItems.find(function(item) { return item.id === id; });
    if (!target) return { success: false, message: 'Item not found' };
    if (target.status !== 'pending') return { success: false, message: 'Item is not in pending status' };

    var q = edits && edits.q ? edits.q : target.q;
    var a = edits && edits.a ? edits.a : target.a;
    var category = edits && edits.category ? edits.category : target.category;
    var tags = edits && edits.tags ? edits.tags : (target.tags || []);

    var knowledge = dataStore.loadKnowledge();
    var catObj = knowledge.find(function(c) { return c.category === category; });
    if (!catObj) {
        catObj = { category: category, items: [] };
        knowledge.push(catObj);
    }

    var duplicate = catObj.items.find(function(item) { return item.q === q; });
    if (duplicate) {
        return { success: false, message: 'Duplicate question found in category: ' + category, duplicate: true };
    }

    var newItem = { q: q, a: a };
    if (tags.length > 0) newItem.tags = tags;
    if (target.source) newItem.source = target.source;
    if (target.llmProvider) newItem.llmProvider = target.llmProvider;
    if (target.llmModel) newItem.llmModel = target.llmModel;
    catObj.items.push(newItem);

    dataStore.saveKnowledge(knowledge);
    versionManager.createVersion(knowledge, {
        addedCount: 1,
        updatedCount: 0,
        failedCount: 0,
        summary: 'Approved pending item: ' + q.substring(0, 30),
        status: 'success'
    });

    dataStore.updatePendingItem(id, { status: 'approved', reviewedQ: q, reviewedA: a, reviewedCategory: category });

    return { success: true, message: 'Item approved and added to knowledge base' };
}

function approveItems(ids) {
    var results = { approved: 0, failed: 0, errors: [] };
    ids.forEach(function(id) {
        var result = approveItem(id);
        if (result.success) {
            results.approved++;
        } else {
            results.failed++;
            results.errors.push({ id: id, message: result.message });
        }
    });
    return results;
}

function rejectItem(id) {
    var updated = dataStore.updatePendingItem(id, { status: 'rejected' });
    if (!updated) return { success: false, message: 'Item not found' };
    return { success: true, message: 'Item rejected' };
}

function rejectItems(ids) {
    var results = { rejected: 0, failed: 0 };
    ids.forEach(function(id) {
        var result = rejectItem(id);
        if (result.success) results.rejected++;
        else results.failed++;
    });
    return results;
}

function editPendingItem(id, edits) {
    var updated = dataStore.updatePendingItem(id, edits);
    if (!updated) return { success: false, message: 'Item not found' };
    return { success: true, message: 'Item updated' };
}

function cleanupExpired(maxAgeDays) {
    maxAgeDays = maxAgeDays || 30;
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - maxAgeDays);

    var fs = require('fs');
    var path = require('path');
    var pendingFile = path.join(dataStore.DATA_DIR, 'pending-items.json');
    var allItems = [];
    try {
        allItems = JSON.parse(fs.readFileSync(pendingFile, 'utf8'));
    } catch (e) { return { cleaned: 0 }; }

    var before = allItems.length;
    allItems = allItems.filter(function(item) {
        if (item.status !== 'pending') return true;
        var created = new Date(item.createdAt);
        return created >= cutoff;
    });
    var cleaned = before - allItems.length;

    if (cleaned > 0) {
        dataStore.savePendingItems(allItems);
    }

    return { cleaned: cleaned };
}

function getStats() {
    return dataStore.getPendingStats();
}

module.exports = {
    listPending: listPending,
    approveItem: approveItem,
    approveItems: approveItems,
    rejectItem: rejectItem,
    rejectItems: rejectItems,
    editPendingItem: editPendingItem,
    cleanupExpired: cleanupExpired,
    getStats: getStats
};