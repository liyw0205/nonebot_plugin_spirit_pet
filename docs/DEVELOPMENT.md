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

### 灵宠关卡挑战交互闭环（2026-10-14，已完成）

关卡列表每页五条，此前挑战命令全部进按钮，`_action_items` 四条上限截断后第四、五行不可达，且锁定关卡也占用按钮位。本切片沿用任务/成就的“仅可执行行挂蓝字”约定：`pve_stages.catalog` 中 `可挑战/已通关` 行在所在行挂唯一“前往挑战”蓝字（`InlineCommand`，命令 `灵宠挑战关卡 <序号>` 或组队关 `灵宠组队关卡 <序号>`，完整、直接执行），`未解锁/尚未结契` 行不挂可执行入口；蓝字命令同时退出按钮集合，按钮只剩 `灵宠关卡` 分页导航。关卡详情回复、行文本、解锁/精力/境界/前置校验、首通奖励与永久战报幂等重放、schema 20 全部不动。

定向命令 `./.venv/bin/pytest -q tests/test_stage_interaction.py tests/test_pve_stages.py tests/test_stage_content.py`：`33 passed`。新增 `test_stage_interaction` 覆盖新号仅首关挂蓝字与行位、已通关与新开行各挂一行、锁定/未注册行不挂、第二页仅新开行挂蓝字且分页按钮保留、组队蓝字即注册入口且未组队干净拒绝、QQ native payload 与按钮零重复。未跑全量、仿真、压测、真实 QQ 或部署。范围与停止条件见 [pet-pve 目标卡](goals/pet-pve.md)。

### 山海秘境行内详情闭环（2026-10-14，已完成）

秘境列表每条秘境的进入命令此前全部进按钮，`_action_items` 四条上限截断后第四、五行秘境在 QQ native 键盘不可达。本切片沿用万灵图鉴“查看详情”只读约定：`adventure.dungeons` 列表每页五条秘境各在所在行挂唯一“查看详情”蓝字（`InlineCommand`，命令 `灵宠秘境 <秘境名>`，完整、直接执行只读详情）；蓝字命令同时退出按钮集合，按钮只剩 `灵宠秘境` 分页导航。秘境详情回复、行文本、排序、分页、`灵宠挑战`/`灵宠组队挑战` 校验、掉落与永久战报幂等重放、schema 20 全部不动。

定向命令 `./.venv/bin/pytest -q tests/test_dungeon_interaction.py tests/test_balance.py tests/test_adventure_routes.py tests/test_commands.py`：`38 passed`（含新增 `test_dungeon_interaction` 4 项）。新增测试覆盖首页五行蓝字行号/命令逐行对应、`reply.commands` 恰为分页导航、native markdown payload 与按钮零重复、第二页蓝字与上一页下一页按钮、详情首命令仍为挑战入口、降级文本含可读命令且无 `mqqapi://`。未跑全量、仿真、压测、真实 QQ 或部署。范围与停止条件见 [pet-dungeon-list 目标卡](goals/pet-dungeon-list.md)。

### 队务列表行内详情闭环（2026-10-14，已完成）

`待处理队务` 每页四条队务，此前把每行详情命令 `灵宠队务 <对方UID>` 全部塞进按钮，再叠加 `灵宠队务 分页 <n>` 导航；`_action_items` 四条上限截断后满页时的第四行队务与翻页在 QQ native 键盘不可达。本切片沿用万灵图鉴/秘境列表的“查看详情”只读约定：`teams/requests.inbox` 每条队务行在所在行挂唯一“查看详情”蓝字（`InlineCommand`，命令 `灵宠队务 <对方UID>`，完整、直接执行只读详情）；行命令同时退出按钮集合，按钮只剩 `灵宠队务 分页 <n>` 导航，空列表保留 `灵宠队伍`/`灵宠组队` 回退入口。行文本 `_summary`、排序、分页、`_detail` 审批方向（发起人撤回 / 处理人同意与拒绝）、`_require_decider` 授权、过期与上限规则、并发与永久幂等重放、schema 20 全部不动；`party.py` 与 `management.py` 不在本切片范围。

定向命令 `./.venv/bin/pytest -q tests/test_team_request_interaction.py tests/test_team_requests.py tests/test_team_management.py tests/test_commands.py`：`57 passed`（含新增 `test_team_request_interaction` 5 项）。新增测试覆盖满页四行蓝字行位与命令逐行对应、`reply.commands` 恰为分页导航、native markdown payload 与按钮零重复、第二页蓝字与上一页下一页按钮、空列表回退入口且无蓝字、详情审批方向与详情不挂蓝字、降级文本含可读命令且无 `mqqapi://`。未跑全量、仿真、压测、真实 QQ 或部署。范围与停止条件见 [pet-team-request-row-actions 目标卡](goals/pet-team-request-row-actions.md)。

### 队伍玩法体验里程碑（2026-10-14，已完成）

三个阶段一次交付：小队名册逐行名帖、页面动作诚实化、邀请/申请/帮助连通。名册此前把每位其他成员的 `灵宠队伍 <UID>` 全部塞进按钮，叠加页面动作后受 `_action_items` 四条上限截断，成员多时后面成员的名帖在 QQ native 键盘不可达；同时名册对队长固定给出 `灵宠组队挑战 上古灵殿`（业务层要求全员已准备，未准备必被拒绝），`灵宠准备` 在出战宠外出派遣时也必被拒绝。

现在 `party.status` 每位其他成员行挂唯一“查看名帖”蓝字（`InlineCommand`，命令 `灵宠队伍 <成员UID>`，只读名帖），容量行挂“组队指南”蓝字（`灵宠帮助 组队与派遣`），行命令退出按钮集合；`party._member_detail` 的身份行同样挂“组队指南”蓝字。页面动作按状态诚实给出：`灵宠组队挑战` 仅在至少两人且全员已准备时出现，`灵宠准备` 仅在出战宠齐全且均未外出派遣（`_can_ready`，与 `require_idle_pet` 同条件）时出现，已准备时给 `灵宠取消准备`；破坏性动作（踢人/转让/解散/退队）仍走按钮。`requests` 的建队、入队、邀请、同意、拒绝、撤回与空队务回退入口都补上 `灵宠帮助 组队与派遣` 下一步。共享常量 `TEAM_HELP` 定义在 `teams/common.py`。玩法规则、授权、过期、准备失效、幂等重放与 schema 20 全部不动。

定向命令 `./.venv/bin/pytest -q tests/test_team_play_ux.py tests/test_team_management.py tests/test_team_requests.py tests/test_team_requests_contract.py tests/test_team_messaging.py tests/test_team_request_interaction.py tests/test_commands.py tests/test_team_concurrency.py tests/test_team_config.py`：`134 passed`（含新增 `test_team_play_ux` 7 项）。新增测试覆盖满员名册逐行蓝字与行位、按钮集合 ≤4 且互不重复且与蓝字零重叠、组队挑战入口仅在全员准备时出现且此时可执行、出战宠外出时不给准备入口、队员名帖保留队长动作与指南蓝字、流程回复均含指南下一步、名册 native payload 蓝字与按钮零重复。共享业务行为只跑一次；QQ 适配器契约 `test_team_messaging` 未改动即通过。`test_team_management` 与 `test_team_request_interaction` 的旧按钮形状断言按需原地更新。未跑全量、仿真、压测、真实 QQ 或部署。

### 道具与灵坊闭环（2026-10-14，已完成）

四个阶段一次交付：灵坊行内详情、乾坤袋分组与逐行动作、购买/使用/喂养/孵化连通、亲密消耗品内容补齐。此前 `economy.shop` 列表把每页五条 `灵宠商店 <物品名>` 全部塞进按钮，叠加分页与 `灵宠背包` 后受 `_action_items` 四条上限截断，第四、五行道具与翻页在 QQ native 键盘不可达；乾坤袋是纯只读平铺列表，没有逐行动作也没有用途说明；`buy`、`use`/`_use_consumable`、`feed` 的回复没有任何后续命令，道具闭环在购买与使用处断掉；消耗品只有精力与修为两类，缺亲密道具。

现在 `economy.shop` 列表每行挂唯一“查看详情”蓝字（`InlineCommand`，命令 `灵宠商店 <物品名>`，既有详情入口），行命令退出按钮集合，按钮只剩 `灵宠商店` 翻页与 `灵宠背包`。`economy.bag` 按消耗品/灵卵/装备灵物/灵术秘笈/材料与丹药分组，每行补上道具用途（取 `description`），并按种类挂当前真能执行的一步：灵粮“喂养”、其他消耗品“使用”、灵卵在名册有名额时“孵化”、装备灵物“装备图鉴”、灵术秘笈“灵术图鉴”；材料与破境丹只给提示。门控与业务层一致：`_can_use` 复用 `Context.pet` 的精力恢复语义并检查 `active_expedition`，`_has_roster_room` 复用 `owned_pets` 与 `spirit_pet_max_pets`；`_use_consumable` 的重复动作按使用后的内存状态判断，不读旧行。`buy` 补 `灵宠背包` + 该道具下一步 + `灵宠商店`，`use`/`feed` 补 `灵宠背包` + 重复动作 + `我的灵宠`，`hatch` 补 `灵宠背包`。内容新增 `affinity_pill 同心丹`（消耗品，亲密 +20，120 灵石），使精力/修为/亲密各有一件灵坊道具；沿用既有消耗品路径，不新增 schema、事件或命令。定价、掉落、效果上限、每日任务事件与幂等重放全部不动。

定向命令 `./.venv/bin/pytest -q tests/test_item_loop.py tests/test_player_experience.py tests/test_pagination.py tests/test_commands.py tests/test_content.py tests/test_pet_catalog.py tests/test_messaging.py tests/test_hatching.py tests/test_crafting.py tests/test_skill_effects.py tests/test_quest_interaction.py tests/test_forging.py tests/test_loadout.py` 与第二批 `tests/test_co_training_contract.py tests/test_effect_models.py tests/test_expedition_occupancy.py tests/test_game.py tests/test_lineages.py tests/test_lineup_readiness.py tests/test_mastery.py tests/test_pet_archive.py tests/test_progression.py tests/test_talents.py tests/test_targeted_care.py`：合计 `735 passed`（含新增 `test_item_loop` 9 项），无既有断言需要改动。新增测试覆盖灵坊逐行蓝字与行位、按钮只剩翻页与背包、乾坤袋分组与用途、消耗品按状态门控（外出/属性满不给入口）、灵卵名额门控、装备与秘笈只读图鉴、材料无可执行入口、购买/使用/喂养/孵化下一步、同心丹购买使用与满亲密拒绝。QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 万灵塔逐层试炼闭环（2026-10-15，已完成）

四个阶段一次交付：内容与校验、业务模块、命令与帮助、定向测试。此前 PVE 只有八处章节关卡，通关后没有更高强度的单人目标；玩家缺少一个可长期攀爬、逐层变难、每层给一次性奖励的试炼线。

新增 `data/tower.json`（八层 `tower_01`..`tower_08`，顺序 1..8，境界启灵→渡劫，精力 20→55，敌手 1→3 只，`previous_id` 成链，首通奖励逐层抬升）与 `domain/tower_content.py::TowerFloor`；`content/catalog.py` 载入 `tower` 并新增 `_validate_tower`（序号连续、境界/敌手/奖励引用存在、前置链闭合、精力 ≤100），塔层奖励并入既有奖励物品校验，成就指标集与终局里程碑加入 `tower_depth`。

`gameplay/tower.py` 提供 `catalog`（列表与层详情）与 `challenge`。列表显示当前深度与每层状态（`可挑战`/`已通关`/`未解锁`），只给可挑战与已通关的行挂唯一“前往挑战”蓝字（`InlineCommand`，命令 `灵宠挑战万灵塔 <层号>`），行命令退出按钮集，按钮保留翻页与 `灵宠关卡`/`灵宠秘境`；未结契玩家可只读浏览且不建号。层详情显示敌手、精力、境界、首通奖励与挑战入口；裸数字按页码处理，与 `灵宠关卡` 一致，层详情用层名。`challenge` 在战斗事务内校验前置层、境界、精力与共享 PVE 冷却，胜利时以 `INSERT ... ON CONFLICT DO NOTHING` 写入既有 `pve_stage_progress`（前缀 `tower_`）并只发一次首通奖励，重复挑战只练熟练度，失败/平局不推进进度，全部写入既有 `battle_records`（`kind='pve_stage'`）。命令注册为 `tower_catalog`（`registered=False`，只读入口）与 `tower_challenge`（`registered=True`），别名 `灵宠万灵塔`/`灵宠挑战万灵塔`，帮助“秘境与关卡”段补两条。

成就侧新增 `tower_depth` 指标（取已通关塔层的最大序号）与“三层登临”“六层凌云”“塔顶问道”三条成就，同时把 `stage_clears` 查询改为排除 `tower_%`，使“章节征服者”仍只统计八处章节。schema 20、既有定价、掉落、效果上限与幂等重放全部不动，未新增离线战斗或第二行程。

定向命令 `./.venv/bin/pytest -q tests/test_tower.py tests/test_pve_stages.py tests/test_stage_content.py tests/test_stage_interaction.py tests/test_achievements.py tests/test_achievement_interaction.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py` 与第二批 `tests/test_information.py tests/test_player_experience.py tests/test_battles.py tests/test_battle_records.py tests/test_identity.py tests/test_game.py`：合计 `397 passed`（含新增 `test_tower` 11 项），无既有断言需要改动。新增测试覆盖八层内容与前置链、列表行位与按钮集合（≤4、互不重复、与蓝字零重叠）、未结契只读浏览不建号、层详情、首通只发一次奖励、重复挑战只练熟练度、失败/平局不推进进度、前置层/境界/精力/冷却/越界/未知名称门控、同消息重放与跨身份拒绝、`tower_depth` 成就可领而 `stage_clears` 不被塔层污染、帮助条目、native payload 蓝字与按钮零重复。QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠培育闭环（2026-10-15，已完成）

四个阶段一次交付：内容与规则、业务模块、命令与帮助、定向测试。此前灵宠获取只有领养、召唤与 6 枚秘境掉落灵卵，灵宠之间没有任何产出玩法；灵卵与孵化路径虽已存在，却只覆盖 27 族中的 6 族。

`data/items.json` 补齐 27 族灵卵（新增 21 枚 `kind: pet_egg`，`price` 留空，描述写明由同族培育所得），`data/rules.json` 新增 `breeding`（`affinity` 100、`energy` 30、`cost.stones` 800），`domain/content.py` 增加 `BreedingRule` 并挂到 `Rules.breeding`，`content/catalog.py` 校验培育成本物品、精力上限与“每个种族都有一枚灵卵”，同时把 `tests/test_pet_catalog.py` 中“灵卵只能来自秘境掉落”的旧断言更新为“秘境掉落灵卵仍须是灵卵，且灵卵覆盖全部种族”。

`gameplay/breeding.py` 提供 `breeding` 分派、`catalog` 与 `breed`。列表显示规则与本人同族配对（编号、亲密、可用精力、阻塞原因或“可培育”），只给就绪配对挂唯一“培育这一对”蓝字（`InlineCommand`，命令 `灵宠培育 A B`），按钮只保留分页与 `灵宠列表`；未结契玩家可只读浏览且不建号。`breed` 在事务内校验归属、封存、行程、同族、亲密、精力与灵石，成功后扣除 800 灵石与双方各 30 精力、写入该族灵卵并 `invalidate_ready`。命令注册为 `breeding`（`registered=False`，只读可浏览，动作分支自行取玩家），别名 `灵宠培育`，帮助“成长”段补两条。schema 20、召唤定价、秘境掉落、亲密上限、精力恢复与每日任务事件全部不动，未新增冷却或第二行程。

定向命令 `./.venv/bin/pytest -q tests/test_breeding.py tests/test_hatching.py tests/test_item_loop.py tests/test_commands.py tests/test_content.py tests/test_pet_catalog.py tests/test_messaging.py tests/test_player_experience.py tests/test_information.py`：合计 `267 passed`（含新增 `test_breeding` 12 项）。新增测试覆盖 27 族灵卵与规则合法性、列表行位与唯一蓝字、按钮集合与蓝字零重叠、阻塞原因（亲密/精力/灵石）、未结契只读不建号、无同族伙伴的下一步、成功扣费发卵、培育灵卵经既有孵化路径成为新伙伴、格式/同一只/无效编号/封存/非同族/亲密/精力/灵石/外出派遣各类拒绝、同消息重放不重复扣费、帮助条目与 native payload 蓝字按钮零重叠。`test_pet_catalog` 的旧灵卵断言按需原地更新；QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠主线闭环（2026-10-15，已完成）

四个阶段一次交付：内容与集成修复、业务模块、命令与帮助、定向测试。此前只有 10 条每日事件任务与 40+ 条无序成就，玩家从结契到渡劫之间没有任何按序引导；`quest_progress` 虽是通用一次性领取表，但 `gameplay/quests.py::refresh` 跨日时执行 `DELETE FROM quest_progress WHERE user_id=?`，会连主线记录一起清空。

