/**
 * Captcha Guard — 后台"测试连接"按钮
 */
(function () {
  'use strict';

  var btn = document.getElementById('cg-test-btn');
  if (!btn || !window.CG_TEST) {
    return;
  }
  var statusEl = document.getElementById('cg-test-status');
  var listEl = document.getElementById('cg-test-checks');

  function render(checks) {
    listEl.innerHTML = '';
    (checks || []).forEach(function (c) {
      var li = document.createElement('li');
      li.style.margin = '4px 0';
      li.style.color = c.ok ? '#2271b1' : '#b32d2e';
      li.textContent = (c.ok ? '[OK] ' : '[FAIL] ') + c.label + ' — ' + (c.detail || '');
      listEl.appendChild(li);
    });
  }

  btn.addEventListener('click', function () {
    btn.disabled = true;
    statusEl.textContent = '测试中…';
    statusEl.style.color = '#646970';
    listEl.innerHTML = '';

    var data = new URLSearchParams();
    data.append('action', 'captcha_guard_test');
    data.append('nonce', window.CG_TEST.nonce);

    fetch(window.CG_TEST.ajaxurl, {
      method: 'POST',
      body: data,
      credentials: 'same-origin'
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res && Array.isArray(res.checks)) {
          render(res.checks);
          if (res.ok) {
            statusEl.textContent = '全部通过';
            statusEl.style.color = '#00a32a';
          } else {
            statusEl.textContent = '存在异常，请按上方提示排查';
            statusEl.style.color = '#b32d2e';
          }
        } else {
          statusEl.textContent = (res && res.msg) || '测试失败';
          statusEl.style.color = '#b32d2e';
        }
      })
      .catch(function (e) {
        statusEl.textContent = '请求失败：' + e.message;
        statusEl.style.color = '#b32d2e';
      })
      .finally(function () {
        btn.disabled = false;
      });
  });
})();
