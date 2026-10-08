# 安装与启动

[返回仓库](../README.md) · [安装后连接机器人](CONNECTIONS.md)

支持 Python 3.10+。Linux/Termux 安装、卸载和 `xiupet` 进程管理均由 Bash 完成。没有 Python 环境时，脚本会尝试使用系统包管理器安装 Python；Python 仅用于建立虚拟环境、安装依赖和执行 NoneBot CLI。

## Linux 一键安装

完整仓库内直接执行：

```bash
bash scripts/install.sh install
```

单独下载入口时，脚本会从 GitHub 获取完整源码归档：

```sh
curl -fL --proto '=https' --proto-redir '=https' \
  https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/main/scripts/install.sh \
  -o install-spirit-pet.sh
bash install-spirit-pet.sh install --directory "$HOME/spirit-pet"
```

完整仓库内默认使用当前源码目录；单独下载脚本默认安装到 `~/spirit-pet`。安装会创建 `.venv`、安装 `nb-cli==1.5.0` 和 `requirements.txt`，并从 `.env.example` 生成配置。不会要求预先准备 Python 虚拟环境。

Linux 自动安装系统依赖需要 root 或 sudo；Termux 使用 `pkg`。脚本支持 apt、dnf、yum、apk、pacman、zypper 和 Homebrew。准备好 Python、curl 和 tar 时可传 `--skip-system`，缺少依赖会报错且不会修改系统。

## 安装选项

| 参数 | 作用 |
| --- | --- |
| `install` / `uninstall` | 操作类型，默认 `install` |
| `--directory PATH` | 安装目录；仓库内默认为当前仓库，单独下载脚本默认为 `~/spirit-pet` |
| `--yes` | 确认卸载，供非交互终端使用 |
| `--no-start` | 安装后不以前台方式启动 |
| `--skip-system` 或 `SPIRIT_PET_SKIP_SYSTEM=1` | 不通过系统包管理器安装依赖 |

卸载独立安装目录时会删除整个目录。直接在现有源码仓库中卸载只移除 `.venv` 和运行状态，保留源码、`.env` 与存档。

安装成功后，Linux/Termux 在 `~/.local/bin/xiupet` 生成 shell 快捷命令。若该目录不在当前 PATH 中，会显示需要添加的路径。可用命令：

```text
xiupet start
xiupet stop
xiupet restart
xiupet status
xiupet logs
xiupet install
xiupet uninstall
```

首次安装默认以前台方式执行 `nb run`，按 Ctrl+C 停止；传 `--no-start` 后可用 `xiupet start` 后台启动。停止和卸载会结束机器人进程。非交互直接卸载必须显式传 `--yes`。

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
