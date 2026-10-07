# 静态内容规范

插件里的 `data/` 是**内容定义**，不是运行数据。所有文件 UTF-8 编码，使用标准 JSON，不允许注释、重复对象键或未声明字段。修改后重启加载，不在游戏运行中热改全局配置。

玩家存档位于 `SPIRIT_PET_DB` 指定的 SQLite 文件，二者不能混用。

## 文件分类

| 文件 | 定义 |
| --- | --- |
| pets.json | 种族、初始数值、初选标志、类别、主副属性、天赋引用 |
| pools.json | 召唤池、灵石价格、种族 ID 与抽取权重 |
| realms.json | 大境界顺序、属性倍率、该境界十层升到下一大境界的代价 |
| layers.json | 1-10 层、层数倍率、该层升下一层的代价 |
| bloodlines.json | 连续血脉等级、属性倍率、下一阶进化代价 |
| items.json | 道具种类、名称、效果与商店价格 |
| adventures.json | 奇遇文本、权重与奖励区间 |
| enemies.json | PVE 敌人、基础战斗属性与明确的主属性 |
| dungeons.json | 秘境准入境界、敌人列表、精力消耗、奖励、是否组队 |
| quests.json | 每日任务的事件、目标次数、奖励 |
| expeditions.json | 离线委托的名称、描述、境界门槛、精力成本与奖励范围，不含时间或玩家状态 |
| arena.json | 论剑赛季的积分规则、准入门槛、场次限额、奖励资格与固定奖励档位 |
| stages.json | 线性章节关卡、前置关卡、队伍模式、敌手、精力成本和首通奖励范围 |
| achievements.json | 稳定成就 ID、目标指标、完成条件文案和一次性静态奖励 |
| resonances.json | 双种族共鸣组合、说明文字与四项战斗属性倍率 |
| rules.json | 初始资源、签到奖励、训练收益、精力消耗、队伍人数与共鸣启用成本 |
| dao_names.json | 随机道号的定宽词段、组合模板，不保存已占用道号 |
| categories.json | 羽、兽、龙、甲、虫、植、蛇、灵八类定义 |
| elements.json | 五行、分支的父系引用、风雷毒及克制关系 |
| equipment.json | 装备槽位、固定属性、元素/类别/境界门槛 |
| skills.json | 技能效果、元素、倍率、学习门槛与秘笈引用 |
| talents.json | 种族天赋的名称、效果类型、强度与可选元素限制 |
| skill_levels.json | 技能等级、升到下一级消耗的熟练度、威力倍率 |
| forge_levels.json | +0 至 +10 强化倍率与下一级灵石、材料成本 |
| lineages.json | 各种族两条血脉分支、最低血脉、选择成本与四维成长倍率 |
| recipes.json | 每件装备的打造灵石/材料、基础分解回收、强化材料回收比例 |

除 `rules.json`、`dao_names.json`、`arena.json` 为对象外，其余文件均为对象数组。不要往这些文件写 `created_at`、`last_train`、`sign_day`、`expires_at`、`timestamp`、`cooldown`、玩家 ID 或库存数量。

冷却间隔、精力恢复间隔属于运行配置，放在 `.env`；某玩家的最后修炼时间、准备状态属于 SQLite。静态的“进化需要 3 个血脉精华”是成本，不是库存。

## 新增灵宠

在 `pets.json` 数组追加：

```json
{
  "id": "chiling",
  "name": "赤灵",
  "description": "离火灵根，善纳地脉灵息。",
  "starter": false,
  "stats": {"hp": 115, "attack": 28, "defense": 9, "speed": 24},
  "category": "beast",
  "elements": ["fire"],
  "primary_element": "fire",
  "talent": "moonfire_ambush",
  "initial_affinity": 0,
  "training_bonus": 0.1
}
```

需要能被召唤时，在 `pools.json` 的 standard 池 `entries` 中加入：

```json
{"species": "chiling", "weight": 8}
```

概率为该项权重除以池总权重，不要求权重和为 100。同一池不能重复引用同一个种族。随机领养仅从 `starter=true` 的种族等概率抽取；指定领养也不能绕过 starter 限制。召唤获得独立宠物实例，同种族可拥有多只，以实例编号切换，不自动合并。

