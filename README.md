# nonebot_plugin_spirit_pet

灵宠修仙题材的文字宠物游戏，运行在 NoneBot2。OneBot V11 与 QQ 官方适配器接入**同一个 SQLite 文件**：只有两端得到的用户 ID 完全相同才是同一玩家；两个 ID 不同就是两位不同玩家。不加平台前缀、不绑定、不猜 QQ 号，也不自动合并存档。

## 游戏内容

| 指令 | 内容 |
| --- | --- |
| `灵宠领养 青鸾` | 与青鸾、玄狐、白泽或蛟龙结契 |
| `我的灵宠` | 查看境界、修为、精力、灵石、灵粮和亲密度 |
| `灵宠签到`、`灵宠喂养` | 领取每日灵缘，或给灵宠灵粮恢复精力 |
| `灵宠修炼`、`灵宠历练` | 修习功法、探索山海；精力与冷却各自结算 |
| `灵宠突破` | 消耗修为、灵石尝试晋阶 |
| `灵宠背包`、`灵宠商店`、`灵宠购买 灵粮 3` | 查看并管理灵粮、灵石 |
| `灵宠改名 小青`、`灵宠图鉴`、`灵宠排行` | 取名、查看灵兽和全服境界榜 |
| `灵宠身份`、`灵宠帮助` | 查看当前原始用户 ID 和帮助 |

每天按北京时间 00:00 刷新签到。精力自然恢复，修炼、历练有独立冷却。游戏数据和指令幂等记录均保存在本地 SQLite，无需安装或注册数据库服务。

本仓库当前是可运行的源码部署版，尚未发布 PyPI 包。已有 NoneBot 项目可将 `src/plugins/nonebot_plugin_spirit_pet/` 放入自己的 `src/plugins/`，安装 `requirements.txt`，注册需要的适配器并加载该插件目录；不要覆盖已有项目的配置文件或数据库。

## 安装

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

## 连接 OneBot V11 / NapCat 反向 WS

这里的“反向 WebSocket”是 **OneBot V11 客户端连到 NoneBot WebSocket server**。NapCat 是常见但**可选**的一种 OneBot V11 客户端，不是插件、NoneBot 或协议接入的硬性依赖；其他兼容 OneBot V11 反向 WS 的实现使用相同地址即可。NoneBot 监听 `HOST:PORT/onebot/v11/ws`；**不要再**在 `.env` 配 `ONEBOT_V11_WS_URLS`，该项是另一个方向的正向连接配置。

1. 在 `.env` 设定监听地址、端口，并选用长随机 token：

   ```dotenv
   HOST=0.0.0.0
   PORT=8080
   ONEBOT_V11_ACCESS_TOKEN=replace-with-your-own-random-token
   ```

   如果只在同一台电脑连接，可以将 `HOST` 设为 `127.0.0.1`。跨电脑连接时要使用 `0.0.0.0` 监听，允许防火墙 TCP 入站端口 `8080`，并只向可信局域网开放。切勿将无访问令牌的端口暴露到公网。

   Token 使用 ASCII 随机字符串，不要直接填中文占位提示；可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成。

2. 在 **NapCat WebUI → 网络配置 → WebSocket 客户端**新增并启用连接，配置对应字段：

   ```text
   URL: ws://127.0.0.1:8080/onebot/v11/ws
   Token: 与 ONEBOT_V11_ACCESS_TOKEN 完全一致
   消息格式: array
   ```

   WebSocket client 对应 NapCat 配置文件中 `network.websocketClients` 的项目；不是 `websocketServers`。若通过文件修改，保留其它配置，只在 `network` 中新增或合并：

   ```json
   {
     "network": {
       "websocketClients": [
         {
           "enable": true,
           "name": "灵宠 NoneBot V11",
           "url": "ws://127.0.0.1:8080/onebot/v11/ws",
           "messagePostFormat": "array",
           "reportSelfMessage": false,
           "reconnectInterval": 5000,
           "token": "replace-with-your-own-random-token",
           "heartInterval": 30000
         }
       ]
     }
   }
   ```

   启动或重载 NapCat 后，NoneBot 控制台出现 OneBot 适配器连接即可；群聊里发送 `灵宠帮助` 验证。跨电脑时将 WebSocket URL 的主机名替换为 **NoneBot 主机** 的局域网 IP，并确保防火墙只允许 NapCat 所在网络访问。

## 连接 QQ 官方机器人

QQ 官方适配器是**独立的平台接入**，不是 NapCat OneBot 连接。NoneBot 和 NapCat 可同时接不同适配器，但 QQ 开放平台的机器人凭证必须作为机密保存在 `.env`，不要发布到 GitHub。

1. 在 QQ 开放平台创建机器人，取得 **AppID 与 AppSecret**，在测试范围加入自己的 QQ 用户及测试群，按发布范围申请权限。`secret` 填 AppSecret，不是旧版 Bot Token、临时 AccessToken 或 QQ 密码。本插件不会自动申请平台权限。
2. 在 `.env` 替换原有 `QQ_BOTS='[]'`，不要重复定义同一项。以下示例开启群/C2C 消息，适用于平台仍允许 WebSocket 接入的机器人：

   ```dotenv
   QQ_BOTS='[
     {
       "id": "YOUR_APP_ID",
       "secret": "YOUR_APP_SECRET",
       "intent": {
         "c2c_group_at_messages": true
       },
       "use_websocket": true
     }
   ]'
   ```

   `DRIVER=~fastapi+~httpx+~websockets` 提供 HTTP 客户端和 WebSocket 客户端能力。QQBot 通过官方网关主动连接，不填写 OneBot 地址。官方群里以 `@机器人 /灵宠帮助` 验证；C2C 私聊直接发送 `/灵宠帮助`。频道可按权限开启 `at_messages`，频道私信另启用 `direct_message`。

   **Webhook 接入**：如果平台要求 HTTP 回调，把 `use_websocket` 改为 `false`，保留 `~fastapi+~httpx`，在开放平台填写 `https://你的域名/qq/webhook`。用反向代理把该 HTTPS 路径转发到 NoneBot 的 `http://127.0.0.1:8080/qq/webhook`，并在开放平台订阅群 @ 消息、C2C 等事件。Webhook 的事件订阅由平台控制，`intent` 只作用于 WebSocket。保持适配器默认验签，不关闭 `QQ_VERIFY_WEBHOOK`；不能把 `ws://.../onebot/v11/ws` 当作官方回调地址。

   QQ 适配器 1.7.3 的有效配置以 `nonebot/adapters/qq/config.py` 为准；不要盲目照搬旧教程的 `QQ_IS_SANDBOX` 或 `token` 字段。本项目使用 `id`、`secret`、`intent`、`use_websocket`。

