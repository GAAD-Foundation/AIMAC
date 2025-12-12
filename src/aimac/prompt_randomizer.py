"""Prompt randomization for anti-gaming.

Replaces static example lists with random selections from larger pools
to prevent benchmark gaming while maintaining semantic equivalence.
"""

import json
import random
import re

# Regex patterns for each fragment type in user prompts
PATTERNS = {
    "nav_links": re.compile(
        r'(links\*\* including: )"([^"]+)", "([^"]+)", "([^"]+)"'
    ),
    "section_themes": re.compile(
        r'(themes similar to: )"([^"]+)", "([^"]+)", "([^"]+)"'
    ),
    "terminology": re.compile(
        r'(terminology like: )"([^"]+)", "([^"]+)", "([^"]+)"'
    ),
    "ctas": re.compile(
        r'(verbs similar to: )"([^"]+)", "([^"]+)", "([^"]+)"'
    ),
    "engagement": re.compile(
        r'(similar but not limited to: )"([^"]+)"'
    ),
    "sidebar": re.compile(
        r'(Ideas: )"([^"]+)", "([^"]+)", "([^"]+)"'
    ),
}

# How many fragments to select per type
FRAGMENT_COUNTS = {
    "nav_links": 3,
    "section_themes": 3,
    "terminology": 3,
    "ctas": 3,
    "engagement": 1,
    "sidebar": 3,
}


def randomize_prompt(
    user_prompt: str,
    prompt_fragments_json: str | None,
    seed: int | None = None,
) -> str:
    """Replace text in prompt with randomly selected fragments.

    Args:
        user_prompt: The category's user prompt template
        prompt_fragments_json: JSON string of fragment options (or None to skip)
        seed: Optional seed for reproducibility (stored in request for debug)

    Returns:
        Randomized prompt with different fragments selected
    """
    if not prompt_fragments_json:
        return user_prompt

    fragments: dict[str, list[str]] = json.loads(prompt_fragments_json)

    rng = random.Random(seed)
    result = user_prompt

    for fragment_type, pattern in PATTERNS.items():
        options = fragments.get(fragment_type, [])
        count = FRAGMENT_COUNTS.get(fragment_type, 3)

        if len(options) < count:
            continue  # Not enough fragments, skip this type

        selected = rng.sample(options, count)

        def replacer(match: re.Match, count: int = count, selected: list[str] = selected) -> str:
            prefix = match.group(1)
            if count == 1:
                return f'{prefix}"{selected[0]}"'
            else:
                quoted = '", "'.join(selected)
                return f'{prefix}"{quoted}"'

        result = pattern.sub(replacer, result, count=1)

    return result


def generate_seed() -> int:
    """Generate a seed for this request (stored for reproducibility)."""
    return random.randint(0, 2**31 - 1)