初始种族固定为 `qingluan/xuanhu/baize/jiaolong`。扩充其他种族时 `starter` 必须为 false，并提供可达的召唤或灵卵来源。天赋引用必须存在；正式内容应为每种宠物配置贴合定位的神通，而不是复制属性、仅改名字。

`primary_element` 必须显式填写，且出现在不重复的 `elements` 中，不能通过数组位置推断。其余元素是副属性。怪物也遵守此规则。分支以 `elements.json` 的 `parent` 表示，例如冰的 parent 为 water；引用必须存在，不能自指或构成环。

`utils/elements.py` 统一展开祖先：冰可以满足水系门槛，水不能满足冰系门槛。攻击和防守的主属性均继承祖先克制关系；副属性不参与防御倍率。普攻取主属性，技能取自己的 element，不能为了多属性“优势相消”遍历整组副属性。

## 境界、层数与血脉

`realms.json` 数组顺序就是大境界序号。每个大境界都有完整的一至十层：

- 一至九层使用 `layers.json` 中当前层的 `advancement`。其中修为、灵石乘以“当前大境界序号 + 1”；道具数量不额外缩放。
- 十层使用 `realms.json` 中当前大境界的 `advancement`，成功后进入下一大境界一层。
- `advancement: null` 只允许出现在第十层与最后的大境界上。
- `bloodlines.json` 必须从 level 0 连续编号，最后一阶 `evolution: null`。
- 默认小境界与血脉进化必成，大境界成功率由内容加亲密加成决定，最多 100%。

成本示例：

```json
{
  "exp": 100,
  "stones": 200,
  "chance": 1,
  "items": {"bloodline_essence": 3}
}
```

更改或删除已有 ID、重排境界、缩短血脉等级会改变现有存档含义。开发期应创建新测试库验证，不能通过改名假装自动迁移老角色。

## 道具与奖励

道具种类：

- `consumable`：至少有一种 energy/exp/affinity 效果，使用数量会乘到每一种效果，精力与亲密封顶 100。
- `breakthrough`：仅有 `breakthrough_bonus`，只通过“灵宠突破 道具名”使用，不能直接服用，也不用于必成的小境界突破。
- `material`：无直接效果，用于进化或其他玩法成本。
- `equipment`：无消耗品效果，必填 `equipment_id` 指向装备；一份装备定义对应一个背包物品。
- `skill_book`：无消耗品效果，必填 `skill_id`，对应技能的 `book_item` 必须反向指回该物品。
- `pet_egg`：无消耗品效果，必填 `species_id`。使用时先检查名册容量，再消耗灵卵并创建独立宠物，不改变出战选择。
- `price: null`：不在商店出售；省略 price 也不出售。

通用玩法奖励使用区间对象，不混用数组与数字；论剑的赛季档位使用下文单独定义的固定数值结构：

```json
{
  "exp": {"minimum": 30, "maximum": 60},
  "stones": {"minimum": 50, "maximum": 80},
  "items": {"bloodline_essence": {"minimum": 1, "maximum": 2}}
}
```

固定奖励将 minimum 与 maximum 设成相同值。掉落可以为零，成本和权重必须为正，奖励最小值不能大于最大值。

## 共鸣定义

`resonances.json` 为对象数组。每项必须引用两个不同的已有种族，种族组合不能重复，且每个种族至少出现在一项组合中。`bonuses` 可定义 `hp`、`attack`、`defense`、`speed`；每项倍率为正且不超过 8%，总倍率不超过 10%。玩家状态和启用时间不写入静态文件。

`rules.json` 的 `resonance_cost` 定义启用成本，只能消耗灵石与材料。启用后属性加成只对组合内种族的当前出战宠物生效；该玩家的启用选择及时间存入 SQLite。

任务 event 仅允许 `train/feed/explore/pve/evolve`。领取不会推进任务；喂养和直接使用灵粮推进同一种任务；PVE 仅胜利计数。任务日和领取状态不出现在 JSON。

## 离线委托定义

`expeditions.json` 是对象数组，由 `domain/expedition_content.py` 的 `Expedition` 严格校验。它与每日任务 `quests.json` 分离，不使用 event 或累计次数。

