# 安装与启动

[返回仓库](../README.md) · [安装后连接机器人](CONNECTIONS.md)

支持 Python 3.10-3.13。Linux/Termux 的安装、更新、卸载和 `xiupet` 进程管理都由 Bash 脚本完成。Python 仅用于建立虚拟环境、安装运行依赖和执行 NoneBot CLI。

## Linux 一键安装

先下载脚本再执行，不使用 `curl | sh`：

```bash
curl -fL --proto '=https' --proto-redir '=https' \
  https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/main/scripts/install.sh \
  -o install-spirit-pet.sh
bash install-spirit-pet.sh install --directory "$HOME/spirit-pet"
```

安装器先查找 Python 3.10+、`venv` 和 `ensurepip`。没有可用环境时会尝试通过系统包管理器安装 Python、curl 和解压工具；支持 Debian/Ubuntu、Fedora、RHEL、Alpine、openSUSE、Arch 与 Homebrew。Linux 自动安装系统依赖需要 root 或 sudo。准备好依赖时可传 `--skip-system`，这时缺少 Python 或 curl 会直接报错，不修改系统。

安装器下载并检查完整源码归档，选择验证成功且较快的来源，再复制到项目目录。下载入口和完整仓库内的入口走同一套 Bash 实现。新项目创建 `.venv` 并安装 `nb-cli==1.5.0` 与 `requirements.txt`；不要求事先准备虚拟环境。

完整仓库内默认安装到当前仓库。下载单文件入口时默认安装到 `~/spirit-pet`。例如：

```bash
bash scripts/install.sh install --directory "$HOME/spirit-pet" --yes --no-start
SPIRIT_PET_SKIP_SYSTEM=1 bash scripts/install.sh update-deps --directory "$HOME/spirit-pet" --yes
bash scripts/install.sh uninstall --directory "$HOME/spirit-pet" --yes
```

Termux 使用与 Linux 相同的安装脚本；需要先有 `curl` 下载入口，之后脚本通过 `pkg` 安装 Python、编译工具和 `curl`，使用 `venv --system-site-packages` 以复用 Termux 原生扩展。后台运行时可执行 `termux-wake-lock`，但 Android 仍可能回收进程。

已有完整仓库时，在仓库目录运行 `bash scripts/install.sh install`。安装不会覆盖已有 `.env`、数据库或 Git 工作区改动。

## 安装选项

| Bash 参数 | 作用 |
| --- | --- |
| `install` / `uninstall` / `reinstall` / `update` / `update-deps` | 操作类型，默认 `install` |
| `--directory PATH` | 安装目录；源码仓库内默认为当前仓库，单文件入口默认为 `~/spirit-pet` |
| `--venv PATH` | 指定新建或已有虚拟环境，默认项目下 `.venv` |
| `--branch main` / `--branch develop` | 新源码下载使用的分支 |
| `--host 127.0.0.1` | 新 `.env` 的监听地址 |
| `--port 8080` | 新 `.env` 的监听端口，范围 1-65535 |
| `--yes` | 确认卸载等破坏性操作，供非交互终端使用 |
| `--no-start` | 安装后不以前台方式启动 |
| `--skip-system` 或 `SPIRIT_PET_SKIP_SYSTEM=1` | 不自动安装系统级 Python/工具 |

`install` 保留已有项目源码；`update` 对干净 Git 工作区执行 `git pull --ff-only`，对源码归档安装更新程序文件；`reinstall` 只重建已验证的项目虚拟环境；`update-deps` 只重装依赖。更新和重装不会删除 `.env` 或数据库。Git 工作区有修改或处于 detached HEAD 时，更新会拒绝继续。

安装成功后，Linux/Termux 在 `~/.local/bin/xiupet` 生成 shell 快捷命令。若该目录不在当前 PATH 中，会显示需要添加的路径。可用命令：

```text
xiupet start
xiupet stop
xiupet restart
xiupet status
xiupet logs
xiupet update
xiupet update-deps
xiupet uninstall
```

首次安装默认以前台方式执行 `nb run`，按 Ctrl+C 停止；传 `--no-start` 后可在项目目录运行 `nb run`，或使用 `xiupet start` 后台启动。停止和卸载会结束机器人进程。非交互卸载必须显式传 `--yes`。

新安装会从 `.env.example` 创建 `.env`，生成随机 `ONEBOT_V11_ACCESS_TOKEN` 并设置文件权限；重复安装完整保留现有 `.env`。OneBot 客户端 token 必须与 `.env` 的值相同。QQBot 凭证可在之后按 [连接教程](CONNECTIONS.md) 填写。

## 手动安装

已有源码和 Python 时，可直接使用虚拟环境内的 `nb` 命令启动：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'nb-cli==1.5.0' -r requirements.txt
cp .env.example .env
.venv/bin/nb run
```

本项目没有 `bot.py` 启动入口。

当前存档 schema 为 12。安装器不迁移不兼容的旧开发库；遇到 `Unsupported spirit pet schema version` 时会保留旧文件并停止启动。需要保留旧存档时先备份，再为新版本设置新的 `SPIRIT_PET_DB` 路径。
