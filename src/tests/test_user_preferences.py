"""Tests for user preferences endpoints."""

from fastapi.testclient import TestClient


class TestUserPreferences:
    """Tests for user preferences updates."""

    def test_update_preferences_success(self, client: TestClient, test_user_with_tokens: dict):
        """Test updating user preferences."""
        access_token = test_user_with_tokens["access_token"]
        preferences = {
            "theme": "dark",
            "language": "pt-BR",
            "ai_tone": "casual"
        }
        
        response = client.put(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"preferences": preferences}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["preferences"] == preferences
        
        # Verify persistence
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["preferences"] == preferences

    def test_update_preferences_partial(self, client: TestClient, test_user_with_tokens: dict):
        """Test updating user preferences partially (overwrite behavior)."""
        access_token = test_user_with_tokens["access_token"]
        
        # Set initial preferences
        client.put(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"preferences": {"theme": "light", "notifications": True}}
        )
        
        # Update with new dict (should replace entire dict based on typical PUT behavior for JSON fields unless merged manually)
        # In our implementation, we are replacing the field value, so it should be a replacement.
        new_preferences = {"theme": "dark"}
        response = client.put(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"preferences": new_preferences}
        )
        
        assert response.status_code == 200
        data = response.json()
        # Verify merge behavior: new value overwrites old, distinct value persists
        assert data["preferences"]["theme"] == "dark"
        assert data["preferences"]["notifications"] is True
