# 安装与启动

[返回仓库](../README.md) · [安装后连接机器人](CONNECTIONS.md)

支持 Python 3.10 至 3.x，Linux / Windows 推荐 3.11 或 3.12；Termux 使用发行版 Python。安装顺序为：检查或安装 Python → 创建虚拟环境 → 安装 **`nb-cli==1.5.0`** → 使用 `nb` 安装驱动和适配器 → 校验项目配置及依赖 → 配置 `.env` → 前台启动。

脚本安装 `fastapi/httpx/websockets` 三个驱动、OneBot V11 和 QQ 两个适配器，并按仓库 `requirements.txt` 补齐最低版本依赖。不安装 NapCat，不更改全局 pip 镜像，不升级系统 pip。NapCat 只是可选的 OneBot V11 客户端。

## Linux 一键安装

先将入口下载到本地，再运行，不使用 `curl | sh`：

```bash
curl -fL --proto '=https' --proto-redir '=https' \
  https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/main/scripts/install.sh \
  -o install-spirit-pet.sh
bash install-spirit-pet.sh --directory "$HOME/spirit-pet"
```

可先用文本编辑器检查下载的脚本。首次获取入口需要能访问 GitHub；也可在浏览器下载入口，或使用下文列出的已核验上游代理前缀。脚本执行后的引导器与项目源码下载都会检测五个来源，不将 HTTP 200 的 HTML 页面当作成功。

Debian/Ubuntu 缺少 Python/venv 时自动通过 `apt-get` 安装必要包，非 root 用户需要 `sudo`；Fedora 系使用 `dnf`。不会执行系统全量升级或安装后台服务。不支持的发行版、Python 低于 3.10 时，请先安装合适的 Python。已准备好系统依赖时可跳过系统包步骤：

```bash
SPIRIT_PET_SKIP_SYSTEM=1 SPIRIT_PET_PYTHON=python3.12 \
  bash install-spirit-pet.sh --directory "$HOME/spirit-pet" --no-start
```

下载了完整仓库时，直接在仓库内运行 `bash scripts/install.sh`，默认使用本仓库目录，不重复下载、不覆盖源代码。

## Windows 一键安装

使用 Windows PowerShell 5.1 或 PowerShell 7，先下载脚本，再启动独立进程运行：

```powershell
Invoke-WebRequest -UseBasicParsing `
  -Uri "https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/main/scripts/install.ps1" `
  -OutFile "install-spirit-pet.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\install-spirit-pet.ps1" `
  -Directory "$HOME\spirit-pet"
```

这里只对当前 PowerShell 进程放行脚本，不更改系统执行策略。无需运行虚拟环境的 `Activate.ps1`。若没有可用 Python，脚本尝试通过 `winget` 安装用户范围的 Python 3.12；没有 `winget` 时会停止并提示从 python.org 安装，重新打开终端后重试。已有 Python 可通过 `$env:SPIRIT_PET_PYTHON` 指定完整可执行文件路径。

已有完整仓库时运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\install.ps1" -NoStart
```

路径含空格时保留双引号，例如 `-Directory "D:\QQ Bots\Spirit Pet"`。脚本不要求 Git，也不需要管理员权限来创建项目和虚拟环境。

## Termux 一键安装

使用仍受维护的 Termux 版本。在 Termux 中准备下载工具并运行同一个自动识别平台的入口：

```bash
pkg update
pkg install curl
curl -fL --proto '=https' --proto-redir '=https' \
  https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/main/scripts/install.sh \
  -o install-spirit-pet.sh
bash install-spirit-pet.sh --directory "$HOME/spirit-pet"
```

完整仓库也提供明确的 Termux 入口：`bash scripts/install_termux.sh`。`install_termux.sh` 是本地分发入口，不单独下载；单文件自举使用上面的 `install.sh`。

Termux 安装器会通过 `pkg` 准备 Python、curl、clang、rust、make、pkg-config、OpenSSL 和 libffi，供缺少 Android wheel 的依赖编译使用。按参考项目实际脚本创建 `venv --system-site-packages`，允许复用已经安装的 Termux 原生扩展；新增 Python 包仍安装到虚拟环境，不改写系统 pip。Linux/Windows 默认不共享系统包。

