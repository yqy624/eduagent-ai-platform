"""Quick AI test"""
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

# Login
a = req("POST", "/api/auth/login", {"username":"admin","password":"admin123","role":"ADMIN"})
tok = a["data"]["token"]
print("Login OK")

# QA - check the exact error
qa = req("POST", "/api/ai/courses/4/qa", {"question":"Python是什么？"}, token=tok)
print("Code:", qa.get("code"))
print("Message:", qa.get("message"))
