import pytest

from nonebot_plugin_spirit_pet.application.commands import COMMANDS
from nonebot_plugin_spirit_pet import __plugin_meta__
from nonebot_plugin_spirit_pet.domain.models import GameError
from nonebot_plugin_spirit_pet.gameplay.information import _HELP_SECTIONS

from .support import sql


def test_status_shows_explicit_primary_secondary_and_talent(game, play):
    play("adopt", "青鸾", user="private-id-123")
    reply = play("status", user="private-id-123")
    species = game[0].content.species["qingluan"]
    assert f"主属性：{game[0].content.elements[species.primary_element].name}" in reply.text()
    assert "副属性：木" in reply.text()
    talent = game[0].content.talents[species.talent]
    assert talent.name in reply.text() and talent.description in reply.text()
    assert "private-id-123" not in reply.text()


def test_status_shows_bond_guard_unlock(game, play):
    play("adopt", "青鸾")
    assert "亲密达到 100 后解锁" in play("status").text()
    sql(game[1], "UPDATE pets SET affinity=100")
    assert "每场战斗首次受控时自动抵挡" in play("status").text()


def test_help_has_category_overview_and_short_subpages(game, play):
    overview = play("help")
    contract = play("help", "结契")
    assert "秘境与关卡：发送灵宠帮助 秘境与关卡 查看" in overview.text()
    assert "灵宠领养 青鸾" in contract.text()
    assert "灵宠封存库" in contract.text()
    assert "灵宠帮助" in contract.commands
    assert all(not line.lstrip().startswith("/") for line in (*overview.lines, *contract.lines))


def test_help_categories_cover_registered_commands():
    help_text = "灵宠帮助 " + "\n".join(
        line for section in _HELP_SECTIONS.values() for line in section
    )
    missing = [name for name in COMMANDS if name not in help_text and name != "灵宠"]
    assert not missing


def test_plugin_usage_does_not_assume_a_command_prefix():
    assert all(not item.strip().startswith("/") for item in __plugin_meta__.usage.split("·"))


def test_rename_entry_without_argument_explains_the_existing_command(game, play):
    reply = play("dao_name")
    assert reply.title == "修改道号"
    assert "灵宠道号 青云" in reply.text()
    assert reply.commands == ("我的灵宠",)


def test_catalog_pages_cover_every_species_once(game, play):
    content = game[0].content
    pages = (len(content.species) + 4) // 5
    seen = []
    for page in range(1, pages + 1):
        reply = play("catalog", str(page))
        assert reply.title == f"万灵图鉴 {page}/{pages}"
        headers = reply.lines[::3]
        assert len(headers) <= 5
        seen.extend(line.split(" · ")[0] for line in headers)
        assert all("主属性：" in line and "副属性：" in line for line in headers)
        assert (f"灵宠图鉴 {page + 1}" in reply.commands) == (page < pages)
    assert seen == [species.name for species in content.species.values()]


def test_catalog_detail_contains_talent_stats_and_real_acquisition(game, play):
    pool = game[0].content.pools["standard"]
    for species in game[0].content.species.values():
        reply = play("catalog", species.name)
        talent = game[0].content.talents[species.talent]
        assert talent.description in reply.text()
        assert f"初始气血 {species.stats.hp}" in reply.text()
        assert ("初始可选" in reply.text()) == species.starter
        assert "召唤概率" in reply.text() or "孵化" in reply.text()
        assert ("十连珍稀保底池" in reply.text()) == (species.id in pool.guaranteed_species)
        assert "召唤限定" not in reply.text()


@pytest.mark.parametrize("arg", ["0", "999", "不存在的宠物"])
def test_catalog_rejects_invalid_page_and_unknown_species(play, arg):
    with pytest.raises(GameError):
        play("catalog", arg)
