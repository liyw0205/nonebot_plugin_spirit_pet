from dataclasses import dataclass
from sqlite3 import Row

from ...application.context import Context
from ...domain.arena_content import ArenaRules
from ...domain.models import GameError
from ...utils.time import beijing_day, parse_season_id, season_bounds


@dataclass(frozen=True)
class Season:
    season_id: str
    starts_at: int
    ends_at: int
    closed_at: int | None
    rules: ArenaRules


def _season(row: Row) -> Season:
    return Season(row["season_id"], row["starts_at"], row["ends_at"], row["closed_at"],
                  ArenaRules.model_validate_json(row["rules_snapshot"]))


def current_season(ctx: Context) -> Season:
    conn = ctx.repo.conn
    latest = conn.execute("SELECT MAX(observed_at) FROM seasons").fetchone()[0]
    if latest is not None and ctx.now < latest:
        raise GameError("服务器时间早于已记录的赛季时间，请等待时钟恢复后再试。")
    season_id, starts_at, ends_at = season_bounds(ctx.now)
    conn.execute(
        "UPDATE seasons SET closed_at=? WHERE ends_at<=? AND closed_at IS NULL", (ctx.now, ctx.now),
    )
    conn.execute(
        "INSERT INTO seasons(season_id, starts_at, ends_at, observed_at, rules_snapshot) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(season_id) DO UPDATE SET observed_at=excluded.observed_at",
        (season_id, starts_at, ends_at, ctx.now, ctx.content.arena.model_dump_json()),
    )
    return _season(conn.execute("SELECT * FROM seasons WHERE season_id=?", (season_id,)).fetchone())


def load_season(ctx: Context, season_id: str) -> Season:
    try:
        parse_season_id(season_id)
    except ValueError:
        raise GameError("赛季格式应为 YYYY-MM，例如 2028-01。") from None
    row = ctx.repo.conn.execute("SELECT * FROM seasons WHERE season_id=?", (season_id,)).fetchone()
    if row is None:
        raise GameError("未找到该赛季记录；尚未发生的赛季和未开放月份不能查询。")
    return _season(row)


def rating(ctx: Context, season: Season, user_id: str) -> int:
    row = ctx.repo.conn.execute(
        "SELECT rating FROM season_entries WHERE season_id=? AND user_id=?", (season.season_id, user_id),
    ).fetchone()
    return row["rating"] if row else season.rules.initial_rating


def stats(ctx: Context, season: Season, user_id: str) -> dict[str, int]:
    entry = ctx.repo.conn.execute(
        "SELECT rating, wins, losses, draws FROM season_entries WHERE season_id=? AND user_id=?",
        (season.season_id, user_id),
    ).fetchone()
    totals = ctx.repo.conn.execute(
        "SELECT COUNT(CASE WHEN day=? THEN 1 END) AS today_matches, "
        "COUNT(CASE WHEN winner_id IS NOT NULL THEN 1 END) AS qualifying_matches, "
        "COUNT(DISTINCT CASE WHEN winner_id IS NOT NULL THEN target_id END) AS opponents "
        "FROM pvp_results WHERE season_id=? AND challenger_id=?",
        (beijing_day(ctx.now), season.season_id, user_id),
    ).fetchone()
    return {**(dict(entry) if entry else {"rating": season.rules.initial_rating, "wins": 0, "losses": 0, "draws": 0}),
            **dict(totals)}
