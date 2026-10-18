"""Numbers in customer messages read the way the website shows them."""

from __future__ import annotations

import pytest

from apps.common.phone import display_phone


@pytest.mark.parametrize(("stored", "shown"), [
    ("+12233631317", "+1 (223) 363-1317"),
    ("+16622195243", "+1 (662) 219-5243"),
    ("  +15550007890 ", "+1 (555) 000-7890"),
])
def test_a_us_number_is_grouped_as_the_website_shows_it(stored, shown):
    assert display_phone(stored) == shown


@pytest.mark.parametrize("stored", [
    "+233241234567",   # not US/Canada: left exactly as stored
    "+447911123456",
    "+1223363131",     # one digit short
    "+122336313170",   # one digit long
    "12233631317",     # no plus sign
    "+1 (223) 363-1317",  # already grouped
])
def test_anything_else_comes_back_unchanged(stored):
    assert display_phone(stored) == stored.strip()


@pytest.mark.parametrize("stored", ["", None])
def test_no_number_is_an_empty_string(stored):
    assert display_phone(stored) == ""
