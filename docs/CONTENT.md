# 静态内容规范

插件里的 `data/` 是**内容定义**，不是运行数据。所有文件 UTF-8 编码，使用标准 JSON，不允许注释、重复对象键或未声明字段。修改后重启加载，不在游戏运行中热改全局配置。

玩家存档位于 `SPIRIT_PET_DB` 指定的 SQLite 文件，二者不能混用。

## 文件分类

| 文件 | 定义 |
| --- | --- |
| pets.json | 种族、初始数值、初选标志、类别、主副属性、天赋引用 |
| pools.json | 召唤池、灵石价格、种族 ID 与抽取权重 |
| realms.json | 大境界顺序、属性倍率、该境界十层升到下一大境界的代价；境界奖励按已达境界序号派生 |
| layers.json | 1-10 层、层数倍率、该层升下一层的代价 |
| bloodlines.json | 连续血脉等级、属性倍率、下一阶进化代价 |
| items.json | 道具种类、名称、效果与商店价格 |
| adventures.json | 奇遇名称、文本、权重、奖励区间与 2-3 个互斥回响选项 |
| outing_scenes.json | 灵宠出游的目的地、属性检定、灵石区间、可选特产与首次见闻 |
| tracking_maps.json | 三张寻踪地图：16个行优先地点、两类各8处地貌与初始气息；不保存玩家目标 |
| herb_routes.json | 三处九点药山：行优先地点、进入脚程、既有材料与采集脚程、总脚程；入口无产物，每处采集必须允许往返 |
| nursery.json | 灵卵护育对象：两次护理预算、间隔、灵粮/精力消耗、原伙伴羁绊及三种互斥成长方向 |
| exploration_routes.json | 历练路线说明、境界门槛及其奇遇 ID；每条奇遇必须且只能属于一条路线 |
| enemies.json | PVE 敌人、基础战斗属性、明确的主属性与可选周期招式 |
| dungeons.json | 秘境准入境界、敌人列表、精力消耗、奖励、是否组队、一次性首通奖励 |
| quests.json | 每日任务的事件、目标次数、奖励 |
| daily_assignments.json | 今日课题的指标、目标值与一次性奖励，按自然日轮换三项 |
| daily_encounters.json | 每日路边际遇的名字、描述、2-3 个带成本/回报的选项，以及可引出次日续篇的 `next` |
| daily_followups.json | 由普通际遇选项引出的次日续篇，形状同际遇并带 `trigger` 回指来源际遇 |
| codex_rewards.json | 每个种族的一份一次性图鉴收集奖励，按稀有度递增 |
| expeditions.json | 离线委托的名称、描述、境界门槛、精力成本与奖励范围，不含时间或玩家状态 |
| arena.json | 论剑赛季的积分规则、准入门槛、场次限额、奖励资格与固定奖励档位；六档由青云 0 分到归元 1450 分 |
| stages.json | 线性章节关卡、前置关卡、队伍模式、敌手、精力成本和首通奖励范围 |
| stage_star_rewards.json | 关卡星数里程碑的星数门槛与一次性奖励，按星数递增 |
| arena_tier_rewards.json | 论剑各档位的一次性达成奖励，与 arena.json 的档位一一对应 |
| achievements.json | 稳定成就 ID、目标指标、完成条件文案和一次性静态奖励 |
| main_quests.json | 主线步骤的序号、前置、目标指标与一次性奖励，按序解锁 |
| journey.json | 行纪章节的境界、前置章节、故事文案、任务类型与目标、一次性奖励 |
| weekly_quests.json | 周常目标的指标、目标值与每周一次性奖励，按自然周重置；每个指标 1-2 个难度 |
| season_missions.json | 赛季目标的指标、目标值与每赛季一次性奖励，按自然月重置；每个指标 1-2 个难度 |
| titles.json | 称号的名称、条件指标、目标值与优先级，全部由存档即时派生；可统计五阶灵术精进奖励的永久领取凭证与飞升周目 |
| ascension.json | 飞升试炼三段（雷劫、心魔、天道）的顺序、说明与敌手引用，不含玩家状态 |
| shop_rotation.json | 灵坊每日特供池：物品、折扣百分比与当日库存；按北京时间日期轮换三件 |
| resonances.json | 双种族共鸣组合、说明文字与四项战斗属性倍率；21 组覆盖全部 27 族，含跨系配对 |
| rules.json | 初始资源、签到奖励、训练收益、精力消耗、队伍人数、共鸣启用成本、灵宠培育成本、今日秘境奖励、强化继承成本、关卡星级回合门槛、灵坊回收比例、灵田互助浇水（缩短秒数/每日次数/灵石）、信箱邮寄（保存天数/每日封数/单封上限/信箱容量/可寄种类）、好友（名册上限/申请有效小时数）、战报分享（每日次数/分享码有效天数/每页条数）、演武场（每日次数）与借力（借出比例/保留天数） |
| dao_names.json | 随机道号的定宽词段、组合模板，不保存已占用道号 |
| categories.json | 羽、兽、龙、甲、虫、植、蛇、灵八类定义 |
| elements.json | 五行、分支的父系引用、风雷毒及克制关系 |
| equipment.json | 装备槽位、固定属性、元素/类别/境界门槛 |
| equipment_sets.json | 装备套件组成、名称、说明、完整套件属性加成与三阶共鸣成本/固定增幅 |
| skills.json | 技能效果、元素、倍率、学习门槛与秘笈引用 |
| talents.json | 种族天赋的名称、效果类型、强度与可选元素限制 |
| skill_levels.json | 技能等级、升到下一级消耗的熟练度、威力倍率 |
| forge_levels.json | +0 至 +10 强化倍率与下一级灵石、材料成本 |
| lineages.json | 各种族两条血脉分支、最低血脉、选择成本与四维成长倍率 |
| recipes.json | 每件装备的打造灵石/材料、基础分解回收、强化材料回收比例 |

除 `rules.json`、`dao_names.json`、`arena.json`、`nursery.json` 等规则对象外，目录文件为对象数组。不要往这些文件写 `created_at`、`last_train`、`sign_day`、`expires_at`、`timestamp`、`cooldown`、玩家 ID 或库存数量。

冷却间隔、精力恢复间隔属于运行配置，放在 `.env`；某玩家的最后修炼时间、准备状态属于 SQLite。静态的“进化需要 3 个血脉精华”是成本，不是库存。

## 灵卵护育合同

`nursery.json` 的三种照料方向各只给修为、亲密、羁绊中的一种（单次上限20/2/8），可重复集中或分配两次预算。每次消耗既有灵粮1与原伙伴精力6；首次与相邻照料至少间隔600秒，入巢1200秒后可迎接。原伙伴在有照料且成功迎接时获得羁绊经验4；自然等待不获额外成长。不改灵卵来源、即孵规则、每日任务或战斗奖励。

巢中状态及完整回复写入 schema 28 的 `duel_actions`（`kind=nursery`），保存原灵卵/种族/伙伴/规则/名称/成长/时间；所有旧斗法及其他动作消费者排除此类型。`quest_progress.nursery_day_<北京时间日期>` 只记录入巢预算，跨日不删除；照料/孵化/返还和永久回执同一事务。巢号、步号守卫阻止旧控件作用于下一枚灵卵，原消息过期重投仍重放原回复。名册满、封存或行程阻塞时保留整巢；撤回不依赖原伙伴仍存在，返还原卵但不获成长、不退已花资源。

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

概率为该项权重除以池总权重，不要求权重和为 100。同一池不能重复引用同一个种族。可选 `guaranteed_batch_size` 和 `guaranteed_species` 配置批量保底，两者必须同时提供；批次数量达到门槛且随机结果尚未命中保底种族时，最后一抽会从保底种族中按原权重抽取。standard 池的十连保证至少一只珍稀灵宠。随机领养仅从 `starter=true` 的种族等概率抽取；指定领养也不能绕过 starter 限制。召唤获得独立宠物实例，同种族可拥有多只，以实例编号切换，不自动合并。

初始种族固定为 `qingluan/xuanhu/baize/jiaolong`。扩充其他种族时 `starter` 必须为 false，并提供可达的召唤或灵卵来源。天赋引用必须存在；正式内容应为每种宠物配置贴合定位的神通，而不是复制属性、仅改名字。

`primary_element` 必须显式填写，且出现在不重复的 `elements` 中，不能通过数组位置推断。其余元素是副属性。怪物也遵守此规则。分支以 `elements.json` 的 `parent` 表示，例如冰的 parent 为 water；引用必须存在，不能自指或构成环。

`utils/elements.py` 统一展开祖先：冰可以满足水系门槛，水不能满足冰系门槛。攻击和防守的主属性均继承祖先克制关系；副属性不参与防御倍率。普攻取主属性，技能取自己的 element，不能为了多属性“优势相消”遍历整组副属性。

`enemies.json` 的高阶敌人可同时定义 `signature_skill` 与正整数 `skill_every`；前者必须引用 `skills.json`，且招式元素必须与敌人元素兼容。敌人每到设定行动次数施展招式，其余行动普通攻击。没有这两个字段时敌人只会普通攻击。

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

`battle_supplies.json` 定义当天战斗可消耗的战备灵酿。每项包含稳定 `id`、展示名称、说明、既有 `item_id` 与 `dealt`/`taken` 倍率；`Catalog` 会校验引用物品存在且为 `consumable`，倍率在 0.75-1.25 之间，且不能同时保持 1.0/1.0。当前三项分别引用回元丹、蕴灵丹、同心丹，数据文件只保存内容，不保存玩家选择。

战备运行状态写入既有 `quest_progress`：`battle_supply_used_<北京时间日期>` 表示当天已经消耗过一枚，`battle_supply_active_<北京时间日期>_<战备 id>` 表示当前启用项。选择、扣除物品和两条凭证在同一事务中提交；清除只删除 active 凭证，不退回物品，used 凭证保留以阻止当天再次消耗。跨日查询只匹配当天前缀，因此旧凭证自然失效，重启和缓存清理无需迁移。战斗构造从当天凭证读取倍率，永久战报把名称与实际倍率写入快照；未准备战备的倍率固定为 1.0。

通用玩法奖励使用区间对象，不混用数组与数字；论剑的赛季档位使用下文单独定义的固定数值结构：

```json
{
  "exp": {"minimum": 30, "maximum": 60},
  "stones": {"minimum": 50, "maximum": 80},
  "items": {"bloodline_essence": {"minimum": 1, "maximum": 2}}
}
```

固定奖励将 minimum 与 maximum 设成相同值。掉落可以为零，成本和权重必须为正，奖励最小值不能大于最大值。

逐宠亲密里程碑奖励由 `gameplay/affinity_milestone_rewards.py` 固定定义，读取现有 `pets.affinity` 进度，并将每宠每档领取凭证写入 `quest_progress`。25/50/75/100 四档物品分别要求为灵粮/同心丹/回元丹消耗品和血脉精华材料；目录读取会校验奖励物品仍存在且类型相符，领取凭证与资源奖励必须处于同一事务。该内容不是玩家状态，不写入 JSON 或新增存档列。

逐宠血脉进阶奖励由 `gameplay/bloodline_milestone_rewards.py` 固定定义，读取 `pets.bloodline` 当前等级，并将每宠每级凭证写入 `quest_progress`。灵血至仙血四档分别发放固定灵石和血脉精华；奖励精华必须仍是 `material`，缺失或类型不符时不结算。该奖励不改变 `bloodlines.json` 的进化成本与倍率，也不需要新增存档列。

逐宠血脉分支觉醒礼由 `gameplay/lineage_awakening_rewards.py` 固定定义，读取 `pets.lineage_id` 的已选分支，并将凭证按宠物与稳定分支 ID 写入 `quest_progress`。固定奖励为 100 灵石与 1 枚血脉精华；精华须仍定义为 `material`。分支选择、成本、门槛与属性倍率保持不变，无需新增存档列。

`achievements.json` 的每项只定义稳定 ID、名称、说明、指标、目标和一次性奖励，不保存玩家进度。`duplicate_species` 指至少拥有两只实例的种族数量；封存宠物仍属于玩家，也计入此指标。动态进度从 SQLite 当前存档与永久记录计算，领取凭证和奖励快照单独持久化。玩家页与详情按当前定义展示说明、派生进度、状态和奖励预览；领取时必须把成就 ID/名称、指标/目标、领取时进度、灵石、物品 ID/当时名称/数量及幂等回复写入既有 `achievement_claims` 记录。已领取详情只读这份快照，不能从更新后的静态目录重新计算实际奖励；发奖、领取凭证、快照与回复必须在同一事务内提交，任一奖励写入失败时全部回滚。新增成就时同步验证稳定 ID、唯一名称、目标可达及奖励物品引用，不向内容目录写玩家状态或累计计数。指标词汇同时覆盖装备强化等级（`max_enhancement`，取 `equipment` 与 `unequipped_equipment` 的最大强化等级）、切磋胜场（`spar_wins`）、累计战斗场次（`battles_fought`）、装备收藏（`equipment_owned`）、成就领取数（`achievements_claimed`）与共鸣启用（`resonances_enabled`），全部只读派生，不新增表或计数列。`max_enhancement` 的上限由 `forge_levels` 阶梯决定，因此 +10 里程碑必须在册。领取式系统也各有指标：`journey_claims`、`echo_claims` 与 `first_clear_claims` 分别统计 `quest_progress` 中 `journey_`、`echo_` 与 `first_clear_` 前缀的已领取标记；`equipment_set_claims` 只统计配置有奖励且当前仍存在于套装目录的精确领奖凭证。上限由对应目录条目数决定，成就目标不能超出可达上限。