如果 NoneBot 或适配器来自系统包，安装器只把这些包的同一版本单独安装到虚拟环境，不重装它们的原生依赖，也不卸载系统版本，避免 `nonebot.adapters` 不能跨两个包目录发现适配器的问题。

首次编译 `watchfiles/pydantic-core/cryptography` 可能较久。Android wheel 和构建工具版本可能导致失败，错误日志会保留在终端，不会假报安装成功。若出现 `dlopen failed`、`PyExc_RuntimeError` 等原生扩展错误，先检查失败包的 Android 构建和系统已有版本；不要反复升级系统 pip。可显式选择已有可用环境，但这会将该环境的 NB CLI 调整为 1.5.0：

```bash
SPIRIT_PET_SKIP_SYSTEM=1 bash scripts/install_termux.sh --venv "$HOME/myenv" --no-start
```

默认使用项目自己的 `.venv`，不会擅自改动 `$HOME/myenv`。保持后台运行可另行执行 `termux-wake-lock`，但 Android 仍可能回收进程，安装器不会声称已配置永久后台服务。

## 安装选项与配置

| Linux / Termux | PowerShell | 作用 |
| --- | --- | --- |
| `--directory PATH` | `-Directory PATH` | 新安装目录；本地仓库默认为当前源码位置，独立入口默认为 `~/spirit-pet` |
| `--venv PATH` | `-Venv PATH` | 显式使用已有/新虚拟环境，默认项目下 `.venv` |
| `--branch main` / `--branch develop` | `-Branch main` / `-Branch develop` | 新源码下载分支；不会自动切换或更新已有目录 |
| `--host 127.0.0.1` | `-ListenHost 127.0.0.1` | 新 `.env` 监听地址 |
| `--port 8080` | `-Port 8080` | 新 `.env` 监听端口，1-65535 |
| `--yes` | `-Yes` | 非交互安全默认值，QQ 凭证留待后续填写 |
| `--no-start` | `-NoStart` | 安装配置后退出，不启动机器人 |

交互终端首次安装时可选择 OneBot V11、QQBot 或同时接入；QQ AppSecret 隐藏输入，QQ 连接可选 WebSocket/Webhook。不输入 QQ AppID 时保留 `QQ_BOTS='[]'`，随后按 [连接教程](CONNECTIONS.md) 填写。默认先使用纯文本模式验证连接，Markdown/按钮/蓝字还需要 QQ 平台对应权限。

新 `.env` 自动生成随机 `ONEBOT_V11_ACCESS_TOKEN`，不会在安装日志显示凭证。OneBot 客户端的 token 要与该值一致。Linux/Termux 的新 `.env` 权限为 600。默认 `HOST=127.0.0.1`；局域网接入需显式设置 `--host 0.0.0.0`，并按连接教程限制防火墙入站。

重复运行安装器会保留已有 `.env`、`.env.dev`、数据库和源代码，既有配置时新传入的 host/port 不会覆盖文件。不识别的非空目录或损坏的虚拟环境会拒绝覆盖。它是安装器，不是更新/重装工具；不会删除数据库、自动迁移存档或在后台启动多个服务。

## 下载来源

五个候选来源为 GitHub 官方直连，以及上游安装脚本实际列出的四个代理前缀：

```text
官方：不加前缀
https://gh-proxy.com/
https://gh.jasonzeng.dev/
https://git.yylx.win/
https://wget.la/
```

代理拼接方式是 `代理前缀 + 完整 GitHub URL`，不是 PyPI 镜像。每个来源分别显示成功/失败、耗时和诊断，全部测完才选择最低耗时的有效响应。失败来源不算可用；全部失败时停止，提示检查 DNS/TLS/网络或改用完整本地源码。第三方代理的可用性会变化，源码仍属于供应链信任范围，测速和格式校验不是数字签名验证。

引导 Python 文件必须有预期标识且能通过 AST 解析；源码包必须为完整 gzip/tar、包含本项目关键文件，限制下载/解压大小，并拒绝路径穿越、链接、设备文件、重复路径和不完整项目。源码包在临时目录验证后才复制到新目录，不执行下载响应中的 shell 片段。

