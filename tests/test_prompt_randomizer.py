"""Tests for prompt randomization anti-gaming feature.

Prompt randomization prevents benchmark gaming by replacing static "similar to"
example lists with random selections from larger fragment pools.
"""


from aimac.prompt_randomizer import generate_seed, randomize_prompt

# Sample prompt with a pattern that should be matched and replaced
SAMPLE_PROMPT = '''Consider themes similar to: "Consulting Services", "Industry Insights", "Client Success".'''

# Sample fragments JSON with enough options for randomization
SAMPLE_FRAGMENTS = '''{
    "section_themes": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
}'''


def test_randomize_prompt_deterministic():
    """Same seed produces identical output."""
    r1 = randomize_prompt(SAMPLE_PROMPT, SAMPLE_FRAGMENTS, seed=42)
    r2 = randomize_prompt(SAMPLE_PROMPT, SAMPLE_FRAGMENTS, seed=42)
    assert r1 == r2


def test_randomize_prompt_different_seeds():
    """Different seeds produce different output."""
    r1 = randomize_prompt(SAMPLE_PROMPT, SAMPLE_FRAGMENTS, seed=42)
    r2 = randomize_prompt(SAMPLE_PROMPT, SAMPLE_FRAGMENTS, seed=43)
    assert r1 != r2


def test_randomize_prompt_null_fragments():
    """NULL fragments returns original prompt unchanged."""
    assert randomize_prompt(SAMPLE_PROMPT, None) == SAMPLE_PROMPT


def test_randomize_prompt_empty_fragments():
    """Empty JSON returns original prompt unchanged."""
    assert randomize_prompt(SAMPLE_PROMPT, "{}") == SAMPLE_PROMPT


def test_randomize_prompt_partial_fragments():
    """Missing fragment types are skipped, present ones are randomized."""
    partial = '{"section_themes": ["X", "Y", "Z", "W"]}'
    result = randomize_prompt(SAMPLE_PROMPT, partial, seed=1)
    # Original values should be replaced
    assert "Consulting Services" not in result
    assert result != SAMPLE_PROMPT


def test_generate_seed_range():
    """Seed is valid positive int32."""
    for _ in range(100):
        seed = generate_seed()
        assert 0 <= seed <= 2**31 - 1
