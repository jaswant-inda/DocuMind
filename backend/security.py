"""Password hashing (scrypt), signed expiring tokens (HMAC-SHA256) and a tiny rate limiter. Stdlib only."""
import base64, hashlib, hmac, json, os, secrets, time
from collections import defaultdict, deque
from fastapi import Header, HTTPException
import repo
from config import BASE_DIR

_sf = BASE_DIR / ".jwt_secret"
if os.getenv("JWT_SECRET"):
    SECRET = os.environ["JWT_SECRET"].encode()
else:
    if not _sf.exists(): _sf.write_text(secrets.token_hex(32))
    SECRET = _sf.read_text().encode()

b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
_kdf = lambda pw, salt: hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1).hex()

def hash_pw(pw):
    salt = os.urandom(16); return salt.hex() + "$" + _kdf(pw, salt)

def check_pw(pw, stored):
    s, h = stored.split("$"); return hmac.compare_digest(_kdf(pw, bytes.fromhex(s)), h)

def _sig(body): return b64(hmac.new(SECRET, body.encode(), "sha256").digest())

def make_token(uid, days=7):
    body = b64(json.dumps({"sub": uid, "exp": int(time.time()) + days * 86400}).encode())
    return body + "." + _sig(body)

def current_user(authorization: str = Header(default="")):
    try:
        body, sig = authorization.removeprefix("Bearer ").split(".")
        if not hmac.compare_digest(sig, _sig(body)): raise ValueError
        p = json.loads(unb64(body)); assert p["exp"] > time.time()
        u = repo.one("SELECT * FROM users WHERE user_id=?", p["sub"]); assert u
        return u
    except Exception:
        raise HTTPException(401, "Not signed in")

_hits = defaultdict(deque)
def rate(key, n=20, per=60):
    d, now = _hits[key], time.time()
    while d and d[0] < now - per: d.popleft()
    if len(d) >= n: raise HTTPException(429, "Too many requests - please slow down")
    d.append(now)
