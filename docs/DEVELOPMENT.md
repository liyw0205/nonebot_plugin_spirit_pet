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
  gameplay/duels.py            论剑、切磋、邀请与应战
  gameplay/teams.py            队伍、准备、出征
  gameplay/information.py      帮助、面板、图鉴、排行榜
  storage/schema.sql          运行数据表
  storage/database.py         SQLite 连接、初始化、事务、幂等
  storage/repository.py        事务内对象缓存与 SQL 操作
  utils/arguments.py          复用的名称解析和数量验证
  utils/time.py               UTC+8 日期和冷却计算
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

成功结果保留约七天，后续请求清理过期记录。超过保留窗口的古老重投不保证去重；业务拒绝不缓存，玩家修正条件后可重试。消息发送不承诺 exactly-once。

## 数据边界

- `players`：原始用户 ID、唯一道号、共享灵石、出战宠物、日期、玩家级冷却与论剑积分。道号用 SQLite UNIQUE COLLATE NOCASE 约束，生成和改名均处于写事务内。
- `pets`：每只宠物独立的种族 ID、名字、大境界、层数、血脉、选定的 lineage_id、修为、亲密、精力及恢复时间。分支不改 species_id。
- `inventory`：道具 ID 与数量，没有专门的“灵粮镜像”字段。
- `equipment`：每只宠物的槽位物品与强化等级，装备不同时计入库存。
- `unequipped_equipment`：玩家背包中 +1 及以上的装备，按物品、强化等级计数；+0 仍使用普通 inventory。卸装和重新穿戴不清空强化，不重复计数。
- `learned_skills`：每只宠物的学习/携带状态、技能等级与当前级剩余熟练度。
- `quest_progress`：当前任务日的进度及领取状态；刷新按玩家的 `quest_day` 处理。
- `teams/team_members`：队长、成员、已同意出征的宠物编号。
- `duels`：待处理邀请及失效时间；应战后删除。
- `pvp_pairs`：同一对玩家最后一次论剑积分结算日。
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

涉及持久化结构时直接修改运行模型与 schema，提高开发期 schema 版本，使用新临时库测试。当前 schema 为 6，旧版库明确拒绝启动并保留原文件。不要保留历史字段双写。需要保留某份真实存档时，应另立明确的数据迁移任务，而不是默认销毁或假装兼容。

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
- PVP 双方确认才结算；每对玩家每日最多结算一次积分，切磋不消耗精力或发放经济奖励。
- 组队用同一战斗函数，每位参战成员胜利后获得一份各自抽取的奖励，不分摊掉落。
- `Battle.skill_uses` 按左右阵营、pet_id、skill_id 统计真实施放。PVE（含败退/平局）与积分 PVP 在原事务内调用 `mastery.award_mastery`，切磋不调用。不得根据战报文本或回合数猜测使用次数。

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

测试覆盖静态目录校验、同 ID 数据共享、十层成长、血脉、主属性/分支继承、天赋效果、技能成长、强化保留、灵卵容量、事务回滚、并发、重复消息、组队准备、论剑应战与适配器构造。真实 ASGI 测试会连接 `/onebot/v11/ws`，验证鉴权和收发，不只调用业务函数。

GitHub Actions 使用 Linux/Windows 和 Python 3.10/3.13。QQ 真机 AppID 权限、Markdown 审批和蓝字客户端呈现需另行验收，单元测试不代表平台授权已经通过。

固定种子矩阵的场景、准备程度、收益口径和留存结果见 [数值验收](BALANCE.md)。日常 pytest 含每个准备阵容 10 次的快速门禁；内容、公式、主动技能变更后另跑完整 100 次并审阅差异。脚本不得连接或修改 `SPIRIT_PET_DB`，仿真只使用临时数据库、生产 `loadout.combatant` 和真实 `fight`。

基础矩阵不包含血脉分支或辅助配装；专项脚本另外验证全部分支和主动效果，并保留未胜利的对照结果。效果观测器仅在单进程专项范围内临时包装 `effects.apply`，统计实际状态变化，退出或异常时恢复原函数；它不是机器人运行时组件，不应在运行中的服务进程里调用。

## 配置来源

`pyproject.toml` 保留参考仓库安装脚本生成的 NoneBot 运行项目布局，不猜测 PyPI 包模板：

- 参考提交：`97f43acba8dd185111d998c48d4e1cf5a069b117`。
- `scripts/install.sh` 的 TOML 生成段与 `scripts/install_termux.sh` 的 `write_pyproject()`。
- `[project]`、`[tool.nonebot]`、适配器配置表及 `plugin_dirs = ["src/plugins"]`。
- Python 最低 3.10、Pydantic 2 对应本项目实际 API；打包发布前另做分发配置与静态资源包含测试。
