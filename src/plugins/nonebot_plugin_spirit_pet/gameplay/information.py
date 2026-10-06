from ..application.context import Context
from ..domain.content import Species
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from .loadout import combatant
from .lineage import describe_multipliers


def element_line(ctx: Context, species: Species) -> str:
    secondary = [ctx.content.elements[key].name for key in species.elements if key != species.primary_element]
    return f"主属性：{ctx.content.elements[species.primary_element].name} · 副属性：{'、'.join(secondary) or '无'}"


def help_game(ctx: Context, arg: str) -> Reply:
    return Reply("灵宠仙途", (
        "结契：灵宠领养 青鸾 / 灵宠召唤 1 / 灵宠列表 / 灵宠切换 编号 / 灵宠使用 灵卵名称",
        "成长：我的灵宠 / 灵宠签到 / 灵宠喂养 / 灵宠修炼 / 灵宠突破 / 灵宠进化",
        "血脉：灵宠血脉 / 灵宠分支 分支名",
        "道具：灵宠背包 / 灵宠商店 / 灵宠购买 灵粮 3 / 灵宠使用 回元丹 1",
        "秘境：灵宠历练 / 灵宠秘境 / 灵宠挑战 青岚林 / 灵宠任务 / 灵宠领奖 任务名",
        "对战：灵宠论剑 道号 / 灵宠切磋 道号 / 灵宠应战 / 灵宠拒战",
        "灵物：灵宠装备 / 灵宠装备 青岚翎 / 灵宠强化 灵器 / 灵宠卸装 灵器 / 灵宠装备图鉴",
        "工坊：灵宠工坊 / 灵宠打造 青岚翎 / 灵宠分解 青岚翎 +0 1",
        "灵术：灵宠技能 / 灵宠技能图鉴 / 灵宠学习 风刃术 / 灵宠携带 风刃术 / 灵宠卸技 风刃术",
        "组队：灵宠组队 / 灵宠入队 队长道号 / 灵宠队伍 / 灵宠准备 / 灵宠取消准备",
        "出征：灵宠组队挑战 上古灵殿 / 灵宠退队",
        "其他：灵宠改名 名字 / 我的道号 / 灵宠道号 新道号 / 灵宠图鉴 / 灵宠排行",
    ), ("灵宠领养 青鸾", "我的灵宠", "灵宠秘境", "灵宠任务"))


def status(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    stats = combatant(ctx).stats
    species = ctx.content.species[pet.species_id]
    talent = ctx.content.talents[species.talent]
    major = pet.layer == 10
    cost = ctx.content.realms[pet.realm].advancement if major else ctx.content.layers[pet.layer].advancement
    scale = 1 if major else pet.realm + 1
    breakthrough = (
        f"{'大' if major else '小'}境界突破：{cost.exp * scale} 修为、{cost.stones * scale} 灵石"
        f" · 成功率 {min(1, cost.chance + pet.affinity / 1000):.0%}"
        if cost else "已达当前最高境界十层。"
    )
    bloodline = ctx.content.bloodlines[pet.bloodline]
    branch = ctx.content.lineages.get(pet.lineage_id)
    branch_line = (f"分支：{branch.name} · {describe_multipliers(branch.stat_multipliers)}"
                   if branch else "血脉分支：尚未选择")
    evolution = bloodline.evolution
    evolve_line = "已达当前最高血脉。" if evolution is None else (
        f"进化：{evolution.exp} 修为、{evolution.stones} 灵石、"
        + "、".join(f"{ctx.content.items[key].name} {amount}" for key, amount in evolution.items.items())
    )
    return Reply(pet.name, (
        f"道号：{player.dao_name}",
        f"编号 {pet.pet_id} · 种族：{ctx.content.species[pet.species_id].name}",
        f"类别：{ctx.content.categories[species.category].name} · {element_line(ctx, species)}",
        f"天赋神通：{talent.name} · {talent.description}",
        f"境界：{ctx.content.realms[pet.realm].name} {pet.layer}层 · 血脉：{bloodline.name}",
        branch_line,
        f"修为：{pet.exp} · 灵石：{player.stones}",
        f"精力：{pet.energy}/100 · 亲密：{pet.affinity}/100",
        f"气血：{stats.hp} · 攻击：{stats.attack} · 防御：{stats.defense} · 速度：{stats.speed}",
        breakthrough, evolve_line,
    ), ("灵宠突破", "灵宠进化", "灵宠喂养", "灵宠修炼"))


def catalog(ctx: Context, arg: str) -> Reply:
    if arg and not arg.isdecimal():
        species = named(ctx.content.species, arg)
        talent = ctx.content.talents[species.talent]
        stats = species.stats
        return Reply(f"万灵图鉴 · {species.name}", (
            species.description,
            f"类别：{ctx.content.categories[species.category].name} · {element_line(ctx, species)}",
            f"天赋神通：{talent.name} · {talent.description}",
            f"初始气血 {stats.hp} · 攻击 {stats.attack} · 防御 {stats.defense} · 速度 {stats.speed}",
            f"初始亲密 {species.initial_affinity} · 修炼加成 {species.training_bonus:.0%}",
            acquisition(ctx, species),
        ), ("灵宠图鉴", "灵宠召唤", "灵宠秘境"))
    species_list = list(ctx.content.species.values())
    page = quantity(arg or "1", 999)
    pages = (len(species_list) + 4) // 5
    if page > pages:
        raise GameError(f"万灵图鉴共 {pages} 页。")
    lines = []
    for species in species_list[(page - 1) * 5:page * 5]:
        talent = ctx.content.talents[species.talent]
        lines.extend((
            f"{species.name} · {ctx.content.categories[species.category].name} · {element_line(ctx, species)}",
            f"天赋：{talent.name} · {species.description}", acquisition(ctx, species),
        ))
    actions = ["灵宠召唤", "灵宠列表"]
    if page > 1:
        actions.append(f"灵宠图鉴 {page - 1}")
    if page < pages:
        actions.append(f"灵宠图鉴 {page + 1}")
    return Reply(f"万灵图鉴 {page}/{pages}", tuple(lines), tuple(actions))


def acquisition(ctx: Context, species: Species) -> str:
    sources = ["初始可选"] if species.starter else []
    pool = ctx.content.pools["standard"]
    weight = sum(entry.weight for entry in pool.entries if entry.species == species.id)
    if weight:
        sources.append(f"召唤概率 {weight / sum(entry.weight for entry in pool.entries):.1%}")
    for item in ctx.content.items.values():
        if item.kind != "pet_egg" or item.species_id != species.id:
            continue
        dungeons = [dungeon.name for dungeon in ctx.content.dungeons.values()
                    if item.id in dungeon.reward.items and dungeon.reward.items[item.id].maximum > 0]
        sources.append(f"{item.name}孵化" + (f"（{'、'.join(dungeons)}掉落）" if dungeons else ""))
    return "获取：" + "；".join(sources)


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