```json
{
  "id": "herb_gathering",
  "name": "采灵药",
  "description": "寻访山野灵圃，采集可制成灵粮的草木精华。",
  "min_realm": "qiling",
  "energy": 25,
  "reward": {
    "exp": {"minimum": 15, "maximum": 25},
    "stones": {"minimum": 10, "maximum": 20},
    "items": {"spirit_food": {"minimum": 1, "maximum": 2}}
  }
}
```

- 仅允许 id、name、description、min_realm、energy、reward 六个字段，且全部必填；ID 和名称在本表中分别唯一，数组不能为空。
- `min_realm` 引用现有大境界 ID；`energy` 为 1-100 的整数，是出发成本，不是宠物当前精力。
- `reward` 复用前述奖励区间结构；物品 ID 必须存在，所有数量非负且 minimum 不大于 maximum，不接受数字字符串。
- 初版包含 `herb_gathering`（采灵药，启灵，25 精力）、`ore_survey`（寻锻矿，凝气，30 精力）、`essence_search`（探血髓，筑基，40 精力），分别提供灵粮、锻灵矿、血脉精华。
- 行程秒数统一来自 `.env` 中的 `SPIRIT_PET_EXPEDITION_DURATION`，默认 3600。此 JSON 不允许 duration、duration_seconds、started_at、finishes_at、settled_at 等时间字段。

每次派遣绑定的宠物、操作号、开始/完成时间、抽取后的实际奖励快照和领取状态属于 SQLite 的行程记录。奖励范围是静态定义，实际抽取结果是运行数据，不能写回内容目录。派遣时固定奖励快照，之后修改任务名称、时长配置或奖励区间，不应追溯改写既有行程。

修改委托定义后运行：

```bash
$HOME/myenv/bin/python -m pytest tests/test_expedition_content.py -q
```

## 论剑赛季定义

`arena.json` 是一个根对象，由 `domain/arena_content.py` 的 `ArenaRules` 与 `ArenaTier` 严格校验，加载为 `Catalog.arena`。所有字段显式必填，旧 `rules.json` 中的 `pvp_energy/pvp_rating_delta` 已移除，不做开发期兼容。

| 字段 | 默认值 | 定义 |
| --- | --- | --- |
| initial_rating | 1000 | 每个新赛季的初始积分 |
| min_realm | ningqi | 最低准入境界，引用 realms.json |
| max_rating_gap | 200 | 双方当前积分最大差距 |
| daily_matches | 5 | 每个玩家每日最多主动挑战场次，含平局 |
| pair_daily_matches | 1 | 同一对玩家每日最多完成场次 |
| pair_season_matches | 3 | 同一对玩家单赛季最多完成场次 |
| reward_matches | 10 | 领奖至少完成的主动挑战非平局场次 |
| reward_opponents | 4 | 主动挑战至少交手的不同非平局对手数 |
| rating_delta | 20 | 非平局胜负双方的积分变化量 |
| energy | 20 | 每场挑战者的精力消耗，整数 1-100；防守不消耗 |
| tiers | 见下表 | 按赛季最终积分选择的固定奖励档位 |

场次参数、积分差与积分变化量均为有上界的正整数，不接受数字字符串、浮点数或布尔值。同对手每日上限不能高于个人每日上限或同对手赛季上限；不同对手门槛不能高于非平局场次门槛；场次门槛不能超过最短 28 日自然月的每日场次容量。

`reward_opponents` 是下限而不是固定对手池大小。因此允许“10 场、至少 4 位对手、同对手每季 2 场”，玩家可以通过第五位对手补足场次。默认的 10 场、4 位、每对 3 场也可以满足奖励资格。平局消耗场次与精力，但不增加奖励资格所需的场次和不同对手数。

档位对象结构如下，不复用带 `exp` 的随机奖励模型：

```json
{
  "id": "qingyun",
  "name": "青云",
  "minimum_rating": 0,
  "stones": 300,
  "items": {"forge_ore": 3}
}
```

| 档位 | 最低积分 | 灵石 | 锻灵矿 | 血脉精华 |
| --- | --- | --- | --- | --- |
| 青云 qingyun | 0 | 300 | 3 | 0 |
| 凌霄 lingxiao | 1050 | 600 | 6 | 2 |
| 天阙 tianque | 1150 | 1000 | 10 | 4 |

