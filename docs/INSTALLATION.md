# 安装与启动

[返回仓库](../README.md) · [安装后连接机器人](CONNECTIONS.md)


支持 Python 3.10 及以上；推荐 Python 3.11 或 3.12。项目的 `pyproject.toml` 和源码目录采用参考项目安装脚本的格式：项目配置使用 `[project]`、`[tool.nonebot]`、`[tool.nonebot.adapters]`、`[tool.nonebot.plugins]`；插件位于 `src/plugins/nonebot_plugin_spirit_pet/`，由 `plugin_dirs = ["src/plugins"]` 发现。

### Linux

Debian / Ubuntu 安装系统依赖：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

克隆并启动：

```bash
git clone https://github.com/liyw0205/nonebot_plugin_spirit_pet.git
cd nonebot_plugin_spirit_pet
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python bot.py
```

发行版的 Python 包管理器要求使用虚拟环境时，以上方式已满足，不要以 `sudo pip install` 安装项目依赖。

### Windows

安装 Python 3.11+ 和 Git。使用 PowerShell：

```powershell
git clone https://github.com/liyw0205/nonebot_plugin_spirit_pet.git
Set-Location nonebot_plugin_spirit_pet
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe bot.py
```

PowerShell 中如遇脚本执行策略限制，不必运行虚拟环境的 `Activate.ps1`；直接使用上面的 `.venv\Scripts\python.exe` 即可。NapCat 桌面端和 NoneBot 如果分处两台电脑，把后面说明中的 `127.0.0.1` 改成运行 NoneBot 的电脑局域网地址。

### Termux

在 Termux 安装 Python、Git：

```bash
pkg update
pkg install python git
git clone https://github.com/liyw0205/nonebot_plugin_spirit_pet.git
cd nonebot_plugin_spirit_pet
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
termux-wake-lock
.venv/bin/python bot.py
```

原生 Termux 若提示 `pydantic-core`、`cryptography` 等依赖缺少预编译 wheel，可先安装构建依赖再重试原安装命令：

```bash
pkg install clang rust make pkg-config openssl libffi
```

不要升级 Termux 系统的 pip 来绕过构建错误；使用发行版提供的 Python/pip。已有可用虚拟环境时无需重建，例如 `$HOME/myenv/bin/python -m pip install -r requirements.txt`、`$HOME/myenv/bin/python bot.py`。本项目在 Termux 的既有 `myenv` 环境完成测试；全新 Termux 依赖编译是否成功仍取决于其系统和包版本。

需要让局域网内的 NapCat 主动连接到 Termux 时，在 `.env` 把 `HOST=127.0.0.1` 改为 `HOST=0.0.0.0`，然后在 NapCat 的 WebSocket 客户端配置里填写 Termux 的局域网 IP。Termux 与 NapCat 在同一台 Android 设备时可使用 `127.0.0.1`。Android 后台可能会回收进程；`termux-wake-lock` 用于减少休眠影响，不保证系统永不杀进程。

首次启动会在 `data/spirit_pet/spirit_pet.db` 自动创建游戏数据库。请备份整个 `data/spirit_pet/` 目录；备份前先停止 bot。


## 已有 NoneBot 项目

将整个 `src/plugins/nonebot_plugin_spirit_pet/` 目录复制到已有项目的插件目录，保留其中的 `data/` 和 `storage/schema.sql`；安装 `requirements.txt` 中的依赖，注册所需适配器并加载该插件。不要覆盖已有 `.env` 或数据库。

## 更新开发版

当前未发布稳定版本，结构与存档格式允许直接重构。更新前停止 bot，备份 `.env`、整个运行数据目录与代码版本。若提示 `Unsupported spirit pet schema version`，代码不会迁移或删除旧库；保留备份，改用新的 `SPIRIT_PET_DB` 路径创建测试存档。需要旧存档时使用对应版本的代码和数据库，不能只回退其中一项。

插件内 `data/*.json` 是随代码分发的静态内容，不是玩家存档。仓库根 `data/spirit_pet/` 才是默认运行数据目录。
