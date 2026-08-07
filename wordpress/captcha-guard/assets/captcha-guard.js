/**
 * Captcha Guard（动态验证码）— 前端表单拦截
 *
 * 兼容三种提交方式：
 * 1. 标准表单（submit 事件默认提交）
 * 2. Ajax 主题监听 submit 事件（jQuery .on('submit') 等）
 * 3. Ajax 主题按钮直连（不触发 submit，按钮点击直接发请求，如 Argon）
 *
 * 流程：拦截（submit/click 双通道）→ 弹 CaptchaSDK → 通过后注入隐藏字段
 * cg_pass_token → 重放原事件（WeakSet 一次性放行）→ 主题处理器/默认提交。
 * 纯原生 JS，不依赖 jQuery。
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

  // 表单识别：已知 id 匹配，或兜底（含评论字段的表单，兼容自定义 id 的主题）
  function isProtectedForm(f) {
    if (!f || !f.matches) {
      return false;
    }
    for (var i = 0; i < selectors.length; i++) {
      if (f.matches(selectors[i])) {
        return true;
      }
    }
    return f.querySelector('textarea[name="comment"], input[name="comment"], input[name="comment_post_ID"]') !== null;
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

  // 已通过验证的表单（一次性标志）：重放事件放行，避免二次拦截
  var verifiedSet = (typeof WeakSet !== 'undefined') ? new WeakSet() : null;

  // 点击通道通过验证后即将触发的默认 submit：放行一次，避免二次弹验证码
  var pendingSubmitForm = null;

  // 验证码 token 共享缓存（表单通道与请求通道共用，避免重复弹验证码）
  var cachedToken = null;
  var cachedTokenAt = 0;
  var verifyQueue = null;

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
        // 共享缓存：后续的 Ajax 评论请求直接复用，避免二次弹验证码
        cachedToken = passToken;
        cachedTokenAt = Date.now();
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
    if (isVerified(f) || f === pendingSubmitForm) {
      pendingSubmitForm = null;
      consumeVerified(f);
      return;
    }
    if (!isProtectedForm(f)) {
      return;
    }
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
  }, true);

  // 通道二：提交按钮点击（主题不触发 submit、按钮直连 Ajax 的场景，如 Argon）
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) {
      return;
    }
    var btn = t.closest('input[type="submit"], button[type="submit"], #submit, button:not([type="button"]):not([type="reset"]):not([class*="emoji"]):not([class*="smiley"])');
    if (!btn) {
      return;
    }
    var form = btn.form || t.closest('form');
    if (!form || !isProtectedForm(form)) {
      return;
    }
    if (isVerified(form)) {
      consumeVerified(form);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    runVerification(form, function () {
      markVerified(form);
      // 重放点击会触发表单默认 submit；提前标记该表单，让随后进入
      // submit 通道的请求直接放行，避免同一表单二次弹验证码。
      pendingSubmitForm = form;
      // 重放点击：主题的点击处理器执行 Ajax 提交（表单已含 token）；
      // 无处理器时浏览器默认提交表单 → submit 通道放行
      btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
    });
  }, true);

  // ===== 通道三：请求级拦截（终极兜底）=====
  // 不依赖表单事件/序列化/按钮结构：包装 XHR 与 fetch，
  // 拦截发往 admin-ajax.php 的评论提交请求，先完成验证码再附加 cg_pass_token 发送。
  var TOKEN_CACHE_MS = 8000; // 缓存 token 最多 8 秒（pass_token 默认 60s 有效，防残留复用）

  function bodyText(body) {
    // 统一提取请求体文本（string / URLSearchParams / FormData）
    var parts = [];
    if (typeof body === 'string') {
      parts.push(body);
    } else if (body && typeof body.entries === 'function') {
      try {
        for (var pair of body.entries()) {
          parts.push(pair[0] + '=' + pair[1]);
        }
      } catch (e) {}
    }
    return parts.join('&');
  }

  function isCommentAjaxRequest(url, body) {
    if (!url || String(url).indexOf('admin-ajax.php') === -1) {
      return false;
    }
    var s = bodyText(body);
    // 已携带 token（表单序列化场景）直接放行，避免重复验证
    if (s.indexOf('cg_pass_token') !== -1) {
      return false;
    }
    return s.indexOf('comment') !== -1 || /action=[^&]*comment/i.test(s);
  }

  // 是否为真实评论提交（而非"点赞评论"等仅含 comment 字样、字段名不同的请求）
  function isCommentSubmit(body) {
    var s = bodyText(body);
    return s.indexOf('comment_post_ID') !== -1 ||
      (/action=[^&]*comment/i.test(s) && s.indexOf('comment=') !== -1);
  }

  function appendTokenToBody(body, token) {
    if (!body) {
      return 'cg_pass_token=' + encodeURIComponent(token);
    }
    if (typeof body === 'string') {
      return body + '&cg_pass_token=' + encodeURIComponent(token);
    }
    try { // FormData / URLSearchParams
      body.append('cg_pass_token', token);
    } catch (e) {}
    return body;
  }

  function ensureCaptchaToken(callback) {
    if (cachedToken && (Date.now() - cachedTokenAt) < TOKEN_CACHE_MS) {
      var t = cachedToken;
      cachedToken = null;
      callback(t);
      return;
    }
    cachedToken = null;
    if (verifyQueue) {
      verifyQueue.push(callback);
      return;
    }
    verifyQueue = [callback];
    sdkReady(function () {
      if (!window.CaptchaSDK) {
        flushQueue(null);
        return;
      }
      CaptchaSDK.verify({
        apiKey: cfg.apiKey,
        type: cfg.type,
        baseUrl: cfg.baseUrl
      }).then(function (token) {
        flushQueue(token);
      }).catch(function (err) {
        fail(err && err.message);
        flushQueue(null);
      });
    });
    function flushQueue(token) {
      var q = verifyQueue;
      verifyQueue = null;
      if (token) {
        cachedToken = token;
        cachedTokenAt = Date.now();
      }
      (q || []).forEach(function (cb) { cb(token); });
    }
  }

  // XHR 拦截
  (function () {
    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this.__cgUrl = url;
      return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      if (isCommentAjaxRequest(this.__cgUrl, body)) {
        var xhr = this;
        var originalBody = body;
        ensureCaptchaToken(function (token) {
          if (token) {
            origSend.call(xhr, appendTokenToBody(originalBody, token));
          } else if (isCommentSubmit(originalBody)) {
            // 真实评论提交：验证失败/服务不可用时 fail-closed，不发送
          } else {
            // 非评论提交（如"点赞评论"等仅含 comment 字样）：放行，避免功能损坏
            origSend.call(xhr, originalBody);
          }
        });
        return;
      }
      return origSend.call(this, body);
    };
  })();

  // fetch 拦截
  if (typeof window.fetch === 'function') {
    var origFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = (typeof input === 'string') ? input : (input && input.url) || '';
      var body = (init && init.body) || '';
      if (isCommentAjaxRequest(url, body)) {
        return new Promise(function (resolve, reject) {
          ensureCaptchaToken(function (token) {
            if (token) {
              var newInit = Object.assign({}, init || {});
              newInit.body = appendTokenToBody(body, token);
              origFetch.call(window, input, newInit).then(resolve, reject);
            } else if (isCommentSubmit(body)) {
              // 真实评论提交：fail-closed
              reject(new Error('captcha failed'));
            } else {
              // 非评论提交：放行原请求
              origFetch.call(window, input, init).then(resolve, reject);
            }
          });
        });
      }
      return origFetch.apply(window, arguments);
    };
  }
})();
