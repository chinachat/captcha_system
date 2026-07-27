/**
 * CaptchaSDK — 验证码前端接入插件
 *
 * 修复内容（v1.1.1）：
 *   - 滑块/点选容器改用 aspect-ratio，宽度自适应时 X/Y 缩放比保持一致
 *     （修复窄屏下写死 height 导致的拼图垂直错位与点选 Y 坐标偏差）
 *   - 弹窗加 max-height + 内部滚动，适配手机横屏等矮视口
 *   - 去除触摸点击高亮（-webkit-tap-highlight-color）
 *
 * 修复内容（v1.1.0）：
 *   - 移动端触摸事件完整生命周期（touchcancel 兜底）
 *   - 缓存 scale / maxOffset，防止地址栏变化导致坐标漂移
 *   - 监听 resize / orientationchange 自动重算尺寸
 *   - touch-action: none 防止滑块/点选时页面滚动
 *   - 增大滑块触摸目标（::after 扩展至 56×56）
 *   - 点选点击添加涟漪反馈动画
 *   - 阻止多点触控缩放
 *
 * 用法：
 *   <script src="https://your-host/static/captcha-sdk.js"></script>
 *   CaptchaSDK.verify({
 *     apiKey: 'demo-api-key-captcha-2026',
 *     type: 'click',          // 'click' | 'slider'
 *     baseUrl: '',            // API 根路径，同域可留空
 *   }).then(function (passToken) {
 *     // 将 passToken 交给业务接口
 *   }).catch(function (err) {
 *     console.warn(err.message);
 *   });
 */
