"""Debug grading suggestion 500"""
import http.client, json

def req(method, path, body=None, token=None):
    conn = http.client.HTTPConnection("localhost", 8001, timeout=30)
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    if body: conn.request(method, path, json.dumps(body), h)
    else: conn.request(method, path, headers=h)
    d = json.loads(conn.getresponse().read())
    conn.close()
    return d

t = req("POST", "/api/auth/login", {"username":"teacher1","password":"teacher123","role":"TEACHER"})
tok = t["data"]["token"]
print("Login OK")

g = req("POST", "/api/ai/teacher/submissions/1/grade-suggestion", token=tok)
print("Code:", g.get("code"))
print("Msg:", str(g.get("message",""))[:300])
