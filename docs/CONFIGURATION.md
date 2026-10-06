# 配置与排错

首次启动把 `.env.example` 复制为 `.env`，不要只复制成 `.env.dev` 而遗漏 `ENVIRONMENT=dev` 的入口配置。已有 `.env.dev` 时 NoneBot 会继续读取它；同名项可能覆盖 `.env`，请清理重复项。安装更新不要覆盖已有配置。

| 项目 | 默认值 | 含义 |
| --- | --- | --- |
| DRIVER | `~fastapi+~httpx+~websockets` | 服务端、HTTP 客户端、WS 客户端 |
| HOST / PORT | `127.0.0.1` / `8080` | NoneBot 监听地址；URL 目标不能填 `0.0.0.0` |
| ONEBOT_V11_ACCESS_TOKEN | 未设置 | 对外开放 OneBot 端口前设置随机令牌 |
| QQ_BOTS | `[]` | 官方机器人 JSON 数组，无账号也可启动 |
| SPIRIT_PET_DB | `data/spirit_pet/spirit_pet.db` | 相对于启动目录，建议生产使用固定绝对路径 |
| SPIRIT_PET_TRAIN_COOLDOWN | `300` | 修炼冷却秒数，最少 1 |
| SPIRIT_PET_EXPLORE_COOLDOWN | `900` | 历练冷却秒数，最少 1 |
| SPIRIT_PET_ENERGY_INTERVAL | `300` | 恢复 1 精力所需秒数，最少 1 |
| SPIRIT_PET_PVE_COOLDOWN | `600` | 单人和组队 PVE 共享冷却，按玩家记录 |
| SPIRIT_PET_PVP_COOLDOWN | `900` | 论剑冷却秒数，双方各自结算 |
| SPIRIT_PET_INVITATION_TTL | `300` | 论剑/切磋邀请有效秒数 |
| SPIRIT_PET_TEAM_REQUEST_TTL | `600` | 入队申请与队伍邀请有效秒数，最少 1；到期立即不能审批 |
| SPIRIT_PET_TEAM_REQUEST_LIMIT | `10` | 每支队伍、每名候选人各自的待处理请求总上限，范围 1-100；只计未过期记录 |
| SPIRIT_PET_MAX_PETS | `50` | 每名玩家宠物上限，范围 1-200 |
| SPIRIT_PET_QQ_MODE | `text` | `text` / `native` / `template` |
| SPIRIT_PET_QQ_TEMPLATE_ID | 空 | `template` 必填，QQ 审核通过的模板 ID |
| SPIRIT_PET_QQ_TEMPLATE_PARAM | `content` | 模板里的单个文本参数名 |
| SPIRIT_PET_QQ_KEYBOARD | `true` | 富消息模式附加指令键盘；text 模式忽略 |
| SPIRIT_PET_QQ_BLUE_LINKS | `true` | native 模式生成蓝字；其他模式忽略 |
| SPIRIT_PET_COMMAND_PREFIX | `/` | 插件接受的附加前缀、按钮和蓝字发送的前缀 |

本插件也接受无前缀完整中文命令，参数与命令之间必须有空格；不会将「灵宠签到后的聊天」误识别为签到。不依赖 `COMMAND_START` 才能识别这些本插件命令，不修改其他插件的匹配规则。QQ 平台菜单是否显示指令需在开放平台单独配置。

## 连接检查

| 现象 | 检查点 |
| --- | --- |
| QQ adapter requires HTTPClient | DRIVER 缺少 `~httpx` 或 `~aiohttp` |
| 本地能连、其他机器不能连 | HOST 是否为 `0.0.0.0`，防火墙和端口是否正确 |
| OneBot 401/403/1008 | token 是否一致、客户端是否带 X-Self-ID、是否重复连接同 bot |
| 反向 WS 404 | 路径是 `/onebot/v11/ws`，不是 WebUI 端口或 `/qq/webhook` |
| QQ 群消息无响应 | `c2c_group_at_messages`、群权限、测试成员/群白名单、是否 @bot |
| QQ WS 无权连接 | 按开放平台要求改用 Webhook，不反复修改 OneBot 配置 |
| QQ Webhook 失败 | HTTPS 证书、回调订阅、AppID/AppSecret、验签请求是否被代理保留 |
| QQ Markdown 回退文本 | 开放平台原生权限、模板 ID 与参数、键盘权限；先关闭键盘排查 |
| 按钮/蓝字无法显示 | 客户端版本及 QQ 审核权限；纯文本命令仍可操作 |
| 游戏突然像新服 | 是否换了工作目录或 SPIRIT_PET_DB 指向另一文件 |
| 两端人物不一致 | 后台身份不同就是不同玩家；游戏内以道号交互，不提供自动绑定 |

Docker/容器中的 `127.0.0.1` 指向容器本身，不一定是 NoneBot 所在主机。本项目不要求使用容器。

## 升级与回滚

1. 停止 bot，记录当前 `git rev-parse HEAD`，备份 `.env` 和整个数据目录。
2. 运行 `git pull --ff-only`，仅在需要时使用同一个虚拟环境更新 requirements。
3. 当前未发布版不提供历史兼容层或自动迁移。若存档 schema 不匹配，会明确拒绝启动；保留旧库，配置新的数据库路径用于新版本测试。
4. 回滚时同时使用对应版本的代码和数据库备份，不单独降级其中一项。重构不等于允许自动删除玩家数据。

同一台主机的两个实例可以指向同一 SQLite 文件，但建议单个 NoneBot 进程注册两个适配器，避免重复接收、重复回复和额外数据库锁竞争。不支持网络文件系统共享数据库或异地文件实时同步。
