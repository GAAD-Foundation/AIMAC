"""Tests for model set canonicalization and persistence helpers."""

import sqlite3

import pytest

from aimac.database import canonicalize_model_ids, get_model_set, upsert_model_set


@pytest.mark.parametrize(
    ("input_ids", "expected"),
    [
        (["GPT-4", "claude-3-opus", "GPT-4"], '["claude-3-opus","gpt-4"]'),
        (["B", "a", "B"], '["a","b"]'),
        (["model / with spaces", "another"], '["another","model/withspaces"]'),
        ([" Some", "SOME", "some"], '["some"]'),
        ([], '[]'),
    ],
)
def test_canonicalize_model_ids(input_ids: list[str], expected: str) -> None:
    """Canonicalization lowercases, de-duplicates, sorts, and removes spaces."""
    assert canonicalize_model_ids(input_ids) == expected


def test_upsert_model_set_reuses_existing_pk(model_sets_db: sqlite3.Connection) -> None:
    """Upserting the same model set returns the original primary key."""
    first_pk = upsert_model_set(["gpt-4", "claude-3-opus"])

    second_pk = upsert_model_set(["CLAUDE-3-OPUS", "GPT-4"])

    assert second_pk == first_pk

    third_pk = upsert_model_set(["llama-3", "gemini-pro"])

    assert third_pk != first_pk


def test_get_model_set_found_and_missing(model_sets_db: sqlite3.Connection) -> None:
    """Fetching by canonical IDs returns rows with expected columns."""
    pk = upsert_model_set(["gpt-4", "claude-3-opus"])

    row = get_model_set(["claude-3-opus", "GPT-4"])

    assert row is not None
    assert row["pk"] == pk
    assert row["sorted_model_list"] == '["claude-3-opus","gpt-4"]'
    assert "created_at" in row
    assert "updated_at" in row

    missing = get_model_set(["nonexistent-model"])

    assert missing is None


@pytest.mark.parametrize(
    "payload",
    [
        '["openai/gpt-4","anthropic/claude"]',  # not sorted
        '["Anthropic/claude","openai/gpt-4"]',  # uppercase
        '["anthropic / claude","openai/gpt-4"]',  # spaces inside IDs
        '["dup","dup","openai/gpt-4"]',  # duplicates
    ],
)
def test_model_set_triggers_reject_non_canonical(
    model_sets_db: sqlite3.Connection, payload: str
) -> None:
    """Database trigger prevents non-canonical payloads from persisting."""
    with pytest.raises(sqlite3.IntegrityError):
        model_sets_db.execute(
            "INSERT INTO model_sets (sorted_model_list) VALUES (?)",
            (payload,),
        )
        model_sets_db.commit()
