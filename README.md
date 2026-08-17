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
  main.py            FastAPI 路由：/api/geocode /api/chart，托管前端静态文件
  astrology.py        本命盘计算（Lahiri 恒星黄道，整宫制宫位）
  dasha.py             Vimshottari 大运/小运计算
  geocode.py           城市名 -> 经纬度 -> 时区
  interpretation.py    构建提示词并调用 Claude API 生成四板块解读
  requirements.txt
frontend/
  index.html / style.css / app.js   单页应用
render.yaml            Render 一键部署配置
```

## 部署到 Render

1. 把这个项目推送到一个 GitHub 仓库。
2. 在 [Render](https://render.com) 创建账号，选择 "New +" → "Blueprint"，
   连接你的仓库 —— Render 会自动读取根目录的 `render.yaml` 并创建 Web Service。
   （如果不用 Blueprint，也可以手动创建 Web Service：Root Directory 填 `backend`，
   Build Command 填 `pip install -r requirements.txt`，
   Start Command 填 `uvicorn main:app --host 0.0.0.0 --port $PORT`。）
3. 在 Render 服务的 Environment 页面添加环境变量 `ANTHROPIC_API_KEY`（必填）
   和 `CLAUDE_MODEL`（可选，默认 `claude-opus-5`）。
4. 部署完成后 Render 会给一个 `https://xxx.onrender.com` 的域名，即可直接使用。

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
