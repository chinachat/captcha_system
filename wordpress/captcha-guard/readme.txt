=== Captcha Guard（动态验证码） ===
Contributors: chinachat
Tags: captcha, security, login, anti-spam, 验证码
Requires at least: 5.8
Tested up to: 6.5
Requires PHP: 7.4
Stable tag: 1.0.10
License: MIT

对接"动态验证码管理系统"（captcha_system），后台选择滑动/点选/文字验证方式，保护登录、注册、评论、找回密码表单。

== Description ==

本插件为开源验证码服务 [captcha_system](https://github.com/chinachat/captcha_system) 提供 WordPress 接入：

* 后台选择验证方式：滑动拼图 / 点选 / 文字
* 保护表单：登录、注册、评论、找回密码（可多选）
* 前端弹窗式验证（CaptchaSDK），服务端校验 pass_token（JWT HS256 签名 + 过期 + 一次性使用）
* 无第三方 PHP 依赖，纯 PHP 实现 JWT 校验

== 安装与配置 ==

1. 将插件目录上传到 `/wp-content/plugins/`，在后台启用"Captcha Guard（动态验证码）"。
2. 部署并启动验证码服务（captcha_system），创建 API Key，记录 `PASS_TOKEN_SECRET`（未单独设置时即 `SECRET_KEY`）。
3. 进入"设置 → Captcha Guard"：
   - 启用验证码，选择验证方式（slider / click / text）
   - 填写验证码服务地址（与 WordPress 同域可留空）
   - 填写 API Key 与 PASS_TOKEN_SECRET
   - 勾选需要保护的表单
4. 保存后在前端测试。

== 常用设置 ==

* **验证方式**：slider（滑动拼图）/ click（点选）/ text（文字）
* **API Base URL**：验证码服务根地址，如 `https://captcha.example.com`；同域部署可留空
* **API Key**：验证码服务下发的 Key（会暴露在前端，建议使用专用 Key）
* **PASS_TOKEN_SECRET**：验证码服务端 `PASS_TOKEN_SECRET`（未单独设置时即其 `SECRET_KEY`），用于校验 pass_token
* **SDK 脚本地址**：一般留空，默认取 `服务地址 + /static/captcha-sdk.js`
* **服务不可用时放行**：仅调试用，生产建议关闭

== 安全说明 ==

* pass_token 为短期 JWT（默认 60 秒），服务端校验签名、过期时间与 `captcha=passed` 声明
* 同一 pass_token（jti）只能使用一次（transient 120 秒）
* 若验证码服务不可用且未开启"放行"，受保护的表单将拒绝提交（fail-closed）
* API Key 与 PASS_TOKEN_SECRET 以明文保存在 `wp_options`，请确保站点文件与数据库权限安全

== Changelog ==

= 1.0.10 =
* 修复：评论表单内表情/工具栏按钮（type=button 等）不再误触验证码
* 修复：双通道重复验证 —— token 缓存共享（8 秒窗口），已携带 token 的请求直接放行，仅需一次验证码

= 1.0.9 =
* 新增：请求级拦截（XHR/fetch 包装）——发往 admin-ajax.php 的评论提交请求先完成验证码再自动附加 cg_pass_token，兼容任何主题的 Ajax 提交方式

= 1.0.8 =
* 修复：评论表单兜底识别（不再依赖 #commentform id）——含评论字段（name="comment"/comment_post_ID）的表单即受保护，兼容自定义 id 的主题

= 1.0.7 =
* 修复：Argon 等"按钮直连 Ajax"评论主题 403 —— 新增提交按钮点击拦截通道（submit 事件 + 点击双通道兜底）

= 1.0.6 =
* 新增：评论验证码仅游客选项（默认开启）——登录用户评论直接放行（表单与 REST 均生效），前端不弹验证码

= 1.0.5 =
* 修复：Ajax 评论主题（如 Argon）提交 403 —— 前端改为隐藏字段预注入 + 重放 submit 事件，兼容原生与 Ajax 表单

= 1.0.4 =
* 新增：PASS_TOKEN_SECRET 可留空——留空时插件调用服务端在线校验接口（服务端 v2.4.1+），普通用户无需密钥即可使用
* 修复：在线校验模式支持同机部署（放行配置的主机）

= 1.0.3 =
* 修复：SDK 检查改用 GET 请求（验证码服务不支持 HEAD，原逻辑误报 501）

= 1.0.2 =
* 新增：后台"测试连接"按钮，一键检测服务连通性 / API Key / PASS_TOKEN_SECRET 一致性 / SDK 地址
* 依赖：验证码服务端需升级至 v2.2.0（新增 /api/v1/captcha/test 接口）

= 1.0.1 =
* 修复：XML-RPC 认证绕过登录验证码（启用登录保护时一律拒绝 XML-RPC 认证）
* 修复：REST API 创建评论绕过评论验证码（新增 rest_pre_insert_comment 校验）
* 修复：密钥未配置时错误信息泄露配置状态（统一通用文案）
* 新增：README.md 与安全评估报告 ASSESSMENT_REPORT.md

= 1.0.0 =
* 首个版本：三种验证方式选择、四类表单保护、JWT 服务端校验
