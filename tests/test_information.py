import pytest

from nonebot_plugin_spirit_pet.domain.models import GameError


def test_status_shows_explicit_primary_secondary_and_talent(game, play):
    play("adopt", "青鸾", user="private-id-123")
    reply = play("status", user="private-id-123")
    species = game[0].content.species["qingluan"]
    assert f"主属性：{game[0].content.elements[species.primary_element].name}" in reply.text()
    assert "副属性：木" in reply.text()
    talent = game[0].content.talents[species.talent]
    assert talent.name in reply.text() and talent.description in reply.text()
    assert "private-id-123" not in reply.text()


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
    for species in game[0].content.species.values():
        reply = play("catalog", species.name)
        talent = game[0].content.talents[species.talent]
        assert talent.description in reply.text()
        assert f"初始气血 {species.stats.hp}" in reply.text()
        assert ("初始可选" in reply.text()) == species.starter
        assert "召唤概率" in reply.text() or "孵化" in reply.text()
        assert "召唤限定" not in reply.text()


@pytest.mark.parametrize("arg", ["0", "999", "不存在的宠物"])
def test_catalog_rejects_invalid_page_and_unknown_species(play, arg):
    with pytest.raises(GameError):
        play("catalog", arg)
