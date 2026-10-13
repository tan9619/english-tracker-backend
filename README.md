# english-tracker-backend

english-tracker 小程序的 Flask 后端，部署到**微信云托管**。

配套前端在 `../english-tracker-v2`。

## 它是怎么工作的

小程序通过 `wx.cloud.callContainer` 走微信私有链路调用本服务。云托管在请求头
注入 `X-WX-OPENID`，Flask 直接读 —— **不需要 `wx.login`、不需要 code2session、
不需要自己维护 access_token**。

```
小程序 ──callContainer──▶ 云托管网关 ──HTTP──▶ Flask 容器
                              │
                              └─ 注入 X-WX-OPENID / X-WX-APPID
```

数据库是 MySQL。音频和头像**不经过本服务**：客户端用 `wx.cloud.uploadFile`
直传对象存储，后端只存那个 `cloud://` 字符串；只有删除时才需要调 COS。

## 本地开发

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # 改 DATABASE_URL / DEV_OPENID

# 起一个 MySQL（也可以直接用 sqlite，见 .env.example 里注释掉的那行）
docker run -d --name et-mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=devpass -e MYSQL_DATABASE=english_tracker \
  mysql:8 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci

set -a && source .env && set +a
.venv/bin/python wsgi.py      # 127.0.0.1:5000
```

自测：

```bash
curl -s localhost:5000/health
curl -s -X POST localhost:5000/api/login | python3 -m json.tool
```

跑完整的接口冒烟测试（不需要装额外依赖）：

```bash
DATABASE_URL="sqlite:///:memory:" MODERATION_MODE=off DEV_OPENID=dev-user-001 \
  .venv/bin/python tests/smoke_test.py
```

### 关于 `DEV_OPENID`

本地没有云托管网关，拿不到 `X-WX-OPENID`，所以开发时用一个固定的假身份。
它有四重限制，**不可能在生产生效**：

1. 只在 `APP_ENV != 'production'` 时
2. 只在请求来自 loopback 时
3. 只在没有 `X-WX-SOURCE` 头时（有就说明走的是真微信链路）
4. 生产环境设了 `DEV_OPENID` 会让容器**直接拒绝启动**

## 部署到微信云托管

1. [cloud.weixin.qq.com](https://cloud.weixin.qq.com) 扫码 → 选小程序 → 新建环境。
   记下**环境 ID**（形如 `prod-xxxx`），要填进前端 `utils/api.js` 的 `CLOUD_RUN_ENV`。

2. 控制台建 MySQL，建库 `english_tracker`（utf8mb4），记下内网地址/账号/密码。

3. 对象存储 → 存储配置，记下 **Bucket 名称**和**地域**。

4. 新建服务，名字必须是 **`english-tracker-api`**（要和前端 `X-WX-SERVICE` 一致），
   端口填 **80**（和 Dockerfile 里 gunicorn 监听的一致）。

5. 服务设置 → 环境变量：

   ```
   APP_ENV=production
   TZ=Asia/Shanghai
   MYSQL_ADDRESS=<内网地址:端口>
   MYSQL_USERNAME=<账号>
   MYSQL_PASSWORD=<密码>
   MYSQL_DATABASE=english_tracker
   AUTO_CREATE_TABLES=1
   COS_BUCKET=<桶名>
   COS_REGION=<地域>
   ```

   **绝不要设 `DEV_OPENID` 或 `MODERATION_MODE=off`** —— 会拒绝启动。

6. 新建版本，从 Git 仓库拉代码（或本地上传，源码远小于 2MiB 上限）。

7. **服务设置 → 网络访问 → 关闭公网访问。**

   > 这一步才是真正的安全边界。开着公网访问时 `X-WX-OPENID` 就是个普通请求头，
   > 任何人都能伪造，**代码层面补不了**。关掉后唯一入口是微信私有链路。

8. **云调用 / 开放接口服务**：白名单加两行（不带域名和参数）：

   ```
   /wxa/msg_sec_check
   /_/cos/getauth
   ```

   打开开关后**必须重新构建版本**，否则没有 sidecar，每个调用都会失败。

9. 部署初期把**最小实例数设为 1** —— `callContainer` 有 15 秒超时，冷启动可能超。

### 表结构

`AUTO_CREATE_TABLES=1` 会自动建表。想手动建或核对，用 `schema.sql`。

## 几个容易踩的坑

- **时区**：容器默认 UTC，业务按北京时间。所有"今天"都走 `app/dates.py`，
  不要直接用 `datetime.now()` —— 否则用户 00:30 打卡会被记成前一天，且不报错。
- **`js_round`**：Python 的 `round()` 是银行家舍入，JS 的 `Math.round` 是四舍五入。
  SM-2 里的取整必须用 `dates.js_round`，否则复习间隔会跟旧版不一致。
- **字符集**：表显式声明 utf8mb4。不写的话跟随库默认值，latin1 库会让中文静默乱码。
- **`connect_timeout`** 是 PyMySQL 专有参数，SQLite 不接受 —— 所以 `config.py`
  按数据库类型分别构造连接参数。

## 接口

所有接口都要求身份（`X-WX-OPENID` 或本地 `DEV_OPENID`），否则返回 401。
返回体统一是 `{success, ...}` 的 JSON。

| 方法 + 路径 | 说明 |
|---|---|
| `GET /health` | 唯一免鉴权；返回 `{ok, db}` |
| `POST /api/login` | 建/取用户行，返回 `{success, openid, isNewUser, userInfo}` |
| `GET/PATCH /api/user/profile` | 昵称、头像 |
| `PATCH /api/user/settings` | 三个提醒字段 |
| `POST /api/checkin` | 打卡；重复时返回 `code:'ALREADY_CHECKED_IN'` |
| `GET /api/checkin/stats` | 连续天数、本月统计、已打卡日期 |
| `GET /api/checkin/month?year=&month=` | **month 是 1-based** |
| `POST /api/diary` | 保存日记（含内容安全检测） |
| `GET /api/diary/today` · `GET /api/diary` · `/monthly-words` · `/stats` · `/by-date` | 查询 |
| `POST /api/chunks` | 新增语块，同时建复习卡 |
| `GET /api/chunks` · `/stats` · `POST /api/chunks/update` · `/delete` | 增删改查 |
| `GET /api/review/due` · `POST /api/review/rate` · `/skip` · `/delete` · `GET /stats` | SM-2 复习 |
| `POST /api/recordings` · `GET /api/recordings` · `/listened` · `/category` · `/delete` | 录音 |
| `POST /api/account/clear` · `/delete` | 清空数据 / 注销账号 |

前端的路由映射表在 `../english-tracker-v2/utils/api.js` 的 `ROUTES`。

## 内容安全

`cloudfunctions` 时代的 `msgSecCheck` 在云托管里换成开放接口服务的 `msg_sec_check`。
保持三态和**失败关闭**：检测做不完就不放行（`code:'ERROR'`），宁可让用户重试，
也不能让违规内容落库。`MODERATION_MODE=off` 只给本地用，生产会拒绝启动。