`titles.json` 的每项只定义稳定 ID、名称、说明、指标、目标值与优先级（`order` 从 1 连续），不保存玩家状态；称号由当前存档即时派生，取已获得中优先级最高的一个。指标词汇复用成就指标，另加 `main_quest_claims`、`weekly_claims`、`skill_mastery_rewards`、`battle_pass_premium_claims`、`ascended_pets` 与 `rebirth_count` 六个领取/派生指标。`ascended_pets` 统计 `ascended_<宠物编号>` 飞升凭证数量，`rebirth_count` 读取 `quest_progress` 的周目计数；两者都不新增列。校验与成就同一套：`order` 连续、名称唯一、`指标 + 目标` 组合不得重复，且目标值不得超出该指标的可达上限（上限由对应目录条目数决定，例如 `lineage_branches` 为血脉分支数、`battle_pass_premium_claims` 为进阶节点数、`max_affinity` 为 100、`resonances_enabled` 为 1），因此不能定义玩家永远拿不到的称号。两类指标不做上限校验，追加内容时可以继续抬高目标：一类随游玩次数无限累积（论剑/秘境胜场、战斗场次、切磋胜场、连胜、成就领取数、`expedition_claims`、`best_bond_streak`、`ascended_pets`、`rebirth_count`）；一类由玩家配置的上限决定而非内容（`pets_owned` 取 `spirit_pet_max_pets`、`skill_mastery_rewards` 取名册上限 × 灵术数、`equipment_owned` 可重复持有同一件装备）。上限表由成就与称号共用，任一侧新增内容后都要重新核对。

`journey.json` 的每章只定义境界、前置章节、故事文案、任务与一次性奖励，不保存玩家进度。校验要求：境界必须存在；每个境界至少一章；恰好一个首章（`previous_id` 为空），其余章节的前置必须存在且境界不倒退；整条链必须无环、无分叉且覆盖全部章节；任务目标按类型引用对应目录（秘境、奇闻、种族、共鸣、境界），且秘境 `min_realm`、奇闻所属路线的 `min_realm` 与 `reach_realm` 目标都不得高于本章境界（避免出现无法达成的章节）；只有 `win_at` 允许 `count` 大于 1；奖励物品必须存在。前置境界不得倒退，因此追加章节只能接在链尾且境界不低于末章（渡劫境的终章 `journey_15`/`journey_16` 即如此）。进度由永久战报、奇闻发现记录、灵宠种族与境界、当前共鸣即时派生，领取标记写入 `quest_progress`。

`season_missions.json` 的每项只定义指标、目标、说明与一次性奖励，不保存玩家进度。指标词汇为 `season_matches`（本赛季论剑场次）、`season_wins`（本赛季论剑胜场）、`season_pve`（本赛季秘境或关卡获胜）、`season_discoveries`（本赛季发现奇闻）与 `season_claims`（本赛季领取成就奖励），五种指标必须全部在册且不得出现重复的“指标 + 目标”组合；奖励物品必须存在。进度全部按当前赛季窗口（`utils.time.season_bounds` 给出的北京时间自然月起止）从带时间戳的既有记录派生，领取标记写入 `quest_progress` 并保存赛季起始时间，因此换季自动重置。

`daily_assignments.json` 的每项只定义指标、目标、说明与一次性奖励，不保存玩家进度。指标词汇为 `daily_pve`（今日秘境或关卡获胜）、`daily_pvp`（今日论剑场次）、`daily_discovery`（今日发现奇闻）、`daily_expedition`（今日领取委托）、`daily_claim`（今日领取成就奖励）与 `daily_training`（今日修炼），六种指标必须全部在册且不得出现重复的“指标 + 目标”组合；奖励物品必须存在。池中现有 12 项（六种指标各 1-3 个难度，同一指标的不同目标共用同一条当日进度），每天按北京时间日期序数确定性轮换出三项（`pool[(序数 * 3 + i) % len(pool)]`），同一天稳定、四天覆盖全池；进度只统计当天的记录，领取标记写入 `quest_progress` 的 `daily_assignment` 行，`progress` 为 `序数 * 10 + 所选序号`，因此次日自动重置且只保留一行。

`arena_tier_rewards.json` 的每项只定义 `tier`、`stones` 与 `items`，不保存玩家进度。`tier` 必须与 `arena.json` 的档位 id 一一对应（不多不少），`items` 必须引用已有物品，`stones` 非负且与 `items` 至少有一项非空。奖励是固定值而非区间；档位由 `season_entries.rating` 即时派生，领取标记写入 `quest_progress` 的 `arena_tier_<赛季号>_<档位 id>` 行，因此每档每季只发一次、换季自动重新可领。

`stage_star_rewards.json` 的每项只定义 `stars`、`stones` 与 `items`，不保存玩家进度。星数门槛为正整数、互不重复且不超过 `3 × stages.json 条目数`（当前 48）；`items` 必须引用已有物品，`stones` 非负且与 `items` 至少有一项非空。奖励是固定值而非区间；星级由 `battle_records` 中该玩家的获胜记录即时派生（取最少回合数，按 `rules.json` 的 `stage_star_rounds` 每敌手门槛换算），领取标记写入 `quest_progress` 的 `stage_stars_<星数>` 行，因此每档只发一次且永久有效。

`codex_rewards.json` 的每项只定义 `species`、`stones` 与 `items`，不保存玩家进度。`species` 必须引用已有种族且每个种族恰好一条（不多不少），`items` 必须引用已有物品，`stones` 非负且与 `items` 至少有一项非空。奖励是固定值而非区间，领取时按单值发放；收集状态由 `pets` 表即时派生（封存宠物仍计入），领取标记写入 `quest_progress` 的 `codex_<种族>` 行，因此每族只发一次且永久有效。

`collection_rank_rewards.json` 是收集榜名次奖励数组，由 `domain/collection_rank_reward_content.py` 的 `CollectionRankReward` 校验：每项声明 `rank`（1-10）、`name`、`stones`（非负）与 `items`（物品 id → 正整数），奖励不能全空。`Catalog._validate_collection_rank_rewards` 强制档位恰为 1、3、10；物品必须存在且为 `consumable`/`material`；名次越高奖励不得越低。领取标记写入 `quest_progress` 的 `collection_rank_reward_<档位>`，`progress` 保存领取时的实际名次，`claimed=1`；因此每档只发一次，掉出榜单不撤回。

## 禁地定义

`forbidden.json` 是禁地对象数组，由 `domain/forbidden_content.py` 严格校验，当前三处禁地按北京时间自然周轮换开放。进度凭证 `forbidden_<周>_<层id>`／`_all` 永久保留，因此 `灵宠禁地 战历` 能按周回顾历史；层被撤下后按 id 标注。每处禁地定义 `id`、`name`、`description`、`restriction`、`bonus` 与 `depths`，不接受额外字段。

```json
{
  "id": "ember_crypt",
  "name": "焚骨禁地",
  "description": "地火未熄的古战场，焦土上只容一道身影独行。",
  "restriction": {"type": "solo"},
  "bonus": {
    "exp": {"minimum": 0, "maximum": 0},
    "stones": {"minimum": 200, "maximum": 260},
    "items": {"forge_ore": {"minimum": 3, "maximum": 3}}
  },
  "depths": [
    {
      "id": "ember_crypt_1",
      "name": "焦土外环",
      "description": "余烬里游荡的傀儡仍在守着旧日的门。",
      "order": 1,
      "min_realm": "ningqi",
      "enemies": ["wood_guard"],
      "energy": 20,
      "reward": {
        "exp": {"minimum": 120, "maximum": 180},
        "stones": {"minimum": 100, "maximum": 140},
        "items": {"forge_ore": {"minimum": 1, "maximum": 1}}
      }
    }
  ]
}
```

`restriction.type` 只能是 `solo`（只允许一只灵宠出战）、`duo`（只允许两只）或 `same_element`（出战灵宠须同属一种主属性）。每处禁地的 `depths` 为 2-5 层，`order` 必须从 1 连续递增，层 `id` 与层名在同一禁地内唯一，且层 `id` 在全部禁地间也唯一（周进度凭证以层 id 结尾）。`min_realm` 引用 `realms.json`，`enemies` 引用 `enemies.json`，`energy` 为正且不超过 100，`reward` 与 `bonus` 的物品必须存在，单层奖励与全清奖励至少各有一项非空奖励（`bonus.exp` 可为 0，此时不要求出战宠物闲置）。禁地层只复用现有敌手，不定义新属性或新战斗规则。

轮换、周进度与本周最佳回合属于运行逻辑：禁地按 id 排序后以 `(周一零点时间戳 // 86400) % 禁地数` 选择，同一周稳定、下周前移；每层首通写入 `quest_progress` 的 `forbidden_<周一零点时间戳>_<层id>`（`progress` 为该场回合数），全清写入 `forbidden_<周一零点时间戳>_all`，换周自动重新开始，旧周凭证保留为历史。本周最佳回合由永久 `battle_records`（`kind='pve_stage'`、本人为胜方、`played_at` 在当周内）取最少回合派生，不写入 JSON 或玩家档案。

## 膳房定义

`cuisine.json` 是菜谱对象数组，由 `domain/cuisine_content.py` 严格校验。每道菜定义 `id`、`name`、`description`、`level`（1-10，但不得超过 `rules.json` 的 `cuisine.max_level`）、`heat`（1-5）、`stones`、`ingredients`，以及 `item` 与 `effects` 中的**恰好一个**：`item` 指向单膳产出的消耗品，`effects` 表示宴席当场作用于全体伙伴的恢复量。

```json
{
  "id": "rice_porridge",
  "name": "灵米粥",
  "description": "以灵米慢煨的暖粥，最寻常也最养人。",
  "level": 1,
  "heat": 1,
  "stones": 10,
  "ingredients": {"spirit_food": 2},
  "item": "meal_rice"
}
```

菜谱等级必须从 1 起连续（当前 1-5），`ingredients` 1-4 项且引用已有物品，单膳的 `item` 必须引用 `kind='consumable'` 且 `price` 为空的物品（只在膳房产出，不进入灵坊、不可回收），宴席的 `effects` 只能含精力/修为/亲密且至少一项为正、不得包含破境加成。`stones` 与 `ingredients` 合计不能为空；`heat` 参与每日灶火预算。

厨艺等级与灶火属于运行逻辑：等级 = `min(max_level, 1 + 已烹饪过的不同菜谱数)`，由 `quest_progress` 的 `cuisine_dish_<菜谱id>`（值为累计份数）派生；当日灶火消耗记在 `cuisine_heat_<北京日期>`，换日自动重置。宴席只作用于在册、未封存且未外出派遣的伙伴，精力与亲密按 100 封顶，修为照常累加；单膳产物通过既有 `灵宠使用`/`灵宠喂养` 生效。以上状态不进入静态 JSON，也不新增表列。

## 洞府定义

`cave.json` 是洞府设施对象数组，由 `domain/cave_content.py` 校验。每处设施定义 `id`、`name`、`description`、`effect`（`energy` / `affinity` / `item`）、`yields`（每级一个正整数，2-10 级且不得递减）、可选的 `item`（仅 `effect='item'` 必填）与 `upgrades`（级数减一步，每步含 `stones` 与 `items`）。

```json
{
  "id": "spring",
  "name": "灵泉",
  "description": "引地脉灵泉入洞府，每日凝神一次，为一只伙伴补回精力。",
  "effect": "energy",
  "yields": [30, 45, 60, 75, 100],
  "upgrades": [
    {"stones": 300, "items": {"spirit_food": 2}},
    {"stones": 700, "items": {"spirit_food": 4}},
    {"stones": 1500, "items": {"spirit_food": 6}},
    {"stones": 3000, "items": {"spirit_food": 8}}
  ]
}
```

`effect='item'` 时必须给 `item` 且指向已有物品（当前为 `exp_pill` 蕴灵丹），其余两类不得带 `item`；`upgrades` 数量必须正好是 `yields` 长度减一，每步至少要花灵石或材料（不接受免费升级）。所有升级材料与产出物品都会在 `Catalog` 载入时校验存在性。

等级与每日状态属于运行逻辑：`cave_<设施id>_level` 存当前等级（缺省 1），`cave_<设施id>_day_<北京日期>` 记录当日是否已使用，均写入既有 `quest_progress`，不新增表列。精力与亲密按 100 封顶，丹房产物直接进入乾坤袋；设施不产生被动收益，也不影响战斗、掉落或商店价格。

## 回廊定义

`corridor.json` 是回廊对象数组，由 `domain/corridor_content.py` 校验。每条回廊定义 `id`、`name`、`description`、`energy`（1-100）、`max_floor`（5-60）、`base_enemy`（已有敌人）、`scaling`（气血/攻击/防御/速度的每层复利率，至少一项为正）、`stones_per_floor` 与 `exp_per_floor`（`base` + `growth × (层数-1)`）以及 `milestones`（层数唯一递增、不超过 `max_floor`，物品必须存在）。

```json
{
  "id": "corridor",
  "name": "无尽回廊",
  "description": "回廊深处每一层都比上一层更凶险；随时可以收手兑现，也可以再赌一层。",
  "energy": 6,
  "max_floor": 30,
  "base_enemy": "wood_guard",
  "scaling": {"hp": 0.18, "attack": 0.14, "defense": 0.12, "speed": 0.10},
  "stones_per_floor": {"base": 10, "growth": 6},
  "exp_per_floor": {"base": 8, "growth": 4},
  "milestones": [
    {"floor": 5, "items": {"forge_ore": 2}},
    {"floor": 30, "items": {"exp_pill": 5}}
  ]
}
```

敌人属性按 `(1 + rate) ** (层数 - 1)` 复利放大后取整，`hp/attack/speed` 至少为 1；因此不需要为回廊新增敌人数值，调平衡只改 `base_enemy` 与 `scaling`。层奖励是线性的，深度收益靠层数本身放大，里程碑只补材料，不设额外货币。

可选 `paths` 定义五层一段的岔路（当前三条），每条包含唯一 `id`/`name`、`energy`（1-100）、`hp_percent`/`attack_percent`/`speed_percent`/`reward_percent`（整数 50-200，默认 100）。`common` 是常道的保留 ID，不能用作岔路。现配疾行道为精力 4、敌速度 125%；护灵道为精力 8、敌攻击 85%；寻宝道为精力 6、敌气血/攻击 120%、灵石与修为 130%。敌手倍率在逐层复利后向下取整，气血/攻击/速度至少为 1；奖励每层单独向下取整，材料不乘倍率。常道始终沿用 `energy` 与原始敌手和奖励。

运行状态写在既有 `quest_progress`：`corridor_floor` 存下一层待战层数，`corridor_best_<北京周一零点时间戳>` 存本周最深清层；`corridor_path_start`/`corridor_path_id_<id>` 与各参数行冻结本段选择，换段失效，重新择路时替换快照；`corridor_pending_stones`/`corridor_pending_exp` 累计实际赢得的金额，不由后续路线重算。旧版没有这两行时按原线性规则派生，首次成功战斗转为累计值，纯查询不写入。结束一局清掉层数、路线与待领值，保留周最佳与 `corridor_receipt_<操作键 SHA256>` 永久凭证；同一择路/收手消息不能作用于新局。

