# 动态验证码管理系统 v2.1

纯 Python 实现的验证码服务，支持：

- **滑动拼图验证码**（服务端生成图片 + 轨迹行为校验）
- **点选位置验证码**（依次点击汉字/字母，支持弹出框前端）
- **文字验证码**（兼容旧接口）
- **多 API Key 管理**、**IP 限流**、**失败锁定**
- **可选 Redis** 存储 Token / 限流
- **管理后台**（统计、日志、Key 管理）

依赖：Python 3.10+、Pillow、PyJWT（可选 redis）

---

## 目录结构

```
captcha_system/
├── app.py                      # 启动入口
├── captcha_app/
│   ├── config.py               # 配置 / 环境变量
│   ├── utils.py                # JWT、时间、图片 base64
│   ├── fonts.py                # 中文字体自动加载
│   ├── db.py                   # SQLite
│   ├── redis_client.py         # 可选 Redis
│   ├── rate_limit.py           # IP 限流
│   ├── anti_bot.py             # 轨迹 / 时序 / 失败锁定
│   ├── captcha_gen.py          # 图片生成
│   ├── tokens.py               # Token 与验证日志
│   ├── api_keys.py             # API Key CRUD
│   ├── stats.py                # 统计
│   └── handler.py              # HTTP 路由
├── templates/
│   ├── demo.html               # 演示页（滑动 + 点选弹窗）
│   └── admin.html              # 管理后台
├── fonts/                      # 可选自备中文字体
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 一、本地部署

### 1. 环境要求

- Python 3.10+
- 系统中文字体（推荐）：

```bash
# Debian / Ubuntu
sudo apt-get update
sudo apt-get install -y fonts-noto-cjk fonts-wqy-microhei fontconfig

# 或把字体文件放到 captcha_system/fonts/ 目录
```

### 2. 安装依赖

```bash
pip install pillow PyJWT
# 若使用 Redis：
pip install redis
```

### 3. 启动

```bash
cd captcha_system
python3 app.py
```

默认监听 `0.0.0.0:8080`。

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8080/ | 前端演示 |
| http://127.0.0.1:8080/admin | 管理后台 |
| http://127.0.0.1:8080/api/v1/docs | API 文档（JSON） |
| http://127.0.0.1:8080/api/v1/health | 健康检查 |

**默认账号**

| 项目 | 值 |
|------|-----|
| 管理员 | `admin` / `admin123` |
| API Key | `demo-api-key-captcha-2026` |

> 生产环境务必修改 `ADMIN_PASS`、`SECRET_KEY`、`DEFAULT_API_KEY`。

---

## 二、Docker 部署（详细步骤）

### 2.1 前置条件

| 项目 | 要求 |
|------|------|
| 系统 | Linux / macOS / Windows（WSL2 推荐） |
| Docker | 20.10+（`docker --version`） |
| Docker Compose | V2（`docker compose version`） |
| 磁盘 | 建议预留 ≥ 2GB（含中文字体层） |
| 端口 | 宿主机 `8080` 未被占用 |

安装 Docker（Ubuntu 示例）：

```bash
# 官方或系统包均可
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # 重新登录后生效
```

验证：

```bash
docker run --rm hello-world
docker compose version
```

---

### 2.2 获取代码并进入目录

```bash
# 若已有项目目录
git clone https://github.com/chinachat/captcha_system.git
cd captcha_system

# 确认关键文件存在
ls -la app.py Dockerfile docker-compose.yml captcha_app templates
```

---

### 2.3 修改生产配置（必做）

编辑 `docker-compose.yml` 中的环境变量：

```yaml
environment:
  - SECRET_KEY=请换成足够长的随机串   # 例如 openssl rand -hex 32
  - ADMIN_USER=admin
  - ADMIN_PASS=请换成强密码
  - DEFAULT_API_KEY=请换成业务用的 Key
  - RATE_LIMIT_GENERATE=30
  - CAPTCHA_EXPIRE=120
  - DB_PATH=/data/captcha.db