新增 `data/main_quests.json`（16 步，`order` 1..16 连续、`previous_id` 成链、指标复用 `AchievementMetric`、一次性 `Reward`）与 `domain/main_quest_content.py::MainQuest`；`content/catalog.py` 载入 `main_quests`、把主线奖励并入奖励物品校验，并新增 `_validate_main_quests`（序号连续、前置链闭合、至少一步）。集成修复：`quests.refresh` 的跨日清理改为 `DELETE ... AND quest_id IN (每日任务 id)`，每日任务跨日清零行为不变，主线行不再被误删。

`gameplay/main_quest.py` 提供 `catalog` 与 `claim`。列表按页展示全部步骤与四态（`已完成`/`可领奖`/`进行中`/`未解锁`）、当前步进度与奖励摘要，当前可领步挂唯一“领取奖励”蓝字（`InlineCommand`，命令 `灵宠主线领奖 <步骤名>`），按钮只保留翻页与 `灵宠任务`；未结契玩家可只读浏览且不建号。`claim` 在事务内校验步骤名、重复领取、按序推进与指标达成，随后 `grant` 发奖并把 `claimed=1` 与领取时的指标值写入 `quest_progress`。命令注册为 `main_quests`（`registered=False`）与 `main_quest_claim`（`registered=True`），别名 `灵宠主线`/`灵宠主线领奖`，帮助“秘境与关卡”段补两条。schema 20、每日任务事件与奖励、成就定义与指标语义全部不动，未新增表或迁移。

定向命令 `./.venv/bin/pytest -q tests/test_main_quest.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_player_experience.py tests/test_information.py tests/test_messaging.py tests/test_achievements.py tests/test_achievement_interaction.py tests/test_adventure_routes.py tests/test_companionship.py` 与第二批 `tests/test_quest_interaction.py tests/test_battles.py tests/test_arena_battles.py tests/test_expedition_commands.py tests/test_hatching.py tests/test_item_loop.py tests/test_breeding.py`：合计 `400 passed`（含新增 `test_main_quest` 9 项），无既有断言需要改动。新增测试覆盖 16 步内容与前置链、四态与进度显示、唯一蓝字与按钮集合零重叠、未结契只读不建号、领取发奖与解锁下一步、未知步骤/乱序/条件未达成/重复领取的拒绝、跨日后主线保留而每日任务清零、同消息重放不重复发奖、帮助条目与 native payload 蓝字按钮零重叠。QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 今日秘境闭环（2026-10-15，已完成）

四个阶段一次交付：内容与规则、业务模块、命令与帮助、定向测试。此前秘境是无限重复内容，规则只有“胜利按参战成员发一份奖励、败平无奖励、无论胜败都消耗精力与共享冷却”，没有任何每日节奏；每日循环只有签到与 10 条每日事件任务，玩家缺少“今天该打哪一处”的轮换目标。

`data/rules.json` 新增 `daily_featured`（`first` 与 `third` 两份 `Reward`），`domain/content.py` 新增 `DailyFeatured` 并挂到 `Rules.daily_featured`（校验两份奖励非空），`content/catalog.py` 把两份今日奖励并入既有奖励物品校验。轮换不需要数据文件。

`gameplay/daily_dungeon.py` 提供 `featured_dungeon`（按 `beijing_day` 的日期序数在九处单人秘境中取模，纯函数）、`wins_today`（由 `battle_records` 与 `battle_participants` 派生当日该秘境胜场）、`claimed_today`（领取行带当日日期，跨日自动失效）、`catalog` 与 `claim`。奖励沿用既有领取约定（与每日任务、成就一致），因此 `adventure.run_dungeon` 的战斗结算路径与平衡门禁完全不变——最初把奖励直接写进 `run_dungeon` 时，`test_balance_lineups` 的生产结算门禁立刻报出 `production settlement violation`，改为领取式后门禁恢复。命令注册为 `daily_dungeon`（`registered=False`，未结契可只读浏览）与 `daily_dungeon_claim`（`registered=True`），别名 `灵宠今日秘境`/`灵宠今日秘境领奖`，帮助“秘境与关卡”段补两条。schema 20、秘境掉落、精力消耗、共享冷却、每日任务事件与组队规则全部不动，未新增计数列或冷却。

定向命令 `./.venv/bin/pytest -q tests/test_daily_dungeon.py tests/test_balance_lineups.py tests/test_adventure_routes.py tests/test_dungeon_interaction.py tests/test_battles.py tests/test_battle_records.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_main_quest.py tests/test_breeding.py tests/test_quest_interaction.py`：合计 `329 passed`（含新增 `test_daily_dungeon` 11 项与平衡门禁 12 项），无既有断言需要改动。新增测试覆盖轮换的纯函数性（同日稳定、跨日轮换、九处循环、只取单人秘境）、未结契只读不建号、列表文本与唯一蓝字、按钮集合与蓝字零重叠、首胜/三胜的可领取与领取发奖、未达成与重复领取的拒绝、非今日秘境不计入、跨日状态失效、重投不重复发奖、帮助条目与 native payload 零重叠。QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 周常任务闭环（2026-10-15，已完成）

四个阶段一次交付：内容与规则、业务模块、命令与帮助、定向测试。此前目标体系只有每日任务（10 条事件计数、跨日清零）、今日秘境（每日轮换）、成就（无序里程碑）与主线（16 步按序引导），没有任何“本周做什么”的中期循环；而周度进度所需的证据已经全部永久留存，因此可以纯派生实现。

新增 `data/weekly_quests.json`（六项，`WeeklyMetric` 词表：`weekly_pve_wins`/`weekly_pvp_wins`/`weekly_expedition_claims`/`weekly_adventures`/`weekly_stage_clears`/`weekly_achievement_claims`）与 `domain/weekly_quest_content.py::WeeklyQuest`；`content/catalog.py` 载入 `weekly_quests` 并把周常奖励并入奖励物品校验（`_index` 已负责空/重复 id 与重名校验）；`utils/time.py` 新增 `beijing_week(now)` 返回本周（周一 00:00 北京时间）起止时间戳。

`gameplay/weekly_quests.py` 提供 `_metric`（六项均按 `[week_start, week_end)` 窗口统计既有永久记录）、`claimed_this_week`（领取行 `progress` 存本周起始时间戳，因此“本周是否已领取”由存储值判定，跨周自动失效，不依赖任何清理时机）、`catalog` 与 `claim`。命令注册为 `weekly_quests`（`registered=False`，未结契可只读浏览）与 `weekly_quest_claim`（`registered=True`），别名 `灵宠周常`/`灵宠周常领奖`，帮助“秘境与关卡”段补两条。奖励沿用既有领取约定，战斗结算路径、平衡门禁、每日任务、今日秘境、成就与主线全部不动；未新增计数列或冷却。

定向命令 `./.venv/bin/pytest -q tests/test_weekly_quests.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_quest_interaction.py tests/test_daily_dungeon.py tests/test_main_quest.py tests/test_achievements.py tests/test_achievement_interaction.py tests/test_adventure_routes.py tests/test_battles.py tests/test_arena_battles.py tests/test_expedition_commands.py tests/test_expedition_content.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_balance_lineups.py`：合计 `435 passed`（含新增 `test_weekly_quests` 10 项），无既有断言需要改动。新增测试覆盖六项内容与指标词表、未结契只读不建号、本周周期与零进度、六项指标只统计本周窗口（上周/下周的记录不计入、塔层不计入章节指标）、未达成与重复领取的拒绝、领取发奖与周标记、跨周归零并重新可领、重投不重复发奖、帮助条目与 native payload 零重叠。QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 装备强化继承闭环（2026-10-15，已完成）

四个阶段一次交付：内容与规则、业务模块、命令与帮助、定向测试。此前装备线只有打造（产出 +0）、强化（逐级消耗）与分解（回收至多 50% 材料、不退灵石）三条路径：玩家把过渡装备强化到高等级后换到更好的同部位装备时，那笔强化投入完全作废，缺少把等级带到新装备上的长期配装路径。

`data/rules.json` 新增 `inheritance_cost`（`ResourceCost`，默认每级 80 灵石 + 1 锻灵矿），`domain/content.py` 的 `Rules` 增加 `inheritance_cost: ResourceCost`，`content/catalog.py` 把该成本物品并入既有校验并要求为材料（与 `resonance_cost` 一致）。不需要新数据文件：部位来自 `items.json` 的 `equipment_id` → `equipment.json` 的 `slot`，等级来自 `forge_levels.json`。

`gameplay/inheritance.py` 提供 `cost`（按源等级线性计算）与 `inherit`：校验两件都是装备灵物、部位相同、不是同一件、源在背包且取最高强化等级 ≥1、目标在背包且未强化，再校验灵石与材料，然后用既有 `equipment_inventory.take`/`put` 完成转移——源回到 +0、目标变为该等级。命令注册为 `inheritance`（`registered=True`），别名 `灵宠强化继承`，帮助“血脉与道具”段补一条。打造、强化、分解的成本与回收规则、战斗数值与平衡门禁全部不动，未新增表或列。

定向命令 `./.venv/bin/pytest -q tests/test_inheritance.py tests/test_crafting.py tests/test_loadout.py tests/test_item_loop.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_balance_lineups.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_main_quest.py tests/test_breeding.py`：合计 `363 passed`（含新增 `test_inheritance` 6 项），无既有断言需要改动。新增测试覆盖按等级计费（+1 与 +10）、源回 +0 与目标变 +N、背包数量与资源校验、格式/同一件/非装备/部位不同/源未强化/目标已有强化/缺少目标/灵石不足/材料不足各类拒绝、继承后可穿戴（既有 `灵宠装备`）、同消息重投不重复扣费与帮助条目。QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠称号闭环（2026-10-15，已完成）

四个阶段一次交付：内容与规则、业务模块、命令与展示、定向测试。此前目标体系已有五种（每日任务、今日秘境、周常、成就、主线），但玩家没有任何身份展示：`我的信息` 只显示 UID 与注册时间，完成万灵塔、主线、论剑、委托之后除成就条目外没有可见的长期沉淀。

新增 `data/titles.json`（16 项，`order` 1..16 连续且兼作优先级）与 `domain/title_content.py::Title`（`TitleMetric = AchievementMetric | Literal["main_quest_claims", "weekly_claims"]`）；`content/catalog.py` 载入 `titles` 并新增 `_validate_titles`（order 连续）。插入校验时注意不要把既有 `if` 与其 `raise` 拆开——本次一度造成 `IndentationError`，`compileall` 立刻暴露。

`gameplay/titles.py` 提供 `_metric`（复用 `achievements._metric`，另实现两个领取数指标）、`earned`（按优先级列出已获得称号）、`current`（已获得中优先级最高者）与 `catalog`（当前称号行 + 逐项 `已获得`/`进度 n/target` + 条件说明，分页）。命令注册为 `titles`（`registered=False`，未结契可只读浏览），别名 `灵宠称号`，帮助“身份与收集”段补一条；`gameplay/information.py` 的 `我的信息` 概况新增“称号：… · 已获得 n/16 项”一行（既有断言为子串匹配，不受影响）。称号纯派生，不落库、不消耗、无冷却；schema 20、成就/主线/周常/今日秘境与战斗、经济结算路径全部不动。

定向命令 `./.venv/bin/pytest -q tests/test_titles.py tests/test_information.py tests/test_commands.py tests/test_content.py tests/test_pet_catalog.py tests/test_messaging.py tests/test_player_experience.py tests/test_achievements.py tests/test_achievement_interaction.py tests/test_main_quest.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_breeding.py tests/test_inheritance.py tests/test_balance_lineups.py`：合计 `349 passed`（含新增 `test_titles` 9 项），无既有断言需要改动。新增测试覆盖 16 项内容与 order 连续、未结契只读不建号、当前称号与逐项进度、最高优先级称号生效（塔层 8 + 渡劫）、主线与周常领取数指标、双灵称号条件、`我的信息` 展示、帮助条目与 native payload 按钮集合。QQ 适配器契约 `test_messaging` 未改动即通过。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠扫荡闭环（2026-10-15，已完成）

四个阶段一次交付：业务模块、命令与帮助、聚焦测试、文档。秘境是可重复内容，但每次都要打完整战斗（最多 40 回合）才能拿一次掉落，重复刷材料时回复冗长；同时每日任务与周常又要求“秘境获胜场次”，因此战斗不能被替代，但重复刷取应当有一条更轻的路径。

新增 `gameplay/sweep.py`：`_cleared` 用 `battle_records JOIN battle_participants` 判定该玩家在该秘境（`kind='pve'`、`battle_key=<秘境 id>`、`winner_side = p.side`）是否已有胜利，因此不需要任何新计数列；`sweep` 复用 `named`、`ctx.check_action`、`ctx.require_idle_pet`、`ctx.active_pets` 与 `rewards.grant`，与 `run_dungeon` 保持同一套境界门槛、精力与冷却语义，并复用 `dungeon.reward` 作为掉落定义。命令注册为 `sweep`（`registered=True`），别名 `灵宠扫荡`，帮助“秘境与关卡”段补一条。

关键边界：扫荡不写 `battle_records`、不调用 `award_mastery`、不调用 `advance(ctx, "pve")`，因此不推进每日任务与周常的获胜计数，也不影响首通与关卡进度；`adventure.run_dungeon` 与平衡门禁路径完全未动。组队秘境、未通关、境界不足、精力不足与冷却中均按既有提示拒绝；未填名称给出格式提示。

定向命令 `./.venv/bin/pytest -q tests/test_sweep.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_adventure_routes.py tests/test_pve_stages.py tests/test_daily_dungeon.py tests/test_weekly_quests.py tests/test_balance_lineups.py tests/test_content.py tests/test_pet_catalog.py tests/test_player_experience.py tests/test_titles.py tests/test_achievements.py tests/test_tower.py`：合计 `357 passed`（含新增 `test_sweep` 10 项），无既有断言需要改动。新增测试覆盖未通关（含败退不算通关）、奖励与精力/冷却、不写战报与不计获胜场次、组队秘境、境界门槛、冷却中、名称缺失/无效、同 `operation_id` 幂等、帮助条目与 native payload 按钮集合。精力断言先固定 `energy_updated`，避免受被动回复影响。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵坊回收闭环（2026-10-15，已完成）

四个阶段一次交付：内容与规则、业务模块、命令与帮助、聚焦测试与文档。审计发现道具只进不出：`灵宠分解` 只接受装备（`named(ctx.content.recipes, …)`，换成材料且明确“不返还灵石”），材料、消耗品、灵术秘笈与破境丹没有任何换回灵石的路径；而秘笈受类别/元素/境界三重门槛限制（例如玄狐学不了水箭术），装备也受元素与类别限制，玩家必然会囤下用不了的道具。

新增 `rules.recycle_percent`（默认 40）与 `Rules.recycle_percent: Annotated[int, Field(gt=0, lt=100)]`——上限 100 由类型约束保证，从结构上杜绝“买入再回收”套利；`data/rules.json` 按唯一锚点文本插入，`git diff --stat` 确认只有 2 行新增。`gameplay/economy.py::recycle` 复用 `item_amount`（名称+数量，缺省 1）与 `named`，先拒绝装备（“装备请用 灵宠分解 回收材料。”）与无售价道具（“该道具不在灵坊出售，无法回收。”），再按 `售价 × 数量 × percent // 100` 结算并拒绝不足 1 灵石的情况，最后用既有 `Repository.consume_item` 扣道具、`player.stones` 加灵石。命令注册为 `recycle`（`registered=True`），别名 `灵宠回收`，帮助“血脉与道具”段补一条（与 `灵宠购买`/`灵宠使用` 同段，而非 `灵宠分解` 所在的“灵物与灵术”段）。

关键边界：回收只写 `inventory.quantity` 与 `players.stones`，不写 `battle_records`、不推进任务与成就、不改动宠物与装备；装备分解规则与打造套利不变量（`cheaper materials`）完全不动。非战斗动作没有持久重放守卫，因此合同测试断言同 `operation_id` 重投返回原回复且只结算一次。

定向命令 `./.venv/bin/pytest -q tests/test_recycle.py tests/test_crafting.py tests/test_loadout.py tests/test_item_loop.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_content.py tests/test_pet_catalog.py tests/test_balance_lineups.py tests/test_sweep.py tests/test_titles.py tests/test_inheritance.py tests/test_breeding.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_main_quest.py`：合计 `395 passed`（含新增 `test_recycle` 13 项），无既有断言需要改动。新增测试覆盖比例区间与逐件套利不可能、回收结算与取整、无售价道具（青藤灵卵）、装备拒绝、背包不足、参数与数量越界、未结契、零记录零宠物影响、同 `operation_id` 幂等、买入再回收必然亏损、帮助条目与 native payload 按钮集合。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠批量强化闭环（2026-10-15，已完成）

