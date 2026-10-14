# 开发指南

`main` 是公开安装入口、正式 Release 与集成分支；`develop` 是唯一活动开发分支。schema 20 已随 `v0.1.0` 发布，schema 18 / 19 到 20 的注册时间与 UID 保留迁移已交付。存档结构不匹配时必须拒绝启动，不能静默重建或清空用户文件。

开发计划见 [开发路线](ROADMAP.md)，数据字段见 [静态内容规范](CONTENT.md)，玩家操作见 [玩法说明](GAMEPLAY.md)。

## 唯一执行入口

只读取本短入口与路线图的“当前唯一进度”，再按当前任务读取相关领域章节、源码和测试；不每轮全量加载历史文档。已实现范围与原文快照供定向核对。D1-D3、同族合修、共鸣交互、QQ 命令蓝链和 `v0.1.0` Release 均已完成；历史测试结果不代表本轮重新运行。

### 适配器上游审查与文档交付（已完成，2026-10-10）

只读上游审查、文档复核及提交推送已完成，不保留为活动目标。D1-D3 全部 `passed`；`v0.1.0` 已发布。上游审查记录见 [适配器上游审查](adapter-upstream-review.md)，既有交付证据见 [本地交付记录](reports/development-delivery.md)。

完整共享业务链的唯一适配器验收为 OneBot WS；QQ 只做格式、Markdown、蓝字、按钮 payload、回调 ACK 与降级等短合同，不重复业务长链。原 `1450 passed`、真实 OneBot ASGI/WS、compileall 和 `81,400` 场仿真证据按其对应运行状态复用；测试去重后的 QQ 聚焦短合同已有定向结果，但不把去重前全量结果表述为当前测试树重新全量通过。QQ 机器人连接/鉴权与 QQ 客户端官方呈现、权限分别记录；客户端呈现未实测，不能由 OneBot 结果替代。`v0.1.0` 已发布。

### QQ 面板与分类帮助补充交付（2026-10-10）

