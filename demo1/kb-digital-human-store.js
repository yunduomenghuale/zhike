var fs = require('fs');
var path = require('path');

var DATA_DIR = path.join(__dirname, 'kb-data');
var VIDEOS_DIR = path.join(DATA_DIR, 'digital-human-videos');
var META_FILE = path.join(DATA_DIR, 'digital-human-meta.json');

function ensureDir() {
    if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
    if (!fs.existsSync(VIDEOS_DIR)) fs.mkdirSync(VIDEOS_DIR, { recursive: true });
}

function loadMeta() {
    ensureDir();
    try {
        if (!fs.existsSync(META_FILE)) return [];
        var data = JSON.parse(fs.readFileSync(META_FILE, 'utf8'));
        return Array.isArray(data) ? data : [];
    } catch (e) {
        return [];
    }
}

function saveMeta(list) {
    ensureDir();
    fs.writeFileSync(META_FILE, JSON.stringify(list, null, 2), 'utf8');
}

function addVideo(filename, originalName, description, fileSize) {
    var list = loadMeta();
    var item = {
        id: 'dh_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
        filename: filename,
        originalName: originalName,
        description: description || '',
        fileSize: fileSize,
        createdAt: new Date().toISOString()
    };
    list.push(item);
    saveMeta(list);
    return item;
}

function listVideos(page, pageSize) {
    var list = loadMeta();
    page = page || 1;
    pageSize = pageSize || 20;
    var total = list.length;
    var start = (page - 1) * pageSize;
    return { total: total, items: list.slice(start, start + pageSize) };
}

function deleteVideo(id) {
    var list = loadMeta();
    var idx = list.findIndex(function(v) { return v.id === id; });
    if (idx < 0) return { success: false, message: 'Video not found' };
    var video = list[idx];
    var filePath = path.join(VIDEOS_DIR, video.filename);
    try {
        if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
    } catch (e) {}
    list.splice(idx, 1);
    saveMeta(list);
    return { success: true, message: 'Video deleted' };
}

function getVideoPath(filename) {
    return path.join(VIDEOS_DIR, filename);
}

module.exports = {
    addVideo: addVideo,
    listVideos: listVideos,
    deleteVideo: deleteVideo,
    getVideoPath: getVideoPath,
    VIDEOS_DIR: VIDEOS_DIR
};