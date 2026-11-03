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

### 灵宠洞府（2026-10-29，已完成）

团队试炼交付后，审计确认全项目缺少「建造与升级」这个动词：所有系统要么是灵宠、要么是一场战斗、要么是一次性消耗品，没有玩家投入灵石与材料长期经营的设施，也没有由设施提供的每日行动；同时 `resonances.json` 已经承担了种族两两搭配加成，做「组合羁绊」会与共鸣重复，装备宝石则需要新表。本切片新增常驻设施「灵宠洞府」：灵泉、兽栏、丹房各 5 级，玩家用灵石与材料逐级升级，每天每处可领一次当前等级的效果。

数值入口只有 `data/cave.json`：灵泉每日恢复 30/45/60/75/100 精力，兽栏每日增加 3/5/7/9/12 亲密，丹房每日炼出 1/1/2/2/3 枚蕴灵丹；三类升级固定四步，灵石 300/700/1500/3000 加 2/4/6/8 份对应材料（灵粮 / 血脉精华 / 锻灵矿）。`domain/cave_content.py` 校验 `effect` 枚举、`yields` 级数与不递减、`item` 仅在 `effect='item'` 时存在、`upgrades` 数量恰为级数减一且不接受免费升级；`Catalog._validate_cave` 再校验产出物品与全部升级材料存在。

`gameplay/cave.py` 把等级与每日状态写进既有 `quest_progress`：`cave_<设施id>_level`（缺省 1 级）与 `cave_<设施id>_day_<北京日期>`，不新增表列。升级前依次检查满级、灵石、材料，任一不足整笔拒绝、不扣任何资源；成功后扣费并升级。使用按北京时间 00:00 换日，精力/亲密默认作用于当前出战伙伴、也可按名字指定，目标必须属于自己且未封存、未派遣，已满时拒绝且不消耗当日次数；丹房不需要伙伴，产物直接入乾坤袋；设施行动改变伙伴状态后取消该玩家组队准备，升级不影响准备。

页面给出洞府总级数、今日剩余次数、每处设施的等级/实际效果/今日状态与下一级花费，只有当前确实可执行的行才挂「使用 / 升级」蓝字，资源不足时标注「（资源不足）」且不给升级入口；未结契为带领养入口的只读页。帮助「成长」新增三条，`灵宠目标` 新增洞府行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_cave.py` 18 项（内容形状与五级/四步、未结契只读、页面等级与花费、资源不足标注与隐藏入口、升级精确扣费与升级后效果、满级拒绝、灵石/材料不足整笔拒绝、未知设施/空参数/未知子命令、灵泉恢复与 100 封顶与当日锁定、跨日恢复、满精力拒绝且不消耗次数、兽栏亲密封顶、丹房产物与拒绝多余伙伴、目标只限本人/未封存/未派遣、设施行动取消组队准备、重启持久、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `cave` 纳入只读页面审计并登记内容数量 3 项。聚焦 10 个文件 `227 passed`，另跑商店/委托合同/委托占用/队务/成就/战令/装备词条/套装批次 `256 passed`；`compileall` 与 `git diff --check` 通过。提交 `14d6242` 已推送 develop，develop CI `40742557771` 全绿，fast-forward 合入 main 后 main CI `40743042065` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 无尽回廊（2026-10-29，已完成）

洞府交付后，审计确认所有 PVE 玩法都是一次进入、一条消息结算（秘境、关卡、塔、禁地、团队试炼），没有任何模式让玩家在「继续深入」和「现在收手」之间做取舍。本切片新增单局制无尽模式「灵宠无尽回廊」：30 层，每层一只随层数复利放大的幻影，胜利后可继续或收手，战败只拿回一半且失去里程碑。

数值入口只有 `data/corridor.json`：以林间傀儡（85/17/5/12）为底，每层按气血 18%、攻击 14%、防御 12%、速度 10% 复利放大；第 N 层给 `10 + 6×(N-1)` 灵石与 `8 + 4×(N-1)` 修为，5/10/15/20/25/30 层各给一次材料里程碑；每只出战伙伴每层付 6 精力。`domain/corridor_content.py` 校验能量上限、层数区间、底敌人引用、复利率至少一项为正、里程碑层数唯一递增且不超过总层数、里程碑物品存在。

`gameplay/corridor.py` 用 `quest_progress` 的 `corridor_floor`（下一层）与 `corridor_best_<周一零点>`（本周最深）保存状态，不新增表列：挑战前逐只检查未派遣与精力，胜出后层数 +1 并展示累计待领奖励，收手一次性发放全部灵石/修为与已达里程碑，战败或平局只发一半且不给里程碑，第 30 层胜利自动按收手结算以免出现第 31 层。层与层之间不检查 PVE 调息，精力是唯一节奏限制；战报以 `pve_stage`、`corridor_<层>` 记录，不写 `pve_stage_progress`，因此关卡战绩、星级与塔层成就保持不变。

页面给出总层数、当前层、已清层数、待领灵石/修为/材料、本周最深、下一层幻影的实际四维与下一个里程碑，只有当前确实能打时才给「挑战」，已清至少一层才给「收手」，精力不足时说明原因；未结契为带领养入口的只读页。帮助「秘境与关卡」新增三条，`灵宠目标` 新增回廊行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_corridor.py` 20 项（内容与线性奖励、未结契只读、新页仅给挑战、单层推进与精力扣除、三层累计待领、收手全额与里程碑与清空与重复收手拒绝、无进行中回廊拒绝、战败减半且无里程碑、满层自动结算、精力门、派遣门、复利数值与命名、跨周本周最深归零、重启持久、不写关卡进度、同操作重放、帮助/目标/解析、QQ 按钮与蓝字分离、页面按精力隐藏可执行入口、内容校验拒绝越界/乱序/零增长）；`test_contract_audit.py` 把 `corridor` 纳入只读页面审计并登记内容数量 1 项。聚焦 10 个文件 `215 passed`，另跑禁地/团队试炼/洞府/膳房/成就/战令/委托占用/历练路线/论剑批次 `264 passed`；`compileall` 与 `git diff --check` 通过。提交 `aebcdb1` 与补充测试 `b359b32` 已推送 develop，develop CI `40754985290`、`40755674091` 全绿，fast-forward 合入 main 后 main CI `40756151986` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠师门（2026-10-29，已完成）

无尽回廊交付后，审计确认玩家维度只剩 UID 与由指标派生的称号：共鸣管种族两两搭配、洞府管设施、称号是阈值展示，没有任何「选择身份并长期投入」的玩法，也没有任何玩家级状态会进入战斗。本切片新增师门：四派各带一项随阶位成长的被动，首次拜入免费，转投 500 灵石且各派贡献分别保留。

数值入口分两处：`data/sects.json` 定义四派（剑阁攻击、玄门气血、丹鼎门防御、御兽宗速度）与五阶曲线（贡献 0/60/160/320/560、加成 2%/4%/6%/8%/10%、灵石 120/240/480/900/1600 加各派材料 1/2/3/5/8 份），`rules.json` 的 `sect` 定义每日贡献 10、修行精力 20、修行修为 30、转投灵石 500。`domain/sect_content.py` 校验门派属性枚举、阶位从 1 连续、首阶贡献为 0、贡献与加成严格递增、加成不超过 50%；`Catalog._validate_sects` 再校验全部奖励物品存在。

`gameplay/sects.py` 把加入、当前门派、贡献、当日修行与领赏写进既有 `quest_progress`（`sect_member_*`、`sect_current_*`、`sect_contrib_*`、`sect_day_*`、`sect_claim_*`），不新增表列；阶位由贡献实时推导，被动不单独存档。修行每日一次、按北京时间换日，逐一检查出战伙伴未派遣与 20 精力，任一不足整笔拒绝；`领赏` 一次补齐所有已达阶位未领取的奖励，不重复、不超前。被动在 `loadout.combatant` 的共鸣之后、装备之前按**伙伴所属玩家**放大对应属性，镜像防守因此使用对手自己的师门；未拜入时不产生任何加成。

页面在未拜入时列出四派被动与「拜入」入口，拜入后给出当前门派、阶位、被动、贡献进度、今日修行状态、可领阶位与转投花费，只在确实可执行时给「修行 / 领赏」蓝字；未结契为带领养入口的只读页。帮助「成长」新增四条，`灵宠目标` 新增师门行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_sects.py` 20 项（内容四派五阶、阶位曲线校验负例、未结契只读、未拜入四派与拜入入口、首次拜入免费、重复/未知门派拒绝、转投扣费与双向贡献保留、灵石不足拒绝、修行贡献与修为与精力、每日一次与跨日恢复、精力不足与派遣拒绝、未拜入拒绝、跨阶提升、逐阶领赏与不重复、不超前领赏、被动随阶位放大且只作用于本人、未拜入无加成、重启持久、同操作重放、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `sect` 纳入只读页面审计并登记内容数量 4 项。聚焦 10 个文件 `237 passed`，另跑装备/天赋/飞升/词条/羁绊/成就/战令/洞府/回廊/禁地/团队试炼批次 `207 passed`；`compileall` 与 `git diff --check` 通过。提交 `6849d2a` 已推送 develop，develop CI `40787473616` 全绿，fast-forward 合入 main 后 main CI `40787867641` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠图鉴试炼（2026-10-29，已完成）

师门交付后，审计确认 27 个种族的图鉴仍然只是「拥有即领奖」的清单：没有任何玩法要求你真的培养并使用某一个种族，图鉴奖励与实际战斗脱节。本切片新增按种族的一对一试炼「灵宠图鉴·种族试炼」：用自家该族伙伴单挑该族幻影，首通发奖并累计里程碑。

数值入口只有 `data/codex_trials.json`：幻影属性 = 该族基础属性 × 2.2（元素与主属性沿用种族，不配灵术），每场精力 10，首通灵石 200 / 修为 150 / 锻灵矿 1，9/18/27 族各发一次材料里程碑（锻灵矿 4 / 血脉精华 4 / 蕴灵丹 4）。`domain/codex_trial_content.py` 校验 boost 区间、能量、里程碑数量唯一递增；`Catalog._validate_codex_trials` 再校验奖励物品存在且里程碑不超过种族总数。

`gameplay/codex_trials.py` 以 `quest_progress` 的 `codex_trial_<种族id>`（首通回合）与 `codex_trial_milestone_<数量>` 存状态，不新增表列：出战伙伴优先取与该族匹配的当前出战宠，否则取该族最早结契的未封存伙伴；逐场校验派遣与精力并进入共享 PVE 冷却；首通才发奖并推进 PVE 周常，重复通关只记练习；修为直接发给参战伙伴而不是当前出战宠。战报以 `pve_stage`、`codex_<种族id>` 记录，不写 `pve_stage_progress`，关卡战绩/星级/塔层成就保持不变。

页面按种族 id 分页（每页 9 个，共 3 页），每行给出幻影四维与状态（未拥有 / 可挑战 / 已通关 N 回合），只有已拥有种族给「挑战」蓝字；页脚列出里程碑与「再战只作练习」说明。帮助「秘境与关卡」新增两条，`灵宠目标` 新增图鉴试炼行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_codex_trials.py` 16 项（配置形状、未结契只读、分页与拥有状态与链接、未知/未拥有种族拒绝、首通奖励与标记与战报与不写关卡进度、重复通关练习不发奖、战败扣精力无进度、精力与派遣门、非出战同族伙伴也能出战、9 族里程碑只发一次、未达数量不发里程碑、页面与目标进度、重启持久、同操作重放、帮助/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `codex_trials` 纳入只读页面审计并登记内容数量 1 项。聚焦 12 个文件 `244 passed`，另跑塔/回廊/禁地/团队试炼/洞府/师门/成就/战令/论剑批次 `184 passed`；`compileall` 与 `git diff --check` 通过。提交 `68dde61` 已推送 develop，develop CI `40789901187` 全绿，fast-forward 合入 main 后 main CI `40790283338` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠淬魂（2026-10-29，已完成）

图鉴试炼交付后，审计确认灵卵只有「孵化成同族新宠」一个用途：重复种族、重复灵卵没有出口，同一族的两只伙伴在境界/层数/血脉相同时完全等价，玩家也没有办法把资源集中到某一只伙伴身上。本切片新增「灵宠淬魂」：消耗同族灵卵与灵石，为选中的伙伴叠加永久全属性层数。

数值只在 `rules.json` 的 `temper`：最多 10 层、每层全属性 +1%、每层 50 灵石与 1 枚 `egg_<种族id>`；`TemperRule` 校验层数 1-20、比率 0-5% 与灵石非负。层数按伙伴写入 `quest_progress` 的 `temper_<宠物编号>`，不新增表列；加成由 `loadout.combatant` 在师门被动之后、装备之前乘到四维，因此秘境、关卡、塔、禁地、回廊、图鉴试炼与论剑镜像都会生效，镜像防守使用对手自己的层数。

`gameplay/tempering.py` 负责页面与淬魂：先按名字解析本人伙伴（含封存判断），再检查派遣、满层、请求层数是否超过剩余，最后校验灵石与该族灵卵，任一不足整笔拒绝、不扣任何资源；成功后扣费、写层数并取消组队准备。页面列出每只未封存伙伴的层数、当前加成、持有同族灵卵与下一层花费，只有确实能淬的行才挂「淬魂」蓝字，满层显示「已满」。帮助「成长」新增两条，`灵宠目标` 新增淬魂行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_tempering.py` 15 项（未结契只读、页面层数/灵卵/花费与入口、无卵或无灵石隐藏入口、单层与多层扣费、满层拒绝、超出剩余层拒绝、灵石/灵卵不足整笔拒绝、异族灵卵不误用、未知/封存/派遣拒绝、四维按层放大且只作用于该宠、重启持久、同操作重放、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `temper` 纳入只读页面审计。聚焦 10 个文件 `230 passed`，另跑师门/洞府/图鉴试炼/共鸣/天赋/论剑/装备词条/飞升批次 `133 passed`；`compileall` 与 `git diff --check` 通过。提交 `406756a` 已推送 develop，develop CI `40801254158` 全绿，fast-forward 合入 main 后 main CI `40801603141` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠守关（2026-10-29，已完成）

淬魂交付后，审计确认所有战斗都以击杀分胜负：塔、禁地、回廊、图鉴试炼都在敌人或我方倒下时结束，没有任何玩法衡量「能撑多久」，防御与续航流派也没有可量化的目标。本切片新增「灵宠守关」：面对气血 ×40、攻击 ×0.6 的深渊魔将，成绩是撑过的回合数，历史最深永久保留。

数值入口只有 `data/survival.json`：守卫四项倍率、每场精力 12、5/10/15/20 回合四档里程碑（灵石 300/600/1000/1600，修为 120/220/360/520，材料 2/2/3/5）。`domain/survival_content.py` 校验倍率区间、里程碑回合唯一递增；`Catalog._validate_survival` 再校验敌人与里程碑物品存在。

`gameplay/survival.py` 复用塔的出战/精力/冷却合同：全队每只伙伴付 12 精力，战败或平局按 `battle.rounds` 记分，打赢则直接记满目标 20 回合，避免速杀反而低分。成绩写入 `quest_progress` 的 `survival_best`，只增不减；跨档时一次补齐所有新达成里程碑并入账 `survival_milestone_<回合>`，已领档位不再重复。战报以 `pve_stage`、`survival` 记录，不写 `pve_stage_progress`，关卡战绩/星级/塔层成就保持不变。

页面给出守卫四维、目标回合、历史最深与每档状态（已领/可达/未达），未达目标给「挑战」，已达目标给「再战」；未结契为带领养入口的只读页。帮助「秘境与关卡」新增两条，`灵宠目标` 新增守关行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_survival.py` 16 项（配置与倍率、守关属性缩放、未结契只读、页面守卫/最深/里程碑、战败按回合记分并写战报、胜利记满目标、里程碑只发一次、跨档一次补齐、更差成绩不降低最深也不补发、精力门、派遣门、达目标后切「再战」、重启持久、同操作重放、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `survival` 纳入只读页面审计并登记内容数量 1 项。聚焦 10 个文件 `211 passed`，另跑回廊/禁地/图鉴试炼/淬魂/师门/洞府/成就/战令批次 `165 passed`；`compileall` 与 `git diff --check` 通过。提交 `4a0384f` 已推送 develop，develop CI `40827896758` 全绿，fast-forward 合入 main 后 main CI `40828226418` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠奇缘（2026-10-29，已完成）