```

生成密钥示例：

```bash
openssl rand -hex 32
# 输出类似：a1b2c3d4e5f6...
```

也可在启动时用环境变量覆盖，不必改文件：

```bash
export SECRET_KEY=$(openssl rand -hex 32)
export ADMIN_PASS='YourStrongPass!2026'
```

---

### 2.4 配置镜像加速（国内网络强烈建议）

若构建时出现 `TLS handshake timeout` / `failed to resolve source metadata`：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json << 'JSON'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ]
}
JSON
sudo systemctl daemon-reload
sudo systemctl restart docker
```

本仓库 `Dockerfile` 默认使用：

```dockerfile
FROM docker.m.daocloud.io/library/python:3.12-slim
```

pip 使用清华源；若仍失败，可将第一行改为：

```dockerfile
FROM registry.cn-hangzhou.aliyuncs.com/library/python:3.12-slim
```

---

### 2.5 构建并启动（基础版，仅 SQLite）

```bash
cd captcha_system

# 构建镜像并后台启动
docker compose up -d --build

# 查看状态
docker compose ps

# 查看日志（确认出现「已启动」）
docker compose logs -f captcha
```

成功日志示例：

```text
========================================================
  动态验证码管理系统 v2.1（模块化）已启动
  演示页面:  http://127.0.0.1:8080/
  管理后台:  http://127.0.0.1:8080/admin
  ...
  存储: SQLite
========================================================
```

浏览器访问：

| 地址 | 说明 |
|------|------|
| http://服务器IP:8080/ | 演示页 |
| http://服务器IP:8080/admin | 管理后台 |
| http://服务器IP:8080/api/v1/health | 健康检查 |

快速探测：

```bash
curl -s http://127.0.0.1:8080/api/v1/health
# {"ok": true, "storage": "sqlite", ...}
```

---

### 2.6 启用 Redis（生产推荐）

Redis 用于 Token 自动过期与多实例共享限流。

**步骤 A — 编辑 `docker-compose.yml`**

取消下列注释（去掉行首 `#`）：

```yaml
services:
  captcha:
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis

  redis:
    image: docker.m.daocloud.io/library/redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data

volumes:
  captcha_data:
  redis_data:
```

**步骤 B — 重建并启动**

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f captcha
```

日志中应出现：`[INFO] Redis 已连接: redis://redis:6379/0`，且 health 中 `"storage": "redis"`。

```bash
curl -s http://127.0.0.1:8080/api/v1/health
```

---

### 2.7 仅用 docker 命令（不使用 compose）

```bash
cd captcha_system

# 构建
docker build -t captcha-system:2.1 .

# 运行（数据持久化到命名卷）
docker volume create captcha_data
docker run -d --name captcha   -p 8080:8080   -e SECRET_KEY="$(openssl rand -hex 32)"   -e ADMIN_PASS="YourStrongPass"   -e DEFAULT_API_KEY="demo-api-key-captcha-2026"   -e DB_PATH=/data/captcha.db   -v captcha_data:/data   --restart unless-stopped   captcha-system:2.1

docker logs -f captcha
```

---

### 2.8 数据持久化说明

| 挂载 | 路径 | 内容 |
|------|------|------|
| 卷 `captcha_data` | 容器内 `/data` | SQLite 文件 `captcha.db` |
| 卷 `redis_data`（可选） | Redis 数据目录 | Redis 持久化 |

备份 SQLite：

```bash
docker compose exec captcha ls -la /data
docker cp $(docker compose ps -q captcha):/data/captcha.db ./captcha-backup-$(date +%F).db
```

---

### 2.9 常用运维命令

```bash
# 查看运行状态
docker compose ps

# 实时日志
docker compose logs -f captcha

# 重启
docker compose restart captcha

# 停止并删除容器（保留数据卷）
docker compose down

# 停止并删除容器 + 数据卷（慎用）
docker compose down -v

# 修改代码或 Dockerfile 后重新构建
docker compose up -d --build

# 进入容器调试
docker compose exec captcha bash
# 容器内：fc-list :lang=zh | head   # 检查中文字体
```

---

### 2.10 反向代理（Nginx 示例）

