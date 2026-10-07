# 连接机器人

[安装教程](INSTALLATION.md) · [配置与排错](CONFIGURATION.md)

一键安装默认最后以前台方式启动；用了 `--no-start` / `-NoStart` 时，在项目目录执行 `nb run`，或用生成的 `xiupet start` 后台启动。自定义虚拟环境时使用该环境中的 `nb` 命令。

安装器首次生成的 `.env` 已含随机 `ONEBOT_V11_ACCESS_TOKEN`，填写 OneBot 客户端时使用文件中的真实值，不必重新生成。重复安装不会覆盖 `.env`；修改连接参数后需重启 bot。已有 `.env.dev` / `.env.prod` 也会参与 NoneBot 环境配置，检查是否存在同名参数覆盖。

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


## 接通后的检查

依次发送 `灵宠领养 青鸾`、`我的道号`、`灵宠签到`、`我的灵宠`。OneBot 和 QQBot 共用同一数据库，但只有完全相同的后台用户 ID 才共用角色；不同 ID 不绑定、不合并。游戏内只显示唯一道号，不展示平台 ID。

协议自动测试不要求安装 NapCat。QQ 真实 AppID 的 Markdown、键盘和蓝字需要开放平台权限及客户端验证；本仓库的契约测试不能替代真机授权验收。
