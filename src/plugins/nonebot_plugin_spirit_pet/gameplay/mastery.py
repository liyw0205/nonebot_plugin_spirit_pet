from ..application.context import Context


def progress(ctx: Context, pet_id: int) -> dict[str, tuple[int, int]]:
    return {
        row["skill_id"]: (row["level"], row["proficiency"])
        for row in ctx.repo.conn.execute(
            "SELECT skill_id, level, proficiency FROM learned_skills WHERE pet_id=? ORDER BY skill_id",
            (pet_id,),
        )
    }


def progress_text(ctx: Context, level: int, proficiency: int) -> str:
    required = ctx.content.skill_levels[level].required_proficiency
    detail = "熟练度已满" if required is None else f"熟练度 {proficiency}/{required}"
    return f"{level}级 · {detail}"


def award_mastery(
    ctx: Context, user_id: str, uses: dict[str, int], *, pet_id: int,
) -> tuple[str, ...]:
    if any(type(count) is not int or count < 0 for count in uses.values()):
        raise ValueError("skill use counts must be nonnegative integers")
    if not any(uses.values()):
        return ()
    pet = ctx.repo.pet(pet_id)
    if pet.user_id != user_id:
        raise ValueError("mastery pet must belong to the participant")
    rows = ctx.repo.conn.execute(
        "SELECT skill_id, level, proficiency FROM learned_skills "
        "WHERE pet_id=? AND equipped=1 ORDER BY skill_id", (pet.pet_id,),
    ).fetchall()
    lines = []
    upgraded = False
    for row in rows:
        skill_id = row["skill_id"]
        count = uses.get(skill_id, 0)
        level, proficiency = row["level"], row["proficiency"]
        if not count or ctx.content.skill_levels[level].required_proficiency is None:
            continue
        gained = count * ctx.content.rules.skill_proficiency_per_use
        proficiency += gained
        while (required := ctx.content.skill_levels[level].required_proficiency) is not None:
            if proficiency < required:
                break
            proficiency -= required
            level += 1
            upgraded = True
        if ctx.content.skill_levels[level].required_proficiency is None:
            gained -= proficiency
            proficiency = 0
        ctx.repo.conn.execute(
            "UPDATE learned_skills SET level=?, proficiency=? WHERE pet_id=? AND skill_id=?",
            (level, proficiency, pet.pet_id, skill_id),
        )
        skill = ctx.content.skills[skill_id]
        suffix = "，领悟精进" if level > row["level"] else ""
        lines.append(
            f"{ctx.player(user_id).dao_name}的{pet.name}：{skill.name}熟练度 +{gained}{suffix}；"
            f"{progress_text(ctx, level, proficiency)}。"
        )
    if upgraded:
        ctx.repo.invalidate_ready(user_id)
    return tuple(lines)