四个阶段一次交付：业务模块、命令与帮助、聚焦测试、文档。审计发现强化只能一级一级点：`forge_levels` 是 0..10 的阶梯（80/120/180/260/360/480/620/780/960/1160 灵石配 1..10 锻灵矿），把新装备推到 +5 要 5 条命令、+10 要 10 条，是当前最重复的配装动作；其余候选都已被既有系统覆盖（战报详情已按页渲染完整日志、关卡只在首通发奖、材料与秘笈已有灵坊回收出口、内容可达性审计无缺口）。

`gameplay/forging.py::enhance` 改为先 `arg.split()` 再解析：超过两段给出格式示例，第一段交给既有 `selected_slot`（槽位或装备名），第二段作为可选目标等级（`isdecimal` 且 1-`len(forge_levels)-1`，否则“目标等级须为 1-10 的整数”）。随后统一按 `range(level, target or level + 1)` 收集阶梯，逐级累加 `upgrade_stones` 与 `upgrade_items`；任一级 `upgrade_stones is None` 时按有无目标分别给出“该装备已达最高强化等级。”或“该装备最高只能强化到 +N。”。灵石不足时沿用既有“强化需要 …，灵石不足。”句式并带上总消耗；材料走既有 `Repository.consume_item`（不足即“道具数量不足”）并整条回滚。成功后一次 `UPDATE equipment SET enhancement=?` 写到 `level + len(steps)`，回复沿用“灵物淬炼”与既有两行格式。不带目标等级时 `steps` 只有一级，消息与成本与改动前完全一致，因此 `test_crafting`/`test_forging` 无需改动。

关键边界：整条命令原子（灵石与材料在同一事务内结算，任一步失败等级/灵石/材料都不变）；目标等级必须高于当前等级，超过 +10 被拒绝；逐级定价、倍率、回收规则、打造与分解、强化继承与灵坊回收全部不动，schema 20 不变。

定向命令 `./.venv/bin/pytest -q tests/test_batch_enhance.py tests/test_forging.py tests/test_crafting.py tests/test_loadout.py tests/test_item_loop.py tests/test_inheritance.py tests/test_recycle.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_content.py tests/test_pet_catalog.py tests/test_balance_lineups.py tests/test_battle_records.py tests/test_sweep.py tests/test_titles.py tests/test_breeding.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_main_quest.py`：合计 `428 passed`（含新增 `test_batch_enhance` 11 项），无既有断言需要改动。新增测试覆盖 +0→+5 的阶梯成本（1000 灵石、15 锻灵矿）、逐级路径字节一致、灵石不足与材料不足时的原子性、目标不高于当前等级、目标越界/非数字/段数错误、空部位、满级两条路径、同 `operation_id` 幂等、帮助条目与 native payload 按钮集合。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠目标闭环（2026-10-15，已完成）

四个阶段一次交付：业务模块、命令与帮助、聚焦测试、文档。审计发现目标体系已经长到五套（每日任务 10 项、周常 6 项、主线 16 步、成就 50 项、称号 16 项）外加今日秘境，却没有任何一处能看到“现在有哪些奖励可以领”；玩家必须依次打开 `灵宠任务`、`灵宠周常`、`灵宠主线`、`灵宠成就`、`灵宠今日秘境` 才能发现可领项，跨页可领项尤其容易漏掉。这是本轮自己新增四个目标面之后新出现的摩擦，也说明目标面继续增加时必须有一个汇总入口。

新增 `gameplay/objectives.py`：`objectives` 是 `registered=False` 的只读命令，先拒绝参数（“灵宠目标 不接受参数，直接发送即可。”），未结契时只返回预览与“开始领养”蓝字（不建号），否则调用 `quests.refresh`（与 `灵宠任务` 同一条跨日重置路径）后拼六行——`_daily_line` 镜像 `quests.quests` 的可领判定读 `quest_progress`，`_weekly_line` 用 `weekly_quests.claimed_this_week`/`_metric`，`_main_quest_line` 用 `main_quest._claimed`/`_current`/`_state`，`_achievement_line` 用 `achievements._metric` 与 `achievement_claims`，`_dungeon_line` 用 `daily_dungeon.featured_dungeon`/`wins_today`/`_state`，`_title_line` 用 `titles.earned`。每行挂该体系入口蓝字（`HUB_PAGES`），按钮保留 `灵宠帮助` 与 `我的灵宠`，与行蓝字零重叠。命令注册为 `objectives`（`registered=False`），别名 `灵宠目标`，帮助“身份与收集”段补一条。

关键边界：汇总只读派生，不发放奖励、不写 `battle_records`、不推进任务与成就、不改动宠物与装备；唯一的写入是 `quests.refresh` 的跨日每日任务重置（与 `灵宠任务` 行为一致）。未结契预览不创建玩家行。不新增表或列、不新增数据文件与规则字段，既有各体系规则、奖励与领取条件全部不动。

定向命令 `./.venv/bin/pytest -q tests/test_objectives.py tests/test_quest_interaction.py tests/test_weekly_quests.py tests/test_main_quest.py tests/test_achievements.py tests/test_achievement_interaction.py tests/test_titles.py tests/test_daily_dungeon.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_content.py tests/test_pet_catalog.py tests/test_balance_lineups.py tests/test_batch_enhance.py tests/test_recycle.py tests/test_sweep.py tests/test_forging.py tests/test_crafting.py`：合计 `439 passed`（含新增 `test_objectives` 9 项），无既有断言需要改动。新增测试覆盖六行内容与各体系计数、签到后可领数变化、领取后回落、主线下一步与称号行、未结契只读预览且不建号、参数拒绝、只读性（无战报与成就领取行、宠物精力不变）、同 `operation_id` 幂等、帮助条目与 native payload 按钮/蓝字零重叠。未跑全量、仿真、压测、真实 QQ 或部署。

### 成就扩充闭环（2026-10-15，已完成）

四个阶段一次交付：指标与内容、业务分支、聚焦测试、文档。审计发现成就的指标词汇停留在早期系统：装备强化（`forge_levels` 0..10 阶梯、`equipment.enhancement`）、切磋（`battle_records.kind='spar'`）、累计战斗（`battle_participants`）、装备收藏（`equipment` + `unequipped_equipment`）、成就领取（`achievement_claims`）与共鸣启用（`player_resonance`）都没有任何成就，玩家把装备强化到 +10 或赢下 50 场切磋，成就页毫无反馈。这些指标全部可从既有持久化只读派生，因此本项在 schema 20 冻结下完成，不新增表或计数列。

`domain/achievement_content.py` 的 `AchievementMetric` 增加六个指标；`data/achievements.json` 追加 14 项成就（50 → 64）：初试锋芒 +3、精炼有成 +6、炉火纯青 +10；切磋初胜 1、切磋十胜 10、切磋五十胜 50；十战之身 10、百战之身 100、千锤百炼 500；装备初集 5、装备成库 15；成就初集 5、成就成册 20；共鸣初启 1。奖励复用既有物品与灵石，档位与既有成就同量级。`content/catalog.py` 把六个指标加入 `required`，`maxima` 增加 `max_enhancement = len(forge_levels) - 1`，并把 `max_enhancement` 加入 `final_milestones`（因此 +10 里程碑必须在册，改小目标会先触发 `missing final achievement milestone for max_enhancement`）；无界指标（战斗总量、装备收藏、成就领取数）不设上限，用固定目标。

`gameplay/achievements.py::_metric` 增加六个分支：`max_enhancement` 用 `equipment`（经 `pets` 关联到 `user_id`）与 `unequipped_equipment` 的 `UNION ALL` 取 `MAX(enhancement)`，`spar_wins` 用 `battle_records` 连接 `battle_participants` 且 `kind='spar' AND winner_side=p.side`，`battles_fought` 统计 `battle_participants`，`equipment_owned` 把两处装备表计数相加，`achievements_claimed` 统计 `achievement_claims`，`resonances_enabled` 统计 `player_resonance`。`_milestone` 为 `max_enhancement` 返回 `+N`，`_progress` 把它并入“当前 / 目标”的里程碑格式。领取沿用既有 `achievement_claims` 路径与奖励快照，既有 50 项成就的目标、奖励与领取行为完全不变。

定向命令 `./.venv/bin/pytest -q tests/test_achievement_expansion.py tests/test_achievements.py tests/test_achievement_interaction.py tests/test_objectives.py tests/test_titles.py tests/test_information.py tests/test_commands.py tests/test_messaging.py tests/test_content.py tests/test_pet_catalog.py tests/test_balance_lineups.py tests/test_crafting.py tests/test_forging.py tests/test_loadout.py tests/test_item_loop.py tests/test_battle_records.py tests/test_arena_battles.py tests/test_arena_messaging.py tests/test_mastery.py tests/test_resonance.py tests/test_resonance_contract.py tests/test_quest_interaction.py tests/test_weekly_quests.py tests/test_main_quest.py tests/test_daily_dungeon.py`：合计 `471 passed`（含新增 `test_achievement_expansion` 11 项），既有断言无需改动。新增测试覆盖六个指标在空存档与未结契用户下均为 0 且不写任何行、强化等级跨两处装备表取最大、切磋胜场按永久战报的胜方判定（败方为 0）、累计战斗场次、装备收藏跨两处装备表、成就领取计数、共鸣启用计数、新成就在成就页的 `可领奖`/`进行中` 呈现与领取一次/重复拒绝/重投幂等、`灵宠目标` 成就行随新可领项变化、内容校验（`required` 覆盖、+10 里程碑在册、目标不得超出 `maxima`）与 native payload 按钮/蓝字零重叠。未跑全量、仿真、压测、真实 QQ 或部署。

### 秘境首通奖励闭环（2026-10-15，已完成）

四个阶段一次交付：内容与校验、业务与命令、聚焦测试、文档。审计发现关卡有首通奖励（`pve_stage_progress`，首次通关发奖并记录），但秘境完全没有首通概念：16 处秘境每次获胜都发同一份随机奖励，第一次通关没有任何额外反馈，也没有“把 16 处秘境各通关一次”的完成度目标。秘境是主要 PVE 循环，却缺少完成度激励。

`domain/content.py` 的 `Dungeon` 增加 `first_clear: Reward | None = None`（保持既有构造兼容），`data/dungeons.json` 用文本锚点按 `"id"` 定位并插在 `"reward"` 行之前，为 16 处秘境各补一行 `first_clear`（`exp` 固定 0-0，灵石与道具为固定值）：青岚林 150 + 锻灵矿 2、上古灵殿 250 + 锻灵矿 3、月影谷 200 + 锻灵矿 2、寒晶洞 220 + 血脉精华 1、腐毒沼 220 + 灵粮 3、潮生宫 350 + 血脉精华 2、雷泽 300 + 锻灵矿 3、幽冥深渊 450 + 血脉精华 2、焚天峰 400 + 锻灵矿 4、玄玉天阙 600 + 血脉精华 3、万载霜渊 500 + 锻灵矿 5、万木归墟 750 + 血脉精华 3、太虚剑境 650 + 蕴灵丹 2、冥帝幽庭 900 + 血脉精华 4、九霄劫海 800 + 蕴灵丹 3、太上天门 1200 + 血脉精华 5。`content/catalog.py` 新增完整性校验（`dungeon <id> is missing a first-clear reward`），并把 `first_clear` 奖励并入既有的奖励物品校验列表。

`gameplay/first_clear.py`：`claim_id(dungeon_id)` 返回 `first_clear_<秘境 id>`，`claimed` 读 `quest_progress` 的 `claimed`（一次性，不比较日期），通关判定直接复用 `sweep._cleared`（永久战报派生，`winner_side=side`，败退与平局不算）——两条路径共用同一判定，不会各自漂移。`catalog` 分页每页 5 处（16 处共 4 页），逐行给出 `名称（单人/组队）· 奖励摘要 · 状态`，`可领取` 行挂 `灵宠秘境首通领奖 <秘境名>` 蓝字，页尾给出可领数量；未结契时只返回预览与“开始领养”蓝字，不建号。`claim` 依次校验已领取、未通关，再 `grant(ctx, dungeon.first_clear, user_id)` 并写入 `quest_progress` 标记（`progress=0`，一次性）。命令注册为 `first_clear`（`registered=False`，页面可只读）与 `first_clear_claim`（`registered=True`），别名 `灵宠秘境首通` / `灵宠秘境首通领奖`，帮助“秘境与关卡”段补两条，`灵宠目标` 增加第七行“秘境首通”。

关键边界：不改动秘境战斗结算、掉落、精力与冷却——首通奖励只在结算路径之外补一份一次性领取，因此平衡门禁“一次秘境胜利只付秘境自身奖励”不变；不新增表或列，领取标记复用 `quest_progress`。

定向命令 `./.venv/bin/pytest -q tests/test_first_clear.py tests/test_sweep.py tests/test_daily_dungeon.py tests/test_objectives.py tests/test_achievement_expansion.py tests/test_achievements.py tests/test_achievement_interaction.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_balance_lineups.py tests/test_battle_records.py tests/test_arena_battles.py tests/test_arena_messaging.py tests/test_mastery.py tests/test_tower.py tests/test_main_quest.py tests/test_weekly_quests.py tests/test_quest_interaction.py tests/test_crafting.py tests/test_forging.py tests/test_dungeon_interaction.py tests/test_stage_interaction.py`：合计 `467 passed`（含新增 `test_first_clear` 10 项），既有断言无需改动。新增测试覆盖分页与页数边界、未通关拒绝、通关后解锁并发放一次（灵石 +150、锻灵矿 +2）、重复领取拒绝与同 `operation_id` 幂等、未结契只读预览且不建号、`灵宠目标` 秘境首通行随领取变化、组队秘境按真实胜利判定（从战报读取胜方并逐人核对）、缺少 `first_clear` 的内容被拒绝、native payload 按钮与行蓝字零重叠、帮助条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 每周免费召唤闭环（2026-10-15，已完成）

四个阶段一次交付：业务、命令与帮助、聚焦测试、文档。审计发现召唤是除秘境灵卵外唯一的获取新种族途径，但只有付费一条路（标准池 100 灵石/次、十连 1000 灵石并有珍稀保底）；每日循环里没有免费但有限的召唤，周常六项也都与召唤无关。已排除的方向：新增装备部位（schema 20 的 `equipment.slot` 有 `CHECK (slot IN ('weapon','armor','charm'))`，必须改 schema）；批量扫荡（扫荡进入共享 PVE 冷却，无法连续执行）；改名/道号（有意移除并有合同测试锁定）；好友/交易/信箱（需要新表）。

`gameplay/pets.py::summon` 增加可选 `free` 参数：`cost = 0 if free else count * pool.stones`，并把首行改为 `本次召唤不消耗灵石。`；付费路径的定价、权重、保底与文案保持字节一致（`test_pets`、`test_catalog_interaction` 不改动即通过）。新增 `gameplay/free_summon.py`：`CLAIM = "free_summon_weekly"`、`DRAW_COUNT = 10`，`available` 直接复用 `weekly_quests.claimed_this_week`（存储的周起始必须等于当前周起始），`catalog` 给出状态、规则与名册上限提示并在可领时挂 `灵宠每周召唤领取` 蓝字（未结契只返回预览与“开始领养”蓝字，不建号），`claim` 先校验本周未领取，再调用 `summon(ctx, "10", free=True)`，成功后把 `beijing_week(ctx.now)` 的起始时间戳写入 `quest_progress`。名册检查在 `summon` 内部先于任何写入，因此名册已满时抛错且标记未写入，本周机会保留。命令注册为 `free_summon`（`registered=False`，页面可只读）与 `free_summon_claim`（`registered=True`），别名 `灵宠每周召唤` / `灵宠每周召唤领取`，帮助“结契”段补两条，`灵宠目标` 增加第八行“每周召唤”。

关键边界：不新增表或列、不新增数据文件与规则字段；付费召唤的定价、权重、保底与名册上限完全不变；领取标记按周失效且不累积。

定向命令 `./.venv/bin/pytest -q tests/test_free_summon.py tests/test_objectives.py tests/test_first_clear.py tests/test_weekly_quests.py tests/test_quest_interaction.py tests/test_catalog_interaction.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_balance_lineups.py tests/test_achievement_expansion.py tests/test_achievements.py tests/test_breeding.py tests/test_tower.py tests/test_main_quest.py tests/test_daily_dungeon.py tests/test_player_experience.py tests/test_item_loop.py tests/test_crafting.py`：合计 `445 passed`（含新增 `test_free_summon` 9 项），既有断言无需改动。新增测试覆盖未结契只读预览且不建号、页面状态与蓝字、领取后一次得到 10 只且灵石不变、保底文案、本周重复领取拒绝与同 `operation_id` 幂等、跨周（`now + 8 天`）重新可领、名册已满时拒绝且不写入标记（本周机会保留）、付费召唤仍扣 100 灵石、`灵宠目标` 每周召唤行随领取变化、native payload 按钮与行蓝字零重叠、帮助条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 山海行纪闭环（2026-10-15，已完成）

