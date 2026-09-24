import pytest

from subzero.language import Language

from subtitles.download import _get_hi_mode


def _item(language, hi="False", forced="False"):
    return {"language": language, "hi": hi, "forced": forced}


@pytest.mark.parametrize("items, language, expected", [
    ([_item("en")], Language("eng"), "don't prefer"),
    ([_item("en", hi="True")], Language("eng", hi=True), "force HI"),
    ([_item("en", hi="Excluded")], Language("eng"), "force non-HI"),
    # a profile asking for both regular and HI English must resolve each requirement to its own item
    ([_item("en"), _item("en", hi="True")], Language("eng", hi=True), "force HI"),
    ([_item("en", hi="True"), _item("en")], Language("eng"), "don't prefer"),
    ([_item("en", hi="Excluded"), _item("en", forced="True")], Language("eng", forced=True), "don't prefer"),
    ([_item("fr", hi="True")], Language("eng"), "don't prefer"),
])
def test_hi_mode_matches_the_profile_item_of_the_requirement(items, language, expected):
    assert _get_hi_mode({"items": items}, language) == expected
