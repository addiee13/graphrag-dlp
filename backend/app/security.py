"""Verified server identities and fail-closed evidence policy."""
import os
import secrets
import time
from dataclasses import dataclass, field
import jwt
from fastapi import HTTPException

IDENTITIES = {
    "contractor": dict(name="External Contractor", clearance_level=1, departments=["engineering"], tenant_id="acme", roles=["reader"]),
    "engineer": dict(name="Engineering Analyst", clearance_level=2, departments=["engineering"], tenant_id="acme", roles=["reader"]),
    "vp": dict(name="Executive VP", clearance_level=4, departments=["engineering", "procurement", "mna"], tenant_id="acme", roles=["reader"]),
    "admin": dict(name="Demo Administrator", clearance_level=4, departments=["engineering", "procurement", "mna"], tenant_id="acme", roles=["admin", "ingestor"]),
    "other_tenant": dict(name="Other Tenant Administrator", clearance_level=4, departments=["engineering", "procurement", "mna"], tenant_id="other", roles=["admin", "ingestor"]),
}

def persistent_key(filename):
    """Atomically publish a complete mode0600 key, including concurrent workers."""
    import tempfile
    from pathlib import Path
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd, temporary = tempfile.mkstemp(prefix=".key-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(secrets.token_hex(32))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    value = path.read_text().strip()
    if len(value) < 32: raise RuntimeError("Invalid persisted signing key")
    return value

@dataclass
class Settings:
    mode: str = field(default_factory=lambda: os.getenv("APP_ENV", "demo"))
    secret: str | None = field(default_factory=lambda: os.getenv("JWT_SECRET"))
    issuer: str = field(default_factory=lambda: os.getenv("JWT_ISSUER", "graphrag-dlp-demo"))
    audience: str = field(default_factory=lambda: os.getenv("JWT_AUDIENCE", "graphrag-dlp"))
    jwks_url: str = field(default_factory=lambda: os.getenv("JWT_JWKS_URL", ""))
    algorithm: str = field(default_factory=lambda: os.getenv("JWT_ALGORITHM", "RS256"))
    db_path: str = field(default_factory=lambda: os.getenv("DLP_DB_PATH", "backend/data/graph.sqlite3"))

    def __post_init__(self):
        if self.secret:
            if len(self.secret) < 32:
                raise RuntimeError("JWT_SECRET must contain at least 32 characters")
            return
        if self.db_path == ":memory:":
            self.secret = secrets.token_hex(32)
            return
        self.secret = persistent_key(self.db_path + ".key")

class Auth:
    def __init__(self, settings):
        self.settings = settings
        self.jwks = None
        if settings.mode == "production":
            if not settings.jwks_url.startswith("https://") or settings.algorithm not in ("RS256", "ES256"):
                raise RuntimeError("Production requires HTTPS JWKS and pinned RS256/ES256")
            self.jwks = jwt.PyJWKClient(settings.jwks_url, cache_jwk_set=True, lifespan=300)

    def issue(self, identity_id):
        if self.settings.mode == "production":
            raise HTTPException(404, "Not found")
        if identity_id not in IDENTITIES:
            raise HTTPException(400, "Unknown identity_id")
        claims = dict(IDENTITIES[identity_id], user_id=identity_id)
        now = int(time.time())
        payload = dict(claims, sub=identity_id, iat=now, nbf=now, exp=now + 3600,
                       iss=self.settings.issuer, aud=self.settings.audience)
        return dict(access_token=jwt.encode(payload, self.settings.secret, algorithm="HS256"),
                    token_type="bearer", expires_in=3600, claims=claims)

    def verify(self, token):
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key if self.jwks else self.settings.secret
            claims = jwt.decode(token, key, algorithms=[self.settings.algorithm if self.jwks else "HS256"],
                issuer=self.settings.issuer, audience=self.settings.audience,
                options={"require": ["exp", "sub", "iss", "aud", "tenant_id", "clearance_level", "departments", "roles"]})
            if (not isinstance(claims["tenant_id"], str) or not claims["tenant_id"] or
                type(claims["clearance_level"]) is not int or not 1 <= claims["clearance_level"] <= 4 or
                not all(isinstance(claims[k], list) and all(isinstance(v, str) for v in claims[k]) for k in ("departments", "roles"))):
                raise ValueError()
            claims["user_id"] = claims["sub"]
            return claims
        except Exception:
            raise HTTPException(401, "Invalid or expired bearer token") from None

def permitted(record, claims):
    level = record.get("classification_level")
    department = record.get("department")
    return (record.get("tenant_id") == claims["tenant_id"] and type(level) is int and
            1 <= level <= claims["clearance_level"] and isinstance(department, str) and
            (department in ("public", "shared") or department in claims["departments"]))
