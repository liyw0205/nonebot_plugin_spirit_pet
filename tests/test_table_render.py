"""Tables survive the message layer instead of arriving as escaped pipes.

`adapters/messaging.escape()` escapes `|`, so before this a table built by any page
reached QQ as `\\| 列1 \\|` and never rendered. These tests pin both halves: the
builder escapes only what would break a row, and the renderer passes a confirmed
table run through untouched while still escaping ordinary text.
"""

import pytest

from nonebot_plugin_spirit_pet.adapters.messaging import _qq_segments, _table_rows
from nonebot_plugin_spirit_pet.core.config import Config
from nonebot_plugin_spirit_pet.domain.models import Reply
from nonebot_plugin_spirit_pet.utils.table import header, row, table


def markdown_of(reply, **config):
    _, message = _qq_segments(reply, Config(spirit_pet_qq_mode="native", **config))
    return message["markdown"][0].data["markdown"].content


# ------------------------------------------------------------------- builder

def test_table_emits_header_separator_and_rows():
    lines = table(("项目", "甲"), (("气血", 10), ("攻击", 20)))
    assert lines == (
        "| 项目 | 甲 |",
        "| --- | --- |",
        "| 气血 | 10 |",
        "| 攻击 | 20 |",
    )


def test_a_pipe_inside_a_cell_is_escaped_so_it_cannot_split_the_row():
    assert table(("甲",), (("a|b",),))[2] == "| a\\|b |"


def test_newlines_and_blank_cells_are_flattened():
    assert table(("甲", "乙"), (("两\n行", ""),))[2] == "| 两 行 |   |"


def test_ragged_rows_are_padded_or_truncated_to_the_header_width():
    lines = table(("甲", "乙"), (("只有一格",), ("多", "出", "来")))
    assert lines[2] == "| 只有一格 |   |"
    assert lines[3] == "| 多 | 出 |"
    assert all(len(line.strip("|").split("|")) == 2 for line in lines)


def test_an_empty_header_makes_no_table():
    assert table((), (("a",),)) == ()


def test_header_and_row_helpers_agree_with_table():
    assert header("甲", "乙") == table(("甲", "乙"), ())[:2]
    assert row("a", "b") == "| a | b |"


# ------------------------------------------------------------------ detection

def test_only_a_run_confirmed_by_a_separator_is_a_table():
    lines = ("| 一 | 二 |", "| --- | --- |", "| 1 | 2 |")
    assert _table_rows(lines) == frozenset({0, 1, 2})


def test_a_stray_pipe_line_is_not_treated_as_a_table():
    assert _table_rows(("a | b", "c | d")) == frozenset()


def test_rows_without_a_separator_are_not_a_table():
    assert _table_rows(("| a | b |", "| c | d |")) == frozenset()


def test_detection_stops_at_the_first_non_table_line():
    lines = ("说明", "| 一 | 二 |", "| --- | --- |", "| 1 | 2 |", "尾巴")
    assert _table_rows(lines) == frozenset({1, 2, 3})


# ------------------------------------------------------------------ rendering

def test_native_markdown_keeps_table_pipes_unescaped():
    reply = Reply("对比", table(("项目", "甲"), (("气血", 10),)))
    markdown = markdown_of(reply)
    assert "| 项目 | 甲 |" in markdown
    assert "| --- | --- |" in markdown
    assert "| 气血 | 10 |" in markdown
    assert "\\|" not in markdown


def test_ordinary_text_is_still_escaped():
    # `+` is a markdown metacharacter, so ordinary lines keep being escaped.
    reply = Reply("说明", ("速度 10 vs 12（+2）",))
    markdown = markdown_of(reply)
    assert "速度 10 vs 12（\\+2）" in markdown


def test_a_pipe_in_ordinary_text_is_still_escaped():
    reply = Reply("说明", ("甲 | 乙",))
    assert "\\|" in markdown_of(reply)


def test_plain_text_fallback_still_shows_the_table_legibly():
    reply = Reply("对比", table(("项目", "甲"), (("气血", 10),)))
    plain, _ = _qq_segments(reply, Config(spirit_pet_qq_mode="text"))
    assert "| 项目 | 甲 |" in plain
    assert "| 气血 | 10 |" in plain


def test_a_section_heading_next_to_a_table_is_not_swallowed():
    reply = Reply("页面", ("状态", *table(("甲",), (("1",),))))
    markdown = markdown_of(reply)
    assert "**状态**" in markdown
    assert "| 甲 |" in markdown


@pytest.mark.parametrize("mode", ["native", "text"])
def test_every_mode_renders_a_table_without_dropping_rows(mode):
    reply = Reply("页面", table(("甲", "乙"), (("1", "2"), ("3", "4"))))
    if mode == "text":
        plain, _ = _qq_segments(reply, Config(spirit_pet_qq_mode="text"))
        assert "| 1 | 2 |" in plain and "| 3 | 4 |" in plain
    else:
        markdown = markdown_of(reply)
        assert "| 1 | 2 |" in markdown and "| 3 | 4 |" in markdown
