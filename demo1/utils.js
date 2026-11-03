// 密码加密工具
const CryptoUtils = {
    // 使用SHA-256加密密码
    async hashPassword(password) {
        const encoder = new TextEncoder();
        const data = encoder.encode(password);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
        return hashHex;
    },

    // 验证密码
    async verifyPassword(inputPassword, storedHash) {
        if (!storedHash) return false;
        const inputHash = await this.hashPassword(inputPassword);
        return inputHash === storedHash;
    },

    // 简单加密（用于验证码等临时数据）
    encrypt(data) {
        return btoa(encodeURIComponent(JSON.stringify(data)));
    },

    // 简单解密
    decrypt(encrypted) {
        try {
            return JSON.parse(decodeURIComponent(atob(encrypted)));
        } catch (e) {
            return null;
        }
    }
};

// 数据备份工具
const BackupUtils = {
    dbName: 'NetworkTeachingSystem',
    version: 1,

    // 初始化IndexedDB
    async initDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.version);
            
            request.onerror = () => reject(request.error);
            
            request.onsuccess = () => resolve(request.result);
            
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('backups')) {
                    db.createObjectStore('backups', { keyPath: 'id' });
                }
            };
        });
    },

    // 备份数据
    async backup() {
        try {
            const data = {
                id: 'latest',
                systemUsers: localStorage.getItem('systemUsers'),
                teachers: localStorage.getItem('teachers'),
                students: localStorage.getItem('students'),
                classes: localStorage.getItem('classes'),
                timestamp: new Date().toISOString()
            };

            // 同时保存学习记录
            const studyData = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key.startsWith('study-detail-') || key.startsWith('learn-count-')) {
                    studyData[key] = localStorage.getItem(key);
                }
            }
            data.studyData = studyData;

            const db = await this.initDB();
            const transaction = db.transaction(['backups'], 'readwrite');
            const store = transaction.objectStore('backups');
            
            return new Promise((resolve, reject) => {
                const request = store.put(data);
                request.onsuccess = () => {
                    console.log('✅ 数据备份成功', new Date().toLocaleString());
                    resolve(true);
                };
                request.onerror = () => reject(request.error);
            });
        } catch (error) {
            console.error('❌ 数据备份失败:', error);
            return false;
        }
    },

    // 恢复数据
    async restore() {
        try {
            const db = await this.initDB();
            const transaction = db.transaction(['backups'], 'readonly');
            const store = transaction.objectStore('backups');
            
            return new Promise((resolve, reject) => {
                const request = store.get('latest');
                request.onsuccess = () => {
                    const data = request.result;
                    if (!data) {
                        resolve(false);
                        return;
                    }

                    // 恢复数据
                    if (data.systemUsers) localStorage.setItem('systemUsers', data.systemUsers);
                    if (data.teachers) localStorage.setItem('teachers', data.teachers);
                    if (data.students) localStorage.setItem('students', data.students);
                    if (data.classes) localStorage.setItem('classes', data.classes);
                    
                    // 恢复学习记录
                    if (data.studyData) {
                        for (let key in data.studyData) {
                            localStorage.setItem(key, data.studyData[key]);
                        }
                    }

                    console.log('✅ 数据恢复成功');
                    resolve(true);
                };
                request.onerror = () => reject(request.error);
            });
        } catch (error) {
            console.error('❌ 数据恢复失败:', error);
            return false;
        }
    }
};

// 数据验证工具
const ValidationUtils = {
    // 验证学号格式（7位数字）
    validateStudentId(id) {
        return /^\d{7}$/.test(id);
    },

    // 验证教师工号（字母+数字组合）
    validateTeacherId(id) {
        return /^[A-Za-z0-9]{4,20}$/.test(id);
    },

    // 验证姓名
    validateName(name) {
        return name && name.trim().length >= 2 && name.trim().length <= 20;
    },

    // 验证电话
    validatePhone(phone) {
        if (!phone) return true; // 选填
        return /^1[3-9]\d{9}$/.test(phone);
    },

    // 验证专业名称
    validateMajor(major) {
        const validMajors = [
            '计算机科学与技术',
            '软件工程',
            '网络工程',
            '信息安全',
            '数据科学与大数据技术',
            '人工智能'
        ];
        return validMajors.includes(major);
    },

    // 验证学生数据
    validateStudent(student) {
        const errors = [];
        
        if (!this.validateStudentId(student.id)) {
            errors.push(`学号格式错误（应为7位数字）: ${student.id}`);
        }
        
        if (!this.validateName(student.name)) {
            errors.push(`姓名无效（2-20个字符）: ${student.name}`);
        }
        
        if (!student.major) {
            errors.push('专业不能为空');
        }
        
        return {
            valid: errors.length === 0,
            errors: errors
        };
    }
};

var escapeHtml = function(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
};

var API_BASE = (function() {
    if (window.location.protocol === 'file:') return 'http://localhost:8090';
    if (window.location.port === '8090') return '';
    return '';
})();

// 导出工具
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { CryptoUtils, BackupUtils, ValidationUtils, escapeHtml };
}