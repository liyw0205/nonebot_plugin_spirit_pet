# nonebot_plugin_spirit_pet

灵宠修仙、山海玄幻题材的 NoneBot2 文字宠物游戏。支持 **OneBot V11** 与 **QQ 官方机器人**，QQ 可使用 Markdown、指令按钮和蓝字，OneBot 使用纯文本。

当前为未发布稳定版的源码开发项目，尚未发布 PyPI 安装包。

## 游戏内容

- 27 种灵宠，四种初始可选；后续通过召唤与秘境灵卵孵化收集，多宠独立养成。
- 超过两千万个随机候选道号，注册时确保唯一；玩家交互使用道号，不展示平台 ID。
- 八类种族，五行、冰系分支与风雷毒；多属性有明确主属性，对战按属性克制结算。
- 每种宠物独有天赋神通，技能熟练度与等级、三槽装备和 +0 至 +10 强化。
- 54 条种族专属血脉分支；控制、净化、驱散与护盾灵术；装备打造和分解。
- 七个大境界，每个境界一至十层；小境界突破、大境界破境与五阶血脉进化。
- 签到、喂养、修炼、历练、背包、商店与每日任务。
- 离线委托采药、寻矿与采集血髓，派遣占用、手动归来领奖和提前召回。
- 七境共 16 处单人/组队秘境、直接挑战榜单对手的 PVP 论剑、按道号无损切磋。
- 八处线性单人/组队关卡、每位玩家独立首通奖励，以及保留战前阵容和完整战斗事件的永久战报。
- 按种族进度展示的灵宠收集图鉴，以及从存档和永久记录派生、可一次性领取的长期成就。
- 自然月论剑赛季、同境界积分区间匹配、场次限额与一次性赛季奖励，无需邀请或应战。
- 入队审批、双向确认邀请、队长转让和成员管理；二至三人协作、全员准备与独立奖励。

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

提供 Linux、Windows PowerShell 和 Termux 一键安装入口，固定 `nb-cli==1.5.0`，自动配置虚拟环境、驱动与双适配器。GitHub 下载先检测五个来源再选择可用快源，保留已有配置和存档。

- 完整仓库：Linux `bash scripts/install.sh`，Termux `bash scripts/install_termux.sh`，Windows `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1`。
- 单文件下载入口、安装选项和首次配置见下方安装教程。

- [Linux / Windows / Termux 安装教程](docs/INSTALLATION.md)
- [OneBot V11 反向 WS / NapCat / QQBot 配置](docs/CONNECTIONS.md)
- [参数说明、备份与排错](docs/CONFIGURATION.md)

NapCat 只是可选的 OneBot V11 实现，不是插件或反向 WS 的必要依赖。

两个适配器共用同一个 SQLite 数据库。**用户 ID 完全相同才是同一玩家，不同 ID 就是不同的人**；不增加平台前缀，不绑定，不推测 OpenID 与 QQ 号的关系。

## 项目文档

[变更记录](CHANGELOG.md) · [开发指南](docs/DEVELOPMENT.md) · [静态内容规范](docs/CONTENT.md) · [开发路线](docs/ROADMAP.md)

## 参考与许可

参考 [nonebot_plugin_xiuxian_2_pmv](https://github.com/liyw0205/nonebot_plugin_xiuxian_2_pmv) 的双适配器接入及安装脚本配置布局，不复制其业务代码。本项目采用 [MIT License](LICENSE)。
