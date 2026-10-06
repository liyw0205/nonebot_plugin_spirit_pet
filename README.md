# nonebot_plugin_spirit_pet

灵宠修仙、山海玄幻题材的 NoneBot2 文字宠物游戏。支持 **OneBot V11** 与 **QQ 官方机器人**，QQ 可使用 Markdown、指令按钮和蓝字，OneBot 使用纯文本。

当前为未发布稳定版的源码开发项目，尚未发布 PyPI 安装包。

## 游戏内容

- 七种灵宠，领养、概率召唤、多宠收藏与出战切换。
- 随机唯一道号，玩家交互使用道号，无需输入或展示平台 ID。
- 羽族、兽族、龙族、甲族，单系或多系灵根，装备与技能按类别和元素匹配。
- 七个大境界，每个境界一至十层；小境界突破、大境界破境与五阶血脉进化。
- 签到、喂养、修炼、历练、背包、商店与每日任务。
- 单人 PVE 秘境、双方确认的 PVP 论剑、无损切磋。
- 二至三人组队、成员准备、队长挑战和全队独立奖励。

```text
灵宠领养 青鸾
灵宠签到
我的灵宠
灵宠修炼
灵宠突破
灵宠挑战 青岚林
灵宠帮助
```

命令可以带 `/` 前缀；QQ 群聊通常需要先 @机器人。完整指令、成长规则、对战与组队流程见 [玩法说明](docs/GAMEPLAY.md)。

## 安装与接入

- [Linux / Windows / Termux 安装教程](docs/INSTALLATION.md)
- [OneBot V11 反向 WS / NapCat / QQBot 配置](docs/CONNECTIONS.md)
- [参数说明、备份与排错](docs/CONFIGURATION.md)

NapCat 只是可选的 OneBot V11 实现，不是插件或反向 WS 的必要依赖。

两个适配器共用同一个 SQLite 数据库。**用户 ID 完全相同才是同一玩家，不同 ID 就是不同的人**；不增加平台前缀，不绑定，不推测 OpenID 与 QQ 号的关系。

## 项目文档

[开发指南](docs/DEVELOPMENT.md) · [静态内容规范](docs/CONTENT.md) · [开发路线](docs/ROADMAP.md)

## 参考与许可

参考 [nonebot_plugin_xiuxian_2_pmv](https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv) 的双适配器接入及安装脚本配置布局，不复制其业务代码。本项目采用 [MIT License](LICENSE)。