四个阶段一次交付：内容与校验、业务与命令、聚焦测试、文档。审计发现内容之间没有叙事主线：`灵宠主线` 的 16 步是通用指标（拥有 X 只、修炼 N 次），与具体地点、奇闻、种族无关；14 条奇闻、7 条路线、16 处秘境、27 族灵宠各自独立，玩家没有任何一条“按故事顺序走遍山海”的旅程。奇闻有文案但没有前后关系，路线有境界门槛但没有章节感。

新增 `data/journey.json`：14 章（每境界 2 章）按 `previous_id` 串成单链，从启灵的「灵泉初醒」（通关青岚林）到渡劫的「天门问道」（达到渡劫）。每章含 `realm`、`story`、`task` 与一次性 `reward`；任务类型六种——`clear_dungeon`、`win_at`（可带 `count`）、`discover`、`collect_species`、`enable_resonance`、`reach_realm`。`domain/journey_content.py` 定义 `JourneyTask`/`Journey`，`content/catalog.py` 的 `_validate_journey` 校验境界引用、每境界至少一章、恰好一个首章、链条无环无分叉且全覆盖、前置章节境界不倒退、任务目标按类型引用（秘境/奇闻/种族/共鸣/境界）、可达性不越界（秘境 `min_realm`、奇闻所属路线 `min_realm`、`reach_realm` 目标都不得高于本章境界）、只有 `win_at` 允许 `count > 1`、奖励物品存在；`journey` 奖励也并入既有的奖励物品校验元组。

`gameplay/journey.py`：`_value` 按类型派生进度——`clear_dungeon` 直接复用 `sweep._cleared`（与扫荡、秘境首通同源），`win_at` 统计永久战报中该秘境的胜场，`discover` 读 `adventure_discoveries`，`collect_species` 读 `pets`，`enable_resonance` 读 `player_resonance`，`reach_realm` 比较 `MAX(realm)` 与目标境界序号。`_state` 依次判定已领取、前置未领取（`未解锁`）、任务达成（`可领取`）与进行中；`catalog` 每页 5 章，每章两行（状态行 + 故事文案），可领章挂 `灵宠行纪领奖 <章节名>` 蓝字，未结契只返回预览与“开始领养”蓝字；`claim` 依次校验重复领取、前置章节、任务进度，再 `grant` 并把标记写入 `quest_progress` 的 `journey_<章节 id>`（`progress=0`，一次性），回复给出下一章解锁提示。命令注册为 `journey`（`registered=False`）与 `journey_claim`（`registered=True`），别名 `灵宠行纪` / `灵宠行纪领奖`，帮助“秘境与关卡”段补两条（与主线条目同段），`灵宠目标` 增加第九行“行纪”。

关键边界：不新增表或列、不新增规则字段；不改动主线、周常、成就、称号、秘境、关卡与召唤的任何规则与数值；进度只读派生，领取标记按一次性保存且不随日期失效。

定向命令 `./.venv/bin/pytest -q tests/test_journey.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_objectives.py tests/test_main_quest.py tests/test_achievements.py tests/test_achievement_expansion.py tests/test_first_clear.py tests/test_free_summon.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_balance_lineups.py tests/test_dungeon_interaction.py tests/test_sweep.py tests/test_tower.py tests/test_breeding.py tests/test_catalog_interaction.py tests/test_quest_interaction.py`：合计 `375 passed`（含新增 `test_journey` 11 项），既有断言无需改动。新增测试覆盖未结契只读预览且不建号、分页与页数边界、章节状态与故事文案、首章需先通关秘境、领取发放奖励并解锁下一章、锁定与重复领取被拒、同 `operation_id` 幂等、六种任务类型的派生进度（含两连胜与境界门槛）、`灵宠目标` 行纪行、内容校验（链条断裂、目标不存在、可达性越界）、native payload 按钮与行蓝字零重叠、帮助条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 奇闻回响闭环（2026-10-15，已完成）

四个阶段一次交付：内容与校验、业务与命令、聚焦测试、文档。审计发现 14 条奇闻是一次性、无选择的：探索按权重随机触发、发一份固定奖励并写入 `adventure_discoveries`，之后这条奇闻再也不能交互；全游戏只有血脉分支是永久选择，奇闻这条最有叙事潜力的内容线完全没有玩家能动性。

`domain/content.py` 新增 `EncounterOption`（`id`、`label`、`text`、`reward`），`Encounter` 增加 `options: list[EncounterOption]`（默认空，保持既有构造兼容）。`data/adventures.json` 用文本锚点按 `"id"` 定位、插在 `"reward"` 行之前，为 14 条奇闻各补 2 个互斥选项（奖励按路线境界从 60 灵石递增到 750 灵石，并带灵粮/锻灵矿/血脉精华），既有 `text`、`weight`、`reward` 字节不变。`content/catalog.py` 校验每条奇闻 2-3 个选项、选项 id 在奇闻内唯一，并把选项奖励并入统一的奖励物品校验元组。

`gameplay/echoes.py`：`_discovered` 读 `adventure_discoveries`（未发现不可回响），`_chosen` 读 `quest_progress` 的 `echo_<奇闻 id>` 并用 `progress` 还原所选选项，`_rows` 为每条已发现奇闻的每个选项生成 `可回响`/`已回响（选项名）`/`已错过` 三态；`catalog` 每页 5 行（每选项一行），可选项挂 `灵宠回响选择 <奇闻名> <选项名>` 蓝字，页尾给出已发现奇闻数与可回响选项数，未结契只返回预览与“开始领养”蓝字；`choose` 依次校验参数格式、奇闻是否发现、是否已回响、选项是否存在（不存在时列出可选选项），再 `grant` 并把选项序号写入 `quest_progress`。命令注册为 `echoes`（`registered=False`）与 `echo_choose`（`registered=True`），别名 `灵宠回响` / `灵宠回响选择`，帮助“秘境与关卡”段在奇闻条目旁补两条，`灵宠目标` 增加第十行“回响”。

关键边界：不新增表或列；探索触发概率、触发奖励与奇闻文案完全不变（回响是独立的主动选择路径）；同一条奇闻的选项互斥，由“已有标记”派生，不需要额外状态。

定向命令 `./.venv/bin/pytest -q tests/test_echoes.py tests/test_adventure_routes.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_objectives.py tests/test_journey.py tests/test_achievements.py tests/test_achievement_expansion.py tests/test_first_clear.py tests/test_free_summon.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_balance_lineups.py tests/test_catalog_interaction.py tests/test_quest_interaction.py tests/test_player_experience.py`：合计 `393 passed`（含新增 `test_echoes` 11 项与既有 `test_adventure_routes` 12 项），既有断言无需改动。新增测试覆盖未结契只读预览且不建号、未发现奇闻不出现、发现后列出全部选项、选择发放选项奖励并锁定其余选项、未发现与未知选项与格式错误被拒、重复回响被拒与同 `operation_id` 幂等、`灵宠目标` 回响行、内容校验（选项少于 2 个、id 重复、奖励物品缺失）、全部奇闻的选项完整性、native payload 按钮与行蓝字零重叠、帮助条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 赛季任务闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务与命令、聚焦测试、文档。审计发现论剑赛季只有排名档位奖励（青云/凌霄/天阙，按 rating 判定），没有任何赛季目标：玩家在整个赛季里除了“打够场次、冲分”没有可勾选的清单，赛季与每日/每周任务之间也没有衔接。

新增 `data/season_missions.json` 五项赛季目标：论剑历练（本赛季参加 10 场论剑）、论剑争锋（本赛季赢下 5 场）、山海征战（本赛季在秘境或关卡获胜 5 场）、奇闻寻访（本赛季发现 3 条奇闻）、成就累积（本赛季领取 3 项成就奖励）。`domain/season_mission_content.py` 定义 `SeasonMissionMetric` 与 `SeasonMission`，`content/catalog.py` 的 `_validate_season_missions` 校验五种指标必须全部在册、不得出现重复的“指标 + 目标”组合，并把奖励并入统一的奖励物品校验元组。

`gameplay/season_missions.py`：`window` 直接复用 `utils.time.season_bounds`（北京时间自然月起止），`_value` 按指标派生——`season_matches`/`season_wins` 读 `pvp_results`（按 `season_id`，参与计挑战者或目标任一侧，胜场计 `winner_id`），`season_pve` 统计 `battle_records` 中 `kind IN ('pve','pve_stage')` 且 `winner_side=side` 且 `played_at` 落在窗口内的记录，`season_discoveries` 读 `adventure_discoveries.discovered_at`，`season_claims` 读 `achievement_claims.claimed_at`。`_claimed` 要求存储的赛季起始等于当前赛季起始（与周常同款，但窗口为自然月）。`catalog` 每页 5 项，逐项两行（奖励摘要 + 状态行、说明行），页尾给出赛季号、剩余天数与已领取/可领取计数，未结契只返回预览与“开始领养”蓝字；`claim` 依次校验本赛季是否已领取、进度是否达标，再 `grant` 并把赛季起始写入 `quest_progress` 的 `season_<任务 id>`。命令注册为 `season_missions`（`registered=False`）与 `season_mission_claim`（`registered=True`），别名 `灵宠赛季任务` / `灵宠赛季任务领奖`，帮助“对战与赛季”段补两条，`灵宠目标` 增加第十一行“赛季任务”。

关键边界：不新增表或列、不新增规则字段；赛季档位奖励、积分规则、场次限额与每日限额完全不变；进度只统计当前赛季窗口内的记录，换季自动重置且未领取不累积。

定向命令 `./.venv/bin/pytest -q tests/test_season_missions.py tests/test_seasons.py tests/test_arena_battles.py tests/test_arena_content.py tests/test_arena_interaction.py tests/test_arena_matching.py tests/test_arena_messaging.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_objectives.py tests/test_journey.py tests/test_echoes.py tests/test_achievements.py tests/test_first_clear.py tests/test_free_summon.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_balance_lineups.py tests/test_catalog_interaction.py tests/test_quest_interaction.py tests/test_player_experience.py`：合计 `585 passed`（含新增 `test_season_missions` 12 项与全部论剑/赛季既有合同），既有断言无需改动。新增测试覆盖未结契只读预览且不建号、页面内容与赛季行、五种指标的派生进度（含窗口外记录不计）、领取发放奖励并写入赛季起始、未达成与重复领取被拒、同 `operation_id` 幂等、换季重新可领、`灵宠目标` 赛季任务行、内容校验（指标缺失、重复目标、奖励物品缺失）、native payload 按钮与行蓝字零重叠、帮助条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 今日课题闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务与命令、聚焦测试、文档。审计发现每日任务十项是固定清单、今日秘境是固定轮换，玩家每天都是“照着清单做完”，日常循环里没有任何当日决策（全游戏只有奇闻回响与血脉分支提供选择）。

新增 `data/daily_assignments.json` 六项课题：秘境一胜（今日秘境或关卡获胜 1 场）、论剑一试（今日参加 1 场论剑）、奇闻一探（今日发现 1 条奇闻）、委托一程（今日领取 1 次离线委托）、成就一收（今日领取 1 项成就奖励）、吐纳一回（今日修炼 1 次）。`domain/daily_assignment_content.py` 定义 `DailyAssignmentMetric` 与 `DailyAssignment`，`content/catalog.py` 的 `_validate_daily_assignments` 校验六种指标必须全部在册、不得出现重复的“指标 + 目标”组合，并把奖励并入统一的奖励物品校验元组（指标齐全已隐含至少六项，因此不再单设“至少三项”的分支）。

`gameplay/daily_assignment.py`：`todays` 用 `day_ordinal`（`beijing_day` 的日期序数）从池中取 `pool[(序数 * 3 + i) % len(pool)]` 三项，确定性、同一天稳定、次日换新；`_value` 按指标派生且只统计当天——`daily_pve` 扫 `battle_records` 的今日胜场，`daily_pvp` 扫 `pvp_results` 的今日参与，`daily_discovery` 读 `adventure_discoveries.discovered_at`，`daily_expedition` 读 `expeditions.settled_at`（`state='claimed'`），`daily_claim` 读 `achievement_claims.claimed_at`，`daily_training` 比较 `players.last_train` 的日期；所有时间戳查询都用 `SCAN_WINDOW`（两天）限定扫描范围，与今日秘境同款。`_chosen` 从 `quest_progress` 的 `daily_assignment` 行还原今日所选（`progress // 10` 必须等于今日序数，`progress % 10` 为所选序号，越界即视为未选）。`catalog` 逐项两行（奖励摘要 + 状态行、说明行），未结契只返回预览与“开始领养”蓝字；`claim` 依次校验课题是否属于今日三项、今日是否已领取、进度是否达标，再 `grant` 并写入 `progress = 序数 * 10 + 序号`。命令注册为 `daily_assignment`（`registered=False`）与 `daily_assignment_claim`（`registered=True`），别名 `灵宠课题` / `灵宠课题领奖`，帮助“秘境与关卡”段在每日任务条目旁补两条，`灵宠目标` 增加第十二行“今日课题”。

关键边界：不新增表或列、不新增规则字段；每日任务、今日秘境、周常、赛季任务与任何既有奖励完全不变；当日只能领取一项，其余两项作废，次日自动重置且未领取不累积。

定向命令 `./.venv/bin/pytest -q tests/test_daily_assignment.py tests/test_expedition_commands.py tests/test_expedition_content.py tests/test_expedition_contract.py tests/test_expedition_interaction.py tests/test_expedition_occupancy.py tests/test_expedition_storage.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_objectives.py tests/test_journey.py tests/test_echoes.py tests/test_season_missions.py tests/test_achievements.py tests/test_first_clear.py tests/test_free_summon.py tests/test_weekly_quests.py tests/test_daily_dungeon.py tests/test_quest_interaction.py tests/test_balance_lineups.py tests/test_catalog_interaction.py tests/test_player_experience.py`：合计 `690 passed`（含新增 `test_daily_assignment` 12 项与全部委托既有合同），既有断言无需改动。新增测试覆盖未结契只读预览且不建号、三项轮换的确定性与次日变化、六种指标的当日派生（含昨日记录不计）、领取发放奖励并锁定其余两项、未提供与未完成被拒、同 `operation_id` 幂等、次日重新可领、`灵宠目标` 今日课题行、内容校验（指标缺失、重复目标、奖励物品缺失）、native payload 按钮与行蓝字零重叠、帮助条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 新体系成就与称号闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计发现身份体系没有跟上后加的三个领取式系统：成就的 25 个指标与称号的 16 项全部来自早期系统（收集、境界、血脉、塔、论剑、秘境、技能、委托、亲密、强化、切磋、装备、共鸣），玩家走完 14 段山海行纪、回响全部 14 条奇闻、领满 16 处秘境首通，身份页上不会留下任何痕迹。

`domain/achievement_content.py` 的 `AchievementMetric` 增加 `journey_claims`、`echo_claims`、`first_clear_claims`；`gameplay/achievements.py::_metric` 用一个分支处理三者：按 `quest_progress` 中 `claimed=1` 且 `quest_id LIKE '<前缀>%'` 计数（前缀分别为 `journey_`、`echo_`、`first_clear_`）。三个前缀互不重叠，也不会与每日任务、周常、主线、赛季、今日课题的标记冲突。`gameplay/titles.py` 复用同一函数，因此新指标自动可用于称号。

`data/achievements.json` 追加 7 项（64 → 71）：行纪三章 3、行纪七章 7、行纪全章 14；回响三章 3、回响全章 14；秘境五通 5、秘境全通 16。`data/titles.json` 追加 3 项（16 → 19）：山海尽头（`journey_claims` 14，order 17）、万籁归心（`echo_claims` 14，order 18）、秘境行家（`first_clear_claims` 16，order 19）。既有条目的 id、名称、说明、数值与顺序字节不变。

`content/catalog.py`：`required` 加入三个指标；`maxima` 加入 `journey_claims = len(self.journey)`、`echo_claims = len(self.encounters)`、`first_clear_claims = len(self.dungeons)`；`final_milestones` 加入三者，因此每个指标都必须有达到上限的成就（删掉 `journey_all` 会报 `missing final achievement milestone for journey_claims`）。

关键边界：不新增命令、表、列或规则字段；`灵宠成就`、`灵宠称号`、`灵宠目标` 自动包含新条目，无需改动；行纪、回响、首通的业务逻辑与奖励完全不变。

定向命令 `./.venv/bin/pytest -q tests/test_system_achievements.py tests/test_titles.py tests/test_objectives.py tests/test_achievements.py tests/test_achievement_expansion.py`：合计 `76 passed`（新增 `test_system_achievements` 8 项）。同步更新 `test_titles.py` 与 `test_objectives.py` 中写死的称号总数（16 → 19）——这是本次唯一需要改动的既有断言。新增测试覆盖三个指标的派生（未领取标记与无关前缀不计、跨玩家隔离）、行纪成就 3/7/14 的解锁与领取、回响与首通成就的解锁、三个新称号在达标后出现且当前称号取最高优先级、`灵宠目标` 的成就行、`final_milestones` 校验与 native payload 按钮零重叠。未跑全量、仿真、压测、真实 QQ 或部署。

