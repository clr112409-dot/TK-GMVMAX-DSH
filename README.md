# TK-GMVMAX-DSH

TikTok 广告素材分析 + FBT 库存监管看板。本仓库提供 **两种使用方式**：

- **方式一：本地运行版（推荐给普通使用，不需要 dsh）**——下载 zip，双击即用
- **方式二：DeepSeek Harness (dsh) 宿主插件版**——看板作为 dsh 常驻插件集成

## 方式一：本地运行版（不需要 dsh）

下载 **`TK-GMVMAX-FBT面板-分享包.zip`**，解压后：

1. 安装 Python 3.10+（https://www.python.org/downloads/ ，勾选 **Add Python to PATH**）
2. 双击 **`启动面板.bat`**：自动安装依赖（首次约 1-2 分钟），自动打开 http://127.0.0.1:8501
3. 把数据 Excel 放入对应文件夹：
   - `daily_data\`：广告日报（按日期命名，支持 `8.13.xlsx` 或 `2026-08-12.xlsx`）
   - `SKU Matching Table\`：SKU 匹配表（第一列商品 ID，第二列产品名称）
   - `KCXQ\`：库存 Excel（自动取最新文件）
4. 更新文件后点页面「刷新数据」即可；关闭启动窗口即停止面板

> 局域网访问（可选）：启动命令加 `--host 0.0.0.0` 可让手机/局域网设备访问；此时面板**自动生成访问令牌**并打印带 `?token=...` 的访问地址，未携带令牌的 `/api/*` 请求返回 401。也可用 `--token 自定义令牌` 指定固定令牌。

> 分享包 zip 不含任何业务数据，可直接分发；端口占用时自动改用 8502 等后续端口。

## 方式二：dsh 宿主插件版

- 看板服务自动启动/常驻（端口 8501），跨会话可用
- `dashboard_query` 工具全局注册：任意会话可直接查询广告/素材/库存数据
- `/api/tkdash` 端口路由：浏览器端可随时读取看板端口状态
- 系统提示自动注入，助手知道何时调用看板工具

### 一键安装（目标机）

需要：已安装 dsh web、Python 3.10+（含 pandas、openpyxl）。

在目标机 PowerShell 中执行：


```powershell
irm https://raw.githubusercontent.com/clr112409-dot/TK-GMVMAX-DSH/main/install.ps1 | iex
```

> ⚠️ 建议使用 **PowerShell 7+（pwsh）** 或直接使用上面的 `irm | iex` 方式（脚本文件为无 BOM UTF-8，Windows PowerShell 5.1 下用 `-File` 本地运行可能中文乱码，请改用 `pwsh -File install.ps1`）。

脚本自动完成：

1. 探测 dsh 安装目录（npm 全局 node_modules）
2. 对比已安装版本与仓库最新版（相同则提示已最新并退出）
3. 复制 `tkdash-host` 插件到 `dsh/node_modules/tkdash-host`
4. 在 `~/.dsh/profiles/web/cordis.patch.yml` 注册插件行（幂等，自动备份原文件）
5. 设置用户环境变量 `DSH_TKDASH_ROOT`（看板项目目录）和 `DSH_TKDASH_PYTHON`
6. 检查/安装 pandas、openpyxl
7. 创建数据目录 `daily_data` / `KCXQ` / `SKU Matching Table`
8. 冒烟测试看板服务

然后**重启 dsh web**，看板服务自动启动。

## 更新插件（目标机）

**重跑同一条命令即可**：

```powershell
irm https://raw.githubusercontent.com/clr112409-dot/TK-GMVMAX-DSH/main/install.ps1 | iex
```

脚本会自动对比版本：有新版则覆盖更新，无新版则提示"已是最新"。更新完成后**重启 dsh web** 生效（若 8501 看板服务正在运行，重启 dsh 或手动结束旧 python 进程后新服务代码才生效）。

> 版本号在 `tkdash-host/package.json` 的 `version` 字段。作者发布更新时需**递增版本号**（如 1.0.0 → 1.0.1），目标机才能识别到新版本。

> 强制重装：下载 `install.ps1` 到本地后运行 `powershell -ExecutionPolicy Bypass -File install.ps1 -Force`。

## 在目标机修改代码并推送回 GitHub

安装脚本会把仓库解压到固定工作区 **`C:\Users\<用户名>\TK-GMVMAX-DSH\`**（更新时保留其中的数据文件），所以目标机也可以直接改代码并发布：

```powershell
# 1. 进入工作区
cd $HOME\TK-GMVMAX-DSH

# 2. 初始化 git 并关联远程仓库
git init
git remote add origin https://github.com/clr112409-dot/TK-GMVMAX-DSH.git
git fetch origin
git checkout -b main origin/main
# （首次需要配置 git 身份）
git config user.name "你的名字"
git config user.email "你的邮箱"

# 3. 修改代码后提交推送（建议同时递增 tkdash-host/package.json 的 version）
git add -A
git commit -m "你的修改说明"
git push origin main
```

推送成功后，**所有目标机**（包括你自己这台）重跑安装命令即可同步更新：

```powershell
irm https://raw.githubusercontent.com/clr112409-dot/TK-GMVMAX-DSH/main/install.ps1 | iex
```

注意事项：
- 目标机需要安装 [Git for Windows](https://git-scm.com/download/win)，推送时需 GitHub 账号认证（Personal Access Token 或 SSH key）
- 数据文件（`daily_data` / `KCXQ` / `SKU Matching Table` 里的 xlsx）已被 `.gitignore` 排除，不会被推送到 GitHub
- 如果多台电脑都改代码，推送前先 `git pull` 拉取最新，避免冲突

## 数据文件放置

| 数据 | 目录 |
|---|---|
| 广告日报 Excel | `TK-GMVMAX\daily_data\`（按日期命名，支持 `8.13.xlsx` 或 `2026-08-12.xlsx`） |
| FBT 库存 Excel | `TK-GMVMAX\KCXQ\`（按日期命名，自动取最新） |
| SKU 匹配表 | `TK-GMVMAX\SKU Matching Table\` |

数据目录由安装脚本创建。文件更新后无需重启：看板每次请求自动检测源文件签名，变了就重新解析。

> 可选：在 `KCXQ` 目录放一个 `brand_keywords.json`（格式 `{"品牌名": ["关键词", ...]}`）可自定义品牌识别规则，无需改代码；文件不存在时使用内置规则。

> 可选：在面板根目录（`dashboard_server.py` 同级）放 `lifecycle_rules.json`（格式 `{"new_days": 7, "compare_days": 7, "decline_threshold": 0.3}`）可自定义素材生命周期阈值；文件更新后自动生效。

## 开发与测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

## 手动安装（不用脚本）

```powershell
# 1. 复制插件到 dsh 的 node_modules
Copy-Item tkdash-host "$env:APPDATA\npm\node_modules\@deepseek-ai\dsh\node_modules\" -Recurse -Force

# 2. 在 ~/.dsh/profiles/web/cordis.patch.yml 追加：
# - insert:
#     - id: tkdash-host
#       name: 'file:///C:/Users/<你的用户>/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/node_modules/tkdash-host/index.js'

# 3. 设置环境变量（PowerShell，永久生效）
[Environment]::SetEnvironmentVariable('DSH_TKDASH_ROOT', '<本仓库绝对路径>\TK-GMVMAX', 'User')
[Environment]::SetEnvironmentVariable('DSH_TKDASH_PYTHON', '<python.exe 绝对路径>', 'User')

# 4. 安装 Python 依赖
python -m pip install pandas openpyxl

# 5. 重启 dsh web
```

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DSH_TKDASH_ROOT` | TK-GMVMAX 看板项目目录（含 dashboard_server.py） | 本机开发路径 |
| `DSH_TKDASH_PYTHON` | python 可执行文件绝对路径 | 本机开发路径 |
| `DSH_TKDASH_SANDBOX_ROOT` | 沙箱工作根目录（一般无需设置） | dsh 沙箱策略 |

## 目录结构

```
TK-GMVMAX-DSH/
├── install.ps1        # 目标机一键安装脚本
├── tkdash-host/       # dsh 宿主插件（ESM, host-only）
│   ├── package.json
│   └── index.js       # dashboard_query 工具 + 服务管理 + 路由 + 系统提示
└── TK-GMVMAX/         # 看板服务（Python）
    ├── 启动面板.bat    # 本地双击即用入口
    ├── dashboard_server.py
    ├── data_loader.py
    ├── inventory_loader.py
    ├── common.py
    ├── requirements.txt
    └── static/        # 前端页面（广告素材 + 库存）
```

## 常见问题

- **重启后 8501 未启动**：看板服务在宿主 ready 时自动拉起；若失败，直接调用 `dashboard_query` 工具会再次尝试启动，错误信息见 dsh 日志。
- **dsh 升级（npm 重装）后插件丢失**：重跑一次安装脚本即可（install.ps1 幂等）。
- **端口被占用**：服务会扫描 8501–8512 找可用端口，`dashboard_query` 返回实际端口。
- **其他电脑数据不同**：数据文件不进入本仓库，各机器放自己的数据即可。