战报以 `pve_stage` 类型、`corridor_<层>` 为键记录真实修改后的敌手快照，不写 `pve_stage_progress`。收手全额结算累计奖励，战败或平局减半且不给里程碑，第 `max_floor` 层胜利自动按收手结算，避免越界层。路线与累计值和资源/战报在原事务内一起提交或回滚，schema 仍为 26。

## 斗法定义

`duels.json` 是斗法护法数组，由 `domain/duel_content.py` 校验：每项声明 `id`、`name`、`description`、`realm`（已有境界 id）、`stats`（四维）与 `reward`（`exp`/`stones` 区间加可选物品）；奖励必须至少发灵石或修为之一。`Catalog._validate_duels` 要求表非空、境界存在、奖励物品都在 `items.json` 里。当前七位护法覆盖启灵至渡劫七个境界，四维沿用既有递增带并对齐同境界秘境敌手的量级。

```json
{
  "id": "songfeng",
  "name": "松风道人",
  "description": "启灵境入门护法，出招直来直去，正好试手。",
  "realm": "qiling",
  "stats": {"hp": 150, "attack": 18, "defense": 4, "speed": 20},
  "reward": {
    "exp": {"minimum": 40, "maximum": 60},
    "stones": {"minimum": 50, "maximum": 70},
    "items": {"forge_ore": {"minimum": 1, "maximum": 1}}
  }
}
```

`rules.json` 的 `duel` 由 `DuelRule` 校验：`energy` 为每回合精力（不超过 100），`exchanges` 限定 3-20，`stances` 至少两条且名称唯一；每条出手的 `dealt`/`taken` 都在 0.5-1.5 之间、必须同向移动（拒绝纯增益或纯亏损），整套出手还必须同时给出进攻与防守两种选择。

```json
{"energy": 3, "exchanges": 12,
 "stances": {"assault": {"name": "抢攻", "dealt": 1.3, "taken": 1.2},
             "feint": {"name": "游斗", "dealt": 1.12, "taken": 1.06},
             "guard": {"name": "稳守", "dealt": 0.85, "taken": 0.7}}}
```

`intents` 是 2–6 个 `assault` / `guard` / `feint` 的循环序列，至少两种不同招式；旧内容缺字段默认三招循环。七护法各有不同序列。目录要求三种标准出手 id 都存在。按本回合序号循环读取招式，稳守克抢攻、游斗克稳守、抢攻克游斗；破招出伤/承伤乘 1.15/0.85，同招 1/1，受制 0.85/1.15，再与原出手倍率相乘并受既有战斗倍率边界限制。护法自身不额外套用出手倍率。

运行气血仍写在既有 `quest_progress` 四行，周奖励凭证不变。schema 28 的单表 `duel_actions` 保存每个成功开局/出手/认输：唯一 `operation_id`、归属玩家、时间、局次/原伙伴/护法与规则/状态/选择/气血快照和完整 `Reply`；按玩家与递减 action_id 索引查询，分页只取五行。新局按开局快照读对手，不依赖内容列表重排；气血绑定原伙伴，装备成长仍按原宠实时读取。永久操作归属在 handler 前校验，缓存删除后跨命令重投也不会再执行；跨身份拒绝。周胜仍只写原周凭证，不写 `battle_records`、`pve_stage_progress` 或额外计数。

27→28 先验证冻结结构与完整性，再创建私密一致备份，单事务建表/索引及更新版本，失败回滚。`legacy_schema27` 剥新表，26 及更早版本按原冻结链继续。旧四行局保持中立倍率至结束，首次成功出手才绑定伙伴并开始留新记录；UID、旧周胜和鱼篓原行全部保留，不补造历史。

## 师徒定义

`rules.json` 的 `mentor` 由 `MentorRule` 校验：`max_apprentices`（1-5，实配 3）、`request_hours`（1-72，实配 24）、
`graduate_realm`（境界 id，实配 `zhuji` 筑基）、`lesson`（`MentorLessonRule`：`energy` 1-100、`exp` 1-500、
`stones` 非负、`daily_limit` 1-10；实配 10/30/20/3）以及 `mentor_reward`/`apprentice_reward` 两份奖励。
`Catalog._validate_mentor` 要求出师境界存在、且不是起始境界（否则开局即出师），并校验两份奖励的物品引用。

传道状态是师父行上的 `mentorlesson_<北京日期>_<徒弟 user_id>`，`progress=1`；当天总次数按同一前缀计数，
跨日换 key 自动重置。传道只写这一行并扣师父伙伴精力、加徒弟伙伴修为与师父灵石，不写战报、不推进成就/任务。

关系存两行 `quest_progress`，成对写入、成对删除：徒弟行 `mentorlink_<师父 user_id>`、师父行
`apprentice_<徒弟 user_id>`。缺一半即视为没有关系，因此不会出现「单边师徒」。拜师帖是师父行上的
`mentorreq_<徒弟 user_id>`，`progress` 存到期时间戳，读取时按 `progress > now` 过滤，不需要清理任务。

出师凭证是徒弟行上的 `graduated` 一行：它让已出师者无法再次拜师，也就堵住了「拜师—被逐—再拜师」
重复领取谢礼的路径。谢礼用模块内的 `_pay` 发放（只发灵石与物品），刻意不走 `rewards.grant`——
后者顺带发修为并要求收礼方伙伴空闲，会让出师因为师父正在外派而失败。

## 约战定义

`rules.json` 的 `spar_request` 由 `SparRequestRule` 校验：`expires_hours` 限定 1-72，实配 24。约战没有内容文件——
它借用的是双方现有阵容，不产生新的敌手、奖励或掉落，因此没有可调数值表。

状态是对方名下一行 `quest_progress`：`spar_req_<发起者 user_id>`，`progress` 存到期时间戳。不发奖、不扣资源，
所以不存在托管与结算一致性问题；应战成功即删除该行，撤回同样删除。过期条目由读取端按 `progress > now` 过滤，
不做后台清理，也不会阻塞同一发起者的再次约战（重复发起覆盖同一行）。

## 今日汇总定义

`灵宠今日` 没有内容文件与规则数值：它是纯入口聚合，每一条都由来源模块自己的只读 helper 生成
（`checkin_rewards.signed_today`/`claimable`、`daily_assignment.claimable`、`free_summon.available`、
`mailbox.inbox`、`affinity_milestone_rewards.claimable`、
`realm_milestone_rewards.claimable`、`expeditions.running_rows`、`merchant.todays`/`delivered`/`_missing`、
`drill.remaining`、`codex_trials.weekly_slots`/`weekly_cleared`），本模块不复制它们的业务规则，也不写任何表。

因此加一条 `rules.today` 只会是伪配置；页面的唯一契约是「只读」：打开前后整库快照必须逐位相同。
若某个来源将来需要新的判定，应先在它自己的模块里暴露只读 helper，再由今日页调用，而不是在今日页里重算。

## 配装预设定义

配装没有内容文件与规则数值：它只是玩家自己穿在身上的三件灵物的快照，不存在可调的刻度，因此任何 `rules.gear_preset` 都只会是伪配置。每只伙伴固定 3 套。

预设不复制装备，只记录「哪个部位是哪个物品、强化到几」，所以应用时走的是与 `灵宠装备` 同一条真实路径（从背包取出、被替换的退回背包），没有第二种物品来源。数据落在 `quest_progress`，每个部位一行：

```
gear<伙伴编号>_<套号>_<部位>_<强化等级>_<物品id>
```

`item_id` 放在最后，因此键可以用一次 `split("_", 4)` 解析，即使物品 id 本身含下划线也不会错位。头部 `gear<编号>` 以数字结尾、套号与强化等级都是十进制数字、部位必须是 `weapon`/`armor`/`charm` 之一，任一不成立的行被视为外来键并忽略。

应用前会逐件校验：物品仍在该玩家背包中（+0 在 `inventory`，+N 在 `unequipped_equipment`），或本来就穿这只伙伴身上。缺少任何一件都整笔拒绝、零写入——不会出现「换了一半」的伙伴。

## 每周图鉴试炼定义

`codex_trials.json` 的单个图鉴试炼条目新增三项：`weekly_slots`（1-5，实配 3）、`weekly_bonus`（三场全清奖励）与
`rotations`（每周轮换条件，实配 5 条）。三者必须同进同退：只写 `weekly_slots` 不写 `weekly_bonus`（或反之）、
声明了 `rotations` 却没有 `weekly_slots`、或轮换条数少于槽位数，都会在加载期被拒绝——否则周页会渲染出一个永远
无法结算或恒定重复的周。

每条 `CodexRotation` 只武装**一个**条件，由 `kind` 决定，其余种类的字段必须留空：

| kind | 字段 | 战斗中的效果 |
| --- | --- | --- |
| `round_limit` | `rounds`（1-40） | 到该回合仍未分胜负即判负，`rounds` 内必须取胜 |
| `element_lock` | `elements`（≥2，去重） | 只允许携带该属性之一的伙伴出战；具体是哪一个由周号从池中轮换 |
| `stat_scale` | `scale`（1.0-3.0） | 幻影四维在 `boost` 之上再乘 `scale` |

`Catalog._validate_codex_trials` 校验轮换奖励物品、轮换属性引用与能量上限（不超过宠物精力池 100），
并校验 `weekly_bonus` 的物品引用。

轮换是纯确定性的：第 i 个槽位取 `rotations[(周序号 + i) % 轮换数]`，目标种族取 `species[(周序号 + i) % 27]`，
`element_lock` 的属性取 `elements[(周序号 + i) % 属性池长度]`。因为 `i < 槽位数 ≤ 轮换数`，同一周内三个槽位
必然是三条不同轮换，且同周全服一致、跨周整体滑一位。周序号是北京周一 00:00 的 Unix 秒除以一周秒数，不使用随机数。

状态全部落在 `quest_progress`：`codex_week_<周起点>_<槽位>` 记录该场通关回合数、`codex_week_all_<周起点>` 记录
周奖已发。日期写在键里，换周即自动失效，无需清理任务，也不与新表打交道。

## 行情定义

`rules.json` 的 `market.trend_days`（1-30，实配 7）由 `MarketRule` 校验，决定行情窗口长度。行情没有内容文件：它不定义任何物品或价格，只把 schema 22 的 `market_sales` 与 schema 26 的 `market_bid_sales` 两张成交账本按窗口聚合，因此不存在可调的加成表；改 `trend_days` 就是改「市场记住多久」。

两张账本都存 `unit_price`（成交单价），所以聚合不需要任何除法或估算。每个物品在窗口内报告样本笔数、最低、**中位**与最高单价，外加总件数。中位数的偶数样本约定是「两个中位值的整数平均」，保证头条数字一定是一个玩家真能填进指令的价格。窗口按 `sold_at >= now - trend_days × 86400` 取，边界秒计入。

没有成交的物品明确说「没有任何成交」，**绝不显示 0 灵石**——0 会被读成「这东西白送」。行情也不读任何挂单价：它回答的是「成交过多少」，不是「现在标多少钱」。

## 名帖可见性

名帖没有内容文件与规则数值：它不定义任何新内容，只把既有数据按关系分层展示，任何 `rules.card` 都只会是伪配置。可见性本身就是这个功能的全部规则，因此写在文档与测试里：

| 层级 | 谁 | 可见 |
| --- | --- | --- |
| 陌生修士 | 任何人 | UID、出战境界、论剑段位、收集榜名次、佩戴称号 |
| 好友 | 已接受的好友 | 以上 + 出战阵容明细、成就数、图鉴进度、好友数、挂出的伙伴数 |
| 本人 | 自己 | 同上（灵石、背包、封存、注册时间不在名帖中，只在 `我的信息`） |

公开层不是新增披露：论剑段位与收集名次本来就由 `灵宠论剑榜`/`灵宠收集榜` 公开，称号是玩家主动佩戴的展示品。关系在**读取时**判定（`friends.linked()`），所以解除好友后同一张名帖立刻退回公开层，无需清理。

## 借力定义

`rules.json` 的 `borrow` 由 `BorrowRule` 校验：`rate` 限定 0.01-0.25，`keep_days` 限定 1-30，实配 12% 与 7 天。借力没有内容文件——它借的是**已有的伙伴**，所以不存在新的种族、加成表或掉落，全部数值来自被借伙伴自身的 `pet_stats`。

`Catalog._validate_borrow` 的唯一加载期不变量是：一只借来的好友伙伴，其加成不得超过自己全部助战席的合计（`borrow.rate <= support.rate * support.slots`，实配 12% ≤ 10% × 2）。否则「拉好友」会取代「练后备伙伴」，`support` 两席会退化成摆设，玩家最优解变成刷社交而不是养成。

状态全部落在 `quest_progress`，无新表：出借方写 `lend_<伙伴编号>`，`progress` 存到期时间戳；借用方写 `borrow_pet`（伙伴编号）与 `borrow_until`（到期时间戳）。两者都不是凭证——每次读取都重新校验好友关系、挂出有效期、伙伴是否封存或外出，所以解除好友、收回、封存或派遣都会让加成**立即**失效，不需要任何清理任务，也不存在残留状态需要修。

## 演武场定义

`drills.json` 是木人桩数组，由 `domain/drill_content.py` 的 `DrillDummy` 校验：每项声明 `id`、`name`（1-12 字）、`description`、`realm`（已有境界 id）、`stats`（四维，`speed` 必须为正）、`elements`（1-4 个）、`primary_element`、`order`（1-99）。`model_validator` 要求 `primary_element` 必须出现在自己的 `elements` 里——本命元素不属于自身属性的桩子在克制计算里没有意义。

`Catalog._validate_drills` 要求表非空、`realm` 引用现有境界、每个 `elements` 引用现有元素、`order` 与名称都唯一。重名同时会被 `_index` 的通用去重拦下，因此 `_validate_drills` 里的重名判断只是对绕过加载器的调用方的兜底。