### 渡劫终章秘境闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计发现秘境共 16 处（启灵 2、凝气 4、筑基 2、金丹 2、元婴 2、化神 2、渡劫 2），渡劫作为最高境界只有 `九霄劫海` 与 `太上天门` 两行，山海行纪也在第 14 章「天门问道」结束——把收集、血脉、技能、装备、共鸣、塔与论剑都推到顶的玩家没有新内容可打。

`data/enemies.json` 新增 4 个渡劫境敌人：星陨守望（`starfall_warden`，metal/wind，`metal_edge`）、镜心幻影（`mirror_mirage`，water/ice，`ice_lance`）、沉星帝君（`sunken_sovereign`，fire/earth，`fireball`）、归元守御（`origin_keeper`，wood/thunder，`vine_lash`）。**战斗数值严格照抄同境界既有敌人**（前两者取 `sky_gate_guard` 的 22000/1350/750/900，后两者取 `tribulation_avatar` 的 12500/1300/700/1000），只改 id、名称、主属性与招式，因此平衡门禁的胜率与回合上限结论与既有渡劫秘境一致。

`data/dungeons.json` 新增 4 处渡劫秘境：星陨祭坛（`starfall_altar`，精力 50，首通 1250 灵石 + 5 血脉精华）、镜心湖（`mirror_lake`，52，1300 + 5）、沉星古庭（`sunken_court`，55，1350 + 6）、归元峰（`origin_peak`，58，1400 + 6），均为组队秘境，奖励略高于既有渡劫秘境。

`data/journey.json` 追加 2 章：`journey_15` 星陨问道（`clear_dungeon` 星陨祭坛）与 `journey_16` 归元问鼎（`win_at` 归元峰 count 2），`previous_id` 接在 `journey_14` 之后，境界均为 `dujie`。上限里程碑随内容对齐：`achievements.json` 的 `first_clear_all` 16 → 20、`journey_all` 14 → 16，`titles.json` 的「秘境行家」16 → 20、「山海尽头」14 → 16（说明文案同步）。

关键边界：不新增命令、表、列或规则字段；`catalog` 的 `maxima`/`final_milestones` 自动取到 `len(self.dungeons)`/`len(self.journey)`，因此业务代码零改动；既有 16 处秘境、14 章行纪与 2 个渡劫敌人的数值与奖励字节不变。

定向命令 `./.venv/bin/pytest -q tests/test_endgame_arc.py tests/test_balance_lineups.py tests/test_balance.py tests/test_first_clear.py tests/test_journey.py tests/test_content.py tests/test_pet_catalog.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_achievements.py tests/test_titles.py tests/test_objectives.py tests/test_system_achievements.py tests/test_adventure_routes.py tests/test_daily_assignment.py tests/test_sweep.py tests/test_echoes.py tests/test_achievement_expansion.py tests/test_player_experience.py tests/test_catalog_interaction.py`：合计 `418 passed`（新增 `test_endgame_arc` 9 项）。新增测试覆盖新秘境的境界/组队/精力/首通与敌人引用、新敌人数值与同境界既有敌人一致、首通页总数 20 与领取幂等、秘境列表包含新条目、行纪终章的链条与任务类型、行纪终章在完成条件后可领取、成就与称号上限随内容变化。既有断言同步：`test_balance_lineups` 场景数 64 → 80、快速矩阵 32/128 → 40/160；`test_first_clear` 共 16 处 → 20 处；`test_journey` 页数 1/3 → 1/4 与总数 1/14 → 1/16；`test_system_achievements` 的上限断言（行纪 16、秘境 20）。平衡门禁在新秘境纳入矩阵后 `issues == []`。未跑全量、仿真、压测、真实 QQ 或部署。

### 万灵塔终章闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。内容审计显示万灵塔是当前最薄的主要玩法：秘境 20 处、行纪 16 章、成就 71 项、称号 19 项，而塔只有 8 层，第 8 层「天门绝顶」之后没有后续，把塔打完的玩家在塔里再无目标。

`data/tower.json` 追加 8 层：`tower_09` 星陨回廊（60 精力，星陨守望）、`tower_10` 镜心迷途（65，镜心幻影 + 太虚剑魄）、`tower_11` 沉星古庭（68，沉星帝君 + 万载霜主）、`tower_12` 归元试炼（72，归元守御 + 万木归墟）、`tower_13` 双帝临朝（75，幽冥帝影 + 沉星帝君）、`tower_14` 万法归墟（80，三敌）、`tower_15` 星陨绝壁（85，三敌）、`tower_16` 归元绝顶（90，三敌）。全部 `dujie`，`order` 9-16，`previous_id` 逐层相接（`tower_08` → … → `tower_15`），奖励逐层高于第 8 层（exp 3200-4200 → 4800-6200，灵石 1300-1700 → 2200-2700，血脉精华与破境丹递增）。敌人全部复用既有 `enemies.json` 条目（含渡劫终章秘境新增的四个敌人），不新增敌人定义，也不触碰秘境/关卡与平衡矩阵。

上限里程碑随内容对齐：`achievements.json` 的「塔顶问道」8 → 16（说明「登上万灵塔第十六层。」），`titles.json` 的「万灵塔主」8 → 16（说明「通关万灵塔全部十六层。」）；「三层登临」「六层凌云」「塔门守卫」保持 3/6/3 不变。

关键边界：不新增命令、表、列或规则字段；`catalog` 的 `maxima["tower_depth"] = len(self.tower)` 与 `final_milestones` 自动取到 16，`gameplay/tower.py` 按 `order`/`previous_id` 派生解锁与深度，因此业务代码零改动；既有 8 层的数值、奖励与顺序字节不变。

定向命令 `./.venv/bin/pytest -q tests/test_tower_finale.py tests/test_tower.py tests/test_achievements.py tests/test_titles.py tests/test_objectives.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_system_achievements.py tests/test_balance_lineups.py tests/test_player_experience.py tests/test_catalog_interaction.py tests/test_endgame_arc.py tests/test_achievement_expansion.py tests/test_pet_catalog.py tests/test_weekly_quests.py`：合计 `365 passed`（新增 `test_tower_finale` 5 项）。新增测试覆盖新层的境界/精力/奖励递增/前置链/末层三敌、新层在旧塔顶通关后才可挑战、新层首通奖励只发一次且重复挑战只记练习、深度与上限里程碑随内容变化、页面链接与按钮不重叠。既有断言同步：`test_tower` 的层序 `range(1, 17)`、id 格式 `tower_{index:02d}`（原 `tower_0{index}` 在两位数层号下会错）、页码 `1/4` 与 `4/4`、深度文案 `0/16 层`、`共 4 页`、`1-16 的整数`、第二页按钮集合；`test_titles` 的塔层种子从 8 层改为 16 层。未跑全量、仿真、压测、真实 QQ 或部署。

### 奇闻扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示奇闻（`adventures.json`）是当前最薄的内容层：秘境 20 处、行纪 16 章、塔 16 层、成就 71 项，而奇闻只有 14 条（7 条路线各 2 条），每条路线可遇到的内容很快被看遍，`灵宠回响` 的收集目标（尽览奇闻 14、回响全章 14、称号万籁归心 14）也停在 14。

`data/adventures.json` 追加 7 条奇闻（每条路线 1 条）：灵泉回响、星谷寻脉、洞壁遗刻、火脉遗炉、归墟祭台、太虚残桥、劫云古碑。每条含 `id`/`name`/`text`/`weight`（22）与 2 个互斥 `options`，奖励按所属路线境界落在该路线既有两条之间（灵石 35-100 / 35-105 / 30-115 / 85-160 / 125-215 / 175-290 / 250-390），选项沿用「偏材料 / 偏灵石」的既有模式。`data/exploration_routes.json` 把每条新奇闻加入对应路线的 `encounters`（每条路线 2 → 3 条，共 21 条）。

上限里程碑随内容对齐：`achievements.json` 的「尽览奇闻」与「回响全章」14 → 21，`titles.json` 的「万籁归心」14 → 21（说明文案同步）；`catalog` 的 `maxima`（`adventures_discovered`/`echo_claims` = `len(self.encounters)`）与 `final_milestones` 自动取到 21。

关键边界：不新增命令、表、列或规则字段；探索按路线权重抽取、回响按 `quest_progress` 的 `echo_<奇闻 id>` 标记派生，业务代码零改动；既有 14 条奇闻与 7 条路线的名称/权重/奖励/选项字节不变（仅把新条目追加进路线列表）。

定向命令 `./.venv/bin/pytest -q tests/test_encounter_expansion.py tests/test_echoes.py tests/test_adventure_routes.py tests/test_achievements.py tests/test_system_achievements.py tests/test_titles.py tests/test_objectives.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_balance_lineups.py tests/test_catalog_interaction.py tests/test_tower_finale.py tests/test_endgame_arc.py tests/test_achievement_expansion.py tests/test_pet_catalog.py`：合计 `372 passed`（新增 `test_encounter_expansion` 5 项）。新增测试覆盖 7 条新奇闻在册且选项合法、每条路线恰好 3 条且新奇闻归属正确、新奇闻奖励落在所属路线区间内、发现后可回响并幂等领取、计数与上限里程碑随内容变化。既有断言同步：`test_echoes` 与 `test_adventure_routes` 的 `n/14` → `n/21`、7 条路线的「奇遇概率」字符串（权重归一后每条路线三条）、`test_adventure_routes` 的「最后一条奇闻」参数化（0.99 现在命中新奇闻）与逐条发现循环的取样值、`test_achievements` 的 `adventures_discovered` 上限 14 → 21 与超限用例 15 → 22、`test_system_achievements` 的回响标记数与进度断言。未跑全量、仿真、压测、真实 QQ 或部署。

### 章节关卡扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示章节关卡是最薄的主动内容：秘境 20 处、塔 16 层、奇闻 21 条、行纪 16 章，而关卡只有 8 处，第 8 关「九霄天门」之后没有后续。

`data/stages.json` 追加 8 关：`stage_09` 星陨残关（55 精力，单人，星陨守望）、`stage_10` 镜心重围（60，组队，镜心幻影 + 太虚剑魄）、`stage_11` 沉星旧庭（64，单人，沉星帝君 + 万载霜主）、`stage_12` 归元试锋（68，组队，归元守御 + 万木归墟）、`stage_13` 双帝压境（72，单人，幽冥帝影 + 沉星帝君）、`stage_14` 万法归墟（78，组队，三敌）、`stage_15` 星陨绝壁（84，单人，三敌）、`stage_16` 归元绝顶（90，组队，三敌）。全部 `dujie`，`order` 9-16，`previous_id` 逐关相接（`stage_08` → … → `stage_15`），奖励逐关高于第 8 关（修为 1450-1900 → 2100-2700，灵石 520-720 → 900-1200，材料在雷角/龙鳞之外加入血脉精华与破境丹）。敌人全部复用既有 `enemies.json` 条目，不新增敌人定义。

上限里程碑随内容对齐：`achievements.json` 的「章节征服者」8 → 16（说明「通关全部十六处章节关卡。」）；「初战告捷」1 与「连破五关」5 不变。

关键边界：不新增命令、表、列或规则字段；`catalog` 的 `maxima["stage_clears"] = len(self.stages)` 与 `final_milestones` 自动取到 16，`gameplay/pve_stages.py` 按 `order`/`previous_id` 派生解锁与首通，因此业务代码零改动；既有 8 关的数值、奖励、组队标记与顺序字节不变。

定向命令 `./.venv/bin/pytest -q tests/test_stage_finale.py tests/test_pve_stages.py tests/test_stage_content.py tests/test_stage_interaction.py tests/test_achievements.py tests/test_titles.py tests/test_objectives.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_weekly_quests.py tests/test_player_experience.py tests/test_balance_lineups.py tests/test_system_achievements.py tests/test_encounter_expansion.py tests/test_tower_finale.py tests/test_endgame_arc.py`：合计 `325 passed`（新增 `test_stage_finale` 5 项）。新增测试覆盖新关的境界/精力/奖励递增/前置链/单人与组队交替/末关三敌、新关在旧末关通关后才可挑战、新关首通奖励只发一次、上限里程碑随内容变化、页面链接与按钮不重叠。既有断言同步：`test_stage_interaction` 的种子 id 改为 `stage_{order:02d}`、第二页断言与注释（16 关共 4 页，第二页为第 6-10 关）、`test_achievements` 的 `stage_clears` 上限 8 → 16。未跑全量、仿真、压测、真实 QQ 或部署。

### 离线委托扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示离线委托是最薄的选择面：每个大境界只有一条委托（共 7 条），玩家在任一境界都没有选择，而秘境 20 处、塔 16 层、关卡 16 处、奇闻 21 条都已有纵深。

`data/expeditions.json` 追加 14 条委托（每境界 2 条，共 21 条）：启灵的灵泉浸润（20 精力，回元丹）与采药炼丹（30，蕴灵丹）；凝气的铸翎（28，青岚翎）与铸牙（34，赤焰牙）；筑基的寻鳞（38，龙鳞甲）与掘甲（44，玄岩甲）；金丹的炼铃（48，灵心铃）与雕喙（54，霜喙）；元婴的织茧（58，霜茧衣）与制鳞（64，蚀鳞甲）；化神的接根（68，灵木根）与磨角（74，雷角）；渡劫的锻镰（78，金锋镰）与琢晶（86，水灵晶）。每条 `min_realm` 与所属境界一致，奖励沿用既有形状（单一材料 `minimum 0 / maximum 1`、`exp.minimum < maximum`、`stones.minimum < maximum`），材料互不重复且都在册。

关键边界：不新增命令、表、列或规则字段；`expedition_claims` 是累计领取次数指标、不在 `catalog.maxima` 内，因此本次扩充不触发上限里程碑级联；派遣/归来/领取与幂等全部复用既有实现，业务代码零改动；既有 7 条委托与委托时长规则字节不变。

定向命令 `./.venv/bin/pytest -q tests/test_expedition_expansion.py tests/test_expedition_interaction.py tests/test_expedition_commands.py tests/test_expedition_content.py tests/test_expedition_contract.py tests/test_expedition_occupancy.py tests/test_expedition_storage.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_objectives.py tests/test_weekly_quests.py tests/test_main_quest.py tests/test_player_experience.py tests/test_balance_lineups.py`：合计 `521 passed`（新增 `test_expedition_expansion` 4 项）。新增测试覆盖每境界恰好三条、新条目精力与奖励区间合法且材料互不重复、境界门槛生效、派遣占用与归来领取幂等、目录分页覆盖全部境界。既有断言同步：`test_expedition_content` 的「委托集合恰好等于 7 条」改为「既有 7 条仍在册」（子集断言），`test_expedition_interaction` 的第二页链接集合（分页后第二页为第 6-10 条）并补末页断言。未跑全量、仿真、压测、真实 QQ 或部署。

### 今日课题扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示今日课题的池子太浅：6 项里每天抽 3 项，同一组三项每两天就重复，且每个指标只有 1 次这一种难度，没有“今天多做一点换更高奖励”的取舍。

`data/daily_assignments.json` 追加 6 项课题：秘境三胜（`daily_pve` 3）、论剑三试（`daily_pvp` 3）、奇闻双探（`daily_discovery` 2）、委托双程（`daily_expedition` 2）、成就双收（`daily_claim` 2）、秘境五胜（`daily_pve` 5），奖励高于对应轻量版（灵石 260-420，材料 2-4）。池子由 6 项变为 12 项。

**审计发现**：`daily_training` 指标是布尔量——`_value` 只比较 `players.last_train` 的日期，取值恒为 0 或 1，无法计数，因此不能给它加“修炼 3 次”这类高强度变体（加了也永远无法达成）。改为再给 `daily_pve` 加一个 5 胜变体，池子仍为 12 项；这也说明该指标目前只能表达“今天是否修炼过”。

关键边界：不新增命令、表、列或规则字段；轮换按 `pool[(序数 * 3 + i) % len(pool)]` 自动覆盖全池（3 与 12 互质，四天一轮）；`daily_assignment` 的领取标记是 `quest_progress` 的单行、不在 `catalog.maxima` 内，因此无上限里程碑级联；业务代码零改动。

定向命令 `./.venv/bin/pytest -q tests/test_assignment_expansion.py tests/test_daily_assignment.py tests/test_objectives.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_balance_lineups.py tests/test_catalog_interaction.py`：合计 `224 passed`（新增 `test_assignment_expansion` 4 项）。新增测试覆盖池子 12 项且每个指标目标互不相同、高强度变体奖励高于轻量版、四天轮换覆盖全池、高强度课题按目标判定与领取幂等。既有断言同步：`test_daily_assignment` 的「缺失指标」用例原本只删数组第一条，池中有两个 `daily_pve` 后不再触发校验，改为删除该指标的全部条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 周常任务扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示周常和今日课题一样只有单一难度：六个指标（`weekly_pve_wins`、`weekly_pvp_wins`、`weekly_expedition_claims`、`weekly_adventures`、`weekly_stage_clears`、`weekly_achievement_claims`）各只有一个目标值，玩家每周把六项做完就无事可做，没有“本周要不要冲更高目标”的取舍。

