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

  function verifyAndSubmit(form) {
    sdkReady(function () {
      if (!window.CaptchaSDK) {
        if (cfg.bypassWhenUnavailable) {
          form.submit();
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
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'cg_pass_token';
        input.value = passToken;
        form.appendChild(input);
        form.submit();
      }).catch(function (err) {
        fail(err && err.message);
      });
    });
  }

  // 捕获阶段监听，确保在主题自身 submit 处理前拦截。
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || !f.matches) {
      return;
    }
    for (var i = 0; i < selectors.length; i++) {
      if (f.matches(selectors[i])) {
        e.preventDefault();
        e.stopPropagation();
        verifyAndSubmit(f);
        return;
      }
    }
  }, true);
})();
