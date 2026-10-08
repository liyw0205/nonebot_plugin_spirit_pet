from ..application.context import Context
from ..domain.content import Species
from ..domain.models import GameError, Reply
from ..utils.arguments import named, quantity
from .companionship import active_bond_streak
from .cultivation import MAJOR_BREAKTHROUGH_PITY, breakthrough_chance
from .effects import BOND_GUARD_AFFINITY
from .loadout import combatant
from .lineage import describe_multipliers


def element_line(ctx: Context, species: Species) -> str:
    secondary = [ctx.content.elements[key].name for key in species.elements if key != species.primary_element]
    return f"主属性：{ctx.content.elements[species.primary_element].name} · 副属性：{'、'.join(secondary) or '无'}"


def help_game(ctx: Context, arg: str) -> Reply:
    return Reply("灵宠仙途", (
        "结契：灵宠领养 青鸾 / 灵宠召唤 1 / 灵宠列表 / 灵宠出战 编号 [编号] [编号] / 灵宠切换 编号 / 灵宠封存 编号 / 灵宠封存库 / 灵宠复原 编号",
        "成长：我的灵宠 / 灵宠签到 / 灵宠互动 [编号] / 灵宠喂养 [编号] / 灵宠修炼 [编号] / 灵宠合修 编号 / 灵宠突破 [编号] / 灵宠进化 [编号]",
        "血脉：灵宠血脉 / 灵宠分支 分支名",
        "道具：灵宠背包 / 灵宠商店 / 灵宠购买 灵粮 3 / 灵宠使用 回元丹 1",
        "秘境：灵宠历练 [路线] / 灵宠奇闻 [页] / 灵宠奇闻榜 / 灵宠秘境 / 灵宠挑战 青岚林 / 灵宠任务 / 灵宠领奖 任务名",
        "关卡：灵宠关卡 / 灵宠挑战关卡 编号或名称 / 灵宠组队关卡 编号或名称",
        "对战：灵宠论剑 / 灵宠论剑 道号 / 灵宠切磋 道号",
        "赛季：灵宠赛季 / 灵宠匹配 / 灵宠论剑榜 / 灵宠赛季奖励 / 灵宠赛季领奖 赛季号",
        "灵物：灵宠装备 / 灵宠装备 青岚翎 / 灵宠套装 / 灵宠强化 灵器 / 灵宠卸装 灵器 / 灵宠装备图鉴",
        "工坊：灵宠工坊 / 灵宠打造 青岚翎 / 灵宠分解 青岚翎 +0 1",
        "灵术：灵宠技能 / 灵宠技能图鉴 / 灵宠学习 风刃术 / 灵宠携带 风刃术 / 灵宠卸技 风刃术",
        "组队：灵宠组队 / 灵宠入队 队长道号 / 灵宠邀请 道号 / 灵宠队伍",
        "审批：灵宠队务 / 灵宠队伍同意 道号 / 灵宠队伍拒绝 道号 / 灵宠队伍撤回 道号",
        "管理：灵宠队伍 道号 / 灵宠踢人 道号 / 灵宠转让 道号 / 灵宠退队 / 灵宠解散",
        "出征：灵宠准备 / 灵宠取消准备 / 灵宠组队挑战 上古灵殿",
        "派遣：灵宠委托 / 灵宠派遣 名称 / 灵宠行程 / 灵宠归来 行程号 / 灵宠召回 行程号",
        "其他：我的道号 / 灵宠道号 新道号 / 灵宠图鉴 / 灵宠排行",
        "收集与战报：灵宠收集 [页] / 灵宠成就 [页] / 灵宠成就领奖 成就名 / 灵宠战报 [页]",
        "共鸣：灵宠共鸣 / 灵宠共鸣 查看 名称 / 灵宠共鸣 激活 名称 / 灵宠共鸣 停用",
    ), ("灵宠领养 青鸾", "我的灵宠", "灵宠秘境", "灵宠任务"))


