#!/usr/bin/env python3
"""Test token verification."""
import sys
import requests
import json

# Get token
login_response = requests.post(
    "http://localhost:8001/api/v1/auth/login",
    json={"email": "test@example.com", "password": "Test@2024!Secure"},
)
print(f"Login status: {login_response.status_code}")
if login_response.status_code == 200:
    token_data = login_response.json()
    token = token_data["access_token"]
    print(f"Token: {token[:50]}...")

    # Test planets endpoint
    planets_response = requests.get(
        "http://localhost:8001/api/v1/planets", headers={"Authorization": f"Bearer {token}"}
    )
    print(f"\nPlanets status: {planets_response.status_code}")
    print(f"Response: {planets_response.text}")

    # Test session endpoint
    session_response = requests.get(
        "http://localhost:8001/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"}
    )
    print(f"\nSession status: {session_response.status_code}")
    print(f"Response: {session_response.text}")
else:
    print(f"Login failed: {login_response.text}")
