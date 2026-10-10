import re

from ..application.context import Context
from ..domain.models import GameError, InlineCommand, Reply


PET_NAME_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{1,12}")


def _owned_pet(ctx: Context, pet_id: int):
    pet = ctx.repo.conn.execute(
        "SELECT pet_id FROM pets WHERE user_id=? AND pet_id=?",
        (ctx.user_id, pet_id),
    ).fetchone()
    if pet is None:
        raise GameError("没有属于你的这只灵宠，请先查看灵宠列表中的编号。")
    return ctx.repo.pet(pet_id)


def _prompt(ctx: Context) -> Reply:
    active = ctx.repo.active_pets(ctx.user_id)
    if not active:
        return Reply(
            "灵宠命名",
            ("当前没有出战伙伴。先查看灵宠名册，再用‘灵宠命名 编号 新名字’为任意伙伴取名。",),
            ("灵宠列表",),
            (InlineCommand(0, "查看灵宠名册", "灵宠列表"),),
        )
    pet = active[0]
    return Reply(
        "灵宠命名",
        (f"当前出战伙伴：{pet.name}（编号 {pet.pet_id}）。", "填写新名字即可，也可写成‘灵宠命名 编号 新名字’。"),
        ("灵宠列表",),
        (InlineCommand(0, "填写新名字", f"灵宠命名 {pet.pet_id} "),),
    )


def rename_pet(ctx: Context, arg: str) -> Reply:
    ctx.player()
    if not arg:
        return _prompt(ctx)

    parts = arg.split()
    target = None
    if parts[0].isdigit():
        if len(parts) != 2:
            raise GameError("格式：灵宠命名 编号 新名字。")
        pet_id = int(parts[0])
        name = parts[1]
        target = _owned_pet(ctx, pet_id)
    else:
        if len(parts) != 1:
            raise GameError("格式：灵宠命名 编号 新名字；当前出战伙伴可直接填写新名字。")
        active = ctx.repo.active_pets(ctx.user_id)
        if not active:
            guidance = _prompt(ctx)
            raise GameError(guidance.lines[0], reply=guidance)
        target = active[0]
        name = parts[0]

    if PET_NAME_PATTERN.fullmatch(name) is None:
        raise GameError("灵宠名字限 1-12 个汉字、英文字母或数字，不能含空格。")
    if target.name == name:
        raise GameError("新名字与当前名字相同。")
    old_name = target.name
    target.name = name
    status_command = "我的灵宠" if not target.archived else "灵宠封存库"
    return Reply(
        "灵宠新名",
        (f"编号 {target.pet_id}：{old_name}已改名为{name}。", "成长、装备和灵术记录均已保留。"),
        (status_command, "灵宠列表"),
    )
