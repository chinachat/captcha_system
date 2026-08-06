# 动态验证码管理系统 v2.4.2

纯 Python 实现的验证码服务（无第三方 Web 框架），支持滑动拼图、点选、文字三种验证方式，内置多用户体系、IP 限流、失败锁定与可选 Redis，配套 WordPress 接入插件。

- **依赖**：Python 3.10+、Pillow、PyJWT（可选 redis）
- **仓库**：https://github.com/chinachat/captcha_system

---

## 功能特性

- **三种验证码**：滑动拼图（轨迹/时序行为校验）、点选（按序点击）、文字（兼容旧接口）
- **多用户体系**：管理员 / 普通用户双角色、用户组配额、注册默认关闭
- **登录验证码**：后台登录默认需图片验证码（防暴力破解）
- **多 API Key 管理**：每 Key 连接配置一键复制、按 Key 使用统计、编辑/禁用/删除
- **演示页 Key 隔离**：demo/文档页使用自动轮换的受限演示 Key，业务 Key 不在页面泄露
- **安全**：IP 限流（按 action 独立配额）、失败锁定、pass_token 一次性校验、JWT 固定算法
- **高可用**：可选 Redis（Token 自动过期 + 多实例共享限流）；线程化服务器 + 连接上限 + 请求体上限
- **构建友好**：自动选择国内/国际镜像源（基础镜像 + apt + pip）
- **WordPress 插件**：后台选验证方式，保护登录/注册/评论/找回密码

---

## 目录结构

```
captcha_system/
├── app.py                      # 启动入口（线程化服务器 + 连接上限）
├── build.sh                    # 自动选择国内/国际基础镜像源后构建
├── docker-compose.yml          # 凭据从 .env 读取（.env 不入库）
├── .env.example                # 环境变量模板
├── requirements.txt            # 依赖锁定
├── captcha_app/
│   ├── config.py               # 配置 / 环境变量 / 凭据 fail-fast 校验
│   ├── utils.py                # JWT、时间、图片 base64
│   ├── fonts.py                # 中文字体自动加载（含 Windows 字体扫描）
│   ├── db.py                   # SQLite（旧库自动迁移）
│   ├── redis_client.py         # 可选 Redis
│   ├── rate_limit.py           # IP 限流（按 action 独立配额）
│   ├── anti_bot.py             # 轨迹 / 时序 / 失败锁定 / 登录锁定
│   ├── captcha_gen.py          # 图片生成（字形按 bbox 精确渲染）
│   ├── tokens.py               # Token 与验证日志（含 pass_token 一次性消费）
│   ├── api_keys.py             # API Key CRUD
│   ├── users.py                # 多用户：用户组 / 用户 / 配额 / 密码哈希
│   ├── stats.py                # 统计（按角色过滤）
│   └── handler.py              # HTTP 路由
├── templates/                  # demo / admin / api-docs / guide
├── wordpress/
│   └── captcha-guard/          # WordPress 接入插件（含安装包 zip）
└── fonts/                      # 可选自备中文字体
```

---

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt

# 设置生产凭据（ENV=production 下默认凭据会拒绝启动）
export SECRET_KEY=$(openssl rand -hex 32)
export ADMIN_PASS='强密码'
export DEFAULT_API_KEY='业务用的 Key'

python3 app.py
```

默认监听 `0.0.0.0:8080`：

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8080/ | 前端演示页 |
| http://127.0.0.1:8080/admin | 管理后台（登录需验证码） |
| http://127.0.0.1:8080/api/v1/health | 健康检查 |
| http://127.0.0.1:8080/api/v1/docs | API 文档（JSON） |

### Docker 部署

```bash
cd captcha_system
git pull origin main

# ① 配置生产凭据（.env 不入库，git pull 永不冲突）
cp .env.example .env
# 编辑 .env 填入 SECRET_KEY / ADMIN_PASS / DEFAULT_API_KEY
# 生成密钥：openssl rand -hex 32

# ② 自动探测国内/国际基础镜像源后构建
./build.sh

