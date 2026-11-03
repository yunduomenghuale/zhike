const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DATA_DIR = path.join(__dirname, 'user-data');

if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
}

function readFile(name) {
    var p = path.join(DATA_DIR, name);
    if (!fs.existsSync(p)) return null;
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
    catch (e) { return null; }
}

function writeFile(name, data) {
    var p = path.join(DATA_DIR, name);
    fs.writeFileSync(p, JSON.stringify(data, null, 2), 'utf8');
}

async function hashPassword(pwd) {
    return new Promise(function(resolve, reject) {
        var hash = crypto.createHash('sha256');
        hash.update(pwd);
        resolve(hash.digest('hex'));
    });
}

var store = {
    getUsers: function() { return readFile('users.json') || {}; },
    saveUsers: function(data) { writeFile('users.json', data); },

    getClasses: function() { return readFile('classes.json') || []; },
    saveClasses: function(data) { writeFile('classes.json', data); },

    getStudents: function() { return readFile('students.json') || []; },
    saveStudents: function(data) { writeFile('students.json', data); },

    getMajors: function() { return readFile('majors.json') || ['计算机科学与技术', '软件工程', '网络工程', '信息安全', '数据科学与大数据技术', '人工智能']; },
    saveMajors: function(data) { writeFile('majors.json', data); },

    getTeachers: function() { return readFile('teachers.json') || []; },
    saveTeachers: function(data) { writeFile('teachers.json', data); },

    getDepts: function() { return readFile('depts.json') || []; },
    saveDepts: function(data) { writeFile('depts.json', data); },

    getLabSchedules: function() { return readFile('lab-schedules.json') || {}; },
    saveLabSchedules: function(data) { writeFile('lab-schedules.json', data); },

    getStudyDetail: function(studentId) {
        var all = readFile('study-details.json') || {};
        return all[studentId] || {};
    },
    getAllStudyDetails: function() { return readFile('study-details.json') || {}; },
    saveStudyDetail: function(studentId, detail) {
        var all = readFile('study-details.json') || {};
        all[studentId] = detail;
        writeFile('study-details.json', all);
    },

    getStudyTime: function(studentId) {
        var all = readFile('study-times.json') || {};
        return all[studentId] || 0;
    },
    getAllStudyTimes: function() { return readFile('study-times.json') || {}; },
    saveStudyTime: function(studentId, time) {
        var all = readFile('study-times.json') || {};
        all[studentId] = time;
        writeFile('study-times.json', all);
    },

    getLoginCount: function(studentId) {
        var all = readFile('login-counts.json') || {};
        return all[studentId] || 0;
    },
    saveLoginCount: function(studentId, count) {
        var all = readFile('login-counts.json') || {};
        all[studentId] = count;
        writeFile('login-counts.json', all);
    },

    getLabReports: function(studentId) {
        var all = readFile('lab-reports.json') || {};
        return all[studentId] || [];
    },
    getAllLabReports: function() { return readFile('lab-reports.json') || {}; },
    saveLabReports: function(studentId, reports) {
        var all = readFile('lab-reports.json') || {};
        all[studentId] = reports;
        writeFile('lab-reports.json', all);
    },

    getLearnCounts: function() { return readFile('learn-counts.json') || {}; },
    saveLearnCounts: function(data) { writeFile('learn-counts.json', data); },

    hashPassword: hashPassword,

    initDefaultAdmin: async function() {
        var users = store.getUsers();
        if (Object.keys(users).length === 0) {
            var adminHash = await hashPassword('admin123');
            users['admin'] = {
                username: 'admin',
                passwordHash: adminHash,
                type: 'admin',
                typeName: '管理员',
                icon: '⚙️',
                name: '系统管理员',
                firstLogin: false
            };
            var teacherHash = await hashPassword('teacher123');
            users['teacher'] = {
                username: 'teacher',
                passwordHash: teacherHash,
                type: 'teacher',
                typeName: '教师',
                icon: '👨‍🏫',
                name: '教师',
                firstLogin: true
            };
            store.saveUsers(users);
        }
    }
};

module.exports = store;