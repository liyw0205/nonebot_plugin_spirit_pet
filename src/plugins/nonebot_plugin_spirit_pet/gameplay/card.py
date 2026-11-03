"""灵宠名帖: a cultivator's card, with visibility that follows what the game publishes.

Schema 24 made friendship a player-managed edge and schema 26 let friends lend companions
(``灵宠借力 借用 <好友UID> <编号>``), so the game now asks players to type a stranger's UID
and browse that stranger's pets — while offering no way to see who they are. ``我的信息``
only ever renders your own account, and 名帖 elsewhere in the codebase means a *team
lineup*, not a person.

The card therefore has three tiers, chosen so the card never publishes more than the
existing boards already do:

* ``public`` — UID, the active companion's realm/layer, 论剑段位, 收集榜名次 and the worn
  title. 论剑榜/收集榜 already print tiers and standings, and a title is chosen to be shown.
* ``friend`` — adds the lineup in detail, achievement count, 图鉴 progress, friend count and
  how many companions they have lent (which is exactly what 借力 needs to know).
* ``self`` — the same detail for yourself; 灵石/背包/封存/注册时间 are never rendered here at
  all, because they already live in ``我的信息`` and a card is not the place to leak them.

Everything is derived on read from existing tables: no schema change, no content file, and
no cached snapshot that could go stale or outlive a friendship.
"""

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply
from . import achievements, borrow, collection_rank, friends, titles
from .arena.common import current_season, rating
from .arena.tier_rewards import tier_of
from .pets import pet_label

TITLE = "灵宠名帖"
SELF = "self"
FRIEND = "friend"
PUBLIC = "public"


def relation(ctx: Context, user_id: str) -> str:
    """How much of ``user_id``'s card the caller may see."""
    if user_id == ctx.user_id:
        return SELF
    return FRIEND if friends.linked(ctx, user_id, ctx.user_id) else PUBLIC


def _tier_name(ctx: Context, user_id: str) -> str:
    season = current_season(ctx)
    return tier_of(season, rating(ctx, season, user_id)).name


def _standing(ctx: Context, user_id: str) -> str:
    rank = collection_rank.personal_rank(ctx, user_id)
    return f"第 {rank} 名" if rank is not None else "尚未入榜"


def _realm_line(ctx: Context, user_id: str) -> str:
    lineup = ctx.repo.active_pets(user_id)
    if not lineup:
        return "出战：尚未选择伙伴"
    realms = [ctx.content.realms[pet.realm].name for pet in lineup]
    layers = [f"{realm} {pet.layer}层" for realm, pet in zip(realms, lineup)]
    return f"出战境界：{'、'.join(layers)}"


def _title_line(ctx: Context, user_id: str) -> str:
    holder = titles.current(ctx, user_id)
    return f"称号：{holder.name}" if holder is not None else "称号：尚无"


def card(ctx: Context, arg: str) -> Reply:
    if ctx.repo.player(ctx.user_id) is None:
        return Reply(
            TITLE,
            (
                "尚未结契，先完成领养，才能查看修士名帖。",
                "名帖按 UID 查看：陌生修士只显示榜单上已有的公开信息，好友能看到出战阵容与收集进度。",
            ),
            ("灵宠帮助",),
            (InlineCommand(0, "开始领养", "灵宠领养 "),),
        )
    text = arg.strip()
    if not text:
        target_id = ctx.user_id
    elif text.isdecimal():
        target = ctx.repo.player_by_uid(text)
        if target is None:
            raise GameError("未找到该 UID 对应的修士。")
        target_id = target.user_id
    else:
        raise GameError("格式：灵宠名帖 [UID]。不填则查看自己的名帖。")
    target = ctx.repo.player(target_id)
    if target is None:
        raise GameError("未找到该修士。")
    level = relation(ctx, target_id)
    lines = [
        f"UID {target.uid} · {'本人' if level == SELF else ('好友' if level == FRIEND else '陌生修士')}",
        _title_line(ctx, target_id),
        _realm_line(ctx, target_id),
        f"论剑段位：{_tier_name(ctx, target_id)} · 收集榜：{_standing(ctx, target_id)}",
    ]
    links = []
    if level != PUBLIC:
        lineup = ctx.repo.active_pets(target_id)
        if lineup:
            lines.append("出战阵容：")
            for pet in lineup:
                lines.append(
                    f"{pet_label(ctx, pet)} · {ctx.content.realms[pet.realm].name} {pet.layer}层"
                )
        lines.append(
            f"成就：已领取 {achievements.claimed_count(ctx, target_id)} 项"
            f" · 图鉴：{collection_rank.collected_species(ctx, target_id)}"
            f"/{len(ctx.content.species)} 种"
        )
        lines.append(
            f"好友：{friends.friend_count(ctx, target_id)} 位"
            f" · 挂出的伙伴：{len(borrow.lent(ctx, target_id))} 只"
        )
    if level == PUBLIC:
        lines.append("陌生修士只显示榜单公开的信息；结为好友后可看到更多。")
        links.append(InlineCommand(0, "加为好友", f"灵宠好友 添加 {target.uid}"))
    elif level == FRIEND:
        lines.append("好友可互借伙伴：在灵宠借力里借用对方挂出的伙伴，加成自己的出战伙伴。")
        links.append(InlineCommand(len(lines) - 1, "去借力", "灵宠借力"))
    else:
        lines.append("名帖只公开榜单与他人可见的部分；账户私密数据只在 我的信息 里。")
        links.append(InlineCommand(0, "我的信息", "我的信息"))
    commands = [TITLE, "我的信息", "灵宠好友"]
    return Reply(TITLE, tuple(lines), tuple(commands)[:4], tuple(links))


def dispatch(ctx: Context, arg: str) -> Reply:
    return card(ctx, arg)


__all__ = ["FRIEND", "PUBLIC", "SELF", "TITLE", "card", "dispatch", "relation"]