(function (global) {
  "use strict";

  var STYLE_ID = "captcha-sdk-style";
  var CSS = [
    ".csdk-mask{position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(2px);font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif}",
    ".csdk-modal{background:#fff;border-radius:16px;width:100%;max-width:380px;box-shadow:0 25px 60px rgba(0,0,0,.35);overflow:hidden;max-height:calc(100% - 32px);overflow-y:auto;-webkit-overflow-scrolling:touch}",
    ".csdk-hd{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;border-bottom:1px solid #f1f5f9}",
    ".csdk-hd h3{margin:0;font-size:16px;color:#1e293b}",
    ".csdk-x{width:32px;height:32px;border:none;border-radius:8px;background:#f1f5f9;cursor:pointer;font-size:18px;color:#64748b}",
    ".csdk-bd{padding:16px}",
    ".csdk-prompt{text-align:center;font-size:15px;font-weight:600;margin-bottom:10px;color:#1e293b}",
    ".csdk-prompt .hl{display:inline-block;padding:2px 6px;margin:0 2px;background:#eef2ff;color:#4338ca;border-radius:6px}",
    ".csdk-progress{text-align:center;font-size:12px;color:#64748b;margin-bottom:8px}",
    ".csdk-box{position:relative;width:320px;max-width:100%;aspect-ratio:16/9;margin:0 auto 12px;border-radius:8px;overflow:hidden;cursor:crosshair;background:#e5e7eb;user-select:none;touch-action:none;-webkit-tap-highlight-color:transparent}",
    ".csdk-box.slider{aspect-ratio:2/1}",
    ".csdk-box img{width:100%;height:100%;display:block;object-fit:fill;pointer-events:none}",
    ".csdk-piece{position:absolute;left:0;top:0;pointer-events:none;filter:drop-shadow(2px 2px 2px rgba(0,0,0,.3))}",
    ".csdk-marker{position:absolute;width:28px;height:28px;margin:-14px 0 0 -14px;border-radius:50%;background:rgba(79,70,229,.9);color:#fff;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;border:2px solid #fff;pointer-events:none}",
    "@keyframes csdk-ripple{0%{transform:scale(1);opacity:.6}100%{transform:scale(4);opacity:0}}",
    ".csdk-ripple{position:absolute;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;background:rgba(79,70,229,.35);pointer-events:none;animation:csdk-ripple .5s ease-out forwards}",
    ".csdk-track{position:relative;width:320px;max-width:100%;height:44px;margin:0 auto 12px;background:#f3f4f6;border-radius:22px;overflow:hidden;touch-action:none}",
    ".csdk-fill{position:absolute;left:0;top:0;bottom:0;width:0;background:linear-gradient(90deg,#4f46e5,#7c3aed);border-radius:22px}",
    ".csdk-thumb{position:absolute;left:0;top:0;width:44px;height:44px;background:#fff;border-radius:50%;box-shadow:0 2px 8px rgba(0,0,0,.2);cursor:grab;display:flex;align-items:center;justify-content:center;z-index:2;user-select:none;touch-action:none;-webkit-tap-highlight-color:transparent}",
    ".csdk-thumb::after{content:'';position:absolute;inset:-6px;border-radius:50%}",
    ".csdk-tip{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#9ca3af;font-size:13px;pointer-events:none}",
    ".csdk-btns{display:flex;gap:8px}",
    ".csdk-btns button{flex:1;padding:10px;border:none;border-radius:8px;font-size:14px;cursor:pointer}",
    ".csdk-primary{background:#4f46e5;color:#fff}",
    ".csdk-secondary{background:#f3f4f6;color:#374151}",
    ".csdk-status{margin-top:10px;padding:8px;border-radius:8px;font-size:13px;text-align:center;display:none}",
    ".csdk-status.ok{background:#d1fae5;color:#065f46;display:block}",
    ".csdk-status.err{background:#fee2e2;color:#991b1b;display:block}"
  ].join("");

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function request(baseUrl, path, apiKey, body) {
    return fetch((baseUrl || "") + path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey
      },
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) { return r.json(); });
  }

  function statusEl(el, msg, ok) {
    el.textContent = msg;
    el.className = "csdk-status " + (ok ? "ok" : "err");
    el.style.display = "block";
  }

  function openClick(opts, resolve, reject) {
    var mask = document.createElement("div");
    mask.className = "csdk-mask";
    mask.innerHTML =
      '<div class="csdk-modal">' +
        '<div class="csdk-hd"><h3>安全验证</h3><button type="button" class="csdk-x" data-close>×</button></div>' +
        '<div class="csdk-bd">' +
          '<div class="csdk-prompt" data-prompt>加载中…</div>' +
          '<div class="csdk-progress" data-progress></div>' +
          '<div class="csdk-box" data-box><img data-img alt="captcha"></div>' +
          '<div class="csdk-btns">' +
            '<button type="button" class="csdk-secondary" data-reset>重选</button>' +
            '<button type="button" class="csdk-secondary" data-refresh>刷新</button>' +
            '<button type="button" class="csdk-primary" data-submit>提交</button>' +
          '</div>' +
          '<div class="csdk-status" data-status></div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(mask);
    document.body.style.overflow = "hidden";

    var state = { token: null, chars: [], need: 0, points: [], timings: [], start: 0 };
    var box = mask.querySelector("[data-box]");
    var st = mask.querySelector("[data-status]");
    var closed = false;

    function cleanup(err, token) {
      if (closed) return;
      closed = true;
      document.body.style.overflow = "";
      mask.remove();
      if (err) reject(err);
      else resolve(token);
    }

    mask.querySelector("[data-close]").onclick = function () {
      cleanup(new Error("用户取消"));
    };
    mask.addEventListener("click", function (e) {
      if (e.target === mask) cleanup(new Error("用户取消"));
    });

    function load() {
      state.points = []; state.timings = []; state.start = 0;
      box.querySelectorAll(".csdk-marker").forEach(function (m) { m.remove(); });
      box.querySelectorAll(".csdk-ripple").forEach(function (m) { m.remove(); });
      statusEl(st, "加载中…", true);
      request(opts.baseUrl, "/api/v1/captcha/click/generate", opts.apiKey)
        .then(function (json) {
          if (!json.ok) throw new Error(json.msg || "生成失败");
          var d = json.data;
          state.token = d.token;
          state.chars = d.chars || [];
          state.need = d.count || state.chars.length;
          mask.querySelector("[data-img]").src = d.image;
          mask.querySelector("[data-prompt]").innerHTML =
            "请依次点击：" + state.chars.map(function (c) {
              return '<span class="hl">' + c + "</span>";
            }).join(" ");
          mask.querySelector("[data-progress]").textContent = "已选 0 / " + state.need;
          statusEl(st, "请按顺序点击图中文字", true);
        })
        .catch(function (e) { statusEl(st, e.message, false); });
    }

    function addClickFeedback(x, y) {
      var ripple = document.createElement("div");
      ripple.className = "csdk-ripple";
      ripple.style.left = x + "px";
      ripple.style.top = y + "px";
      box.appendChild(ripple);
      setTimeout(function () { ripple.remove(); }, 500);
    }

    // 阻止多点触控缩放
    box.addEventListener("touchstart", function (e) {
      if (e.touches.length > 1) e.preventDefault();
    }, { passive: false });

    box.addEventListener("click", function (e) {
      if (!state.token || state.points.length >= state.need) return;
      var rect = box.getBoundingClientRect();
      var scale = rect.width / 320;
      var dx = e.clientX - rect.left;
      var dy = e.clientY - rect.top;
      state.points.push({
        x: Math.round((dx / scale) * 10) / 10,
        y: Math.round((dy / scale) * 10) / 10
      });
      if (!state.start) state.start = performance.now();
      state.timings.push(Math.round(performance.now() - state.start));
      var mk = document.createElement("div");
      mk.className = "csdk-marker";
      mk.textContent = String(state.points.length);
      mk.style.left = dx + "px";
      mk.style.top = dy + "px";
      box.appendChild(mk);
      addClickFeedback(dx, dy);
      mask.querySelector("[data-progress]").textContent =
        "已选 " + state.points.length + " / " + state.need;
    });

    mask.querySelector("[data-reset]").onclick = function () {
      state.points = []; state.timings = []; state.start = 0;
      box.querySelectorAll(".csdk-marker").forEach(function (m) { m.remove(); });
      box.querySelectorAll(".csdk-ripple").forEach(function (m) { m.remove(); });
      mask.querySelector("[data-progress]").textContent = "已选 0 / " + state.need;
    };
    mask.querySelector("[data-refresh]").onclick = load;
    mask.querySelector("[data-submit]").onclick = function () {
      if (state.points.length !== state.need) {
        statusEl(st, "请点击 " + state.need + " 个位置", false);
        return;
      }
      statusEl(st, "校验中…", true);
      request(opts.baseUrl, "/api/v1/captcha/click/verify", opts.apiKey, {
        token: state.token,
        points: state.points,
        timings: state.timings
      }).then(function (json) {
        if (json.ok) {
          statusEl(st, "✓ 验证通过", true);
          setTimeout(function () { cleanup(null, json.pass_token); }, 500);
        } else {
          statusEl(st, "✗ " + (json.msg || "失败"), false);
          setTimeout(load, 1000);
        }
      }).catch(function (e) { statusEl(st, e.message, false); });
    };

    load();
  }

  function openSlider(opts, resolve, reject) {
    var mask = document.createElement("div");
    mask.className = "csdk-mask";
    mask.innerHTML =
      '<div class="csdk-modal">' +
        '<div class="csdk-hd"><h3>安全验证</h3><button type="button" class="csdk-x" data-close>×</button></div>' +
        '<div class="csdk-bd">' +
          '<div class="csdk-box slider" data-box>' +
            '<img data-bg alt="bg"><img class="csdk-piece" data-piece alt="piece">' +
          '</div>' +
          '<div class="csdk-track" data-track>' +
            '<div class="csdk-fill" data-fill></div>' +
            '<div class="csdk-tip" data-tip>拖动滑块完成拼图</div>' +
            '<div class="csdk-thumb" data-thumb>→</div>' +
          '</div>' +
          '<div class="csdk-btns"><button type="button" class="csdk-secondary" data-refresh>刷新</button></div>' +
          '<div class="csdk-status" data-status></div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(mask);
    document.body.style.overflow = "hidden";

    var ORIG_W = 320, PIECE = 58;
    var state = {
      token: null, offset: 0, dragging: false, startX: 0,
      track: [], t0: 0, puzzleY: 0
    };
    var box = mask.querySelector("[data-box]");
    var track = mask.querySelector("[data-track]");
    var thumb = mask.querySelector("[data-thumb]");
    var fill = mask.querySelector("[data-fill]");
    var piece = mask.querySelector("[data-piece]");
    var tip = mask.querySelector("[data-tip]");
    var st = mask.querySelector("[data-status]");
    var closed = false;

    // 缓存布局参数，防止滑动过程中地址栏变化导致坐标漂移
    var layout = { scale: 1, maxOffset: 276 };

    function cleanup(err, token) {
      if (closed) return;
      closed = true;
      document.body.style.overflow = "";
      mask.remove();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("orientationchange", onOrientationChange);
      if (err) reject(err);
      else resolve(token);
    }
    mask.querySelector("[data-close]").onclick = function () { cleanup(new Error("用户取消")); };
    mask.addEventListener("click", function (e) {
      if (e.target === mask) cleanup(new Error("用户取消"));
    });

    function updateLayout() {
      var boxW = box.getBoundingClientRect().width || ORIG_W;
      layout.scale = boxW / ORIG_W;
      if (layout.scale <= 0) layout.scale = 1;
      var trackW = track.getBoundingClientRect().width || ORIG_W;
      layout.maxOffset = Math.max(0, trackW - 44);
      // 同步更新 piece 尺寸
      piece.style.width = (PIECE * layout.scale) + "px";
      piece.style.height = (PIECE * layout.scale) + "px";
      piece.style.top = (state.puzzleY * layout.scale) + "px";
    }

    function onResize() {
      if (closed) return;
      updateLayout();
    }
    function onOrientationChange() {
      if (closed) return;
      // 屏幕旋转动画完成后重算
      setTimeout(updateLayout, 300);
    }
    window.addEventListener("resize", onResize);
    window.addEventListener("orientationchange", onOrientationChange);

    function load() {
      statusEl(st, "加载中…", true);
      request(opts.baseUrl, "/api/v1/captcha/slider/generate", opts.apiKey)
        .then(function (json) {
          if (!json.ok) throw new Error(json.msg || "生成失败");
          var d = json.data;
          state.token = d.token;
          state.puzzleY = d.puzzle_y || 0;
          mask.querySelector("[data-bg]").src = d.background;
          piece.src = d.puzzle;
          updateLayout();
          state.offset = 0;
          thumb.style.left = "0px";
          fill.style.width = "0px";
          piece.style.left = "0px";
          tip.textContent = "拖动滑块完成拼图";
          tip.style.opacity = "1";
          tip.style.color = "#9ca3af";
          statusEl(st, "请拖动滑块", true);
        })
        .catch(function (e) { statusEl(st, e.message, false); });
    }

    function onMove(e) {
      if (!state.dragging) return;
      e.preventDefault();
      var cx = e.touches ? e.touches[0].clientX : e.clientX;
      var x = Math.max(0, Math.min(cx - state.startX, layout.maxOffset));
      state.offset = x;
      thumb.style.left = x + "px";
      fill.style.width = (x + 22) + "px";
      piece.style.left = x + "px";
      tip.style.opacity = x > 8 ? "0" : "1";
      var t = performance.now() - state.t0;
      var last = state.track[state.track.length - 1];
      if (!last || Math.abs(last.x - x) >= 1 || t - last.t >= 16) {
        state.track.push({ x: Math.round(x * 10) / 10, t: Math.round(t) });
      }
    }

    function onUp() {
      if (!state.dragging) return;
      state.dragging = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onUp);
      document.removeEventListener("touchcancel", onUp);
      if (!state.token) return;
      var s = layout.scale;
      var ox = s > 0 ? state.offset / s : state.offset;
      var duration = Math.round(performance.now() - state.t0);
      var tr = state.track.map(function (p) {
        return { x: Math.round((p.x / (s || 1)) * 100) / 100, t: p.t };
      });
      request(opts.baseUrl, "/api/v1/captcha/slider/verify", opts.apiKey, {
        token: state.token,
        offset_x: Math.round(ox * 100) / 100,
        duration_ms: duration,
        track: tr
      }).then(function (json) {
        if (json.ok) {
          tip.textContent = "验证成功 ✓";
          tip.style.opacity = "1";
          tip.style.color = "#059669";
          statusEl(st, "✓ 验证通过", true);
          setTimeout(function () { cleanup(null, json.pass_token); }, 500);
        } else {
          statusEl(st, json.msg || "失败", false);
          setTimeout(load, 600);
        }
      }).catch(function (e) { statusEl(st, e.message, false); });
    }

    thumb.addEventListener("mousedown", function (e) {
      e.preventDefault();
      state.dragging = true;
      state.startX = e.clientX - state.offset;
      state.t0 = performance.now();
      state.track = [{ x: state.offset, t: 0 }];
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
    thumb.addEventListener("touchstart", function (e) {
      e.preventDefault();
      state.dragging = true;
      state.startX = e.touches[0].clientX - state.offset;
      state.t0 = performance.now();
      state.track = [{ x: state.offset, t: 0 }];
      document.addEventListener("touchmove", onMove, { passive: false });
      document.addEventListener("touchend", onUp);
      document.addEventListener("touchcancel", onUp);
    }, { passive: false });

    mask.querySelector("[data-refresh]").onclick = load;
    load();
  }

  /**
   * @param {Object} options
   * @param {string} options.apiKey
   * @param {string} [options.type='click'] - click | slider
   * @param {string} [options.baseUrl=''] - API 根地址，同域留空
   * @returns {Promise<string>} pass_token
   */
  function verify(options) {
    options = options || {};
    if (!options.apiKey) {
      return Promise.reject(new Error("缺少 apiKey"));
    }
    ensureStyle();
    var type = options.type || "click";
    return new Promise(function (resolve, reject) {
      if (type === "slider") openSlider(options, resolve, reject);
      else openClick(options, resolve, reject);
    });
  }

  global.CaptchaSDK = {
    verify: verify,
    version: "1.1.1"
  };
})(typeof window !== "undefined" ? window : this);