“我的灵宠”分组布局、帮助总览与八类子帮助、无固定斜杠前缀的可见文案、语义化蓝字/按钮及群 @ /全量消息事件短合同已完成首轮实现与验证。结果与当时部署边界见 [补充交付记录](reports/development-delivery.md#qq-消息体验补充交付2026-10-10)。当时未部署、不发真 QQ、不重新运行既有全量门禁或仿真；50 用户任务/秒的压测因隔离服务、临时库、RAM 基线与硬上限未确认而未执行。

### 玩家体验修订（历史交付范围，2026-10-10）

根据 fcdc957 部署的用户反馈，修订自然玩法帮助与行内蓝字、移除帮助键盘，分离“我的信息”与“我的灵宠”，完善首次领养及无出战宠引导。新注册仅在首次领养写入 `ctx.now`；旧账号只有可核实的首次成功领养缓存才恢复注册时间，否则为“未记录”。schema 18 迁移前自动创建一致备份，扩展与版本变更同一事务，失败回滚；不支持无关历史版本迁移。

本任务允许聚焦验证、普通提交推送和保留数据更新现有 QQ 测试部署并定向重启。配置/凭据、venv/依赖与玩家存档均保留；不重装、不发真实 QQ 消息、不跑全量、仿真或压测。共享业务流只经 OneBot 代表验证，QQ 只测受影响的短合同。QQ 客户端呈现、权限与 Termux 真机仍待外部验收，独立于已发布的 `v0.1.0`。当前过程记录位于 `/tmp/pet-player-experience-20261010.md`。

源码聚焦验证已通过：首轮 91 项，补充布局、SDK payload、备份与迁移回归 119 项；包含 OneBot 首次领养到修炼、账号无出战宠、注册时间持久化/重投，以及迁移失败回滚。两次有重叠，不相加为独立用例总数；没有重跑全量门禁。

### 命令交互上下文蓝链（2026-10-10，已完成）

在已有帮助和“我的信息”蓝链之外，领养提示、本人缺少出战宠提示、商店装备/秘笈说明及打造配方详情可在关联句旁提供 QQ Markdown 蓝字。完整查询继续使用已配置前缀；需补参数的操作只预填。与正文蓝链相同的命令不再进入该回复的底部动作和键盘。请求者查询他人/队友时仍只返回中性条件提示。QQ 客户端实际呈现未实测。

上下文位置由可选的 `Reply.inline_commands` 行索引、标签和命令表达，并纳入幂等回复与战报/成就快照；`Reply.from_data` 对旧快照缺字段按空集合读取。OneBot、QQ template/text、蓝字关闭时输出可读命令标签，不向业务层执行蓝字操作。本次 formatter、SDK payload、首领养/缺宠、商店/配方与缓存兼容聚焦测试 `40 passed`；未重跑全量、OneBot 长链、仿真或压测。源码 commit `4e78473` 已普通推送并部署到现有 QQ 测试实例；具体提交/远端、备份、配置与运行核验见 `/tmp/pet-player-experience-20261010.md`。本项切片已结束，下一项以路线图当前唯一进度为准。

### 同族合修入口垂直切片（2026-10-11，已完成）

既有合修结算已实现，但名册缺少可点入口、空参不能先查看伙伴。本切片补齐“名册/成长帮助 → 伙伴预览 → 编号合修 → 查看成长”：空参及 `分页 N` 每页展示两位同族在册伙伴和精力、行程、调息条件，只为就绪候选提供完整操作。没有同族伙伴时给图鉴/封存库入口，召唤只预填，不替玩家执行。预览不恢复或消耗精力，不改冷却、任务或准备；成功结果仍进入普通回复缓存。结算沿用双宠各付精力、各获修为、玩家共享调息和一次每日任务的原子事务，不新增字段或数值规则。

QQ 最多两项合修动作加两项翻页，正文蓝链只作成长/行程等辅助，不与按钮重复；键盘不可用时保留蓝链，text/template 或关闭蓝字时保留配置前缀的可读命令。成长子帮助无键盘，未填编号的执行入口只预填。共享业务仅用 OneBot handler 的一条短链验证，QQ 只测受影响的 payload 和降级。

定向命令 `./.venv/bin/pytest -q tests/test_co_training.py tests/test_co_training_contract.py`：`31 passed`。覆盖条件拒绝/回滚、分页、不改资源和准备、本人宠物过滤、行程待领奖、并发、重启重投、前缀、按钮/蓝链去重和预填。最初 5 项失败均因测试批量召唤余额不足；改为正常签到准备资源，保留全部交互断言。本轮提交推送 `main`，不更新测试部署、不发真实 QQ 消息、不跑全量、长链、仿真或压测；真机呈现仍属外部验收。

### 灵宠共鸣交互闭环（2026-10-11，已完成）

在既有 schema20 共鸣规则、原子启停和战斗快照基础上，补齐目录→详情→启用/停用→回看详情的消息链。目录详情命令改为行内蓝字，翻页保留少量按钮；详情只把当前可执行的启用、停用或图鉴入口放在状态行，避免蓝字与按钮重复。OneBot、QQ text/template、关闭键盘或蓝字时均保留配置前缀的可读命令，QQ native 只验证 payload/标签，不宣称客户端实测。

定向命令 `./.venv/bin/pytest -q tests/test_resonance.py tests/test_resonance_contract.py`：`13 passed`。覆盖既有成本、收集门槛、并发、准备失效和战斗隔离，以及目录/详情只读、持久化重放、OneBot handler、QQ 蓝字/按钮去重和前缀。没有跑全量、仿真、压测、真实 QQ 或部署。

### 山海委托交互闭环（2026-10-12，已完成）

高境界委托内容已随 `v0.1.2` 交付，但委托目录、详情与行程回复还没有行内蓝字：目录每页五条任务全部占用按钮位，第二页与翻页在 QQ native 键盘上不可达。本切片沿用合修/共鸣的控件约定补齐“目录→详情→派遣→行程→归来/召回”：目录每行任务名提供“查看详情”蓝字，蓝字命令不再进入按钮，翻页与“灵宠行程”保留少量主按钮；任务详情在门槛行提供“出发派遣”蓝字；行程状态行按剩余/待领/终态给出提前召回、领取奖励或查看目录的唯一蓝字。规则、schema 20、奖励快照与幂等不变；派发的“灵宠启程”回复不带状态性蓝字。

定向命令 `./.venv/bin/pytest -q tests/test_expedition_interaction.py tests/test_expedition_commands.py tests/test_expedition_contract.py tests/test_expedition_content.py tests/test_expedition_occupancy.py tests/test_expedition_storage.py`：`296 passed`。覆盖目录/详情/行程蓝字行位与命令归属、按钮与蓝字去重、翻页可达、同操作重投一致、OneBot/降级可读命令与前缀。未跑全量、仿真、压测、真实 QQ 或部署；QQ native 只验证 payload/标签，不宣称客户端实测。

### 每日任务交互闭环（2026-10-12，已完成）

`灵宠任务` 回复把十条领取命令全部放进按钮，`_action_items` 截断后只有最靠前四条可点，且与任务状态无关：进行中/已领取任务占用按钮，真正的“可领取”任务反而可能没有入口。本切片沿用合修/共鸣/委托的控件约定：只给状态为“可领取”的任务在其状态行挂“领取奖励”蓝字（`InlineCommand`，命令 `灵宠领奖 <任务名>` 完整、直接执行），蓝字命令同时退出按钮集合，因此列表页不再出现固定按钮；行文本、进度、跨日刷新、每日一次领取与幂等重投规则不变，schema 20 不动。

定向命令 `./.venv/bin/pytest -q tests/test_quest_interaction.py tests/test_game.py tests/test_messaging.py tests/test_player_experience.py tests/test_expedition_contract.py tests/test_expedition_occupancy.py`：`271 passed`。覆盖蓝字行位与任务名一一对应、可领取集合恰为蓝字集合、领取后蓝字与按钮清空、跨日清进度、QQ native/template payload 无按钮残留、OneBot 降级保留前缀可读命令。未跑全量、仿真、压测、真实 QQ 或部署。

### 封存库复原交互闭环（2026-10-12，已完成）

封存库列表此前只把复原命令放进按钮，五条封存记录加翻页会超过按钮上限，第二页起复原入口在 QQ native 键盘不可达。本切片沿用名册/共鸣/委托的控件约定：每只封存灵宠在所在行挂“复原”蓝字（`InlineCommand`，命令 `灵宠复原 <编号>` 完整、直接执行），蓝字命令同时退出按钮集合，翻页与“灵宠列表”保留为少量主按钮；空封存库回复在提示行挂“查看灵宠名册”蓝字。封存/复原条件、行文本、分页、幂等与 OneBot/降级可读命令不变，schema 20 不动。

定向命令 `./.venv/bin/pytest -q tests/test_pet_archive_interaction.py tests/test_pet_archive.py tests/test_hatching.py tests/test_messaging.py tests/test_commands.py tests/test_pet_catalog.py`：`112 passed`。覆盖蓝字行位与编号一一对应、按钮去重、两页翻页可达、空库入口、native/template payload、复原幂等重投与 OneBot 前缀可读。未跑全量、仿真、压测、真实 QQ 或部署。

### 成就领奖交互闭环（2026-10-12，已完成）

成就共 47 项、每页五项，可领奖命令此前只进按钮：与翻页/收集入口竞争四个按钮位，且只覆盖当前页最靠前的可领奖成就，其余可领奖成就在 QQ native 键盘上没有入口。本切片沿用任务/封存库的控件约定：每条状态为“可领奖”的成就在其状态行挂“领取奖励”蓝字（`InlineCommand`，命令 `灵宠成就领奖 <名称>` 完整、直接执行），蓝字命令同时退出按钮集合，翻页与“灵宠收集”保留为少量主按钮。成就条件、行文本、分页、永久凭证与奖励快照、幂等重投和 OneBot/降级可读命令不变，schema 20 不动。

定向命令 `./.venv/bin/pytest -q tests/test_achievement_interaction.py tests/test_achievements.py tests/test_messaging.py tests/test_content.py`：`164 passed`。覆盖蓝字行位与可领奖集合一一对应、按钮去重、领取后蓝字清空、同操作幂等重投、native/template payload、OneBot 前缀可读。未跑全量、仿真、压测、真实 QQ 或部署。

### 战报列表交互闭环（2026-10-13，已完成）

战报列表每页五条记录全部把“查看”命令放进按钮，`_action_items` 四条上限截断后第五行战报无法打开，翻页按钮同样被挤出。本切片沿用成就/封存库的控件约定：每行挂“查看详情”蓝字（`InlineCommand`，命令 `灵宠战报 查看 <编号>` 完整、直接执行），蓝字命令同时退出按钮集合，翻页保留为少量主按钮；空列表在提示行挂“查看灵宠名册”蓝字。参与者授权（非参与者查询拒绝）、行文本、分页与永久战报幂等重放不变，schema 20 不动。

定向命令 `./.venv/bin/pytest -q tests/test_battle_report_interaction.py tests/test_battle_records.py tests/test_messaging.py`：`42 passed`。覆盖每行蓝字编号对应、两页翻页可达、按钮与蓝字去重、空列表入口、非参与者详情拒绝、native/template payload、OneBot 前缀可读。未跑全量、仿真、压测、真实 QQ 或部署。

### 万灵图鉴交互闭环（2026-10-13，已完成）

图鉴 27 族分六页浏览，但列表行没有直达详情的入口，详情也不给按获取途径的下一步。本切片沿用共鸣/委托/图鉴行蓝字的既有约定：`information.catalog` 列表每行种族挂“查看详情”蓝字（`灵宠图鉴 <种族>`，完整直接执行）；种族详情在获取途径行挂唯一下一步蓝字——初始可选族“结契该族”预填 `灵宠领养 <种族>`（仍会重新校验 starter 与未注册条件），非初始族“寻访该族”仅预填 `灵宠召唤 `（尾部空格按消息层约定只预填不发送，不替玩家决定召唤次数）。图鉴行文本、分页、领养/召唤规则、starter 限制与 OneBot/降级可读命令不变，schema 20 不动。

定向命令 `./.venv/bin/pytest -q tests/test_catalog_interaction.py tests/test_pet_catalog.py tests/test_messaging.py tests/test_player_experience.py`：`130 passed`。覆盖列表蓝字行位与种族名对应、初始/非初始详情蓝字区分与预填语义、末页详情可达、按钮与蓝字去重、native/template payload、OneBot 前缀可读。未跑全量、仿真、压测、真实 QQ 或部署；QQ 客户端实际呈现仍属外部验收，不由本地 payload 合同替代。

### 论剑挑战交互闭环（2026-10-13，已完成）

论剑榜与匹配候选每页五条，此前挑战命令全部进按钮，`_action_items` 四条上限截断后第四、五行对手在 QQ native 键盘不可达。本切片沿用图鉴/战报的控件约定：`matching.candidates` 与 `seasons.rank`（仅当前赛季）每行在所在行挂唯一“挑战该修士”蓝字（`InlineCommand`，命令 `灵宠论剑 UID <公开UID>` 完整、直接执行），蓝字命令同时退出按钮集合，按钮只保留分页与“灵宠匹配/灵宠赛季”入口；历史赛季行仍可读但从不挂挑战入口，本人行也从不挂。赛季冻结规则、积分结算、限额/资格检查、永久凭证与幂等重放、schema 20 全部不动。

定向命令 `./.venv/bin/pytest -q tests/test_arena_interaction.py tests/test_arena_matching.py tests/test_seasons.py tests/test_arena_messaging.py tests/test_arena_battles.py tests/test_arena_content.py tests/test_lineup_settlement.py`：`242 passed`。新增 `test_arena_interaction` 覆盖候选/榜单蓝字行位与 UID 一一对应、第二页蓝字直达挑战、仅当前赛季挂入口、本人行不挂、QQ native payload 与按钮零重复、OneBot 降级前缀可读。未跑全量、仿真、压测、真实 QQ 或部署；QQ 客户端实际呈现仍属外部验收。

### 开发阶段流程

1. 读取 [开发路线](ROADMAP.md#当前唯一进度) 的当前唯一进度，选取下一有限任务；先核对工作区已有改动和相同状态的验证记录。
2. 对排队缺陷先做最小复现，再修改对应模块并运行相关快测；记录输入、行为、改动和结果。小项通过后继续下一项，阶段通过后进入下一阶段。
3. 按 [验证节奏](#验证节奏) 完成阶段门禁，更新路线图状态和证据。D1-D3 全部完成并有本地交付记录后，开发阶段才通过；goal 完成条件以当前交付目标为准。
4. QQ 机器人连接/鉴权与 QQ 客户端 Markdown、按钮、蓝字呈现分开记录；Termux 设备安装与进程管理也单列。它们不改变 `v0.1.0` 已发布的事实；未实测的平台行为保持未验证状态。

既有架构、数据、玩法和事务规则仍是完整开发合同。当前唯一活动切片、部署 SHA/Release 与下一项见 [开发路线](ROADMAP.md#当前唯一进度)。

## 目录与依赖

```text
scripts/install.sh             Linux / Termux 安装、更新与卸载
scripts/xiupet.sh              Linux / Termux 后台进程管理
src/plugins/nonebot_plugin_spirit_pet/
  __init__.py                  仅插件元数据与入口
  core/config.py               环境变量，运行节奏与消息配置
  adapters/handlers.py         指令识别、真实身份、事件去重键
  adapters/messaging.py        OneBot 文本 / QQ Markdown、按钮、蓝字
  application/commands.py      命令和动作注册
  application/context.py       单次事务上下文
  application/game.py          调度、事务、保存
  domain/content.py            Pydantic 静态内容模型
  domain/battle_content.py     元素、天赋、装备、装备套装、技能及成长阶梯模型
  domain/lineage_content.py    种族血脉分支与四维倍率模型
  domain/crafting_content.py   打造配方与纯函数分解回收公式
  domain/expedition_content.py 离线委托的静态要求与奖励定义
  domain/expedition_state.py   出发时抽取的严格运行奖励快照
  domain/stage_content.py      章节关卡静态定义
  domain/achievement_content.py 成就指标、目标与固定奖励定义
  domain/resonance_content.py  双种族组合与属性倍率定义
  domain/state.py              Player、Pet 运行模型（封存宠物保留为历史记录）
  domain/models.py             Reply、GameError
  content/catalog.py           JSON 加载、唯一性和引用验证
  content/validation.py        装备、技能、元素与内容可用性验证
  content/lineage_validation.py 种族分支、成本与成长取舍校验
  content/crafting_validation.py 配方完整性、材料来源与资源损耗校验
  gameplay/pets.py             领养、召唤、名册/封存库、切换与三宠出战阵容
  gameplay/companionship.py    每日灵宠互动与亲密提升
  gameplay/hatching.py         灵卵孵化与名册容量检查
  gameplay/identity.py         UID 与账户信息查询
  gameplay/help.py             自然玩法帮助、纯文本示例与行内入口
  gameplay/cultivation.py      修炼、大小境界突破、血脉进化
  gameplay/lineage.py          种族分支展示、选择和基础成长倍率
  gameplay/economy.py          签到、背包、商店、消耗品
  gameplay/quests.py           每日任务与领奖
  gameplay/expeditions.py      离线委托、行程查询、原宠领奖与召回
  gameplay/rewards.py          共用奖励结算
  gameplay/pve_stages.py       线性关卡进度与首通奖励
  gameplay/achievements.py    收集图鉴、成就进度与一次性领奖
  gameplay/resonance.py       共鸣目录、启用成本与状态切换
  gameplay/combat.py           属性计算与限回合战斗
  gameplay/talents.py          天赋触发与单场护盾、毒伤效果
  gameplay/effects.py          主动控制、嘲阵、弱化、增益、净化、驱散和持续次数
  gameplay/compatibility.py    类别、元素、境界适用性检查
  gameplay/equipment.py        穿戴、卸装、槽位与图鉴
  gameplay/forging.py          装备强化与强化件库存保留
  gameplay/equipment_inventory.py 同等级装备库存取用与返还
  gameplay/crafting.py         配方、打造、分解与回收预览
  gameplay/skills.py           秘笈学习、携带与卸下
  gameplay/mastery.py          熟练度结算、升级与满级处理
  gameplay/loadout.py          将装备与技能组装到战斗单位
  gameplay/adventure.py        奇遇、单人/组队 PVE 结算
  gameplay/battle_records.py   战前快照、场景名称、永久战斗记录、参与者授权与分页战报
  gameplay/arena/              镜像对战、赛季快照、积分、资格、SQL 匹配与领奖
  gameplay/teams/common.py     队伍成员、权限、容量与准备失效的共用事务操作
  gameplay/teams/party.py      建队、成员详情、准备与出征
  gameplay/teams/requests.py   申请、邀请、审批、撤回与按权限分页
  gameplay/teams/management.py 退队、踢人、队长转让与显式解散
  gameplay/information.py      帮助、面板、图鉴、排行榜
  storage/schema.sql          运行数据表
  storage/database.py         SQLite 连接、初始化、事务、幂等
  storage/registration.py     schema 18/19 到 20 注册时间/UID 保留迁移与一致备份
  storage/repository.py        事务内对象缓存与 SQL 操作
  utils/arguments.py          复用的名称解析和数量验证
  utils/time.py               UTC+8 日期、自然月赛季和冷却计算
  utils/energy.py             精力恢复与上限
  utils/elements.py           元素祖先展开与继承门槛判断
  utils/pagination.py         只读内容分页、页码校验与导航
  utils/randomness.py         可注入随机源的加权抽取
  data/*.json                 静态宠物、境界、血脉、关卡、成就、共鸣、物品、怪物和奖励
tests/                         单元、并发、适配器契约和真实 WS 测试
scripts/smoke_test.py          无需 NapCat 的协议冒烟测试
scripts/database_admin.py      SQLite 在线备份、完整性验证与非覆盖恢复
scripts/balance_report.py      固定种子仿真入口，只使用临时数据库
scripts/balance_specials.py    血脉分支与七类主动效果的独立专项仿真
scripts/balance_lineups.py     单人三宠、三人五宠与合法基线的生产战斗/结算仿真
scripts/balance/               场景矩阵、实际战斗、单位时间收益与验收
docs/                          安装、接入、玩法和开发文档
```

消息层不改玩家数据；玩法层不调用机器人 API。目录按职责分类，不建立把所有函数重新导出到根目录的门面。公共函数只在存在实际复用时进入 `utils/`，业务奖励和战斗规则仍归 `gameplay/`。

## 一次指令的路径

1. `handlers._parse` 匹配完整指令，取 `str(event.get_user_id())`。
2. 用适配器名、bot ID、会话 ID、消息 ID 构造事件键，仅用于去重，不参与玩家身份。
3. `asyncio.to_thread` 执行 `Game.execute`，避免 SQLite 阻塞事件循环。
4. `Store.transact` 开启 `BEGIN IMMEDIATE`。已有结果直接返回，否则建立 `Repository` 和 `Context`。
5. 命令函数只使用这一份事务连接。玩家/宠物对象按 ID 缓存在 Repository，库存、队伍等 SQL 也使用同一连接。
6. `repo.save()` 保存对象，结果与幂等记录一同提交。任何异常均回滚。
7. 提交后发送消息。QQ 拒绝富消息时可退回纯文本，但不得再次执行业务。

不要在玩法函数中 `store.connect()`、`commit()`、`asyncio.sleep()` 或调用外部 API。尤其不要在同一事务中创建第二个 SQLite 写连接，也不要一边改缓存对象，一边对其同一字段执行 SQL 增量更新，避免锁等待或覆盖奖励。

通用成功结果保留约七天，后续请求清理过期记录。战斗记录额外永久保留唯一消息键、参与者和完整 Reply，故同一战斗消息在通用缓存清除后仍会由事务入口原样重放且不会再次结算；离线派遣也永久保留来源消息键及终态，赛季领奖保留复合唯一凭证。业务拒绝不缓存，玩家修正条件后可重试。消息发送不承诺 exactly-once。

## 数据边界

- `players`：原始用户 ID、注册时间 `registered_at`（可空）、共享灵石、出战宠物、日期与玩家级冷却。新注册时间只在首次领养插入，普通保存不更新。
- `player_identity`：稳定自增内部 ID 与原始用户 ID 的唯一映射；公开 UID 为内部 ID + 9999，从 10000 起。旧道号仅保留为历史记录，不用于新交互，也不新增或修改。
- `pets`：每只宠物独立的种族 ID、名字、大境界、层数、血脉、选定的 lineage_id、修为、亲密、精力及恢复时间。分支不改 species_id。
- `inventory`：道具 ID 与数量，没有专门的“灵粮镜像”字段。
- `equipment`：每只宠物的槽位物品与强化等级，装备不同时计入库存；完整套件的属性由静态 `equipment_sets.json` 按当前穿戴组合派生，不另存运行状态。
- `unequipped_equipment`：玩家背包中 +1 及以上的装备，按物品、强化等级计数；+0 仍使用普通 inventory。卸装和重新穿戴不清空强化，不重复计数。
- `learned_skills`：每只宠物的学习/携带状态、技能等级与当前级剩余熟练度。
- `quest_progress`：当前任务日的进度及领取状态；刷新按玩家的 `quest_day` 处理。
- `expeditions`：行程及原宠归属、委托名称、永久出发消息键、开始/完成时间、严格奖励快照、运行/已领/已召回状态与结算时间。
- `active_pet_slots`：每名玩家 1-3 个有序出战槽位；同一阵容禁止重复宠物种类。
- `teams/team_members`：队长、成员、已同意出征的宠物编号；队长可带三只，队友各带一只，整队最多五只。
- `team_requests`：待处理申请/邀请，复合键为队伍与候选人，记录发起人、创建时间及失效时间。不是静态 JSON；解散级联清理，审批完成删除，入队删除该候选人所有请求。
- `seasons/season_entries`：自然月边界、观测时间高水位、规则快照及实际参赛玩家的独立积分与胜负平。
- `pvp_results`：挑战双方及原宠、胜者、日期、分差、结算时间、永久唯一消息键和当时的 Reply；用于配额、领奖统计和重投，不是逐回合完整战报。
- `battle_records/battle_participants`：永久唯一操作键、发起人、战斗类型/胜方/回合/时间、战前阵容快照、完整战斗事件日志与 Reply；参与者表按原始用户 ID 授权查询。快照持有当时道号、宠物名、主属性、属性面板、技能等级/熟练度、装备强化和生效套装，不引用当前玩家/宠物资料来重建历史。
- `pve_stage_progress`：每名玩家每个静态关卡的首通时间与来源操作键；前置链来自 `data/stages.json`，不把玩家进度或运行时间写回内容文件。
- `achievement_claims`：每名玩家每项成就的唯一领取凭证、永久操作键、领取时间、实际奖励快照与回复。成就进度从当前存档、关卡进度和永久战斗记录派生，不重复保存累计计数；组队 PVE 成就按战报中同侧玩家参战人数识别协作胜场。
- `season_claims`：每季每人唯一的领奖凭证、实际奖励快照与领取时间。
- `operations`：事件来源去重键、玩家和完整结果。

玩家 ID 不加适配器、bot 或群号前缀。不存在绑定和合并接口。“我的信息”展示稳定 UID，不展示或猜测 QQ 号码；玩家查找、社交和队伍交互使用 UID，不将原始平台 ID 放入按钮或蓝字。玩家信息和背包不要求出战宠物；旧存档的 `pets.name` 仅用于历史资料和战报展示。

修炼、历练、PVE、PVP 冷却在玩家上，换宠不能绕过。精力在宠物上；未出战宠物的恢复于再次访问时按时间差计算。队伍战斗对所有成员检查条件后才扣费，任何一人不满足则整场回滚。

## 添加一个玩法

以新增“采药”为例：

1. 静态掉落写入对应 JSON，涉及新结构时先在 `domain/content.py` 定义模型，在 Catalog 校验其物品引用。新冷却秒数放 `core/config.py` 和 `.env.example`。
2. 在合适的 `gameplay/` 模块编写 `def gather(ctx: Context, arg: str) -> Reply`。先校验条件，再通过同一 Repository 修改资源；预期拒绝抛 `GameError`。
3. 如果消费精力或改变战斗能力，须取消对应组队准备。指定宠物的养成使用 `ctx.repo.invalidate_pet_ready(user_id, pet_id)`，按队长整队/队友首宠判断实际参战；阵容或账户战斗配置变更使用 `ctx.repo.invalidate_ready(user_id)`。
4. 在 `application/commands.py` 为 ACTIONS 注册函数，COMMANDS 注册中文入口。仅确实接受参数时设置 `arguments=True`。
5. 如果影响每日任务，明确成功事件并调用 `quests.advance`，同时扩展静态任务事件类型。
6. 添加成功、失败回滚、资源不足、并发、相同消息重投和冷却边界测试；更新玩家帮助、`docs/GAMEPLAY.md`。

涉及持久化结构时修改运行模型与 schema，提高版本并使用临时库测试。当前 schema 为 20，已支持完整 schema 18 / 19 的保留迁移：schema 18 先补可空注册时间，可证明的首次领养回复与所属宠物编号对应时恢复时间，无证据或有歧义则留空；schema 19 按原玩家顺序建立稳定 UID 映射，保留平台身份、宠物、关系、时间和旧回复。每步迁移前备份必须成功且通过完整性/外键检查，失败回滚；其他旧版库拒绝启动并保留原文件。本轮不改该迁移逻辑。

自动备份位于原库旁的 `<库名>.schema18-backup-*.db` 或 `<库名>.schema19-backup-*.db`，权限 0600，保留对应原 schema。成功升级后若需回退旧代码，须先停该部署并保留当前库及 WAL，再将原代码与一致备份库配对恢复；不要仅回退代码，也不要覆盖或删除升级后的玩家存档。

升级前可用 `scripts/database_admin.py` 通过 SQLite Online Backup API 生成一致快照，并检查完整性与外键。备份和恢复都只能写入不存在的目标路径；恢复不会修改当前数据库或迁移 schema。具体操作和版本配对规则见 [配置与升级回滚](CONFIGURATION.md#升级与回滚)。

## 赛季与镜像

- `arena.common.current_season` 用 UTC+8 自然月创建严格规则快照，关闭旧季，并以所有赛季的 `MAX(observed_at)` 拒绝时钟倒退。停机跨月只在实际访问月份建季，不补造空月份；新季不修改旧季积分或玩家冷却。
- 删除旧全局 rating、pvp_pairs 及邀请战帖系统，积分唯一来源为 season_entries；查询默认分数不插入参赛记录。`scoring` 结算两方零和积分与胜负平；`battles` 直接取当前双方出战宠镜像，仅扣主动方精力、设置冷却、取消准备并增加实际施法熟练度，持久化结果与完整回复，全部处于同一事务。
- `eligibility` 检查主动方闲置、恢复后精力、冷却、日挑战次数，并检查双方境界、分差和同对额度。`matching` 在 SQL 中按后者筛选镜像，再执行 LIMIT/OFFSET，不无界加载全服玩家。守方精力、冷却、主动挑战次数或外出占用均不影响被挑战。
- `loadout.combatant(recover_energy=False)` 构建镜像但不触发被动精力恢复，防守方的宠物/玩家资源、冷却、技能熟练度与队伍准备保持不变。切磋双方都用此只读路径，无积分或经济收益；只有主动方须闲置。
- `pvp_results.operation_id` 永久唯一。读取该键必须先验证挑战者身份；通用缓存清除后直接重放旧 Reply，不重新解析当时道号、不重新参战，也不将旧挑战记入新季。原宠组合外键保证参与者归属。
- PVP、切磋、单人/组队秘境及逐关挑战应在 `fight` 前调用 `battle_records.capture_snapshot`，结算完成后于同一事务调用 `record_battle`。场景名称和战前阵容保存在版本化 `snapshot` 中；详情分页只能读取 `snapshot` 与 `battle_log`，不能用当前静态内容、宠物、道号、技能或装备补算；`battle_participants` 用于严格过滤本人可见记录，离队不撤销既有战报读取权限。
- 章节首通按 `(user_id, stage_id)` 唯一写入；组队战胜后只给首次通关成员发该关奖励，已经通关的队友可以助战。失败照常扣参战者精力与冷却，但不写进度。
- `data/achievements.json` 只声明稳定 ID、目标、指标与静态奖励。`gameplay/achievements.py` 通过 SQLite 查询派生进度；`achievement_claims` 的玩家/成就主键和操作键唯一约束共同保证并发、跨缓存过期重投均只领奖一次。记录奖励/回复快照后再发放，必须和发奖处于同一事务。
- 日总额只统计主动挑战，包含平局；同对日/季额度统计两个方向所有结果。领奖只统计主动非平局及其不同对手，镜像防守不增加有效场次。败方余额不足时转移其余额，不能产生负分或凭空增分。
- 领奖按冻结规则及最终积分发一个档位，season_claims 与物品、灵石、回复同时提交；不访问当前宠物，因此不会给外出宠加修为。缺失快照所需物品时明确回滚，恢复定义后可重试。
- 此防刷范围仅为原始玩家 ID 的频次与经济收益限制，不识别设备、关联账号或跨 ID 绑定；镜像不要求在线。QQ 赛季蓝字允许 YYYY-MM 中的连字符，所有回传仍走同一命令解析与事务检查；当前榜每页五人，挑战/翻页按钮总数不超过八个。

## 离线行程

- `data/expeditions.json` 不放时间或玩家状态。行程时长来自 `Config.spirit_pet_expedition_duration`，开始时写入绝对完成时间；不依赖后台轮询或进程内定时器。
- 数据库 `running` 状态同时对 user_id 和 pet_id 建部分唯一索引，组合外键保证宠物归属。只有归来/召回提交后释放；到期只是可领奖，不自动把 `running` 改为终态。
- `Context.operation_id` 由 `Game.execute` 显式传入，出发时永久写入唯一 `source_operation_id`。通用缓存到期后重投只能查询旧行程，不生成新的派遣。归来/召回使用 job_id，不能按“当前行程”隐式修改；不带参数仅查询。
- 出发时抽取并验证 `RewardSnapshot`，结算时再次严格读取，不重新随机，也不查询任务当前的奖励区间。任务名称从行程读取；快照引用的物品被移除时明确拒绝并回滚，管理员恢复定义后可重试，不静默丢奖励。
- 三种写操作均使用原 `BEGIN IMMEDIATE`，宠物修为通过 Repository 缓存对象写回，禁止 SQL 增量与缓存覆盖混用。状态、资源、回复缓存同时提交；领取永远给行程原宠，不复用默认面向当前宠的 `rewards.grant`。
- `Repository.active_expedition` 只检查 `state='running'`，`Context.require_idle_pet` 统一执行占用约束；`Context.pet` 仍供查询和被动精力恢复。`check_action` 拦截耗能玩法，突破/进化/消耗品/配装/技能/主动切磋/准备显式检查。论剑、组队出征实时检查主动宠占用，防守镜像不动原宠状态。
- 纯账户奖励不读取当前宠；含修为上限的普通奖励在抽取之前要求当前宠闲置，即使本次可能抽到零修为也不能绕过。切宠后可继续其他玩法。
- 保留终态记录用于重试与审计。时钟回退不能提前领奖，召回不能早于出发；新派遣不能早于上一行程结算。查询按归属过滤，只返回最近一条或指定编号，不展示来源消息键或玩家原始 ID。
- 独立测试覆盖时间边界、重启、内容/配置变更、原宠归属、无参只读、终态竞争、七天后重投与所有占用入口。真实 WS 与 QQ 事件模型验证完整中文命令链；QQ 实号权限仍需单独验收。

## 队伍授权

- `apply` 由候选人发起，仅当前队长可同意/拒绝；`invite` 由当前队长发起，仅候选人可同意/拒绝。原发起人可撤回，但不能充当审批人。同一队伍与候选人只能存在一条请求，反方向请求不得覆盖原授权或刷新 TTL。
- 所有查询显式要求 `expires_at > ctx.now`。过期清理在成功写操作中惰性执行；失败时整个事务会回滚，不能假设先前执行过 DELETE 就已经清理。
- `common.add_member` 在同一写事务重查候选人无队和队伍容量，插入成员、删除候选人全部请求并清除全队准备。邀请不占名额，最后余位按审批成功的事务先后分配。
- 退队/踢人/转让同样清全队准备；转让还删除该队全部请求，避免旧队长授权残留。队长普通退队不能隐式解散。管理和准备查询直接读取宠物，不借此触发精力恢复；真实出征仍由 PVE 处理恢复与结算。
- UID 用于查找和显示，数据库关联仍是原始玩家 ID。`Context` 没有群作用域，团队明确为全服团队；消息层不主动跨会话推送。不能将适配器的会话去重键误当队伍权限范围。
- 队务按四条一页执行 SQL LIMIT/OFFSET，查询限定本人或当前队长可处理的记录。此限制属于查询授权，不等于私聊投递；`bot.send(event, ...)` 回复当前会话，群内查询结果仍对同群成员可见。显式分页参数 `分页 N` 含空格，与 UID 详情区分；成员详情也必须限定在本人当前队伍。
- 成员变动与出征共用 `BEGIN IMMEDIATE`：要么先完成整场结算再变动，要么先变动并使旧准备失效。不能在战斗中途重新读取名单，把一次请求变成部分成员扣费。

## 战斗规则

当前是自定义回合制规则，不依赖已有桌游或游戏规则体系：

- 属性来自种族基础值乘以境界、层数、血脉、亲密、分支各属性倍率，再加装备各自强化后的固定属性和完整装备套件的固定加成，修为余额不直接增加攻击。血脉分支引用错误或不属于该种族时明确拒绝，不能悄悄返回默认倍率。
- `loadout.combatant` 对装备和技能再次校验类别、全部所需元素与最低境界；拒绝不兼容内容，不静默跳过坏数据。
- `Fighter.primary_element` 显式从宠物/敌人定义传入，不能取 elements[0]。普攻使用主属性，伤害技能使用技能元素，防守仅看目标主属性；分支递归继承五行关系，倍率只算一次，1.25/0.8/1.0。无属性技能按中性处理。
- `Skill.targeting=all` 只允许无状态附加的伤害技能；施法瞬间锁定存活目标，随后每名目标独立闪避、承伤和触发受击天赋，即使反击击倒施法者也完成本次锁定结算，但施法计数、熟练度与 `Fighter.attacks` 各只推进一次。群攻不经由单体嘲阵目标选择。
- 已携带技能依固定顺序轮换，系数乘数据库等级对应的威力倍率。治疗技能回复自身；满血但仍有有效净化等附加效果时可以施放，否则回退普攻且不记技能施放。技能轮次属于单场内存状态，不是 JSON 时间字段。
- `talents` 负责开场护盾、行动前毒伤/恢复、进攻增益、闪避和命中后触发。毒和反击不递归触发天赋或技能熟练度。效果状态在每场新建 Fighter 时重置。
- `effects` 负责明确的控制/增益状态与行动计数：先处理行动前毒伤和天赋，再检查受控，随后施法或普攻，最后推进效果期限和免控。亲密达到 100 的灵宠在每场战斗首次受到控制时自动抵挡一次；该标记仅属于 Fighter，不持久化。嘲阵优先重定向敌方目标选择，并按护阵者自己的行动计时；驱散会一并移除。规划目标后才检查效用，避免随机探测目标与实际目标不一致。`actions` 只统计真正行动并推动技能轮换，`turns` 包含受控跳过的行动机会。
- 同类效果取较强值、较长剩余次数并刷新，不叠加；自身刚施加的持续效果从后续行动才计期。护盾先消耗临时层再消耗天赋层。有效驱散和净化计技能施放，无目标则回退普攻；持续效果、反击和天赋不记技能施放。
- 每场从满气血开始；气血只在本场存在，结算消耗精力，不持久化战斗气血。
- 速度决定行动顺序，同速时随机决定先后，目标从存活对手中抽取。伤害至少为 1，有 90%-110% 浮动。
- 最多 40 回合，超时视作平局；不发 PVE 胜利奖励，不转移论剑积分。
- PVP 直接挑战镜像，遵循冻结赛季的同境界、分差和日/季限额；切磋按 UID 立即结算，无邀请过程，不消耗精力或发放经济奖励。
- 组队用同一战斗函数，每位参战成员胜利后获得一份各自抽取的奖励，不分摊掉落。
- `Battle.skill_uses` 按左右阵营、pet_id、skill_id 统计真实施放。PVE（含败退/平局）与积分 PVP 主动挑战者在原事务内调用 `mastery.award_mastery`，镜像防守与切磋不调用。不得根据战报文本或回合数猜测使用次数。

参数内容可在 JSON 中调整；更换算法需同时改 `combat.py` 和测试，不把战斗分支硬塞进适配器。

## 分支约定

`main` 是公开安装、正式 Release 与集成分支；`develop` 是唯一活动开发分支。普通提交先推送 `develop`，审查后普通合入 `main`。禁止 force push、reset 或移动既有 tag；提交不包含 `.env`、玩家库或本地虚拟环境。

## 验证节奏

| 时点 | 验证要求 |
| --- | --- |
| 仅文档调整 | 检查链接、合同表述和 diff；复用原证据，不跑全量业务、WS 长链或仿真 |
| 适配器上游只读审查 | 核实加载路径、版本/SHA 和上游差异；列出按接入差异选择的短合同测试，不修改实现或重复启动既有长测 |
| 等价测试去重 | 审查原断言、平台差异与覆盖映射，必要时只验修改的短合同用例；不因去重重跑完整共享业务或仿真 |
| 一次实现修改 | 运行直接涉及的测试文件；修复先有可复现失败，再证明通过 |
| D1/D2 阶段结束 | 共享事务、阵容或奖励语义变化按影响做一次共享全量回归；适配器变化先短合同与针对性接线用例，实际运输/鉴权/路由风险才补一次必要 WS 验证 |
| 数值/内容/战斗公式改变 | 相关快测通过后，运行受影响的完整固定种子矩阵并审阅差异 |
| D3 本地交付里程碑 | 对最终状态完成一次共享全量 pytest、一次必要真实 WS 验证、compileall，以及基础、专项各每场景 100 次和 D2 三宠/五宠每场景 100 次的完整矩阵；复用同一运行状态已有通过记录，pytest 已运行同一 WS 脚本时不再单独重跑 |

验证记录须写明源码提交与未提交 diff 状态、实际加载实现的路径与版本/SHA、静态内容/配置/依赖状态、命令、结果和覆盖限制。未知基线或尚未执行的合同测试必须标为未确认或建议，不以版本标签、源码阅读或计划代替运行证据。

先比对证据对应的运行文件 SHA 清单、实际加载的适配器版本/SHA、依赖快照与配置。仅文档或隔离目录中的上游 HEAD 变化不改变运行状态，沿用原证据；相关运行文件、实际加载版本/SHA、依赖或配置变化后，先确定影响，再补受影响检查。无改动不重跑已通过门禁，遇到失败回到该失败的最早不确定环节。

### 双适配器验证范围

2026-10-10 源码核对：`adapters/handlers.py:66` 的同一 `_run` 将 `str(event.get_user_id())`、解析后的动作/参数与事件键传给 `Game.execute`；`application/game.py:46` 调用 `Store.transact`，其回调在 `game.py:34` 以事务连接建立 `Repository`。`storage/database.py:62` 开启 `BEGIN IMMEDIATE`，`storage/repository.py:12` 保留同一连接；共享业务入口没有按 QQ/OneBot 选择不同玩法函数。以下路径均相对 `src/plugins/nonebot_plugin_spirit_pet/`。

| 边界 | OneBot V11 | QQ 官方 |
| --- | --- | --- |
| 原始玩家身份 | `user_id` 转字符串 | 私聊 `author.user_openid`，群聊 `author.member_openid` |
| 消息凭证 | `message_id` | `id`；共用入口在无 `message_id` 时回退到 `id` |
| 会话与去重 | 私聊用户会话，群聊 `group_<group_id>_<user_id>` | 私聊 `friend_<user_openid>`，群聊 `group_<group_openid>_<member_openid>` |
| 回复发送 | `messaging.py:53` 发送纯文本 | `messaging.py:96` 处理 text/native/template、按钮与明确拒绝时的降级 |

`handlers.py:54` 将适配器名、bot ID、会话 ID、消息 ID 编成去重键；这些字段不加入玩家身份。同一原始 ID 字符串共享玩家，不同 ID 不做绑定或推测。发送在事务提交后执行，富消息降级不能重新执行业务；超时也不能视为安全重发。平台身份/会话字段以本轮安装的 OneBot 2.4.6、QQ 1.7.3 事件实现为依据。两适配器来自 `nonebot.adapters` 依赖，插件内的 `adapters/` 是接线与发送层，当前不是平台适配器实现的 vendor 副本。

此前重复可由源码定位：`tests/test_lineup_protocol.py` 曾将 QQ 群/私聊与三种消息模式参数化为六例，并每例执行同一 `run_multi_pet_chain`；`scripts/smoke_test.py:462` 又经 OneBot WS 执行同一链，且 `tests/test_runtime.py:16` 已在 pytest 内运行 WS 脚本。本次已移除六次 QQ 长链，改为 QQ 富消息格式、Markdown、蓝字、按钮 payload、回调 ACK 与降级等短合同；共享多宠业务链仍只由 OneBot WS 代表一次。全量通过后单独再次运行 `scripts/smoke_test.py` 仍会重复 WS 长链，应仅在 pytest 未覆盖且需要运输诊断时执行。重复长链不表示 1450 项 pytest 或 81,400 场仿真按两平台跑两套；仿真脚本没有平台分支。原 1450/81,400 证据对应去重前相同运行代码与内容状态，本次测试结构变化后只运行聚焦 QQ 短合同，未重新全量。

后续验证按这三个范围执行：

- 完整共享业务、事务与固定种子仿真对同一运行状态一次即可；OneBot WS 作为共享业务链唯一完整适配器验收，不将同一业务脚本按 QQ 消息模式或两平台机械复制。
- QQ 只保留格式、Markdown、蓝字、按钮 payload、回调 ACK 与降级合同；两端另保留命令提取/解析、原始身份、事件键、路由和回传参数短合同。可用构造事件、固定 Reply 或执行调用观察检查边界，不引入无关成长与战斗长链。
- 平台特有业务分支或适配器到业务接线风险有明确证据时补针对性用例。等价测试去重先保留断言与覆盖映射，再仅验证修改范围；运行语义不变时沿用原共享业务/仿真结果，不启动完整长测。

本轮真实运输证据是 OneBot ASGI/WS；QQ 短合同使用事件模型和 mock 发送，不代表 QQ 官方呈现、回调、网络或 AppID 权限已实测。QQ 连接/鉴权、QQ 客户端呈现和 Termux 设备验收分别记录；OneBot 通过不能声称 QQ 真机通过，缩短验证不会扩张这些证据边界。`v0.1.0` 已发布。

依赖缺失时才安装：

```bash
.venv/bin/python -m pip install -r requirements.txt 'pytest>=8,<10'
```

实现修改先选择相关文件，例如阵容结算：

```bash
.venv/bin/python -m pytest -q tests/test_multi_pet_lineup.py tests/test_lineup_settlement.py tests/test_lineup_coverage.py tests/test_mastery.py
```

阶段和交付门禁按上表选用；以下命令是可选入口，不是每轮执行清单。全量 pytest 已包含同一 WS 脚本，独立冒烟只在该路径未运行且确有运输验证需要时执行；当前文档任务不执行这些命令：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke_test.py
.venv/bin/python scripts/balance_report.py --runs 100 --seed 20261007 --check
.venv/bin/python scripts/balance_specials.py --runs 100 --seed 20261007 --check
.venv/bin/python scripts/balance_lineups.py --runs 100 --seed 20261007 --check --json docs/reports/development-lineups.json --markdown docs/reports/development-lineups.md
.venv/bin/python -m compileall -q src tests scripts
```

Windows 使用 `.venv\Scripts\python.exe`。当前 Termux 可直接用 `$HOME/myenv/bin/python`，不要求新建环境，不要求 NapCat 或真实 QQ 凭证。测试全部使用临时数据库。

测试覆盖静态目录校验、同 ID 数据共享、十层成长、血脉、共鸣成本与战斗加成、主属性/分支继承、天赋效果、技能成长、强化保留、灵卵容量、事务回滚、并发、重复消息、组队准备、直接镜像对战与适配器构造。真实 ASGI 测试会连接 `/onebot/v11/ws`，验证鉴权和收发，不只调用业务函数。

一键安装脚本的无 Python 自举、隔离安装/卸载与 `xiupet` 启停由本地测试覆盖。QQ 真机 AppID 权限、Markdown 审批和蓝字客户端呈现需另行验收，单元测试不代表平台授权已经通过。

固定种子矩阵的场景、准备程度、收益口径和留存结果见 [数值验收](BALANCE.md)。全量 pytest 含原基础矩阵每个准备阵容 10 次及新增有限阵容每场景 2 次的快速门禁；完整 100 次矩阵只按上表的相关变更或交付里程碑运行。原 626/124 矩阵与新增三宠/五宠矩阵分别记录，不能互相替代。新增矩阵运行生产 `run_dungeon`，包含逐宠精力、首宠修为、成员掉落、任务与快照检查。脚本不得连接或修改 `SPIRIT_PET_DB`，仿真只使用临时数据库、生产装配和真实 `fight`。

基础矩阵不包含血脉分支或辅助配装；专项脚本另外验证全部分支和主动效果，并保留未胜利的对照结果。效果观测器仅在单进程专项范围内临时包装 `effects.apply`，统计实际状态变化，退出或异常时恢复原函数；它不是机器人运行时组件，不应在运行中的服务进程里调用。

## 配置来源

`pyproject.toml` 是 NoneBot 运行项目配置，声明插件目录、驱动和适配器。Python 最低 3.10，运行依赖由一键安装器在项目虚拟环境中准备。
