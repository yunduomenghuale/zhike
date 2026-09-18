var fs = require('fs');
var path = require('path');
var dataStore = require('./kb-data-store');
var pdfParse;
try { pdfParse = require('pdf-parse'); } catch(e) { pdfParse = null; }

var MAX_FILE_SIZE = 10 * 1024 * 1024;
var ALLOWED_EXTENSIONS = ['.txt', '.md', '.pdf'];

function parseUploadRequest(req) {
    return new Promise(function(resolve, reject) {
        var chunks = [];
        var totalSize = 0;
        var boundary = extractBoundary(req.headers['content-type']);
        if (!boundary) {
            reject(new Error('Invalid multipart request: boundary not found'));
            return;
        }

        req.on('data', function(chunk) {
            totalSize += chunk.length;
            if (totalSize > MAX_FILE_SIZE + 1024 * 1024) {
                reject(new Error('File size exceeds 10MB limit'));
                return;
            }
            chunks.push(chunk);
        });

        req.on('end', function() {
            try {
                var buffer = Buffer.concat(chunks);
                var parts = parseMultipart(buffer, boundary);
                resolve(parts);
            } catch (e) {
                reject(e);
            }
        });

        req.on('error', function(e) { reject(e); });
    });
}

function extractBoundary(contentType) {
    if (!contentType) return null;
    var match = contentType.match(/boundary=(.+)/);
    return match ? match[1].replace(/"/g, '') : null;
}

function parseMultipart(buffer, boundary) {
    var boundaryStr = '--' + boundary;
    var boundaryBuf = Buffer.from(boundaryStr);
    var parts = [];
    var start = 0;

    while (true) {
        var idx = buffer.indexOf(boundaryBuf, start);
        if (idx === -1) break;
        if (start > 0) {
            var partData = buffer.slice(start, idx - 2);
            var parsed = parsePart(partData);
            if (parsed) parts.push(parsed);
        }
        start = idx + boundaryBuf.length + 2;
    }

    return parts;
}

function parsePart(partBuffer) {
    var headerEndIdx = partBuffer.indexOf('\r\n\r\n');
    if (headerEndIdx === -1) return null;

    var headerStr = partBuffer.slice(0, headerEndIdx).toString('utf8');
    var bodyBuffer = partBuffer.slice(headerEndIdx + 4);
    if (bodyBuffer.length >= 2 && bodyBuffer[bodyBuffer.length - 2] === 0x0D && bodyBuffer[bodyBuffer.length - 1] === 0x0A) {
        bodyBuffer = bodyBuffer.slice(0, -2);
    }

    var nameMatch = headerStr.match(/name="([^"]+)"/);
    var filenameMatch = headerStr.match(/filename="([^"]+)"/);
    var name = nameMatch ? nameMatch[1] : '';
    var filename = filenameMatch ? filenameMatch[1] : '';

    if (filename) {
        var ext = path.extname(filename).toLowerCase();
        if (ALLOWED_EXTENSIONS.indexOf(ext) === -1) {
            return { name: name, filename: filename, error: 'Unsupported file type: ' + ext };
        }
        return { name: name, filename: filename, data: bodyBuffer, ext: ext };
    }

    return { name: name, value: bodyBuffer.toString('utf8') };
}

function parseTxtContent(content) {
    var items = [];
    var lines = content.split(/\r?\n/);
    var currentQ = null;
    var currentA = null;

    lines.forEach(function(line) {
        var qMatch = line.match(/^Q[：:]\s*(.+)/i) || line.match(/^问题[：:]\s*(.+)/) || line.match(/^【(.+?)】$/);
        var aMatch = line.match(/^A[：:]\s*([\s\S]*)/i) || line.match(/^答案[：:]\s*([\s\S]*)/);

        if (qMatch) {
            if (currentQ && currentA) {
                items.push({ q: currentQ.trim(), a: currentA.trim() });
            }
            currentQ = qMatch[1];
            currentA = null;
        } else if (aMatch && currentQ) {
            currentA = aMatch[1];
        } else if (currentQ && currentA !== null) {
            currentA += '\n' + line;
        } else if (currentQ && currentA === null) {
            currentA = line;
        }
    });

    if (currentQ && currentA) {
        items.push({ q: currentQ.trim(), a: currentA.trim() });
    }

    return items;
}

