# 安装与启动

## 发布资产与回退约定

稳定发布 tag 固定为 `vMAJOR.MINOR.PATCH`，正式 Release 资产固定为
`project.tar.gz`。默认安装从
`https://github.com/liyw0205/nonebot_plugin_spirit_pet/releases/latest/download/project.tar.gz`
获取资产，先尝试已核验的 `gh-proxy.com`，失败或归档无效后再直连官方地址。

核验时本仓库尚无正式 Release 资产；资产缺失或官方 URL 下载失败时安装停止，不会改取
`main` 分支归档。需要安装未发布的开发源码时使用 `--source checkout`。代理透传验证使用
xiu2 `v1.0.0` 的 `project.tar.gz`，下载 SHA-256 与 GitHub Release API 摘要一致；pet 自身
资产发布后仍需核验其实际响应。

[返回仓库](../README.md) · [安装后连接机器人](CONNECTIONS.md)

支持 Python 3.10+。Linux/Termux 安装、卸载和 `xiupet` 进程管理均由 Bash 完成。没有 Python 环境时，脚本会尝试使用系统包管理器安装 Python；Python 仅用于建立虚拟环境、安装依赖和执行 NoneBot CLI。独立安装默认获取 GitHub 最新 Release 的 `project.tar.gz`，先尝试已核验字节一致的 `gh-proxy.com`，失败后回退 GitHub 官方资产地址；不会切换到其他未验证代理。

## Linux 一键安装

默认安装最新正式版：

```bash
bash scripts/install.sh install
```

在本地 checkout 中安装当前开发源码时显式选择：

```bash
bash scripts/install.sh install --source checkout --directory "$HOME/spirit-pet-dev"
```

`install` 是默认动作，也可以把选项写在动作名前：

```bash
bash scripts/install.sh --directory "$HOME/spirit-pet" --yes --no-start
```

有正式 Release 后，可单独下载入口并获取最新 Release 资产：

```sh
curl -fL --proto '=https' --proto-redir '=https' \
  https://raw.githubusercontent.com/liyw0205/nonebot_plugin_spirit_pet/main/scripts/install.sh \
  -o install-spirit-pet.sh
bash install-spirit-pet.sh install --directory "$HOME/spirit-pet"
```

单独下载脚本默认安装到 `~/spirit-pet`，并从最新 GitHub Release 获取 `project.tar.gz`；本地 checkout 仅在显式传入 `--source checkout` 时使用。安装会创建 `.venv`、安装 `nb-cli==1.5.0` 和 `requirements.txt`，并从 `.env.example` 生成配置。不会要求预先准备 Python 虚拟环境。

Linux 自动安装系统依赖需要 root 或 sudo；Termux 使用 `pkg`。脚本支持 apt、dnf、yum、apk、pacman、zypper 和 Homebrew。准备好 Python、curl 和 tar 时可传 `--skip-system`，缺少依赖会报错且不会修改系统。

## 安装选项

| 参数 | 作用 |
| --- | --- |
| `install` / `uninstall` | 操作类型，默认 `install` |
| `--source release\|checkout` | 源码来源，默认 `release`；`checkout` 使用脚本所在的本地项目仓库 |
| `--directory PATH` | 安装目录；默认 `~/spirit-pet`；checkout 模式未指定目录时使用本地仓库 |
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
xiupet update
xiupet uninstall
```

首次安装默认以前台方式执行 `nb run`，按 Ctrl+C 停止；传 `--no-start` 后可用 `xiupet start` 后台启动。`xiupet install` 会先停止实例，再用本地源码重新安装依赖，不更新源码且不会自动重启。

`xiupet update` 只接受来源标记为 Release 的受管理安装。它先停止当前实例，再按代理优先、官方直连回退的顺序下载并校验最新 `project.tar.gz`；只替换 `src/`、`scripts/`、`pyproject.toml` 和 `requirements.txt`，然后在现有 `.venv` 中安装依赖。`.env`、`data/`（包括 SQLite、WAL 与备份）、`.xiupet/`（包括运行日志）、`.venv` 目录、其他日志和命令链接均保留，更新完成后保持停止状态，需手动执行 `xiupet start`。源码替换失败或依赖安装失败时会尝试恢复旧源码。checkout、来源标记缺失或来源未知的目录会被拒绝，不会覆盖用户源码；早期安装目录若没有来源标记，也需先人工确认来源再迁移，不应直接更新。

停止和卸载会结束机器人进程。非交互直接卸载必须显式传 `--yes`。

新安装会从 `.env.example` 创建 `.env`，生成随机 `ONEBOT_V11_ACCESS_TOKEN` 并设置文件权限；重复安装完整保留现有 `.env`。OneBot 客户端 token 必须与 `.env` 的值相同。QQBot 凭证可在之后按 [连接教程](CONNECTIONS.md) 填写。

## 源码版本与发布

推送 `vMAJOR.MINOR.PATCH` 标签会触发 GitHub Actions 测试门禁；通过后 workflow 用 `git archive` 从该 tag 检出内容生成 `project.tar.gz` 并附加到 GitHub Release。重复运行安装器会保留已有项目源码，不会覆盖或升级现有代码；它适用于新目录安装，源码更新需按当前版本的变更说明制定并验证更新步骤。

## 手动安装

已有源码和 Python 时，可直接使用虚拟环境内的 `nb` 命令启动：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'nb-cli==1.5.0' -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
.venv/bin/nb run
```

本项目没有 `bot.py` 启动入口。

当前存档 schema 为 19。安装器本身不修改数据库；启动时仅对 schema 18 执行注册时间保留迁移，迁移前会创建并验证数据库备份，原文件保留。schema 1-17、未来版本和未版本化的非空库会被拒绝且不重建，遇到 `Unsupported spirit pet schema version` 时会保留旧文件并停止启动。需要升级其他旧存档时先备份并验证，再按该版本迁移策略操作，不要更换或清空现有 `SPIRIT_PET_DB`。