```nginx
server {
    listen 80;
    server_name captcha.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

建议同时配置 HTTPS（Let's Encrypt / 云证书）。应用会读取 `X-Forwarded-For` 作为客户端 IP（限流与日志）。

---

### 2.11 构建失败排查

| 现象 | 处理 |
|------|------|
| `TLS handshake timeout` 拉基础镜像 | 配置 registry-mirrors；或改用阿里云/DaoCloud 基础镜像 |
| `pip install` 超时 | Dockerfile 已用清华源；检查容器出网 |
| 端口占用 `bind: address already in use` | 修改 compose 中 `"8080:8080"` 为 `"8081:8080"` |
| 点选汉字方框 | 镜像已装 `fonts-noto-cjk`；`docker compose build --no-cache` 重装 |
| 权限 / 卷无法写 | 确认 `DB_PATH=/data/captcha.db` 且挂载了 `/data` |
| 旧容器配置未生效 | `docker compose down && docker compose up -d --build` |

查看完整构建日志：

```bash
docker compose build --no-cache --progress=plain 2>&1 | tee build.log
```

---

### 2.12 资源占用参考

| 组件 | 大约内存 |
|------|----------|
| captcha（含 Noto CJK 字体的进程） | 150–400MB |
| redis:7-alpine | 10–30MB |

首次构建因下载基础镜像与 `fonts-noto-cjk`，耗时可能 5–15 分钟，视网络而定。

---

## 三、环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8080` | 端口 |
| `SECRET_KEY` | 随机 | JWT 签名密钥（生产请固定） |
| `ADMIN_USER` | `admin` | 后台用户名 |
| `ADMIN_PASS` | `admin123` | 后台密码 |
| `DEFAULT_API_KEY` | `demo-api-key-captcha-2026` | 默认 API Key |
| `CAPTCHA_EXPIRE` | `120` | 验证码有效秒数 |
| `DB_PATH` | `/tmp/captcha_system.db` | SQLite 路径 |
| `REDIS_URL` | 空 | 如 `redis://127.0.0.1:6379/0` |
| `RATE_LIMIT_GENERATE` | `30` | 每 IP 每分钟生成次数上限 |
| `SLIDER_MIN_MS` | `280` | 滑动最短耗时（毫秒） |
| `SLIDER_MIN_TRACK` | `5` | 滑动轨迹最少采样点 |
| `CLICK_MIN_TOTAL_MS` | `600` | 点选总最短耗时 |
| `CLICK_MIN_GAP_MS` | `120` | 两次点击最小间隔 |
| `FAIL_LOCK_THRESHOLD` | `8` | 连续失败锁定阈值 |
| `FAIL_LOCK_SECONDS` | `300` | 锁定时长（秒） |

---

## 四、鉴权说明

### 业务接口（验证码生成 / 校验）

所有 `/api/v1/captcha/*` 请求需携带：

```http
X-API-Key: <your-api-key>
```

或：

```http
Authorization: Bearer <your-api-key>
```

### 管理接口

先登录获取 JWT，再携带：

```http
Authorization: Bearer <admin-jwt>
```

---

## 五、前端接口文档

Base URL：`http://127.0.0.1:8080`  
Content-Type：`application/json`

通用响应：

```json
{ "ok": true/false, "msg": "...", "data": { } }
```

限流 / 锁定时 HTTP 状态码为 **429**，body 含 `retry_after`（秒）。

---

### 5.1 健康检查

```http
GET /api/v1/health
```

**响应示例**

```json
{
  "ok": true,
  "ts": 1710000000.0,
  "storage": "sqlite",
  "rate_limit": 30
}
```

---

### 5.2 滑动拼图 — 生成

```http
POST /api/v1/captcha/slider/generate
X-API-Key: demo-api-key-captcha-2026
```

**响应**

```json
{
  "ok": true,
  "data": {
    "token": "uuid-...",
    "background": "data:image/png;base64,...",
    "puzzle": "data:image/png;base64,...",
    "puzzle_y": 32,
    "pad": 8,
    "width": 320,
    "height": 160,
    "expires_in": 120
  }
}
```

| 字段 | 说明 |
|------|------|
| `token` | 一次性校验凭证 |
| `background` | 带缺口的背景图（base64） |
| `puzzle` | 拼图块（含 8px 内边距） |
| `puzzle_y` | 拼图块 **CSS top**（原图像素，已减 pad） |
| `width` / `height` | 原图尺寸，用于缩放换算 |

