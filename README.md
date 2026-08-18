# 印度占星解读网页应用

用 Python (pyswisseph) 计算吠陀占星本命盘与 Vimshottari 大运/小运，再用 Claude API
生成中文解读，分「性格 / 财富 / 感情 / 近况」四个板块；未成年人自动切换为面向家长的语气。

## 技术栈

- **后端**：FastAPI + pyswisseph（Moshier 星历，无需下载星历文件）+ Anthropic SDK
- **前端**：原生 HTML/CSS/JS 单页应用
- **地理编码**：Photon (OpenStreetMap)，无需 API key
- **时区**：timezonefinder + Python 标准库 zoneinfo

## 本地运行

### 1. 准备 Python 环境

项目已使用 [uv](https://github.com/astral-sh/uv) 创建了 `.venv`（Python 3.11，因为
`pyswisseph` 目前没有 3.12+ 的预编译 wheel）。如果需要重新创建：

```bash
uv venv --python 3.11 .venv
uv pip install -p .venv -r backend/requirements.txt
```

### 2. 配置 Anthropic API Key

复制 `backend/.env.example` 为 `backend/.env`，填入你的 key：

```
ANTHROPIC_API_KEY=sk-ant-...
```

前往 https://console.anthropic.com/settings/keys 获取 API key（需要先注册 Anthropic
账号并绑定付款方式）。

### 3. 启动后端

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn main:app --reload --port 8000
```

Windows PowerShell 下也可以直接：

```powershell
.\.venv\Scripts\Activate.ps1
cd backend
uvicorn main:app --reload --port 8000
```

打开浏览器访问 http://127.0.0.1:8000 即可看到页面（前端由后端直接托管，无需单独启动）。

## 项目结构

```
backend/
  main.py            FastAPI 路由：/api/geocode /api/chart /admin，托管前端静态文件
  astrology.py        本命盘计算（Lahiri 恒星黄道，整宫制宫位）
  dasha.py             Vimshottari 大运/小运计算
  geocode.py           城市名 -> 经纬度 -> 时区
  interpretation.py    构建提示词并调用 Claude API 生成四板块解读+金句
  db.py                记录每次生成结果（供 /admin 查看），Postgres/SQLite
  requirements.txt
frontend/
  index.html / style.css / app.js   单页应用
render.yaml            Render 一键部署配置
```

## 后台记录（/admin）

每次成功生成解读都会被记录下来（时间、姓名、出生信息、是否未成年、金句、完整四
板块解读），访问 `/admin` 可以查看历史记录列表。

- **需要密码**：设置环境变量 `ADMIN_PASSWORD` 才能访问，用户名固定为 `admin`。
  没设置这个变量的话 `/admin` 会直接返回 503，禁止访问。
- **数据存储**：优先读取 `DATABASE_URL`（Postgres 连接串）；没设置的话会退化成
  本地 SQLite 文件 `backend/local_readings.db`。**Render 的免费 Web Service 没有
  持久化磁盘**，每次重新部署都会清空文件系统，所以线上想真正保留记录，必须配置
  Postgres（见下方部署说明）。
- 记录的数据包含姓名、出生日期/时间/地点这类个人信息，未成年人的数据也会被记录。
  `/admin` 的密码要妥善保管，不要分享给不该看到这些数据的人。

## 部署到 Render

1. 把这个项目推送到一个 GitHub 仓库。
2. 在 [Render](https://render.com) 创建账号，选择 "New +" → "Blueprint"，
   连接你的仓库 —— Render 会自动读取根目录的 `render.yaml` 并创建 Web Service。
   （如果不用 Blueprint，也可以手动创建 Web Service：Root Directory 填 `backend`，
   Build Command 填 `pip install -r requirements.txt`，
   Start Command 填 `uvicorn main:app --host 0.0.0.0 --port $PORT`。）
3. 在 Render 服务的 Environment 页面添加环境变量：
   - `ANTHROPIC_API_KEY`（必填）
   - `CLAUDE_MODEL`（可选，默认 `claude-opus-5`）
   - `ADMIN_PASSWORD`（可选，要用 `/admin` 后台的话必填，自己起一个密码）
   - `PYTHON_VERSION` = `3.11.16`（重要，否则 `pyswisseph` 可能要现场编译，构建变慢）

   > **填 Value 的时候要小心**：每个环境变量的 Value 框里只填这一个值本身，
   > 不要把 `.env` 文件里的好几行一起粘进同一个框——粘多了会导致值里混进换行符，
   > 请求会莫名其妙地失败（这是本项目部署时真实踩过的坑）。
4. 如果要用 `/admin` 后台记录功能，还需要建一个 Postgres 数据库：Render 项目页面
   点 "New +" → "Postgres"，建好后复制它的 **Internal Database URL**，回到
   Web Service 的 Environment 页面新增一个环境变量 `DATABASE_URL`，粘贴这个连接
   串。注意 Render 免费版 Postgres 通常有 30 天有效期，到期后需要重新创建并更新
   `DATABASE_URL`。不需要后台记录功能的话可以跳过这一步。
5. 部署完成后 Render 会给一个 `https://xxx.onrender.com` 的域名，即可直接使用。

免费套餐说明：Render 免费实例闲置一段时间后会休眠，首次访问需要几十秒唤醒；如需稳定
可用，升级到付费套餐。

## 关于计算精度的说明

- 星历计算使用 Swiss Ephemeris 的 Moshier 半解析算法（`FLG_MOSEPH`），精度在几角秒
  以内，足够个人占星解读使用，且不需要在部署环境中额外下载星历数据文件。
- 恒星黄道采用 Lahiri 分点岁差（印度政府天文历采用的标准）。
- 宫位采用整宫制（Whole Sign），这是吠陀占星最主流的宫位系统。
- 罗睺/计都采用平均交点（Mean Node）。

## 关于 Claude API 的说明

- 默认模型为 `claude-opus-5`（质量最高，成本也最高）。如果想降低成本，可以把环境
  变量 `CLAUDE_MODEL` 改成 `claude-sonnet-5` 或 `claude-haiku-4-5`。
- 每次生成解读都会消耗你 Anthropic 账号的 API 额度，请留意用量与账单。
- 生成的四个板块通过 `output_config.format`（结构化输出）强制为固定 JSON 格式，
  避免解析失败。

## 免责声明

本应用生成的内容基于传统占星计算方法与 AI 生成，仅供娱乐和自我参考，不构成医疗、
法律、心理或投资建议。
