# 代码审查与安全评估报告 — Captcha Guard WordPress 插件 v1.0.1

- **审查对象**: `wordpress/captcha-guard/`（对接 captcha_system 验证码服务的 WP 插件）
- **审查日期**: 2026-08-03
- **环境**: WordPress 5.8+ / PHP 7.4+，PHP 8.2.33 语法校验通过
- **审查范围**: 全部 6 个 PHP 文件、前端 JS、安装包结构

---

## 一、总体评价

插件结构清晰（主文件/核心/设置/校验/前端五层分离），安全基线良好：全量输出转义、Settings API 内置 nonce、输入白名单、JWT 固定算法校验、fail-closed 设计。审查发现并修复 3 个问题（见第四节），剩余为低危/设计权衡项。

---

## 二、安全评估

### ✅ 做得正确的地方

| 项 | 位置 | 说明 |
|----|------|------|
| JWT 固定算法 | `verify.php:62-87` | 不信任 token header 的 `alg`，固定 HS256 校验，杜绝 `alg=none` 与算法混淆攻击 |
| 签名+过期+声明三重校验 | `verify.php:47-60` | `hash_equals` 常数时间比较；`exp` 校验；`captcha=passed` 声明校验 |
| jti 一次性使用 | `verify.php:56-59` | transient 记录已用 jti（120s），防重放 |
| 输出全转义 | `settings.php` 全部 echo/printf | `esc_html`/`esc_attr`/`esc_url_raw`；`wp_localize_script` 由 WP 序列化 |
| 输入白名单 | `settings.php:156-190` | 验证方式、集成位置白名单；`sanitize_text_field`/`esc_url_raw` 清洗 |
| CSRF 防护 | `settings.php:144-147` | `settings_fields()` + `submit_button()` 内置 nonce 验证 |
| 权限控制 | `settings.php:36-42,132-135` | 菜单与渲染双重 `manage_options` 检查 |
| 无 SSRF | 前端配置仅 JS 输出 | 插件零出站请求，API 地址不产生服务端请求 |
| fail-closed | `verify.php:38-41` | 无 token/密钥未配置/服务异常一律拒绝，不自动放行 |
| 输入清洗模式 | `class-captcha-guard.php:169` 等 | `sanitize_text_field( wp_unslash( $_POST[...] ) )` 为 WP 官方推荐模式 |
| 无注入 | 全部查询/写入使用 WP API | 无 SQL 拼接、无文件操作、无 `eval` |
| 卸载清理 | `uninstall.php` | 删除配置项，无残留 |

### 🟡 本次审查发现并修复

| # | 严重度 | 问题 | 修复 |
|---|--------|------|------|
| 1 | 中 | **XML-RPC 登录绕过验证码**：`authenticate` 原仅校验 `$_POST['log']`/`$_POST['pwd']` 表单路径，攻击者可经 `xmlrpc.php` 的 `wp.getUsersBlogs` 等方法无验证码暴力破解 | `class-captcha-guard.php:168-173` 登录保护启用时，XML-RPC 认证请求一律返回 `WP_Error` 拒绝 |
| 2 | 中 | **REST 评论绕过**：`pre_comment_on_post` 仅覆盖表单评论，`/wp-json/wp/v2/comments` 创建评论不受保护（垃圾评论主要来源之一） | 新增 `rest_pre_insert_comment` filter，REST 路径返回 `WP_Error`（400 JSON） |
| 3 | 低 | **配置状态泄露**：密钥未配置时错误信息明示"未配置 PASS_TOKEN_SECRET"，向攻击者暴露内部状态 | `verify.php` 改为统一通用文案 |

### ⚪ 剩余低危 / 设计权衡（建议知悉）

| # | 项 | 说明 |
|---|----|------|
| 4 | jti 一次性 TOCTOU | `get_transient`+`set_transient` 非原子，极端并发下同一 token 可能通过两次。攻击者需在 60s 窗口内精确同步双请求，利用难度高，未处理 |
| 5 | 密钥明文存储 | API Key / PASS_TOKEN_SECRET 明文存 `wp_options`。已通过 README 说明；高安全环境建议专用 Key + 定期轮换 |
| 6 | API Key 暴露前端 | SDK 前端请求必须携带，属设计使然。建议使用专用低权限 Key，可在验证码服务端单独禁用 |
| 7 | 登录保护边界 | 仅覆盖 wp-login.php 原生表单；REST 认证、第三方登录插件（OAuth 等）不受限。XML-RPC 已被封堵 |
| 8 | 单站 REST 注册用户不受保护 | `registration_errors` 不覆盖 `/wp-json/wp/v2/users` 创建（与 WP 默认一致），避免误伤管理员/API 调用 |
| 9 | 登录验证基于存在性判断 | 依赖 `$_POST['log']`/`$_POST['pwd']` 区分表单路径，如第三方插件复用同字段名可能被误拦截（fail-closed 方向，安全优先） |

---

## 三、功能与健壮性评估

| 维度 | 评估 |
|------|------|
| PHP 语法 | 6 个文件 `php -l`（PHP 8.2）全部通过；代码未使用 7.4+ 特性，向下兼容 7.4 |
| 安装包 | zip 条目使用标准 `/` 分隔符（已验证二进制无 `\`），Linux/WP 可正常解压；顶层目录 `captcha-guard/` 符合 WP 规范 |
| 前端 | 原生 JS 无依赖，捕获阶段拦截，SDK 按需加载（动态注入），失败提示用 `alert`（无 HTML 注入面） |
| 依赖 | 零第三方 PHP 依赖，JWT 校验为纯 PHP（HMAC-SHA256 + base64url） |
| 性能 | 校验为单次 HMAC + transient 读写，开销可忽略 |
| 卸载 | 无残留配置、无钩子残留、无数据表 |

---

## 四、验证记录

| 验证项 | 结果 |
|--------|------|
| `php -l` 全部 PHP 文件（PHP 8.2.33） | 6/6 通过 |
| JWT 校验逻辑与 PyJWT（验证码服务端实际签发库）互操作 | 有效签发通过 / 篡改拒绝 / 过期拒绝 / 错密钥拒绝 |
| zip 安装包结构（模拟解压） | `captcha-guard/captcha-guard.php` 主文件与 4 个 include 完整 |
| zip 条目分隔符字节检查 | 反斜杠 0，正斜杠 16 |
| 后端钩子覆盖矩阵 | 登录/注册/评论/找回密码 + REST 评论 + XML-RPC 封堵 |

---

## 五、结论

**评级：安全可用（生产级）**。未发现可利用的高危漏洞；本次审查修复了 XML-RPC 与 REST 评论两条绕过路径。剩余事项均为低危或明确的部署层权衡（密钥保管、专用 Key、覆盖边界），已在 README 中给出指引。

*本报告为静态代码审查结论，未进行 WordPress 运行时动态渗透测试。建议部署后在测试站点验证四类表单的拦截/放行行为。*