def status(ctx: Context, arg: str) -> Reply:
    player, pet = ctx.player(), ctx.pet()
    roster = ctx.repo.active_pets(ctx.user_id)
    expedition = ctx.repo.active_expedition(pet.pet_id)
    activity = ()
    commands = ("灵宠突破", "灵宠进化", "灵宠互动", "灵宠喂养", "灵宠修炼", "灵宠行程")
    if expedition is not None:
        state = "外出中" if ctx.now < expedition["finishes_at"] else "已完成，待领取"
        activity = (f"行程：{expedition['task_name']} · {state}。",)
        commands = ("灵宠行程", "灵宠列表", "灵宠装备", "灵宠技能")
    fighter = combatant(ctx)
    stats = fighter.stats
    selected_resonance = ctx.repo.player_resonance(player.user_id)
    resonance = (
        ctx.content.resonances.get(selected_resonance["resonance_id"])
        if selected_resonance is not None else None
    )
    resonance_status = fighter.resonance_name or (
        f"{resonance.name}（当前出战灵宠不匹配）" if resonance else "无"
    )
    species = ctx.content.species[pet.species_id]
    talent = ctx.content.talents[species.talent]
    major = pet.layer == 10
    cost = ctx.content.realms[pet.realm].advancement if major else ctx.content.layers[pet.layer].advancement
    scale = 1 if major else pet.realm + 1
    if cost:
        breakthrough = (
            f"{'大' if major else '小'}境界突破：{cost.exp * scale} 修为、{cost.stones * scale} 灵石"
            f" · 成功率 {breakthrough_chance(pet, cost):.0%}"
        )
        if major and pet.major_breakthrough_failures:
            bonus = pet.major_breakthrough_failures * MAJOR_BREAKTHROUGH_PITY
            breakthrough += f" · 连续失败 {pet.major_breakthrough_failures} 次，积累 +{bonus:.0%}"
    else:
        breakthrough = "已达当前最高境界十层。"
    bloodline = ctx.content.bloodlines[pet.bloodline]
    branch = ctx.content.lineages.get(pet.lineage_id)
    branch_line = (f"分支：{branch.name} · {describe_multipliers(branch.stat_multipliers)}"
                   if branch else "血脉分支：尚未选择")
    bond_guard = (
        "心契护佑：已启用，每场战斗首次受控时自动抵挡。"
        if pet.affinity >= BOND_GUARD_AFFINITY else
        f"心契护佑：亲密达到 {BOND_GUARD_AFFINITY} 后解锁。"
    )
    evolution = bloodline.evolution
    evolve_line = "已达当前最高血脉。" if evolution is None else (
        f"进化：{evolution.exp} 修为、{evolution.stones} 灵石、"
        + "、".join(f"{ctx.content.items[key].name} {amount}" for key, amount in evolution.items.items())
    )
    return Reply(pet.name, (
        f"道号：{player.dao_name}",
        *activity,
        f"出战阵容：{'、'.join(f'{item.name}（{item.pet_id}）' for item in roster)}",
        f"编号 {pet.pet_id} · 种族：{ctx.content.species[pet.species_id].name}",
        f"类别：{ctx.content.categories[species.category].name} · {element_line(ctx, species)}",
        f"天赋神通：{talent.name} · {talent.description}",
        f"境界：{ctx.content.realms[pet.realm].name} {pet.layer}层 · 血脉：{bloodline.name}",
        branch_line,
        f"修为：{pet.exp} · 灵石：{player.stones}",
        f"精力：{pet.energy}/100 · 亲密：{pet.affinity}/100",
        bond_guard,
        f"连续陪伴：当前 {active_bond_streak(player, ctx.now)} 天 · 最佳 {player.best_bond_streak} 天",
        f"气血：{stats.hp} · 攻击：{stats.attack} · 防御：{stats.defense} · 速度：{stats.speed}",
        f"战斗共鸣：{resonance_status}",
        breakthrough, evolve_line,
    ), commands)


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
        rate = weight / sum(entry.weight for entry in pool.entries)
        guarantee = " · 十连珍稀保底池" if species.id in pool.guaranteed_species else ""
        sources.append(f"召唤概率 {rate:.1%}{guarantee}")
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
        "FROM pets p WHERE archived=0) ranked JOIN players owner ON ranked.user_id=owner.user_id "
        "WHERE n=1 ORDER BY realm DESC, layer DESC, exp DESC, pet_id LIMIT 10"
    ).fetchall()
    return Reply("万灵榜", tuple(
        f"{index}. {row['dao_name']} · {row['name']} · {ctx.content.realms[row['realm']].name} {row['layer']}层"
        f" · 修为 {row['exp']}" for index, row in enumerate(rows, 1)
    ) or ("尚无灵宠入榜。",))


def adventure_rank(ctx: Context, arg: str) -> Reply:
    encounter_ids = tuple(ctx.content.encounters)
    placeholders = ",".join("?" for _ in encounter_ids)
    rows = ctx.repo.conn.execute(
        "SELECT owner.dao_name, COUNT(discovery.encounter_id) AS found, "
        "MAX(discovery.discovered_at) AS last_found "
        "FROM players owner JOIN adventure_discoveries discovery ON discovery.user_id=owner.user_id "
        f"AND discovery.encounter_id IN ({placeholders}) "
        "GROUP BY owner.user_id "
        "ORDER BY found DESC, last_found DESC, owner.dao_name COLLATE NOCASE LIMIT 10",
        encounter_ids,
    ).fetchall()
    total = len(encounter_ids)
    return Reply("山海奇闻榜", tuple(
        f"{index}. {row['dao_name']} · 奇闻 {row['found']}/{total}"
        for index, row in enumerate(rows, 1)
    ) or ("尚无修士发现历练奇闻。",))