七座木人桩的四维**直接锚定同境界既有秘境敌手**（启灵 `wood_guard`、凝气 `moon_wolf`、筑基 `thunder_dragon`、金丹 `ember_wraith`、元婴 `frost_monarch`、化神 `void_blade`、渡劫 `tribulation_avatar`），不引入新的平衡带：演武的意义是让玩家在不花资源的前提下预演真实内容，若木人桩比真实敌手更强或更弱，这个预演就会误导配装。

```json
{
  "id": "firewood_post",
  "name": "柴木桩",
  "description": "启灵境最常见的练手桩，出招朴素，用来确认伙伴站得住。",
  "realm": "qiling",
  "stats": {"hp": 85, "attack": 17, "defense": 5, "speed": 12},
  "elements": ["wood", "earth"],
  "primary_element": "wood",
  "order": 1
}
```

`rules.json` 的 `drill` 由 `DrillRule` 校验：`daily_attempts` 限定 1-10，实配 5。演武不建表：每日额度写在既有 `quest_progress` 的 `drill_<北京日期>`，行内 `progress` 就是当日已用次数，缺行即 0 次。

## 商会委托定义

`commissions.json` 是委托数组，由 `domain/commission_content.py` 校验：每项声明 `id`、`name`、`description`、`min_rep`（接单所需声望）、`items`（物品 id → 数量 1-99）、`stones` 与 `rep`（正的回报）。`Catalog._validate_commissions` 要求表非空、物品都存在、至少有一条 `min_rep = 0` 的基础单，并且每条委托的灵石回报**严格低于**所需物品的商店售价合计（没有商店价的物品按 0 计），从根上堵死「买货→交付」的套利。

```json
{
  "id": "grain_run",
  "name": "粮车押运",
  "description": "商会要给远行的商队备粮，灵粮永远不嫌多。",
  "min_rep": 0,
  "items": {"spirit_food": 5},
  "stones": 55,
  "rep": 4
}
```

`rules.json` 的 `merchant` 由 `MerchantRule` 校验：`offers_per_day` 限定 1-5，`all_clear_stones` 与 `all_clear_rep` 至少一项为正。

```json
{"offers_per_day": 3, "all_clear_stones": 60, "all_clear_rep": 4}
```

运行状态写在既有 `quest_progress`：`merchant_rep` 存累计声望，`merchant_order_<北京日期>_<委托id>` 与 `merchant_bonus_<北京日期>` 存当日已交与日清凭证；换日自动失效，无需清理。看板按北京日序数在「当前声望可接」的委托池里取连续 `offers_per_day` 条，因此同一天同一声望下稳定。

## 集市定义

`market.json` 是单个对象，由 `domain/market_content.py` 的 `MarketRule` 校验：`listing_days`（1-30 天）、`min_unit_price` 与 `max_unit_price`（1-1000000，且最小值不得大于最大值）、`max_quantity`（1-99）、`sellable_kinds`（可取 `material`、`consumable`，不得重复）、`bid_days`（1-30 天）、`max_bid_quantity`（1-99 且不得大于 `max_quantity`）、`bid_slots`（1-6 且不得大于最高摊位的陈列位），以及 `stalls` 摊位阶梯（1-6 级）。每个摊位声明 `id`、`name`、`unlock_cost`、`slots`（1-12）与 `fee_percent`（0-25）。

`Catalog._validate_market` 要求：首个摊位 `unlock_cost = 0`；后续每级解锁价**严格递增**、陈列位**严格递增**、成交税**不得上升**；摊位 id 不得重复；每种 `sellable_kinds` 在 `items.json` 里至少存在一件对应种类的物品，避免上架表指向空集；求购单笔上限不得超过上架的数量上限。

```json
{
  "listing_days": 3,
  "min_unit_price": 1,
  "max_unit_price": 50000,
  "max_quantity": 30,
  "bid_days": 3,
  "max_bid_quantity": 30,
  "bid_slots": 2,
  "sellable_kinds": ["material", "consumable"],
  "stalls": [
    {"id": "stall_spread", "name": "散铺", "unlock_cost": 0, "slots": 2, "fee_percent": 10},
    {"id": "stall_long", "name": "长摊", "unlock_cost": 800, "slots": 4, "fee_percent": 8}
  ]
}
```

schema 22 新增两张表：`market_listings` 保存托管挂单（`seller_id`、`item_id`、`quantity`、`unit_price`、`created_at`、`expires_at`、`state` 为 `active`/`sold`/`cancelled`/`expired`、`closed_at`、`buyer_id`），表级 CHECK 保证四种状态与 `closed_at`、`buyer_id` 的组合自洽，成交时买家不得等于卖家；`market_sales` 是永久成交账本（`gross`、`fee`、`net`，CHECK `fee + net = gross`，且买家不等于卖家）。索引 `market_listing_board` 服务集市浏览，`market_listing_seller` 服务我的摊位，`market_sales_seller` 服务成交记录。摊位等级存 `quest_progress` 的 `market_stall`（值为 1 起的等级号），不额外加列。

schema 26 新增两张表，承载集市的反向一侧。`market_bids` 保存求购挂单（`buyer_id`、`item_id`、`quantity`、`unit_price`、`escrow`、`created_at`、`expires_at`、`state` 为 `active`/`filled`/`cancelled`/`expired`、`closed_at`、`seller_id`），表级 CHECK 把三件事绑死：`escrow = quantity * unit_price`（托管额必须等于标价总额，代码写错也造不出付款与价格不符的单）、四种状态与 `closed_at`/`seller_id` 的组合自洽（`filled` 必须两者都有且卖家不是买家）、`expires_at > created_at`。`market_bid_sales` 是求购的永久成交账本（`buyer_id`、`seller_id`、`gross`、`fee`、`net`，CHECK `fee + net = gross` 且买家不等于卖家），主键就是 `bid_id`，一单只能结算一次。索引 `market_bid_board` 服务公开看板（按物品与单价倒序），`market_bid_buyer` 服务我的求购，`market_bid_sales_seller`/`market_bid_sales_buyer` 服务「交货」「收货」两侧记录。

托管的方向与上架相反：上架把**物品**移出卖家背包，求购把**灵石**移出买家钱包，因此成交时不再向买家收钱，撤单与到期退的是灵石而不是道具——即使求购的物品已从内容中移除，退款也照常可付，不需要把死 id 塞回背包。

## 信箱定义

信箱没有独立内容文件：附件就是既有物品与灵石，数值写在 `rules.json` 的 `mail`。

```json
{"days": 7, "daily_limit": 5, "max_stones": 5000, "max_items": 20, "inbox_capacity": 20, "kinds": ["material", "consumable"]}
```

`MailRule` 校验每个字段的区间（`days` 1-30、`daily_limit` 1-10、`max_stones` 1-10000、`max_items` 1-50、`inbox_capacity` 1-50），`kinds` 只接受 `material`/`consumable` 且不得重复；`Catalog._validate_mail` 进一步要求每种已声明种类在 `items.json` 里至少有一件物品——广告一个寄不出去的品类会在启动时直接失败，与 `_validate_market` 同一口径。

schema 23 新增单表 `mail_messages`：`sender_id`/`recipient_id` 外键指向 `players`，`kind` 只取 `item`/`stones`，`stones`、`item_id`、`quantity`、`body`（≤60 字）、`created_at`、`expires_at`、`state`（`active`/`claimed`/`recalled`/`returned`）、`closed_at`、`claimed_at`。表级 CHECK 同时约束三件事：寄件人不得等于收件人；附件形状必须与 `kind` 一致（道具类 `quantity ≥ 1` 且无灵石，灵石类 `stones ≥ 1` 且无道具）；状态与时间戳必须一致（`active` 无关闭与领取时间、`claimed` 两者都有、`recalled`/`returned` 只有关闭时间）。索引 `mail_inbox (recipient_id, state, message_id)` 服务收件箱，`mail_outbox (sender_id, state, message_id DESC)` 服务寄件箱。托管形状与状态一致性都由表约束保证，因此 `claim`/`recall` 只要用 `state='active'` 作更新守卫，同一封邮件的附件就不可能被支付两次。

## 委托线定义

`rules.json` 的 `expedition_lines` 由 `ExpeditionLinesRule` 校验：`count` 限定 1-2，`unlock_cost` 为一次性灵石费用；当 `count` 为 1 时费用必须为 0，否则「只有一条线却收开辟费」会被启动校验直接拒绝。

```json
{"count": 2, "unlock_cost": 3000}
```

第二条线的解锁状态是 `quest_progress` 的 `expedition_lines_<用户>`，存在即为已开辟——行本身就是凭证，因此重复开辟只会命中「已经开辟」而不会二次扣费。`expeditions` 表在 schema 21 新增 `slot`（0 或 1），并把 `expedition_running_player` 换成 `expedition_running_slot (user_id, slot) WHERE state='running'`：同一玩家同一线最多一条进行中行程，这个限制由索引保证而不是靠代码自觉；`expedition_running_pet` 仍然保证同一只伙伴不会同时出现在两条线。

## 镶嵌定义

`gems.json` 是宝石表，由 `domain/gem_content.py` 校验：每项声明 `id`、`name`、`item_id`、`stat`（`hp`/`attack`/`defense`/`speed`）与 `rate`（0.01-0.25）。`Catalog._validate_gems` 要求表非空、四颗宝石各对应不同属性、且消耗的物品必须是 `material`。

```json
{"id": "socket_flame", "name": "赤炎石", "item_id": "gem_flame", "stat": "attack", "rate": 0.08}
```

宝石本体是普通材料物品（`gem_flame`/`gem_ward`/`gem_swift`/`gem_vital`），因此可以照常购买、掉落、回收与制作，无需新增物品类型。槽位状态是每槽一行 `socket_<宠物id>_<槽位>_<宝石id>`，行归属玩家、宠物 id 写在键里，所以「一槽一宝石」由主键结构保证，跨账号也不会串号。镶嵌在单事务内消耗物品并写入行，二者不会一半成功。属性加成在 `loadout.combatant` 中按基础值乘算，位置在阵位之后、固定加成之前，与心情/同心/阵位的既有约定一致。

## 战意定义

`intents.json` 是战意表，由 `domain/intent_content.py` 校验：每项声明 `id`、`name`、`description`、`dealt`（输出乘区）与 `taken`（承伤乘区），两者都限制在 0.5-1.5；`check_trade_off` 要求两个乘区**同向移动**——都大于 1（打得更痛也更痛）或都小于 1（打得更轻也更轻）。反向组合是纯增益，等值组合是纯亏损，都不算选择，直接拒绝。

```json
{"id": "intent_guard", "name": "守势", "description": "稳守阵脚，受伤更少，但推进更慢。",
 "dealt": 0.86, "taken": 0.84}
```

乘区落在 `Fighter.dealt` 与 `Fighter.taken`（默认均为 1.0），由 `combat.scale_damage()` 在单体与群体两条伤害路径上统一应用，取值范围 0.25-2.5，且至少造成 1 点伤害。`Catalog._validate_intents` 要求表非空且名称不重复。战意状态是「一档一行」：`intent_<用户>_<战意id>`，切换时先删旧行再写新行，因此不会出现两条并存的歧义状态，清除即无行。

## 贡献兑换定义

`sect_exchange.json` 是兑换表，由 `domain/sect_exchange_content.py` 校验：每项声明 `id`、`name`、`description`、`item_id`、`cost`（1-100000 贡献）与 `weekly_limit`（1-10）。`Catalog._validate_sect_exchange` 要求表非空、物品存在于 `items.json`、且同一物品不被两条报价重复收录。

```json
{"id": "sect_rice", "name": "灵粮", "description": "以贡献换取库房灵粮。",
 "item_id": "spirit_food", "cost": 20, "weekly_limit": 5}
```

状态是两条 `quest_progress` 行：`sect_contrib_<门派id>` 仍是**总贡献**（阶位与被动只读它），`sect_spent_<门派id>` 记录已用贡献，可用贡献 = 两者之差；因此兑换不会改写阶位来源。每周库存是计数行 `sect_exchange_<周一零点>_<报价id>`，换周换 key 自动重置，而已用贡献跨周保留。

## 赏金定义

`bounties.json` 是赏金池，由 `domain/bounty_content.py` 校验：每项声明 `id`、`name`、`description`、`metric`（只允许 `hybrid_brews`/`alchemy_brews`/`contracts_met`/`hard_clears` 四个新指标之一）、`target`（1-100）与 `reward`。`Catalog._validate_bounties` 要求池内至少三条并校验奖励物品存在。

```json
{"id": "bounty_alchemy", "name": "丹火悬赏", "description": "今日炼成一炉丹药。",
 "metric": "alchemy_brews", "target": 1,
 "reward": {"exp": {"minimum": 0, "maximum": 0}, "stones": {"minimum": 200, "maximum": 200},
            "items": {"forge_ore": {"minimum": 2, "maximum": 2}}}}
```

当天展示的三份由日序数取模决定窗口（连续三条、循环跨越池尾），窗口内顺序固定，因此同一天内页面稳定、跨日整体前移。进度不走快照：`counters.bump` 除单调总量外还维护 `stat_<指标>_day_<北京日期>`，赏金直接读当日值，昨天的工作天然不计入。领取凭证是 `bounty_<北京日期>_<赏金id>`，因此每份每天只能领一次，且与既有每日课题的「三选一」凭证互不影响。

## 累计指标

杂交、炼丹、契约、强化通关与归灵没有可派生的存档状态，因此各自维护一个单调计数器：`quest_progress` 的 `stat_<指标名>` 行（`progress` 即累计次数）。`gameplay/counters.bump()` 只在成功路径调用，`value()` 供 `achievements._metric` 读取，`pets_released` 则直接由 `released_<伙伴编号>` 标记行派生，不需要计数器。

对应指标写进 `domain/achievement_content.py` 的 `AchievementMetric` 白名单（`hybrid_brews`、`alchemy_brews`、`contracts_met`、`hard_clears`、`pets_released`，以及六个周常体系的 `duel_wins`、`gauntlet_rounds`、`escort_full`、`team_trial_clears`、`forbidden_depths`、`tribulation_slots`、`codex_week_clears`），因此成就、称号、主线与日常四类内容都能引用；这些指标**没有上限**（可以无限累积），所以不进入 `_metric_ceilings()`，内容侧可以把目标定得较高。周常体系的七个指标额外由 `gameplay/achievements.py` 的 `ENDGAME_MARKERS` 表声明“统计哪个前缀、排除哪个全清标记”，`_metric` 按该表直接统计 `quest_progress` 的既有周凭证；护送只统计满评（`progress>=2`）。

