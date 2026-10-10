# 灵宠仙缘

山海玄幻题材的 NoneBot2 文字宠物游戏，与灵宠一起修炼、探索秘境、组队和论剑。支持 **OneBot V11** 与 **QQ 官方机器人**，使用本地 SQLite 保存伙伴与玩家进度，无需 MySQL。

本文与下方教程适用于 [develop 版本](https://github.com/liyw0205/nonebot_plugin_spirit_pet/tree/develop)。仓库默认 `main` 的旧源码尚不包含当前 UID 与交互功能，请按下方命令选择 `develop`。

## 能力概览

- 27 种山海灵宠，四种初始可选；召唤、十连珍稀保底、灵卵孵化与可逆封存。
- 玩家使用从 10000 起的固定 UID 交互；每只灵宠可以单独命名与养成。
- 七个大境界、每境十层，五阶血脉与 54 条种族分支；每日签到、互动、喂养、修炼、突破和任务。
- 主副元素、天赋神通、技能熟练度、三槽装备、强化、套装、打造分解与双种族共鸣。
- 一至三只不同种族灵宠组成阵容；16 处秘境、八处章节关卡、离线委托、收集与长期成就。
- 二至三人组队，整队最多五只灵宠；申请与邀请需确认，全员准备后出征，每名成员独立领奖。
- 镜像论剑、无损切磋、自然月赛季与永久战报，无需对手在线。
- QQ 可使用 Markdown、少量主要操作按钮和正文蓝字；OneBot 与纯文本模式可直接发送中文指令。

## 快速安装

Linux 与 Termux 使用同一个 Bash 安装器。先准备 Bash、Git 和 curl：Debian/Ubuntu 可运行 `sudo apt install -y bash git curl`，Termux 可运行 `pkg install -y bash git curl`。再安装当前源码：

```bash
git clone --branch develop --single-branch \
  https://github.com/liyw0205/nonebot_plugin_spirit_pet.git "$HOME/spirit-pet"
cd "$HOME/spirit-pet"
bash scripts/install.sh install --source checkout --directory "$PWD" --no-start
```

安装器会准备 Python 3.10+、虚拟环境、依赖和 `xiupet` 管理命令，首次生成 `.env` 与随机 OneBot 访问令牌。按下方最小配置连接机器人后执行 `xiupet start`。若命令不在 PATH，可使用 `bash scripts/xiupet.sh start`。

当前尚无可下载的正式 `project.tar.gz`，`releases/latest/download/project.tar.gz` 返回 404。不要省略 `--source checkout`，也不要用旧 `main` 安装脚本代替以上入口。完整参数、Termux 环境与未来 Release 安装见 [安装教程](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/INSTALLATION.md)。

## 手动安装

已有 Python 3.10+ 时，先按上方命令克隆 `develop`，然后在源码目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'nb-cli==1.5.0' -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
```

编辑 `.env` 并配置适配器后，使用 `.venv/bin/nb run` 前台启动。项目没有 `bot.py` 入口；手动安装若需要 `xiupet` 快捷命令，可在同一源码目录运行上述 checkout 安装器。

## 最小配置

安装器已生成 `.env`，重复安装会保留它。关键字段如下；OneBot 的令牌应使用安装器生成的实际值，手动安装时自行设置：

```dotenv
ENVIRONMENT=dev
DRIVER=~fastapi+~httpx+~websockets
HOST=127.0.0.1
PORT=8080
SPIRIT_PET_DB=data/spirit_pet/spirit_pet.db
SPIRIT_PET_COMMAND_PREFIX=/
ONEBOT_V11_ACCESS_TOKEN=replace-with-your-random-token
QQ_BOTS='[]'
```

`SPIRIT_PET_COMMAND_PREFIX` 可以改为空字符串或其他无空格前缀，按钮与蓝字会使用同一配置；无前缀完整中文命令始终可用。已有 `.env.dev` 或 `.env.prod` 时检查同名覆盖项，修改配置后重启。

## 连接机器人

**OneBot V11 / NapCat：**在客户端新增反向 WebSocket 连接，地址为 `ws://127.0.0.1:8080/onebot/v11/ws`，token 与 `.env` 一致。跨主机时填写 NoneBot 主机地址并调整监听与网络访问规则。NapCat 是可选 OneBot 实现，不是游戏必需组件。

**QQ 官方机器人：**用 AppID、AppSecret 配置 `QQ_BOTS`，按开放平台权限选择 WebSocket 或 Webhook 接入。普通群 @ 消息与已获权限的群全量消息均可路由中文命令；是否推送全量事件取决于平台订阅。先使用 `SPIRIT_PET_QQ_MODE=text`，再按已获权限启用 `native` 或 `template`。

两个适配器共用同一数据库，只有原始平台 ID 字符串完全相同才共享玩家；不同 ID 不自动绑定。UID 是游戏内固定编号，不是 QQ 号码或 OpenID。

AppID 配置、Webhook、Markdown、按钮和蓝字说明见 [接入教程](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/CONNECTIONS.md)。

## 开始游戏

```text
灵宠领养 青鸾
我的信息
我的灵宠
灵宠帮助
灵宠签到
灵宠修炼
灵宠命名 小青
```

初始伙伴可选青鸾、玄狐、白泽或蛟龙；领养成功会显示 UID 与伙伴信息，并自动出战。QQ 群聊一般先 @机器人，私聊直接发送指令。可用 `灵宠帮助 成长`、`灵宠帮助 秘境与关卡` 等分类查看玩法。

与其他玩家切磋或组队使用对方的 UID，例如 `灵宠切磋 10001`、`灵宠入队 10001`。宠物编号用于 `灵宠出战 1 2 3` 等伙伴操作，与玩家 UID 分开。完整指令和规则见 [玩法说明](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/GAMEPLAY.md)。

## 管理与更新

```text
xiupet start
xiupet stop
xiupet restart
xiupet status
xiupet logs --lines 100
```

当前推荐直接在 Git checkout 中安装。升级前先停止实例，再按下方备份教程备份配置与数据库，然后更新同一分支：

```bash
cd "$HOME/spirit-pet"
xiupet stop
git pull --ff-only origin develop
xiupet install
xiupet start
```

本地有源码修改时先处理差异，不强制覆盖。`xiupet install` 只重装当前源码的依赖，不更新源码且不自动重启；`xiupet update` 仅用于未来 Release 管理的安装，不接受 checkout 目录。若将 checkout 复制安装到另一个目录，该副本没有 Git 更新入口，更新方式见安装教程。

`xiupet uninstall` 会停止实例并卸载；独立受管理安装目录会整目录删除，先备份存档。直接在源码仓库安装时，卸载保留源码、配置和存档。

## 备份与排错

玩家数据库默认位于 `data/spirit_pet/spirit_pet.db`。使用 `scripts/database_admin.py` 做一致性备份，不要只复制处于 WAL 模式的主 `.db` 文件。当前 UID 版本使用 schema 20，schema 18/19 升级先自动备份再迁移；升级及回滚应配对源码、配置与数据库版本。

启动失败先查看 `xiupet logs`；连接失败核对监听端口、令牌与 QQ 平台订阅；存档像新服时核对启动目录与 `SPIRIT_PET_DB`。具体命令和恢复步骤见 [配置、备份与排错](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/CONFIGURATION.md)。QQ 富消息呈现取决于平台权限与客户端，Termux 也需核对实际设备环境。

## 文档

| 文档 | 内容 |
| --- | --- |
| [安装与更新](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/INSTALLATION.md) | Linux / Termux、checkout 安装、管理命令与更新 |
| [机器人接入](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/CONNECTIONS.md) | OneBot 反向 WS、QQ 官方、消息模式 |
| [配置与排错](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/CONFIGURATION.md) | 参数、数据库备份、升级和恢复 |
| [玩法说明](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/docs/GAMEPLAY.md) | UID、伙伴养成、阵容、对战、队伍与收集 |
| [变更记录](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/develop/CHANGELOG.md) | 版本变化 |

## 许可证

本项目采用 [MIT License](LICENSE)。
