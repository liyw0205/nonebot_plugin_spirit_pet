"""Merchant standing progression: content validation, trade counting, perks, claim."""

import itertools
import json
import shutil

import pytest

from nonebot_plugin_spirit_pet.application.context import Context
from nonebot_plugin_spirit_pet.content.catalog import DATA_DIR, Catalog
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay import market_standing
from nonebot_plugin_spirit_pet.storage.repository import Repository

from .support import sql

NOW = 1_800_000_000
DAY = 86400

_ops = itertools.count()


def ctx_of(game, user="u1", now=NOW) -> Context:
    """A read-only Context over the same database the ``play`` fixture writes."""
    return Context(
        Repository(game[1].connect()),
        game[0].content,
        game[0].config,
        game[0].rng,
        user,
        now,
        f"probe-{user}",
    )


def account(game, play, user="u1", species="青鸾", stones=100_000):
    if not sql(game[1], "SELECT user_id FROM players WHERE user_id=?", (user,)):
        play("adopt", species, user=user, op=f"adopt-{user}-{next(_ops)}")
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (stones, user))


def grant(game, mapping, user="u1"):
    for item_id, amount in mapping.items():
        sql(
            game[1],
            "INSERT INTO inventory VALUES (?, ?, ?) ON CONFLICT(user_id, item_id)"
            " DO UPDATE SET quantity=quantity+excluded.quantity",
            (user, item_id, amount),
        )


def set_stones(game, value, user="u1"):
    sql(game[1], "UPDATE players SET stones=? WHERE user_id=?", (value, user))


def sell(game, play, user="u1", item="forge_ore", amount=5, price=90, op=None):
    """``user`` lists and a funded ``u2`` buys.

    Without ``op`` every call gets a fresh operation id; with ``op`` both steps
    reuse one deterministic id pair, so calling twice with the same ``op``
    exercises the real replay path instead of creating a second sale.
    """
    account(game, play, user="u2", species="玄狐")
    account(game, play, user=user)
    grant(game, {item: amount}, user=user)
    tag = op or "sell"
    suffix = "" if op else f"-{next(_ops)}"
    play("market", f"上架 {item} {amount} {price}", user=user, op=f"{tag}-list{suffix}")
    rows = sql(game[1], "SELECT listing_id FROM market_listings ORDER BY listing_id DESC LIMIT 1")
    listing_id = rows[0]["listing_id"]
    set_stones(game, 100_000, user="u2")
    play("market", f"购买 {listing_id}", user="u2", op=f"{tag}-buy{suffix}")
    return listing_id


# ----------------------------------------------------------------- D1/D2: content validation


@pytest.fixture
def content_dir(tmp_path):
    target = tmp_path / "content"
    shutil.copytree(DATA_DIR, target)
    return target


def edit_standings(content_dir, change):
    path = content_dir / "merchant_standings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_content_5_standings_loaded(content_dir):
    c = Catalog.load(content_dir)
    assert len(c.merchant_standings) >= 5


def test_content_standings_first_threshold_at_least_one(content_dir):
    """The shipped first standing must have min_trades >= 1."""
    c = Catalog.load(content_dir)
    ordered = sorted(c.merchant_standings.values(), key=lambda e: e.min_trades)
    assert ordered[0].min_trades >= 1


def test_content_standings_thresholds_strictly_increase(content_dir):
    """Editing a threshold equal to the previous one must fail."""

    def flatten_last(data):
        data[-1]["min_trades"] = data[-2]["min_trades"]

    edit_standings(content_dir, flatten_last)
    with pytest.raises(ValueError, match="strictly increase"):
        Catalog.load(content_dir)


def test_content_standings_empty_is_rejected(content_dir):
    edit_standings(content_dir, lambda data: data.clear())
    with pytest.raises(ValueError, match="empty or duplicate"):
        Catalog.load(content_dir)


