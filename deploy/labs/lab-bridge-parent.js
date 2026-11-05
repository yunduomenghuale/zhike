/* 平台父页面桥接（v3.2 / L2）——唯一持有 LabAttemptToken 并代发成绩上报的脚本。
 *
 * 安全契约：
 * - 票据只存在于本 IIFE 闭包，绝不写入 window、绝不 postMessage 给 iframe；
 * - 只响应 event.source === frame.contentWindow 的消息（C41，opaque origin 下
 *   event.origin 是字符串 "null"，不能只靠 origin 判断）；
 * - postMessage 只传 context（四字段）与上报响应，绝不传票据；
 * - 一次性闸门（S4）：一次作答只允许一次成功上报，失败自动解除闸门以便重试；
 * - 预览模式（无票据）拒绝一切上报。
 */
(function (bootToken) {
  'use strict';
  var token = bootToken || null;
  var reported = false;
  var contextPromise = null;
  try { delete window.__LAB_BOOT_TOKEN__; } catch (e) { window.__LAB_BOOT_TOKEN__ = undefined; }

  var frame = document.getElementById('lab-frame');
  var preview = window.__LAB_PREVIEW__ === true;

  // 预览模式：不取票据、不提交；validate() 直接回服务端渲染进来的 mock context。
  // 正式模式：用票据取 bridge-validate，只把四字段映射给 iframe（C45/C25）。
  function loadContext() {
    if (window.__LAB_CONTEXT__) return Promise.resolve(window.__LAB_CONTEXT__);
    if (preview || !token) return Promise.resolve(window.__LAB_CONTEXT__ || null);
    if (!contextPromise) {
      contextPromise = fetch(
        '/api/lab-submissions/bridge-validate/?token=' + encodeURIComponent(token),
        { credentials: 'same-origin' }
      ).then(function (r) { return r.json(); }).then(function (res) {
        if (!res || res.code !== 0) return null;
        var d = res.data || {};
        window.__LAB_CONTEXT__ = {
          labId: d.lab && d.lab.id,
          submissionId: d.submission_id,
          totalScore: d.lab && d.lab.total_score != null ? Number(d.lab.total_score) : null,
          gradeEndpoint: '/api/lab-gate/grade/'
        };
        return window.__LAB_CONTEXT__;
      }).catch(function () { return null; });
    }
    return contextPromise;
  }

  window.addEventListener('message', function (e) {
    if (!frame || e.source !== frame.contentWindow) return; // C41
    var m = e.data || {};
    if (m.type === 'lab:context') {
      loadContext().then(function (ctx) {
        e.source.postMessage({ type: 'lab:context:result', context: ctx }, '*');
      });
      return;
    }
    if (m.type !== 'lab:grade' || reported) return; // S4 一次性闸门
    if (preview || !token) {
      e.source.postMessage({
        type: 'lab:grade:result',
        response: { code: 403, message: '预览模式不允许提交成绩', data: null }
      }, '*');
      return;
    }
    reported = true;
    fetch('/api/lab-gate/grade/', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Lab-Token': token },
      body: JSON.stringify(m.payload || {})
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res || res.code !== 0) reported = false; // 失败可重试，不作废票据
      e.source.postMessage({ type: 'lab:grade:result', response: res }, '*');
    }).catch(function () {
      reported = false;
      e.source.postMessage({
        type: 'lab:grade:result',
        response: { code: 500, message: '成绩上报失败，请重试', data: null }
      }, '*');
    });
  });
})(window.__LAB_BOOT_TOKEN__);