3. **Markdown、按钮与蓝字**：先使用默认 `text` 模式验证普通消息，再选择已获授权的模式：

   ```dotenv
   SPIRIT_PET_QQ_MODE=native
   SPIRIT_PET_QQ_KEYBOARD=true
   SPIRIT_PET_QQ_BLUE_LINKS=true
   SPIRIT_PET_COMMAND_PREFIX=/
   ```

   `native` 需要原生 Markdown 权限，蓝字使用 URL 编码的 `mqqapi://aio/inlinecmd`，点击后填入指令；QQ 客户端版本与平台权限会影响蓝字是否生效。键盘使用 `action.type=2` 的指令按钮，点击发送普通消息并执行点击者的指令，**不是** `type=1` 回调按钮，因此本版不需要 `interaction` intent，也不处理回调确认。按钮仍需平台允许自定义键盘。`text` 模式不附加任何富消息段。

   仅有模板权限时，可以在开放平台申请单参数模板（参数如 `content`，模板内容例如 `{{.content}}`），审核后填写：

   ```dotenv
   SPIRIT_PET_QQ_MODE=template
   SPIRIT_PET_QQ_TEMPLATE_ID=YOUR_APPROVED_TEMPLATE_ID
   SPIRIT_PET_QQ_TEMPLATE_PARAM=content
   SPIRIT_PET_QQ_KEYBOARD=true
   ```

   模板模式把完整结果作为文本参数传入，不假定模板允许动态 Markdown 或动态蓝字；蓝字可写进获批的模板正文，动态蓝字仅在 `native` 模式启用。模板参数长度限制与多行支持按平台审批结果确认，插件不会截断玩家结果。原生/模板富消息被明确拒绝（400/403/422）时退回纯文本一次；网络超时、限流和服务端错误不自动补发，避免重复消息。任何消息降级都不会重新结算游戏奖励。

## 验证与日常使用

确认 bot 启动后：

```text
灵宠帮助
灵宠身份
灵宠领养 青鸾
灵宠签到
我的灵宠
```

如果 OneBot 和 QQBot 的事件取得**完全相同**的用户 ID，分别查看 `灵宠身份` 会得到相同的 ID，并读取同一个存档；若原始 ID 不同（例如一个是 QQ 号、另一个是 QQ OpenID），按需求它们就是不同玩家。插件既不声称 OpenID 是 QQ 号，也不会把不同 ID 的玩家强行映射或合并。

在新虚拟环境运行游戏逻辑与适配器消息单元测试：

```bash
.venv/bin/python -m pip install 'pytest>=8,<10'
.venv/bin/python -m pytest -q
```

PowerShell 对应 `.venv\Scripts\python.exe -m pytest -q`。

完整协议冒烟测试：`python scripts/smoke_test.py`。它使用真实 NoneBot ASGI 应用和内存 WebSocket 客户端，验证 token 鉴权、事件解析、指令响应、SQLite 落库和重复消息去重，无需启动 NapCat，也不发送真实 QQ 消息。

测试环境：Termux、Python 3.13、NoneBot 2.5.0、OneBot 2.4.6、QQ 1.7.3。QQ API 请求构造和降级通过适配器契约测试，真实 AppID 下的富消息权限与客户端呈现尚需部署后验证。Linux/Windows 的干净环境由仓库 CI 覆盖；不能用协议模拟测试代替真实平台权限测试。

## 开发路线

1. **MVP（本仓库首版）**：本地 SQLite 存档、跨适配器相同 ID 共用数据、同适配器区分玩家、领养、签到、喂养、修炼、历练、突破、灵坊、改名、图鉴、排行榜、指令幂等，以及 QQ 消息能力降级。
2. **Alpha**：增加灵宠成长阶段、属性、灵根差异、随机奇遇任务和限时活动；每种奖励使用带 operation ID 的数据库事务和固定时区规则。
3. **Beta**：扩展装备、可配置物品与后台调参与数据迁移；为排行加入翻页、隐私开关和可选匿名展示。
4. **Release**：完整 adapter 测试矩阵、SQLite 备份与迁移指南、兼容性 CI、版本说明与 PyPI / NoneBot 插件索引发布。

功能原则：OneBot V11 必须始终能收到完整纯文本结果；QQ 原生 Markdown、交互按钮、蓝字属于能力增强，无法使用时不得阻塞游戏操作或改变数据语义。

详细实施顺序、模块职责、数据边界和验收条件见 [开发路径](docs/DEVELOPMENT.md)。可调参数和常见问题见 [配置说明](docs/CONFIGURATION.md)。

## 参考与许可

参考 [`liyw0205/nonebot_plugin_xiuxian_2_pmv`](https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv) 的 NoneBot 双适配器项目及安装脚本配置布局；不复制该仓库业务源码。本项目采用 MIT License。
