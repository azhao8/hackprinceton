"""Spoken lines lose emojis and markdown (#81): the voice must not read symbols out."""

from app.brain.spoken import clean_spoken


def test_emojis_go():
    assert clean_spoken("Stay hydrated, Mom. 💧") == "Stay hydrated, Mom."
    assert clean_spoken("Good morning ☀️! Ready? 👍🏽") == "Good morning! Ready?"
    assert clean_spoken("Family 👨‍👩‍👧 is here") == "Family is here"
    assert clean_spoken("🇺🇸") == ""


def test_markdown_goes():
    assert clean_spoken("**Here** is your *water*.") == "Here is your water."
    assert clean_spoken("# Plan\n- Go to the kitchen\n- Bring the pills") == "Plan Go to the kitchen Bring the pills"
    assert clean_spoken("1. First, the `pills`.") == "First, the pills."
    assert clean_spoken("See [the label](http://x)") == "See the label"


def test_plain_text_stays():
    for t in ["Hi Mom, it's 3.5 degrees warmer today.", "Dr. Lee said 2 pills, not 3!", "Is that you, David?"]:
        assert clean_spoken(t) == t