守关交付后，审计确认游戏里的叙事只有「一次性奇闻」与「主线清单」两种：奇闻随机出现、只有一个选择；主线是按指标打勾，没有任何系统支持**多章连读、每章抉择、前后依赖**的故事线。本切片新增「灵宠奇缘」：三条三章故事按顺序解锁，每章两个选项，选项奖励立即结算，第三章后发放通关奖励。

数值入口只有 `data/arcs.json`：风起青萍（order 1、启灵、无前置）、雪夜灯影（order 2、筑基、需完成风起青萍）、星槎渡（order 3、金丹、需完成雪夜灯影）；三章各两个选项，奖励为灵石/修为/材料，通关奖励 200~320 灵石与 150~240 修为。`domain/arc_content.py` 校验章序号连续、每章恰好两个且选项 id 唯一、`requires` 指向真实奇缘且不能自指；`Catalog._validate_arcs` 再校验境界与全部奖励物品存在。

`gameplay/arcs.py` 把进度写进 `quest_progress` 的 `arc_<id>_step`（下一章）、`arc_<id>_pick_<章>`（选项序号）与 `arc_<id>_done`，不新增表列。列表页给出三条奇缘的状态与境界要求，只有已解锁未完成的才给「进入」；详情页给当前章正文与两个选项的文案、奖励和蓝字；选择时校验前置、境界、章节与选项，通过后立即发放灵石/修为/材料并推进，第三章选择后标记完成并发放终章奖励，已完成奇缘拒绝重走。修为直接加到当前出战伙伴，不因伙伴外出而被 `grant` 的空闲校验卡住；同一操作重投返回原回复，不二次结算。

页面列表与详情都只读展示，操作全在蓝字；帮助「秘境与关卡」新增三条，`灵宠目标` 新增奇缘行（已完成 N/3 · 进行中 <奇缘>），`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_arcs.py` 16 项（三条奇缘与链条、章数与选项校验负例、未结契只读、列表状态与仅开放入口、详情章节与双选项、选择扣发奖励并推进、未知选项拒绝、前置锁定、境界门槛、第三章终章奖励只发一次、完成后拒绝重走、下一奇缘解锁、选项记录、重启持久、同操作重放不重复发奖、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `arcs` 纳入只读页面审计并登记内容数量 3 项。聚焦 9 个文件 `207 passed`，另跑守关/图鉴试炼/淬魂/洞府/师门/回廊/成就/战令批次 `162 passed`；`compileall` 与 `git diff --check` 通过。提交 `884142e` 已推送 develop，develop CI `40841329710` 全绿，fast-forward 合入 main 后 main CI `40841784610` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠助战（2026-10-29，已完成）

奇缘交付后，审计确认所有养成系统都只作用于「上场的这一只」：共鸣、师门、淬魂、装备、套装、羁绊各自独立，后备伙伴除了换人没有任何价值，五只上限之外养出来的伙伴完全闲置。本切片新增「灵宠助战」：两个后备席位，各把该伙伴基础四维的 10% 借给当前出战伙伴。

数值只在 `rules.json` 的 `support`：`slots` 2、`rate` 0.1；`SupportRule` 校验席位 1-3 与比率 0-50%。`gameplay/support.py` 负责页面、设置与清除：候选必须是本人名下、未封存、未派遣且不在出战阵容的伙伴，同一只不能占两席；设置/清除都会取消组队准备。加成按 `pet_stats(助战伙伴)`（不含装备、词条、套装、淬魂、师门）乘比率取整后求和，由 `loadout.combatant` 在淬魂之后、装备之前只加给**当前出战伙伴**，其他伙伴与镜像对手均不受影响。

状态记在 `quest_progress` 的 `support_1` / `support_2`（伙伴编号），不新增表列；结算时若助战伙伴已封存、已派遣或已不存在，该席自动不计入，避免陈旧编号制造幽灵加成。页面列出两席当前伙伴与贡献、候选伙伴及预计加成，只有可执行行才挂「设为助战 / 清除」蓝字；帮助「成长」新增三条，`灵宠目标` 新增助战行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_support.py` 17 项（规则与校验负例、未结契只读、空席位与出战伙伴排除、候选贡献与席位链接、设置与目标行、10% 四维精确加成、非出战伙伴无加成、两席叠加、出战伙伴拒绝、封存/派遣拒绝、未知名字/超席/重复占位/格式拒绝、清除回退加成、设置清除取消准备、重启持久、同操作重放、帮助/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `support` 纳入只读页面审计。聚焦 10 个文件 `235 passed`，另跑师门/洞府/图鉴试炼/守关/奇缘/论剑/成就/战令批次 `165 passed`；`compileall` 与 `git diff --check` 通过。提交 `d02c122` 已推送 develop，develop CI `40844274237` 全绿，fast-forward 合入 main 后 main CI `40844735426` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠劫境（2026-10-29，已完成）

助战交付后，审计确认周常 PVE 的形态已经固定：禁地锁阵容、团队试炼锁首领与回合上限、回廊是单局赌注，没有任何玩法让同一批秘境以**不同风险参数**被重打。本切片新增「灵宠劫境」：每周三份契约，各把一条数值词缀压在现有秘境上，首通发该词缀的奖励，三份全清再发周奖励。

数值入口只有 `data/tribulations.json`：6 条词缀（血潮气血 ×1.5、刃风攻击 ×1.3、铁壁防御 ×1.5、疾影速度 ×1.25、漏刻 12 回合上限、稀薄精力 ×1.5），每份契约 15 点精力（稀薄向上取整为 23），首通奖励 260-340 灵石与 170-220 修为加材料，三份全清奖励 500 灵石 / 300 修为 / 锻灵矿 3。`domain/tribulation_content.py` 校验倍率区间、回合上限只能 0 或 3-30、精力倍率与词缀唯一；`Catalog._validate_tribulations` 校验奖励物品。

`gameplay/tribulations.py` 用周序号确定性抽签：第 s 份取 `dungeons[(周序号+7s) % 秘境数]` 与 `modifiers[(周序号+2s) % 词缀数]`，同周稳定、跨周轮换，无需随机数或额外存档。战斗按词缀放大敌方四维，逐只校验派遣与精力并进入共享冷却；带回合上限的契约即使判胜，超过上限也算超时，不发奖、不写凭证。凭证为 `quest_progress` 的 `trib_<周起点>_<序号>` 与 `trib_<周起点>_all`，不新增表列；战报以 `pve_stage`、同一键记录，不写 `pve_stage_progress`，关卡战绩/星级/塔层成就保持不变。

页面逐条列出秘境、词缀、敌手四维、精力、奖励与状态，只有未通关的契约挂「挑战」蓝字；帮助「秘境与关卡」新增两条，`灵宠目标` 新增劫境行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_tribulations.py` 18 项（内容与词缀、校验负例、同周稳定跨周轮换、未结契只读、三份契约与入口、首通奖励与凭证与战报、重复通关拒绝、战败扣精力不发奖、超时不发奖、稀薄精力 23、三份全清奖励只发一次、精力门、非法序号、跨周重置、重启持久、同操作重放、帮助/目标/解析、QQ 按钮与蓝字分离）；`test_contract_audit.py` 把 `tribulations` 纳入只读页面审计并登记内容数量 1 项。聚焦 10 个文件 `226 passed`，另跑守关/回廊/图鉴试炼/洞府/师门/淬魂/助战/奇缘/成就/战令批次 `195 passed`；`compileall` 与 `git diff --check` 通过。提交 `61da604` 已推送 develop，develop CI `40847260068` 全绿，fast-forward 合入 main 后 main CI `40847887008` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵术连携（2026-10-29，已完成）

劫境交付后，审计确认战斗玩法已经铺满（禁地/团队试炼/回廊/守关/劫境/图鉴试炼/塔/秘境/PVP），仍然平坦的是**配装**：技能各自结算，玩家换技能时没有组合收益；全服唯一的跨件联动是种族共鸣。本切片新增「灵术连携」：两门技能成对携带时给一份小属性加成，让技能栏的选择变成二维。

内容只有 `data/combos.json` 六组：风火相生（风刃术 + 赤焰术 → 攻击 +5%/速度 +3%）、雷霆共鸣（雷霆吐息 + 惊雷术 → 攻击 +6%）、霜华守望（霜枪术 + 霜茧回生 → 防御 +6%/气血 +4%）、木灵相济（青木回春 + 青藤鞭 → 气血 +5%/防御 +4%）、金锋破障（金锋术 + 破障术 → 攻击 +4%/速度 +4%）、岩阵同心（碎岩术 + 镇岳护阵 → 防御 +5%/气血 +5%）。`domain/combo_content.py` 校验两门技能互不相同、每项 0-10%、合计 ≤15% 且不全为 0；`Catalog._validate_combos` 校验技能存在并禁止重复技能对。

`gameplay/combos.py` 不落任何存档：`matched` 每次按 `learned_skills` 中已携带的技能实时判定，`page` 逐条列出技能对、加成与 `已连携`/`未集齐（缺 …）`，`objective_line` 给出 `连携：已连携 N/6`。`combatant` 在技能循环之后调用 `combos.apply`，按内容顺序以 `int(属性 × (1 + 加成) + 0.5)` 逐组放大，排在共鸣/师门/淬魂/助战/装备/羁绊/套装之后，因此与其他乘区相乘、彼此也按顺序相乘。技能元素与境界门槛仍由 `check_requirements` 把关，六组内容都落在真实物种的元素组合上（风火→毕方/三灵鹿、雷→蛟龙、冰→玄冰蚕、木→青鸾/青藤灵、金与岩→白泽/金羽隼等）。

页面入口 `灵宠连携`，帮助「灵物与灵术」新增一条，`灵宠目标` 新增连携行，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步；`test_contract_audit.py` 把 `combos` 纳入只读页面并登记 6 项内容，`test_content.py` 新增未知技能与重复技能对两条负例。

新增 `tests/test_combos.py` 14 项（六组内容、校验负例、未结契只读、六组全未集齐、单技能缺口提示、成对已连携、战斗属性精确、单技能不变、按内容顺序叠乘、加成归属该宠物、卸下即失效且不写存档、目标/帮助/解析、参数拒绝、QQ 按钮与蓝字分离）。聚焦 11 个文件 `238 passed`，另跑淬魂/助战/师门/图鉴试炼/劫境/竞技/战令/成就/技能预设/套装批次 `190 passed`；`compileall` 与 `git diff --check` 通过。提交 `1289978` 已推送 develop，develop CI `40850354735` 全绿，fast-forward 合入 main 后 main CI `40850791361` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠传功（2026-10-29，已完成）

连携交付后审计发现两处断点：连携要求同一只伙伴同时具备两门技能，而技能只能靠秘笈一本一本学，玩家想让后备伙伴补一门已有技能时没有任何捷径；本地 53 张目标卡已全部交付（`pet-goal-index-10.md` 十目标全绿，`pet-roadmap-index.md` 四线全绿，`test_pet_outing.py` 的覆盖在 `test_play_games.py` 内），没有可继续执行的旧卡。于是本切片补「灵宠传功」：已学会的灵术可以按秘笈价格的八成复制给另一只伙伴，师父保留，徒弟从 1 层 0 熟练度起步。

数值只有 `rules.json` 的 `transfer`（`price_rate` 0.8、`min_stones` 80、`bloodline_essence` 1），`domain/content.py` 的 `TransferRule` 校验 0-1 / 非负 / 0-5。`gameplay/transfer.py` 先完成全部前置校验再扣费：师父已学、徒弟未学、徒弟满足属性类别境界、双方不在派遣、灵石与精华足够、同名伙伴要求改编号、师父徒弟不同；通过后扣灵石与血脉精华，按徒弟剩余携带位写入 `learned_skills(pet_id, skill_id, equipped, 1, 0)`。师父一侧不改动，因此同一门灵术可反复传授给不同伙伴，但每次都要付费，不构成绕过秘笈价格。

费用按 `ceil(秘笈价 × 0.8)` 与 80 灵石取大；秘笈无标价时按 80 计。页面以当前出战伙伴为师父，列出每门已学灵术的熟练度、传功费用与可承接伙伴，未结契只读；帮助「灵物与灵术」新增两条。`test_contract_audit.py` 无需变更（传功是动作命令，不是只读页），`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_transfer.py` 16 项（费用规则、未结契只读、无技能文案、页面候选与费用、正常传授与扣费、携带位满不自动携带、师父未学、徒弟已学、同一只、未知与同名伙伴、徒弟条件不符、灵石与精华不足且零写入、派遣拒绝、重放幂等、格式/解析/帮助、QQ 按钮与蓝字分离）。聚焦 10 个文件 `228 passed`，另跑配装/淬魂/助战/师门/劫境/成就/战报/图鉴试炼/道具/共鸣批次 `165 passed`；`compileall` 与 `git diff --check` 通过。提交 `7ef03f1` 已推送 develop，develop CI `40852834637` 全绿（2679 项），fast-forward 合入 main 后 main CI `40853370702` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠成就商店（2026-10-29，已完成）

传功交付后审计确认：77 个成就各自只发一份固定奖励，领完即成死内容，全服没有任何由玩家**自主支配**的货币。本切片新增「灵宠成就商店」：每领取一个成就奖励累积 10 点成就点，点数可在商店换取自选材料。

点数是派生值：`累计 = per_claim × achievement_claims 行数`（`rules.json` 的 `achievement_points.per_claim` 1-100，当前 10），已用写在 `quest_progress` 的 `ach_points_spent`，因此历史领取自动计入、无需迁移，也不新增货币表或列。内容只有 `data/achievement_shop.json` 六项（灵粮包 40、灵石袋 50、蕴灵丹 60、锻灵矿对 70、血脉精华 90、厚藏 220），`domain/achievement_shop_content.py` 校验 `cost` 1-100000 与奖励非空，`Catalog._validate_achievement_shop` 校验物品存在。

`gameplay/achievement_shop.py` 的 `page` 显示 `可用/累计/已用` 与逐项状态，只给余额足够的行挂「兑换」蓝字；`redeem` 支持序号或名称，先校验余额、物品定义与序号范围，再一次性更新 `ach_points_spent` 并发放灵石与物品。奖励直接入账而不经过 `grant`，所以有灵宠离线派遣时也能兑换；可重复兑换、无库存与冷却；未结契只读不建档。`achievements.claimed_count` 作为共享计数被商店复用，`灵宠目标` 新增成就点行，帮助「身份与收集」新增两条，`test_contract_audit.py` 把 `achievement_shop` 纳入只读页面并登记 6 项内容，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_achievement_shop.py` 17 项（规则与六项内容、内容校验负例、未结契只读、零领取零点、领取即加点、页面全项与只给可兑换行挂入口、物品兑换扣点入账、灵石袋只发灵石、重复兑换叠加、点数不足零写入、非法序号/名称/参数、物品定义缺失拒绝且不扣点、同操作重放、重启后持久、后续领取继续增长、目标/帮助/解析、QQ 按钮与蓝字分离）。聚焦 10 个文件 `252 passed`，另跑传功/连携/淬魂/助战/劫境/战令/称号/收集榜/周常课题/世界首领批次 `139 passed`；`compileall` 与 `git diff --check` 通过。提交 `f0fa3c9` 已推送 develop，develop CI `40973829317` 全绿（2696 项），fast-forward 合入 main 后 main CI `40974250198` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵术专精（2026-10-29，已完成）

成就商店交付后审计确认：熟练度体系是平坦的——任何一只灵宠把风刃术练到 3 级都恰好是 1.25×，伙伴之间只剩「带了哪几门技能」的差别，连携/传功也只决定**装备哪几门**，没有任何让同一门灵术因主人不同而更值钱的机制。本切片新增「灵术专精」：每只伙伴选定一门已学灵术，按流派把它在该伙伴身上的威力倍率乘以 `1 + 流派加成`。

内容只有 `data/specializations.json` 四条流派（单体精研 15%、群攻精研 12%、控场精研 18%、护持精研 20%），流派从技能自身形状派生（敌对效果→控场、治疗或护持效果→护持、群体→群攻、其余→单体），`domain/specialization_content.py` 的 `skill_archetype` 与 `Specialization`（5%-30%）负责分类与校验，`Catalog._validate_specializations` 强制每门灵术都能落到已声明流派上，因此不存在「无法专精」的技能。数值只有 `rules.json` 的 `specialization`（`min_level` 3、`switch_stones` 300）。

`gameplay/specialization.py` 把状态写成 `quest_progress` 的 `spec_<宠物编号>_<灵术id>` 单行（灵术 id 放键里，`progress` 是整数列），按前缀读取，因此换技能、遗忘他术、重启都不影响。`choose` 先校验已学、3 级门槛、派遣状态与灵石，改投他术整笔扣 300 灵石并替换旧行，首次免费；`cancel` 免费删除并明确不返还。加成由 `loadout.combatant` 在技能倍率赋值之后乘上 `1 + rate`，`combat.py` 与 `effects.py` 读同一份 `skill_multipliers`，所以专精同时作用于伤害与效果强度，战斗引擎零改动。页面列出等级/熟练度/流派/加成/状态并只给可专精行挂蓝字，`灵宠目标` 显示专精行，帮助「灵物与灵术」新增三条，`test_contract_audit.py` 把 `specialization` 纳入只读页面并登记 4 项内容，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_specialization.py` 20 项（四条流派与费率、全技能可分类、分类器按技能形状、费率越界拒绝、未结契只读、页面等级/流派/状态与唯一入口、首次专精免费、技能行零改动、页面显示已专精与取消入口、改投扣 300 灵石、灵石不足零写入、重复选择拒绝、低于 3 级与未学习拒绝、取消免费且空专精拒绝、派遣拒绝、战斗倍率精确为 等级倍率 × (1+加成) 且其他技能不变、只放大被专精技能、重启持久与重放、目标/帮助/解析/参数、QQ 按钮与蓝字分离）。聚焦 10 个文件 `237 passed`，另跑连携/传功/技能预设/淬魂/助战/师门/成就商店/竞技/战报/图鉴试炼批次 `164 passed`；`compileall` 与 `git diff --check` 通过。提交 `5058e10` 已推送 develop，develop CI `41003443204` 全绿（2716 项），fast-forward 合入 main 后 main CI `41003821980` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠心境（2026-10-30，已完成）

