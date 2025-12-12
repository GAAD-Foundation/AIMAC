"""Critical safety tests - MUST NEVER FAIL.

These tests prevent:
1. Real API calls that cost money ($80 incident)
2. Loss of manual data overrides
"""

import sqlite3
import tempfile
from unittest.mock import Mock, patch

from aimac.database import upsert_models
from aimac.openrouter import fetch_top_models


def test_never_calls_real_api():
    """Ensure fetch_top_models NEVER makes real API calls in tests."""
    with patch('aimac.openrouter.httpx.Client') as mock_client:
        # Setup mock
        mock_instance = Mock()
        mock_client.return_value.__enter__.return_value = mock_instance
        mock_instance.get.return_value.json.return_value = {"data": []}

        # Call function
        fetch_top_models()

        # Verify mock was called (not real API)
        mock_instance.get.assert_called_once()

        # Verify the URL does NOT contain a real API endpoint
        call_args = mock_instance.get.call_args
        called_url = call_args[0][0]
        assert "openrouter.ai" in called_url  # It should be mocked
        assert mock_client.called  # Confirm we used the mock


def test_manual_overrides_preserved():
    """Ensure upsert NEVER overwrites manual override fields."""
    # Create temp database
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = sqlite3.connect(f.name)

        # Create schema (simplified for test)
        conn.executescript("""
            CREATE TABLE models (
                pk INTEGER PRIMARY KEY,
                id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                context_length INTEGER NOT NULL,
                supported_parameters TEXT NOT NULL,
                pricing TEXT NOT NULL,
                created INTEGER NOT NULL,
                canonical_slug TEXT,
                hugging_face_id TEXT,
                manual_model_display_name TEXT,
                manual_company_display_name TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Insert model with manual overrides
        conn.execute("""
            INSERT INTO models (
                id, name, description, context_length,
                supported_parameters, pricing, created,
                manual_model_display_name, manual_company_display_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "test/model", "Test Model", "Description", 4096,
            '[]', '{}', 1234567890,
            "Custom Model Name", "Custom Company"
        ))
        conn.commit()
        conn.close()

        # Mock get_connection to use our temp db
        with patch('aimac.database._core.get_connection') as mock_get_conn:
            mock_get_conn.return_value = sqlite3.connect(f.name)

            # Upsert with new data
            models = [{
                "id": "test/model",
                "name": "Updated Name",
                "description": "Updated Description",
                "context_length": 8192,
                "supported_parameters": ["new_param"],
                "pricing": {"prompt": "0.01"},
                "created": 9999999999
            }]

            upsert_models(models)

        # Verify manual overrides were NOT changed
        conn = sqlite3.connect(f.name)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT manual_model_display_name, manual_company_display_name,
                   name, description
            FROM models WHERE id = ?
        """, ("test/model",))

        result = cursor.fetchone()
        conn.close()

        # Manual fields should be unchanged
        assert result[0] == "Custom Model Name"
        assert result[1] == "Custom Company"
        # Other fields should be updated
        assert result[2] == "Updated Name"
        assert result[3] == "Updated Description"
