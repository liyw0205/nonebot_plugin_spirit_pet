import pytest
from pydantic import ValidationError

from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import GameError

from .team_support import NAMES, NOW, USERS, create_players, memberships, requests


def test_team_request_configuration_defaults():
    config = Config()
    assert config.spirit_pet_team_request_ttl == 600
    assert config.spirit_pet_team_request_limit == 10


@pytest.mark.parametrize("field,value,expected", [
    ("spirit_pet_team_request_ttl", 1, 1),
    ("spirit_pet_team_request_ttl", 86400, 86400),
    ("spirit_pet_team_request_ttl", "600", 600),
    ("spirit_pet_team_request_limit", 1, 1),
    ("spirit_pet_team_request_limit", 100, 100),
    ("spirit_pet_team_request_limit", "100", 100),
])
def test_team_request_configuration_accepts_boundaries_and_environment_numbers(field, value, expected):
    config = Config.model_validate({field: value})
    assert getattr(config, field) == expected
    assert isinstance(getattr(config, field), int)


@pytest.mark.parametrize("field,value", [
    ("spirit_pet_team_request_ttl", 0),
    ("spirit_pet_team_request_ttl", -1),
    ("spirit_pet_team_request_ttl", "0"),
    ("spirit_pet_team_request_ttl", 1.5),
    ("spirit_pet_team_request_ttl", None),
    ("spirit_pet_team_request_ttl", "invalid"),
    ("spirit_pet_team_request_limit", 0),
    ("spirit_pet_team_request_limit", -1),
    ("spirit_pet_team_request_limit", 101),
    ("spirit_pet_team_request_limit", "101"),
    ("spirit_pet_team_request_limit", 1.5),
    ("spirit_pet_team_request_limit", None),
    ("spirit_pet_team_request_limit", "invalid"),
])
def test_team_request_configuration_rejects_invalid_limits_and_nonintegers(field, value):
    with pytest.raises(ValidationError) as caught:
        Config.model_validate({field: value})
    assert any(error["loc"] == (field,) for error in caught.value.errors())


@pytest.mark.parametrize("kind", ["apply", "invite"])
def test_minimum_configured_ttl_drives_runtime_expiry_without_default_fallback(game, play, kind):
    game[0].config = Config(spirit_pet_team_request_ttl=1)
    create_players(play, count=2)
    play("team_create", user=USERS[0])
    action, sender, argument, recipient, target = (
        ("team_join", 1, NAMES[0], 0, NAMES[1]) if kind == "apply"
        else ("team_invite", 0, NAMES[1], 1, NAMES[0])
    )
    play(action, argument, user=USERS[sender])
    assert requests(game[1])[0]["expires_at"] == NOW + 1
    with pytest.raises(GameError):
        play("team_accept", target, user=USERS[recipient], now=NOW + 1)
    assert len(memberships(game[1])) == 1
    play(action, argument, user=USERS[sender], now=NOW + 1)
    assert requests(game[1])[0]["expires_at"] == NOW + 2
    play("team_accept", target, user=USERS[recipient], now=NOW + 1)
    assert len(memberships(game[1])) == 2
    assert not requests(game[1])