# ③ 启动
docker compose up -d captcha
docker compose logs -f captcha
```

- 也可直接 `docker compose up -d --build`（默认国内 daocloud 基础镜像源）
- 手动指定基础镜像：`BASE_IMAGE=python:3.12-slim docker compose up -d --build`
- **镜像源自动选择**：`build.sh` 探测 daocloud → 阿里云 → Docker Hub；镜像内自动探测网络环境，apt 用阿里云源 / pip 用清华源（国际网络自动用官方源）

---

## 多用户体系

| 角色 | 权限 |
|------|------|
| 管理员（内置 `admin`） | 管理全部 API Key（可指定归属创建）、创建/编辑/删除用户与用户组、设置组配额、启停用户、全量统计、查看 PASS_TOKEN_SECRET |
| 普通用户 | 登录（需验证码）后仅管理自己的 Key（受组配额限制）、统计仅含自己的 Key、不可见 PASS_TOKEN_SECRET |

- **用户组配额**：管理员创建组并设 `key_quota`（默认 5）；普通用户超限创建返回 403
- **用户管理**：注册默认关闭，管理员后台创建（密码 PBKDF2 哈希存储）；删除用户级联删除其 Key；组内有用户的组不可删除
- **登录验证码**：默认开启（`LOGIN_CAPTCHA=1`），图片验证码一次性使用，获取限流 10 次/分钟/IP
- **pass_token 在线校验**：普通用户拿不到密钥时，接入方可留空密钥改用 `POST /api/v1/captcha/validate`（服务端验签 + 一次性消费）

---

## 环境变量

> 生产环境设置 `ENV=production` 后，`SECRET_KEY` / `ADMIN_PASS` / `DEFAULT_API_KEY` 为默认值将拒绝启动（fail-fast）。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` / `PORT` | `0.0.0.0` / `8080` | 监听地址与端口 |
| `ENV` | `development` | `production` 启用凭据 fail-fast 校验 |
| `ALLOW_INSECURE_DEFAULTS` | 空 | 生产环境也允许默认凭据（仅调试） |
| `SECRET_KEY` | 随机（不持久） | JWT 签名密钥，生产必须显式设置并固定 |
| `PASS_TOKEN_SECRET` | 回退 `SECRET_KEY` | 业务 pass_token 独立签发密钥（减小扩散面） |
| `ADMIN_USER` / `ADMIN_PASS` | `admin` / `admin123` | 内置管理员凭据 |
| `DEFAULT_API_KEY` | `demo-api-key-captcha-2026` | 默认 API Key |
| `CAPTCHA_EXPIRE` | `120` | 验证码有效秒数 |
| `PASS_TOKEN_EXPIRE` | `60` | pass_token（JWT）有效秒数 |
| `MAX_BODY_BYTES` | `65536` | 请求体上限（防内存耗尽） |
| `REQUEST_TIMEOUT` | `15` | 单连接读取超时（秒） |
| `MAX_CONCURRENT` | `64` | 最大并发连接（超限拒绝新连接） |
| `DB_PATH` | `/tmp/captcha_system.db` | SQLite 路径（Docker 用 `/data/captcha.db`） |
| `REDIS_URL` | 空 | 如 `redis://127.0.0.1:6379/0` |
| `TRUSTED_PROXIES` | 空 | 可信代理 IP/CIDR，仅命中时才信任 `X-Forwarded-For`（Docker 在 `.env` 配置 `TRUSTED_PROXIES` 注入） |
| `RATE_LIMIT_GENERATE` | `30` | 生成接口限流（次/分钟/IP） |
| `DEMO_KEY_RATE` | `100` | 演示 Key 全局限流（次/分钟，所有 IP 合计） |
| `SLIDER_MIN_MS` / `SLIDER_MAX_MS` / `SLIDER_MIN_TRACK` | `280` / `30000` / `5` | 滑动行为阈值 |
| `CLICK_MIN_TOTAL_MS` / `CLICK_MIN_GAP_MS` | `600` / `120` | 点选时序阈值 |
| `FAIL_LOCK_THRESHOLD` / `FAIL_LOCK_SECONDS` | `8` / `300` | 验证失败锁定（IP+Key） |
| `LOGIN_LOCK_THRESHOLD` / `LOGIN_LOCK_SECONDS` | `5` / `300` | 登录失败锁定（IP） |
| `LOGIN_CAPTCHA` / `LOGIN_CAPTCHA_RATE` | `1` / `10` | 登录验证码开关 / 获取限流 |