`data/weekly_quests.json` 追加 6 项进阶周常：秘境苦战（12 胜）、论剑争锋（8 胜）、山海五往（6 次委托）、奇闻广记（10 条）、关卡连破（5 关）、成就五收（5 项），奖励约为轻量版两倍（灵石 1100-1400，材料 2-5）。池子由 6 项变为 12 项，`灵宠周常` 页面由 2 页变为 3 页（每页 5 条）。

关键边界：不新增命令、表、列或规则字段；`weekly_claims`（累计领取次数）不在 `catalog.maxima` 内，因此无上限里程碑级联，称号「周常不辍」（6 次）保持有效；进度仍按当前自然周从永久记录派生，领取标记仍是 `quest_progress` 的对应行（`progress` 存本周起始），业务代码零改动；既有 6 项周常字节不变。

定向命令 `./.venv/bin/pytest -q tests/test_weekly_expansion.py tests/test_weekly_quests.py tests/test_objectives.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_main_quest.py tests/test_player_experience.py tests/test_balance_lineups.py`：合计 `225 passed`（新增 `test_weekly_expansion` 4 项）。新增测试覆盖 12 项且每指标两个目标、进阶奖励高于轻量版、进阶周常按目标判定与领取幂等、跨周标记失效后可再次领取、`灵宠目标` 行随内容变化。既有断言同步：`test_weekly_quests` 的条目数 6 → 12 与页码 `1/2` → `1/3`、`2/2` → `2/3`。未跑全量、仿真、压测、真实 QQ 或部署。

### 赛季任务扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示赛季任务是三个“目标清单”系统里唯一还没加深的：今日课题（6 → 12）与周常（6 → 12）本轮已各加一档难度，而赛季任务仍是每个指标单一目标，玩家一个月里把五项做完就没有更高追求。

`data/season_missions.json` 追加 5 项进阶赛季任务：论剑百战（`season_matches` 30）、论剑称雄（`season_wins` 15）、山海远征（`season_pve` 15）、奇闻遍访（`season_discoveries` 8）、成就盈册（`season_claims` 8），奖励约为轻量版两倍（灵石 650-900，材料 3-4）。池子由 5 项变为 10 项，`灵宠赛季任务` 页面由 1 页变为 2 页（每页 5 条）。

关键边界：不新增命令、表、列或规则字段；`season_claims`（本赛季领取次数）不在 `catalog.maxima` 内，因此无上限里程碑级联；进度仍按当前赛季窗口（`utils.time.season_bounds` 的自然月起止）从带时间戳记录派生，领取标记仍是 `quest_progress` 的 `season_<任务 id>`（`progress` 存赛季起始），业务代码零改动；既有 5 项赛季任务字节不变。

定向命令 `./.venv/bin/pytest -q tests/test_season_expansion.py tests/test_season_missions.py tests/test_objectives.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_player_experience.py tests/test_balance_lineups.py tests/test_weekly_expansion.py tests/test_assignment_expansion.py`：合计 `226 passed`（新增 `test_season_expansion` 4 项）。新增测试覆盖 10 项且每指标两个目标、进阶奖励高于轻量版、进阶任务按目标判定与领取幂等、跨赛季标记失效后可再次领取、`灵宠目标` 行随内容变化。既有断言同步：`test_season_missions` 的页码 `1/1` → `1/2`、导航按钮（多出 `灵宠赛季任务 2`）、已领取计数 `1/5` → `1/10`，以及「缺失指标」用例改为删除该指标的全部条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠共鸣扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示共鸣覆盖面很窄：27 族只定义了 14 组配对，且多为同系相邻组合（青鸾+寒翎鹰、玄狐+雪狐、白泽+道棠…），跨系组合几乎空缺，玩家手里的跨系双灵大多没有对应共鸣可集，收集与队伍搭配的选择面被压得很小。

`data/resonances.json` 追加 7 组跨系配对：风火同翔（青鸾+毕方）、狐灵相映（玄狐+冥蝶）、金羽共鸣（白泽+金羽）、龙雷交鸣（蛟龙+雷泽）、山岳之盟（玄武+山石）、雪鹿同游（三灵鹿+雪狐）、霜翼共鸣（冰蚕+寒翎鹰），倍率沿用既有量级（合计 0.06-0.08）。目录由 14 组变为 21 组，`灵宠共鸣` 页面由 3 页变为 5 页（每页 5 条），仍覆盖全部 27 族。

关键边界：不新增命令、表、列或规则字段；共鸣不在平衡门禁取样内（`lineup_report.py` 明确写明准备档「no selected lineage or resonance」），`resonances_enabled` 也不在 `catalog.maxima` 内，因此既不影响门禁也无上限里程碑级联；启用/停用/切换与幂等全部复用既有实现（重复启用当前共鸣返回「共鸣已启用」且不重复扣费），业务代码零改动；既有 14 组共鸣字节不变。

定向命令 `./.venv/bin/pytest -q tests/test_resonance_expansion.py tests/test_resonance.py tests/test_resonance_contract.py tests/test_content.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_objectives.py tests/test_player_experience.py tests/test_balance_lineups.py tests/test_catalog_interaction.py`：合计 `225 passed`（新增 `test_resonance_expansion` 4 项）。新增测试覆盖 21 组且配对唯一、每个种族仍被覆盖、新组不与旧组重复、新组可激活并按 `rules.resonance_cost` 扣费、重复启用幂等不重复扣费、种族未集齐时被拒。既有断言同步：`test_resonance` 的条目数 14 → 21、页码 `1/3` → `1/5` 与页码参数（第 6 页越界），以及「种族未覆盖」用例改为删除某一种族的全部配对（原用例只删一组，在该种族被其他组覆盖后不再触发校验）。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠论剑段位达成奖励闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、命令与 UX、测试与文档。审计显示段位已由三档扩到六档，但爬档过程本身没有任何回报：无论爬到哪一档，收益都要等赛季结束才结算一次（`season_claims` 每季一次），赛季中期的爬分只是「为最终结算做准备」；赛季任务覆盖的是活动量而非段位。

新增 `data/arena_tier_rewards.json`（六条，与 `arena.json` 档位一一对应：青云 80 灵石、凌霄 160 + 2 锻灵矿、天阙 260 + 4 锻灵矿、星海 380 + 6 锻灵矿 + 2 血脉精华、太虚 520 + 8 锻灵矿 + 3 血脉精华、归元 700 + 10 锻灵矿 + 4 血脉精华）与 `domain/arena_tier_content.py`，`Catalog` 增加 `arena_tier_rewards` 字段，校验覆盖全部档位、物品存在、奖励非空。新增 `gameplay/arena/tier_rewards.py`：档位由 `season_entries.rating` 即时派生（`tier_of` 取不超过当前积分的最高档），领取标记写入 `quest_progress` 的 `arena_tier_<赛季号>_<档位 id>` 行，因此每档每季只发一次、换季自动重新可领；发奖复用 `rewards.grant`。只读页与 `灵宠目标` 用不建赛季行的 `season_rating`（直接读 `season_entries`，缺省取 `initial_rating`），避免只读页面写 `seasons` 表。命令 `灵宠段位奖励`（只读）与 `灵宠段位领奖 <段位名>`；帮助「对战与赛季」新增两条；`灵宠目标` 新增段位行。

关键边界：不新增表、列或计数列，schema 20 不动；论剑匹配、积分转移、场次限额、领奖资格、赛季结束结算与赛季任务均不变；奖励领取式，不进入任何战斗结算，因此平衡门禁结论不变。

定向命令 `./.venv/bin/pytest -q tests/test_arena_tier_rewards.py tests/test_seasons.py tests/test_arena_content.py tests/test_arena_ladder.py tests/test_arena_interaction.py tests/test_objectives.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_content.py tests/test_balance_lineups.py tests/test_runtime.py tests/test_achievements.py tests/test_player_experience.py tests/test_codex.py tests/test_stage_stars.py tests/test_arena_matching.py`：合计 `494 passed`（新增 `test_arena_tier_rewards` 9 项）。新增测试覆盖六档覆盖且奖励递增、状态与门槛映射（含 `还差 n 分`）、积分不足被拒、领取扣减与二次领取被拒、爬到更高档解锁更多可领项、换季重新可领、同 `operation_id` 重放只发一次、未结契只读浏览不建号、`灵宠目标` 行格式与帮助条目。测试用 `season_bounds` 推导赛季号（默认测试时钟落在 2027-01），并在写入 `season_entries` 前先让命令建立赛季行以满足外键。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠关卡星级评价闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、命令与 UX、测试与文档。审计显示章节关卡只有「未解锁 / 可挑战 / 已通关」三种状态，通关后这一关就彻底结束（`pve_stage_progress` 只记首次通关时间），没有表现评价维度，16 关的深度止步于「是否通关」。战斗记录里已经保存了每场战斗的回合数（`battle_records.rounds`），因此评价可以完全派生。

`rules.json` 新增 `stage_star_rounds`（`{"three": 3, "two": 5}`，每名敌手允许的回合数），`Rules` 模型新增 `StageStarRule` 并校验 3 星门槛严于 2 星门槛。新增 `data/stage_star_rewards.json` 三档里程碑（16 星：500 灵石 + 5 锻灵矿；32 星：1200 灵石 + 10 锻灵矿 + 3 血脉精华；48 星：2400 灵石 + 16 锻灵矿 + 6 血脉精华）与 `domain/stage_star_content.py`，`Catalog` 增加 `stage_star_rewards` 字段，校验星数不重复、不超过 `3 × 关卡数`、物品存在、奖励非空。新增 `gameplay/stage_stars.py`：`best_rounds` 取该玩家在该关**获胜**记录中的最少回合数，`stars_for` 按 `rounds <= 每敌手门槛 × 敌手数` 换算 3/2/1 星，`total` 汇总 16 关星数；领取标记写入 `quest_progress` 的 `stage_stars_<星数>` 行，发奖复用 `rewards.grant`。命令 `灵宠关卡星级`（只读分页，5 关/页，共 4 页）与 `灵宠关卡星级领奖 <星数>`；`灵宠关卡 <序号>` 详情新增星级行；帮助「秘境与关卡」新增两条；`灵宠目标` 新增星级行。

门槛以实测锚定：启灵期青鸾在 `FixedRandom` 最差骰下以 5 回合通关第 1 关（1 名敌手），即最差骰为 2 星、正常骰可拿 3 星。

关键边界：不新增表、列或计数列，schema 20 不动；关卡解锁、前置、精力、首通奖励、助战规则与全部战斗结算不变；星级纯派生、奖励领取式，不进入任何战斗结算，因此平衡门禁结论不变。

定向命令 `./.venv/bin/pytest -q tests/test_stage_stars.py tests/test_stage_interaction.py tests/test_stage_finale.py tests/test_objectives.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_content.py tests/test_balance_lineups.py tests/test_runtime.py tests/test_achievements.py tests/test_player_experience.py tests/test_catalog_interaction.py tests/test_pet_catalog.py tests/test_codex.py tests/test_sweep.py tests/test_pve_stages.py`：合计 `353 passed`（新增 `test_stage_stars` 11 项）。新增测试覆盖每敌手门槛边界（门槛与门槛 +1）、多敌手换算、取历史最少回合、败退与平局不计入、真实通关得星（★★☆）、详情星级行、里程碑领取扣减与二次领取被拒、同 `operation_id` 重放只发一次、未结契只读浏览不建号、`灵宠目标` 行格式与帮助条目。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠图鉴收集奖励闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、命令与 UX、测试与文档。审计显示收集是核心循环之一（领养、召唤、孵化、培育），`灵宠收集` 与 `灵宠图鉴` 都能看到收集状态，但收集本身没有任何直接回报：只有三条成就按总数给奖（初识百灵 3 族、百灵相逢 10 族、万灵归藏 27 族），中间 24 个种族收齐了也没有反馈。

新增 `data/codex_rewards.json`（27 条，每族一条）与 `domain/codex_content.py` 的 `CodexReward`，`Catalog` 增加 `codex_rewards` 字段；奖励按召唤池权重分四档：常见（权重 ≥20）60 灵石 + 灵粮 1、少见（12-19）100 灵石 + 灵粮 2、稀有（8-11）150 灵石 + 血脉精华 1、珍稀（≤7）240 灵石 + 血脉精华 1 + 灵粮 2，全部领取合计 4020 灵石。新增 `gameplay/codex.py`：收集状态由 `pets` 表即时派生（封存宠物仍计入，与 `灵宠收集` 口径一致），每族奖励只发一次，领取标记写入 `quest_progress` 的 `codex_<种族>` 行，发奖复用 `rewards.grant`。命令 `灵宠图鉴奖励`（只读分页，5 族/页，共 6 页）与 `灵宠图鉴领奖 <种族名>`，别名比既有 `灵宠图鉴` 长，按最长前缀优先解析不会误路由；帮助「身份与收集」新增两条；`灵宠目标` 新增图鉴奖励行与入口蓝字。

关键边界：不新增表、列、计数列或规则字段，schema 20 不动；既有成就、称号、收集页、图鉴页、召唤池与全部战斗/结算路径不变；奖励为固定值，领取时构造成单值区间交给既有 `grant`，不进入任何战斗结算。校验要求每个种族恰好一条奖励、物品存在、奖励非空。

定向命令 `./.venv/bin/pytest -q tests/test_codex.py tests/test_objectives.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_achievements.py tests/test_player_experience.py tests/test_content.py tests/test_balance_lineups.py tests/test_runtime.py tests/test_catalog_interaction.py tests/test_pet_catalog.py tests/test_achievement_interaction.py`：合计 `320 passed`（新增 `test_codex` 11 项）。新增测试覆盖 27 族覆盖与唯一、四档奖励取值、六页分页与三种状态、未收集被拒、未知名称被拒、领取扣减与二次领取被拒、封存宠物仍计入、同 `operation_id` 重放返回同一回复且只发一次、未结契只读浏览不建号、`灵宠目标` 行格式与帮助条目。既有断言同步：`test_pet_catalog` 的「无获取途径」用例在追加种族时同时补一条收集奖励，使原校验仍先触发。未跑全量、仿真、压测、真实 QQ 或部署。

### 灵宠论剑段位扩充闭环（2026-10-16，已完成）

四个阶段一次交付：内容与校验、业务、测试、文档。审计显示论剑是唯一只有三档的赛季玩法：青云 0 分、凌霄 1050 分、天阙 1150 分。在 `rating_delta=20`、`daily_matches=5` 下一天全胜即可拿到 100 分，从 1000 分爬到顶档只需约两天，此后整个自然月再无段位可爬，赛季后半程只剩重复刷场次；段位阶梯是这套玩法唯一的目标感来源，三档明显过短。

`data/arena.json` 在既有三档之后追加三档：星海 1250 分（1400 灵石、13 锻灵矿、5 血脉精华）、太虚 1350 分（1900 灵石、16 锻灵矿、6 血脉精华）、归元 1450 分（2500 灵石、20 锻灵矿、8 血脉精华）。灵石与材料按既有节奏递增，`灵宠赛季奖励 规则` 由 1 页变为 2 页（`CATALOG_PAGE_SIZE=4`），既有三档字节不变。

关键边界：不新增命令、表、列或规则字段；档位查找（取不超过当前积分的最高档）、规则分页与赛季结算（按最终积分取最高档、不累加各档）全部内容驱动，业务代码零改动；论剑不在平衡门禁取样范围内（门禁只跑 PVE 秘境与阵容），赛季时长、准入、场次限额、积分转移与领奖资格均不变。

定向命令 `./.venv/bin/pytest -q tests/test_arena_ladder.py tests/test_arena_content.py tests/test_seasons.py tests/test_commands.py tests/test_messaging.py tests/test_information.py tests/test_objectives.py tests/test_player_experience.py tests/test_balance_lineups.py tests/test_runtime.py`：合计 `309 passed`（新增 `test_arena_ladder` 21 项）。新增测试覆盖六档 id/名称唯一且最低积分严格递增、首档为 0、灵石与材料随档位递增、12 个积分边界（每档阈值与阈值减一）映射到正确档位、规则分页为 2 页且第二页只含后两档、越界页被拒、爬到星海（1260 分）与归元（1460 分）后按新档位领奖、以及并发重放只领一次。既有断言同步：`test_arena_content` 的档位断言由三档改为六档。未跑全量、仿真、压测、真实 QQ 或部署。

### 连续签到里程碑奖励闭环（2026-10-16，已完成）

连续签到使用北京时间日期凭证复原当前/历史最佳 streak，3/7/14/30 天里程碑可累计领取；旧存档只利用最近一次签到日期衔接，不虚构更早历史。日期凭证与奖励标记复用 `quest_progress`，每日任务刷新只删内容定义的每日任务 ID，不清理签到历史或其他永久目标。