专精交付后审计确认：全服所有数值都只增不减——亲密封顶后不再变化、精力是花完等待、封存或长期不碰的伙伴与天天照料的伙伴毫无区别，没有任何机制让「是否被照顾」进入战斗。本切片新增「灵宠心境」：每只伙伴的短期状态按天衰减，并按当前档位给出 ±10% 以内的四维倍率。

内容 `data/moods.json` 四档（心情大好 3 点 ±0%、心境平稳 2 点 −5%、心情低落 1 点 −10%、心灰意冷 0 点 −15%），`domain/mood_content.py` 的 `MoodLevel`（阈值 ≥0、倍率 ±30%、阈值 0 不得为正加成）与 `mood_of` 负责查询；`Catalog._validate_moods` 强制最高档阈值等于 `rules.mood.max`、最高档倍率必须为 0 且倍率单调不升、每档倍率与 `rules.mood.rates` 同 id 完全一致。首版把最高档设计成 +5%，本地 10 文件批次全绿但 develop CI `41016608537` 抓到三处回归（`test_ascension` 的飞升血量与判定、`test_lineages` 的 `attack == base.attack + 6`），证实「照顾送强度」是基线膨胀，已改为照料即基准、只由冷落扣属性。数值只有 `rules.json` 的 `mood`（`max` 3、`decay_days` 2、`soothe_items` 1）。

心境是派生值：`quest_progress` 只存 `last_care_<宠物编号>` 一行的北京时间日序数，当前值 = `max − 间隔天数 // decay_days`（下限 0），因此不需要任何定时任务，也不会因为某天没打开页面而错算；无该行的伙伴视为满值，所以新领养与旧存档存量伙伴不会一上线就低落。`gameplay/mood.py` 的 `care()` 被 `灵宠喂养`、每日 `灵宠互动` 与 `灵宠心境 安抚` 三处共用：正常游玩自然维持，忙时用 1 份灵粮安抚回满。安抚在已满、派遣中、编号无效、灵粮不足时整笔拒绝且不消耗。

加成落在 `loadout.combatant` 的**最前面**（伙伴自身基础四维），这样装备、词条、羁绊、套装的固定加成保持原值——首版放在末尾相乘会放大这些固定值，`test_loadout` 的三项契约立刻抓到（例如 `attack == 25 + 6` 变成 32），已改为只放大基础四维。页面逐宠列出档位、当前值、倍率与下次衰减倒计时并只给可安抚行挂蓝字，`灵宠目标` 新增心境行，帮助「成长」新增两条（与喂养、互动同组），`test_contract_audit.py` 把 `mood` 纳入只读页面并登记 4 项内容，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_mood.py` 17 项（内容与规则一致且无正加成、`mood_of` 分档、等级校验负例、新伙伴满值、每档衰减与下限、读取不写状态、冷落逐档降属性且满值不动属性、喂食与互动刷新照料、安抚回满与扣灵粮、三类拒绝零写入、派遣拒绝、页面逐宠与只给可安抚行入口、未结契只读、目标/帮助/解析、重启持久、QQ 按钮与蓝字分离）。聚焦 10 个文件 `239 passed`，另跑专精/连携/传功/陪伴/羁绊/道具/竞技/套装/共鸣/劫境批次 `130 passed`，并补跑 CI 抓到的 `test_ascension`/`test_lineages`/`test_loadout`（`94 passed`）；`compileall` 与 `git diff --check` 通过。功能提交 `1f4669d`、修正提交 `ad8f9ae` 已推送 develop，develop CI `41017439009` 全绿（2733 项）；首版 develop CI `41016608537` 因飞升/血脉两项基线回归失败，修正后通过。随后 fast-forward 合入 main，main CI `41017856076` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠竞速（2026-10-30，已完成）

心境交付后审计确认：全服每一种玩法都以 `fight()` 分胜负（秘境、关卡、塔、回廊、守关、禁地、团队试炼、图鉴试炼、劫境、论剑、切磋），因此速度与气血只在战斗里当子属性用，玩家无法在不打一场的情况下检验配装，也没有「靠堆对属性就能领先」的日常玩法。本切片新增「灵宠竞速」：把伙伴的最终四维直接折算成用时，每周一条赛道、一张全服榜。

内容只有 `data/races.json` 三条赛道（直道竞速 800 米 速度 ×1.25、长坡耐力 1200 米 气血 ×1.3、险道越障 1000 米 防御 ×1.4），`domain/race_content.py` 校验长度 100-10000 与地形属性/倍率，`Catalog._validate_races` 要求地形属性必须出现在权重表里。数值在 `rules.json` 的 `race`（每次 20 精力、每日 3 次、权重 速度 50%/气血 20%/攻击 20%/防御 10%），`RaceRule` 校验权重合计为 1；因 `players` 没有 `last_race` 列，改用每日次数限流，不新增列也不占用既有冷却。

用时是派生值：`round(长度 × 100 / 加权总和)`（地形属性乘倍率，最少 0.1 秒），属性取自 `loadout.combatant`，所以心境、天赋、共鸣、师门、淬魂、助战、装备、词条、羁绊、套装、连携、专精全部自动计入。赛道按北京日期序号轮换，同一天全服一致、次日换道。状态只有 `quest_progress` 的 `race_best_<周起点>`（十分之一秒）与 `race_day_<北京日期>`（当日次数）：换日重置次数、换周重置本周最好且旧 key 保留；报名不动亲密/修为/道具/技能，也不写战报与 `pve_stage_progress`。`灵宠竞速榜` 用 `player_identity` 连接给出本周前三名（UID 标识）与自己的名次，空榜有说明行；`灵宠目标` 新增竞速行，帮助「对战与赛季」新增三条，`test_contract_audit.py` 把 `race`/`race_board` 纳入只读页面并登记 3 项内容，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_race.py` 21 项（内容与权重、赛道与地形校验负例、同日稳定与逐日轮换、用时确定且为正、更强伙伴用时更短、地形倍率真实生效、未结契只读、页面赛道/权重/预计用时/唯一入口、报名写成绩与精力与次数、慢成绩不覆盖最好、每日上限与次日重置、换周重置且保留历史、四类拒绝零写入、封存与派遣拒绝、不写战报/关卡进度/亲密/道具、双人榜名次与本人名次、空榜与参数拒绝、未结契榜只读、目标/帮助/解析、重启持久、QQ 按钮与蓝字分离）。聚焦 10 个文件 `269 passed`，另跑心境/专精/连携/传功/收集榜/今日秘境/竞技/劫境/禁地/战报批次 `153 passed`；`compileall` 与 `git diff --check` 通过。提交 `aeca0a2` 已推送 develop，develop CI `41031427040` 全绿（2754 项），fast-forward 合入 main 后 main CI `41031961694` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠研习（2026-10-30，已完成）

竞速交付后审计发现两个已交付系统被同一个门槛卡住：熟练度只能在战斗里积累（每次有效释放 +5，升阶需要 20/50/100/180），而 `灵宠专精` 要求灵术 3 级、`灵宠传功` 交给徒弟的是一门 1 级 0 熟练度的复制——不打满 120 熟练度，专精根本无法使用。本切片新增「灵宠研习」：消耗精力与灵粮，为当前出战伙伴已携带的一门灵术积累熟练度。

数值只有 `rules.json` 的 `research`（12 精力、1 灵粮、+8 熟练度、每日 4 次、每宠每日 2 次），`ResearchRule` 校验区间与「每宠上限不得超过每日上限」。升阶算术抽成 `mastery.study`，与 `award_mastery` 共用同一套进位逻辑，因此研习与实战的升级完全一致：首版测试确认 1 级 18 熟练度再研习会变成 2 级 6 而非 2 级 0，且 3 级达成时会提示可以去 `灵宠专精` 选这门灵术。状态只有 `quest_progress` 的 `research_day_<北京日期>` 与 `research_<北京日期>_<宠物编号>`，日期写在键里所以两个上限都随换日自动重置。

