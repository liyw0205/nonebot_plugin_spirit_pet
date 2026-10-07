from ...application.context import Context
from ...domain.models import GameError
from ..combat import Battle
from .common import Season, rating


def settle_ranked(ctx: Context, season: Season, target_id: str, battle: Battle) -> tuple[int, tuple[str, ...]]:
    if target_id == ctx.user_id:
        raise GameError("不能向自己发起论剑。")
    if season.closed_at is not None or not season.starts_at <= ctx.now < season.ends_at:
        raise GameError("赛季已经结束或尚未开始，不能计分。")
    if battle.winner not in (-1, 0, 1):
        raise ValueError("ranked battle winner must be -1, 0 or 1")
    conn = ctx.repo.conn
    if conn.execute("SELECT 1 FROM pvp_results WHERE operation_id=?", (ctx.operation_id,)).fetchone():
        raise GameError("这场论剑已经计分，不能重复结算。")
    participants = (ctx.user_id, target_id)
    scores = [rating(ctx, season, user_id) for user_id in participants]
    winner_id = None if battle.winner == -1 else participants[battle.winner]
    delta = 0 if winner_id is None else min(season.rules.rating_delta, scores[1 - battle.winner])
    lines = []
    for side, user_id in enumerate(participants):
        won = int(battle.winner == side)
        lost = int(battle.winner != -1 and not won)
        drawn = int(battle.winner == -1)
        adjustment = delta * (won - lost)
        conn.execute(
            "INSERT INTO season_entries(season_id, user_id, rating, wins, losses, draws) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(season_id, user_id) DO UPDATE SET "
            "rating=excluded.rating, wins=season_entries.wins+excluded.wins, "
            "losses=season_entries.losses+excluded.losses, draws=season_entries.draws+excluded.draws",
            (season.season_id, user_id, scores[side] + adjustment, won, lost, drawn),
        )
        result = "平局" if drawn else "胜" if won else "负"
        lines.append(f"{ctx.player(user_id).dao_name}：{result}，赛季积分 {adjustment:+d}，"
                     f"现为 {scores[side] + adjustment}。")
    return delta, tuple(lines)