档位数组不能为空，首档从 0 分开始，后续门槛严格递增。ID 和名称分别唯一；灵石与物品数量不能随档位提升减少，已有奖励物品也不能从更高档移除。每档至少有一种正数量奖励，物品 ID 必须存在，items 数量为正整数。奖励只含灵石和道具，不包含修为、宠物经验、时间字段或领取状态。

自然月边界、赛季标识、积分、每日计数、参战宠物、比赛结果、永久挑战消息键/回复、规则快照与领奖记录属于运行逻辑和 SQLite。论剑冷却等运行配置写 `.env`，不能加到静态 JSON。赛季创建时保存完整规则快照，内容调整仅影响之后创建的赛季，不追溯改写已有赛季。镜像防守不扣精力或日主动次数，也不增加领奖资格。

修改赛季定义后运行：

```bash
$HOME/myenv/bin/python -m pytest tests/test_arena_content.py -q
```

## 校验与维护

`domain/content.py`、`domain/battle_content.py` 声明字段、严格类型、上下限与 `extra="forbid"`；`content/catalog.py` 与 `content/validation.py` 校验 ID/名称唯一、层数完整、封顶阶段、各类引用、必需内容和可达的精力消耗。数字字符串不会自动转成数值。

内容错误会在插件导入加载时报告，不等到玩家随机抽中错误条目才暴露。测试运行：

```bash
$HOME/myenv/bin/python -m pytest tests/test_content.py tests/test_progression.py -q
```

新增字段时同时更新模型、调用方与对应测试；不要关闭 extra 校验或给错误引用兜底成某个默认物品。

## 类别、技能与装备扩展

宠物用一个 category 加一至四个 elements 描述，而不是用一串难以解析的“风火木宠物”作为类型。

```json
{
  "elements": ["wind", "fire"],
  "categories": ["avian", "beast"],
  "min_realm": "ningqi"
}
```

这份 requirements 表示：必须同时有风、火，类别属于羽族或兽族，并达到凝气。elements 空数组为不限制元素，categories 空数组为不限制类别。三灵鹿同时拥有风、火、木，可以通过此元素门槛；只有火的玄狐不可以。至少要存在一种兼容宠物，否则目录校验失败。

技能 kind 为 damage、heal 或 utility；前两者 coefficient 为正的攻击倍率或最大气血恢复比例，治疗比例不得超过 1。utility 的 coefficient 必须为 0，且必须有 effects。技能的 element 非空时，必须由 requirements.elements 或其祖先覆盖，不能把水技能标成“火宠也可学”。通用技能的 element 为 null。book_item 与 items 中 skill_id 必须互相引用。

装备 slot 为 weapon/armor/charm，对应灵器/护甲/饰品。bonuses 是 hp/attack/defense/speed 的非负固定增量，叠加在成长倍率计算之后，不随使用次数递增。穿戴与卸装使用 SQLite 库存事务，不修改 JSON。

`forge_levels.json` 必须完整包含 0-10 级。当前级的 `upgrade_stones/upgrade_items` 为升下一级成本，材料引用必须是 material。最后一级 upgrade_stones 为 null、upgrade_items 为空；仅 +0 的 bonus_multiplier 为 1，之后严格递增。该倍率只乘装备 bonuses，再向下取整，不能乘基础种族属性。

`skill_levels.json` 从 1 连续编号，当前级的 required_proficiency 是升下一级所需的熟练度，不是累积总量；满级为 null。power_multiplier 从 1 严格递增，实际技能系数乘此倍率。每次施放的熟练度由 rules.skill_proficiency_per_use 定义。运行中的 level/proficiency 存 learned_skills，不能写回 JSON。

天赋 kind 支持 fury、first_strike、lifesteal、counter、shield、regeneration、execute、evasion、venom、pierce。power 为 (0, 1] 的比例，只有 fury 可以设置 element 过滤，且应与所属宠物灵根兼容。所有天赋均由 `gameplay/talents.py` 解释，描述文案不能代替实际效果实现。毒伤剩余行动数、当前护盾、首次攻击状态只存在单场 Fighter 内存中。

学习、携带、穿戴以及构建战斗单位时均执行适用条件检查。只在图鉴显示限制但实际战斗不检查，或者只限制学习却允许借其他宠物携带，都是不允许的实现。