def test_content_standings_repeated_unique_slot_perks_rejected(content_dir):
    """bid_slot or listing_slot appearing twice must fail."""

    def mutate(data):
        data[0].update({"perk": "bid_slot", "perk_text": "first"})
        data[1].update({"perk": "bid_slot", "perk_text": "dup"})

    edit_standings(content_dir, mutate)
    with pytest.raises(ValueError, match="must not repeat"):
        Catalog.load(content_dir)


def test_content_standings_stacked_tax_rebate_ok(content_dir):
    """Two tax_rebate entries are allowed and summed."""
    c = Catalog.load(content_dir)
    rebate_entries = [s for s in c.merchant_standings.values() if s.perk == "tax_rebate"]
    assert len(rebate_entries) >= 2
    assert sum(entry.rebate for entry in rebate_entries) > 1


def test_content_standings_reward_is_essential(content_dir):
    """A standing with zero stones and no items fails."""

    def zero_reward(data):
        data[0].update({
            "reward": {
                "exp": {"minimum": 0, "maximum": 0},
                "stones": {"minimum": 0, "maximum": 0},
                "items": {},
            },
        })

    edit_standings(content_dir, zero_reward)
    with pytest.raises(ValueError, match="needs a milestone reward"):
        Catalog.load(content_dir)


# ---------------------------------------------------------------- D3: derived progress


def test_zero_trades_when_empty(game, play):
    account(game, play)
    assert market_standing.trades(ctx_of(game), "u1") == 0


def test_single_direct_sale_counts_one_trade(game, play):
    account(game, play)
    sell(game, play, user="u1")
    assert market_standing.trades(ctx_of(game), "u1") == 1


def test_two_direct_sales_count_two_trades(game, play):
    account(game, play)
    sell(game, play, user="u1", item="forge_ore")
    sell(game, play, user="u1", item="spirit_food")
    assert market_standing.trades(ctx_of(game), "u1") == 2


def test_bid_sale_counts_as_trade(game, play):
    """Filling a buy order as the seller counts toward standing."""
    account(game, play, user="u1")
    account(game, play, user="u2", species="玄狐")
    grant(game, {"forge_ore": 5}, user="u2")
    play("market", "求购 forge_ore 3 100", user="u1", op="place-bid")
    play("market", "应单 1", user="u2", op="fill-bid")
    assert market_standing.trades(ctx_of(game), "u2") == 1


def test_cancelled_listing_does_not_count(game, play):
    account(game, play)
    grant(game, {"forge_ore": 5})
    play("market", "上架 forge_ore 5 90", op="cancel-list")
    listing_id = sql(
        game[1], "SELECT listing_id FROM market_listings ORDER BY listing_id DESC LIMIT 1",
    )[0]["listing_id"]
    play("market", f"下架 {listing_id}", op="cancel")
    assert market_standing.trades(ctx_of(game), "u1") == 0


def test_expired_listing_does_not_count(game, play):
    account(game, play)
    grant(game, {"forge_ore": 5})
    play("market", "上架 forge_ore 5 90", op="expire-list")
    # browsing the market settles the overdue escrow back to the seller
    play("market", user="u1", now=NOW + 4 * DAY, op="expire-sweep")
    assert market_standing.trades(ctx_of(game), "u1") == 0


def test_replay_does_not_double_count(game, play):
    account(game, play)
    sell(game, play, user="u1", op="replay")
    before = market_standing.trades(ctx_of(game), "u1")
    sell(game, play, user="u1", op="replay")
    assert market_standing.trades(ctx_of(game), "u1") == before


# ---------------------------------------------------------------- D4: perk effective values


def test_listing_slot_perk_adds_one_slot(game, play):
    account(game, play)
    # upgrade to the top stall so the base slot count is the largest shipped
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed)"
        " VALUES ('u1', 'market_stall', 4, 1)",
    )
    base_slots = game[0].content.market.stalls[3].slots
    for _ in range(30):  # 老字号掌柜 unlocks its listing slot at 30 trades
        sell(game, play, user="u1")
    assert market_standing.listing_slots(ctx_of(game), "u1") == base_slots + 1


