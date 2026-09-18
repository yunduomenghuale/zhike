var crypto = require('crypto');

var ALGORITHM = 'aes-256-cbc';
var SECRET_KEY = process.env.KB_CRYPTO_KEY || 'netlearn-companion-2026-secret-key';

function getKey() {
    return crypto.createHash('sha256').update(SECRET_KEY).digest();
}

function encrypt(text) {
    if (!text) return '';
    try {
        var key = getKey();
        var iv = crypto.randomBytes(16);
        var cipher = crypto.createCipheriv(ALGORITHM, key, iv);
        var encrypted = cipher.update(text, 'utf8', 'hex');
        encrypted += cipher.final('hex');
        return iv.toString('hex') + ':' + encrypted;
    } catch (e) {
        return '';
    }
}

function decrypt(encryptedText) {
    if (!encryptedText) return '';
    try {
        var key = getKey();
        var parts = encryptedText.split(':');
        if (parts.length !== 2) return '';
        var iv = Buffer.from(parts[0], 'hex');
        var encrypted = parts[1];
        var decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
        var decrypted = decipher.update(encrypted, 'hex', 'utf8');
        decrypted += decipher.final('utf8');
        return decrypted;
    } catch (e) {
        return '';
    }
}

function maskApiKey(apiKey) {
    if (!apiKey || apiKey.length < 8) return '****';
    return apiKey.substring(0, 4) + '****' + apiKey.substring(apiKey.length - 4);
}

module.exports = {
    encrypt: encrypt,
    decrypt: decrypt,
    maskApiKey: maskApiKey
};