## 难度定义

`difficulties.json` 是难度数组，由 `domain/difficulty_content.py` 校验：每项声明 `id`、`name`、`description`、`enemy_scale`（1.0-3.0）与 `reward_percent`（0-200）。`Difficulty` 拒绝「只加奖励不加数值」与「只加数值不加奖励」，让档位始终是取舍；`Catalog._validate_difficulties` 要求表非空且**必须包含一档 `enemy_scale == 1.0` 的基准档**，否则玩家没有「原样挑战」的参照。

```json
{"id": "challenge", "name": "挑战", "description": "敌手更强，奖励更高。",
 "enemy_scale": 1.25, "reward_percent": 50}
```

缩放发生在 `adventure.run_dungeon` 的两个可选参数上：`enemy_scale` 用 `model_copy` 生成缩放后的 `Enemy`（不修改内容目录本身），`reward` 传入按档位放大的 `Reward`；默认值（1.0 / None）让既有调用方行为完全不变。奖励放大对修为、灵石与每种材料逐项取整，且不低于原始值，因此低数值条目不会被取整抹平。

## 炼丹定义

`alchemy.json` 是丹方数组，由 `domain/alchemy_content.py` 校验：每项声明 `id`、`name`、`description`、`item_id`、`stones`（≥1）、`materials`（≥1 项）与 `yield`（1-10）。`AlchemyRecipe` 拒绝「消耗自己的产物」，`Catalog._validate_alchemy` 进一步要求产物与材料都存在于 `items.json`、且产物是 `consumable` 或 `breakthrough`——丹药方产出装备或材料会在启动时被拒。

```json
{"id": "energy_draught", "name": "回元丹", "description": "以灵稻与灵血草为底。",
 "item_id": "energy_pill", "stones": 30,
 "materials": {"spirit_food": 2, "seed_blood_herb": 1}, "yield": 1}
```

批量炼制按份数线性放大：材料与灵石都乘以份数，产物也乘以份数，因此单份与十份的收益比恒等。炼丹不写任何进度状态——消耗与产出在同一事务内完成，重复提交由既有操作缓存去重，因此不会出现「炼了两次却只扣一次料」。

## 杂交定义

`hybrids.json` 是配方数组，由 `domain/hybrid_content.py` 校验：每项声明 `id`、`name`、`description`、`seeds`（恰好 2 个）、`stones`（1-100000）与 `output`。`Hybrid` 要求两个种子不同、产物不能是输入之一；`Catalog._validate_hybrids` 进一步要求输入与产物都在 `items.json`、产物是 `material`、且 `crops.json` 里存在以该产物为 `seed_item` 的作物。

```json
{"id": "frost_wheat", "name": "霜纹麦", "description": "把灵稻与矿苗的生机调在一起。",
 "seeds": ["seed_spirit_rice", "seed_ore_sprout"], "stones": 120, "output": "seed_frost_wheat"}
```

杂交产物在 `items.json` 里不写 `price`，因此灵坊无法购买、回收页也不会把它当作可买物品；它只能由 `灵宠杂交` 产出，再由 `灵宠播种` 进入正常生长流程。杂交本身不写任何进度状态：消耗与产出都在同一事务里完成，重复提交由操作缓存去重。

## 契约定义

`contracts.json` 是契约数组，由 `domain/contract_content.py` 校验：每项声明 `id`、`name`、`description`、`kind`（`solo`/`speed`/`unhurt`）与 `bonus`。`Contract` 要求 `speed` 必须给 `rounds`（1-40）、其它两种不得给；`ContractBonus` 的百分比 0-200，且（百分比或物品）至少给出一项。`Catalog._validate_contracts` 要求表非空并校验奖励物品存在。

```json
{"id": "speed", "name": "速战", "description": "在限定回合内结束战斗。", "kind": "speed", "rounds": 8,
 "bonus": {"stones_percent": 30, "exp_percent": 30, "items": {"bloodline_essence": 1}}}
```

契约不新增秘境、不缩放敌手、不改基础奖励：挑战走 `adventure.run_dungeon`，仅在 `return_state=True` 时额外返回战斗与玩家侧 `Fighter` 供条件判定（`satisfied` 读 `battle.winner`、`battle.rounds` 与各 `hp`）。达成后额外发放的奖励按该秘境 `reward` 的百分比取整计算，再叠加固定物品，因此基础与契约两部分互不影响、可以分别核对。

## 轮作规则

轮作数值写在 `rules.json` 的 `farm_rotation`，由 `domain/content.py` 的 `FarmRotationRule` 校验：`rate_percent` 必须在 1-100 之间（低于 1 没有意义，高于 100 会让加成翻倍失控）。

```json
{"rate_percent": 20}
```

状态复用 `quest_progress`：`farm_last_<田位>_<作物id>` 记录该田位最近收获的作物（作物 id 放键里），`farm_rotation_<田位>` 标记本季是换种。播种时读取上一季作物——存在且与本次不同才写轮作标记；收获（含枯萎、含原地补种）时把当季作物写成新的上一季并清除标记，因此加成窗口恰好覆盖一季。

倍率在 `farming._grant_reward` 内对修为、灵石与每种材料逐个取整应用（`int(base × (1 + rate))`），枯季只返还种子、不参与倍率。

## 归灵规则

归灵数值写在 `rules.json` 的 `pet_release`，由 `domain/content.py` 的 `PetReleaseRule` 校验：`stones_base`、`stones_per_realm` 非负，`items` 物品存在，且（灵石或材料）至少给出一项，避免出现空收益配置。收益按伙伴境界线性增长：`灵石 = stones_base + stones_per_realm × 境界`，另加 `items` 中的材料与该族灵卵 `egg_<种族id>`（若该物品存在）。归灵不发修为——修为只会落在当前出战伙伴身上，与「退役这只」无关。

归灵**不删除**任何行。`pets` 被 `active_pet_slots`、`equipment`、`learned_skills`、`expeditions`、`teams`、`pvp_results`、`players.active_pet_id` 等引用，直接删除会破坏战报与对外引用，所以实现是软退役：`pets.archived = 1` 加一条永久标记 `quest_progress.released_<伙伴编号>`。名册名额按 `archived=0` 计数，因此归灵自动释放一个名额；`released_` 标记让封存库、`灵宠复原` 与归灵页把这类伙伴当作已消失。

## 出战预设状态

出战预设没有内容文件：三套槽位是固定的（1-3），成员来自玩家自己的名册。状态写在 `quest_progress`：
每个已保存的槽位一行标记 `lineup_preset_<n>`（`progress` 记录成员数），以及每位成员一行
`lineup_preset_<n>_<伙伴编号>`。成员以独立行保存而不是「1 2 3」字符串，因此不存在位数解析问题，
被删除的伙伴自然匹配不上而让整份预设在应用时被拒绝。

保存时会先清空该槽位再写入，所以覆盖保存不会残留旧成员；清除只删该槽位的标记与成员行。应用前复核：
伙伴仍属本人、未封存、未在派遣、种类不重复、数量 1-3；全部通过才调用 `repo.set_active_pets`
并取消组队准备，否则整份预设拒绝且不写任何行。

## 同心规则

同心没有独立内容文件，数值写在 `rules.json` 的 `pair_bond`，由 `domain/content.py` 的 `PairBondRule` 校验：`stones` ≥ 0、`items` 物品存在、`min_affinity` ≥ 0、`rates` 只允许四维键且每项 `0 < rate ≤ 0.5`；同时要求至少一条加成、并且（灵石或材料）至少要付出一样，避免出现零成本或零收益的同心。

```json
{"stones": 300, "items": {"bloodline_essence": 1}, "min_affinity": 60,
 "rates": {"attack": 0.08, "defense": 0.06, "speed": 0.04}}
```

状态是一行对称凭证 `quest_progress.bonded_<小编号>_<大编号>`（`progress`=1）。对称键让「每位伙伴只能有一位同心」成为键本身的约束，不需要第二张表，也不需要额外校验；解契即删除该行。读取时按前缀取行并解析两侧编号，`partner_of()` 对任一方向都返回对方。

加成在 `loadout.combatant` 中紧随心境与阵位之后、所有固定加成之前，对基础四维乘 `1 + rate`；`rate_of()` 只在 `partner_of()` 存在且双方都在当前出战阵容时返回值，因此换阵容会立刻改变数值，且装备/词条/套装/符印/羁绊的固定数值不受影响。

## 阵位定义

`formations.json` 是阵位数组，由 `domain/formation_content.py` 校验：每项声明 `id`、`name`、`description` 与 `rates`。`Formation` 要求四维齐全、每项 0.5-1.8，并且**至少一项 > 1、至少一项 < 1**——一个只加不减或只减不加的位置会被拒绝，这是「阵位必须是取舍」的内容级约束。`Catalog._validate_formations` 要求恰好三个位置 `vanguard`/`center`/`rear`，与页面语义绑定。

```json
{"id": "vanguard", "name": "前锋", "description": "顶在最前面，扛得住也打得钝。",
 "rates": {"hp": 1.18, "attack": 0.88, "defense": 1.22, "speed": 0.92}}
```

状态是 `quest_progress` 的 `formation_<伙伴编号>_<位置id>` 单行（位置 id 放键里），换位时先删旧行再写新行，因此一只伙伴只有一个阵位；没有该行即未布阵。生效点在 `loadout.combatant`：与心境同一位置、同样只缩放基础四维，之后才叠加装备、词条、套装、符印、羁绊等固定加成，所以固定加成的数值不随阵位变化。

## 易脉定义

`attunements.json` 是易脉目标数组，由 `domain/attunement_content.py` 校验：每项声明 `element`、`stones` 与 `items`。`Catalog._validate_attunements` 要求元素存在、**必须是基础元素**（`parent` 为 null，因此冰不可作为目标）、同一目标不重复、材料物品存在；每周次数写在 `rules.json` 的 `attunement.weekly_limit`（1-7）。

```json
{"element": "fire", "stones": 400, "items": {"bloodline_essence": 2}}
```

生效方式是覆盖而不是改写物种：`gameplay/attunement.elements_of()` 返回易脉结果（单元素）或物种默认元素，`loadout.combatant` 用它构造 `Fighter.elements`/`primary_element`，`compatibility.check_requirements` 用它判断灵术与装备兼容，战报快照也读 `fighter.elements`，因此战斗、克制、技能门槛与存档展示始终一致。因为目标都是基础元素，`expand_elements` 不会带出任何子元素，换属性等于彻底放弃原有元素门槛。

状态是 `quest_progress` 的 `attune_<伙伴编号>_<元素>`（元素 id 放键里）与 `attune_week_<周起点>_<伙伴编号>`（`progress` 计数），不新增表列；改属时先删旧覆盖行再写新行，因此一只伙伴只有一个当前元素。

## 护送定义

`escorts.json` 是护送任务数组（当前五条，两条高境界任务把波次推到元婴至渡劫敌手），由 `domain/escort_content.py` 校验：每项声明 `id`、`name`、`description`、`energy`（1-100）、`npc`（`name` 与四维，气血/速度 ≥ 1）、`waves`（1-5 波，每波 1-3 个敌手 id）与 `rewards`（`full` 与 `partial` 两档 `Reward`）。`EscortRewards` 强制满评奖励不低于部分奖励（灵石与修为两档），`Catalog._validate_escorts` 校验敌手与奖励物品都存在。

```json
{"id": "medicine_run", "name": "药囊运送", "energy": 15,
 "npc": {"name": "药囊", "hp": 260, "attack": 12, "defense": 8, "speed": 10},
 "waves": [["wood_guard"], ["wood_guard", "ancient_guard"]],
 "rewards": {"full": {...}, "partial": {...}}}
```

护送目标就是一个普通 `Fighter`（`Fighter.create` 用 `npc` 四维构造），被追加到玩家一侧，因此 `fight()` 无需任何改动；它同样受 `hp` 就地修改影响，跨波延续自然成立。胜负判定是 `battle.winner == 0` **且** 目标 `hp > 0`，这是现有模式没有的条件。

状态是 `quest_progress` 的 `escort_<周起点>_<任务id>`，`progress` 存本周最佳评级（1 部分、2 满评）：首次部分评价发部分奖励，之后满评只补差额（逐字段取 `full - partial`），因此不存在重复领取；换周换 key，旧行保留。战报按操作去重，只落决定胜负那一场。

## 符印定义

`sigils.json` 是符印数组，由 `domain/sigil_content.py` 校验：每项声明 `id`、`name`、`description`、`bonuses`（`hp`/`attack`/`defense`/`speed` 各 0-60，不可全为 0）与 `requires`（`kind` ∈ `achievements`/`collection`/`bond`/`realm`，`value` ≥ 1）。`Catalog._validate_sigils` 要求符印表非空。

```json
{"id": "first_light", "name": "初光符", "description": "第一次结契时点亮的印记。",
 "bonuses": {"hp": 40}, "requires": {"kind": "achievements", "value": 1}}
```

解锁进度全部派生自既有数据，不新增计数：`achievements` 读 `achievement_claims` 行数，`collection` 读已收得的不同种族数，`bond` 读该伙伴的羁绊等级，`realm` 读该伙伴的境界序号。因此内容调整不会与存档脱节，也不需要回填。

槽位状态是 `quest_progress` 的 `sigil_<伙伴编号>_<槽位>_<符印id>` 单行（符印 id 放键里，`progress` 是整数列），按 `sigil_<伙伴编号>_%` 前缀读取；两个槽位彼此独立，卸下即删除对应行，解锁状态不受影响。加成是**固定值**，在 `loadout.combatant` 中与装备、词条同层累加，不参与任何倍率。

## 擂台定义

`gauntlets.json` 是擂台数组（当前两条：`gauntlet` 与元婴起的 `high_gauntlet`，各自独立计周发奖），由 `domain/gauntlet_content.py` 校验：`energy` 1-100、`bonus` 全清奖励、`rounds` 1-10 关，每关声明 `enemy`、四项 `*_scale`（0.1-10）与 `reward`。`Catalog._validate_gauntlets` 进一步要求敌手存在于 `enemies.json`、全清与逐关奖励物品都存在。

