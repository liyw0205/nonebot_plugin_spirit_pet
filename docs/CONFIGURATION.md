# 配置与排错

本文说明当前 UID / schema 20 版本的配置、备份和排错方式。安装步骤见 [安装教程](INSTALLATION.md)。

安装器首次安装会从 `.env.example` 生成 `.env`；手动安装时执行 `cp .env.example .env`。不要只复制成 `.env.dev` 而遗漏 `ENVIRONMENT=dev` 的入口配置。已有 `.env.dev` / `.env.prod` 时 NoneBot 会读取所选环境文件，同名项可能覆盖 `.env`，请清理重复项。安装与更新保留已有配置，修改后重启生效。

| 项目 | 默认值 | 含义 |
| --- | --- | --- |
| ENVIRONMENT | `dev` | 选择额外环境文件，如 `.env.dev` |
| DRIVER | `~fastapi+~httpx+~websockets` | 服务端、HTTP 客户端、WS 客户端 |
| HOST / PORT | `127.0.0.1` / `8080` | NoneBot 监听地址；URL 目标不能填 `0.0.0.0` |
| LOG_LEVEL | `INFO` | 日志级别 |
| ONEBOT_V11_ACCESS_TOKEN | 未设置 | 仅在启用 OneBot 鉴权时手动设置；不启用时可留空或省略 |
| QQ_BOTS | `[]` | 官方机器人 JSON 数组，无账号也可启动 |
| SPIRIT_PET_DB | `data/spirit_pet/spirit_pet.db` | 相对于启动目录，建议生产使用固定绝对路径 |
| SPIRIT_PET_TRAIN_COOLDOWN | `300` | 修炼冷却秒数，最少 1 |
| SPIRIT_PET_EXPLORE_COOLDOWN | `900` | 历练冷却秒数，最少 1 |
| SPIRIT_PET_ENERGY_INTERVAL | `300` | 恢复 1 精力所需秒数，最少 1 |
| SPIRIT_PET_PVE_COOLDOWN | `600` | 单人和组队 PVE 共享冷却，按玩家记录 |
| SPIRIT_PET_PVP_COOLDOWN | `900` | 主动论剑冷却秒数，镜像防守不改变冷却 |
| SPIRIT_PET_TEAM_REQUEST_TTL | `600` | 入队申请与队伍邀请有效秒数，最少 1；到期立即不能审批 |
| SPIRIT_PET_TEAM_REQUEST_LIMIT | `10` | 每支队伍、每名候选人各自的待处理请求总上限，范围 1-100；只计未过期记录 |
| SPIRIT_PET_EXPEDITION_DURATION | `3600` | 离线委托行程秒数，最少 1；只影响新派遣，已出发行程不随配置变化 |
| SPIRIT_PET_MAX_PETS | `50` | 每名玩家宠物上限，范围 1-200 |
| SPIRIT_PET_QQ_MODE | `text` | `text` / `native` / `template` |
| SPIRIT_PET_QQ_TEMPLATE_ID | 空 | `template` 必填，QQ 审核通过的模板 ID |
| SPIRIT_PET_QQ_TEMPLATE_PARAM | `content` | 模板里的单个文本参数名 |
| SPIRIT_PET_QQ_KEYBOARD | `true` | 富消息模式显示当前页面的主要操作按钮，最多四个；text 模式忽略 |
| SPIRIT_PET_QQ_BLUE_LINKS | `true` | native 模式生成蓝字；其他模式忽略 |
| SPIRIT_PET_COMMAND_PREFIX | `/` | 插件接受的附加前缀、按钮和蓝字发送的前缀 |

本插件也接受无前缀完整中文命令，参数与命令之间必须有空格；不会将「灵宠签到后的聊天」误识别为签到。不依赖 `COMMAND_START` 才能识别这些本插件命令，不修改其他插件的匹配规则。前缀不能包含空白，设 `SPIRIT_PET_COMMAND_PREFIX=""` 可不加前缀。QQ 平台菜单是否显示指令需在开放平台单独配置。

QQ 默认 `text` 模式不要求富消息权限。`native` 需要原生 Markdown 权限，正文蓝字与按钮还取决于客户端和平台授权；`template` 需要审核通过的模板 ID、准确的参数名，不保证模板能显示动态蓝字。帮助总览与分类帮助在正文列出入口，不附加按钮网格；需要参数的入口先填入指令，补齐后再发送。具体接入步骤见 [连接机器人](CONNECTIONS.md)。

## 连接检查

