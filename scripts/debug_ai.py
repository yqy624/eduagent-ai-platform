#!/usr/bin/env python
"""Debug AI agent calls"""
import http.client, json

HOST = "localhost"
PORT = 8001

def req(method, path, body=None, token=None):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=60)
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    b = json.dumps(body) if body else None
    conn.request(method, path, b, headers)
    resp = conn.getresponse()
    data = resp.read().decode()
    try:
        return json.loads(data)
    except:
        return {"raw": data, "status": resp.status}

# Login
admin = req("POST", "/api/auth/login", {"username":"admin","password":"admin123","role":"ADMIN"})
tok = admin.get("data", {}).get("token", "")
print(f"Login: {admin.get('code')}")
print(f"Token OK: {bool(tok)}")

# QA
print("\n--- QA Test ---")
qa = req("POST", "/api/ai/courses/4/qa", {"question": "Python课程讲什么？"}, token=tok)
print(f"Status: {qa.get('code')}")
print(f"Response keys: {list(qa.keys())}")
if qa.get("data"):
    print(f"Data keys: {list(qa['data'].keys())}")

# If error, print it
if qa.get("code") != 200:
    print(f"Message: {qa.get('message', 'N/A')}")