修复 CI 暴露的旧合同断言：跨日后每日任务 `sign_once` 应清除，但 `signin_day_YYYY-MM-DD` 历史应保留；增加旧每日任务链接跨日后不生成新链接、执行旧领奖命令会被拒绝的回归。新增 `gameplay/checkin_rewards.py`、命令/帮助/目标页入口与 `docs/GAMEPLAY.md` 玩家规则，未改 schema 或玩家模型。

聚焦回归 `.venv/bin/python -m pytest -q tests/test_quest_interaction.py -k 'day_refresh or stale_daily'`：`2 passed`。develop CI `38855715805` 与 main CI `38855982696` 均全绿（Python 3.10/3.13 全量 pytest、compile、shell 入口与安装冒烟）；提交 `d2c1e55`、`62e9635` 已推送 develop 并 fast-forward 合入 main。无部署、无真实 QQ 或设备验收。

### 装备套装一键配装闭环（2026-10-16，已完成）

套装详情逐件显示槽位、当前宠物适配、背包强化等级和商店/打造入口。备齐部件且当前出战宠物适配、无未结行程时提供 `灵宠套装穿戴 <宠物编号> <套装名>`；命令绑定详情所示宠物并在执行时重验当前出战身份、行程、兼容性和库存。一次性预检全部部件后才交换现有 `equipment` 与背包记录，保留部件强化、返还被替换装备；已穿部件不重复消耗。未完成、缺件、不兼容、宠物忙碌或过期目标均拒绝且不部分换装。完成后仍走既有套装奖励凭证和领取流程。

不新增 schema、表、列或玩家模型；套装定义、属性加成、奖励金额、战斗和既有领奖逻辑不变。新增聚焦合同 `tests/test_equipment_set_loadout.py` 6 项，覆盖部件来源/入口、宠物切换后的过期链接、强化保留与替换返还、领奖衔接、兼容/行程/缺件拒绝、事务失败回滚和操作重放。装备套装受影响合同中先前通过的用例未重复运行；修正断言和装配回归随后单独通过。`tests/test_messaging.py` `28 passed`；`compileall` 和 `git diff --check` 通过。实现提交 `07ef3b2` 的 develop CI `38888597059`、main CI `38889082306` 全绿（Python 3.10/3.13 全量测试、编译、shell 入口和安装冒烟）；已普通推送 develop 并 fast-forward 合入 main。未部署、未发送真实 QQ；辅助目标卡 `docs/goals/pet-equipment-set-auto-equip.md` 仅本地保留、不提交。

### 赛季最终奖励回顾闭环（2026-10-17，已完成）

审计发现 `season_claims.reward_snapshot` 已在赛季领奖事务中保存最终档位、积分、灵石和道具，但 `灵宠赛季奖励` 只有“已领取”状态，没有按赛季回顾实际发放数量的玩家入口。新增只读 `灵宠赛季奖励回顾 [页码/赛季号]`：按本人已领取赛季倒序分页，行内蓝字打开详情；详情严格读取持久快照，显示最终积分、结算档位、北京时间领取时间和实际奖励。静态 arena 规则改变不会重算历史，缺失物品定义按 ID 回退；未知/他人/未领取记录、进行中赛季和损坏快照有稳定边界错误，列表坏记录不会遮蔽其他历史。

实现复用 `season_claims`、`season_entries` 和 `seasons`，无 schema、玩家模型、竞技场结算、段位达成奖励或赛季任务改动；未结契只读列表不创建玩家，回顾不发奖、不写进度。帮助、`docs/GAMEPLAY.md`、命令映射与 QQ native/OneBot 可读入口已同步。新增 `tests/test_arena_reward_history.py` `7 passed`，覆盖空状态、分页排序、快照稳定性、权限/未领取/进行中边界、损坏快照、幂等重投和 native 蓝字/按钮去重；受影响命令/消息合同 `37 passed`，竞技场既有合同 `179 passed`。`compileall` 与 `git diff --check` 通过。实现提交 `cb79816` 的 develop CI `38941789775`、main CI `38942130507` 全绿（Python 3.10/3.13 全量测试、编译、shell 入口和安装冒烟）；已普通推送 develop 并 fast-forward 合入 main。未部署、未发送真实 QQ；本地辅助目标卡 `docs/goals/pet-arena-reward-history.md` 不提交。

### 称号佩戴与切换闭环（2026-10-17，已完成）

审计发现 21 项称号只能按 `order` 自动选择最高已获得项，玩家没有主动展示已获得低阶称号的入口。新增 `灵宠称号佩戴 <称号名>`：称号页已获得行挂唯一蓝字，服务端按当前指标重验资格后把选择写入 `quest_progress.title_equipped`；未主动选择沿用最高称号，未知 order、已不可达称号或坏标记安全回退。`我的灵宠` 状态和新战报快照固定保存/显示当前称号，历史快照无该字段时仍可读。

选择只是展示偏好，不发奖、不推进目标、不改变战斗或经济；未结契页面只读不建号，未知/未获得/多参数与坏记录稳定拒绝，重复选择与同操作号重放幂等。命令、帮助、`docs/GAMEPLAY.md` 和 QQ native/OneBot 蓝字/按钮去重已同步，无 schema、玩家模型、奖励或改名/道号功能改动。新增 `tests/test_title_loadout.py` `6 passed`，覆盖持久切换、状态、战报快照、坏选择回退、错误边界、幂等、帮助解析和 native payload；受影响称号/状态/命令/战报短合同 `39 passed`，`compileall` 与 `git diff --check` 通过。实现提交 `aa46d76` 的 develop CI `38945555706`、main CI `38945890585` 全绿（Python 3.10/3.13 全量测试、编译、shell 入口和安装冒烟）；已普通推送 develop 并 fast-forward 合入 main。未部署、未发送真实 QQ；本地辅助目标卡 `docs/goals/pet-title-loadout.md` 不提交。

### 战斗功勋奖励闭环（2026-10-17，已完成）

审计永久 `battle_records` 后补上长期战斗奖励缺口。新增只读 `灵宠战斗功勋` 与 `灵宠战斗功勋领奖 <胜场>`：按本人参与者行与 `winner_side=side` 派生秘境、章节关卡、论剑胜场，组队每位成员各计一场，切磋、败北、平局不计。5/20/50 胜分别奖励 180 灵石+锻灵矿、600 灵石+血脉精华、1500 灵石+锻灵矿/血脉精华；凭证 `battle_merit_<胜场>` 写入 `quest_progress`，领取时保存胜场快照并与资源同事务提交。

未结契可只读预览，参数/未知档位/未达成/重复/奖励物品定义异常均稳定拒绝且不改资源；原操作重投保持幂等。命令、帮助、`灵宠目标`、`docs/GAMEPLAY.md` 与 QQ native/OneBot 蓝字/按钮去重已同步；不改 schema、玩家模型、战斗、掉落、成就、任务或称号规则。新增 `tests/test_battle_merit_rewards.py` `11 passed`，受影响命令/消息/目标/战报合同 `66 passed`，`compileall` 与 `git diff --check` 通过。实现提交 `b2124a6`、`11291ac` 的 develop CI `38948901912` 与 main CI `38949281474` 全绿（Python 3.10/3.13、安装冒烟、编译、shell 入口）；已普通推送 develop 并 fast-forward 合入 main。未部署、未发送真实 QQ；本地辅助目标卡 `docs/goals/pet-battle-merit-rewards.md` 不提交。

### 万灵榜名次奖励闭环（2026-10-17，已完成）

路线图完成卡片审计后，现有 `docs/goals/*.md` 继续作为已完成目标的本地证据卡，不重复装备套装一键配装。复用现有每人最高在册宠物的稳定排序，新增前 3/10/20 名一次性奖励、`灵宠排行奖励` 与 `灵宠排行领奖 <名次>`、当前名次与领取名次快照；已领取资格不因排名下降、封存、重启或静态内容变化撤回。损坏境界/层数、未入榜、未结契、奖励定义异常、重复/跨用户/格式错误均稳定拒绝且不改资源；奖励凭证 `rank_milestone_<名次>` 与发奖同事务写入 `quest_progress`，不新增 schema、玩家模型、战斗或装备规则。

新增 `tests/test_rank_milestone_rewards.py` `6 passed`，覆盖排序、每人单宠、封存/损坏过滤、三档领取与名次快照、失败回滚、帮助/目标/native 蓝字去重；受影响信息/命令/消息/目标/战斗功勋合同合计 `116 passed`，`compileall` 与 `git diff --check` 通过。实现提交 `17967bd` 的 develop CI `38952125097` 与 main CI `38952450013` 全绿（Python 3.10/3.13 全量 pytest、编译、shell 入口和安装冒烟）；已普通推送 develop 并 fast-forward 合入 main。未部署、未发送真实 QQ；本地辅助目标卡 `docs/goals/pet-rank-milestone-rewards.md` 不提交。

### 奇闻收集里程碑奖励闭环（2026-10-17，已完成）

从永久 `adventure_discoveries` 派生独立发现的不同奇闻数（退役记录行不计入），新增 3/7/14/21 条四档一次性收集奖励、`灵宠奇闻奖励` 与 `灵宠奇闻领奖 <数量>`、`灵宠奇闻榜` 底部个人里程碑状态、`灵宠目标` 汇总行和帮助入口；首次发现新奇闻的历练回复挂“查看收集奖励”蓝字直达奖励页。奖励 3 档 120 灵石+灵粮、7 档 300 灵石+锻灵矿、14 档 700 灵石+同心丹、21 档 1800 灵石+血脉精华。凭证 `adventure_collection_<数量>` 与发奖同事务写入 `quest_progress`，重复发现不重复发奖，跨日/重启/内容调整不影响已领取状态；未结契只读，参数错误、未知/未达成档位、重复领取、奖励物品定义异常均稳定拒绝且不改资源。不新增 schema、玩家模型、奇闻路线、回响选择或战斗规则。

新增 `tests/test_adventure_collection_rewards.py` `10 passed`，覆盖未结契只读与命令解析、重复发现去重与奇闻榜里程碑、四档领取与幂等重放、无效/未达标参数拒绝、奖励定义缺失回滚、目标/帮助/native 蓝字按钮去重；受影响历练/信息/命令/消息/目标/运行时合同合计 `367 passed`，`compileall` 与 `git diff --check` 通过。实现提交 `9c068c2` 的 develop CI `39018947013` 与 main CI `39019114400` 全绿（Python 3.10/3.13 全量 pytest、编译、shell 入口和安装冒烟）；已普通推送 develop 并 fast-forward 合入 main。未部署、未发送真实 QQ；本地辅助目标卡 `docs/goals/pet-adventure-collection-rewards.md` 不提交。

### 图鉴百科与收集二阶（2026-10-25，已完成）

图鉴详情百科化与检索已由提交 `97e2e1e` 交付（图鉴详情页获取途径含灵卵孵化来源、`灵宠图鉴 克制 <元素>` 与 `灵宠图鉴 掉落 <物品>` 检索、`灵宠图鉴克制`/`灵宠图鉴掉落` 独立别名与 `克制`/`掉落` 关键字分支，结果从战斗引擎与秘境/关卡/万灵塔/委托奖励表派生，全部只读、未结契可浏览）。本切片补齐该目标的收集二阶部分：新增三条只读派生成就——`lineage_branches` 达 54“万脉同归”、`skills_learned` 达 24“万法通鉴”、新指标 `dungeon_clears` 达 20“秘境踏遍”；`dungeon_clears` 按永久战报 `kind='pve'` 且参与者 `side == winner_side` 去重 `battle_key` 计数，战败、平局与已下线秘境均不计入，不新增 schema 或计数列。新增派生称号“万脉宗师”（54 支血脉分支全觉醒）。成就升至 77 项、称号升至 22 项，`_validate_achievements` 的 required/maxima 与既有计数合同、成就分页断言（16 页）、称号总数展示断言同步更新；`docs/GAMEPLAY.md` 图鉴/成就/称号段落已更新。不新增离线战斗或 schema 改动，未部署、未发送真实 QQ。

本切片同时在图鉴详情页派生三行百科内容：克制速览（从战斗引擎 effectiveness 双向遍历）、该族两条血脉分支预览、灵卵掉落秘境行，并把掉落行挂“查看掉落秘境”直达蓝字（`tests/test_catalog_interaction.py` 两条 native 蓝字合同按新形状同步）。聚焦 `tests/test_codex2.py` `22 passed`（原 17 项检索/百科合同 + 新增 5 项：详情百科派生、内容定义、指标派生、战报通关判定边界、三条成就解锁/领取/幂等）；受影响成就/称号/图鉴交互/目标/内容/运行时合同 `258 passed`；`compileall` 与 `git diff --check` 通过。全量 `pytest -q tests/` 在 180 秒工具限时内退出 124（约 34% 处中断），未作为成功证据，不重跑。已提交 `be0b0b4` 并普通推送 develop，develop CI `40120894595` 全绿；随后 `git merge --ff-only develop` 快进合入 main 并推送，main CI `40121356939` 全绿（均对应同一提交 `be0b0b4`）。提交范围为白名单 18 个文件，未包含 `docs/goals/` 本地卡片、`gameplay/farming.py` 与 `tests/test_farm2.py` 的既有脏改动。未部署、未发送真实 QQ。

### 渡劫终局飞升与轮回（2026-10-27，已完成）

大目标 10/10，解除此前对“飞升/二周目”的排除。新增 `data/ascension.json` 三段试炼（雷劫、心魔、天道）与 `enemies.json` 三个专属敌手（雷劫天罚 16000/1500/800/900、心魔执念 19000/1700/900/950、天道无情 23000/1900/1000/1000）；敌手数值按渡劫十层、仙血脉、满亲密伙伴的既有战斗公式实测标定，仙血伙伴可连续通过，血脉不足会停在雷劫或心魔。`灵宠飞升` 分页展示周目、已飞升数量与逐宠状态，`灵宠飞升 <宠物编号>` 在同一事务内依次开战，每段以全新 Fighter 满血开始，任意一段败北/平局即停止；试炼不消耗灵石、灵粮、精力或冷却，失败不写标记且可立即重试，只有三段全胜才写入 `quest_progress` 的 `ascended_<宠物编号>`。

飞升标记由 `Repository.pet()` 从 `quest_progress` 派生（不新增列，schema 20 不动），`pet_stats` 对飞升宠全属性乘 1.10，因此秘境、关卡、万灵塔、论剑、组队与战报快照使用同一份数值；`capture_snapshot` 成员快照新增 `ascended` 字段，战报详情显示“飞升”。`skills` 的携带上限改为按宠物派生：普通宠沿用 `rules.max_skill_slots`（2），飞升宠为 5（专属第五栏位），学习与携带都走同一 helper。每次全队飞升记 1 周目（`rebirth_count`），名册仍有未飞升伙伴时不记；已飞升伙伴每周可重走一次试炼（`ascension_week_<编号>`），全胜且全队仍飞升时同样记周目，重走不发任何货币或道具。首只飞升解锁称号“破界者”，三个周目解锁“轮回行者”；`灵宠目标` 增加飞升行与入口，帮助、`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。称号由 23 项增至 25 项，敌手由 20 个增至 23 个，计数合同与 `DOCUMENTED_COUNTS` 同批更新。

新增 `tests/test_ascension.py` 23 项：三段流程与每段满血重开、全胜/部分胜/失败三态、飞升标记与 +10% 属性、第五技能栏位、战报快照与持久战报、全队周目与三次轮回称号、成功/失败重投幂等、跨重启与封存复原持久、未达境界/非本人/派遣中/已封存/同周重复拒绝、未结契只读、目录状态与蓝字、QQ native 按钮与蓝字分离、帮助与目标入口、内容校验。聚焦命令：`PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' ./.venv/bin/pytest -q tests/test_ascension.py`（23 passed）；受影响目标/称号/成就/内容/命令/战报/技能/运行时/契约审计合同 392 passed；`compileall` 与 `git diff --check` 通过。提交 `b229632` 与 `0be8a45` 已推送 develop，develop CI `40522849411` 全绿，fast-forward 合入 main 后 main CI `40523759757` 全绿；首次 develop CI `40521913772` 因目标页末尾链接断言未更新而失败，已在 `0be8a45` 修复。未部署、未发送真实 QQ、未跑本地全量；`docs/goals/pet-goal-ascension.md` 与索引仅本地保留、不提交。

### 灵坊每日特供（2026-10-27，已完成）

十张大目标与四条聚合线交付后，审计每日入口发现经济端仍是静态全量商店：所有有价道具永久同价、无限购，玩家没有每日回访灵坊的理由。本切片新增 `data/shop_rotation.json` 九条特供（物品、折扣 10%-25%、单日库存 1-3 件），`domain/shop_content.py` 的 `ShopOffer` 接入 `Catalog.shop_offers`；启动校验至少三条、物品存在且有售价、同一物品只出现一次。轮换按北京时间日期序数从 id 排序池连续取三件，同一天稳定、次日整体前移，页面附明日预告。

