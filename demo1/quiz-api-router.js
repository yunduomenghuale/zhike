var fs = require('fs');
var path = require('path');

var dataDir = path.join(__dirname, 'user-data');

function readFile(name) {
    try { return JSON.parse(fs.readFileSync(path.join(dataDir, name), 'utf8')); } catch (e) { return null; }
}
function writeFile(name, data) {
    fs.writeFileSync(path.join(dataDir, name), JSON.stringify(data, null, 2), 'utf8');
}

var questionsBank = null;
function getQuestionsBank() {
    if (!questionsBank) {
        try { questionsBank = JSON.parse(fs.readFileSync(path.join(__dirname, 'questions-bank.json'), 'utf8')); } catch (e) { questionsBank = { chapters: [] }; }
    }
    return questionsBank;
}

function getAssignments() { return readFile('assignments.json') || []; }
function saveAssignments(data) { writeFile('assignments.json', data); }
function getSubmissions() { return readFile('quiz-submissions.json') || []; }
function saveSubmissions(data) { writeFile('quiz-submissions.json', data); }

function sendJson(res, code, data) {
    res.writeHead(code, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Authorization,Content-Type' });
    res.end(JSON.stringify(data));
}

function readBody(req) {
    return new Promise(function(resolve) {
        var body = '';
        req.on('data', function(c) { body += c; });
        req.on('end', function() { resolve(body); });
    });
}

function handleRoute(req, res, pathname, method) {
    if (pathname === '/api/questions/chapters' && method === 'GET') {
        var bank = getQuestionsBank();
        var chapters = bank.chapters.map(function(ch) {
            return { id: ch.id, name: ch.name, questionCount: ch.questions.length };
        });
        return sendJson(res, 200, { chapters: chapters });
    }

    if (pathname.match(/^\/api\/questions\/chapter\/(.+)$/) && method === 'GET') {
        var chId = pathname.replace('/api/questions/chapter/', '');
        var bank2 = getQuestionsBank();
        var chapter = bank2.chapters.find(function(ch) { return ch.id === chId; });
        if (!chapter) { return sendJson(res, 404, { error: '章节不存在' }); }
        var questions = chapter.questions.map(function(q) {
            var q2 = { id: q.id, type: q.type, question: q.question };
            if (q.type === 'choice') q2.options = q.options;
            return q2;
        });
        return sendJson(res, 200, { questions: questions });
    }

    if (pathname.match(/^\/api\/questions\/chapter-full\/(.+)$/) && method === 'GET') {
        var chId2 = pathname.replace('/api/questions/chapter-full/', '');
        var bank3 = getQuestionsBank();
        var chapter2 = bank3.chapters.find(function(ch) { return ch.id === chId2; });
        if (!chapter2) { return sendJson(res, 404, { error: '章节不存在' }); }
        return sendJson(res, 200, { questions: chapter2.questions });
    }

    if (pathname === '/api/assignments' && method === 'GET') {
        return sendJson(res, 200, { assignments: getAssignments() });
    }

    if (pathname === '/api/assignments' && method === 'POST') {
        return handleCreateAssignment(req, res);
    }

    if (pathname.match(/^\/api\/assignments\/(.+)$/) && method === 'DELETE') {
        var aId = decodeURIComponent(pathname.replace('/api/assignments/', ''));
        return handleDeleteAssignment(res, aId);
    }

    if (pathname === '/api/quiz/submit' && method === 'POST') {
        return handleSubmitQuiz(req, res);
    }

    if (pathname.match(/^\/api\/quiz\/questions\/(.+)$/) && method === 'GET') {
        var qAssignId = decodeURIComponent(pathname.replace('/api/quiz/questions/', ''));
        var assignQuestions = readFile('questions-' + qAssignId + '.json');
        if (!assignQuestions) { return sendJson(res, 404, { error: '作业题目不存在' }); }
        var studentQuestions = assignQuestions.map(function(q) {
            var sq = { id: q.id, type: q.type, question: q.question };
            if (q.type === 'choice') sq.options = q.options;
            return sq;
        });
        return sendJson(res, 200, { questions: studentQuestions });
    }

    if (pathname.match(/^\/api\/quiz\/submission\/(.+)$/) && method === 'GET') {
        var assignId = decodeURIComponent(pathname.replace('/api/quiz/submission/', ''));
        return handleGetResult(req, res, assignId);
    }

    if (pathname.match(/^\/api\/quiz\/result\/(.+)$/) && method === 'GET') {
        var resultId = decodeURIComponent(pathname.replace('/api/quiz/result/', ''));
        return handleGetResult(req, res, resultId);
    }

    if (pathname === '/api/quiz/my-submissions' && method === 'GET') {
        return handleMySubmissions(req, res);
    }

    if (pathname === '/api/quiz/all-results' && method === 'GET') {
        return handleAllResults(req, res);
    }

    if (pathname === '/api/quiz/review' && method === 'POST') {
        return handleTeacherReview(req, res);
    }

    if (pathname.match(/^\/api\/quiz\/review\/(.+)$/) && method === 'GET') {
        var reviewId = decodeURIComponent(pathname.replace('/api/quiz/review/', ''));
        return handleGetReview(req, res, reviewId);
    }

    return false;
}

async function handleCreateAssignment(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var title = (data.title || '').trim();
        var questionIds = data.questionIds || [];
        var chapters = data.chapters || [];
        var startTime = data.startTime || '';
        var endTime = data.endTime || '';
        var duration = parseInt(data.duration) || 60;
        if (!title) { return sendJson(res, 400, { error: '请填写作业标题' }); }
        if (questionIds.length === 0 && chapters.length === 0) { return sendJson(res, 400, { error: '请选择题目' }); }
        var bank = getQuestionsBank();
        var allQuestions = [];
        if (questionIds.length > 0) {
            bank.chapters.forEach(function(ch) {
                ch.questions.forEach(function(q) {
                    if (questionIds.indexOf(q.id) >= 0) {
                        allQuestions.push({ id: q.id, type: q.type, question: q.question, options: q.options || null, answer: q.answer, explanation: q.explanation, chapter: ch.name });
                    }
                });
            });
        } else {
            chapters.forEach(function(chId) {
                var ch = bank.chapters.find(function(c) { return c.id === chId; });
                if (ch) {
                    ch.questions.forEach(function(q) {
                        allQuestions.push({ id: q.id, type: q.type, question: q.question, options: q.options || null, answer: q.answer, explanation: q.explanation, chapter: ch.name });
                    });
                }
            });
        }
        if (allQuestions.length === 0) { return sendJson(res, 400, { error: '未找到有效题目' }); }
        var assignments = getAssignments();
        var assignment = {
            id: 'hw_' + Date.now(),
            title: title,
            chapters: chapters,
            questionIds: questionIds,
            startTime: startTime,
            endTime: endTime,
            duration: duration,
            questionCount: allQuestions.length,
            createTime: new Date().toISOString()
        };
        assignments.push(assignment);
        saveAssignments(assignments);
        var questionsFile = 'questions-' + assignment.id + '.json';
        writeFile(questionsFile, allQuestions);
        return sendJson(res, 200, { message: '布置成功', assignment: assignment });
    } catch (e) {
        return sendJson(res, 500, { error: e.message });
    }
}

