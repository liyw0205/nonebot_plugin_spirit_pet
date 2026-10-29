"""Connectivity contracts: docs, aliases, links and data counts stay wired.

Written as an audit after a run of fixes (a page link that opened a system it did
not label, credentials shared between independent rewards, replies claiming a
reward the player never received). These do not test gameplay; they test that
players can still *reach* everything the project documents, so a later content or
command edit cannot silently orphan an entry point.

Pages that legitimately refuse without a pet, team or argument are skipped, but
each contract asserts a floor on how much surface it reached, so the audit cannot
quietly degrade into passing on nothing.
"""

import json
import re
from pathlib import Path

import pytest

from nonebot_plugin_spirit_pet.adapters import handlers
from nonebot_plugin_spirit_pet.application.commands import ACTIONS, COMMANDS
from nonebot_plugin_spirit_pet.content.catalog import Catalog
from nonebot_plugin_spirit_pet.gameplay import battle_pass
from nonebot_plugin_spirit_pet.gameplay.help import _HELP_SECTIONS

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "src" / "plugins" / "nonebot_plugin_spirit_pet"
DATA = PLUGIN / "data"
GAMEPLAY = ROOT / "docs" / "GAMEPLAY.md"

# Read-only pages a freshly adopted player can render.
READ_ONLY_PAGES = (
    "achievements", "adventure_codex", "adventure_collection_rewards", "adventure_rank",
    "arcs", "ascension", "daily_shop",
    "arena_reward_history", "arena_tier_rewards", "battle_merits", "battle_pass",
    "battle_pass_history", "bag", "bloodline_milestone_rewards", "bond_levels",
    "bond_rewards", "breeding", "catalog", "cave", "checkin_calendar", "checkin_rewards",
    "codex", "codex_trials", "collection", "collection_rank", "corridor", "cuisine", "daily_assignment", "daily_dungeon",
    "defense", "dungeon_stats", "dungeons", "echoes", "equipment", "equipment_catalog",
    "equipment_sets", "expedition_catalog", "expedition_history", "expedition_status",
    "farm", "first_clear", "forbidden", "free_summon", "identity", "journey", "lineage_catalog",
    "lineage_awakening_rewards", "main_quests", "objectives", "pet_archive_list",
    "pet_list", "pet_outing", "pet_outing_board", "play_game", "pvp_rank", "quests",
    "rank", "rank_rewards", "realm_milestone_rewards", "recipe_catalog", "reforge",
    "resonance", "season", "season_missions", "season_rewards", "season_road", "shop",
    "skill_catalog", "skill_mastery_rewards", "skill_overview", "skills",
    "sect", "stage_catalog", "stage_stars", "stage_stats", "status", "survival", "talent_history", "temper",
    "team_trial", "titles", "tower_catalog", "weekly_quests", "world_boss",
    "affinity_milestone_rewards",
)

# Aliases that intentionally reuse another entry's documentation.
SHARED_HELP_ENTRIES = {
    "我的宠", "灵宠", "灵宠帮助", "灵宠阵容", "灵宠图鉴克制", "灵宠图鉴掉落",
    "灵宠论剑战绩",
}

DOCUMENTED_COUNTS = {
    "achievements": 77, "titles": 25, "dungeons": 20, "stages": 16, "tower": 16,
    "adventures": 21, "expeditions": 21, "pets": 27, "lineages": 54, "skills": 24,
    "resonances": 21, "weekly_quests": 12, "daily_assignments": 12,
    "season_missions": 10, "journey": 16, "main_quests": 16, "crops": 8,
    "equipment": 14, "equipment_sets": 4, "enemies": 23, "shop_rotation": 9,
    "forbidden": 3, "cuisine": 6, "team_trials": 3, "cave": 3, "corridor": 1, "sects": 4, "codex_trials": 1, "survival": 1, "arcs": 3,
}


def documented_heads():
    heads = set()
    for span in re.findall(r"`([^`\n]+)`", GAMEPLAY.read_text()):
        span = span.strip()
        if span.startswith(("灵宠", "我的")):
            heads.add(span.split()[0])
    return heads


def test_every_chat_alias_resolves_to_a_registered_action():
    assert len(COMMANDS) > 180, "the chat alias table moved or shrank unexpectedly"
    unknown = sorted({action for action in COMMANDS.values() if action not in ACTIONS})
    assert not unknown, f"chat aliases point at unregistered actions: {unknown}"


def test_every_chat_alias_is_documented_in_help():
    heads = {row[0].split()[0] for section in _HELP_SECTIONS.values() for row in section}
    missing = sorted(
        name for name in COMMANDS if name not in heads and name not in SHARED_HELP_ENTRIES
    )
    assert not missing, f"chat commands missing from 灵宠帮助: {missing}"


def test_every_documented_command_family_is_reachable():
    heads = documented_heads()
    assert len(heads) > 130, "the documented command surface moved or shrank unexpectedly"
    unreachable = sorted(head for head in heads if handlers._parse(head) is None)
    assert not unreachable, f"documented commands the parser cannot resolve: {unreachable}"


def test_every_link_on_a_rendered_page_opens_a_registered_action(game, play):
    play("adopt", "青鸾")
    problems = []
    rendered, checked = 0, 0
    for action in READ_ONLY_PAGES:
        try:
            page = play(action, op=f"contract-{action}")
        except Exception:  # noqa: BLE001 - pages may legitimately refuse without state
            continue
        rendered += 1
        for link in page.inline_commands:
            checked += 1
            parsed = handlers._parse(link.command)
            if parsed is None:
                problems.append(f"{action}: unparsable link {link.command!r}")
                continue
            if parsed[0] not in ACTIONS:
                problems.append(f"{action}: link {link.command!r} -> unknown action {parsed[0]}")
            if link.line >= len(page.lines):
                problems.append(f"{action}: link {link.command!r} points past the page")
    assert rendered >= 50, f"only {rendered} pages rendered; the audit lost coverage"
    assert checked >= 80, f"only {checked} links reached; the audit lost coverage"
    assert not problems, "\n".join(problems)


