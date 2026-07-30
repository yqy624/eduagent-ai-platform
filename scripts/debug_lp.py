"""Debug learning plan 500"""
import http.client, json

def req(method, path, body=None, token=None):
    conn = http.client.HTTPConnection("localhost", 8001, timeout=30)
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    if body: conn.request(method, path, json.dumps(body), h)
    else: conn.request(method, path, headers=h)
    try:
        resp = conn.getresponse()
        raw = resp.read().decode()
        d = json.loads(raw)
        return d
    except Exception as e:
        return {"error": str(e), "raw": raw[:500] if 'raw' in dir() else "no data"}
    finally:
        conn.close()

t = req("POST", "/api/auth/login", {"username":"teacher1","password":"teacher123","role":"TEACHER"})
tok = t["data"]["token"]
print("Login OK")

# Test learning plan
plan = req("POST", "/api/ai/students/4/learning-plan?course_id=4", token=tok)
print("Plan code:", plan.get("code"))
print("Plan msg:", plan.get("message", "")[:300])
