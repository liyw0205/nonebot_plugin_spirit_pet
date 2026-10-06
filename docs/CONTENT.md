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
| rules.json | 初始资源、签到奖励、训练收益、精力消耗、队伍人数等静态数值 |
| dao_names.json | 随机道号的前缀与后缀词库，不保存已占用道号 |
| categories.json | 羽、兽、龙、甲、虫、植、蛇、灵八类定义 |
| elements.json | 五行、分支的父系引用、风雷毒及克制关系 |
| equipment.json | 装备槽位、固定属性、元素/类别/境界门槛 |
| skills.json | 技能效果、元素、倍率、学习门槛与秘笈引用 |
| talents.json | 种族天赋的名称、效果类型、强度与可选元素限制 |
| skill_levels.json | 技能等级、升到下一级消耗的熟练度、威力倍率 |
| forge_levels.json | +0 至 +10 强化倍率与下一级灵石、材料成本 |

除 `rules.json`、`dao_names.json` 为对象外，其余文件均为对象数组。不要往这些文件写 `created_at`、`last_train`、`sign_day`、`expires_at`、`timestamp`、`cooldown`、玩家 ID 或库存数量。

冷却间隔、邀请有效秒数、精力恢复间隔属于运行配置，放在 `.env`；某玩家的最后修炼时间、准备状态、邀请截止时间属于 SQLite。静态的“进化需要 3 个血脉精华”是成本，不是库存。

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

奖励固定用区间对象，不混用数组与数字：

```json
{
  "exp": {"minimum": 30, "maximum": 60},
  "stones": {"minimum": 50, "maximum": 80},
  "items": {"bloodline_essence": {"minimum": 1, "maximum": 2}}
}
```

固定奖励将 minimum 与 maximum 设成相同值。掉落可以为零，成本和权重必须为正，奖励最小值不能大于最大值。

任务 event 仅允许 `train/feed/explore/pve/evolve`。领取不会推进任务；喂养和直接使用灵粮推进同一种任务；PVE 仅胜利计数。任务日和领取状态不出现在 JSON。

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

技能 kind 为 damage 或 heal；coefficient 为攻击倍率或最大气血恢复比例，治疗比例不得超过 1。技能的 element 非空时，必须出现在自己的 requirements.elements 中，不能把水技能标成“火宠也可学”。通用技能的 element 为 null。book_item 与 items 中 skill_id 必须互相引用。

装备 slot 为 weapon/armor/charm，对应灵器/护甲/饰品。bonuses 是 hp/attack/defense/speed 的非负固定增量，叠加在成长倍率计算之后，不随使用次数递增。穿戴与卸装使用 SQLite 库存事务，不修改 JSON。

`forge_levels.json` 必须完整包含 0-10 级。当前级的 `upgrade_stones/upgrade_items` 为升下一级成本，材料引用必须是 material。最后一级 upgrade_stones 为 null、upgrade_items 为空；仅 +0 的 bonus_multiplier 为 1，之后严格递增。该倍率只乘装备 bonuses，再向下取整，不能乘基础种族属性。

`skill_levels.json` 从 1 连续编号，当前级的 required_proficiency 是升下一级所需的熟练度，不是累积总量；满级为 null。power_multiplier 从 1 严格递增，实际技能系数乘此倍率。每次施放的熟练度由 rules.skill_proficiency_per_use 定义。运行中的 level/proficiency 存 learned_skills，不能写回 JSON。

天赋 kind 支持 fury、first_strike、lifesteal、counter、shield、regeneration、execute、evasion、venom、pierce。power 为 (0, 1] 的比例，只有 fury 可以设置 element 过滤，且应与所属宠物灵根兼容。所有天赋均由 `gameplay/talents.py` 解释，描述文案不能代替实际效果实现。毒伤剩余行动数、当前护盾、首次攻击状态只存在单场 Fighter 内存中。

学习、携带、穿戴以及构建战斗单位时均执行适用条件检查。只在图鉴显示限制但实际战斗不检查，或者只限制学习却允许借其他宠物携带，都是不允许的实现。

道号前缀和后缀各一至四个汉字，生成后由数据库唯一约束保证不重复；组合耗尽时添加不超过四位的数字。生成规则不使用用户 ID，改名不改变存档归属。
