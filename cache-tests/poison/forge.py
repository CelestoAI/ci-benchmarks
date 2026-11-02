"""Send cache lookups with a tampered runtime token (signature no longer valid).

Changes the token's cache scopes (`ac`) to claim read access to another
branch, keeps GitHub's signature, and asks the proxy for the other branch's
entry. A correct API rejects the token (logged as invalid_token) and answers
a miss.
"""
import base64, json, os, sys, urllib.request

def b64d(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

def b64e(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

token = os.environ["ACTIONS_RUNTIME_TOKEN"]
url = os.environ["ACTIONS_RESULTS_URL"].rstrip("/") + "/twirp/github.actions.results.api.v1.CacheService/GetCacheEntryDownloadURL"
target_ref, key, version = sys.argv[1], sys.argv[2], sys.argv[3]
header, payload, signature = token.split(".")
claims = json.loads(b64d(payload))
claims["ac"] = json.dumps([{"Scope": target_ref, "Permission": 1}])
forged = ".".join([header, b64e(json.dumps(claims).encode()), signature])
for name, tok in (("forged", forged), ("garbage", "not-a-token")):
    req = urllib.request.Request(url, data=json.dumps({"key": key, "restore_keys": [], "version": version}).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = {"http": e.code}
    print(f"{name} token -> {body}")
    if body.get("ok") or body.get("signed_download_url"):
        sys.exit(f"POISONING: {name} token got a hit")
print("PASS: tampered tokens get no entry")