```json
{"id": "gauntlet", "name": "灵宠擂台", "energy": 15, "bonus": {...},
 "rounds": [{"enemy": "wood_guard", "hp_scale": 1.0, "attack_scale": 1.0,
             "defense_scale": 1.0, "speed_scale": 1.0, "reward": {...}}]}
```

敌手按 `model_copy(update={"stats": Stats(...)})` 缩放，`Enemy` 本身不变。连战的关键在于玩家一侧的 `Fighter` **只构建一次**并重复传给 `fight()`：`fight()` 直接修改传入单位的 `hp`，所以第 n 关结束时的血量自然成为第 n+1 关的起始血量，战斗引擎无需任何改动。

状态是 `quest_progress` 的两类凭证：`gauntlet_<周起点>_<序号>`（该关本周已通关）与 `gauntlet_<周起点>_all`（本周全清）。战报按操作去重，因此一次命令只落一条 `pve_stage` 记录，键为决定胜负那一关的 `gauntlet_<周>_<序号>`，不写 `pve_stage_progress`。

## 研习定义

研习没有独立内容文件，数值放在 `rules.json` 的 `research`：

```json
{"energy": 12, "food": 1, "gain": 8, "daily_limit": 4, "pet_daily_limit": 2}
```

`energy` 1-100、`food` 0-5、`gain` 1-100、`daily_limit` 1-20、`pet_daily_limit` 1-10 且不得超过 `daily_limit`（`ResearchRule` 校验）。成功一次按 `gain` 增加熟练度并消耗相应精力与灵粮；升阶算术与战斗共用 `mastery.study`，所以研习与实战的进位完全一致，且不会直接跳级——只在熟练度超过阈值时进位。

状态只有 `quest_progress` 的两行计数：`research_day_<北京日期>`（当日已研习次数，账号级）与 `research_<北京日期>_<宠物编号>`（该伙伴当日已研习次数）。日期写在键里，因此两个上限都随北京时间换日自然重置，无需清理任务或额外列；研习不改 `players`、不写战报、不写 `pve_stage_progress`，也不消耗灵石或秘笈。

## 竞速定义

`races.json` 是赛道数组，由 `domain/race_content.py` 校验：每项声明 `id`、`name`、`description`、`length`（100-10000 米）与 `terrain`（`stat` 为 `hp`/`attack`/`defense`/`speed` 之一，`multiplier` 0.1-3）。

```json
{"id": "sprint", "name": "直道竞速", "description": "平直长道。", "length": 800,
 "terrain": {"stat": "speed", "multiplier": 1.25}}
```

数值在 `rules.json` 的 `race`：`energy`（每次报名精力）、`daily_limit`（1-20）与 `weights`（四维权重，必须覆盖四项且合计为 1）。`Catalog._validate_races` 校验赛道非空、id 唯一，且每条赛道的地形属性都必须是权重表里的属性——因此不会出现「地形加成算不进去」的赛道。

用时是派生值，不模拟战斗：把四维按权重求和，地形属性乘上该赛道的倍率，再以 `round(长度 × 100 / 加权总和)` 取整（最少 1，即 0.1 秒）。因为属性来自 `loadout.combatant`，所有既有成长系统都自动计入竞速成绩。

只有两行状态，都在 `quest_progress`：`race_best_<北京周起点>` 存本周最好用时（十分之一秒），`race_day_<北京日期>` 存当日已报名次数（`progress` 为整数，恰好适配）。换日换 key 自动重置次数，换周换 key 自动重置最好成绩，旧行保留在库中但不再参与排名；不写 `players.last_*` 冷却列，也不写战报或 `pve_stage_progress`。

### 竞速周奖励定义

`race_prizes.json` 是三条按名次固定的周结算奖励数组，由 `domain/race_prize_content.py` 的 `RacePrize` 校验：每项声明 `rank`（1-3）、`stones`（非负）与 `items`（物品 id → 正整数），且 `stones` 与 `items` 不能同时为空。

```json
{"rank": 1, "stones": 600, "items": {"forge_ore": 3, "spirit_food": 2}}
```

`Catalog._validate_races` 强制名次恰为 1、2、3；奖励物品必须存在且为 `consumable`/`material`；高名次不得低于低名次——`stones` 与每个出现的物品逐项比较，低名次有而高名次缺的物品按 0 计。因此奖励表倒挂会在启动时被拒绝。领取标记 `race_prize_<北京周起点>` 也写在 `quest_progress`，`progress` 保存最终名次、`claimed=1`；不新增表或列。

### 商会兑换定义

`merchant_exchange.json` 是商会声望兑换项数组，由 `domain/merchant_exchange_content.py` 的 `MerchantOffer` 校验：每项声明 `id`、`name`、`description`、`cost_rep`（正整数）、`item`（物品 id）、`amount`（1-99）与 `weekly_limit`（1-20）。

```json
{"id": "food_pack", "name": "灵粮补给", "description": "三份灵粮。",
 "cost_rep": 8, "item": "spirit_food", "amount": 3, "weekly_limit": 5}
```

`Catalog._validate_merchant_exchange` 要求至少一条兑换项、物品存在且为 `consumable`/`material`。兑换从 `max(0, merchant_rep - merchant_spent)` 扣除可用余额并增加 `merchant_spent`，累计 `merchant_rep` 不变；购买计数写在 `merchant_buy_<北京周起点>_<兑换 id>`，跨周换 key 自动重置。两条状态都在 `quest_progress`，不新增表或列。

## 心境定义

`moods.json` 是心境等级数组，由 `domain/mood_content.py` 校验：每项声明 `id`、`name`、`description`、`threshold`（达到该值即为本等级）与 `rate`（四维倍率，−30% 到 +30%；阈值 0 的等级不得为正加成）。

```json
{"id": "high", "name": "心情大好", "description": "被好好照顾着。", "threshold": 3, "rate": 0.0}
```

数值在 `rules.json` 的 `mood`：`max` 1-5、`decay_days` 1-30、`soothe_items` 0-10 与 `rates`（每个等级 id 对应一条倍率，全部 ≤0，即最高档为 0）。`Catalog._validate_moods` 强制四件事：必须有一档阈值 0、最高档阈值必须等于 `rules.mood.max`、倍率随心境下降单调不升、且最高档必须为 0（照料即基准，任何档位都不得给正加成），每档倍率还必须与 `rules.mood.rates` 同 id 完全一致——因此等级表与规则表不可能被分开改动而不报错。

状态只有 `quest_progress` 的 `last_care_<宠物编号>` 一行，`progress` 记录最近一次照料的北京时间**日序数**（整数，因此天然适配该列）。当前心境 = `max − 间隔天数 // decay_days`，下限 0；从无该行的伙伴视为刚被照料（满值），因此新领养或旧存档的存量伙伴不会一上线就心情低落。照料的唯一副作用就是把这行刷新为今天，喂食、每日互动与安抚都调用同一个 `care()`。

## 专精定义

`specializations.json` 是流派数组，由 `domain/specialization_content.py` 校验：每项声明 `id`、`name`、`description` 与 `rate`（5%-30%）。

```json
{"id": "single", "name": "单体精研", "description": "把一门单体灵术练到极致。", "rate": 0.15}
```

流派不属于技能数据，而是从技能自身形状派生（`skill_archetype`）：带敌对效果（震慑/削弱/破障/嘲讽）→ `control`；治疗类或带增益护持效果 → `support`；群体目标 → `multi`；其余 → `single`。因此新增灵术无需补流派配置。`Catalog._validate_specializations` 要求流派表非空，且 `skills.json` 里每门灵术都能落到已声明的流派上——否则启动即报错，避免出现「无法专精的技能」。

数值只有 `rules.json` 的 `specialization`（`min_level` 1-5、`switch_stones` ≥0，当前 3 级与 300 灵石）。状态是 `quest_progress` 的 `spec_<宠物编号>_<灵术id>` 单行：灵术 id 放在键里，因为 `progress` 是整数列；读取时按 `spec_<宠物编号>_%` 前缀查询，因此换技能、遗忘其他灵术都不影响既有专精，取消即删除该行。

## 成就点商店定义

`achievement_shop.json` 是兑换项数组，由 `domain/achievement_shop_content.py` 校验：每项声明 `id`、`name`、`description`、`cost`（1-100000 点）与 `reward`（`stones` ≥0 加 `items`），`reward` 不能同时为空。`Catalog._validate_achievement_shop` 要求至少一项、且每个奖励物品 id 都存在于 `items.json`。

```json
{
  "id": "food_bundle", "name": "灵粮包", "description": "五份灵粮。",
  "cost": 40, "reward": {"stones": 0, "items": {"spirit_food": 5}}
}
```

点数来源写在 `rules.json` 的 `achievement_points`（`per_claim` 1-100，当前 10）：`累计 = per_claim × achievement_claims 行数`，因此成就领取历史无需回填，也不新增列。消耗写在 `quest_progress` 的 `ach_points_spent`（`progress` 为已用点数），可用余额为两者之差；没有独立货币表。兑换是原子操作：校验余额与物品定义后一次性更新 `ach_points_spent` 并发放灵石与物品，失败路径不写入。

## 传功规则

传功没有独立内容文件，数值放在 `rules.json` 的 `transfer`：

```json
{"price_rate": 0.8, "min_stones": 80, "bloodline_essence": 1}
```

`price_rate` 限定 0-1，`min_stones` 非负，`bloodline_essence` 0-5。费用按目标灵术秘笈价格乘以 `price_rate` 向上取整，再与 `min_stones` 取较大值；秘笈没有标价时按 `min_stones` 计。因此传功始终比重新买一本秘笈便宜，但不会低于保底价，也不会免费。

传功不新增状态：成功后只在 `learned_skills` 插入 `(徒弟编号, 灵术id, equipped, 1, 0)`，`equipped` 取决于徒弟当前携带数是否小于 `skill_slots`。师父一侧完全不变，所以同一门灵术可以被反复传授给不同伙伴；由于每次都要付灵石与血脉精华，这不会绕过秘笈的价格，只是省去等待灵坊轮换与库存。失败路径（师父未学、徒弟已学、徒弟条件不符、任一方在派遣、灵石或精华不足、同名伙伴歧义、师父徒弟相同）都在写入前拒绝。

## 连携定义

`combos.json` 是连携数组，由 `domain/combo_content.py` 校验：每项声明 `id`、`name`、`description`、`skills`（恰好两门、互不相同、必须存在于 `skills.json`）与 `bonuses`（`hp` / `attack` / `defense` / `speed` 的加成比率）。

```json
{
  "id": "windfire_pair",
  "name": "风火相生",
  "description": "风助火势，出手更快也更狠。",
  "skills": ["wind_slash", "fireball"],
  "bonuses": {"attack": 0.05, "speed": 0.03}
}
```

规则：每项加成 0-10%，四项合计不得超过 15%，且不能全为 0；`skills` 长度必须为 2 且两个 id 不同。`Catalog._validate_combos` 进一步要求技能存在，并禁止两组连携使用同一对技能（顺序无关）。

连携没有独立存档：`gameplay/combos.py` 每次按 `learned_skills` 中 `equipped=1` 的技能集合重新判定，因此换装、遗忘、切换出战伙伴都会立刻反映到页面与战斗属性，不需要迁移或回滚。技能的元素/类别/境界条件仍由 `combatant` 的 `check_requirements` 把关——例如风火相生只能由同时具备风与火元素的伙伴携带，木灵相济只能由具备木元素的伙伴携带。

## 助战规则

助战没有独立内容文件，数值放在 `rules.json` 的 `support`：

```json
{"slots": 2, "rate": 0.1}
```

`slots` 限定 1-3，`rate` 限定 0-50%，表示每席把该伙伴**基础**四维的多少借给当前出战伙伴。助战加成按 `pet_stats(伙伴)`（境界/层数/血脉/亲密与天赋，不含装备、词条、套装、淬魂、师门）乘以 `rate` 后取整求和，因此调平衡只改这一处。

席位存 `quest_progress` 的 `support_1` / `support_2`（伙伴编号）。结算时若该伙伴已封存、已外出派遣或已不存在，该席自动不计入；出战阵容中的伙伴、重复占位与超出席位数都会被拒绝。加成不写入宠物表，由 `loadout.combatant` 实时计算。

## 淬魂规则

淬魂没有独立内容文件，数值统一放在 `rules.json` 的 `temper`：

```json
{"max_layers": 10, "rate": 0.01, "stones_per_layer": 50}
```

`max_layers` 限定 1-20，`rate` 限定 0-5%（每层乘到四维的比例），`stones_per_layer` 为每层灵石。灵卵按 `egg_<种族id>` 约定取用（与培育产物同一物品），因此不需要额外的种族到灵卵映射表，也不新增物品。

层数按伙伴记在 `quest_progress` 的 `temper_<宠物编号>`，值为已淬层数；加成由 `loadout.combatant` 在师门被动之后、装备之前实时计算，不写入宠物表。页面、帮助与目标行都从同一份 `rules.json` 读取层数与花费，改数值只需改这一处。

## 师门定义

`sects.json` 是门派对象数组，由 `domain/sect_content.py` 校验。每个门派定义 `id`、`name`、`description`、`stat`（`hp` / `attack` / `defense` / `speed`）与 `ranks`（2-5 阶，必须从 1 连续）。每阶含 `rank`、`contribution`、`rate`、`stones` 与固定数量的 `items`。

```json
{
  "id": "jian_ge",
  "name": "剑阁",
  "description": "以剑证道，门人出剑更快也更狠；贡献愈深，剑意愈盛。",
  "stat": "attack",
  "ranks": [
    {"rank": 1, "contribution": 0, "rate": 0.02, "stones": 120, "items": {"forge_ore": 1}},
    {"rank": 2, "contribution": 60, "rate": 0.04, "stones": 240, "items": {"forge_ore": 2}}
  ]
}
```

校验规则：阶位号从 1 连续、第一阶贡献必须为 0、贡献阈值严格递增、被动比率严格递增且不超过 50%、奖励物品必须存在。当前四派共用 0/60/160/320/560 的阶位曲线，加成 2%→10%，奖励灵石 120/240/480/900/1600 与各派材料 1/2/3/5/8 份。

