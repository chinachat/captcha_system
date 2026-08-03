# 代码审查与安全评估报告 — captcha_system v2.1

- **仓库**: https://github.com/chinachat/captcha_system
- **审查日期**: 2026-08-03
- **技术栈**: Python 3.10+ / `http.server` / Pillow / PyJWT / SQLite（可选 Redis）
- **审查范围**: 全部 Python 源码、Docker 部署文件、前端模板与 SDK

---

## 一、总体评价

架构分层清晰（`config / db / tokens / anti_bot / captcha_gen / handler` 各司其职），SQL 全部参数化、验证码 Token 一次性使用、行为分析思路正确，作为学习/内部集成项目完成度较高。

但存在 **多个可直接利用的高危安全问题**，且生产部署形态（单线程 HTTP 服务器）不具备最基本的抗压能力，**不建议直接用于生产**。

---

## 二、安全评估（按严重程度分级）

### 🔴 P0 — 危急（可导致服务不可用 / 完全被攻破）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 1 | **单线程 HTTP 服务器** | `app.py:28` 使用 `HTTPServer` 而非 `ThreadingHTTPServer` | 所有请求串行处理。任意一个慢速客户端（slowloris，无超时）或耗时图片生成即可**阻塞整个服务**，是彻底的服务拒绝（DoS）。验证码服务应并发承载请求。 |
| 2 | **存储型 XSS → 管理员 JWT 被窃取** | `handler.py:339` 将客户端可控的 `code` 原样写入日志 `detail`；`templates/admin.html:358` 将 `r.detail` 未经转义拼入 `innerHTML`（`title` 属性同样未转义） | 攻击链：`POST /api/v1/captcha/text/verify` 提交 `code: "<img src=x onerror=...>"`（无长度限制）→ 写入 `captcha_logs.detail` → 管理员打开后台 → 脚本以管理员身份执行。由于后台 JWT 存于 `localStorage`（`admin.html:233`），XSS 可直接窃取令牌调用 `/api/v1/admin/keys` 等管理接口。**真实可利用的完整攻击链**。 |
| 3 | **管理登录无任何限流/锁定，且默认密码** | `handler.py:444-451`；`Dockerfile:28` 硬编码 `ADMIN_PASS=admin123` | `/api/v1/admin/login` 不受限流、无失败锁定、无延时，可无限暴力破解；配合默认凭据可秒破。 |

### 🟠 P1 — 高危

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 4 | **X-Forwarded-For 可任意伪造，限流/锁定形同虚设** | `handler.py:74-79` `_client_ip()` | 注释与配置声称"仅当请求来自可信代理时才信任 X-Forwarded-For"（`config.py:30` `TRUSTED_PROXIES`），但代码**只判断配置是否非空，从不校验请求真实来源 IP**。任意攻击者直接带 `X-Forwarded-For: 1.2.3.4` 即可：绕过生成限流、绕过失败锁定、伪造日志 IP。 |
| 5 | **无请求体大小限制 → 内存耗尽 DoS** | `handler.py:66` `_read_json()` | 直接按 `Content-Length` 读取，无上限（如声明 1GB）。`wfile.write` 响应也无大小限制。并发下可耗尽内存。 |
| 6 | **默认凭据贯穿全链路** | `config.py:9,15`、`Dockerfile:26-29`、`docker-compose.yml:11-14` | `ADMIN_PASS=admin123`、`DEFAULT_API_KEY=demo-api-key-captcha-2026` 为默认值且不校验。照 README/Docker 部署即暴露于公开网络，任何人可用默认 Key 生成验证码、用默认密码进后台。 |
| 7 | **内存限流表无限增长** | `rate_limit.py:9` `_rate_memory = defaultdict(deque)` | 与 #4 组合：攻击者伪造随机 IP 每分钟产生新条目，**永不清除**（`_fail_counter` 有清理逻辑，此表没有），内存无界增长直至 OOM。 |

