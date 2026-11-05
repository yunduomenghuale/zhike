/* iframe 内无票据桥接 shim（v3.2 / L2）。
 *
 * 运行在 sandbox iframe（opaque origin）内：
 * - 本文件不持有票据，也不发起任何平台 API 请求（C42）；
 * - 对教师 HTML 暴露与预置实验一致的 window.LabBridge 四 API；
 * - validate() / reportGrade() 全部经 postMessage 交给平台父页面代发；
 * - 预览模式 LabBridge.preview === true，validate() 返回父页面给的 mock context。
 */
(function () {
  'use strict';
  var pending = {};
  window.addEventListener('message', function (e) {
    var m = e.data || {}, p;
    if (m.type === 'lab:context:result' || m.type === 'lab:grade:result') {
      p = pending[m.type];
      if (p) { delete pending[m.type]; p(m); }
    }
  });
  function ask(type, extra) {
    return new Promise(function (resolve) {
      pending[type === 'lab:context' ? 'lab:context:result' : 'lab:grade:result'] = resolve;
      window.parent.postMessage(Object.assign({ type: type }, extra || {}), '*');
    });
  }
  window.LabBridge = {
    preview: window.__LAB_PREVIEW__ === true,
    context: null,
    validate: function () {
      return ask('lab:context').then(function (m) {
        this.context = m.context || null;
        return this.context;
      }.bind(window.LabBridge));
    },
    reportGrade: function (payload) {
      return ask('lab:grade', { payload: payload }).then(function (m) { return m.response; });
    }
  };
  try { delete window.__LAB_PREVIEW__; } catch (e) { window.__LAB_PREVIEW__ = undefined; }
})();