function parseMdContent(content) {
    var items = [];
    var lines = content.split(/\r?\n/);
    var currentQ = null;
    var currentALines = [];

    lines.forEach(function(line) {
        var headingMatch = line.match(/^#{1,3}\s+(.+)/);
        var qaMatch = line.match(/^\*\*Q[：:]\s*(.+?)\*\*/);

        if (headingMatch || qaMatch) {
            if (currentQ && currentALines.length > 0) {
                items.push({ q: currentQ.trim(), a: currentALines.join('\n').trim() });
            }
            currentQ = qaMatch ? qaMatch[1] : headingMatch[1];
            currentALines = [];
        } else if (currentQ) {
            currentALines.push(line);
        }
    });

    if (currentQ && currentALines.length > 0) {
        items.push({ q: currentQ.trim(), a: currentALines.join('\n').trim() });
    }

    if (items.length === 0) {
        return parseTxtContent(content);
    }

    return items;
}

function parseFile(filename, buffer) {
    var ext = path.extname(filename).toLowerCase();

    if (ext === '.pdf') {
        if (!pdfParse) {
            return Promise.resolve([{ q: path.basename(filename, ext), a: '[PDF解析模块未安装，请手动编辑补充]', source: 'upload', pendingEdit: true }]);
        }
        return pdfParse(buffer).then(function(data) {
            var text = data.text || '';
            if (text.trim().length < 10) {
                return [{ q: path.basename(filename, ext), a: '[PDF文档内容无法提取文本，请手动编辑补充]', source: 'upload', pendingEdit: true }];
            }
            return parseTxtContent(text);
        }).catch(function(err) {
            return [{ q: path.basename(filename, ext), a: '[PDF解析失败：' + err.message + ']', source: 'upload', pendingEdit: true }];
        });
    }

    var content;
    try {
        content = buffer.toString('utf8');
    } catch (e) {
        throw new Error('Failed to read file content as UTF-8');
    }

    if (ext === '.md') {
        return Promise.resolve(parseMdContent(content));
    }

    return Promise.resolve(parseTxtContent(content));
}

function sanitizeItems(items) {
    var valid = [];
    var invalid = 0;
    items.forEach(function(item) {
        if (!item.q || typeof item.q !== 'string' || item.q.trim().length < 2) { invalid++; return; }
        if (!item.a || typeof item.a !== 'string' || item.a.trim().length < 2) { invalid++; return; }
        if (item.q.indexOf('<script') >= 0 || item.a.indexOf('<script') >= 0) { invalid++; return; }
        valid.push({
            q: item.q.trim(),
            a: item.a.trim(),
            tags: item.tags || [],
            source: item.source || 'upload',
            pendingEdit: item.pendingEdit || false
        });
    });
    return { valid: valid, invalid: invalid };
}

function handleUpload(req, category) {
    return parseUploadRequest(req).then(function(parts) {
        var filePart = null;
        var categoryOverride = category;

        parts.forEach(function(p) {
            if (p.filename && p.data) filePart = p;
            if (p.name === 'category' && p.value) categoryOverride = p.value;
        });

        if (!filePart) throw new Error('No file found in upload');
        if (filePart.error) throw new Error(filePart.error);
        if (filePart.data.length > MAX_FILE_SIZE) throw new Error('File size exceeds 10MB limit');

        var savedPath = dataStore.saveUploadedFile(Date.now() + '_' + filePart.filename, filePart.data);
        return Promise.resolve(parseFile(filePart.filename, filePart.data)).then(function(rawItems) {
            var result = sanitizeItems(rawItems);

            var pendingItems = result.valid.map(function(item) {
                return {
                    q: item.q,
                    a: item.a,
                    tags: item.tags,
                    source: 'upload',
                    category: categoryOverride || '未分类',
                    pendingEdit: item.pendingEdit || false,
                    uploadedFile: filePart.filename
                };
            });

            var addedCount = dataStore.addPendingItems(pendingItems);

            dataStore.appendUploadHistory({
                timestamp: new Date().toISOString(),
                filename: filePart.filename,
                fileSize: filePart.data.length,
                category: categoryOverride || '未分类',
                totalParsed: rawItems.length,
                validItems: result.valid.length,
                invalidItems: result.invalid,
                addedToPending: addedCount
            });

            return {
                filename: filePart.filename,
                totalParsed: rawItems.length,
                validItems: result.valid.length,
                invalidItems: result.invalid,
                addedToPending: addedCount
            };
        });
    });
}

module.exports = {
    handleUpload: handleUpload,
    parseUploadRequest: parseUploadRequest,
    parseFile: parseFile,
    parseTxtContent: parseTxtContent,
    parseMdContent: parseMdContent
};