### 🟡 P2 — 中危

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 8 | 错误信息泄露内部异常 | `handler.py:260,323,372` | `f"生成失败: {e}"` 将内部异常字符串（路径、依赖版本等）返回给客户端。 |
| 9 | 接口文档泄露敏感信息 | `handler.py:531-532` | 匿名可访问 `/api/v1/docs`，明文返回 `default_api_key` 与管理员用户名。 |
| 10 | 管理员密码明文比对、无哈希 | `handler.py:446` | 字符串 `==` 比较（非常数时间），密码以明文环境变量存储，无法抵御拖库后的密码复用攻击。 |
| 11 | 安全响应头缺失 | `handler.py:43-59` | 无 `X-Content-Type-Options`、`X-Frame-Options`、`CSP`、`Referrer-Policy`，后台页面可被点击劫持。 |
| 12 | 后台 JWT 存 localStorage + 24h 无服务端吊销 | `admin.html:233,256`；`config.py:10` | 结合 #2 的 XSS 可整段窃取；logout 仅为前端清理，令牌 24h 内持续有效。 |
| 13 | 启动日志打印凭据 | `app.py:34-36` | 管理员账号密码、默认 API Key 打印到容器日志；`redis_client.py:17` 打印完整 Redis URL（含密码则泄露）。 |
| 14 | `conn.total_changes` 判断错误 | `api_keys.py:34,42` | `total_changes` 统计连接以来所有变更，同连接先做其他写操作后，对"不存在的 Key"执行 enable/delete 也会返回成功（逻辑误导，非安全漏洞）。 |
| 15 | 业务 pass_token 与管理员 JWT 共用 `SECRET_KEY` | `utils.py:33`；`handler.py:299` | 业务方需持有同一密钥验证 pass_token，密钥扩散面大；pass_token 默认 24h 有效期过长（验证码本身仅 120s）。 |
| 16 | Docker 以 root 运行 | `Dockerfile` 无 `USER` 指令 | 容器逃逸风险面扩大；建议非 root 用户 + read-only 文件系统。 |
| 17 | 管理 Cookie 认证无 CSRF 防护 | `handler.py:449` 设置 `admin_token` Cookie | 当前 `Access-Control-Allow-Origin: *` 下跨站请求不会携带 Cookie（浏览器限制），风险被部分缓解，但若前置代理改写或后续改动 CORS 配置将直接暴露；建议加 `SameSite=Strict` + CSRF 令牌。 |

### ⚪ P3 — 低危 / 设计局限（需知悉）

| # | 问题 | 说明 |
|---|------|------|
| 18 | 滑块缺口可被图像分析自动定位 | 缺口以深色阴影+挖洞绘制，`SLIDER_TOLERANCE=8px`，边缘检测（Canny + 模板匹配）定位后伪造轨迹即可通过。所有图形验证码的固有局限，属于"提高门槛"而非"杜绝"。 |
| 19 | 行为校验可被仿真绕过 | `anti_bot.py` 规则（最短耗时/线性度/速度）为静态启发式，脚本可生成拟合曲线规避。建议补充：轨迹熵、y 轴抖动、终端设备熵、失败分布统计。 |
| 20 | `Content-Length` 非数字时未捕获 | `handler.py:66` `int()` 抛 ValueError，连接直接异常断开（无 4xx 响应）。 |
| 21 | `fonts.py` 扫描全盘字体目录 | 首次调用会递归扫描 `/usr/share/fonts` 等目录（已缓存，影响有限）。 |
| 22 | 仓库含垃圾文件 `test.txt` | 内容为 "test"，应删除。 |
| 23 | 点选验证码 `chars` 数组明文下发 | 攻击者可对每个候选字符位置做 OCR 后再点选；属设计取舍，可改为"点选图片内所有 X 形状"类题型提升难度。 |

---

## 三、功能与性能优化建议

| # | 建议 | 收益 |
|---|------|------|
| F1 | `HTTPServer` → `ThreadingHTTPServer`，并设置 `timeout`（防 slowloris）与请求体上限 | 解决 P0-1、P0-5，并发承载能力提升一个量级 |
| F2 | 图片输出改 JPEG（质量 80）+ `Cache-Control`；滑块背景图与拼图可合并为单张 sprite 减半请求 | 带宽与首屏时间下降约 60% |
| F3 | 验证码生成增加进程内 LRU 预生成池（后台线程预生成 100 张） | 图片生成耗时（PIL 旋转/滤镜）移出请求关键路径 |
| F4 | 日志写入异步化/批量提交（`captcha_logs` 每验证一次一条 INSERT） | 高并发下减少 SQLite 写锁竞争（WAL 下仍建议批量） |
| F5 | 管理端 `recent` 分页 + IP/Key 维度的统计维度扩展 | 数据量大时后台不再拖垮查询 |
| F6 | 启动时生产模式校验：未覆盖 `ADMIN_PASS/SECRET_KEY/DEFAULT_API_KEY` 则 fail-fast 拒绝启动 | 杜绝默认凭据上线 |
| F7 | pass_token 独立短时效（如 60s）与独立签发 key（或 `kid` 区分用途） | 缩小业务侧密钥扩散与过期窗口 |
| F8 | Redis 限流用 Lua 脚本原子化（incr+expire+判断） | 消除 `rate_limit.py:23-27` 的竞态与不一致 |
| F9 | 管理登录加失败计数（内存/Redis）与延时退避 | 补上 P0-3 的暴力破解缺口 |
| F10 | 支持按 IP/Key 配置独立的生成限额（key 维度的 SLA） | 运营灵活性 |
| F11 | 统一加 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、基础 CSP | 纵深防御（修复 P2-11） |
| F12 | 前端 `captcha-sdk.js` 增加 `pass_token` 直传回调的完整性校验示例（README 已提示） | 防业务侧误用 |