每日修行、转投花费与修为收益不写死在前端，统一放在 `rules.json` 的 `sect`：`daily_contribution` 10、`practice_energy` 20、`practice_exp` 30、`switch_stones` 500。运行状态全部存 `quest_progress`，包括加入（`sect_member_<id>`）、当前门派（`sect_current_<id>`）、贡献（`sect_contrib_<id>`）、当日修行（`sect_day_<北京日期>`）与阶位领赏（`sect_claim_<id>_<阶位>`），不新增表列；被动由「当前门派 + 贡献推导阶位」实时计算，不单独存档。

## 劫境定义

`tribulations.json` 是劫境配置数组（当前一条 `tribulation`），由 `domain/tribulation_content.py` 校验。进度凭证 `trib_<周>_<契约序号>`／`_all` 永久保留，因此 `灵宠劫境 战历` 能按周回顾历史。配置定义 `id`、`name`、`description`、`energy`（1-100）、`slots`（1-5）、`bonus`（三份全清奖励）与 `modifiers`（至少 3 个，id 唯一）。

```json
{
  "id": "tribulation",
  "name": "灵宠劫境",
  "description": "三份契约同时压在秘境之上。",
  "energy": 15,
  "slots": 3,
  "bonus": {"exp": {"minimum": 300, "maximum": 300}, "stones": {"minimum": 500, "maximum": 500}, "items": {"forge_ore": {"minimum": 3, "maximum": 3}}},
  "modifiers": [
    {"id": "hourglass", "name": "漏刻", "description": "12 回合内未破敌即算超时",
     "hp": 1.0, "attack": 1.0, "defense": 1.0, "speed": 1.0,
     "round_limit": 12, "energy_multiplier": 1.0,
     "reward": {"exp": {"minimum": 220, "maximum": 220}, "stones": {"minimum": 340, "maximum": 340}, "items": {"bloodline_essence": {"minimum": 1, "maximum": 1}}}}
  ]
}
```

词缀的四项倍率限定 0.1-100，`round_limit` 只能是 0（不限）或 3-30，`energy_multiplier` 0.5-3（消耗按向上取整），奖励物品与全清奖励物品都必须存在。

每周契约由周序号确定性抽取：第 `s` 份（从 0 计）秘境取 `dungeons[(周序号 + 7s) % 秘境数]`，词缀取 `modifiers[(周序号 + 2s) % 词缀数]`，因此同周稳定、跨周轮换，且不需要随机数或存档。凭证为 `quest_progress` 的 `trib_<周起点>_<序号>` 与 `trib_<周起点>_all`，战报键与前者相同，不写 `pve_stage_progress`。

## 奇缘定义

`arcs.json` 是奇缘对象数组，由 `domain/arc_content.py` 校验。每条奇缘定义 `id`、`name`、`order`、`description`、`requires`（前置奇缘 id 或 null）、`min_realm`、`chapters` 与 `finale`；每章含 `order`、`title`、`text` 与**恰好两个** `options`（`id`、`label`、`text`、`reward`），终章含 `text`、`reward` 与可选的 `paths`。

```json
{
  "id": "wind_road",
  "name": "风起青萍",
  "order": 1,
  "description": "山门初雪，一件小事牵出你与一只灵宠的第一次同行。",
  "requires": null,
  "min_realm": "qiling",
  "chapters": [
    {
      "order": 1,
      "title": "山门初雪",
      "text": "雪落山门，一名杂役抱着柴薪滑倒在石阶上。",
      "options": [
        {"id": "help", "label": "相助", "text": "你扶起他。", "reward": {"exp": {"minimum": 40, "maximum": 40}, "stones": {"minimum": 80, "maximum": 80}, "items": {"spirit_food": {"minimum": 1, "maximum": 1}}}},
        {"id": "watch", "label": "旁观", "text": "你站在廊下看着。", "reward": {"exp": {"minimum": 60, "maximum": 60}, "stones": {"minimum": 0, "maximum": 0}, "items": {}}}
      ]
    }
  ],
  "finale": {
    "text": "雪停时，你把那盏灯留在山门。",
    "reward": {"exp": {"minimum": 150, "maximum": 150}, "stones": {"minimum": 200, "maximum": 200}, "items": {}},
    "paths": [
      {"choices": [1, 1], "text": "你扶过他，也借过灯；此后山道总有第二串脚印。"},
      {"choices": [2, 2], "text": "你旁观、独行，山门只剩一盏灯和一双冻硬的鞋。"}
    ]
  }
}
```

校验规则：章序号从 1 连续、每章两个选项且选项 id 不重复、`requires` 必须指向另一条真实奇缘且不能指向自己、境界与全部奖励物品必须存在。`finale.paths` 可选，缺省为空数组（向后兼容，旧文件无需改动）：每条 `choices` 必须与章数等长、每项取值 1-2，且同一奇缘内不能出现重复路径；路径数上限 16（三章恰好覆盖 2³=8 种组合）。五条已发行奇缘（风起青萍、雪夜灯影、星槎渡、云岭旧约、天门问道）各自补齐全部 8 条路径文案，境界门槛依次为启灵、筑基、金丹、元婴、化神。进度存 `quest_progress` 的 `arc_<id>_step`、`arc_<id>_pick_<章>`、`arc_<id>_done`，不新增表列；选项记录为 1-based 序号而不是 id，因为 `progress` 只接受整数。终章结算时按已记录的 `pick` 序列匹配 `paths`，无匹配则回落到 `finale.text`。

## 守关定义

`survival.json` 是守关配置数组（当前一条 `survival`），由 `domain/survival_content.py` 校验。配置定义 `id`、`name`、`description`、`enemy`（已有敌人）、四项 `*_multiplier`（0.1-100，防御允许 0）、`energy` 与 `milestones`（回合数唯一递增、每档带完整 `reward`）。

```json
{
  "id": "survival",
  "name": "灵宠守关",
  "description": "深渊魔将守关不退，气血如渊；此战不求取胜，只问你能否撑到最后。",
  "enemy": "abyss_guard",
  "hp_multiplier": 40.0,
  "attack_multiplier": 0.6,
  "defense_multiplier": 1.0,
  "speed_multiplier": 1.0,
  "energy": 12,
  "milestones": [
    {"rounds": 5, "reward": {"exp": {"minimum": 120, "maximum": 120}, "stones": {"minimum": 300, "maximum": 300}, "items": {"forge_ore": {"minimum": 2, "maximum": 2}}}}
  ]
}
```

守卫属性 = 敌人基础属性 × 对应倍率（取整，气血/攻击/速度至少 1）；气血倍率决定「打不死」，攻击倍率决定存活压力。最高档回合数即页面显示的目标。战绩存 `quest_progress` 的 `survival_best`，里程碑凭证为 `survival_milestone_<回合>`，战报键为 `survival`，不写 `pve_stage_progress`。

## 图鉴试炼定义

`codex_trials.json` 是试炼配置数组（当前只有一条 `codex`），由 `domain/codex_trial_content.py` 校验。每周轮换进度凭证 `codex_week_<周>_<场次>` 与 `codex_week_all_<周>` 永久保留，因此 `灵宠图鉴试炼 战历` 能按周回顾历史。配置定义 `id`、`name`、`boost`（1.0-5.0）、`energy`（1-100）、`reward`（修为/灵石区间加物品）与 `milestones`（通关数量唯一递增、物品存在）。种族列表来自 `pets.json`，不在此文件重复。

```json
{
  "id": "codex",
  "name": "灵宠图鉴试炼",
  "boost": 2.2,
  "energy": 10,
  "reward": {
    "exp": {"minimum": 150, "maximum": 150},
    "stones": {"minimum": 200, "maximum": 200},
    "items": {"forge_ore": {"minimum": 1, "maximum": 1}}
  },
  "milestones": [
    {"count": 9, "items": {"forge_ore": 4}},
    {"count": 18, "items": {"bloodline_essence": 4}},
    {"count": 27, "items": {"exp_pill": 4}}
  ]
}
```

幻影属性 = 该族 `stats` × `boost`（取整，`hp/attack/speed` 至少 1），元素与主属性沿用种族定义，不配置灵术；里程碑数量不得超过种族总数，载入时由 `Catalog` 校验。首通与进度存 `quest_progress` 的 `codex_trial_<种族id>`（回合数）与 `codex_trial_milestone_<数量>`，战报键为 `codex_<种族id>`，不写 `pve_stage_progress`。

## 团队试炼定义

`team_trials.json` 是团队试炼对象数组（当前五条，覆盖凝气至渡劫，按周轮换），由 `domain/team_trial_content.py` 校验。每条试炼定义 `id`、`name`、`description`、`min_realm`、`enemies`（1-5 个已有敌人）、`energy`（1-100）、`round_limit`（3-30）与 `reward`（修为/灵石区间加物品），奖励物品必须存在于 `items.json`。

```json
{
  "id": "thunder_raid",
  "name": "雷泽合击",
  "description": "雷泽蛟灵盘踞云泽，全队须在它蓄满雷势前合力击破。",
  "min_realm": "ningqi",
  "enemies": ["thunder_dragon"],
  "energy": 25,
  "round_limit": 10,
  "reward": {
    "exp": {"minimum": 200, "maximum": 260},
    "stones": {"minimum": 300, "maximum": 380},
    "items": {"forge_ore": {"minimum": 2, "maximum": 2}}
  }
}
```

试炼按 `id` 排序、以北京时间周一零点的 `时间戳 // 86400 % 试炼数` 轮换，因此同周内固定、跨周自动换题；当前三道题为古殿破阵、雷泽合击、潮宫围猎。`round_limit` 是唯一的失败条件之外的限时规则：战斗判胜但回合数超过上限时记为超时，不结算奖励。每周进度写在 `quest_progress` 的 `team_trial_<周一零点时间戳>_<试炼id>`，值为该成员本周最好通关回合数；不新增表、列或货币。

## 奇遇定义

`adventures.json` 为奇遇对象数组。`id`、`name`、`text`、`weight`、`reward` 均必填且不接受额外字段；名称在奇遇间唯一，权重为正整数。同一路线内的权重按总和归一为出现概率，路线目录显示各奇遇概率。每条奇闻还必须定义 `options`（2-3 个互斥回响选项），每个选项含 `id`、`label`、`text` 与 `reward`；选项 id 在奇闻内唯一，选项奖励物品必须存在，选项奖励并入统一的奖励物品校验。`reward` 与 `text` 仍然是探索触发时的即时奖励与文案，回响只在玩家主动选择时结算选项奖励，两者互不影响。

```json
{
  "id": "spring",
  "name": "灵泉寻踪",
  "text": "踏入青岚秘境，在古树下寻得一处灵泉。",
  "weight": 30,
  "reward": {
    "exp": {"minimum": 15, "maximum": 40},
    "stones": {"minimum": 30, "maximum": 90},
    "items": {"spirit_food": {"minimum": 0, "maximum": 2}}
  }
}
```

## 历练路线定义

`exploration_routes.json` 为路线对象数组，定义可进入的境界门槛与所属奇遇；每条奇遇必须且只能归属一条路线。

```json
{
  "id": "spirit_spring",
  "name": "灵泉修行",
  "description": "寻泉静修，偏重修为与基础补给。",
  "min_realm": "qiling",
  "encounters": ["spring", "mountain"]
}
```

ID、名称、说明、`min_realm` 和 `encounters` 均必填，不接受额外字段。境界 ID 与奇遇 ID 必须分别引用 `realms.json` 和 `adventures.json` 中的定义；同一路线不得重复奇遇；七个大境界必须各有一条以该境界为准入门槛的路线。目录会显示进入门槛，未达境界时不消耗精力或冷却。路线从启灵的灵泉修行、凝气的星谷采集、筑基的古洞寻珍，逐步延伸到金丹赤霞寻脉、元婴归墟拾遗、化神太虚巡界和渡劫劫云问道。玩家首次遇见奇遇后，发现记录写入 SQLite 的 `adventure_discoveries`，作为个人长期图鉴和 `adventures_discovered` 成就指标；该状态不进入静态 JSON 或短期消息缓存。

## 共鸣定义

`resonances.json` 为对象数组。每项必须引用两个不同的已有种族，种族组合不能重复，且每个种族至少出现在一项组合中。`bonuses` 可定义 `hp`、`attack`、`defense`、`speed`；每项倍率为正且不超过 8%，总倍率不超过 10%。玩家状态和启用时间不写入静态文件。

`rules.json` 的 `resonance_cost` 定义启用成本，只能消耗灵石与材料。启用后属性加成只对组合内种族的当前出战宠物生效；该玩家的启用选择及时间存入 SQLite。

任务 event 允许 `sign/train/feed/explore/pve/pvp/breakthrough/evolve/bond/expedition`。签到成功后推进当日签到委托；重复消息重投不重复计数。离线委托只在归来成功领取奖励后推进；提前召回、尚未完成或重复领取都不计数。喂养和直接使用灵粮推进同一种任务；突破和血脉进化仅成功时计数；PVE 与排位论剑仅胜利计数，论剑只计挑战者获胜，不含平局、防守镜像或切磋。任务日和领取状态不出现在 JSON。

## 离线委托定义

`expeditions.json` 是对象数组，由 `domain/expedition_content.py` 的 `Expedition` 严格校验。委托定义与每日任务 `quests.json` 分离；委托成功结算后会产生 `expedition` 任务事件，永久已领取的行程数也用于累计成就。

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
- 现有前三境委托保持不变：`herb_gathering`（采灵药，启灵，25 精力）、`ore_survey`（寻锻矿，凝气，30 精力）、`essence_search`（探血髓，筑基，40 精力），分别提供灵粮、锻灵矿、血脉精华。新增 `jindan_alchemy`（赤霞炼丹，金丹，50 精力，破境丹）、`yuanying_stargazing`（归墟观星，元婴，60 精力，技能书）、`huashen_nether_egg`（幽庭觅卵，化神，70 精力，灵卵）和 `dujie_heaven_relic`（天门寻器，渡劫，80 精力，装备），均沿用现有物品与奖励快照规则。
- 行程秒数统一来自 `.env` 中的 `SPIRIT_PET_EXPEDITION_DURATION`，默认 3600。此 JSON 不允许 duration、duration_seconds、started_at、finishes_at、settled_at 等时间字段。