### 随机道号

`dao_names.json` 包含 `fields` 词段字典和 `templates` 字段名数组。例如一个模板 `["qualities", "images", "paths", "titles"]` 依次拼接气质、意象、修行和称谓，得到“玄云问道真人”；`["origins", "aspirations", "paths", "titles"]` 得到“青云听雪御剑散人”。JSON 只定义静态词库，不保存已占用道号或玩家数据。

每个词段只允许 1-4 个汉字、ASCII 字母或数字。同一字段内的词段必须等长，并按 SQLite `NOCASE` 规则去重；每个模板的总长度为 2-12 字，且不同模板的总长度必须不同。定宽保证同一模板的拼接边界唯一，异长保证不同模板没有相同输出，因此候选数是**真正不同的道号数量**，不是可能重名的组合数。加载时拒绝无法满足这些条件或总容量不足 10,000,000 的数据。

默认六个字段：`qualities` 与 `images` 各 64 个单字；`paths`、`origins`、`aspirations` 各 64 个双字词；`titles` 为 40 个双字称谓。两个模板分别生成 6 字和 8 字道号，每个模板有 `64 × 64 × 64 × 40 = 10,485,760` 个唯一输出，总计 **20,971,520** 个。扩充词库时保留字段定宽和模板异长约束，不必枚举全部结果。

`DaoNames.name_at(index)` 按混合进制把序号解码为一个道号，不构建候选全集。取名最多随机抽取 16 次序号，随机阶段不重复查询同一序号；碰撞后从玩家总数对应的序号开始循环查找，每批最多查询 128 个候选，至多检查“玩家总数 + 1”个不同序号或完整候选空间，以先到者为准。道号占用使用数据库唯一索引查询，不加载玩家对象或全表名字；事务和 SQLite 唯一约束负责并发安全。候选全部用尽时明确报错，不拼接数字或用户 ID。改名保持存档归属不变，运行中的占用状态始终仅保存于 SQLite。

## 主动效果

`Skill.effects` 最多三项，每项包含 kind、target、power、duration。duration 是受影响单位的后续行动次数，**不是时间戳、秒数冷却或运行中的剩余次数**。剩余次数只在 `Fighter.effects` 内存中维护。

- stun：敌方目标，power=0、duration=1。跳过一次行动并给予短暂免控。
- weaken/empower/ward：power 为 (0, 0.8]，duration 为 1-3 次；弱化针对敌方，增益/护盾针对 self 或 ally。
- cleanse/dispel：即时移除，power=0、duration=0。净化针对己方，驱散针对敌方。
- 同一技能不能混合敌我效果，不允许重复 kind/target。damage 只附敌方效果，heal 只附己方效果。
- 技能等级放大伤害、治疗、护盾量，不放大控制次数、弱化比例、攻击增益比例或免控次数。

示例：冰系伤害附带一次控制：

```json
{"kind": "stun", "target": "enemy", "power": 0, "duration": 1}
```

## 血脉分支与工艺

`lineages.json` 由 `domain/lineage_content.py` 定义。每个种族至少两条分支，species_id 必须存在，min_bloodline 至少为 1 且引用现有血脉。四维 stat_multipliers 各自限定 0.5-2，同种族的分支不能使用完全相同的四维；至少一项必须提升。cost 是必成选择成本，不含概率；道具成本必须引用材料。运行时只在 pets.lineage_id 保存选中的分支，不修改种族 ID。

`recipes.json` 由 `domain/crafting_content.py` 定义。每件 equipment 物品恰有一个配方，item_id/name 指向并对应物品；stones 为正，materials 与 salvage_materials 仅允许材料。材料必须有商店、初始资源或正数量奖励等非分解来源。enhancement_refund_percent 为 0-50 的整数百分比，不是概率。

分解回收通过 `salvage_yield` 统一计算：基础回收加每种累计升级材料投入乘回收百分比，按单件向下取整。校验遍历 +0 至 +10，要求每种材料回收不超过投入、整体严格损耗；有商店价格的回收不得比直接购买装备再分解更便宜。新增装备必须同时补配方，不能只在商店与装备图鉴出现而无法维护工艺链。
