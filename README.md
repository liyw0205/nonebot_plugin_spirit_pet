# 灵宠仙缘

山海玄幻题材的 NoneBot2 文字灵宠游戏。项目使用本地 SQLite 保存玩家和伙伴进度，支持 OneBot V11 与 QQ 官方机器人适配器。

## 功能

- 27 种灵宠，四种初始伙伴；召唤、十连保底、灵卵孵化、名册与封存库。
- 固定 UID（从 10000 起）用于玩家之间的切磋、组队和队务；灵宠可独立命名与养成。
- 七个大境界、五阶血脉、54 条种族分支，以及签到、互动、喂养、修炼、突破和每日任务。
- 元素与天赋、技能熟练度、三槽装备、强化、套装、打造和分解。
- 一至三只不同种族的出战阵容；单人秘境、章节关卡、离线委托、收集和长期成就。
- 同族合修、双种族共鸣、组队 PVE、赛季论剑、无损切磋和永久战报。

## 安装

Linux 与 Termux 需要 Bash、Git 和 curl。Debian/Ubuntu 可执行：

```bash
sudo apt install -y bash git curl
```

Termux 可执行：

```bash
pkg install -y bash git curl
```

克隆 `main` 并运行项目安装器：

```bash
git clone --branch main --single-branch \
  https://github.com/liyw0205/nonebot_plugin_spirit_pet.git "$HOME/spirit-pet"
cd "$HOME/spirit-pet"
bash scripts/install.sh install --source checkout --directory "$PWD" --no-start
```

安装器会准备 Python 3.10+、虚拟环境、依赖和 `xiupet`，首次安装还会从 `.env.example` 创建 `.env` 并生成随机 OneBot 访问令牌。填写配置后启动：

```bash
xiupet start
xiupet status
xiupet logs --lines 100
```

如果 `xiupet` 不在 `PATH`，使用 `bash scripts/xiupet.sh start`。安装参数和 Termux 注意事项见[安装与启动](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/INSTALLATION.md)。

已有 Python 3.10+ 时也可以手动安装：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'nb-cli==1.5.0' -r requirements.txt
cp .env.example .env
.venv/bin/nb run
```

手动安装只需执行一次 `cp`；已有 `.env` 时不要覆盖它。

## 配置

最小配置示例：

```dotenv
ENVIRONMENT=dev
DRIVER=~fastapi+~httpx+~websockets
HOST=127.0.0.1
PORT=8080
SPIRIT_PET_DB=data/spirit_pet/spirit_pet.db
SPIRIT_PET_COMMAND_PREFIX=/
ONEBOT_V11_ACCESS_TOKEN=replace-with-a-random-token
QQ_BOTS='[]'
```

`SPIRIT_PET_COMMAND_PREFIX` 不能包含空白，也可以设为空字符串；无前缀的完整中文命令始终可用。QQ 的 `text`、`native` 和 `template` 模式以及账号 JSON 配置见[机器人接入](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/CONNECTIONS.md)。Markdown、按钮和蓝字需要相应的平台权限与客户端支持，权限不足时使用普通文本命令。

OneBot V11 反向 WebSocket 地址为：

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

QQ 官方机器人使用开放平台的 AppID、AppSecret 和已获授权的事件订阅；凭证只写入 `.env`，不要提交到仓库。两个适配器共用同一数据库时，只有后台用户 ID 完全相同才是同一玩家，不会自动绑定不同账号。

## 常用命令

首次进入游戏：

```text
灵宠领养 青鸾
我的信息
我的灵宠
灵宠帮助
灵宠签到
灵宠修炼
灵宠命名 小青
```

玩家之间的操作使用 UID，灵宠操作使用名册中的编号：

```text
灵宠切磋 10001
灵宠入队 10001
灵宠列表
灵宠出战 1 2 3
灵宠合修
灵宠共鸣
```

完整玩法和指令见[玩法说明](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/GAMEPLAY.md)。

## 管理与存档

```text
xiupet start
xiupet stop
xiupet restart
xiupet status
xiupet logs --lines 100
xiupet install
xiupet uninstall
```

更新当前 checkout 前先停止实例、备份 `.env` 和数据库，再从 `main` 更新：

```bash
cd "$HOME/spirit-pet"
xiupet stop
git pull --ff-only origin main
xiupet install
xiupet start
```

默认数据库为 `data/spirit_pet/spirit_pet.db`。当前 schema 为 20；schema 18 会备份后补齐注册时间迁移到 19，schema 19 会备份后建立稳定 UID 映射迁移到 20，玩家、灵宠、资源和进度都会保留。schema 1-17、高于 20 的版本及结构不匹配的非空库会拒绝启动，不会清空原文件。使用 SQLite Online Backup API 做一致性备份和恢复，详见[配置与排错](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/CONFIGURATION.md)。

## 文档

- [安装与启动](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/INSTALLATION.md)
- [机器人接入](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/CONNECTIONS.md)
- [配置与排错](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/CONFIGURATION.md)
- [玩法说明](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/docs/GAMEPLAY.md)
- [变更记录](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/CHANGELOG.md)

## 许可证

本项目采用 [MIT License](https://github.com/liyw0205/nonebot_plugin_spirit_pet/blob/main/LICENSE).
