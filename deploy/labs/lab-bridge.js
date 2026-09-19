/**
 * lab-bridge.js — 智课系统V2 虚拟仿真实验桥接层
 *
 * 职责（替代实验平台原 auth-check.js / api-client.js / study-tracker.js）：
 *  1. 从 URL 解析 attempt_token，调 /api/lab-submissions/bridge-validate/ 校验并取回
 *     random_seed（服务端持久化，提交评分唯一真相源）与实验配置；
 *  2. 把 seed 注入 window.LabBridge.seed，实验页由此驱动随机参数（替代 Math.random()）；
 *  3. 提供兼容垫片：为依赖原平台脚本的页面提供最小 API_BASE / utils 存根，
 *     使 7 个实验 HTML 无需改动即可在智课系统内运行；
 *  4. 采集步骤/错误/耗时，提交时经本桥接回传（绝不传分数，分数服务端重算）。
 *
 * 页面引入顺序：lab-bridge.js 须在 auth-check.js 等旧脚本之前加载（旧脚本已从页面移除）。
 */
(function () {
  'use strict';

  var API_ROOT = '/api'; // 同域反代到 Django 后端

  function qs(name) {
    var m = new RegExp('[?&]' + name + '=([^&]+)').exec(window.location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  var bridge = {
    token: qs('token'),
    validated: false,
    submissionId: null,
    seed: null,
    lab: null,
    questions: [],
    startTime: null,
    steps: {},
    errorLog: [],

    /** 服务端校验票据并取回 seed/配置。失败时阻塞实验并提示。 */
    validate: function () {
      var self = this;
      if (!this.token) {
        this.block('缺少实验票据，请从课程实验页进入');
        return Promise.reject(new Error('no token'));
      }
      return fetch(API_ROOT + '/lab-submissions/bridge-validate/?token=' + encodeURIComponent(this.token), {
        headers: { 'X-Lab-Token': this.token },
      })
        .then(function (res) { return res.json(); })
        .then(function (body) {
          var data = body && body.data;
          if (!data || (body.code !== undefined && body.code !== 0)) {
            self.block((body && body.message) || '实验票据校验失败');
            throw new Error('invalid token');
          }
          self.validated = true;
          self.submissionId = data.submission_id;
          self.seed = data.random_seed || {};
          self.lab = data.lab || {};
          self.questions = data.questions || [];
          self.startTime = Date.now();
          window.LAB_SEED = self.seed; // 实验页以 seed 驱动随机参数
          return data;
        });
    },

    /** 实验页在步骤校验失败时调用（防作弊留痕）。 */
    recordError: function (stepId, cmd, msg) {
      this.errorLog.push({ step: stepId, cmd: cmd, msg: msg || '', ts: Date.now() });
    },

    /** 实验页在步骤通过时调用。 */
    recordStep: function (stepId, passed) {
      this.steps[stepId] = passed ? 'pass' : 'fail';
    },

    elapsedSeconds: function () {
      return this.startTime ? Math.round((Date.now() - this.startTime) / 1000) : 0;
    },

    /** 提交：只回传过程数据，分数由服务端按 seed 重算。 */
    submit: function (answers) {
      if (!this.validated) return Promise.reject(new Error('not validated'));
      var payload = {
        attempt_token: this.token,
        steps_result: this.steps,
        error_log: this.errorLog,
        elapsed_seconds: this.elapsedSeconds(),
      };
      if (answers) payload.answers = answers;
      return fetch(API_ROOT + '/lab-submissions/' + this.submissionId + '/submit/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(function (res) { return res.json(); });
    },

    block: function (message) {
      document.addEventListener('DOMContentLoaded', function () {
        var overlay = document.createElement('div');
        overlay.style.cssText =
          'position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99999;display:flex;' +
          'align-items:center;justify-content:center;color:#fff;font-size:16px;text-align:center;padding:20px;';
        overlay.textContent = message || '实验不可用';
        document.body.appendChild(overlay);
      });
    },
  };

  window.LabBridge = bridge;

  // ---- 兼容垫片：让原实验页引用的旧全局可用，避免改 7 个 HTML ----
  // API_BASE：原页面 fetch(API_BASE + '/api/...')；新体系同域直连 /api。
  window.API_BASE = '';

  // auth-check 存根：原页面依赖其登录守卫；新体系票据即凭证，登录态由 validate 保证。
  window.AuthCheck = { check: function () { return true; }, logout: function () { window.close(); } };

  // utils 存根：常见工具函数（原页面用到 showToast / formatTime 等）。
  window.Utils = window.Utils || {
    showToast: function (msg) { console.log('[toast]', msg); },
    formatTime: function (s) {
      var m = Math.floor((s || 0) / 60), r = (s || 0) % 60;
      return m + ':' + (r < 10 ? '0' : '') + r;
    },
  };

  // study-tracker 存根：学习时长已在后端按 elapsed_seconds 统计。
  window.saveCurrentStudyTime = function () {};

  // lab-scoring-enhance 垫片：实验页内部步骤计分仍由页面自行完成；
  // 最终分数以服务端重算为准，这里仅提供与原同名 API 兼容的本地过程记录。
  window.LabScoringEnhance = {
    init: function () { bridge.startTime = bridge.startTime || Date.now(); },
    recordError: function (stepId, cmd) { bridge.recordError(stepId, cmd); },
    recordStep: function (stepId, passed) { bridge.recordStep(stepId, passed); },
    calculateBonus: function () { return { total: 0, errorCount: bridge.errorLog.length }; },
    getFinalScore: function () { return { totalScore: 0 }; },
    formatDetails: function () { return '最终成绩以提交后服务端评分为准'; },
    isInitialized: function () { return bridge.validated; },
  };

  // lab-report-generator 垫片：报告改为提交后在智课系统页面下载（二期生成 DOCX/PDF）。
  window.LabReportGenerator = {
    showConclusionDialog: function () {
      var text = window.prompt('请填写实验结论（提交后可在课程实验页查看报告）：');
      if (!text) return;
      var conclusion = bridge.submit().then(function () {
        return fetch(API_ROOT + '/lab-submissions/' + bridge.submissionId + '/conclusion/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conclusion: text }),
        });
      }).then(function () { alert('实验结论已提交'); })
        .catch(function () { alert('提交失败，请重试'); });
    },
    submitConclusion: function () { this.showConclusionDialog(); },
    cancelConclusion: function () {},
  };

  // 自动校验 + 错误钩子：实验页 console.error 不丢，桥接错误日志留痕。
  bridge.validate().catch(function () { /* block() 已提示 */ });
  window.addEventListener('error', function (e) {
    if (bridge.validated && e.message) bridge.recordError('page', '', e.message);
  });
})();
