import requests

login_data = {
    "email": "test@example.com",
    "password": "Test@2024!Secure"
}

print("Logging in...")
response = requests.post("http://localhost:8000/api/v1/auth/login", json=login_data)
if response.status_code != 200:
    print("Login failed:", response.text)
    exit(1)

token = response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("Fetching tree...")
tree_res = requests.get("http://localhost:8000/api/v1/strategy/tree", headers=headers)
print("Tree response:", tree_res.status_code)
data = tree_res.json()
print("Cycles:", len(data.get("cycles", [])))
print("OKRs:", len(data.get("okrs", [])))
print("Key Results:", len(data.get("key_results", [])))