| 现象 | 检查点 |
| --- | --- |
| QQ adapter requires HTTPClient | DRIVER 缺少 `~httpx` 或 `~aiohttp` |
| 本地能连、其他机器不能连 | HOST 是否为 `0.0.0.0`，防火墙和端口是否正确 |
| OneBot 401/403/1008 | token 是否一致、客户端是否带 X-Self-ID、是否重复连接同 bot |
| 反向 WS 无法连接 | 路径是 `/onebot/v11/ws`，不是 WebUI 端口或 `/qq/webhook` |
| QQ 群消息无响应 | `c2c_group_at_messages`、群权限、测试成员/群白名单、是否 @bot；普通群消息另需平台授权和订阅 |
| QQ WS 无权连接 | 按开放平台要求改用 Webhook，不反复修改 OneBot 配置 |
| QQ Webhook 失败 | HTTPS 证书、回调订阅、AppID/AppSecret、验签请求是否被代理保留 |
| QQ Markdown 回退文本 | 开放平台原生权限、模板 ID 与参数、键盘权限；先关闭键盘排查 |
| 按钮/蓝字无法显示 | 客户端版本及 QQ 审核权限；纯文本命令仍可操作 |
| 游戏突然像新服 | 是否换了工作目录或 SPIRIT_PET_DB 指向另一文件 |
| 两端人物不一致 | 同一存档内后台身份不同就是不同玩家；游戏内以 UID 交互，不提供自动绑定 |
| xiupet update 拒绝更新 | `main` 源码目录用 `git pull --ff-only origin main` 后执行 `xiupet install`，该管理命令只更新 Release 安装 |
| 更新后进程没有运行 | `xiupet install` 与 `xiupet update` 完成后保持停止，检查成功后执行 `xiupet start` |

Docker/容器中的 `127.0.0.1` 指向容器本身，不一定是 NoneBot 所在主机。本项目不要求使用容器。

## 升级与回滚

升级前先停止机器人，记录 `git rev-parse HEAD`，备份 `.env` 与数据库并验证备份。以下命令须在项目目录运行，数据库路径以实际 `SPIRIT_PET_DB` 为准，备份文件名每次换新：

```bash
xiupet stop
git rev-parse HEAD
cp .env /YOUR/BACKUP/DIRECTORY/env-pre-upgrade
.venv/bin/python scripts/database_admin.py backup data/spirit_pet/spirit_pet.db /YOUR/BACKUP/DIRECTORY/pre-upgrade.db
.venv/bin/python scripts/database_admin.py verify /YOUR/BACKUP/DIRECTORY/pre-upgrade.db
```

备份目录需提前创建，`.env` 含连接凭证，限制备份文件访问权限。SQLite 工具使用 Online Backup API，即使运行时备份也能得到一致快照；不要只复制处于 WAL 模式的主 `.db` 文件。`backup` 和 `restore` 只接受新目标路径，副本通过完整性与外键检查后才会写入最终位置。

当前版本使用 **schema 20**。空库初始化为当前版本；schema 18 先自动备份并迁移注册时间到 19，schema 19 再自动备份并为玩家分配稳定 UID 到 20。平台用户关联、灵宠、装备、资源、队伍和进度保留，不会清空玩家数据。历史注册时间仅从可核实的首次成功领养回复恢复，无记录或有歧义时显示“未记录”。自动备份位于原库旁，名称含 `schema18-backup` 或 `schema19-backup`。

18 → 19 → 20 分段迁移，各段有独立备份；不要认为后一段失败就会撤回已经完成的前一段。schema 1-17、高于 20 的版本、未版本化的非空库与不匹配的表结构会拒绝继续启动。保留原库和备份，核对启动日志与来源代码，不要删除数据、换路径或重建数据库来绕过迁移拒绝。

`main` 源码目录按以下顺序更新源码与依赖，再启动：

```bash
git pull --ff-only origin main
xiupet install
xiupet start
```

`xiupet install` 只按现有源码更新环境，不拉取或覆盖项目源码。`xiupet update` 仅适用于正式 Release 管理的目录；不要把它用于 `main` 源码安装。首次升级后可用以下命令确认数据库版本，再查看 `xiupet logs` 和 `我的信息`：

```bash
.venv/bin/python scripts/database_admin.py verify data/spirit_pet/spirit_pet.db --schema-version 20
```

需要恢复时先停止 bot，恢复命令只写入新的数据库路径，然后验证结果，再将 `SPIRIT_PET_DB` 指向恢复副本：

```bash
.venv/bin/python scripts/database_admin.py restore /YOUR/BACKUP/DIRECTORY/pre-upgrade.db data/spirit_pet/spirit_pet.restored.db
.venv/bin/python scripts/database_admin.py verify data/spirit_pet/spirit_pet.restored.db
```

默认 `verify` 检查完整性，不断言 schema；确认备份来源版本后可添加相应的 `--schema-version`。回滚时同时使用与备份 schema 对应的代码、配置和数据库，不单独降级其中一项。当前代码不会把备份降级，还原也不会迁移 schema。保留原始数据库，确认恢复副本正常前不要更改或删除它。

同一台主机的两个实例可以指向同一 SQLite 文件，但建议单个 NoneBot 进程注册两个适配器，避免重复接收、重复回复和额外数据库锁竞争。不支持网络文件系统共享数据库或异地文件实时同步。