---

## 四、整改优先级清单

### ✅ 已整改（2026-08-03，见底部"整改记录"）
1. 单线程 → 线程化服务器 + 请求超时（P0-1）
2. 管理登录限流/锁定 + 常数时间比对 + 移除默认密码上线路径（P0-3、P2-6）
3. 后台渲染所有服务端数据前 HTML 转义（P0-2）
4. `_read_json` 请求体上限（P0-5）
5. `TRUSTED_PROXIES` 按真实来源 IP 校验（P1-4）
6. `_rate_memory` 增加过期清理（P1-7）
7. 环境变量默认值 fail-fast 校验（P1-6）
8. 错误信息脱敏（P2-8）
9. 密码哈希、安全响应头、文档脱敏、`total_changes` 修复、非 root 容器、清理 `test.txt` 等（P2/P3 部分）

### 剩余建议（未在本次范围）
- 管理密码哈希存储（当前为常数时间比对 + 强密码校验 + fail-fast，未引入 bcrypt 依赖）
- 图片生成预生成池、JPEG 压缩、日志异步批量（性能优化项）
- 滑块抗图像识别增强（设计层面）
- 前端 `pass_token` 回调完整性校验示例文档

---

## 五、结论

**评级：不安全（不建议生产部署）**。核心功能代码质量尚可，但 P0 级问题（单线程 DoS、存储型 XSS、无保护的管理登录）使系统在公网环境下可被轻易攻陷或打瘫。按第四节清单整改后可达"可内部使用"水平。

*本报告由代码静态审查得出，未进行动态渗透测试；建议整改后补充接口级测试与并发压测（如 `ab -c 100`）验证。*

---

## 六、整改记录（2026-08-03）

| 编号 | 改动 | 文件 |
|------|------|------|
| R1 | `HTTPServer` → `ThreadingHTTPServer`（daemon 线程、端口复用）+ 连接级 `timeout=15s` 防 slowloris | `app.py` |
| R2 | 新增 `MAX_BODY_BYTES`(64KB)、`REQUEST_TIMEOUT`、`PASS_TOKEN_EXPIRE`(60s)、`LOGIN_LOCK_*`、`ENV`/`ALLOW_INSECURE_DEFAULTS` 配置；`validate_config()` 启动校验 | `config.py` |
| R3 | 请求体超限返回 413；`Content-Length` 非数字容错；调用方处理 None | `handler.py` |
| R4 | `_client_ip()` 仅当真实来源 IP 命中 `TRUSTED_PROXIES`（支持 CIDR，`ipaddress` 校验）才信任 X-Forwarded-For | `handler.py` |
| R5 | 管理登录：IP 维度失败锁定（5 次/5 分钟）→ 429；`hmac.compare_digest` 常数时间比对；Cookie `SameSite=Strict` + HTTPS 下 `Secure` | `handler.py` + `anti_bot.py` |
| R6 | 生成失败错误信息脱敏（内部异常仅打服务端日志）；`/api/v1/docs` 不再返回默认 Key 与管理员用户名 | `handler.py` |
| R7 | 全局安全响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: no-referrer` | `handler.py` |
| R8 | pass_token 时效独立（默认 60s，`PASS_TOKEN_EXPIRE`），与 24h 管理 JWT 分离 | `utils.py` + `handler.py` |
| R9 | 内存限流表每 60s 过期清理（防伪造 IP 撑爆内存） | `rate_limit.py` |
| R10 | `set/delete api_key` 先查存在性再更新，修复 `total_changes` 误报 | `api_keys.py` |
| R11 | Redis 连接日志脱敏（不打印密码） | `redis_client.py` |
| R12 | 启动横幅不再打印密码与默认 API Key | `app.py` |
| R13 | 后台模板新增 `esc()/escAttr()`，日志 detail、IP、Key 名称/备注/onclick 全部转义，封堵存储型 XSS | `templates/admin.html` |
| R14 | Dockerfile：移除默认凭据 ENV、`ENV=production` fail-fast、非 root 用户运行 | `Dockerfile` |
| R15 | compose 注明必填凭据；删除 `test.txt`；`.dockerignore`/README 同步 | `docker-compose.yml` 等 |

**验证**：全部 Python 文件 `py_compile` 通过；冒烟测试 16 项全绿（health/安全头/生成/校验/XSS 载荷/登录锁定 429/超限 413/XFF 伪造不可绕过限流/可信代理路径/production fail-fast 退出码 1/强凭据正常启动/10 并发生成全成功）。
