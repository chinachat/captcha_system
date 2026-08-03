/**
 * Captcha Guard（动态验证码）— 前端表单拦截
 *
 * 拦截已启用的表单提交：先弹出验证码（CaptchaSDK），成功后把 pass_token
 * 注入隐藏字段再提交；服务端对 pass_token 做签名/过期/一次性校验。
 * 纯原生 JS，不依赖 jQuery（wp-login.php 未加载 jQuery）。
 */
(function () {
  'use strict';

  var cfg = window.CG_CONFIG;
  if (!cfg || !cfg.forms || !Object.keys(cfg.forms).length) {
    return;
  }

  var selectors = [];
  Object.keys(cfg.forms).forEach(function (key) {
    if (cfg.forms[key]) {
      selectors.push(cfg.forms[key]);
    }
  });

  function fail(msg) {
    alert(msg || cfg.failMessage || '安全验证未通过，请重试。');
  }

  function sdkReady(callback) {
    if (window.CaptchaSDK) {
      callback();
      return;
    }
    var s = document.createElement('script');
    s.src = cfg.sdkUrl;
    s.async = true;
    s.onload = function () { callback(); };
    s.onerror = function () {
      if (cfg.bypassWhenUnavailable) {
        callback();
        return;
      }
      fail('验证码服务不可用，请稍后重试');
    };
    document.head.appendChild(s);
  }

  // 向表单注入隐藏字段（不存在时创建），验证码通过后回填
  function ensureTokenField(form) {
    var h = form.querySelector('input[name="cg_pass_token"]');
    if (!h) {
      h = document.createElement('input');
      h.type = 'hidden';
      h.name = 'cg_pass_token';
      h.value = '';
      form.appendChild(h);
    }
    return h;
  }

  // 已通过验证的表单（一次性标志）：验证完成后的重放事件放行，避免二次拦截
  var verifiedSet = (typeof WeakSet !== 'undefined') ? new WeakSet() : null;

  function markVerified(form) {
    if (verifiedSet) { verifiedSet.add(form); } else { form.setAttribute('data-cg-passed', '1'); }
  }
  function isVerified(form) {
    if (verifiedSet) { return verifiedSet.has(form); }
    return form.getAttribute && form.getAttribute('data-cg-passed') === '1';
  }
  function consumeVerified(form) {
    if (verifiedSet) { verifiedSet.delete(form); } else if (form.removeAttribute) { form.removeAttribute('data-cg-passed'); }
  }

  function runVerification(form, done) {
    sdkReady(function () {
      if (!window.CaptchaSDK) {
        if (cfg.bypassWhenUnavailable) {
          done();
          return;
        }
        fail('验证码服务不可用，请稍后重试');
        return;
      }
      CaptchaSDK.verify({
        apiKey: cfg.apiKey,
        type: cfg.type,
        baseUrl: cfg.baseUrl
      }).then(function (passToken) {
        ensureTokenField(form).value = passToken;
        done();
      }).catch(function (err) {
        fail(err && err.message);
      });
    });
  }

  // 通道一：submit 事件（标准表单 / 主题监听 submit 的 Ajax 表单）
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || !f.matches) {
      return;
    }
    if (isVerified(f)) {
      consumeVerified(f);
      return;
    }
    for (var i = 0; i < selectors.length; i++) {
      if (f.matches(selectors[i])) {
        e.preventDefault();
        e.stopPropagation();
        runVerification(f, function () {
          markVerified(f);
          // 重放 submit：主题 Ajax 处理器接管；无处理器时默认提交
          var ev = new Event('submit', { bubbles: true, cancelable: true });
          f.dispatchEvent(ev);
          if (!ev.defaultPrevented) {
            f.submit();
          }
        });
        return;
      }
    }
  }, true);

  // 通道二：提交按钮点击（主题不触发 submit 事件、直接按钮绑定 Ajax 的场景，如 Argon）
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) {
      return;
    }
    var btn = t.closest('input[type="submit"], button[type="submit"], #submit, button');
    if (!btn) {
      return;
    }
    var form = btn.form || t.closest('form');
    if (!form) {
      return;
    }
    if (isVerified(form)) {
      consumeVerified(form);
      return;
    }
    for (var i = 0; i < selectors.length; i++) {
      if (form.matches(selectors[i])) {
        e.preventDefault();
        e.stopPropagation();
        runVerification(form, function () {
          markVerified(form);
          // 重放点击：主题的点击处理器执行 Ajax 提交（表单已含 token）；
          // 无处理器时浏览器默认提交表单 → submit 通道放行
          btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
        });
        return;
      }
    }
  }, true);
})();