实现中修掉两处真实缺陷：（一）每宠计数最初写成 `research_<宠物编号>`，不含日期，导致一只伙伴用过 2 次后**永久**不能再研习，测试 `test_both_counters_reset_the_next_day` 抓到后改为日期前缀键；（二）`灵宠研习` 别名漏进 `COMMANDS`，`_parse` 返回 `None`，命令只能靠内部 id 调用，已补上并纳入解析断言。页面逐门列出已携带灵术的等级/熟练度/收益/可升至等级并只给可研习行挂蓝字，未携带或未学会也会明确拒绝；`灵宠目标` 新增研习行，帮助「灵物与灵术」新增两条，`test_contract_audit.py` 把 `research` 纳入只读页面，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_research.py` 19 项（规则与校验负例、未结契只读、无携带灵术文案、页面收益与可升等级、研习收益与双扣费、进位不跳级、3 级提示专精、满级拒绝、未携带/未学会/未知拒绝、精力与灵粮不足零写入、派遣拒绝、每宠上限不阻塞他人、每日上限第 5 次拒绝、换日重置、不写战报与玩家状态、目标/帮助/解析、同操作重放、QQ 按钮与蓝字分离）。聚焦 10 个文件 `236 passed`，另跑专精/连携/传功/心境/竞速/技能预设/灵术赏/飞升/图鉴试炼/劫境批次 `172 passed`；`compileall` 与 `git diff --check` 通过。提交 `2a6ebf7` 已推送 develop，develop CI `41037147250` 全绿（2773 项），fast-forward 合入 main 后 main CI `41037915301` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠擂台（2026-10-30，已完成）

研习交付后审计确认：所有战斗模式都在每场开始重建 `Fighter`，气血随之重置，于是「撑得住」的配置只在单场内有意义，没有任何玩法把续航当作核心资源。本切片新增「灵宠擂台」：五关连战、血量跨关延续、落败即止。

内容 `data/gauntlets.json` 五关（林间傀儡 → 古殿守卫 → 寒晶守灵 → 月影狼王 → 雷泽蛟灵），气血倍率 1.0/1.1/1.3/1.5/1.8、攻击 1.0/1.1/1.2/1.35/1.5，逐关奖励 60-220 修为与 80-320 灵石加材料，全清另给 300 修为/600 灵石/血脉精华 2；`domain/gauntlet_content.py` 校验倍率与奖励，`Catalog._validate_gauntlets` 校验敌手与物品存在。每次挑战每只出战伙伴各付 15 精力并进入共享 PVE 调息，逐关与全清奖励按周凭证发放。

关键实现：玩家一侧的 `Fighter` 只构建一次并在五轮里复用，`fight()` 原地修改 `hp`，因此血量天然跨关延续（测试通过对比第 1 关入场血量与满血值、并验证第 2、5 关入场血量递减来证明）。战报按 `operation_id` 去重，一次命令只能写一条记录，所以只记录**决定胜负的那一场**，键为 `gauntlet_<周>_<关卡>`，不写 `pve_stage_progress`。状态只有 `quest_progress` 的 `gauntlet_<周起点>_<序号>` 与 `_all`，换周自动重置。

新增 `tests/test_gauntlet.py` 19 项（内容与递增倍率、内容校验负例、未结契只读、页面五关/奖励/全清/入口、全清发放逐关与总奖励且精力只扣一次、血量跨关延续、中途落败只发已通关卡、首关失守零奖励、重复挑战不重复发奖、换周重置并可再次领奖、精力不足/派遣/调息三类前置拒绝、战报键与不写关卡进度、目标/帮助/解析、同操作重放、重启持久、QQ 按钮与蓝字分离）；`test_content.py` 新增未知敌手负例，`test_contract_audit.py` 把 `gauntlet` 纳入只读页面并登记内容 1 项。聚焦 10 个文件 `268 passed`，另跑劫境/禁地/团队试炼/回廊/守关/研习/竞速/心境/战报/关卡战绩批次 `164 passed`；`compileall` 与 `git diff --check` 通过。提交 `6ca9b7a` 已推送 develop，develop CI `41180344200` 全绿（2793 项），fast-forward 合入 main 后 main CI `41180563564` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠符印（2026-10-31，已完成）

擂台交付后审计确认：所有养成资源都要用材料换（装备、淬魂、熟练度、专精），没有一种加成是**由账号进度解锁**的，于是长期积累的成就、收集与羁绊从未转化为配装选择。本切片新增「灵宠符印」：八枚符印、每宠两槽、固定四维加成。

内容 `data/sigils.json` 八枚覆盖四类门槛（成就领取 1/5、收集 5/12 族、羁绊 3/5 级、境界 3/5），加成 18-55 点；`domain/sigil_content.py` 校验每项 0-60 且不可全零、门槛 kind 与 value，`Catalog._validate_sigils` 要求非空。解锁判定直接读既有派生数据（`claimed_count`、`collected_species`、`bond_levels.current_level`、`pet.realm`），不新增计数列。

状态是 `quest_progress` 的 `sigil_<伙伴编号>_<槽位>_<符印id>`（符印 id 放键里，`progress` 是整数列），前缀读取后解析槽位与符印；两个槽位独立，`装备` 校验已解锁/未重复/槽位未满/未派遣，`卸下` 校验该符印确实在该伙伴身上。加成在 `loadout.combatant` 中与装备、词条同层**固定相加**，不进入任何倍率，因此不会放大套装或专精。

实现中修掉一处真实缺陷：`灵宠符印` 别名未登记进 `COMMANDS`，`_parse` 返回 `None`（与研习切片同一类错误），测试 `test_objective_help_and_parse` 抓到后补上。页面逐条列出加成/解锁进度/状态并只给可执行行挂蓝字，`灵宠目标` 新增符印行，帮助「灵物与灵术」新增三条，`test_contract_audit.py` 把 `sigils` 纳入只读页面并登记 8 项内容，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

新增 `tests/test_sigils.py` 19 项（八枚内容与四类门槛、内容校验负例、未结契只读、页面加成/进度/状态、成就门槛 4→5 解锁、收集门槛按种族数解锁、羁绊门槛读宠物等级、境界门槛读宠物境界、装备写槽并精确加属性、两槽独立、第三枚被拒、未解锁与重复拒绝、未装备卸下拒绝、派遣拒绝、逐宠隔离、目标/帮助/解析、同操作重放、重启持久、QQ 按钮与蓝字分离）。聚焦 10 个文件 `268 passed`，另跑擂台/研习/竞速/心境/专精/连携/传功/套装/共鸣/劫境批次 `157 passed`；`compileall` 与 `git diff --check` 通过。提交 `aef8bab` 已推送 develop，develop CI `41195480145` 全绿（2812 项），fast-forward 合入 main 后 main CI `41195762917` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠护送（2026-10-31，已完成）

符印与 `v0.1.3` 发布后审计确认：所有 PVE 模式都是「杀光敌人」——秘境/关卡/塔/回廊/守关/禁地/团队试炼/图鉴试炼/劫境/擂台，没有任何玩法要求玩家**保护**一个单位，于是嘲讽、治疗与防御只作为减伤手段存在。本切片新增「灵宠护送」：护送目标加入我方，必须活着走完全部波次，报酬按它剩余血量分级。

内容 `data/escorts.json` 三处任务（药囊运送 15 精力 2 波 / 寒晶引路 18 精力 2 波 / 蛟道护行 22 精力 3 波），目标气血 260/420/620，满评与部分两档奖励；`domain/escort_content.py` 校验波次规模、敌手引用与「满评不低于部分」，`Catalog._validate_escorts` 校验敌手与物品存在。实现上护送者就是 `Fighter.create` 造出的普通单位，追加到玩家一侧，`fight()` 原地改 `hp` 使跨波延续自然成立，引擎零改动。

胜负条件是 `winner == 0` **且** 目标 `hp > 0`；全波清完按目标剩余血量分级（≥50% 满评、存活但不足 50% 部分评价、倒下或战败不发奖）。状态为 `quest_progress` 的 `escort_<周起点>_<任务id>`（1/2 评级），首次部分评价发部分奖励、之后满评只补差额（逐字段 `full - partial`），因此早打不吃亏且不重复发奖；换周自动重置。战报只记决定胜负那一场（`pve_stage`、`escort_` 键），不写 `pve_stage_progress`。

实现中第三次踩到同一类缺陷：`灵宠护送` 别名未登记进 `COMMANDS`，`_parse` 返回 `None`，`test_objective_help_and_parse` 抓到后补上——该检查已写入交付技能，后续新命令必须先加别名再写测试。

新增 `tests/test_escort.py` 20 项（三处任务与精力/波次/奖励档位、奖励倒挂校验负例、未结契只读、页面目标/波次/两档奖励/评级、满评发全额并扣精力、目标血量跨波延续、受损目标只得部分、之后满评只补差额、目标倒下失败零奖励、战败提前结束、满评不重复发奖、换周重置并可再次满评、精力不足零写入、派遣与调息拒绝、战报键与不写关卡进度、快照含护送目标、目标/帮助/解析、同操作重放、重启持久、QQ 按钮与蓝字分离）。聚焦 10 个文件 `269 passed`，另跑擂台/符印/研习/竞速/心境/劫境/禁地/守关/回廊/战报批次 `176 passed`；`compileall` 与 `git diff --check` 通过。提交 `dc73fc5` 已推送 develop，develop CI `41270630897` 全绿（2832 项），fast-forward 合入 main 后 main CI `41270866754` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠易脉（2026-11-01，已完成）

护送交付后审计确认：元素是唯一终生不可改的配装轴——它同时决定灵术门槛、装备门槛与克制关系（`compatibility.check_requirements`、`combat.effectiveness`），而玩家没有任何手段为一只伙伴换掉它，抽到的伙伴只能按物种给定的元素使用。本切片新增「灵宠易脉」：消耗灵石与血脉精华把伙伴本命改写成另一种基础元素。

内容 `data/attunements.json` 八项基础元素（金木水火土风雷毒，360-520 灵石 + 2-3 份血脉精华），周限写在 `rules.json` 的 `attunement.weekly_limit`；`domain/attunement_content.py` 校验目标非空与字段，`Catalog._validate_attunements` 强制基础元素（拒绝冰这类派生元素）、不重复、材料存在。生效方式是覆盖：`attunement.elements_of/primary_of` 返回覆盖值或物种默认，`loadout.combatant`、`compatibility.check_requirements` 与战报快照三处同读这一份，战斗与门槛不会再分叉。

安全边界是这次实现的重点：改属前先检查已穿戴装备，只要有一件不再兼容就整次拒绝并列出需先卸下的部件（避免出现穿不上的存档）；改属后自动卸下不再兼容的灵术并点名。状态为 `quest_progress` 的 `attune_<伙伴编号>_<元素>` 与 `attune_week_<周起点>_<伙伴编号>`，不新增表列；灵石、材料、周限、派遣、封存、同元素任一不满足都整笔拒绝且零写入。

新增 `tests/test_attunement.py` 20 项（八项基础元素与周限、内容校验负例、未结契只读、页面元素/费用/本周次数、改属后 `Fighter` 元素与主元素、扣费与材料、不兼容灵术自动卸下、已穿戴不兼容装备整次拒绝且零写入、同元素拒绝、周限拒绝与跨周重置、灵石/材料不足零写入、派遣拒绝、未知伙伴/元素/格式拒绝、克制表变化、目标/帮助/解析、同操作重放、重启持久、QQ 按钮与蓝字分离）。聚焦 10 个文件 `269 passed`，另跑护送/符印/擂台/对战/套装/战报/论剑/防守/劫境/回廊/淬魂/技能预设批次 `208 passed`；`compileall` 与 `git diff --check` 通过。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠阵位（2026-11-01，已完成）

易脉与 `v0.1.4` 发布后审计确认：全服所有加成都是纯增益（符印、淬魂、装备、词条、套装、共鸣、师门、助战、心境只减不加），玩家从来没有「用一维换另一维」的选择，配装差异只体现在堆了多少而不体现在堆成什么形状。本切片新增「灵宠阵位」：出战阵容的三席各有取舍。

内容 `data/formations.json` 三处阵位（前锋 气血+18%/防御+22%、攻击−12%/速度−8%；中军 攻击+10%/防御+4%、气血−4%；后援 攻击+16%/速度+10%、防御−10%/气血−6%），`domain/formation_content.py` 强制四维齐全、0.5-1.8 区间，并要求每个位置至少一项增益与至少一项代价，`Catalog._validate_formations` 要求恰好三个位置。生效点放在 `loadout.combatant` 与心境同一处：只缩放基础四维，之后才叠加固定加成，因此装备/词条/套装/符印/羁绊的整数不变（测试用「穿武器后攻击 = 基础×倍率 + 武器固定攻击」证明）。

状态是 `quest_progress` 的 `formation_<伙伴编号>_<位置>` 单行，换位先删后写；没有该行即未布阵，未布阵伙伴的行为与既有基线完全一致。`assign` 只校验本人、未封存、属于当前出战阵容、位置存在、不与当前位置相同，全部免费且不占调息，因此不存在资源扣减路径，也就没有部分写入。

新增 `tests/test_formation.py` 16 项（三处阵位与取舍约束、只加不减/只减不加负例、未结契只读、页面阵容与三个位置、基础四维按倍率放大、固定加成保持原值、换位只留一行、重复布阵拒绝、未布阵保持基线、阵容外伙伴拒绝、封存与未知伙伴/位置/格式拒绝、目标/帮助/解析、同操作重放、重启持久、QQ 按钮与蓝字分离）。聚焦 10 个文件 `259 passed`，另跑易脉/护送/符印/目录/对战/套装/战报/论剑/防守/淬魂/助战/专精批次 `244 passed`；`compileall` 与 `git diff --check` 通过。提交 `6cc8f93` 已推送 develop，develop CI `41275306087` 全绿（2868 项），fast-forward 合入 main 后 main CI `41275565074` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠同心（2026-11-01，已完成）

阵位与 `v0.1.5` 发布后审计确认：所有加成都属于单只伙伴或整个账号，伙伴之间没有任何关系，阵容只是「最强的三只」的集合。本切片新增「灵宠同心」：两位伙伴互为同心，只有同时出战时才获得加成。

数值写在 `rules.json` 的 `pair_bond`（300 灵石 + 1 血脉精华、亲密 ≥ 60、攻击 +8%/防御 +6%/速度 +4%），`PairBondRule` 校验区间 0-0.5 并强制「至少一条加成、至少一份成本」。状态是一行对称凭证 `bonded_<小编号>_<大编号>`，让「每位伙伴只有一位同心」成为键的约束而不是额外校验；解契删除该行、免费、不退款。

生效点在 `loadout.combatant`：`rate_of()` 仅在双方都在当前出战阵容时返回倍率，因此把伙伴换下、封存或换人后加成立即消失，重新同阵即恢复——这是本切片与纯属性层的区别，测试用「同阵/单独出战两种阵容的攻击差」和「穿武器后固定加成不变」两处证明。亲密度上限为 100（数据库约束），门槛 60 留出足够余量。

新增 `tests/test_pair_bond.py` 17 项（规则接线与零成本/空加成/越界倍率负例、未结契只读、页面候选与成本、结契写一行且只扣一次费、双方互为同心、加成只在同阵生效、固定加成保持原值、第二段同心被拒、阵容外拒结、亲密/灵石/材料不足整笔拒绝、同宠与未知伙伴与格式拒绝、解契清空双方且不退费、未结契解契拒绝、目标/帮助/解析、同操作重放、重启持久、QQ 按钮与蓝字分离）。聚焦 11 个文件 `276 passed`，另跑易脉/护送/符印/目录/对战/套装/战报/论剑/防守/淬魂/助战/共鸣批次 `231 passed`；`compileall` 与 `git diff --check` 通过。提交 `9e17c5c` 已推送 develop，develop CI `41284834030` 全绿（2885 项），fast-forward 合入 main 后 main CI `41285094049` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠出战预设（2026-11-01，已完成）

同心与 `v0.1.6` 发布后审计确认：切换阵容是最高频的战前动作，但每次都要重打三只编号；技能有预设、阵容没有。本切片补齐「灵宠出战预设」：三套槽位，一键切换。

状态是 `quest_progress` 的 `lineup_preset_<n>` 标记加每位成员一行 `lineup_preset_<n>_<编号>`，成员不走「1 2 3」字符串，避免解析与位序问题。`保存` 先清该槽再写快照、不改当前阵容；`应用` 先复核每只伙伴仍属本人、未封存、未在派遣、种类不重复、数量 1-3，通过后调用 `repo.set_active_pets` 并取消组队准备；`清除` 只删该槽。任一复核失败整份拒绝且零写入，所以过期预设不会把玩家带进非法阵容。

实现中修掉一处真实缺陷：`灵宠目标` 的计数最初写成 `quest_id LIKE 'lineup_preset_%' AND NOT LIKE 'lineup_preset_%_%'`，但 `%_%` 会在 `lineup_preset_1` 的自带下划线上匹配，导致标记行被排除、页面永远显示「尚未保存」；测试抓到大后改为直接统计非空槽位。另修一处自身测试假设错误（初次召唤同族导致阵容重复种类被拒），改为按不同种族插入伙伴。

新增 `tests/test_lineup_presets.py` 16 项（未结契只读、三槽空态、保存不改当前阵容、空阵容与越界槽拒绝、应用切换、应用当前阵容为无操作、空槽拒绝、封存/派遣/已删除成员拒绝且零写入、清除只影响该槽、覆盖保存替换成员、目标/帮助/解析、同操作重放、重启持久、QQ 按钮与蓝字分离）。聚焦 11 个文件 `276 passed`，另跑易脉/护送/符印/同心/阵位/论剑/防守/团队试炼/技能预设/封存批次 `177 passed`；`compileall` 与 `git diff --check` 通过。提交 `44e491f` 已推送 develop，develop CI `41287278356` 全绿（2901 项），fast-forward 合入 main 后 main CI `41287596829` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠归灵（2026-11-01，已完成）

出战预设与 `v0.1.7` 发布后审计确认：伙伴只进不出，重复召唤的伙伴除了封存没有去处，封存只是永远留在库里，名册名额被占满后玩家只能反复封印。本切片新增「灵宠归灵」：按境界回收材料并释放名额。

审计同时发现一个硬约束：**不能**真的 `DELETE FROM pets`。`active_pet_slots`、`equipment`、`learned_skills`、`expeditions`、`teams`、`pvp_results` 与 `players.active_pet_id` 都引用 `pets`，删除会破坏战报与既有引用，因此实现是软退役：`archived=1` 加永久标记 `released_<伙伴编号>`。名册按 `archived=0` 计数，于是名额自然释放；`released_` 标记让封存库、`灵宠复原` 与归灵页把该伙伴视为已消失，而名册行与战报完好。

数值写在 `rules.json` 的 `pet_release`（`stones_base` 200、`stones_per_realm` 120、血脉精华 1），`PetReleaseRule` 拒绝零收益配置；收益按境界线性增长并附该族灵卵。因为不可撤销，`灵宠归灵 <伙伴>` 只预览，`确认` 才执行；仍在阵容、派遣中、有同心、已飞升、最后一只都被拒绝且零写入。归灵不发修为——`grant` 的修为只会加到当前出战伙伴，与退役对象无关，因此奖励里刻意去掉修为，避免语义错位与额外的空闲校验。

新增 `tests/test_pet_release.py` 18 项（规则接线与零收益负例、未结契只读、候选与收益、阵容内伙伴被阻、裸命令只预览不写入、确认后退役并按境界发奖、收益随境界增长、释放名额、未知/格式/派遣拒绝零写入、同心需先解、已飞升拒绝、封存库与复原拒绝已归灵、最后一只拒绝、名册行与战报保留、目标/帮助/解析、同操作重放、QQ 按钮与蓝字分离）。聚焦 10 个文件 `217 passed`，另跑出战预设/易脉/护送/符印/阵位/多宠阵容/阵容就绪/目录/对战批次 `220 passed`；`compileall` 与 `git diff --check` 通过。提交 `3589aac` 已推送 develop，develop CI `41289484664` 全绿（2919 项），fast-forward 合入 main 后 main CI `41289768702` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema、未删除任何玩家数据、未创建新 Release tag。

### 灵宠轮作（2026-11-01，已完成）

归灵与 `v0.1.8` 发布后审计确认：灵田没有「种什么」的长期取舍，同一田位连作与轮换收益完全相同，玩家只会一直种最划算的一种。本切片新增轮作：某田位本季作物与上一季不同时，收获的修为、灵石与材料全部 +20%。

数值在 `rules.json` 的 `farm_rotation.rate_percent`（1-100，`FarmRotationRule` 校验）。状态复用 `quest_progress`：`farm_last_<田位>_<作物id>` 记录最近收获的作物、`farm_rotation_<田位>` 标记本季是否换种；播种时判定并写标记，收获（含枯萎、含原地补种）时更新上一季并清标记，加成窗口恰好覆盖一季。倍率在 `_grant_reward` 内逐项取整，枯季只返种子不参与倍率；加成逐田独立。

实现中发现两处必须处理的边界。其一，把提示直接拼进既有行尾会让农场既有测试的整行断言失效，也违反「行文本稳定」的页面习惯，因此改为独立提示行（待播种时显示上一季与可得加成，生长/成熟时单独一行标出加成）。其二，`灵宠灵田` 的「查看种子」蓝字与按钮 `灵宠商店` 同名，发送层会裁掉其中一个，导致按钮集合与页面命令不一致；改为纯文本提示，使命令与蓝字保持零重叠。既有 `test_farm2` 的收获数值断言原本写死旧行为（120/150），按新规则第二季换种应有加成，已更新为按倍率计算并保留原语义。

新增 `tests/test_farm_rotation.py` 14 项（规则接线与越界负例、首播无加成、换种触发加成与实际产出倍率、连作无加成、枯季记为上一季、原地补种开新一季、页面提示、窗口关闭、逐田独立、重启持久、帮助/解析、同操作重放、QQ 按钮与蓝字分离）。聚焦 11 个文件 `245 passed`，另跑归灵/出战预设/同心/阵位/易脉/护送/战令/每日任务/周常/每日特供批次 `161 passed`；`compileall` 与 `git diff --check` 通过。提交 `9deb0f8` 已推送 develop，develop CI `41293911594` 全绿（2933 项），fast-forward 合入 main 后 main CI `41294210131` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠契约（2026-11-01，已完成）

轮作与 `v0.1.9` 发布后审计确认：秘境是固定赌注——难度与报酬都由内容决定，强者没有可冒的风险，弱者也没有「以安全换价值」的余地。本切片新增「灵宠契约」：三种自选约束（独行/速战/无伤），达成才在基础奖励之上追加额外奖励。

内容 `data/contracts.json` 三条：独行（只带一只，+50% 灵石/修为与锻灵矿 1）、速战（8 回合内结束，+30% 与血脉精华 1）、无伤（全员存活，+40% 与灵粮 2）；`domain/contract_content.py` 强制 `speed` 必须带 `rounds` 且其它类型不得带，`ContractBonus` 要求至少一项收益，`Catalog._validate_contracts` 校验物品存在。

实现刻意不改秘境：`adventure.run_dungeon` 增加可选 `return_state=True`（默认路径不变），额外返回战斗与玩家侧 `Fighter`，契约据此判定 `winner`、`rounds` 与存活；基础奖励、精力、调息、熟练度、战报全部走原路径，契约奖励在结算后追加。独行在扣精力前校验出战人数，避免「先扣精力再报错」；组队秘境直接拒绝。额外奖励按该秘境基础奖励百分比整数向下取整，叠加固定物品，两部分可分别核对。

新增 `tests/test_contracts.py` 16 项（三条契约与 kind/rounds 约束、空奖励负例、未结契只读、页面条件与奖励与目标、组队秘境排除、独行人数不足零扣精力、达成时基础+额外、契约物品到账、未达成只结算基础、战败不发额外、未知契约/秘境/格式拒绝、组队秘境拒绝、百分比计算确定性、目标/帮助/解析、同操作重放、QQ 按钮与蓝字分离）。聚焦 10 个文件 `230 passed`，另跑轮作/归灵/出战预设/同心/阵位/易脉/护送/对战/战报/首通批次 `158 passed`；`compileall` 与 `git diff --check` 通过。提交 `cbec079` 已推送 develop，develop CI `41296055607` 全绿（2949 项），fast-forward 合入 main 后 main CI `41296362604` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠杂交（2026-11-01，已完成）

契约与 `v0.1.10` 发布后审计确认：种子只有购买与掉落两个来源，低阶种子在解锁高阶作物后没有出口。本切片新增「灵宠杂交」：两种不同种子各 1 个 + 灵石 → 一种灵坊不卖的新种子。

内容层新增 2 个作物（霜纹麦 14400 秒、赤霄莲 18000 秒）与 2 个种子物品（均不设 `price`，因此不可购买），`data/hybrids.json` 声明两条配方（灵稻种+矿苗种→霜纹麦种 120 灵石；灵血草种+蕴灵穗种→赤霄莲种 260 灵石）。`domain/hybrid_content.py` 强制两个种子不同、产物不是输入；`Catalog._validate_hybrids` 校验输入/产物存在于物品表、产物是材料、且存在以它为种子的作物——三者缺一启动即失败，避免出现「配方产出一个不能种的种子」。

玩法层 `gameplay/hybrid.py`：页面逐条列出配方、消耗、产物收益与当前缺口，只给材料齐备的配方挂「杂交」蓝字；`brew` 先校验种子与灵石（任一不足整笔拒绝、零写入），再在同一事务内扣种子、扣灵石、加产物。杂交不占精力与调息、不写进度状态，重复提交由既有操作缓存去重。

新增 `tests/test_hybrid.py` 14 项（两条配方与产物可种、同种/自产负例、未结契只读、页面配方与可配状态、缺种子时不给入口、调配扣料与产出、产物不可购买、灵石不足零写入、种子不足零写入、未知配方拒绝、杂交产物可播种收获、目标/帮助/解析、同操作重放、QQ 按钮与蓝字分离）。聚焦 11 个文件 `243 passed`，另跑契约/归灵/出战预设/同心/阵位/易脉/护送/每日特供/道具闭环批次 `147 passed`；`compileall` 与 `git diff --check` 通过。提交 `e474055`（功能）与 `3aaa553`（把 `crops.json`/`items.json` 还原为原格式，只保留新增行）已推送 develop，develop CI `41301318689` 全绿（2963 项），fast-forward 合入 main 后 main CI `41301624406` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠炼丹（2026-11-01，已完成）

杂交与 `v0.1.11` 发布后审计确认：`recipes.json` 的 14 条配方全部是装备，丹药只能购买，玩家种出的作物与攒下的材料从未变成消耗品。本切片新增「灵宠炼丹」：按丹方把作物与材料炼成灵坊在售的丹药。

内容 `data/alchemy.json` 四条丹方（回元丹 灵粮 2+灵血草种 1+30 灵石；同心丹 灵血草种 1+灵粮 1+60；蕴灵丹 蕴灵穗种 1+锻灵矿 1+80；破境丹 血脉精华 1+古灵根种 1+120），`domain/alchemy_content.py` 用 `yield` 别名映射到 `yield_` 并拒绝「消耗自己的产物」，`Catalog._validate_alchemy` 校验产物与材料存在、产物必须是 `consumable`/`breakthrough`。

玩法层 `gameplay/alchemy.py`：页面列出丹方、效果、每份消耗与缺口，只给材料齐备的丹方挂「炼丹」蓝字；`brew` 用既有 `item_amount` 解析「丹方 [数量]」，份数上限沿用 99 的通用数量校验，材料与灵石按份数一次性校验，任一不足整笔拒绝零写入；成功后在事务内扣料、扣费、加产物。炼丹不占精力与调息、不写进度状态，重复提交由操作缓存去重。

实现中修正三处自身测试准备错误：多条丹方共享材料导致 `grant` 累加（改为先清空背包再按固定量发放）、用 `popitem()` 从 pydantic 模型里取材料键（改为按排序取第一个材料）、以及把「数量超限」用例写成 11（通用上限是 99，改为 100）。

新增 `tests/test_alchemy.py` 15 项（四条丹方与产物类型、自消耗负例、未结契只读、页面丹方与效果与消耗、缺料隐藏入口、炼制扣料与产出、批量线性放大、材料不足零写入、灵石不足零写入、批量不足整笔拒绝、未知丹方与超量拒绝、产物可服用、目标/帮助/解析、同操作重放、QQ 按钮与蓝字分离）。聚焦 11 个文件 `268 passed`，另跑契约/归灵/出战预设/同心/阵位/易脉/护送/每日特供/轮作/膳房批次 `170 passed`；`compileall` 与 `git diff --check` 通过。提交 `0520eab` 已推送 develop，develop CI `41303293666` 全绿（2978 项），fast-forward 合入 main 后 main CI `41303619705` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠试炼（2026-11-01，已完成）

炼丹与 `v0.1.12` 发布后审计确认：秘境的难度与奖励都由内容固定，玩家无法为同一个秘境主动加码；契约只能加约束、不能改敌人数值。本切片新增「灵宠试炼」：同一秘境三档难度，敌手四维与奖励同向放大。

内容 `data/difficulties.json` 三档（寻常 ×1.0 / +0%、挑战 ×1.25 / +50%、绝境 ×1.6 / +120%），`domain/difficulty_content.py` 拒绝「只加奖励不加数值」与「只加数值不加奖励」，`Catalog._validate_difficulties` 要求存在基准档。缩放实现在 `adventure.run_dungeon` 的两个可选参数 `enemy_scale` 与 `reward` 上：前者用 `model_copy` 生成缩放后的 `Enemy`（内容目录本身不变，测试对比前后定义相同），后者传入放大的 `Reward`；默认值让所有既有调用方行为不变。

玩法层 `gameplay/difficulty.py`：页面按秘境列出三档倍率与逐项奖励区间，只给有加成的档位挂「挑战」蓝字；`run` 校验秘境非组队、档位非基准（基准档直接指向 `灵宠挑战`），随后走同一条秘境结算路径并追加一行说明档位。精力、调息、掉落、熟练度与战报均复用原逻辑。

新增 `tests/test_difficulty.py` 14 项（三档内容与基准档、单边档位负例、未结契只读、页面倍率与奖励与入口、奖励按档放大、强化档收益不低于基础、基准档拒绝、组队拒绝、未知秘境/档位/格式拒绝、缩放不修改内容定义、缩放后敌手更强、目标/帮助/解析、同操作重放、QQ 按钮与蓝字分离）。聚焦 11 个文件 `235 passed`，另跑炼丹/杂交/归灵/出战预设/同心/阵位/易脉/护送/擂台/回廊批次 `175 passed`；`compileall` 与 `git diff --check` 通过。提交 `65924e4` 已推送 develop，develop CI `41310995511` 全绿（2992 项），fast-forward 合入 main 后 main CI `41311319341` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 新系统成长记录（2026-11-01，已完成）

难度档与 `v0.1.13` 发布后审计确认：杂交、炼丹、契约、强化通关与归灵都不产生任何成就/称号痕迹——它们即时结算、不写进度状态，`_metric` 里也没有对应指标，因此这些系统玩得再多，成就页与称号页仍是空白。本切片补齐这条链路。

新增 `gameplay/counters.py`：`stat_<指标>` 单调计数器（`quest_progress` 行，`progress` 即次数），`bump()` 只在成功路径调用，`value()` 供指标读取。四处接入：杂交成功后 `hybrid_brews`、炼丹成功后 `alchemy_brews`、契约达成（获胜且约束成立）后 `contracts_met`、强化档通关后 `hard_clears`；归灵不新增计数器，直接由 `released_<伙伴编号>` 标记派生 `pets_released`。

`AchievementMetric` 白名单扩入五个新指标（成就、称号、主线、日常四类内容共用同一白名单），并新增 7 个成就与 2 个称号（含目标 10 次的「丹道初窥」与 8 次的「踏破绝境」）。这些指标无上限，因此不进入 `_metric_ceilings()`。计数只在成功路径累加：材料/灵石不足、契约未达成、战败都不计数；同一条消息重投由操作缓存短路，因此不会重复计数（有专门的回归用例）。

同时把四处写死数量的既有测试改为从内容推导：`test_titles` 的 25 个称号与 `1/5` 分页、`test_objectives` 的 `1/25`、`test_achievement_interaction` 的 77 条与 17 页。这类断言在下一次扩充内容时必然失效，改为 `len(game[0].content.*)` 后不会再因新增条目而断。数据文件仍按原格式追加（`achievements.json` 是单行紧凑格式、`titles.json` 是缩进格式），避免整文件重排。

新增 `tests/test_progress_counters.py` 11 项（新成就与称号存在、计数器从零单调增长、炼丹计数一次、失败不计数、重投不重复计数、杂交只计自己的指标、首次炼丹解锁成就、领奖只发一次、10 次解锁称号、归灵由标记派生、计数器重启后仍在）。聚焦 11 个文件 `251 passed`，另跑炼丹/杂交/契约/难度/归灵/战令/成就商店/名次奖励批次 `117 passed`；`compileall` 与 `git diff --check` 通过。提交 `57beb91`（功能）与 `93eaf57`（把五处写死的成就/称号数量改为从内容推导）已推送 develop，develop CI `41314656051` 全绿（3003 项），fast-forward 合入 main 后 main CI `41314978360` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档、未创建新 Release tag。

### 灵宠赏金（2026-11-01，已完成）

成长记录切片后审计确认：`daily_assignments` 的 12 条只覆盖秘境、论剑、奇闻与派遣，且是「三选一、每天领一份」；杂交、炼丹、契约与强化通关虽有计数器，却没有任何日常出口。本切片新增「灵宠赏金」：每日轮换三份、各自独立领取的新系统悬赏。

`counters` 扩展日维度：`bump()` 除单调总量外同时累加 `stat_<指标>_day_<北京日期>`，新增 `today_value()` 读当日值，`value()` 保持读总量。内容 `data/bounties.json` 五条（杂交 1 次、炼丹 1 次、炼丹 2 次、契约 1 次、强化通关 1 次），`domain/bounty_content.py` 用 Literal 限定四个新指标，`Catalog._validate_bounties` 要求池内至少三条并校验物品。

玩法层 `gameplay/bounty.py`：`todays()` 以日序数取模开窗，同一天稳定、跨日整体前移；`page` 逐份列出进度/目标/奖励/状态，只为「已达成且未领取」挂蓝字；`claim` 校验今日在册、未领取、进度达标，随后写 `bounty_<日期>_<id>` 凭证并发放奖励。既有每日课题的三选一逻辑未改动，两套日常互不影响。

新增 `tests/test_bounty.py` 16 项（池覆盖四个新指标、未结契只读、三份且当日稳定、跨日轮换、进度只读当日、未达标拒绝、领取发奖并写凭证、重复领取拒绝、三份独立领取、非今日赏金拒绝、未知与格式拒绝、重投一致、真实炼丹推进并领取、目标/帮助/解析、日计数重启后仍在、QQ 按钮与蓝字分离）。聚焦 11 个文件 `240 passed`，另跑契约/难度/归灵/出战预设/同心/阵位/易脉/护送/成就/称号/目录/终局批次 `236 passed`（其中含上一轮 CI 抓到的五处数量断言，已改为从内容推导）；`compileall` 与 `git diff --check` 通过。提交 `a60c183` 已推送 develop，develop CI `41393288933` 全绿（3019 项），fast-forward 合入 main 后 main CI `41393735439` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠贡献兑换（2026-11-02，已完成）

赏金与 `v0.1.14` 发布后审计确认：门派贡献只能往上堆——`sect_contrib_<id>` 同时充当阶位来源与唯一数值，满阶后每日修行继续加数却买不到任何东西，是全服唯一「只进不出」的货币。本切片新增「灵宠贡献兑换」：贡献可花，阶位不掉。

内容 `data/sect_exchange.json` 五条报价（灵粮 20/5、锻灵矿 40/3、回元丹 60/2、蕴灵丹 90/2、血脉精华 120/1，格式为 贡献/每周库存），`domain/sect_exchange_content.py` 校验区间，`Catalog._validate_sect_exchange` 要求表非空、物品存在、同一物品不重复报价。

关键设计是把「阶位来源」与「可花余额」拆开：`sect_contrib_<id>` 仍是总贡献，新增 `sect_spent_<id>` 记已用，可用贡献取差值，因此兑换不会降阶、不会削弱被动、也不影响已领阶位奖励；周库存写成 `sect_exchange_<周一零点>_<报价id>`，换周自动重置而已用贡献保留。`redeem` 先校验门派、库存与余额（含数量 1-5），再同一事务内加已用、加周计数、发物品。

新增 `tests/test_sect_exchange.py` 18 项（五条报价唯一、未结契只读、未拜入提示、页面成本/库存/余额、师门页显示可用贡献、兑换扣余额但阶位不变、批量线性、余额不足零写入、周库存上限、跨周重置且已用保留、超库存拒绝、数量上限、未拜入与未知报价拒绝、非表内物品拒绝、重投一致、目标/帮助/解析、已用贡献重启后仍在、QQ 按钮与蓝字分离）。聚焦 11 个文件 `252 passed`，另跑成就/称号/目录/终局/套装里程碑/灵术赏/阵位/同心/难度/契约批次 `174 passed`；`compileall` 与 `git diff --check` 通过。提交 `847ceb4` 已推送 develop，develop CI `41397372866` 全绿（3037 项），fast-forward 合入 main 后 main CI `41397764299` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠战意（2026-11-02，已完成）

贡献兑换之后审计确认：阵位、同心、淬魂、符印全都在改四维，后期数值饱和后每加一层都几乎无感，且没有任何一层作用于「伤害乘区」。本切片新增「灵宠战意」：四维不动，改输出与承伤。

引擎侧做了最小侵入：`Fighter` 增加 `dealt`/`taken` 两个默认 1.0 的乘区，`combat.scale_damage()` 在单体（`_act`）与群体（`_attack_all`）两条路径上统一应用，二者都为 1.0 时原样返回，因此既有战斗结果逐位不变（战斗批次 203 项全绿即为证）；`Fighter.create` 拒绝 0.25-2.5 之外的值。

内容 `data/intents.json` 三档（强攻 1.16/1.14、守势 0.86/0.84、游斗 1.08/1.05），`domain/intent_content.py` 用同向移动规则拒绝纯增益与纯亏损，`Catalog._validate_intents` 要求非空且名称唯一。玩法层 `gameplay/intent.py` 以「一档一行」存 `intent_<用户>_<战意id>`，切换先删后写、重选同一档不写库、清除删行；`loadout.combatant` 读取后填入乘区，敌方不受影响。

新增 `tests/test_intent.py` 18 项（默认 1.0、越界拒绝、`scale_damage` 恒等与双向应用、下限 1 点、真实战斗中守势确实减伤、三档均为同向移动、未结契只读、页面列出全部档位、选择后持久化、重选不写库、换档只留一行、清除与空清除拒绝、未知与格式拒绝、乘区进入 Fighter、目标/帮助/解析、重启后仍在、QQ 按钮与蓝字分离）。聚焦 11 个文件 `253 passed`，另跑战斗/竞技/秘境/冒险/难度/阵位/同心/易脉/契约/护送/天赋批次 `203 passed`；`compileall` 与 `git diff --check` 通过。提交 `6d88154` 已推送 develop，develop CI `41401630539` 全绿（3055 项），fast-forward 合入 main 后 main CI `41402077543` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠镶嵌（2026-11-02，已完成）

战意之后审计确认：装备只有强化、洗词条与套装三种出口，玩家无法决定某一格贡献哪项属性；`equipment` 表按 `(pet_id, slot)` 存放且槽位固定为兵刃/护甲/灵饰，没有多余列。本切片把三个槽位变成镶嵌位。

关键决定是不改 schema：宝石写成普通 `material` 物品（四件），槽位状态存 `quest_progress` 的 `socket_<宠物id>_<槽位>_<宝石id>`，行归属玩家（该列是外键）、宠物 id 在键内，因此「一槽一颗」由主键结构保证。宝石绑定槽位而非装备，换装不脱落，也就不必改装备/卸下逻辑。

`domain/gem_content.py` 限定四属性与 0.01-0.25 的倍率，`Catalog._validate_gems` 要求四颗各对应不同属性且消耗物必须是材料。`gameplay/sockets.py` 提供页面、镶嵌与卸下：镶嵌前依次校验槽位有装备、槽位未占、背包有宝石，然后在单个事务里扣物品写行；卸下先删行再返还物品。`loadout.combatant` 在阵位之后按基础值乘算，未镶嵌时属性与旧版逐位一致。

新增 `tests/test_sockets.py` 16 项（四宝石四条不同属性、未结契只读、页面列出槽位装备与可镶宝石、镶嵌扣一颗并提升属性、加成符合声明倍率、空格位拒绝、已占拒绝、宝石不足拒绝且零写入、未知槽位/未知宝石/格式拒绝、卸下返还、空槽卸下拒绝、换装后宝石仍在、重启后仍在、重投不重复扣费、目标/帮助/解析、QQ 按钮与蓝字分离）。聚焦 10 个文件 `232 passed`，另跑商店/制作/锻造/回收/成就/图鉴/终局/成长/炼丹/阵位批次 `217 passed`；`compileall` 与 `git diff --check` 通过。首轮 develop CI `41420587753` 在 `test_item_loop.py` 抓到两处把商店页数写死为 11 的断言（新增四件材料后为 12 页），按既有约定改为由内容推导（`shop_pages()`），修正提交 `55fc5ec`；develop CI `41421527440` 全绿（3071 项），fast-forward 合入 main 后 main CI `41422110754` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 schema 与玩家存档。

### 灵宠双线派遣（2026-11-02，已完成）

镶嵌之后审计确认：`expedition_start` 用「存在任何进行中行程」拒绝再次出发，数据库还叠了 `expedition_running_player` 部分唯一索引，因此每人同时只能跑一条委托——这是剩余吞吐量最大的缺口，也是唯一需要动 schema 的功能。

本切片把 schema 升到 21：`expeditions` 追加 `slot INTEGER NOT NULL DEFAULT 0 CHECK (slot IN (0, 1))`，删除 `expedition_running_player`，改为 `expedition_running_slot (user_id, slot) WHERE state='running'`；`expedition_running_pet` 保留，因此「一条线一条行程」与「一只伙伴一条行程」都由索引保证。迁移沿用既有模式：`legacy_schema20()` 重建旧结构供 `validate_schema20` 比对，`backup_schema20()` 在写库前留底，`migrate_expedition_slots()` 只做加列与换索引，随后 `validate_schema21` 与 integrity/foreign-key 检查，任何一步失败都回滚并保留原库。旧的进行中行程迁移后落在 slot 0。

玩法层：`rules.json` 新增 `expedition_lines`（2 条、3000 灵石）与 `ExpeditionLinesRule`；`unlocked_lines()` 读 `expedition_lines_<用户>` 凭证，`open_line()` 一次性扣费并写凭证（重复开辟命中「已经开辟」，灵石不足零写入）；`start()` 改为按空闲槽位分配，两条线都满时给出明确拒绝。`灵宠行程` 无参数时变成两线总览：逐行给出伙伴、委托、剩余时间、行程号，外出中的行同时挂「提前召回」与「加急完成」（保留加急费用文案），已完成行挂「领取归来奖励」，未开辟时补「开辟委托线」。`灵宠行程 <行程号>` 的详情页保持不变。

新增 `tests/test_expedition_lines.py` 13 项（新建库含 slot 列与按线索引、20→21 迁移留底并换索引、迁移后旧进行中行程落在 slot 0、未开辟时第二次派遣被拒、开辟扣费且只扣一次、灵石不足零写入、两只伙伴分占两线、第三条拒绝、同一只伙伴不能占两线、两线独立结算与领取、总览列出两线与下一步、未开辟时总览给开辟入口、QQ 按钮与蓝字分离）。同时更新两处既有测试到新不变量：存储层改为断言按线唯一索引并验证「同线拒绝/异线允许/同宠拒绝」，总览页保留加急文案与入口。派遣批次 349 passed，命令/目标/内容/运行时/目录/道具循环批次 182 passed；`compileall` 与 `git diff --check` 通过。首轮 develop CI `41432059851` 在 19→20 迁移用例暴露一个真实缺陷：18/19 旧结构fixture 由当前 schema 推导，因此已带上 schema 21 的新索引，与迁移后的结构不匹配；改为先用 `legacy_schema20()` 还原 20 代基础再剥离旧列，并把写死的 `user_version == 20` 改为从 `SCHEMA_VERSION` 推导，修正提交 `c097184`；develop CI `41433204049` 全绿（3085 项），fast-forward 合入 main 后 main CI `41434010937` 全绿。排除项：未部署、未发送真实 QQ、未跑本地全量。

### 灵宠斗法（2026-11-02，已完成）

审计确认：`pet-goal-farming-seeds.md` 已交付，`pet-roadmap-index.md` 四条聚合线与 `pet-goal-index-10.md` 十张卡均已有提交与 CI 证据，本地目标队列已清空；既有交付记录反复标注的唯一玩法缺口是「`fight()` 一次处理完整场，玩家没有战斗内动作」。本切片把一场战斗拆成逐回合：每条消息结算一个回合，玩家在抢攻/稳守/游斗之间取舍，气血跨消息保留。

实现要点：`combat.fight()` 增加可选 `max_rounds`（默认 None 仍是原来的 40 回合逐位不变），传 1 时只跑一回合并在未分胜负时返回 `winner=-1`；`data/duels.json` 定义五位按境界排列的护法，`domain/duel_content.py` 与 `Catalog._validate_duels` 校验境界、奖励与物品；`rules.json` 的 `duel` 由 `DuelRule`/`DuelStance` 校验每回合精力、回合上限与三条同向移动的出手；`gameplay/duel.py` 以 `quest_progress` 的 `duel_target`/`duel_round`/`duel_hp`/`duel_enemy_hp` 保存单局，`duel_week_<周一零点>_<护法id>` 保存周奖励凭证。斗法只用在出战伙伴、每回合扣 3 精力，不施放灵术（每回合重建单位时临时状态不跨回合），不写战报、不推进日常/周常/成就计数。击败护法发当周奖励一次，气血耗尽、12 回合用尽与认输都清空状态且不发奖；四行状态缺一行即视为没有进行中的斗法，开局会覆盖重建。

页面逐行给出护法境界、奖励与状态（可挑战/本周已胜/需相应境界），只给可挑战行挂「挑战」蓝字；进行中页面给双方气血、三条出手与「认输」蓝字，按钮固定 `灵宠斗法`/`灵宠战报`/`我的灵宠`，蓝字与按钮零重叠。`灵宠目标` 新增斗法行，帮助「秘境与关卡」新增四条，`test_contract_audit.py` 把 `duel` 纳入只读页面并登记 5 项内容，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

定向命令 `./.venv/bin/pytest -q tests/test_duel.py tests/test_commands.py tests/test_objectives.py tests/test_contract_audit.py tests/test_content.py tests/test_pet_catalog.py tests/test_battles.py tests/test_runtime.py tests/test_catalog_interaction.py tests/test_messaging.py`：`257 passed`（含新增 `test_duel.py` 19 项）。新增用例覆盖内容阶梯与规则负例、未结契只读、护法列表与唯一入口、境界/精力/派遣/重复开局拒绝、四行状态写入、逐回合精力与气血延续、获胜发奖与周凭证、跨周重开、失败与平局清空、认输、同操作重投、重启续战、残缺状态行、不写战报与计数，以及 `max_rounds=1` 只推进一回合而默认战斗仍打到分出胜负。未跑全量、未做仿真或压测、未发送真实 QQ、未部署；schema 21 与表结构不变。 提交 `7310186` 已推送 develop，develop CI `41459445207` 全绿（3105 项），fast-forward 合入 main 后 main CI `41460479772` 全绿（3105 项）。Release `v0.1.19` 由 `main` `7310186` 发布：tag run `41461552998` 的 `tests 3.10`/`tests 3.13`/`install-smoke`/`release` 全部 success，Release 非草稿非预发布，资产 `project.tar.gz` 1,111,242 字节 / sha256 `26763bbb38d47ee364a16591bf2b4a9790d59ec9da69eed94a15a70fdeb0d76d`，文件清单与 `git archive 7310186` 逐项一致且包含 `gameplay/duel.py`、`domain/duel_content.py`、`data/duels.json`、`tests/test_duel.py`。

### 灵宠商会（2026-11-03，已完成）

审计确认：本地 `docs/goals/*` 全部已交付，`pet-roadmap-index.md` 四线与 `pet-goal-index-10.md` 十卡均有提交与 CI 证据；上一轮 `pet-goal-duel.md` 也已发布 `v0.1.19`。因此本轮按死路审计选新闭环：材料与作物只有「固定打造消耗」和「回收 40% 售价」两条出口，没有按需求交付换更好价格的循环，也没有把日常产出转成长期经营目标的路径。

实现要点：新增 `data/commissions.json` 十条委托（四条 0 声望基础单 + 六条 60 声望高阶单），`domain/commission_content.py` 校验结构，`Catalog._validate_commissions` 要求物品存在、至少一条基础单、且灵石回报严格低于所需物品商店售价合计（堵死买货再交付的套利）；`rules.json` 新增 `merchant`（每日三单、日清灵石 60 / 声望 4）与 `MerchantRule`。`gameplay/merchant.py` 按北京日序数在「当前声望可接」的委托池里取连续三条，因此同日同声望稳定、隔日轮换；交付在同一事务内扣物品、加灵石与声望、写 `merchant_order_<日期>_<id>`，交齐当日三单追加一次 `merchant_bonus_<日期>` 日清奖励。声望存 `merchant_rep` 累计值且不因交付扣减，跨过 60 后可接池由 4 条扩到 10 条（看板即时刷新，已交凭证与已领日清不受影响）。拒绝路径覆盖未上架、重复交付、声望不足、物品不足、未知名称与越界序号，全部零写入；同 operation_id 重投返回原回复。

页面逐条列出今日委托的持有/需求、灵石与声望回报、状态，只有确实可交付的行挂「交付」蓝字，按钮固定 `灵宠商会`/`灵宠背包`/`灵宠目标`；`灵宠目标` 新增商会行，帮助「灵物与灵术」新增两条，`test_contract_audit.py` 把 `merchant` 纳入只读页面并登记 10 项内容，`docs/GAMEPLAY.md` 与 `docs/CONTENT.md` 已同步。

定向命令 `./.venv/bin/pytest -q tests/test_merchant.py tests/test_commands.py tests/test_objectives.py tests/test_contract_audit.py tests/test_content.py tests/test_pet_catalog.py tests/test_runtime.py tests/test_messaging.py tests/test_item_loop.py tests/test_duel.py`：`258 passed`（含新增 `test_merchant.py` 16 项），另跑赏金/每日特供/炼丹/杂交/灵田/贡献/成就商店/每日课题批次 `124 passed`。新增用例覆盖内容与定价校验（未知物品、套利定价、无基础单）、规则负例、未结契只读、看板同日稳定与隔日轮换、声望门槛与扩池、交付扣料发货与凭证、按序号交付与重复拒绝、五类拒绝零写入、日清奖励当天一次且隔日可再得、声望累计、重投幂等、重启持久、不写战报与计数、帮助/目标/解析、native 按钮与蓝字分离。未跑全量、未做仿真或压测、未发送真实 QQ、未部署；schema 21 与表结构不变。

### 灵宠集市（2026-11-03，已完成）

审计确认本地 goal 队列已清空，历次交付记录反复标注的最后系统级缺口是「no cross-player economy (needs new tables)」；`docs/DEVELOPMENT.md` 早前把「好友/交易/信箱」列为需要新表的排除方向，但没有任何合同测试锁定交易命令，赠送/寄养也证明了跨玩家转移本身可行，只是没有定价与撮合。本切片因此交付玩家集市：上架托管 → 浏览比价 → 购买成交 → 卖家入账与成交记录 → 下架或到期退回，形成真实的多用户闭环，与商会的 NPC 每日委托完全不同。

内容与校验：新增 `data/market.json`（挂单 3 天、单价 1-50000、单次 1-30 件、可售 `material`/`consumable`，四级摊位散铺 0/2 位/10% → 长摊 800/4/8% → 铺面 2400/6/6% → 商号 6000/8/4%）；`domain/market_content.py` 的 `Stall`/`MarketRule` 校验字段区间与价格上下界，`Catalog._validate_market` 要求首级免费、解锁价与陈列位严格递增、税率不升、摊位 id 唯一、每种可售种类至少有一件物品。

持久化：schema 升至 22。`market_listings` 保存托管挂单并用表级 CHECK 约束 `active`/`sold`/`cancelled`/`expired` 与 `closed_at`、`buyer_id` 的组合（成交时买家不得等于卖家）；`market_sales` 是永久成交账本，CHECK `fee + net = gross` 且买卖双方不同；索引 `market_listing_board`、`market_listing_seller`、`market_sales_seller` 分别服务浏览、我的摊位与成交记录。迁移沿用既有模式：`legacy_schema21` 还原 21 代结构（21/20/19/18 fixture 都先剥掉集市表再剥远征改动）、`backup_schema21` 留底、`migrate_market_tables` 从 `schema.sql` 取出完全相同的建表/索引语句执行、`validate_schema22` 与完整性/外键检查、失败回滚；20→21 分支改为写 `user_version=21` 后继续落入 21→22，而不是直接跳到最新版本。

玩法层 `gameplay/market.py`：摊位等级存 `quest_progress` 的 `market_stall`（1 起，缺省为散铺）。上架先解析物品与种类、数量、单价，再检查陈列位与持有量，全部通过后才在同一事务内扣背包并写挂单（托管）；购买先惰性结算到期挂单，再校验编号、状态、非自家、灵石足够，随后以 `state='active'` 为守卫更新为 `sold`，扣买家灵石、按**卖家**摊位税率计算 `fee = 总价 × 税率 // 100` 并把 `总价 - fee` 加给卖家、给买家加物品、写成交账本；下架同样以状态守卫更新为 `cancelled` 并原样退回托管；升级一次扣费并写等级，已是最高级或灵石不足整笔拒绝。到期挂单在打开集市相关页面时惰性结算为 `expired` 并退回卖家，重复扫描不会二次退款。

界面：`灵宠集市` 每页 5 条、按物品与单价排序，逐行给出物品/数量/单价/总价/卖家 UID/剩余天数，只有非自家且买得起的行挂「购买」蓝字；`灵宠集市 我的` 给出摊位、税率、陈列占用、下一级费用、在售挂单与「下架」蓝字，资源足够时挂「升级摊位」，并展示最近三笔成交；`灵宠集市 记录` 分页回顾总价/税额/实收。按钮始终不超过四条，蓝字命令不进入按钮。`灵宠目标` 新增集市行，帮助「血脉与道具」新增五条，`test_contract_audit.py` 把 `market` 纳入只读页面。

新增 `tests/test_market.py` 22 项（内容阶梯与负例、规则区间、未结契只读不建号、托管与看板、七类上架拒绝零写入、成交金额/税费/账本、自家/灵石不足/已售拒绝、下架与越权、到期退回、已下架物品关闭、升级扣费与上限、同操作重投、重启持久、帮助/目标/解析、QQ 按钮与蓝字分离、分页、21→22 迁移与留底）；聚焦 12 个文件 `302 passed`，另跑道具/信息/体验/商会/赠送/称号/成就/文档批 `185 passed`；`compileall` 与 `git diff --check` 通过。提交 `079944d` 已推送 develop，develop CI `41494309145` 全绿（3144 项）；fast-forward 合入 main 后 main CI `41495353767` 全绿（3.10/3.13 测试与安装冒烟全部 success，release 任务按分支跳过）。排除项：未部署、未发送真实 QQ、未跑本地全量、未改既有商店价格/回收比例/商会委托/战斗结算。

### 灵宠信箱（2026-11-03，已完成）

审计确认本地 goal 队列已清空（56 张本地卡全部交付并有提交与双绿 CI 证据），也逐一核对过新体系没有未接线的数据键、没有只进不出的货币、没有不可达内容。`docs/DEVELOPMENT.md:261` 早前把「好友/交易/信箱（需要新表）」列为排除方向：交易已由集市（schema 22）交付，**信箱始终没有实现**——`grep -rl '信箱\|邮件' src/` 为空，玩家在对方离线时无法转交任何东西，而赠送只在双方同时在线且每日三次内有效，集市只做「物品换灵石」。本切片补上第三种跨玩家转移：把材料或灵石连同一句留言寄给其他修士，对方上线自取，到期未领自动退回。

内容与校验：`rules.json` 新增 `mail` 与 `domain/content.py` 的 `MailRule`（`days` 1-30、`daily_limit` 1-10、`max_stones` 1-10000、`max_items` 1-50、`inbox_capacity` 1-50、`kinds` 限定 `material`/`consumable` 且去重），`Catalog._validate_mail` 要求每种可寄种类在物品表里至少有一件（与 `_validate_market` 同一口径）。信箱不需要新的内容文件：附件是既有物品与灵石。

持久化：schema 升至 23。新增单表 `mail_messages`（`sender_id`/`recipient_id` 外键到 `players`、`kind` ∈ `item`/`stones`、`stones`、`item_id`、`quantity`、`body` ≤ 60 字、`created_at`、`expires_at`、`state` ∈ `active`/`claimed`/`recalled`/`returned`、`closed_at`、`claimed_at`），表级 CHECK 同时约束三件事：寄件人不得是收件人；附件形状必须与 `kind` 一致（道具类 `quantity ≥ 1` 且无灵石，灵石类 `stones ≥ 1` 且无道具）；状态与时间戳必须一致（`active` 无关闭时间、`claimed` 两者都有、`recalled`/`returned` 只有关闭时间）。索引 `mail_inbox (recipient_id, state, message_id)` 与 `mail_outbox (sender_id, state, message_id DESC)`。迁移沿用既有模式：`legacy_schema22` 剥掉信箱表与两个索引，`legacy_schema21` 先调用它再剥集市表，因此 20/19/18 fixture 仍然逐级还原；`backup_schema22` 留底、`migrate_mail_tables` 从 `schema.sql` 取出完全相同的建表/索引语句执行、`validate_schema23` 与完整性/外键检查、失败回滚；21→22 分支改为写 `user_version=22` 后继续落入 22→23，而不是直接跳到 `SCHEMA_VERSION`。

玩法层 `gameplay/mailbox.py`：`send` 先整体校验（UID、好友边、当日封数、对方信箱容量、物品种类或灵石、上限与持有量），通过后才在同一事务内扣背包或扣灵石并写一行 `active`；`claim` 与 `recall` 都以 `UPDATE ... WHERE state='active'` 作为守卫，`rowcount != 1` 即视为「刚被领取/退回」并拒绝，因此一封托管只可能被支付一次；`_pay` 直接写 `players.stones` 或 `repo.add_item`，绕开 `grant`（`grant` 会把修为发给出战伙伴并要求它空闲，而信箱只转交附件、不发修为）。`sweep_expired` 在任一方打开信箱或寄件页时把过期信件改成 `returned` 并退回寄件人，重复扫描不会二次退款。页面对未领取信件只给可领取行挂「领取」蓝字，寄件页只给未领取行挂「收回」蓝字，按钮不超过四条且与蓝字零重叠。

新增 `tests/test_mail.py` 31 项（规则接线与区间、重复种类与未知种类负例、可寄种类无物品时拒绝、未结契只读且不建号、寄出托管与收件箱、灵石寄出与领取、领取只交付一次且第二次拒绝、未领取可收回、到期惰性退回且只退一次、当日封数只按当天计、信箱满整笔拒绝零写入、五类格式/物品/种类拒绝零写入、自己/陌生人/UID 不存在拒绝、上限与持有不足拒绝、同操作重投只托管一次、双方权限与不存在编号拒绝、领取后不能收回、重启持久、不写战报与进度、目标页两行、寄件箱过滤已领取、帮助与解析、QQ 按钮与蓝字分离、新库含两表两索引、22→23 迁移保留旧行并留底）。聚焦 11 个文件 `250 passed`，另跑道具/信息/体验/消息/分页/商会/赏金/贡献/斗法/双线/回收/图鉴交互/灵术赏批次 `237 passed`；`compileall` 与 `git diff --check` 通过。提交 `ff2b03f` 已推送 develop，develop CI `41558390144` 全绿（3176 项）；fast-forward 合入 main 后 main CI `41559227285` 全绿（同为 3176 项）。排除项：未部署、未发送真实 QQ、未跑本地全量、未改赠送/寄养/集市规则与战斗结算、未创建新 Release tag。

### 灵宠名帖（2026-11-03，已完成）

审计先做了两项覆盖排查：56 张 `docs/goals/*.md` 全部已交付；**123 个声明 `TITLE` 的玩法模块全部既在 `help._HELP_SECTIONS` 里有条目、也通过 `COMMANDS` 别名可达**，不存在“实现了却找不到入口”的系统。物品、技能、敌手、天赋也都没有孤立内容（`dao_names.json` 是道号移除后的历史遗留，刻意保留不删）。

真正的空缺在社交的另一半：`identity.profile` 永远只渲染 `ctx.user_id`，`我的信息` 没有 UID 参数；`名帖` 在 `teams/party.py` 与 `team_trial.py` 里指的是**队伍阵容**，不是玩家名片；`查看他人`/`他人信息`/`资料页` 全库 0 命中。而 schema 24 让玩家可以按 UID 加好友、schema 26 让玩家按 `借用 <好友UID> <编号>` 去借陌生人的伙伴——游戏要求你输入一串 UID 并使用它，却从不让你看清对面是谁。

本切片补上名片，并按**已经公开的东西**分层，而不是自定一套隐私策略：陌生修士只看到 UID、出战境界、论剑段位、收集榜名次与佩戴称号（段位与名次本来就印在 `灵宠论剑榜`/`灵宠收集榜`，称号是主动展示品）；好友额外看到出战阵容明细、成就数、图鉴进度、好友数与挂出的伙伴数，并给出「去借力」入口；自己的名帖与本人视图一致，而**灵石、背包、封存与注册时间在任何层级都不出现**，它们留在 `我的信息`。

`gameplay/card.py`：`relation()` 是唯一层级判定（`self`/`friend`/`public`，好友复用 `friends.linked()`），读取时重新计算，所以解除好友后同一张名帖立刻退回公开层，不需要清理；段位走 `arena.common.current_season` + `rating` + `tier_rewards.tier_of`（只读，不会为访客建立赛季行），收集名次走 `collection_rank.personal_rank`（本轮把内部 `_personal_rank` 开放为公开别名，保证名帖与榜单口径一致），成就数走 `achievements.claimed_count`，挂出数走 `borrow.lent`。切片不新增 schema、不新增内容文件、不写任何表。

顺带修掉一处真实渲染缺陷：名帖最初无条件渲染 `名字（种族）`，在默认名字时就变成「玄狐（玄狐）」。`pets.py` 里那条「自定义名才补种族」的规则此前以内联副本形式存在于两处（领养回复与名册），本轮抽出为 `pets.pet_label()` 并让三处统一调用——**这不是恢复被移除的改名功能**，`灵宠命名`/改名仍按 `tests/test_pet_naming.py` 的合同保持不可解析。

界面：`灵宠名帖` 单页，陌生修士挂「加为好友」，好友挂「去借力」，本人挂「我的信息」；帮助「身份与收集」新增一条；`灵宠目标` 不加行（名片不是进度）；`test_contract_audit.py` 把 `card` 纳入只读页面。schema 保持 26，README/CONFIGURATION/INSTALLATION 版本号不变。

新增 `tests/test_card.py` 20 项（未结契只读零写入、自己的名帖与 UID 等价且不泄露私密字段、陌生人只见公开面并拿到加好友入口、未知 UID 与非数字参数拒绝且零写入、好友可见阵容与四项计数并与专页数字一致、挂出数随借力变化、解除好友立即退回公开层、段位与收集名次与专页一致、佩戴称号、无出战伙伴提示、名帖零写入、帮助与解析、链接可回解析、QQ 按钮与蓝字分离、OneBot 文本、关系判定对称且自己优先）。

### 灵宠借力（2026-11-03，已完成）

审计先排除了一个诱人但错误的方向：**灵宠改名**。它在 `c9a232c` 实现过，随后在 `471b3db` 被有意移除，`tests/test_pet_naming.py::test_naming_command_is_removed` 至今锁定该命令必须不可解析，`docs/GAMEPLAY.md` 写明「当前版本不提供修改灵宠名字的用户命令」，`docs/DEVELOPMENT.md:261` 也把改名/道号列为有意移除项。恢复它等于推翻一条有合同测试守护的产品决定，因此本轮不作此改动。

随后按同一标准（“已有什么结构是扁平的”）审计：`gameplay/support.py` 让两席后备伙伴把基础四维借给当前出战伙伴，`gameplay/friends.py`（schema 24）让好友成为玩家可主动经营的关系，两者却从未相接——好友只换来赠送、寄养与信箱，好友的伙伴在战斗里没有任何意义，每个好友实质只是一个邮筒。`借力`/`借用好友`/`出借` 在 `src/` 命中 0，`灵宠助战` 属于 `support` 且保持不变。

本切片把两者接上：`rules.json` 新增 `borrow` 与 `domain/content.py` 的 `BorrowRule`（借出 12%、保留 7 天，`rate` 1%-25%、`keep_days` 1-30）。`Catalog._validate_borrow` 强制 `borrow.rate <= support.rate * support.slots`——一只借来的好友伙伴不得超过自己全部助战席的合计，否则最优解会变成刷社交而不是养成，`support` 会退化成摆设。

`gameplay/borrow.py`：出借方 `出借`/`收回` 写一行 `lend_<伙伴编号>`，`progress` 存到期时间戳；借用方 `借用`/`归还` 写 `borrow_pet`/`borrow_until`。`current()` 是唯一解析入口，每次读取都重新校验好友关系、挂出有效期、伙伴是否封存或外出，因此解除好友、对方收回、到期、封存或派遣都会让加成**立即**失效——不需要清理任务，半写的行天然读作“没有借用”。`bonus()` 按 `pet_stats` 的 12% 取整返回四维，由 `loadout.combatant` 在 `support.bonus` 之后叠加，只加给出战伙伴；出借不发任何报酬，否则小号互借就是刷钱路径。

界面：`灵宠借力` 分三段列出自己挂出的伙伴（谁在借、还剩几天）、当前借来的伙伴与加成、好友挂出且可借的伙伴，逐行挂「借用/收回/归还」蓝字；帮助「成长」新增四条，`灵宠目标` 新增借力行，`test_contract_audit.py` 把 `borrow` 纳入只读页面。schema 保持 26（状态全在 `quest_progress`），README/CONFIGURATION/INSTALLATION 版本号不变。

实现中修掉两处自身错误：`two_players` 测试夹具把 UID 顺序写反（借方与出借方颠倒，导致所有借用断言撞上“不能借用自己”），以及借用加成断言用伪造对象构造 `pet_stats`（缺字段崩溃），改为通过 `repo.pet()` 取真实模型。另有一处测试假设解析器会拒绝未知子动词，实际解析器透传参数、由 `dispatch` 拒绝，已改为断言拒绝信息。

新增 `tests/test_borrow.py` 34 项（规则接线与区间、借出比例上限的内容负例、未结契只读零写入、出借写一行与到期时间、封存/派遣/非本人拒绝、收回与重复收回、非好友/借自己/未挂出/已到期/已封存/无出战伙伴六类拒绝零写入、借用写两行并按 `pet_stats × 12%` 提升四维、只加出战伙伴、无借用时全零、解除好友立即失效、重新加好友恢复、挂出到期失效、出借人收回失效、伙伴外出失效、归还清两行与重复归还、借第二只替换并说明、借用不写奖励/战报/进度、重启持久、页面三段与空状态、目标行、帮助与解析、链接可回解析、QQ 按钮与蓝字分离、OneBot 文本）。聚焦 12 个文件 `358 passed`，另跑竞技/战斗/功勋/团队阵容/信箱/分享/集市/求购/演武/赠送/信息/封存/多宠阵容/阵容覆盖/平衡/图鉴批次 `310 passed`；`compileall` 与 `git diff --check` 通过。提交 `a13625a` 已推送 develop，develop CI `41670427200` 全绿（3339 项）；fast-forward 合入 main 后 main CI `41671320495` 全绿（同为 3339 项）。排除项：未部署、未发送真实 QQ、未跑本地全量、未改 `support` 两席的数值与命令、未改战斗引擎与奖励结算、未动 schema 与 README/CONFIGURATION/INSTALLATION 版本号、未创建新 Release tag。

### 灵宠演武（2026-11-03，已完成）

审计确认玩家**没有任何零代价的阵容验证手段**：`arena/battles.py::spar` 虽然无损，但要另一名玩家在场且每只出战伙伴都要空闲；`pvp` 要匹配与调息；`adventure`/`pve_stages`/`tower`/`corridor`/`survival`/`forbidden`/`team_trial`/`codex_trials`/`gauntlet`/`escort` 全部先过 `check_action`（精力与冷却）；`duel` 每回合扣 3 精力。`grep -rl '演武|试招|木人|演练|模拟战|训练场' src/` 为 0（只有 `arcs.json` 两句故事里的「木桩」）。于是「换了装备/改了阵位/吃了丹药到底变强没有」只能靠感觉。本切片补上这个缺口。

内容与校验：新增 `data/drills.json` 四座木人桩（柴木桩/青石桩/雷纹桩/玄铁桩），四维直接锚定同境界既有秘境敌手（`wood_guard`/`moon_wolf`/`thunder_dragon`/`ember_wraith`），不引入新的平衡带——打桩若比真实敌手更强或更弱，预演就会误导配装。`domain/drill_content.py` 的 `DrillDummy` 校验名称、境界、四维、`elements` 与 `order`，并要求 `primary_element ∈ elements`；`Catalog._validate_drills` 要求表非空、境界与元素都存在、`order` 唯一（重名由 `_index` 的通用去重拦下）。`rules.json` 新增 `drill` 与 `DrillRule`（`daily_attempts` 1-10，实配 5）。

玩法层 `gameplay/drill.py`：`catalog` 分页列出四座桩与今日剩余次数，只为还有额度时的每座桩挂「演武」蓝字；`run` 先按名称或序号解析木人桩，再要求已选出战伙伴且全部空闲，校验当日额度，然后用 `loadout.combatants(ctx, recover_energy=False)` 取**真实阵容**（心境、同心、阵位、装备、镶嵌、灵术、战意全部计入）、用 `Fighter.create` 以桩子自身元素与本命元素造敌、`combat.fight` 结算，成功后写一行 `drill_<北京日期>` 计数。**关键边界**：全程不调用 `check_action`，因此零精力零冷却；不调用 `reward`/`grant`，因此不发奖；不调用 `record_battle`/`capture_snapshot`/`counters.bump`，因此不写战报、不写关卡进度、不推进任何计数——否则一个零成本战斗入口会让成就与排行口径失效。

界面：回复给出回合数、破桩/落败/平局、木人桩剩余气血，并逐宠给出剩余/总气血与承伤，能直接看出哪个伙伴先倒；页尾复述额度与「不耗精力、不发奖励、不写战报」。帮助「秘境与关卡」新增三条，`灵宠目标` 新增演武行，`test_contract_audit.py` 把 `drill` 纳入只读页面。schema 保持 26（额度复用 `quest_progress`），README/CONFIGURATION/INSTALLATION 的版本号不变。

实现中修掉三处自己写错的地方：`Fighter.create` 的位置参数是 `(name, stats, elements, skills)`，最初把元素当技能传入，导致战斗里读 `skill.id` 崩溃（已改为 `elements` 传元素、`primary_element` 传本命）；`dispatch` 最初用「参数个数」区分页码与演武，语义含糊，改为显式 `名单 [页码]` 子命令；`_state_line` 初版残留了一个错误的境界表达式，改为按 `realm` 查名称。

新增 `tests/test_drill.py` 27 项（四桩按境界升序、境界与元素引用、未知境界/未知元素/重复 order/重复名/零 speed 五类内容负例、规则区间与模型负例、未结契只读且不建号、列表与剩余次数、额度用尽后隐藏入口、一次演武零写入且只写额度行、逐宠剩余气血自洽、名称与序号等价、与直接调用引擎的回合数一致、额度上限零写入、跨日恢复、未知桩/越界序号/未领养拒绝零写入、派遣中拒绝、同操作重投只打一场、除自身行外 `灵宠目标` 不变、目标页额度行、帮助与解析、各页链接可回解析且越界页拒绝、QQ 按钮与蓝字分离、OneBot 文本）。聚焦 12 个文件 `355 passed`，另跑论剑/战斗/历练/关卡/目录/信息/安装器/迁移/分享/今日秘境/秘境交互/历练伏击批次 `179 passed`；`compileall` 与 `git diff --check` 通过。提交 `5a9273a` 已推送 develop，develop CI `41659147417` 全绿（3305 项）；fast-forward 合入 main 后 main CI `41660044475` 全绿（同为 3305 项）。排除项：未部署、未发送真实 QQ、未跑本地全量、未改任何既有战斗路径与 `fight()`、未改精力/冷却/奖励结算、未动 schema 与 README/CONFIGURATION/INSTALLATION 版本号、未创建新 Release tag。

### 集市求购（2026-11-03，已完成）

审计确认集市只有卖方一侧：`gameplay/market.py` 的动词是 `上架 / 购买 / 下架 / 我的 / 记录 / 升级`，每一条都要求卖家先托管物品、买家只能按卖家标价接货。玩家想收 20 个锻灵矿，只能反复刷看板或溢价买；`求购` 在 `src/` 只命中 `commissions.json` 的一句 NPC 文案，`买单`/`应单`/`挂求` 全库为 0（含测试与文档）。`docs/goals/pet-market.md:83` 把「拍卖/竞价」列为非目标——那是随时间抬价的不同机制，固定单价的买方挂单是既有挂单的镜像，不需要竞价。也没有合同测试占用买侧动词：`handlers._parse("灵宠集市 求购")` 当时只会落进格式错误。本切片因此把集市补成双向：买方挂单托管全款，持货者应单交货收款。

内容与校验：`rules.json` 的 `market` 增加 `bid_days`（1-30）、`max_bid_quantity`（1-99）、`bid_slots`（1-6），实配 3 天 / 30 件 / 2 条；`MarketRule` 新增 `bid_slots` 不得大于最高摊位陈列位的校验，`Catalog._validate_market` 追加「求购单笔上限不得超过上架数量上限」。

持久化：schema 升至 26。`market_bids` 以 `escrow = quantity * unit_price` 的表级 CHECK 锁死托管额与标价的一致性，并用状态 CHECK 保证 `filled` 必有 `closed_at` 与 `seller_id`、`active` 两者皆无、`cancelled`/`expired` 只有 `closed_at`；`market_bid_sales` 以 `bid_id` 为主键使一单只能结算一次，CHECK `fee + net = gross`。索引 `market_bid_board`、`market_bid_buyer`、`market_bid_sales_seller`、`market_bid_sales_buyer`。迁移沿用冻结链：`legacy_schema25` 剥掉两张表与四个索引，`legacy_schema24` 改为先调用它再剥分享表，因此 18–25 fixture 仍逐级还原；`backup_schema25`、`migrate_bid_tables`、`validate_schema26` 与完整性/外键检查；24→25 分支改为写 `user_version=25` 后继续落入 25→26。

玩法层 `gameplay/market.py`：`place_bid` 先校验种类、数量、单价、求购位与全款，通过后才扣灵石并写一行 `active`；`fill_bid` 依次拒绝自家求购、未知/已成交/已到期、持有不足，随后以 `WHERE state='active'` 为守卫更新为 `filled` 并写入 `seller_id`，再在同一事务内扣应单者物品、给买方加物品、按**应单者**摊位税率结算并把 `托管 - 税额` 加给应单者、写账本——买方不会二次付款，因为钱在挂单时就已离开；`cancel_bid` 以「本人 + active」为守卫，`rowcount != 1` 即拒绝，成功才退款；`sweep_bids` 与既有 `sweep_expired` 一起由新的 `sweep()` 在每个集市入口统一调用，把过期或物品已下架的求购关闭并退款一次。`objective_line` 追加求购占用。

界面：`灵宠集市 求购` 每页 5 条公开看板，逐行给出物品、数量、单价、托管额、买家 UID、剩余天数与「我持有」，只给「非自家且持有够」的行挂「应单」；空看板给出「挂求购」入口。`灵宠集市 求购记录` 同页分列「收货」与「交货」，含税额与实收。帮助「血脉与道具」新增四条，`灵宠目标` 集市行追加求购占用，`test_contract_audit.py` 的 `market` 只读页保持连通。

新增 `tests/test_market_bids.py` 31 项（规则区间与三条负例、目录层单笔上限负例、未结契只读、空看板、挂单托管全款与到期时间、九类格式/物品/种类/数量/单价拒绝零写入、灵石不足零写入、求购位上限与撤单释放、应单交割与结算（物品双向、买方不二次扣款、应单者按自己摊位税率实收）、高摊位税率生效、自家/未知/不足/格式拒绝零写入、成交后二次应单拒绝、撤单退款与二次撤单拒绝、非本人与未知编号拒绝、到期退款一次且后续页面不重复退款、任意集市页面触发清扫、物品下架按灵石退款、重启持久、同操作重投只挂一单且只结算一次、不动上架表与账本与进度与战报、帮助与解析、只对持有足够的行挂应单且自家不挂、双方记录、目标页求购占用、QQ 按钮与蓝字分离且 OneBot 文本可读、各页链接可回解析且越界页拒绝、新库含两表四索引、表约束拒绝三类坏行、24→26 与 25→26 迁移留底）。同时更新 `tests/test_market.py` 的一处裸 `MarketRule` 夹具以携带三个新必填字段——这是规则模型的真实契约变更，故刻意不给新字段加默认值，避免漏配静默通过。聚焦 15 个文件 `387 passed`，另跑信息/分页/商会/赏金/贡献/斗法/回收/图鉴交互/安装器/双线/灵宠目录/平衡/灵田/赠送/信箱/战报批次 `303 passed`；`compileall` 与 `git diff --check` 通过。提交 `19a44ca` 已推送 develop，develop CI `41649014077` 全绿（3278 项）；fast-forward 合入 main 后 main CI `41649849305` 全绿（同为 3278 项）。排除项：未部署、未发送真实 QQ、未跑本地全量、未改上架/购买/下架/升级的语义与定价、未改摊位阶梯与税率、未改战斗与奖励、未创建新 Release tag。

### 灵宠分享（2026-11-03，已完成）

审计方向从「还能加什么」换成「已有什么永远看不到」：`battle_records` 永久保存每场战斗的不可变战报（战前快照、逐条事件日志、当时回复，全库 50 处引用），但 `repository.battle_report(user_id, battle_id)` 的授权条件是 `JOIN battle_participants p ... AND p.user_id=?`，而 `battle_participants.permission` 只有 `participant`/`defender` 两个值。于是战报**只可能**被已经打过这场的人读到：一场决定性的论剑胜负或一次首领击杀，无法给任何其他人看。`grep -rl '分享' src/` 只命中 `companionship.py` 的文案与首领击退奖励措辞，没有任何分享动词；`tests/test_battle_records.py:85` 与 `tests/test_lineup_coverage.py:434` 都在断言这道参与者门，说明封闭是有意的、必须保留。本切片因此新增第二条**独立守卫**的读取路径，而不是放宽第一条。

内容与校验：`rules.json` 新增 `share` 与 `domain/content.py` 的 `ShareRule`（`daily_limit` 1-20、`code_days` 1-30、`list_page_size` 1-10），`Catalog._validate_share` 要求有效期至少一天。分享没有逐条内容，因此不新增数据文件，也不进 `DOCUMENTED_COUNTS`（与 `mail`/`friend` 同理）。

持久化：schema 升至 25。新增单表 `battle_shares`（`share_id` 主键并 `CHECK(length BETWEEN 6 AND 24)`、`battle_id` 外键到 `battle_records`、`owner_id` 外键到 `players`、`created_at`、`expires_at` 且 `CHECK(expires_at > created_at)`、`state` ∈ `active`/`revoked`、`closed_at`、`views`），表级 CHECK 把状态与关闭时间绑死；索引 `battle_share_owner (owner_id, state, created_at DESC)` 与 `battle_share_battle`。表里只存 `battle_id`，绝不复制 `snapshot`——战报已不可变，复制只会多一条会漂移的路径。迁移沿用冻结链：`legacy_schema24` 剥掉分享表与两个索引，调用它的是 `legacy_schema23`（newest-first），因此 18–23 fixture 仍逐级还原；`backup_schema24` 留底、`migrate_share_tables` 从 `schema.sql` 取相同语句执行、`validate_schema25` 与完整性/外键检查、失败回滚；23→24 分支写 `user_version=24` 后继续落入 24→25（上一切片修掉的两个缺陷不回退，另有 23 库一次走到 25 的回归用例）。

玩法层 `gameplay/shares.py`：`create` 用**参与者门**的 `repo.battle_report(ctx.user_id, id)` 取战报，所以只能分享自己打过的；随后检查当日次数，再用 `secrets` 随机铸码并处理碰撞。码的字母表去掉 `0/O/1/I`（要口头转述与人手重输），长度 12，与自增的战报编号无关——分享码是 bearer 凭据，谁拿到谁就能读那一场，因此不能可推导。`view` 对任何玩家开放：先惰性清理到期码，再按有效码取 `battle_id`，用**分享者**在该场战斗的 `side` 渲染（页首注明「以分享者视角」），并只在该次成功读取时 `views+1`。`revoke` 以 `UPDATE ... WHERE share_id=? AND owner_id=? AND state='active'` 作守卫、`rowcount != 1` 即拒绝，因此重复撤回不可能成功两次。渲染函数从 `battle_records._detail` 中抽出为 `render_report(row, page, *, shareable=False)`，授权留在各自调用方：参与者路径仍走 `battle_report`，分享路径走有效码，两者共用一个渲染器，分享因此不可能变成绕过参与者校验的后门。页面 `灵宠分享 我的` 每页 5 条、只为有效期内的行挂「查看」「撤回」；`灵宠战报 查看` 的详情页在参与者视角下多一条 `灵宠分享 <编号>`。

新增 `tests/test_shares.py` 31 项（规则接线与区间、铸码随机性与字母表、未结契只读、空页、创建写一行 active 且到期时间正确、未参与与未知编号与格式拒绝零写入、`defender` 行对局外人仍拒绝但对本人放行、每日上限拒绝且次日恢复、他人可读且渲染快照而非现况、改名后不影响旧战报、每次成功读取才计数、坏码拒绝不计数、过期码不可开、过期后可重新分享出新码、撤回对所有人关闭、非本人撤回拒绝、未知码撤回拒绝、我的分享状态与行内动作、分页与链接可解析、目标页两行、战报详情给出分享入口且局外人仍被拒、重启持久、同 operation_id 只铸一码、分享不动资源也不写新战报、帮助与解析、QQ 按钮与蓝字分离、新库含表与两索引、半闭合行被表约束拒绝、23 库一次迁到 25、24 库补齐分享表并留底）。聚焦 14 个文件 `309 passed`，另跑论剑/战斗/秘境/关卡/阵容/道具/信息/分页/集市/信箱批次 `314 passed`；`compileall` 与 `git diff --check` 通过。提交 `87c4c4b` 已推送 develop，develop CI `41580710242` 全绿（3246 项）；fast-forward 合入 main 后 main CI `41581270093` 全绿（同为 3246 项）。排除项：未部署、未发送真实 QQ、未跑本地全量、未改参与者校验与 `permission` 取值、未改战斗结算与既有奖励、未创建新 Release tag。

### 灵宠好友（2026-11-03，已完成）

审计确认 `docs/DEVELOPMENT.md:261` 把「好友/交易/信箱（需要新表）」列为排除方向，其中交易已由集市（schema 22）交付、信箱已由邮寄（schema 23）交付，**好友始终没有实现**：`grep -rl '好友' src/` 为空。更要紧的是 `gifting.are_friends()` 只是把「同场战斗或同队」*推导*成好友边，玩家看不到、加不了、也结束不了这条边，而 `灵宠赠送`、`灵宠寄养` 与 `灵宠信箱` 都依赖它。本切片把这条派生边变成可主动经营的关系，同时保留旧判断，避免影响既有存档。

内容与校验：`rules.json` 新增 `friend` 与 `domain/content.py` 的 `FriendRule`（`max_friends` 1-200、`request_hours` 1-72），`Catalog._validate_friend` 要求名册至少能装下两个人。好友没有逐条内容，因此不新增数据文件，也不进 `DOCUMENTED_COUNTS`（与 `mail` 同理）。

持久化：schema 升至 24。`friend_links (user_low, user_high, created_at)` 用 `PRIMARY KEY(user_low, user_high)` 与 `CHECK(user_low < user_high)` 把一段关系归一化成唯一一行，天然对称、不可能重复或只记一半；`friend_requests (from_id, to_id, created_at, expires_at)` 用 `PRIMARY KEY(from_id, to_id)` 锁定单向待处理申请，`CHECK(from_id != to_id)` 禁止自申请、`CHECK(expires_at > created_at)` 保证有效期为正；索引 `friend_link_low`/`friend_link_high`（两个查询方向）、`friend_request_inbox`（待我处理）、`friend_request_outbox`（我发出的）。迁移沿用冻结链：`legacy_schema23` 剥掉两张表与四个索引，`legacy_schema22` 改为先调用它再剥信箱表，因此 21/20/19/18 fixture 仍然逐级还原；`backup_schema23` 留底、`migrate_friend_tables` 从 `schema.sql` 取出完全相同的建表/索引语句执行、`validate_schema24` 与完整性/外键检查、失败回滚。**同时修掉两个既有迁移缺陷**：`validate_schema23` 原先比对的是「当前」schema 文件（加入好友表后必然结构不符），改为比对 `legacy_schema23`；22→23 分支原先直接写 `PRAGMA user_version=SCHEMA_VERSION` 并返回，会跨过 23→24，改为写 `user_version=23` 后继续落入下一段。

玩法层 `gameplay/friends.py`：`add` 先解析 UID 并拒绝自己/未知/多参，再检查是否已是好友、是否已有任一方向的待处理申请、双方名册是否已达上限，全部通过后才写一行单向申请；`accept` 校验申请确实存在且由对方发起、双方名册仍有空间，随后**同一事务内**写入归一化好友行并删除该申请，避免崩溃留下永久待处理状态；`reject` 与 `withdraw` 只删申请不建边，且各自限定「收件人」与「发起人」；`remove` 由任一方执行、删除归一化行，双方名册同时消失。`linked()` 是唯一成员判定（归一化配对查询），`gifting.are_friends()` 改为「已接受的好友边 **或** 旧战斗/同队边」——旧存档行为逐位不变，两条路径各有独立回归用例。申请按 `request_hours` 惰性过期（`sweep_expired` 在每个入口先跑），过期后同一对可立即重新申请；名册计数必须同时统计 `user_low` 与 `user_high` 两列，否则一半好友不计入上限。

界面：`灵宠好友` 每页 4 位，逐行给出 UID、结交日期与距今天数，每行挂「解除」；`灵宠好友 申请` 每页 4 条，待我处理的行挂「同意」「拒绝」，我发出的行挂「撤回」；两页都只为当下可执行的动作挂蓝字，按钮不超过四条（翻页、申请页、目标页）。`灵宠目标` 新增好友行，帮助「秘境与关卡」新增六条，`test_contract_audit.py` 把 `friends` 纳入只读页面。

新增 `tests/test_friends.py` 37 项（规则接线与区间、上限负例、未结契只读且不建号、空名册、添加只写申请不建边、同意写一行归一化边并删申请、反向申请也归一化、拒绝与撤回零写入、任一方解除、自己/未知/多参/格式拒绝、已是好友与双向重复申请拒绝、接受方与发起人权限拒绝、名册上限与对方上限拒绝、全部拒绝路径数据库不变、过期后释放与过期申请不可接受、好友边解锁赠送与信箱、旧战斗边仍然有效、解除后边关闭、`linked` 对称且自我为假、重启持久、同 operation_id 只结算一次、目标页两行、好友操作不动资源与战报、帮助与解析、渲染行仅挂可执行蓝字、QQ 按钮与蓝字分离、OneBot 文本、新库含两表四索引、归一化与自连接约束、双方计数、22→24 与 23→24 迁移留底）。聚焦 14 个文件 `357 passed`，另跑经济与日常批次 `269 passed`；`compileall` 与 `git diff --check` 通过。提交 `197e034` 已推送 develop，develop CI `41567508366` 全绿（3214 项）；fast-forward 合入 main 后 main CI `41568342282` 全绿（同为 3214 项）。排除项：未部署、未发送真实 QQ、未跑本地全量、未改赠送/寄养/信箱的价格与上限（只放宽好友边判定）、未做好友通知推送、未创建新 Release tag。

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