def test_listing_gate_uses_effective_slots(game, play):
    """The perk really widens the gate, not just the reported number."""
    account(game, play)
    sql(
        game[1],
        "INSERT INTO quest_progress(user_id, quest_id, progress, claimed)"
        " VALUES ('u1', 'market_stall', 4, 1)",
    )
    for _ in range(30):
        sell(game, play, user="u1")
    grant(game, {"forge_ore": 50})
    slots = market_standing.listing_slots(ctx_of(game), "u1")
    for index in range(slots):  # base + perk listings all fit
        play("market", "上架 forge_ore 5 90", op=f"gate-{index}")
    with pytest.raises(GameError, match="陈列位已满"):
        play("market", "上架 forge_ore 5 90", op="gate-over")


def test_bid_slot_perk_adds_one_slot(game, play):
    account(game, play)
    for _ in range(10):
        sell(game, play, user="u1")
    assert market_standing.bid_slots(ctx_of(game), "u1") == game[0].content.market.bid_slots + 1


def test_tax_rebate_reduces_fee(game, play):
    account(game, play)
    for _ in range(60):
        sell(game, play, user="u1")
    assert market_standing.fee_percent(ctx_of(game), "u1") == 9


def test_full_stacked_rebate(game, play):
    account(game, play)
    for _ in range(100):
        sell(game, play, user="u1")
    assert market_standing.fee_percent(ctx_of(game), "u1") == 8


def test_current_standing_tracks_trades(game, play):
    account(game, play)
    assert market_standing.current(ctx_of(game), "u1") is None
    sell(game, play, user="u1")
    current = market_standing.current(ctx_of(game), "u1")
    assert current is not None and current.id == "standing_apprentice"
    for _ in range(9):
        sell(game, play, user="u1")
    assert market_standing.current(ctx_of(game), "u1").id == "standing_trader"


# ---------------------------------------------------------------- D5: claim


def test_claim_grant_and_idempotent_replay(game, play):
    account(game, play)
    sell(game, play, user="u1")
    reply = play("market", "掌柜领奖 学徒掌柜")
    assert reply.title == "掌柜领奖"
    assert "灵石 +100" in reply.text()
    with pytest.raises(GameError, match="已经领取"):
        play("market", "掌柜领奖 学徒掌柜")


def test_claim_below_threshold_refuses(game, play):
    account(game, play)
    with pytest.raises(GameError, match="需要"):
        play("market", "掌柜领奖 学徒掌柜")


def test_claim_unknown_standing_refuses(game, play):
    account(game, play)
    with pytest.raises(GameError, match="未找到品阶"):
        play("market", "掌柜领奖 不存在的品阶")


def test_hub_shows_current_and_next(game, play):
    account(game, play)
    hub = play("market", "掌柜")
    assert "累计成交" in hub.text()
    assert "下一品" in hub.text()


def test_hub_shows_claimable_link(game, play):
    account(game, play)
    sell(game, play, user="u1")
    assert "可领" in play("market", "掌柜").text()


def test_history_empty_then_after_claim(game, play):
    account(game, play)
    assert "尚未领取" in play("market", "掌柜记录").text()
    sell(game, play, user="u1")
    play("market", "掌柜领奖 学徒掌柜")
    assert "学徒掌柜" in play("market", "掌柜记录").text()


# ---------------------------------------------------------------- D6: objective_line


def test_objective_line_shows_trades(game, play):
    account(game, play)
    assert "0 笔" in market_standing.objective_line(ctx_of(game), "u1")
    sell(game, play, user="u1")
    assert "1 笔" in market_standing.objective_line(ctx_of(game), "u1")


def test_unregistered_player_reads_preview(game, play):
    reply = play("market", "掌柜", user="u9")
    assert "尚未结契" in reply.text()