每次派遣绑定的宠物、操作号、开始/完成时间、抽取后的实际奖励快照和领取状态属于 SQLite 的行程记录。奖励范围是静态定义，实际抽取结果是运行数据，不能写回内容目录。派遣时固定奖励快照，之后修改任务名称、时长配置或奖励区间，不应追溯改写既有行程。历史详情必须从该行程自身的 `reward_snapshot` 读取实际修为、灵石和道具 ID/数量，不按当前奖励区间重新抽取；若旧物品定义已移除，仍以稳定物品 ID 和快照数量呈现。损坏的快照应明确拒绝回顾或领取，不能静默以静态定义代替。

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
| defense_tiers | 见下表 | 防守方按自然周守擂胜场领取的档位 |

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

`defense_tiers` 是与积分档位分开的根字段，数组 1-10 项，对象结构如下：

```json
{
  "id": "first",
  "name": "初守",
  "wins": 2,
  "stones": 100,
  "items": {"spirit_food": 1}
}
```

`wins` 是本周（北京时间自然周）守擂成功场次门槛，必须为正且严格递增；id、名称与 wins 分别唯一。灵石与物品数量不能随档位提升减少，每档至少一种正数量奖励，物品 ID 必须存在。防守档位不参与赛季积分档位选择，也不写入赛季结算。赛季创建时保存的规则快照可能早于该字段：读取旧快照时按当前内容补齐 `defense_tiers`，所以旧赛季页面与规则页仍能打开；防守奖励本身始终读取当前内容，不由快照重算。

自然月边界、赛季标识、积分、每日计数、参战宠物、比赛结果、永久挑战消息键/回复、规则快照与领奖记录属于运行逻辑和 SQLite。论剑冷却等运行配置写 `.env`，不能加到静态 JSON。赛季创建时保存完整规则快照，内容调整仅影响之后创建的赛季，不追溯改写已有赛季。镜像防守不扣精力或日主动次数，也不增加领奖资格；防守方镜像优先使用玩家设置的防守阵容，未设置或失效时沿用其出战阵容，守擂胜场奖励按自然周统计并写入 `quest_progress`。

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

技能 kind 为 damage、heal 或 utility；前两者 coefficient 为正的攻击倍率或最大气血恢复比例，治疗比例不得超过 1。utility 的 coefficient 必须为 0，且必须有 effects。`targeting` 默认是 `single`；`all` 仅用于无 effects 的 damage 技能，在施法瞬间锁定全部存活敌人后逐个结算，每名目标独立判定闪避、克制、护盾和受击天赋，即使反击击倒施法者也不截断本次锁定结算，施法与熟练度只计一次。全体攻击不受单体嘲阵改写目标。技能的 element 非空时，必须由 requirements.elements 或其祖先覆盖，不能把水技能标成“火宠也可学”。通用技能的 element 为 null。book_item 与 items 中 skill_id 必须互相引用。

装备 slot 为 weapon/armor/charm，对应灵器/护甲/饰品。bonuses 是 hp/attack/defense/speed 的非负固定增量，叠加在成长倍率计算之后，不随使用次数递增。穿戴与卸装使用 SQLite 库存事务，不修改 JSON。

`equipment_sets.json` 中每套至少包含两件、最多三件装备，套件必须占用不同槽位；一件装备不能属于多套。目录校验还要求存在至少一种灵宠，其类别与元素同时满足套件内每件装备的 requirements，避免定义出无法激活的套装。只有同一只灵宠同时装备套件内全部装备时，套装 bonuses 才生效，不能由背包持有或不同宠物拼出。套装加成是完成套件后额外叠加的固定属性，不受单件强化倍率放大；未知装备、重复部位、重复成员、不可达套件和零加成套件均在启动时拒绝。

四套内置套装的首次完成奖固定定义在 `gameplay/equipment_set_rewards.py`，复用 `quest_progress` 持久化一生一次的领取凭证，不扩展玩家存档或 `equipment_sets.json` 字段。自定义套装若尚无奖励配置，会显示“奖励待配置”且不提供领取入口。

`forge_levels.json` 必须完整包含 0-10 级。当前级的 `upgrade_stones/upgrade_items` 为升下一级成本，材料引用必须是 material。最后一级 upgrade_stones 为 null、upgrade_items 为空；仅 +0 的 bonus_multiplier 为 1，之后严格递增。该倍率只乘装备 bonuses，再向下取整，不能乘基础种族属性。

`skill_levels.json` 从 1 连续编号，当前级的 required_proficiency 是升下一级所需的熟练度，不是累积总量；满级为 null。power_multiplier 从 1 严格递增，实际技能系数乘此倍率。每次施放的熟练度由 rules.skill_proficiency_per_use 定义。运行中的 level/proficiency 存 learned_skills，不能写回 JSON。

技能预设只保存“携带了哪些技能”，不保存等级或熟练度。每只宠物三个方案，标记 `skill_preset_<宠物编号>_<方案>` 的 `progress` 记录技能数，`skill_preset_<宠物编号>_<方案>_<技能id>` 每门技能一行；应用时逐项校验技能仍存在、仍已学会、需求仍满足且不超过当前携带上限，再在同一事务内批量更新 `learned_skills.equipped`。技能目录追加新条目不会改变既有方案的含义，已删除的技能会明确报错而不是静默换位。

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
- taunt：仅 damage 技能可附加，target 必须为 self，power=0、duration 为 1-3 次自身行动；敌方优先攻击护阵单位，可被 dispel 移除。
- cleanse/dispel：即时移除，power=0、duration=0。净化针对己方，驱散针对敌方。
- 同一技能不能混合敌我效果，不允许重复 kind/target。damage 只附敌方效果，但允许单独附加 taunt self；heal 只附己方效果。
- 技能等级放大伤害、治疗、护盾量，不放大控制次数、弱化比例、攻击增益比例或免控次数。

示例：冰系伤害附带一次控制：

```json
{"kind": "stun", "target": "enemy", "power": 0, "duration": 1}
```

## 血脉分支与工艺

`lineages.json` 由 `domain/lineage_content.py` 定义。每个种族至少两条分支，species_id 必须存在，min_bloodline 至少为 1 且引用现有血脉。四维 stat_multipliers 各自限定 0.5-2，同种族的分支不能使用完全相同的四维；至少一项必须提升。cost 是必成选择成本，不含概率；道具成本必须引用材料。运行时只在 pets.lineage_id 保存选中的分支，不修改种族 ID。

`recipes.json` 由 `domain/crafting_content.py` 定义。每件 equipment 物品恰有一个配方，item_id/name 指向并对应物品；stones 为正，materials 与 salvage_materials 仅允许材料。材料必须有商店、初始资源或正数量奖励等非分解来源。enhancement_refund_percent 为 0-50 的整数百分比，不是概率。

分解回收通过 `salvage_yield` 统一计算：基础回收加每种累计升级材料投入乘回收百分比，按单件向下取整。校验遍历 +0 至 +10，要求每种材料回收不超过投入、整体严格损耗；有商店价格的回收不得比直接购买装备再分解更便宜。新增装备必须同时补配方，不能只在商店与装备图鉴出现而无法维护工艺链。

## 好友定义

好友同样没有独立内容文件：`rules.json` 的 `friend` 只给出名册上限与申请有效期。

    {"max_friends": 50, "request_hours": 24}

`FriendRule` 校验两个字段的区间（`max_friends` 1-200、`request_hours` 1-72）；`Catalog._validate_friend` 额外要求上限至少为 2——名册小到装不下第二个人就没有结交的可能，这种配置应在启动时直接失败，而不是等玩家撞上。

schema 24 新增两张表。`friend_links (user_low, user_high, created_at)` 用 `PRIMARY KEY(user_low, user_high)` 与 `CHECK(user_low < user_high)` 把「两人是好友」归一化成唯一一行：关系天然对称，既不可能重复记录，也不可能只记一半。`friend_requests (from_id, to_id, created_at, expires_at)` 用 `PRIMARY KEY(from_id, to_id)` 锁定单向待处理申请，`CHECK(from_id != to_id)` 禁止自申请，`CHECK(expires_at > created_at)` 保证有效期为正。索引 `friend_link_low` 与 `friend_link_high` 服务「我的好友」两个方向，`friend_request_inbox` 服务待我处理，`friend_request_outbox` 服务我发出的。

两张表互不蕴含：申请只是意图，接受时才在同一事务里写入归一化边并删除申请；任一方「解除」直接删除该行，双方名册同时消失。因此查询好友一律是 `WHERE user_low=? OR user_high=?`，名册计数也必须同时统计两列，否则一半好友不会计入上限。


## 战报分享定义

分享同样没有独立内容文件：`rules.json` 的 `share` 只给出每日次数、分享码有效期与每页条数。

    {"daily_limit": 5, "code_days": 7, "list_page_size": 5}

`ShareRule` 校验三个字段的区间（`daily_limit` 1-20、`code_days` 1-30、`list_page_size` 1-10）；`Catalog._validate_share` 要求有效期至少一天。

schema 25 新增单表 `battle_shares`：`share_id` 主键并限定长度 6-24（分享码是凭据，太短就能被穷举），`battle_id` 外键指向 `battle_records`，`owner_id` 外键指向 `players`，`created_at`/`expires_at`（`CHECK(expires_at > created_at)`）、`state` 取 `active`/`revoked`、`closed_at`、`views`（`CHECK(views >= 0)`）。表级 CHECK 把状态与关闭时间绑死：`active` 必须没有关闭时间，`revoked` 必须有。索引 `battle_share_owner (owner_id, state, created_at DESC)` 服务「我的分享」，`battle_share_battle` 服务按战报反查。

表里只存 `battle_id`，不复制 `snapshot`：战报本身已经不可变，复制只会多出一条会漂移的路径。分享码由 `secrets` 随机生成、字母表去掉 `0/O/1/I`（需要口头转述与人手重输），因此不可能从自增的战报编号推出。读取路径与参与者的读取路径是两个独立出口：`灵宠战报 查看` 仍走 `repo.battle_report` 的参与者校验，`灵宠分享 查看 <码>` 只认有效分享码，两者共用同一个渲染函数，所以分享不会成为绕过参与者校验的后门。

`share_rewards.json` 是分享读者里程碑数组，由 `domain/share_reward_content.py` 的 `ShareReward` 校验：每项声明 `readers`（1-100）、`name`、`stones`（非负）与 `items`（物品 id → 正整数），奖励不能全空。`Catalog._validate_share_rewards` 强制档位恰为 3、10、30；物品必须存在且为 `consumable`/`material`；读者越多奖励不得越低。读者去重行写入分享者名下的 `quest_progress` 的 `shareview_<读者 user_id>`，同一读者只一行；领取标记写 `share_read_reward_<读者数>`，`progress` 保存领取时的读者数，`claimed=1`。

`灵宠分享榜` 没有独立内容文件：它直接按 `shareview_` 前缀分组计数，JOIN `players` 与 `player_identity` 只用于确认玩家存在并取 UID（`identity.id + 9999`，与收集榜同一口径）；排序为读者数降序、user_id 升序，展示前十。榜单不写表、不发奖励，因此没有可配置档位；改榜口径只需改 `gameplay/share_board.py` 的查询，不需要新增 schema 或内容 JSON。

`share_rank_rewards.json` 是分享榜名次奖励数组，由 `domain/share_rank_reward_content.py` 的 `ShareRankReward` 校验：每项声明 `rank`（1-100）、`name`、`stones`（非负）与 `items`（物品 id → 正整数），奖励不能全空。`Catalog._validate_share_rank_rewards` 强制档位恰为 1、3、10；物品必须存在且为 `consumable`/`material`；名次越高奖励不得越低。领取标记写 `share_rank_reward_<名次>`，`progress` 保存领取时的实际名次，`claimed=1`；榜单本身仍由 `shareview_` 行派生。

`灵宠历练战绩` 也没有独立内容文件：它从 `battle_records` 中 `kind='pve'` 且 `battle_key` 以 `ambush_` 开头的永久战报派生，JOIN `battle_participants` 限定本人，按当前 `exploration_routes` 过滤未知路线；页面的场次、胜负平、最近五场都即时计算，不写 `quest_progress`、不重新抽奖，也不改伏击奖励或概率。

`灵宠切磋战绩` 同样没有独立内容文件：它从 `battle_records` 的 `kind='spar'` 行派生，用对侧 `battle_participants` 识别对手，并以 `player_identity.id + 9999` 展示 UID；列表按对手聚合，详情只读取本人参与的战报，不新增表、列或内容 JSON。

`灵宠切磋榜` 也没有独立内容文件：它按 `utils.time.beijing_week()` 的本周起止过滤 `battle_records` 的 `spar` 行，按参与者聚合胜/负/平/场次，展示前十；周榜随自然周自动换窗，不写 `quest_progress`、不发奖励，也不改切磋结算。

## 垂钓择饵与鱼篓

`fishing_spots.json` 为三处水域，`FishingSpot` 校验非空描述、至少三个不重复鱼获、正整数权重与数量区间、精力 1-100；目录校验物品引用。`fishing_baits.json` 为三种饵料（3 项），`FishingBait` 声明 id/name/description、`cost_item`、`cost_quantity`（1-10）、`favored_items`（非空且不重复）与 `multiplier`（2-5，实配 3）。名称唯一，`plain`/素饵保留；费用物品与偏向鱼获必须存在。素饵没有内容行，不收额外费用。

实际权重仅将水域表内命中 `favored_items` 的条目乘以 multiplier，其他权重和数量区间保持原值；没有任何匹配鱼获的饵料不可在该水域使用。详情以同一个权重函数显示精确比值与近似百分比。饵料不新增物品或奖励，使用既有灵粮/锻灵矿。

schema 27 新增 `fishing_casts`：自增 `cast_id`、唯一 `operation_id`、玩家外键、时间、`snapshot` 与 `reply` JSON；索引按本人/cast_id 倒序读取五条。snapshot 保存当时伙伴/水域/饵料/费用/物品名称、id、数量、精力与权重，reply 保存包括蓝字的原结算。通用缓存清除后仍先验证永久记录的操作归属并返回原回复。鱼获、每日竿数和集齐凭证沿用 quest_progress，不从旧数据伪造逐竿历史。

26→27 沿用冻结结构校验、一致备份、单事务建表/索引与版本更新，校验完整性和外键；失败保持 26。`legacy_schema26` 剥离鱼篓，25 及更早的重建继续逐级剥离，UID/注册顺序不变。所有测试使用隔离库，不接触运行存档。