**前端注意**

- 画布逻辑尺寸固定 **320×160**
- 拼图块尺寸 **58×58**（42 + 2×8）
- `piece.style.top = puzzle_y * scale`
- `scale = 显示宽度 / 320`

---

### 5.3 滑动拼图 — 校验

```http
POST /api/v1/captcha/slider/verify
X-API-Key: demo-api-key-captcha-2026
Content-Type: application/json
```

**请求体**

```json
{
  "token": "uuid-...",
  "offset_x": 128.5,
  "duration_ms": 650,
  "track": [
    { "x": 0, "t": 0 },
    { "x": 12.3, "t": 32 },
    { "x": 45.0, "t": 80 }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `token` | 是 | 生成接口返回的 token |
| `offset_x` | 是 | 拼图块左上角最终 x（**原图像素**） |
| `duration_ms` | 强烈建议 | 滑动总耗时（毫秒） |
| `track` | 强烈建议 | 轨迹采样，`t` 为相对起点的毫秒 |

**成功**

```json
{
  "ok": true,
  "msg": "验证通过",
  "pass_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**失败**

```json
{ "ok": false, "msg": "验证失败，请重试" }
```

或行为异常：

```json
{ "ok": false, "msg": "操作异常，请重新完成滑动" }
```

`pass_token` 为短期 JWT，业务方可自行校验签名与过期时间。

---

### 5.4 点选验证 — 生成

```http
POST /api/v1/captcha/click/generate
X-API-Key: demo-api-key-captcha-2026
```

**响应**

```json
{
  "ok": true,
  "data": {
    "token": "uuid-...",
    "image": "data:image/png;base64,...",
    "prompt": "请依次点击：天 → 地 → 人",
    "chars": ["天", "地", "人"],
    "count": 3,
    "width": 320,
    "height": 180,
    "expires_in": 120
  }
}
```

| 字段 | 说明 |
|------|------|
| `image` | 点选底图 |
| `chars` | 需**按顺序**点击的字符 |
| `count` | 需点击次数 |
| `width` / `height` | 原图尺寸（默认 320×180） |

---

### 5.5 点选验证 — 校验

```http
POST /api/v1/captcha/click/verify
X-API-Key: demo-api-key-captcha-2026
Content-Type: application/json
```

**请求体**

```json
{
  "token": "uuid-...",
  "points": [
    { "x": 120.0, "y": 80.5 },
    { "x": 200.0, "y": 95.0 },
    { "x": 60.0, "y": 130.0 }
  ],
  "timings": [0, 320, 710]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `token` | 是 | 生成接口 token |
| `points` | 是 | 点击坐标（**原图像素**），顺序与 `chars` 一致 |
| `timings` | 强烈建议 | 每次点击相对第一下的毫秒时间戳 |

坐标换算示例：

```js
const scale = displayWidth / 320;
const x = (clientX - boxLeft) / scale;
const y = (clientY - boxTop) / scale;
```

点击容差约 **28 像素**（圆心距离）。

**成功 / 失败** 响应格式同滑动接口。

---

### 5.6 文字验证码（兼容）

```http
POST /api/v1/captcha/text/generate
POST /api/v1/captcha/text/verify
```

校验 body：

```json
{ "token": "...", "code": "A3K9" }
```

新业务推荐使用点选或滑动接口。

---

### 5.7 前端接入示例（点选弹窗）

```js
const API_KEY = "demo-api-key-captcha-2026";
const headers = {
  "Content-Type": "application/json",
  "X-API-Key": API_KEY
};

// 1. 打开弹窗后生成
async function openCaptcha() {
  const res = await fetch("/api/v1/captcha/click/generate", {
    method: "POST", headers
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.msg);
  const { token, image, chars, count, width } = json.data;
  // 显示 image，提示 chars
  // 收集用户点击 → points[], timings[]
}

// 2. 提交
async function submit(token, points, timings) {
  const res = await fetch("/api/v1/captcha/click/verify", {
    method: "POST",
    headers,
    body: JSON.stringify({ token, points, timings })
  });
  const json = await res.json();
  if (json.ok) {
    // 将 json.pass_token 交给业务登录/提交接口
    return json.pass_token;
  }
  throw new Error(json.msg);
}
```

滑动接入需额外采集 `track` 与 `duration_ms`，详见演示页 `templates/demo.html`。

---

## 六、管理后台 API

### 6.1 登录

```http
POST /api/v1/admin/login
Content-Type: application/json

{ "username": "admin", "password": "admin123" }
```

**响应**

```json
{ "ok": true, "token": "<jwt>", "msg": "登录成功" }
```

后续请求 Header：`Authorization: Bearer <jwt>`

### 6.2 统计

```http
GET /api/v1/stats
Authorization: Bearer <jwt>
```

返回总次数、成功率、滑动/点选/文字分类、最近 50 条日志、API Key 列表等。

### 6.3 API Key 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/keys` | 列出全部 Key |
| POST | `/api/v1/admin/keys` | 创建，body: `{"name":"业务名","note":"备注"}` |
| PUT | `/api/v1/admin/keys/{key}/enable` | 启用 |
| PUT | `/api/v1/admin/keys/{key}/disable` | 禁用 |
| DELETE | `/api/v1/admin/keys/{key}` | 删除（默认 Key 不可删） |

创建响应示例：

```json
{
  "ok": true,
  "data": {
    "key": "ak-xxxx",
    "name": "官网",
    "note": "web"
  }
}
```

---

## 七、抗自动化说明

| 能力 | 说明 |
|------|------|
| 滑动轨迹 | 最短耗时、最少采样点、线性度、速度异常检测 |
| 点选时序 | 总时长、点击间隔 |
| 失败锁定 | 同一 IP+Key 连续失败达阈值后临时封禁 |
| 生成限流 | 每 IP 每分钟生成次数上限 |
| 图像干扰 | 点选字符旋转、噪声线；拼图缺口形状 |
| Token | 一次性使用 + 默认 120 秒过期 |

无轨迹/时序数据的校验请求会被拒绝或判定异常。

---

## 八、生产建议

1. 修改 `ADMIN_PASS`、`SECRET_KEY`、`DEFAULT_API_KEY`
2. 固定 `SECRET_KEY`，避免重启后 JWT 全部失效
3. 启用 Redis（多实例共享 Token 与限流）
4. 前置 Nginx / Caddy 做 HTTPS 与额外限流
5. 业务接口校验 `pass_token` 的 JWT 签名与 `exp`
6. 安装中文字体，避免点选汉字显示为方框

---

## 九、常见问题

**Q: 汉字不显示？**  
安装 `fonts-noto-cjk` 或将字体放入 `fonts/` 目录后重启。

**Q: 滑动对不齐？**  
使用接口返回的 `puzzle_y` 作为块的 `top`；`offset_x` 为块左上角原图 x（已按 pad 校正）。

**Q: 点选无成功提示？**  
演示页已修复；自建前端请确保提示元素未被 `display:none` 内联样式盖住。

**Q: `name 'uuid' is not defined`？**  
请使用当前模块化版本（`captcha_app/tokens.py` 已包含 `import uuid`）。

---

## 十、前端接入插件（CaptchaSDK）

### 引入

```html
<script src="https://你的域名/static/captcha-sdk.js"></script>
```

同域可写：

```html
<script src="/static/captcha-sdk.js"></script>
```

### 调用

```js
// 点选弹窗
CaptchaSDK.verify({
  apiKey: "demo-api-key-captcha-2026",
  type: "click",       // 或 "slider"
  baseUrl: ""          // 跨域时填 https://captcha.example.com
}).then(function (passToken) {
  // 将 passToken 随业务请求提交到后端
  console.log("pass_token", passToken);
}).catch(function (err) {
  console.warn(err.message); // 用户取消或失败
});
```

### 说明

- 自动注入样式与弹窗，无需改业务页面布局
- 已内置轨迹 / 时序采集，与服务端抗自动化策略匹配
- 成功返回 `pass_token`（JWT），业务服务端应校验其签名与过期时间

管理后台「验证码仪表盘」中也可查看接入提示与实时统计。

---

## 十一、License

仅供学习与内部集成参考。生产使用请自行评估安全策略并完成加固。

---
