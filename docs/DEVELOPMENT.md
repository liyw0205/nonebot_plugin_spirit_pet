# 开发指南

本项目尚未发布稳定版。允许直接重构内部 API、目录和数据模型，不为未发布代码保留兼容导出、旧字段镜像或自动迁移分支。数据库不匹配时拒绝启动，不能静默重建或清空用户文件。

开发计划见 [开发路线](ROADMAP.md)，数据字段见 [静态内容规范](CONTENT.md)，玩家操作见 [玩法说明](GAMEPLAY.md)。

## 目录与依赖

```text
bot.py                         NoneBot 启动、双适配器注册
src/plugins/nonebot_plugin_spirit_pet/
  __init__.py                  仅插件元数据与入口
  core/config.py               环境变量，运行节奏与消息配置
  adapters/handlers.py         指令识别、真实身份、事件去重键
  adapters/messaging.py        OneBot 文本 / QQ Markdown、按钮、蓝字
  application/commands.py      命令和动作注册
  application/context.py       单次事务上下文
  application/game.py          调度、事务、保存
  domain/content.py            Pydantic 静态内容模型
  domain/battle_content.py     元素、天赋、装备、技能及成长阶梯模型
  domain/lineage_content.py    种族血脉分支与四维倍率模型
  domain/crafting_content.py   打造配方与纯函数分解回收公式
  domain/expedition_content.py 离线委托的静态要求与奖励定义
  domain/expedition_state.py   出发时抽取的严格运行奖励快照
  domain/state.py              Player、Pet 运行模型
  domain/models.py             Reply、GameError
  content/catalog.py           JSON 加载、唯一性和引用验证
  content/validation.py        装备、技能、元素与内容可用性验证
  content/lineage_validation.py 种族分支、成本与成长取舍校验
  content/crafting_validation.py 配方完整性、材料来源与资源损耗校验
  gameplay/pets.py             领养、召唤、列表、切换、改名
  gameplay/hatching.py         灵卵孵化与名册容量检查
  gameplay/identity.py         唯一道号生成、显示、修改
  gameplay/cultivation.py      修炼、大小境界突破、血脉进化
  gameplay/lineage.py          种族分支展示、选择和基础成长倍率
  gameplay/economy.py          签到、背包、商店、消耗品
  gameplay/quests.py           每日任务与领奖
  gameplay/expeditions.py      离线委托、行程查询、原宠领奖与召回
  gameplay/rewards.py          共用奖励结算
  gameplay/combat.py           属性计算与限回合战斗
  gameplay/talents.py          天赋触发与单场护盾、毒伤效果
  gameplay/effects.py          主动控制、弱化、增益、净化、驱散和持续次数
  gameplay/compatibility.py    类别、元素、境界适用性检查
  gameplay/equipment.py        穿戴、卸装、槽位与图鉴
  gameplay/forging.py          装备强化与强化件库存保留
  gameplay/equipment_inventory.py 同等级装备库存取用与返还
  gameplay/crafting.py         配方、打造、分解与回收预览
  gameplay/skills.py           秘笈学习、携带与卸下
  gameplay/mastery.py          熟练度结算、升级与满级处理
  gameplay/loadout.py          将装备与技能组装到战斗单位
  gameplay/adventure.py        奇遇、单人/组队 PVE 结算
  gameplay/arena/              镜像对战、赛季快照、积分、资格、SQL 匹配与领奖
  gameplay/teams/common.py     队伍成员、权限、容量与准备失效的共用事务操作
  gameplay/teams/party.py      建队、成员详情、准备与出征
  gameplay/teams/requests.py   申请、邀请、审批、撤回与按权限分页
  gameplay/teams/management.py 退队、踢人、队长转让与显式解散
  gameplay/information.py      帮助、面板、图鉴、排行榜
  storage/schema.sql          运行数据表
  storage/database.py         SQLite 连接、初始化、事务、幂等
  storage/repository.py        事务内对象缓存与 SQL 操作
  utils/arguments.py          复用的名称解析和数量验证
  utils/time.py               UTC+8 日期、自然月赛季和冷却计算
  utils/energy.py             精力恢复与上限
  utils/elements.py           元素祖先展开与继承门槛判断
  utils/pagination.py         只读内容分页、页码校验与导航
  utils/randomness.py         可注入随机源的加权抽取
  data/*.json                 静态宠物、境界、血脉、物品、怪物和奖励
tests/                         单元、并发、适配器契约和真实 WS 测试
scripts/smoke_test.py          无需 NapCat 的协议冒烟测试
scripts/balance_report.py      固定种子仿真入口，只使用临时数据库
scripts/balance_specials.py    血脉分支与六类主动效果的独立专项仿真
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

通用成功结果保留约七天，后续请求清理过期记录。超过保留窗口的古老重投通常不保证去重；离线派遣永久保留来源消息键及终态，论剑结果保留唯一消息键和完整回复，赛季领奖保留复合唯一凭证。业务拒绝不缓存，玩家修正条件后可重试。消息发送不承诺 exactly-once。

## 数据边界

- `players`：原始用户 ID、唯一道号、共享灵石、出战宠物、日期与玩家级冷却。道号用 SQLite UNIQUE COLLATE NOCASE 约束，生成和改名均处于写事务内。
- `pets`：每只宠物独立的种族 ID、名字、大境界、层数、血脉、选定的 lineage_id、修为、亲密、精力及恢复时间。分支不改 species_id。
- `inventory`：道具 ID 与数量，没有专门的“灵粮镜像”字段。
- `equipment`：每只宠物的槽位物品与强化等级，装备不同时计入库存。
- `unequipped_equipment`：玩家背包中 +1 及以上的装备，按物品、强化等级计数；+0 仍使用普通 inventory。卸装和重新穿戴不清空强化，不重复计数。
- `learned_skills`：每只宠物的学习/携带状态、技能等级与当前级剩余熟练度。
- `quest_progress`：当前任务日的进度及领取状态；刷新按玩家的 `quest_day` 处理。
- `expeditions`：行程及原宠归属、委托名称、永久出发消息键、开始/完成时间、严格奖励快照、运行/已领/已召回状态与结算时间。
- `teams/team_members`：队长、成员、已同意出征的宠物编号。
- `team_requests`：待处理申请/邀请，复合键为队伍与候选人，记录发起人、创建时间及失效时间。不是静态 JSON；解散级联清理，审批完成删除，入队删除该候选人所有请求。
- `seasons/season_entries`：自然月边界、观测时间高水位、规则快照及实际参赛玩家的独立积分与胜负平。
- `pvp_results`：挑战双方及原宠、胜者、日期、分差、结算时间、永久唯一消息键和当时的 Reply；用于配额、领奖统计和重投，不是逐回合完整战报。
- `season_claims`：每季每人唯一的领奖凭证、实际奖励快照与领取时间。
- `operations`：事件来源去重键、玩家和完整结果。

玩家 ID 不加适配器、bot 或群号前缀。不存在绑定和合并接口。玩家界面只显示道号，交互按道号查找内部 ID；不要把原始 ID 插进 Reply、按钮或蓝字。改道号后邀请和队伍仍按内部 ID 关联，不会转移到复用旧道号的人。

修炼、历练、PVE、PVP 冷却在玩家上，换宠不能绕过。精力在宠物上；未出战宠物的恢复于再次访问时按时间差计算。队伍战斗对所有成员检查条件后才扣费，任何一人不满足则整场回滚。

## 添加一个玩法

以新增“采药”为例：

1. 静态掉落写入对应 JSON，涉及新结构时先在 `domain/content.py` 定义模型，在 Catalog 校验其物品引用。新冷却秒数放 `core/config.py` 和 `.env.example`。
2. 在合适的 `gameplay/` 模块编写 `def gather(ctx: Context, arg: str) -> Reply`。先校验条件，再通过同一 Repository 修改资源；预期拒绝抛 `GameError`。
3. 如果消费精力或改变战斗能力，调用 `ctx.repo.invalidate_ready(user_id)`，不要沿用旧的组队准备。
4. 在 `application/commands.py` 为 ACTIONS 注册函数，COMMANDS 注册中文入口。仅确实接受参数时设置 `arguments=True`。
5. 如果影响每日任务，明确成功事件并调用 `quests.advance`，同时扩展静态任务事件类型。
6. 添加成功、失败回滚、资源不足、并发、相同消息重投和冷却边界测试；更新玩家帮助、`docs/GAMEPLAY.md`。

涉及持久化结构时直接修改运行模型与 schema，提高开发期 schema 版本，使用新临时库测试。当前 schema 为 9，旧版库明确拒绝启动并保留原文件。不要保留历史字段双写。需要保留某份真实存档时，应另立明确的数据迁移任务，而不是默认销毁或假装兼容。

## 赛季与镜像

- `arena.common.current_season` 用 UTC+8 自然月创建严格规则快照，关闭旧季，并以所有赛季的 `MAX(observed_at)` 拒绝时钟倒退。停机跨月只在实际访问月份建季，不补造空月份；新季不修改旧季积分或玩家冷却。
- 删除旧全局 rating、pvp_pairs 及邀请战帖系统，积分唯一来源为 season_entries；查询默认分数不插入参赛记录。`scoring` 结算两方零和积分与胜负平；`battles` 直接取当前双方出战宠镜像，仅扣主动方精力、设置冷却、取消准备并增加实际施法熟练度，持久化结果与完整回复，全部处于同一事务。
- `eligibility` 检查主动方闲置、恢复后精力、冷却、日挑战次数，并检查双方境界、分差和同对额度。`matching` 在 SQL 中按后者筛选镜像，再执行 LIMIT/OFFSET，不无界加载全服玩家。守方精力、冷却、主动挑战次数或外出占用均不影响被挑战。
- `loadout.combatant(recover_energy=False)` 构建镜像但不触发被动精力恢复，防守方的宠物/玩家资源、冷却、技能熟练度与队伍准备保持不变。切磋双方都用此只读路径，无积分或经济收益；只有主动方须闲置。
- `pvp_results.operation_id` 永久唯一。读取该键必须先验证挑战者身份；通用缓存清除后直接重放旧 Reply，不重新解析当时道号、不重新参战，也不将旧挑战记入新季。原宠组合外键保证参与者归属。
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
- 道号仅用于查找和显示，数据库关联仍是原始玩家 ID。`Context` 没有群作用域，团队明确为全服团队；消息层不主动跨会话推送。不能将适配器的会话去重键误当队伍权限范围。
- 队务按四条一页执行 SQL LIMIT/OFFSET，查询限定本人或当前队长可处理的记录。此限制属于查询授权，不等于私聊投递；`bot.send(event, ...)` 回复当前会话，群内查询结果仍对同群成员可见。显式分页参数 `分页 N` 含空格，不可能与合法道号冲突；成员详情也必须限定在本人当前队伍。
- 成员变动与出征共用 `BEGIN IMMEDIATE`：要么先完成整场结算再变动，要么先变动并使旧准备失效。不能在战斗中途重新读取名单，把一次请求变成部分成员扣费。

## 战斗规则

当前是自定义回合制规则，不依赖已有桌游或游戏规则体系：

- 属性来自种族基础值乘以境界、层数、血脉、亲密、分支各属性倍率，再加装备各自强化后的固定属性，修为余额不直接增加攻击。血脉分支引用错误或不属于该种族时明确拒绝，不能悄悄返回默认倍率。
- `loadout.combatant` 对装备和技能再次校验类别、全部所需元素与最低境界；拒绝不兼容内容，不静默跳过坏数据。
- `Fighter.primary_element` 显式从宠物/敌人定义传入，不能取 elements[0]。普攻使用主属性，伤害技能使用技能元素，防守仅看目标主属性；分支递归继承五行关系，倍率只算一次，1.25/0.8/1.0。无属性技能按中性处理。
- 已携带技能依固定顺序轮换，系数乘数据库等级对应的威力倍率。治疗技能回复自身；满血但仍有有效净化等附加效果时可以施放，否则回退普攻且不记技能施放。技能轮次属于单场内存状态，不是 JSON 时间字段。
- `talents` 负责开场护盾、行动前毒伤/恢复、进攻增益、闪避和命中后触发。毒和反击不递归触发天赋或技能熟练度。效果状态在每场新建 Fighter 时重置。
- `effects` 负责明确的控制/增益状态与行动计数：先处理行动前毒伤和天赋，再检查受控，随后施法或普攻，最后推进效果期限和免控。规划目标后才检查效用，避免随机探测目标与实际目标不一致。`actions` 只统计真正行动并推动技能轮换，`turns` 包含受控跳过的行动机会。
- 同类效果取较强值、较长剩余次数并刷新，不叠加；自身刚施加的持续效果从后续行动才计期。护盾先消耗临时层再消耗天赋层。有效驱散和净化计技能施放，无目标则回退普攻；持续效果、反击和天赋不记技能施放。
- 每场从满气血开始；气血只在本场存在，结算消耗精力，不持久化战斗气血。
- 速度决定行动顺序，同速时随机决定先后，目标从存活对手中抽取。伤害至少为 1，有 90%-110% 浮动。
- 最多 40 回合，超时视作平局；不发 PVE 胜利奖励，不转移论剑积分。
- PVP 直接挑战镜像，遵循冻结赛季的同境界、分差和日/季限额；切磋按道号立即结算，无邀请过程，不消耗精力或发放经济奖励。
- 组队用同一战斗函数，每位参战成员胜利后获得一份各自抽取的奖励，不分摊掉落。
- `Battle.skill_uses` 按左右阵营、pet_id、skill_id 统计真实施放。PVE（含败退/平局）与积分 PVP 主动挑战者在原事务内调用 `mastery.award_mastery`，镜像防守与切磋不调用。不得根据战报文本或回合数猜测使用次数。

参数内容可在 JSON 中调整；更换算法需同时改 `combat.py` 和测试，不把战斗分支硬塞进适配器。

## 分支约定

`develop` 用于日常开发和提交，`main` 接收验证通过的版本。本轮以同一通过测试的提交建立两个分支；后续功能先提交 develop，再通过审查/测试合入 main。提交不包含 .env、玩家库或本地虚拟环境，不强制推送覆盖已有提交。

## 验证

```bash
.venv/bin/python -m pip install -r requirements.txt 'pytest>=8,<10'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke_test.py
.venv/bin/python scripts/balance_report.py --runs 100 --seed 20261007 --check
.venv/bin/python scripts/balance_specials.py --runs 100 --seed 20261007 --check
.venv/bin/python -m compileall -q src tests scripts bot.py
```

Windows 使用 `.venv\Scripts\python.exe`。当前 Termux 可直接用 `$HOME/myenv/bin/python`，不要求新建环境，不要求 NapCat 或真实 QQ 凭证。测试全部使用临时数据库。

测试覆盖静态目录校验、同 ID 数据共享、十层成长、血脉、主属性/分支继承、天赋效果、技能成长、强化保留、灵卵容量、事务回滚、并发、重复消息、组队准备、直接镜像对战与适配器构造。真实 ASGI 测试会连接 `/onebot/v11/ws`，验证鉴权和收发，不只调用业务函数。

GitHub Actions 使用 Linux/Windows 和 Python 3.10/3.13 跑完整回归，另在 Python 3.12 的两个系统运行一键安装入口，在含空格的新目录建立环境，再用安装出的 Python 执行真实 WS 冒烟。QQ 真机 AppID 权限、Markdown 审批和蓝字客户端呈现需另行验收，单元测试不代表平台授权已经通过。

固定种子矩阵的场景、准备程度、收益口径和留存结果见 [数值验收](BALANCE.md)。日常 pytest 含每个准备阵容 10 次的快速门禁；内容、公式、主动技能变更后另跑完整 100 次并审阅差异。脚本不得连接或修改 `SPIRIT_PET_DB`，仿真只使用临时数据库、生产 `loadout.combatant` 和真实 `fight`。

基础矩阵不包含血脉分支或辅助配装；专项脚本另外验证全部分支和主动效果，并保留未胜利的对照结果。效果观测器仅在单进程专项范围内临时包装 `effects.apply`，统计实际状态变化，退出或异常时恢复原函数；它不是机器人运行时组件，不应在运行中的服务进程里调用。

## 配置来源

`pyproject.toml` 保留参考仓库安装脚本生成的 NoneBot 运行项目布局，不猜测 PyPI 包模板：

- 参考提交：`97f43acba8dd185111d998c48d4e1cf5a069b117`。
- `scripts/install.sh` 的 TOML 生成段与 `scripts/install_termux.sh` 的 `write_pyproject()`。
- `[project]`、`[tool.nonebot]`、适配器配置表及 `plugin_dirs = ["src/plugins"]`。
- Python 最低 3.10、Pydantic 2 对应本项目实际 API；打包发布前另做分发配置与静态资源包含测试。