def test_documented_content_counts_match_the_data_files():
    actual = {
        name: len(json.loads((DATA / f"{name}.json").read_text()))
        for name in DOCUMENTED_COUNTS
    }
    drifted = {
        name: {"docs": DOCUMENTED_COUNTS[name], "data": actual[name]}
        for name in DOCUMENTED_COUNTS
        if DOCUMENTED_COUNTS[name] != actual[name]
    }
    assert not drifted, f"documented counts drifted from the content: {drifted}"


def copy_content(tmp_path):
    """A mutable copy of the shipped content so validation can be exercised."""
    for source in DATA.glob("*.json"):
        (tmp_path / source.name).write_text(source.read_text())
    return tmp_path


def test_catalog_accepts_the_shipped_content():
    catalog = Catalog.load(DATA)
    assert len(catalog.titles) == DOCUMENTED_COUNTS["titles"]


def test_title_beyond_the_reachable_ceiling_is_rejected(tmp_path):
    """A title no player can ever earn must fail at load, like achievements do."""
    root = copy_content(tmp_path)
    titles = json.loads((root / "titles.json").read_text())
    # Pick a content-bounded metric: unbounded metrics (rebirth_count,
    # ascended_pets) legitimately accept any target.
    season_walker = next(title for title in titles if title["metric"] == "battle_pass_premium_claims")
    season_walker["target"] = 999
    (root / "titles.json").write_text(json.dumps(titles, ensure_ascii=False))
    with pytest.raises(ValueError, match="exceeds available"):
        Catalog.load(root)


def test_duplicate_title_metric_and_target_is_rejected(tmp_path):
    root = copy_content(tmp_path)
    titles = json.loads((root / "titles.json").read_text())
    titles[-1]["metric"] = titles[0]["metric"]
    titles[-1]["target"] = titles[0]["target"]
    (root / "titles.json").write_text(json.dumps(titles, ensure_ascii=False))
    with pytest.raises(ValueError, match="duplicate title metric target"):
        Catalog.load(root)


def test_achievement_beyond_the_reachable_ceiling_is_rejected(tmp_path):
    """The pre-existing achievement guard must keep working through the shared table."""
    root = copy_content(tmp_path)
    achievements = json.loads((root / "achievements.json").read_text())
    entry = next(item for item in achievements if item["metric"] == "lineage_branches")
    entry["target"] = 999
    (root / "achievements.json").write_text(json.dumps(achievements, ensure_ascii=False))
    with pytest.raises(ValueError, match="exceeds available lineage_branches"):
        Catalog.load(root)


def test_every_shipped_title_and_achievement_sits_within_its_ceiling():
    """Guards the ceiling table itself: content must stay inside what it asserts."""
    catalog = Catalog.load(DATA)
    ceilings = catalog._metric_ceilings()
    offenders = []
    for title in catalog.titles.values():
        ceiling = ceilings.get(title.metric)
        if ceiling is not None and title.target > ceiling:
            offenders.append(f"title {title.name}: {title.target} > {title.metric}={ceiling}")
    for entry in catalog.achievements.values():
        ceiling = ceilings.get(entry.metric)
        if ceiling is not None and entry.target > ceiling:
            offenders.append(f"achievement {entry.name}: {entry.target} > {entry.metric}={ceiling}")
    assert not offenders, offenders


def test_battle_pass_ceiling_matches_the_ladder():
    """The content ceiling is a literal, so pin it to the ladder it describes."""
    catalog = Catalog.load(DATA)
    assert catalog._metric_ceilings()["battle_pass_premium_claims"] == len(battle_pass.PREMIUM_LEVELS)
    # The ladder's own title is the one that uses this ceiling.
    ladder_titles = [
        title for title in catalog.titles.values()
        if title.metric == "battle_pass_premium_claims"
    ]
    assert [title.target for title in ladder_titles] == [len(battle_pass.PREMIUM_LEVELS)]


def test_bounded_metrics_that_have_a_content_ceiling_are_all_covered():
    """Every content-bounded metric used by titles or achievements must have a ceiling.

    Metrics absent from the table are unbounded by design, so this only checks the
    reverse direction: nothing in the table may be a metric the content never uses.
    """
    catalog = Catalog.load(DATA)
    used = {entry.metric for entry in catalog.achievements.values()}
    used |= {title.metric for title in catalog.titles.values()}
    ceilings = catalog._metric_ceilings()
    assert set(ceilings).issubset(used), set(ceilings) - used
    # The bounded-only set: metrics driven by static content rather than endless play.
    expected_bounded = {
        "species_collected", "duplicate_species", "max_realm", "max_layer",
        "max_bloodline", "stage_clears", "tower_depth", "lineage_branches",
        "skills_learned", "max_skill_level", "skill_level_sum", "max_affinity",
        "adventures_discovered", "max_enhancement", "journey_claims", "echo_claims",
        "first_clear_claims", "dungeon_clears", "equipment_set_claims",
        "resonances_enabled", "main_quest_claims", "weekly_claims",
        "battle_pass_premium_claims",
    }
    assert expected_bounded.issubset(set(ceilings)), expected_bounded - set(ceilings)
