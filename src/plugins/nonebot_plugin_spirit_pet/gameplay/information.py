from ..application.context import Context
from ..domain.models import Reply
from .loadout import combatant


def help_game(ctx: Context, arg: str) -> Reply:
    return Reply("灵宠仙途", (
        "结契：灵宠领养 青鸾 / 灵宠召唤 1 / 灵宠列表 / 灵宠切换 编号",
        "成长：我的灵宠 / 灵宠签到 / 灵宠喂养 / 灵宠修炼 / 灵宠突破 / 灵宠进化",
        "道具：灵宠背包 / 灵宠商店 / 灵宠购买 灵粮 3 / 灵宠使用 回元丹 1",
        "秘境：灵宠历练 / 灵宠秘境 / 灵宠挑战 青岚林 / 灵宠任务 / 灵宠领奖 任务名",
        "对战：灵宠论剑 道号 / 灵宠切磋 道号 / 灵宠应战 / 灵宠拒战",
        "灵物：灵宠装备 / 灵宠装备 青岚翎 / 灵宠卸装 灵器 / 灵宠装备图鉴",
        "灵术：灵宠技能 / 灵宠学习 风刃术 / 灵宠携带 风刃术 / 灵宠卸技 风刃术",
        "组队：灵宠组队 / 灵宠入队 队长道号 / 灵宠队伍 / 灵宠准备 / 灵宠取消准备",
        "出征：灵宠组队挑战 上古灵殿 / 灵宠退队",
        "其他：灵宠改名 名字 / 我的道号 / 灵宠道号 新道号 / 灵宠图鉴 / 灵宠排行",
    ), ("灵宠领养 青鸾", "我的灵宠", "灵宠秘境", "灵宠任务"))


def status(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    stats = combatant(ctx).stats
    species = ctx.content.species[pet.species_id]
    major = pet.layer == 10
    cost = ctx.content.realms[pet.realm].advancement if major else ctx.content.layers[pet.layer].advancement
    scale = 1 if major else pet.realm + 1
    breakthrough = (
        f"{'大' if major else '小'}境界突破：{cost.exp * scale} 修为、{cost.stones * scale} 灵石"
        f" · 成功率 {min(1, cost.chance + pet.affinity / 1000):.0%}"
        if cost else "已达当前最高境界十层。"
    )
    bloodline = ctx.content.bloodlines[pet.bloodline]
    evolution = bloodline.evolution
    evolve_line = "已达当前最高血脉。" if evolution is None else (
        f"进化：{evolution.exp} 修为、{evolution.stones} 灵石、"
        + "、".join(f"{ctx.content.items[key].name} {amount}" for key, amount in evolution.items.items())
    )
    return Reply(pet.name, (
        f"道号：{player.dao_name}",
        f"编号 {pet.pet_id} · 种族：{ctx.content.species[pet.species_id].name}",
        f"类别：{ctx.content.categories[species.category].name}"
        f" · 灵根：{'、'.join(ctx.content.elements[key].name for key in species.elements)}",
        f"境界：{ctx.content.realms[pet.realm].name} {pet.layer}层 · 血脉：{bloodline.name}",
        f"修为：{pet.exp} · 灵石：{player.stones}",
        f"精力：{pet.energy}/100 · 亲密：{pet.affinity}/100",
        f"气血：{stats.hp} · 攻击：{stats.attack} · 防御：{stats.defense} · 速度：{stats.speed}",
        breakthrough, evolve_line,
    ), ("灵宠突破", "灵宠进化", "灵宠喂养", "灵宠修炼"))


def catalog(ctx: Context, arg: str) -> Reply:
    pool = ctx.content.pools["standard"]
    total = sum(entry.weight for entry in pool.entries)
    weights = {entry.species: entry.weight for entry in pool.entries}
    return Reply("万灵图鉴", tuple(
        f"{species.name}（{ctx.content.categories[species.category].name}"
        f" · {'/'.join(ctx.content.elements[key].name for key in species.elements)}）：{species.description}"
        f" · {'初始可选' if species.starter else '召唤限定'}"
        f" · 召唤概率 {weights.get(species.id, 0) / total:.1%}"
        for species in ctx.content.species.values()
    ), ("灵宠召唤", "灵宠列表"))


def rank(ctx: Context, arg: str) -> Reply:
    rows = ctx.repo.conn.execute(
        "SELECT name, realm, layer, exp, dao_name FROM ("
        "SELECT p.*, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY realm DESC, layer DESC, exp DESC, pet_id) n "
        "FROM pets p) ranked JOIN players owner ON ranked.user_id=owner.user_id "
        "WHERE n=1 ORDER BY realm DESC, layer DESC, exp DESC, pet_id LIMIT 10"
    ).fetchall()
    return Reply("万灵榜", tuple(
        f"{index}. {row['dao_name']} · {row['name']} · {ctx.content.realms[row['realm']].name} {row['layer']}层"
        f" · 修为 {row['exp']}" for index, row in enumerate(rows, 1)
    ) or ("尚无灵宠入榜。",))


def pvp_rank(ctx: Context, arg: str) -> Reply:
    rows = ctx.repo.conn.execute(
        "SELECT p.rating, p.dao_name, t.name FROM players p JOIN pets t ON t.pet_id=p.active_pet_id "
        "ORDER BY p.rating DESC, p.user_id LIMIT 10"
    ).fetchall()
    return Reply("论剑榜", tuple(
        f"{index}. {row['dao_name']} · {row['name']} · 积分 {row['rating']}" for index, row in enumerate(rows, 1)
    ) or ("暂无玩家。",))