function handleDeleteAssignment(res, aId) {
    var assignments = getAssignments();
    assignments = assignments.filter(function(a) { return a.id !== aId; });
    saveAssignments(assignments);
    try { fs.unlinkSync(path.join(dataDir, 'questions-' + aId + '.json')); } catch (e) {}
    return sendJson(res, 200, { message: '删除成功', assignments: assignments });
}

function levenshteinDistance(s1, s2) {
    var len1 = s1.length, len2 = s2.length;
    var dp = [];
    for (var i = 0; i <= len1; i++) dp[i] = [i];
    for (var j = 0; j <= len2; j++) dp[0][j] = j;
    for (var i = 1; i <= len1; i++) {
        for (var j = 1; j <= len2; j++) {
            var cost = s1[i - 1] === s2[j - 1] ? 0 : 1;
            dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
        }
    }
    return dp[len1][len2];
}

function stringSimilarity(s1, s2) {
    var maxLen = Math.max(s1.length, s2.length);
    if (maxLen === 0) return 1;
    return 1 - levenshteinDistance(s1, s2) / maxLen;
}

var STOP_WORDS = ['的','是','在','和','与','或','及','了','也','都','就','还','不','为','以','可','上','下','中','对','到','从','把','被','让','使','给','向','由','于','而','且','但','则','若','如','这','那','其','之','所','者','并','即','已','曾','将','会','能','要','应','该','须','只','才','再','又','更','最','很','非','无','有','一个','一种','一些','可以','需要','进行','通过','使用','称为','就是','说明','比较','不同','相同','以及','并且','或者','如果','那么','因为','所以','虽然','但是','对于','关于','根据','按照','利用','基于','由于','为了','使得','它们','这个','那个','哪些','什么','怎么','怎样','为何','何处','哪个','哪些'];

