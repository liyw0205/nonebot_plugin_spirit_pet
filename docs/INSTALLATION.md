# 安装与启动

本文适用于仓库 `main` 分支的当前源码，包含稳定 UID、双适配器接入和完整的灵宠交互。

[用户说明](../README.md) · [安装后连接机器人](CONNECTIONS.md) · [配置与备份](CONFIGURATION.md)

## Linux / Termux 快速安装

先准备 Bash、Git 和 curl。Debian/Ubuntu 可执行 `sudo apt install -y bash git curl`，Termux 执行 `pkg install -y bash git curl`。安装器会按需准备 Python 3.10+、venv 和 tar；Linux 自动安装系统依赖需要 root 或 sudo，Termux 使用 `pkg`。

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_spirit_pet.git "$HOME/spirit-pet"
cd "$HOME/spirit-pet"
bash scripts/install.sh install --source-mode source --source "$PWD" --target "$PWD" --no-start
```

首次安装创建 `.venv`，安装 `nb-cli==1.5.0` 与 `requirements.txt`，从 `.env.example` 生成 `.env`。重复安装保留源码、现有 `.env` 与存档。按 [接入教程](CONNECTIONS.md) 填写机器人配置后启动：

```bash
xiupet start
xiupet status
xiupet logs --lines 100
```

若 `~/.local/bin` 未加入 PATH，可使用 `bash scripts/xiupet.sh start` 等同名动作；也可按安装器提示将该目录加入 PATH。每个实例使用自己的 `scripts/xiupet.sh`，同一个快捷链接不会覆盖另一个安装。

安装默认保持停止，便于先填配置；传入 `--run` 才以前台 `.venv/bin/nb run` 启动，按 Ctrl+C 停止。Termux 仍需使用当前受维护的环境，并按设备系统设置允许后台运行；安装脚本不会消除 Android 的进程限制。

## 安装选项

真实入口为仓库的 [scripts/install.sh](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/scripts/install.sh)：

| 参数 | 作用 |
| --- | --- |
| `install` / `update` / `uninstall` / `start` / `stop` / `restart` / `status` / `logs` / `login` | 动作，默认 `install`；`update` 只接受正式 Release 来源 |
| `--source-mode auto|release|source` | 源码来源模式；`source` 使用本地源码，`release` 获取最新正式 Release |
| `--source PATH` | 本地源码目录；配合 `--source-mode source` 使用 |
| `--mirror direct|accelerated|custom` | Release 下载方式；`custom` 另需 `--mirror-url URL` |
| `--target PATH` | 目标目录；默认 Release 安装到 `~/spirit-pet` |
| `--venv PATH` | 指定 Python 虚拟环境目录，默认目标目录下的 `.venv` |
| `--no-start` | 安装后不启动 |
| `--skip-system` 或 `SPIRIT_PET_SKIP_SYSTEM=1` | 已有 Python、venv、curl、tar 时跳过系统包管理器 |
| `--yes` | 卸载时确认删除，非交互卸载必填 |
| `SPIRIT_PET_PYTHON` | 指定可用的 Python 3.10+ 解释器 |
| `SPIRIT_PET_BIN_DIR` | 指定 `xiupet` 快捷命令目录，默认 `~/.local/bin` |

脚本支持 apt、dnf、yum、apk、pacman、zypper、Homebrew 与 Termux `pkg`。指定 `--skip-system` 后缺少依赖会明确报错，不自动安装系统组件。

可从 `main` 源码目录复制到一个全新空目录安装：

```bash
bash scripts/install.sh install --source-mode source --source "$PWD" \
  --target "$HOME/spirit-pet-instance" --no-start
```

副本不包含源仓库的 `.git`、`.env`、数据库与虚拟环境，拥有自己的配置与存档。已有项目目录会保留源码，重复 `install` 不会覆盖已有源码。源码目录的更新应从 `main` 获取并再次执行 `xiupet install`；`xiupet update` 只用于正式 Release 安装。

## 手动安装

先按上方命令克隆 `main`。已有 Python 3.10+ 时，在源码目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'nb-cli==1.5.0' -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
```

编辑 `.env` 后运行 `.venv/bin/nb run`。不要覆盖已有 `.env`。`ONEBOT_V11_ACCESS_TOKEN` 仅在启用 OneBot 鉴权时手动配置，不启用时可留空或省略。项目没有 `bot.py` 启动入口。

## 管理已安装实例

| 命令 | 作用 |
| --- | --- |
| `xiupet start` / `stop` / `restart` | 后台启动、停止、重启 |
| `xiupet status` | 显示进程状态与日志路径 |
| `xiupet logs --lines 100` | 查看最近日志，默认 80 行 |
| `xiupet install` | 先停止，再用本地项目重装依赖；不更新源码、不自动重启 |
| `xiupet update` | 只更新正式 Release 管理的安装，完成后保持停止 |
| `xiupet uninstall` | 停止并卸载；独立受管理目录会整目录删除 |
| `xiupet login` | 执行 QQ 官方机器人扫码授权，写入 `.env`；运行中的实例会自动重启 |

默认日志为 `.xiupet/run.log`。源码仓库卸载只移除 `.venv`、运行状态和快捷链接，保留源码、`.env`、存档；安装器复制创建的独立受管理目录会整个删除，卸载前必须另存数据库和配置。也可显式运行 `bash scripts/install.sh uninstall --directory PATH --yes`。

## 更新 `main` 源码安装

先停止机器人，按 [配置与备份](CONFIGURATION.md#升级与回滚) 记录代码版本、备份 `.env` 和数据库，检查本地源码修改；然后在原 `main` 源码目录中更新：

```bash
cd "$HOME/spirit-pet"
xiupet stop
git pull --ff-only origin main
xiupet install
xiupet start
```

有本地修改时先处理差异，不强制覆盖源码。更新后若启动失败，查看日志并保留迁移备份，按源码与数据库版本成对回滚，不清空数据库。首次迁移可能生成备份，需为数据库目录预留空间。

## Release 安装与更新

Release 版本采用 `vMAJOR.MINOR.PATCH`，归档名称为 `project.tar.gz`。Release 安装会保留现有配置、存档和运行数据。

安装器的 `--source-mode release` 会读取最新正式 Release，按 `--mirror` 选择直连或加速地址；归档无效就停止，不改用分支归档。

`xiupet update` 只接受来源标记为 `release` 的受管理安装，拒绝源码目录、缺来源标记及未知来源目录。更新先停止实例，再替换 `src/`、`scripts/`、`pyproject.toml` 与 `requirements.txt` 并安装依赖；保留 `.env`、`data/`、`.xiupet/`、`.venv`、日志与命令链接。完成后需手动 `xiupet start`；源码替换或依赖安装失败会尝试恢复旧源码。

## 存档升级

当前 UID 版本使用 schema 20。新空库可初始化；结构匹配的 schema 18/19 在启动前分别生成并验证备份后迁移，保留平台关联、灵宠、资源、队伍和进度。schema 18 先补注册时间进入 19，再迁移 UID 进入 20；无法确认的历史注册时间显示“未记录”。旧版玩家道号不再作为当前交互入口，UID 用于切磋和组队，灵宠自己的名字保留。

schema 1-17、高于 20 的版本、结构不匹配和未版本化的非空库会被拒绝。安装器不清空数据库；升级失败应保留现有库与备份，按 [升级与回滚](CONFIGURATION.md#升级与回滚) 处理。