---

## 鉴权说明

- **业务接口**（`/api/v1/captcha/*`）：Header `X-API-Key: <key>` 或 `Authorization: Bearer <key>`
- **管理接口**：登录后携带 `Authorization: Bearer <jwt>`（JWT 含 `role: admin|user`，普通用户仅访问自己的资源）
- 通用响应 `{ "ok": true/false, "msg": "...", "data": {} }`；限流/锁定返回 **429** 且含 `retry_after`

---

## API 接口

### 验证码业务接口

```http
POST /api/v1/captcha/slider/generate     POST /api/v1/captcha/slider/verify
POST /api/v1/captcha/click/generate      POST /api/v1/captcha/click/verify
POST /api/v1/captcha/text/generate       POST /api/v1/captcha/text/verify
```

- 滑动校验 body：`{"token","offset_x","duration_ms","track":[{x,t}]}`；`offset_x` 为拼图块左上角原图像素 x，`track` 缺失/过短/线性/超速判定异常
- 点选校验 body：`{"token","points":[{x,y}],"timings":[ms...]}`；坐标按原图像素，容差约 28px，时序过快/间隔过短判定异常
- 文字校验 body：`{"token","code"}`
- 通过后返回 `pass_token`（JWT，默认 60 秒有效）

### 连接测试（v2.2.0+）

```http
POST /api/v1/captcha/test
```
校验 API Key 后用服务端密钥签发测试 pass_token，返回 `server_secret_explicit`（是否显式配置 PASS_TOKEN_SECRET）。接入方可反向验证密钥一致性（插件"测试连接"按钮即用此接口）。

### 在线校验（v2.4.1+）

```http
POST /api/v1/captcha/validate
{ "pass_token": "eyJ..." }
```
服务端验签 + 一次性消费（jti 独立记录）。供未配置密钥的接入方（如普通用户的 WordPress 插件）使用。

### 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/admin/login` | 登录（需验证码），返回 JWT + role |
| POST | `/api/v1/admin/captcha/generate` | 登录验证码（无需 API Key） |
| GET | `/api/v1/stats` | 统计（管理员全量 / 普通用户仅自己的） |
| GET / POST | `/api/v1/admin/keys` | Key 列表（含 connect 配置）/ 创建（普通用户受配额） |
| PUT | `/api/v1/admin/keys/{key}` | 编辑名称/备注 |
| PUT / DELETE | `/api/v1/admin/keys/{key}/enable\|disable` | 启停 / 删除（仅本人或管理员） |
| GET / POST | `/api/v1/admin/users` | 用户列表 / 创建（仅管理员） |
| PUT / DELETE | `/api/v1/admin/users/{username}` | 编辑（改密/改组/启停）/ 删除（级联删 Key） |
| GET / POST | `/api/v1/admin/groups` | 用户组列表 / 创建（仅管理员） |
| PUT / DELETE | `/api/v1/admin/groups/{id}` | 编辑配额 / 删除（组内有用户拒绝） |

---

## WordPress 插件接入

仓库内置 `wordpress/captcha-guard/`（安装包 `captcha-guard-1.0.10.zip`）：后台选择验证方式，保护登录/注册/评论/找回密码表单。

**配置**：
1. 服务端后台 → API Key 卡片 → "复制插件配置"（服务地址 / API Key / PASS_TOKEN_SECRET）
2. WordPress → 设置 → Captcha Guard → 粘贴并保存，勾选保护表单
3. 点击"测试连接"验证（服务连通 / API Key / 密钥一致性 / SDK 地址）

**两种校验模式**：
- **本地验签**（推荐，管理员）：填写 PASS_TOKEN_SECRET，插件本地验证 JWT
- **在线校验**（普通用户）：密钥留空，插件调用 `/api/v1/captcha/validate`（服务端 v2.4.1+）

