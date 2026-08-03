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

  // 重放标志：SDK 完成后的 submit 事件放行（交给主题的 Ajax 处理器或默认提交）
  var replaying = false;

  function interceptSubmit(e, form, tokenField) {
    e.preventDefault();
    e.stopPropagation();
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
        tokenField.value = passToken;
        replaying = true;
        // 重放 submit 事件：Ajax 主题（如 Argon）由其处理器接管并序列化表单；
        // 无处理器拦截时走默认提交兜底
        var ev = new Event('submit', { bubbles: true, cancelable: true });
        form.dispatchEvent(ev);
        if (!ev.defaultPrevented) {
          form.submit();
        }
      }).catch(function (err) {
        fail(err && err.message);
      });
    });
  }

  // 捕获阶段监听，确保在主题自身 submit 处理前拦截。
  document.addEventListener('submit', function (e) {
    if (replaying) {
      replaying = false;
      return;
    }
    var f = e.target;
    if (!f || !f.matches) {
      return;
    }
    for (var i = 0; i < selectors.length; i++) {
      if (f.matches(selectors[i])) {
        interceptSubmit(e, f, ensureTokenField(f));
        return;
      }
    }
  }, true);
})();
