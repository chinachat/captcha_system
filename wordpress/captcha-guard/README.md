# Captcha Guard（动态验证码）WordPress 插件

为开源验证码服务 [captcha_system](https://github.com/chinachat/captcha_system) 提供 WordPress 接入。在后台选择验证方式（滑动拼图 / 点选 / 文字），保护登录、注册、评论、找回密码等表单，抵御暴力破解与垃圾评论。

- **版本**: 1.0.3
- **兼容**: WordPress 5.8+ / PHP 7.4+
- **依赖**: 需部署 captcha_system 验证码服务（v2.1.1+），插件本身零第三方 PHP 依赖

---

## 功能特性

| 能力 | 说明 |
|------|------|
| 三种验证方式 | 滑动拼图（slider）/ 点选（click）/ 文字（text），后台一键切换 |
| 四类表单保护 | 登录、注册、评论、找回密码，可多选 |
| 弹窗式体验 | 前端 CaptchaSDK 弹窗，不改变业务页面布局 |
| 服务端强校验 | pass_token 校验 JWT HS256 签名 + 过期时间 + `captcha=passed` 声明 + 一次性使用（jti） |
| fail-closed | 验证码服务不可用时受保护表单拒绝提交，不自动放行 |
| REST 覆盖 | REST API 创建评论同样受保护 |
| XML-RPC 封堵 | 登录保护启用时自动拒绝 XML-RPC 认证（暴力破解高危入口） |
| 无第三方依赖 | JWT 校验纯 PHP 实现（HMAC-SHA256） |

---

## 安装

### 方式一：后台上传（推荐）

1. 下载 `captcha-guard-1.0.0.zip`
2. WordPress 后台 → 插件 → 安装插件 → 上传插件 → 选择 zip → 立即安装
3. 启用插件

### 方式二：手动部署

```bash
# 将插件目录放到 wp-content/plugins/ 下
wp-content/plugins/captcha-guard/
```

### 前置：部署验证码服务

插件本身不生成验证码，需要先部署 captcha_system：

```bash
git clone https://github.com/chinachat/captcha_system.git
cd captcha_system
# 设置生产凭据（ENV=production 下默认凭据会拒绝启动）
export ENV=production
export SECRET_KEY=$(openssl rand -hex 32)
export ADMIN_PASS='强密码'
export DEFAULT_API_KEY='给插件用的 Key'
python3 app.py
```

在验证码服务管理后台创建 API Key，并记录：

- **API Key**：插件前端请求生成/校验接口使用
- **PASS_TOKEN_SECRET**：未单独设置时即服务端 `SECRET_KEY`，插件用它校验 pass_token 签名

---

## 配置

路径：**设置 → Captcha Guard**

| 字段 | 说明 |
|------|------|
| 启用验证码 | 总开关，关闭后插件不再拦截任何表单 |
| 验证方式 | `slider` 滑动拼图 / `click` 点选 / `text` 文字 |
| API Base URL | 验证码服务根地址，如 `https://captcha.example.com`；与 WordPress 同域部署可留空（子路径如 `/captcha` 则填完整地址） |
| API Key | 验证码服务的 API Key（会出现在页面 JS 中，建议专用低权限 Key） |
| PASS_TOKEN_SECRET | 验证码服务端 `PASS_TOKEN_SECRET`（未单独设置时即其 `SECRET_KEY`），用于服务端校验 pass_token |
| SDK 脚本地址 | 前端 `captcha-sdk.js` 完整地址，留空自动取 `API Base URL + /static/captcha-sdk.js` |
| 失败提示文案 | 验证未通过时的提示语 |
| 服务不可用时放行 | ⚠️ 仅调试用：开启后验证码服务故障时表单直接放行，生产务必关闭 |
| 保护范围 | 登录 / 注册 / 评论 / 找回密码 多选 |

> 安全建议：`API Key` 与 `PASS_TOKEN_SECRET` 存于 `wp_options` 表（明文）。高安全环境建议：
> 1. 验证码服务侧为插件创建**专用 API Key**（便于单独禁用）；
> 2. 定期轮换 `PASS_TOKEN_SECRET`（服务端与插件同步更新）；
> 3. 若验证码服务与 WordPress 同机部署，避免将 `SECRET_KEY` 明文写入可见于网络的配置文件。

---

## 工作原理

### 验证流程

```
用户提交受保护表单
        │
        ▼
[前端] 拦截 submit，弹出 CaptchaSDK 验证码
        │   ├─ POST {API}/api/v1/captcha/{type}/generate → token + 图片
        │   └─ 用户操作 → POST verify → pass_token (JWT, 60s)
        ▼
[前端] 将 pass_token 注入隐藏字段 cg_pass_token 后提交表单
        │
        ▼
[服务端] 插件校验 pass_token：
        ├─ HS256 签名（PASS_TOKEN_SECRET）
        ├─ 过期时间 exp
        ├─ 声明 captcha=passed
        └─ jti 一次性使用（transient 120s）
        │
        ▼
放行 / 拒绝（WP_Error → 表单错误提示 / 403）
```

### 各表单的校验挂钩

| 表单 | 前端选择器 | 服务端挂钩 | 备注 |
|------|-----------|-----------|------|
| 登录 | `#loginform` | `authenticate` filter | 仅 wp-login.php 表单路径；XML-RPC 认证直接拒绝 |
| 注册 | `#registerform` | `registration_errors` filter | 覆盖 wp-login.php 注册 |
| 评论 | `#commentform` | `pre_comment_on_post` action + `rest_pre_insert_comment` filter | 表单 403；REST 400 JSON |
| 找回密码 | `#lostpasswordform` | `lostpassword_post` action | 校验失败不发送重置邮件 |

**覆盖范围说明**：
- REST API 认证（如 JWT 插件登录）、第三方登录插件（OAuth 等）不经过 `authenticate` 的表单分支，不受登录验证码限制
- 单站 REST 创建用户（`/wp-json/wp/v2/users`）不触发 `registration_errors`，不在保护范围（与 WP 默认行为一致）

---

## 安全设计

- **JWT 固定算法校验**：不读取 token header 的 `alg`，始终按 HS256 校验，杜绝 `alg=none`/算法混淆攻击
- **一次性使用**：同一 pass_token（jti）只能通过一次校验，防重放
- **fail-closed**：验证码服务不可用（未开"放行"）时，受保护表单一律拒绝
- **全量输出转义**：设置页与错误提示使用 `esc_html`/`esc_attr`/`esc_url_raw`，无 XSS
- **Settings API + nonce**：设置保存受 CSRF 防护；仅 `manage_options` 权限可访问
- **输入白名单**：验证方式、集成位置均为白名单校验；字段长度受限
- **无 SSRF 面**：API 地址仅用于前端输出，插件不发起任何出站请求
- **不泄露配置状态**：校验失败返回统一提示，不暴露密钥是否配置等内部信息

---

## 常见问题

**Q: 启用后登录不了/一直提示验证失败？**
先检查：① 验证码服务是否已部署并可从浏览器访问（`{API}/api/v1/health`）；② 后台填写的 API Key 与 PASS_TOKEN_SECRET 是否正确（与验证码服务端一致）；③ 若服务端单独设置了 `PASS_TOKEN_SECRET`，插件必须填该值而非 `SECRET_KEY`。

**Q: 登录成功但跳转后未登录？**
检查 pass_token 是否过期（默认 60s，`PASS_TOKEN_EXPIRE` 可调大），或用户从填写验证码到提交表单间隔过久。

**Q: 手机/平板无法弹出验证码？**
CaptchaSDK 支持移动端（触摸事件）。若仍异常，确认前端能正常加载 SDK（浏览器控制台 Network 查看 sdkUrl 是否 200）。

**Q: 我用了其他登录插件（如 OAuth），验证码不生效？**
当前版本仅保护 WordPress 原生表单。第三方登录走各自的认证流程，如需保护请在其登录表单中自行集成 CaptchaSDK。

**Q: 能保护 REST API 创建用户吗？**
默认不保护（避免误伤管理员/合法 API 调用）。如需启用可自行挂钩 `rest_pre_insert_user`。

**Q: 服务端日志里大量 "XML-RPC 登录已被验证码保护禁用"？**
这是预期的安全行为：登录保护开启时 XML-RPC 认证被拒绝（xmlrpc.php 是暴力破解高危入口）。业务不需要 XML-RPC 时可在服务器层直接禁用 `xmlrpc.php`。

---

## 开发

```bash
wp-content/plugins/captcha-guard/
├── captcha-guard.php                      # 主文件：常量、引导、单例
├── uninstall.php                          # 卸载清理
├── assets/
│   └── captcha-guard.js                   # 前端表单拦截（原生 JS，无 jQuery 依赖）
├── includes/
│   ├── class-captcha-guard.php            # 核心：配置读写、服务端校验挂钩
│   ├── class-captcha-guard-settings.php   # 后台设置页（Settings API）
│   ├── class-captcha-guard-verify.php     # pass_token 校验（JWT HS256 + jti 一次性）
│   └── class-captcha-guard-frontend.php   # SDK 加载与表单选择器配置
└── readme.txt                             # WordPress.org 格式插件说明
```

代码规范：WordPress 编码标准（`wp` 前缀函数、`esc_*` 输出转义、`sanitize_*` 输入清洗、i18n 函数）。提交前请运行：

```bash
php -l captcha-guard.php && find . -name '*.php' -exec php -l {} \;
```

---

## 许可

MIT License，仅供学习与内部集成参考；生产使用请自行完成安全加固评估（详见 `ASSESSMENT_REPORT.md`）。