function extractKeywords(text) {
    var terms = text.split(/[，,。.；;、\s\n\r\t（）()【】\[\]{}""''"':：!！?？/]/);
    return terms.filter(function(t) {
        return t.length >= 2 && STOP_WORDS.indexOf(t) < 0;
    });
}

function keywordMatchRatio(userAnswer, correctAnswer) {
    var keywords = extractKeywords(correctAnswer);
    if (keywords.length === 0) return 0;
    var matched = keywords.filter(function(kw) { return userAnswer.indexOf(kw) >= 0; });
    return matched.length / keywords.length;
}

function fillSimilarity(userAnswer, correctAnswer) {
    var separators = /[，,、\/\s\n\r\t]/;
    var userTerms = userAnswer.split(separators).map(function(t) { return t.trim().toLowerCase(); }).filter(function(t) { return t.length > 0; });
    var correctTerms = correctAnswer.split(separators).map(function(t) { return t.trim().toLowerCase(); }).filter(function(t) { return t.length > 0; });
    if (correctTerms.length === 0) return 0;
    userTerms.sort();
    correctTerms.sort();
    if (JSON.stringify(userTerms) === JSON.stringify(correctTerms)) return 1;
    var matched = 0;
    var usedIndices = [];
    correctTerms.forEach(function(ct) {
        for (var i = 0; i < userTerms.length; i++) {
            if (usedIndices.indexOf(i) < 0) {
                var sim = stringSimilarity(ct, userTerms[i]);
                if (sim >= 0.8 || userTerms[i].indexOf(ct) >= 0 || ct.indexOf(userTerms[i]) >= 0) {
                    matched++;
                    usedIndices.push(i);
                    break;
                }
            }
        }
    });
    return matched / correctTerms.length;
}

function calculateSubjectiveScore(userAnswer, correctAnswer, type) {
    if (!userAnswer || typeof userAnswer !== 'string' || userAnswer.trim().length === 0) {
        return { similarity: 0, partialScore: 0, isCorrect: false };
    }
    var ua = userAnswer.trim().toLowerCase();
    var ca = String(correctAnswer).trim().toLowerCase();
    var similarity;
    if (type === 'fill') {
        similarity = fillSimilarity(ua, ca);
    } else {
        var kwRatio = keywordMatchRatio(ua, ca);
        var strSim = stringSimilarity(ua, ca);
        similarity = 0.7 * kwRatio + 0.3 * strSim;
    }
    var partialScore, isCorrect;
    if (similarity < 0.3) {
        partialScore = 0;
        isCorrect = false;
    } else if (similarity >= 0.9) {
        partialScore = 1;
        isCorrect = true;
    } else {
        partialScore = similarity;
        isCorrect = false;
    }
    return { similarity: Math.round(similarity * 100) / 100, partialScore: Math.round(partialScore * 100) / 100, isCorrect: isCorrect };
}

async function handleSubmitQuiz(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var assignmentId = data.assignmentId;
        var studentId = data.studentId;
        var answers = data.answers || {};
        var images = data.images || {};
        if (!assignmentId || !studentId) { return sendJson(res, 400, { error: '参数不完整' }); }
        var submissions = getSubmissions();
        var existing = submissions.find(function(s) { return s.assignmentId === assignmentId && s.studentId === studentId; });
        if (existing) { return sendJson(res, 400, { error: '您已提交过该作业，不能重复提交' }); }
        var questions = readFile('questions-' + assignmentId + '.json') || [];
        var correctCount = 0;
        var totalPartialScore = 0;
        var results = questions.map(function(q) {
            var userAnswer = answers[q.id];
            var isCorrect = false;
            var partialScore = 0;
            var similarity = null;
            var pendingReview = false;
            if (q.type === 'choice') {
                isCorrect = parseInt(userAnswer) === q.answer;
                partialScore = isCorrect ? 1 : 0;
            } else if (q.type === 'judge') {
                if (userAnswer === 'true') userAnswer = true;
                if (userAnswer === 'false') userAnswer = false;
                isCorrect = userAnswer === q.answer;
                partialScore = isCorrect ? 1 : 0;
            } else if (q.type === 'fill') {
                if (images[q.id]) {
                    pendingReview = true;
                } else {
                    var sc = calculateSubjectiveScore(userAnswer, q.answer, 'fill');
                    isCorrect = sc.isCorrect;
                    partialScore = sc.partialScore;
                    similarity = sc.similarity;
                }
            } else if (q.type === 'short') {
                if (images[q.id]) {
                    pendingReview = true;
                } else {
                    var sc2 = calculateSubjectiveScore(userAnswer, q.answer, 'short');
                    isCorrect = sc2.isCorrect;
                    partialScore = sc2.partialScore;
                    similarity = sc2.similarity;
                }
            }
            if (isCorrect) correctCount++;
            totalPartialScore += partialScore;
            return { questionId: q.id, userAnswer: userAnswer, correctAnswer: q.answer, isCorrect: isCorrect, partialScore: partialScore, similarity: similarity, pendingReview: pendingReview, explanation: q.explanation };
        });
        var score = questions.length > 0 ? Math.round(totalPartialScore / questions.length * 100) : 0;
        var submission = {
            assignmentId: assignmentId,
            studentId: studentId,
            answers: answers,
            images: images,
            results: results,
            score: score,
            correctCount: correctCount,
            totalPartialScore: Math.round(totalPartialScore * 100) / 100,
            totalQuestions: questions.length,
            submitTime: new Date().toISOString(),
            reviewed: false
        };
        submissions.push(submission);
        saveSubmissions(submissions);
        return sendJson(res, 200, { message: '提交成功', score: score, correctCount: correctCount, totalQuestions: questions.length });
    } catch (e) {
        return sendJson(res, 500, { error: e.message });
    }
}

function handleGetResult(req, res, assignmentId) {
    var url = req.url || '';
    var studentId = '';
    var parts = url.split('?studentId=');
    if (parts.length > 1) studentId = decodeURIComponent(parts[1].split('&')[0]);
    if (!studentId) { return sendJson(res, 400, { error: '缺少studentId' }); }
    var submissions = getSubmissions();
    var sub = submissions.find(function(s) { return s.assignmentId === assignmentId && s.studentId === studentId; });
    if (!sub) { return sendJson(res, 404, { error: '未找到提交记录' }); }
    var questions = readFile('questions-' + assignmentId + '.json') || [];
    return sendJson(res, 200, { submission: sub, questions: questions });
}

function handleMySubmissions(req, res) {
    var url = req.url || '';
    var studentId = '';
    var parts = url.split('?studentId=');
    if (parts.length > 1) studentId = decodeURIComponent(parts[1].split('&')[0]);
    if (!studentId) { return sendJson(res, 400, { error: '缺少studentId' }); }
    var submissions = getSubmissions();
    var mySubs = submissions.filter(function(s) { return s.studentId === studentId; });
    var assignments = getAssignments();
    var result = mySubs.map(function(s) {
        var a = assignments.find(function(a2) { return a2.id === s.assignmentId; });
        return { assignmentId: s.assignmentId, title: a ? a.title : '未知作业', score: s.score, correctCount: s.correctCount, totalQuestions: s.totalQuestions, submitTime: s.submitTime };
    });
    return sendJson(res, 200, { submissions: result });
}

function handleAllResults(req, res) {
    var assignments = getAssignments();
    var submissions = getSubmissions();
    var result = assignments.map(function(a) {
        var subs = submissions.filter(function(s) { return s.assignmentId === a.id; });
        return { assignment: a, submissionCount: subs.length, submissions: subs.map(function(s) { return { studentId: s.studentId, score: s.score, correctCount: s.correctCount, totalQuestions: s.totalQuestions, submitTime: s.submitTime, reviewed: s.reviewed || false }; }) };
    });
    return sendJson(res, 200, { results: result });
}

function handleGetReview(req, res, assignmentId) {
    var url = req.url || '';
    var studentId = '';
    var parts = url.split('?studentId=');
    if (parts.length > 1) studentId = decodeURIComponent(parts[1].split('&')[0]);
    if (!studentId) { return sendJson(res, 400, { error: '缺少studentId' }); }
    var submissions = getSubmissions();
    var sub = submissions.find(function(s) { return s.assignmentId === assignmentId && s.studentId === studentId; });
    if (!sub) { return sendJson(res, 404, { error: '未找到提交记录' }); }
    var questions = readFile('questions-' + assignmentId + '.json') || [];
    return sendJson(res, 200, { submission: sub, questions: questions });
}

async function handleTeacherReview(req, res) {
    var body = await readBody(req);
    try {
        var data = JSON.parse(body);
        var assignmentId = data.assignmentId;
        var studentId = data.studentId;
        var reviews = data.reviews || [];
        if (!assignmentId || !studentId) { return sendJson(res, 400, { error: '参数不完整' }); }
        var submissions = getSubmissions();
        var sub = submissions.find(function(s) { return s.assignmentId === assignmentId && s.studentId === studentId; });
        if (!sub) { return sendJson(res, 404, { error: '未找到提交记录' }); }
        reviews.forEach(function(review) {
            var result = sub.results.find(function(r) { return r.questionId === review.questionId; });
            if (result) {
                result.partialScore = review.partialScore;
                result.isCorrect = review.partialScore >= 1;
                result.reviewed = true;
                result.teacherComment = review.comment || '';
            }
        });
        var totalPartialScore = 0;
        var correctCount = 0;
        sub.results.forEach(function(r) {
            totalPartialScore += r.partialScore || 0;
            if (r.isCorrect) correctCount++;
        });
        sub.score = sub.totalQuestions > 0 ? Math.round(totalPartialScore / sub.totalQuestions * 100) : 0;
        sub.correctCount = correctCount;
        sub.totalPartialScore = Math.round(totalPartialScore * 100) / 100;
        sub.reviewed = true;
        sub.reviewTime = new Date().toISOString();
        saveSubmissions(submissions);
        return sendJson(res, 200, { message: '复核成功', score: sub.score, correctCount: sub.correctCount });
    } catch (e) {
        return sendJson(res, 500, { error: e.message });
    }
}

module.exports = { handleRoute: handleRoute };