**内置保护**：登录保护开启时自动拒绝 XML-RPC 认证；REST 评论创建同样受保护。详见 `wordpress/captcha-guard/README.md`。

---

## 抗自动化

| 能力 | 说明 |
|------|------|
| 滑动轨迹 | 最短耗时、最少采样点、线性度、速度异常检测 |
| 点选时序 | 总时长、点击间隔、时间单调性 |
| 失败锁定 | 同一 IP+Key 连续失败达阈值后临时封禁 |
| 生成限流 | 每 IP 每分钟生成次数上限 |
| 登录防护 | 登录验证码 + IP 失败锁定 + 获取限流 |
| 图像干扰 | 点选字符旋转/噪声线；拼图缺口形状随机化 |
| Token | 一次性使用 + 默认 120 秒过期（Redis 自动过期） |

无轨迹/时序数据的校验请求会被拒绝或判定异常。

---

## 生产建议

1. `ENV=production` + 凭据写入 `.env`，`SECRET_KEY` 用 `openssl rand -hex 32` 生成并固定
2. 建议单独设置 `PASS_TOKEN_SECRET`，缩小业务侧密钥扩散面
3. 启用 Redis 实现多实例共享 Token 与限流
4. 前置 Nginx/Caddy 做 HTTPS 与连接级限流；配置 `TRUSTED_PROXIES` 后才信任 `X-Forwarded-For`
5. 确认 `DB_PATH` 持久化（Docker 卷 `/data`），避免重启丢失 Key/用户
6. 业务方校验 pass_token：本地验签需保管密钥；无密钥场景使用在线校验接口
7. 普通用户按组分配配额；删除离职用户会级联删除其 Key
8. 中文字体：Docker 镜像已内置 Noto CJK；裸机安装 `fonts-noto-cjk` 或放入 `fonts/`
9. 多个 WordPress 站共用同一验证码服务时，插件 `PASS_TOKEN_SECRET` 建议留空使用**在线校验模式**（服务端原子消费 jti）；本地验签模式的 jti 一次性消费按站点独立记录，共用密钥时 pass_token 存在 60 秒窗口内跨站重放的可能

---

## 常见问题

**Q: 登录提示"验证码错误或已过期"？**
点击验证码图片刷新重试；验证码一次性使用；频繁获取会被限流（429，默认 10 次/分钟）。

**Q: 普通用户配置插件时 PASS_TOKEN_SECRET 填什么？**
留空——插件自动切换在线校验模式（服务端 v2.4.1+）。

**Q: 服务端重启后 Key/用户丢失？**
`DB_PATH` 默认在 `/tmp`，请指向持久化目录（Docker 用 `/data` 卷）。

**Q: 后台提示"无效或缺失 API Key"？**
服务端数据库无该 Key（数据库被重置或 Key 被禁用）。后台重新创建 Key 并复制配置；确认 `DB_PATH` 持久化。

**Q: 演示页/文档页的 Key 是什么？会被滥用吗？**
演示页与文档页使用独立的 `cg-demo-*` 受限 Key：不在页面展示、每次服务重启自动轮换、后台可禁用，并受全局限流（`DEMO_KEY_RATE`，默认 100 次/分钟、所有 IP 合计）保护，换 IP 也无法绕过。业务 Key 不会出现在页面源码中。

**Q: TRUSTED_PROXIES 在 .env 里不生效？**
Docker 部署时该变量由 compose 注入（`TRUSTED_PROXIES=${TRUSTED_PROXIES:-}`），请确认：① compose 已更新到最新；② `.env` 中已配置；③ `docker compose up -d` 重启过容器（无需重建镜像）。

**Q: 构建卡在 apt-get？**
用 `./build.sh` 或 `docker compose up -d --build`——镜像内自动探测网络切换阿里云 apt 源 / 清华 pip 源。

**Q: 汉字显示为方框？**
安装 `fonts-noto-cjk` 或将字体放入 `fonts/` 目录后重启。

---

## License

MIT License，仅供学习与内部集成参考；生产使用请自行评估安全策略并完成加固（详见 `wordpress/captcha-guard/ASSESSMENT_REPORT.md` 与 guide 文档）。