`灵宠特供` 页面逐行给出原价、特供价、今日总件数、剩余与本人已购，可购买行挂 `灵宠特供 <物品>` 蓝字；`灵宠特供 <物品> [数量]` 按折扣价扣灵石、加道具并把已购件数累加到 `quest_progress` 的 `shop_offer_<北京日期>_<特供id>`，库存 = 定义库存 - 当日已购，跨日换 key 自动重置。普通 `灵宠购买` 的价格、数量与无限购语义不变；`灵宠商店` 增加 `灵宠特供` 页面级入口，按钮仍不超过四条。未结契只读；非当日特供、售罄、超库存、灵石不足、格式错误整笔拒绝且不改变任何状态；同一操作重投返回原回复。帮助、`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步，未改 schema、玩家表、道具售价或回收比例。

新增 `tests/test_daily_shop.py` 15 项；受影响商店/分页/命令/帮助/内容/运行时/契约审计/目标/成就/称号/战令/飞升合同 340 passed；`compileall` 与 `git diff --check` 通过。提交 `81b34ef` 已推送 develop，develop CI `40528647073` 全绿，fast-forward 合入 main 后 main CI `40529233227` 全绿。未部署、未发送真实 QQ、未跑本地全量；目标卡 `docs/goals/pet-goal-daily-shop.md` 仅本地保留、不提交。

### 灵田互助浇水（2026-10-27，已完成）

十张目标卡、四条聚合线、飞升与每日特供均已交付后，审计发现队伍只服务组队战斗，灵田完全单人，队友之间没有日常互动。本切片新增 `rules.farm_water`（缩短 60 秒/次、每人每日 3 次、每次 10 灵石）与 `灵宠浇水`：无参数列出同队队友与生长/成熟田位数，`灵宠浇水 <队友UID>` 查看四个田位，`灵宠浇水 <队友UID> <田位>` 为生长中的作物浇水。灵田读取助手改为支持指定所有者，`_growth_seconds` 同时扣除翻新与浇水缩短，总览、队友页与收获判定共用同一份计算。

浇水缩短量写入所有者 `quest_progress` 的 `farm_water_cut_<田位>`，当日田位标记 `farm_water_day_<北京日期>_<队友UID>_<田位>`，每日次数 `farm_water_daily_<北京日期>`；收获/补种/重新播种一并清除，下一轮不继承。只有同队队友可互相浇水，不能浇自己或跨队；空田、成熟、枯萎、次数用尽、未知 UID、越界田位与格式错误整笔拒绝，不扣灵石、不发灵石、不写计数；未结契只读，同一操作重投幂等。帮助、`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步；未改 schema、表结构、作物基础时长/产量/枯萎窗口/翻新价格/升级规则。

新增 `tests/test_farm_help.py` 16 项；受影响灵田/队伍/命令/帮助/内容/运行时/契约审计/目标合同 373 passed；`compileall` 与 `git diff --check` 通过。提交 `0df6f75` 已推送 develop，develop CI `40549589042` 全绿，fast-forward 合入 main 后 main CI `40550049616` 全绿。未部署、未发送真实 QQ、未跑本地全量；目标卡 `docs/goals/pet-goal-farm-help.md` 仅本地保留、不提交。

### 灵宠技能预设（2026-10-27，已完成）

灵田互助交付后，审计发现 24 门灵术、普通 2 格/飞升 5 格，而 `灵宠携带`/`灵宠卸技` 只能逐门调整，玩家在秘境、关卡、论剑与组队之间切换时没有可保存的配置。本切片新增 `gameplay/skill_presets.py`、`灵宠技能预设` 页面与 `保存/应用/清除 <1-3>`：每只伙伴三套方案，保存当前携带集合；应用前逐项校验技能仍存在、仍已学会、属性/类别/境界仍满足且不超过当前上限（普通 2、飞升 5），任一不满足整次拒绝，通过后在同一事务批量更新 `learned_skills.equipped`，不改变等级、熟练度、学习记录或宠物属性；已是当前配置时回复未改动。

预设写入 `quest_progress` 的 `skill_preset_<宠物编号>_<方案>` 标记（`progress` 记录技能数）与 `skill_preset_<宠物编号>_<方案>_<技能id>` 逐技能行，不新增表/列/货币；逐技能行避免内容追加导致位序漂移，已删除技能会明确报错而不是静默换位。保存不消耗资源、不写战报、不推进任务；应用要求伙伴未外出派遣，保存与查看不要求；封存/切换出战伙伴后按宠物编号保留。帮助、`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步，未改技能数值、携带上限、学习成本、熟练度或战斗规则。

新增 `tests/test_skill_presets.py` 19 项；受影响技能/飞升/命令/帮助/内容/运行时/契约审计/目标/成就/称号/战报/阵容合同 371 passed；`compileall` 与 `git diff --check` 通过。提交 `7a10e44` 已推送 develop，develop CI `40604405338` 全绿，fast-forward 合入 main 后 main CI `40604721222` 全绿。未部署、未发送真实 QQ、未跑本地全量；目标卡 `docs/goals/pet-goal-skill-presets.md` 仅本地保留、不提交。

### 论剑防守阵容与每周守擂奖励（2026-10-28，已完成）

技能预设交付后，工作区里已有一份未提交的防守镜像实现，但它没有闭环：`arena/eligibility.py` 仍按对方出战阵容判定境界并写入 `pvp_results.target_pet_id`，而实际镜像用的是防守阵容 —— 同一场战斗的境界门槛与宠物级结果记录都和真正出战的灵宠不一致；只有防守阵容、没有出战阵容的玩家仍被拒绝。另外 `spar` 被误改成使用防守镜像（切磋应取双方当前出战阵容），且对只有防守阵容的对手会 `IndexError`；`ArenaRules.defense_tiers` 作为必填字段让旧 `seasons.rules_snapshot` 无法解析，已部署存档里的旧赛季页面会直接报错。

本切片把防守方阵容收敛为唯一解析入口 `defense.resolve()`：排位论剑的境界门槛、镜像构建与 `pvp_results.target_pet_id` 全部读同一份结果，取防守阵容第一只作为宠物级记录；未设置、封存、易主、失联、种类重复或跨大境界时回退到出战阵容并在本人页面标注"已失效"，攻击者不被失效阵容阻挡。`设置` 校验 1-3 只、本人、未封存、不同种类且同一大境界；`spar` 恢复为双方出战阵容，仅排位 `pvp` 使用防守镜像。旧规则快照缺少 `defense_tiers` 时按当前内容补齐（防守奖励始终读当前内容，快照值不参与结算），`arena.json` 仍要求该字段并校验 id/名称/wins 唯一、wins 严格递增、奖励不递减、物品存在。

守擂奖励按北京时间自然周从 `pvp_results` 派生（本人为防守方且 `winner_id` 为本人；平局、败北、组队论剑不计），两档（2 胜 / 5 胜）凭证 `defense_reward_<周一零点时间戳>_<档位>` 各自独立，先领高档不消耗低档，换周自动重新开始；领取直接发放灵石与道具，不写战报、不扣精力、不加经验或熟练度，重投返回原回复。`灵宠防守` 页面、`灵宠目标` 汇总行与帮助三处入口连通；`docs/GAMEPLAY.md`、`docs/CONTENT.md` 已同步。schema 20、表结构、积分/限额/精力/熟练度规则、切磋资源语义与既有奖励数值不变。

新增 `tests/test_defense.py` 23 项（设置/清除、镜像出战与宠物级记录、仅防守阵容可挑战与无阵容仍拒绝、跨大境界拒绝与突破后回退、切磋仍取出战阵容且不再崩溃、逐档领取与先高后低、平局/败北/上周/组队不计、领奖不碰宠物进度、重启持久、重投幂等、未结契只读、QQ 按钮与蓝字分离、目标页入口、旧赛季快照可读、帮助与解析）；`test_contract_audit.py` 将 `defense` 纳入只读页面连通性审计。聚焦合同 14 个文件 `310 passed`，另跑受影响论剑/目标/帮助/飞升/战令/运行/消息批次 `233 passed` 与 `333 passed`；`compileall` 与 `git diff --check` 通过。提交 `a853f90` 已推送 develop，develop CI `40681642999` 全绿，fast-forward 合入 main 后 main CI `40682264261` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠禁地（2026-10-28，已完成）

论剑防守交付后，审计确认所有 PVE 面要么是固定内容（16 章节关卡、16 层万灵塔、20 处秘境），要么是每日轮换（今日秘境），没有任何玩法要求玩家按约束重组阵容，也没有任何 PVE 进度按周重置。本切片新增每周轮换的受限秘境「灵宠禁地」：三处禁地（焚骨禁地/霜狱/虚空祠）按北京时间自然周轮换，各带一条禁制（独行 1 只、双生 2 只、同心同主属性），每处三层必须按周内顺序通关，单层首通与三层全清各发一次周奖励，已通关层显示本周最佳回合。

禁制在开战前校验：不满足时整场拒绝，不扣精力、不进冷却、不写进度；禁制只约束出战阵容，战斗规则、配装与灵宠本身不变。三层复用既有敌手（林间傀儡、月影狼王、古殿守卫、寒晶守灵、腐沼毒灵、潮宫镇守、雷泽蛟灵），不新增敌人数值，也不改战斗引擎。每层首通写入 `quest_progress` 的 `forbidden_<周一零点时间戳>_<层id>`（`progress` 记录该场回合数），全清写入 `forbidden_<周一零点时间戳>_all`；换周自动重新开始，旧周凭证保留为历史。本周最佳回合由永久 `battle_records`（`kind='pve_stage'`、本人为胜方、当周内）取最少回合派生，不新增表或列。战报沿用 `pve_stage`，关卡战绩按当前关卡/塔层目录过滤，不会把禁地层混入章节统计。

列表页给出本周禁地、禁制、三层状态（`可挑战`/`未解锁`/`本周已通关`）、境界与精力、本周最佳与下周轮换预告；只有可挑战或本周已通关的行挂「前往挑战」蓝字，按钮保留 `灵宠秘境`/`灵宠关卡`/`灵宠战报`/`我的灵宠`。`灵宠目标` 新增禁地行与入口，帮助「秘境与关卡」新增三条，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。schema 20、表结构、既有 PVE 规则、精力/冷却、成就与平衡输入均不变。

新增 `tests/test_forbidden.py` 19 项（内容与轮换稳定、下周预告、未结契只读、列表/详情与行内蓝字、三种禁制拒绝与满足放行、周内顺序解锁、首通只发一次、再战只算练习、三层全清奖励只发一次、换周重开与再次发奖、本周最佳回合、境界/精力/冷却/参数/跨禁地层名拒绝、重投幂等与他人复用拒绝、战报归属与关卡战绩隔离、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 将 `forbidden` 纳入只读页面审计并登记 `DOCUMENTED_COUNTS` 3 项。聚焦合同 9 个文件 `203 passed`，另跑受影响 PVE/目标/成就/战令/防守/里程碑/消息批次 `228 passed`；`compileall` 与 `git diff --check` 通过。提交 `2c7fa3b` 已推送 develop，develop CI `40709152804` 全绿，fast-forward 合入 main 后 main CI `40709707789` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠膳房（2026-10-29，已完成）

灵宠禁地交付后，审计发现全项目 80 件道具里没有任何生产型玩法：消耗品只能从灵坊购买或委托掉落，灵粮/锻灵矿/血脉精华除了按 50% 回收没有第二条转化路径，也没有任何系统带专业等级。本切片新增常驻生产玩法「灵宠膳房」：六道菜谱按厨艺等级解锁，单膳产出可存进乾坤袋的消耗品，宴席则当场作用于全部在册伙伴。

厨艺等级 = 1 + 已烹饪过的不同菜谱数（上限 5），因此每掌握一道新菜升一级、重复做同一道菜不再升级；每日灶火 6 点、按北京时间换日重置，每道菜耗 1-4 点，`灵宠烹饪 <菜名> [份数]` 一次最多 9 份，灶火/灵石/材料按份数线性计算。开火前依次校验厨艺等级、剩余灶火、灵石与材料，任一不足整笔拒绝，不扣资源、不加道具、不写进度。宴席只作用于在册、未封存且未外出派遣的伙伴，精力与亲密按 100 封顶，修为照常累加；全部伙伴都在派遣时明确拒绝。单膳产物 `meal_rice/meal_herb/meal_lotus/meal_grain` 的 `price` 为空，只能经膳房产出，不进入灵坊分页、不能回收，但可继续用既有 `灵宠使用`/`灵宠喂养` 生效（`Item.effects` 本来就走数据驱动，未改使用路径）。

状态全部落在 `quest_progress`：`cuisine_dish_<菜谱id>` 记录累计份数并派生等级，`cuisine_heat_<北京日期>` 记录当日灶火消耗，`rules.json` 的 `cuisine.daily_heat/max_level` 是唯二数值入口；不新增表列，也不写战报、不推进任务或成就。页面给出厨艺、已掌握数、剩余灶火与每道菜的等级/灶火/成本/效果/状态，只有可烹饪行挂「烹饪」蓝字；`灵宠目标` 新增灵膳行，帮助「成长」新增两条，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_cuisine.py` 18 项（内容形状、未结契只读、页面状态与蓝字、单膳产出与扣费、重复菜不升级、等级门槛、材料/灵石整笔拒绝、每日灶火与跨日重置、超量拒绝、宴席覆盖全部在册并跳过派遣、无伙伴可宴请拒绝、精力亲密封顶、产物不可购买/回收、经既有使用路径生效、重投幂等、重启持久、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 将 `cuisine` 纳入只读页面审计并登记 `DOCUMENTED_COUNTS` 6 项。聚焦合同 8 个文件 `196 passed`，另跑商店/分页/消息/信息/灵田/周常/成就/战令批次 `190 passed`；`compileall` 与 `git diff --check` 通过。提交 `516e4ba` 已推送 develop，develop CI `40733259006` 全绿，fast-forward 合入 main 后 main CI `40733856173` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 团队试炼（2026-10-29，已完成）

膳房交付后，审计确认组队是唯一没有周目标的方向：队伍只服务一次性秘境、组队关卡与组队论剑，打完即散，也没有任何玩法带时间或输出约束。本切片新增每周轮换的团队首领「灵宠团队试炼」：三道试炼按北京时间周一切换，全队须在回合上限内击破，超时、失败与平局都不结算奖励。

数值入口只有 `data/team_trials.json`：古殿破阵（金丹起，古殿守卫 + 寒晶守灵，8 回合）、雷泽合击（凝气起，雷泽蛟灵，10 回合）、潮宫围猎（筑基起，潮宫镇守，8 回合），精力 25-30，每人首通奖励为修为/灵石区间加固定材料。`domain/team_trial_content.py` 与 `Catalog.team_trials` 校验编号、名称、境界、敌人、奖励物品、精力上限与 3-30 的回合上限；轮换取 `周一零点时间戳 // 86400 % 试炼数`，同周固定、跨周换题。

`gameplay/team_trial.py` 复用既有组队合同：仅队长发起、至少两名成员、全员准备且准备名单必须与 `team_pets` 实选一致，再逐人复核境界、精力与 PVE 冷却，任一人不足整笔拒绝、不扣任何资源。战斗结果只在 `winner == 0 and rounds <= round_limit` 时算通关；通关后每位**本周尚未通关**的成员各自领取奖励、写入 `quest_progress` 的 `team_trial_<周起点>_<试炼id>`（值为最好回合数）并推进 PVE 周常与战令，已通关成员继续陪打记「助战」不发奖，队伍最佳取成员最好回合数的最小值。战斗以 `pve_stage` 类型、试炼编号为键写入战报，不写 `pve_stage_progress`，因此不进关卡战绩、星级与塔层成就；不新增表、列或货币。

页面给出本周试炼、敌手、回合上限、准入境界、精力、每人奖励、各成员通关状态与队伍最佳，只有队长在「至少两人且全员准备」时才看到 `灵宠团队试炼 挑战`；未组队时是带组队指南蓝字的只读页。帮助「组队与派遣」新增两条，`灵宠目标` 新增团队试炼行并按「尚未组队 / 本周未通关 · <试炼> / 本周已通关（N 回合）」显示，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_team_trial.py` 17 项（内容形状与三道试炼、同周稳定跨周轮换、未组队只读页、成员进度与队长入口、非队长/未准备/单人队伍拒绝、首通逐人发奖与标记、助战不重复发奖且照扣精力、超时与失败不结算、回合上限纯函数、跨周不被旧标记阻塞、逐人境界/精力/冷却门、同操作重放与跨身份拒绝、战报类型与关卡战绩隔离、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `team_trial` 纳入只读页面审计并登记内容数量 3 项。聚焦 9 个文件 `208 passed`，另跑组队论剑/组队并发/队务消息/历练路线/战报/成就/战令/禁地/膳房/战斗批次 `183 passed`；`compileall` 与 `git diff --check` 通过。提交 `527f707` 已推送 develop，develop CI `40738809579` 全绿，fast-forward 合入 main 后 main CI `40739338272` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

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
