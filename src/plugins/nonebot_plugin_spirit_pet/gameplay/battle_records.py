"""Immutable battle snapshots and the player-facing battle report view.

The combat engine intentionally remains unaware of storage.  Callers capture
the loadout before ``fight`` mutates fighters, then persist the result after
settlement in the same transaction.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from ..application.context import Context
from ..domain.models import GameError, Reply
from ..gameplay.combat import Battle, Fighter
from ..gameplay.equipment import loadout
from ..gameplay.mastery import progress
from ..utils.arguments import quantity
from ..utils.time import BEIJING

REPORT_PAGE_SIZE = 5
DETAIL_PAGE_SIZE = 8
_KIND_NAMES = {"pvp": "论剑", "spar": "切磋", "pve": "秘境", "pve_stage": "关卡"}


@dataclass(frozen=True)
class BattleCapture:
    snapshot: dict
    participants: tuple[dict, ...]


def _skill_snapshot(ctx: Context, pet_id: int, fighter: Fighter) -> list[dict]:
    mastery = progress(ctx, pet_id)
    return [
        {
            "id": skill.id,
            "name": skill.name,
            "level": mastery.get(skill.id, (1, 0))[0],
            "proficiency": mastery.get(skill.id, (1, 0))[1],
        }
        for skill in fighter.skills
    ]


def _fighter_snapshot(ctx: Context, fighter: Fighter, user_id: str | None) -> dict:
    primary = ctx.content.elements.get(fighter.primary_element) if fighter.primary_element else None
    member = {
        "dao_name": ctx.player(user_id).dao_name if user_id else None,
        "pet_name": fighter.name.rsplit("的", 1)[-1] if "的" in fighter.name else fighter.name,
        "species_id": None,
        "realm": None,
        "realm_name": None,
        "layer": None,
        "bloodline": None,
        "bloodline_name": None,
        "lineage_id": None,
        "elements": [],
        "primary_element": fighter.primary_element,
        "primary_element_name": primary.name if primary else fighter.primary_element,
        "stats": fighter.stats.model_dump(),
        "skills": [],
        "equipment": [],
        "resonance": fighter.resonance_name,
    }
    if fighter.pet_id is None:
        return member
    pet = ctx.repo.pet(fighter.pet_id)
    member["pet_name"] = pet.name
    member["species_id"] = pet.species_id
    species = ctx.content.species[pet.species_id]
    member["realm"] = pet.realm
    member["realm_name"] = ctx.content.realms[pet.realm].name
    member["layer"] = pet.layer
    member["bloodline"] = pet.bloodline
    member["bloodline_name"] = ctx.content.bloodlines[pet.bloodline].name
    member["lineage_id"] = pet.lineage_id
    member["elements"] = [
        {"id": element_id, "name": ctx.content.elements[element_id].name}
        for element_id in species.elements
    ]
    member["skills"] = _skill_snapshot(ctx, pet.pet_id, fighter)
    for slot, (item_id, enhancement) in loadout(ctx, pet.pet_id).items():
        item = ctx.content.items.get(item_id)
        member["equipment"].append({
            "slot": slot,
            "item_id": item_id,
            "name": item.name if item else item_id,
            "enhancement": enhancement,
        })
    return member


def capture_snapshot(
    ctx: Context,
    teams: tuple[list[Fighter], list[Fighter]],
    user_ids_by_side: tuple[list[str], list[str]],
) -> BattleCapture:
    """Capture all user-visible combatant state before combat starts."""
    groups = []
    participants = []
    for side, (team, user_ids) in enumerate(zip(teams, user_ids_by_side)):
        members = []
        for index, fighter in enumerate(team):
            user_id = user_ids[index] if index < len(user_ids) else None
            members.append(_fighter_snapshot(ctx, fighter, user_id))
            if user_id is not None:
                participants.append({
                    "user_id": user_id,
                    "side": side,
                    "permission": "defender" if side == 1 else "participant",
                })
        groups.append({"side": side, "members": members})
    return BattleCapture({"version": 1, "teams": groups}, tuple(participants))


def record_battle(
    ctx: Context,
    *,
    kind: str,
    battle: Battle,
    capture: BattleCapture,
    reply: Reply,
    battle_key: str = "",
    battle_name: str = "",
) -> int:
    """Persist an immutable result and return its numeric report ID."""
    if kind not in _KIND_NAMES:
        raise ValueError(f"unknown battle kind: {kind}")
    if type(battle.winner) is not int or battle.winner not in (-1, 0, 1):
        raise ValueError("invalid battle winner side")
    snapshot = dict(capture.snapshot)
    snapshot["version"] = 2
    if battle_name:
        snapshot["scenario"] = {"id": battle_key, "name": battle_name}
    return ctx.repo.record_battle(
        operation_id=ctx.operation_id,
        initiator_id=ctx.user_id,
        kind=kind,
        battle_key=battle_key,
        title=reply.title,
        winner_side=battle.winner,
        rounds=battle.rounds,
        played_at=ctx.now,
        reply=asdict(reply),
        snapshot=snapshot,
        battle_log=battle.history or battle.lines,
        participants=list(capture.participants),
    )


def _outcome(row, side: int) -> str:
    if row["winner_side"] == -1:
        return "平局"
    return "胜利" if row["winner_side"] == side else "败北"


def _member_text(member: dict) -> str:
    dao = member.get("dao_name") or "秘境敌手"
    element = member.get("primary_element_name") or member.get("primary_element") or "未知"
    skills = "、".join(
        f"{item['name']} {item['level']}级/{item['proficiency']}熟练度"
        for item in member.get("skills", [])
    ) or "无"
    equipment = "、".join(
        f"{item['name']} +{item['enhancement']}" for item in member.get("equipment", [])
    ) or "无"
    realm = member.get("realm_name")
    realm_text = f" · {realm}{member.get('layer')}层 · {member.get('bloodline_name')}" if realm else ""
    resonance = f" · 共鸣 {member['resonance']}" if member.get("resonance") else ""
    return (f"{dao}的{member.get('pet_name', '未知灵宠')}{realm_text}{resonance} · 主属性 {element} · "
            f"技能 {skills} · 装备 {equipment}")


def _detail(ctx: Context, battle_id: int, page: int = 1) -> Reply:
    row = ctx.repo.battle_report(ctx.user_id, battle_id)
    if row is None:
        raise GameError("战报不存在，或你不是该场战斗的参与者。")
    snapshot = json.loads(row["snapshot"])
    log = json.loads(row["battle_log"])
    summary = [
        f"战报 #{row['battle_id']} · {_KIND_NAMES.get(row['kind'], row['kind'])} · {row['title']}",
        f"结果：{_outcome(row, row['side'])} · {row['rounds']} 回合 · "
        f"{datetime.fromtimestamp(row['played_at'], BEIJING).strftime('%Y-%m-%d %H:%M:%S')}（北京时间）",
    ]
    scenario = snapshot.get("scenario")
    scenario_name = scenario.get("name") if isinstance(scenario, dict) else None
    if isinstance(scenario_name, str) and scenario_name:
        summary.append(f"场景：{scenario_name}")
    for team in snapshot.get("teams", []):
        label = "我方" if team["side"] == row["side"] else "对方"
        summary.extend(f"{label} · {_member_text(member)}" for member in team.get("members", []))
    pages = max(1, (len(log) + DETAIL_PAGE_SIZE - 1) // DETAIL_PAGE_SIZE)
    if page > pages:
        raise GameError(f"该战报共 {pages} 页。")
    commands = ["灵宠战报"]
    if page > 1:
        commands.append(f"灵宠战报 详情 {battle_id} {page - 1}")
    if page < pages:
        commands.append(f"灵宠战报 详情 {battle_id} {page + 1}")
    return Reply(
        f"战报 #{row['battle_id']} {page}/{pages}",
        (*summary, "战斗记录：", *log[(page - 1) * DETAIL_PAGE_SIZE:page * DETAIL_PAGE_SIZE]),
        tuple(commands),
    )


def reports(ctx: Context, arg: str) -> Reply:
    """List reports or display a report detail after participant authorization."""
    ctx.player()
    parts = arg.split()
    if parts and parts[0] in {"查看", "详情"}:
        if len(parts) not in (2, 3) or not parts[1].isdecimal():
            raise GameError("格式：灵宠战报 查看 编号 [分页]。")
        page = quantity(parts[2], 999999) if len(parts) == 3 else 1
        return _detail(ctx, int(parts[1]), page)
    if len(parts) == 1 and parts[0].isdecimal():
        page = quantity(parts[0], 999999)
    elif len(parts) == 2 and parts[0] == "分页":
        page = quantity(parts[1], 999999)
    elif parts:
        raise GameError("格式：灵宠战报 [分页 N] 或 灵宠战报 查看 编号。")
    else:
        page = 1
    total = ctx.repo.battle_history_count(ctx.user_id)
    pages = max(1, (total + REPORT_PAGE_SIZE - 1) // REPORT_PAGE_SIZE)
    if page > pages:
        raise GameError(f"战报共 {pages} 页。")
    rows = ctx.repo.battle_history(
        ctx.user_id, limit=REPORT_PAGE_SIZE, offset=(page - 1) * REPORT_PAGE_SIZE,
    )
    lines = []
    for row in rows:
        snapshot = json.loads(row["snapshot"])
        own = snapshot.get("teams", [])[row["side"]].get("members", []) if snapshot.get("teams") else []
        names = "、".join(member.get("pet_name", "未知灵宠") for member in own)
        scenario = snapshot.get("scenario")
        scenario_name = scenario.get("name") if isinstance(scenario, dict) else None
        context = f" · {scenario_name}" if isinstance(scenario_name, str) and scenario_name else ""
        lines.append(
            f"#{row['battle_id']} {_KIND_NAMES.get(row['kind'], row['kind'])}{context} · {row['title']} · "
            f"{_outcome(row, row['side'])} · {row['rounds']}回合 · {names}"
        )
    commands = [f"灵宠战报 查看 {row['battle_id']}" for row in rows]
    if page > 1:
        commands.append(f"灵宠战报 分页 {page - 1}")
    if page < pages:
        commands.append(f"灵宠战报 分页 {page + 1}")
    return Reply(f"灵宠战报 {page}/{pages}", tuple(lines) or ("尚无参与过的战斗。",), tuple(commands))


# Short aliases for integrations that prefer a verb matching their domain.
capture = capture_snapshot
history = reports