## 手动安装

已有完整源码、Python 和可用虚拟环境时，可复现安装器的核心步骤。以下以 Linux/Termux 的 `.venv/bin/` 为例，Windows 改为 `.venv\Scripts\`：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "nb-cli==1.5.0"
.venv/bin/python -m nb_cli driver install "nonebot2[fastapi]"
.venv/bin/python -m nb_cli driver install "nonebot2[httpx]"
.venv/bin/python -m nb_cli driver install "nonebot2[websockets]"
.venv/bin/python -m nb_cli adapter install nonebot.adapters.onebot.v11
.venv/bin/python -m nb_cli adapter install nonebot.adapters.qq
.venv/bin/python -m pip install -r requirements.txt
```

Termux 第一条按平台换为 `python -m venv --system-site-packages .venv`。手动 `nb` 命令会改写当前项目配置；自动安装器在临时配置副本中执行，保留原始 `pyproject.toml` 字节。首次手动安装再从 `.env.example` 创建 `.env` 并填写连接参数，已有 `.env` 不要覆盖。

这里使用完整驱动包名、适配器模块名进行精确匹配。NB CLI 1.5.0 对短名称会做子串搜索，例如当前商店中的 `httpx` 同时匹配 HTTPX 和 HTTPX2，直接照抄旧脚本短名称会报 `No or multiple packages found`。`python -m nb_cli` 是同一套 `nb` 命令入口，能保证使用所选虚拟环境，也兼容 Termux 复用系统 NB CLI 包时没有虚拟环境内 `nb` 可执行文件的情况。

仓库配置直接沿用参考项目安装脚本的 `[project]`、`[tool.nonebot]`、`[tool.nonebot.adapters]`、`[tool.nonebot.plugins]` 格式，并使用 `plugin_dirs = ["src/plugins"]`。不会猜测生成另一种配置格式，也不运行 `nb init` 替换现有项目。

## 启动与更新

在项目目录运行，所有平台都无需激活环境：

```bash
# Linux / Termux
.venv/bin/python bot.py
```

```powershell
# Windows
.venv\Scripts\python.exe bot.py
```

安装器默认最后以前台方式启动，`Ctrl+C` 停止。首次启动会创建 `data/spirit_pet/spirit_pet.db`；没有 OneBot 客户端或 QQ 凭证也可启动监听。连接地址及配置格式见 [CONNECTIONS.md](CONNECTIONS.md)。

已有 NoneBot 项目可将整个 `src/plugins/nonebot_plugin_spirit_pet/` 放入自己的插件目录，保留其静态 `data/` 与 `storage/schema.sql`，安装对应依赖并注册所需适配器。不要将完整项目安装器指向不相关的机器人项目。

当前未发布稳定版，更新前停止 bot，备份 `.env`、运行数据目录和代码版本。`Unsupported spirit pet schema version` 会明确拒绝旧库，不迁移、不删除；开发测试可换新的 `SPIRIT_PET_DB` 路径。插件内 `data/*.json` 是静态内容，仓库根的 `data/spirit_pet/` 才是默认存档目录。

## 参考依据

核验上游版本：`nonebot_plugin_xiuxian_2_pmv@97f43acba8dd185111d998c48d4e1cf5a069b117`：

- [Linux 安装脚本](https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv/blob/97f43acba8dd185111d998c48d4e1cf5a069b117/scripts/install.sh)：pyproject 布局、代理列表、gzip 校验思路。
- [Termux 安装脚本](https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv/blob/97f43acba8dd185111d998c48d4e1cf5a069b117/scripts/install_termux.sh)：系统构建依赖、共享系统包的虚拟环境方式。
- [Windows 安装脚本](https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv/blob/97f43acba8dd185111d998c48d4e1cf5a069b117/scripts/install.bat)：固定 `nb-cli==1.5.0`、`nb driver install` 与 `nb adapter install` 的命令顺序。

上游 Linux/Termux 当前改为 pip 安装最新版；本项目按明确需求统一固定 NB CLI 1.5.0，不照搬最新版升级、全局 pip 配置或删除重装行为。
