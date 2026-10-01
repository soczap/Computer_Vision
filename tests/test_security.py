from vigil.security import ROLE_RANK, Principal, decode_token, hash_password, issue_token, verify_password
from vigil.db import User


def test_password_hash_roundtrip():
    h = hash_password("correct horse")
    assert h.startswith("scrypt$")
    assert verify_password("correct horse", h)
    assert not verify_password("wrong", h)
    assert hash_password("x" * 8) != hash_password("x" * 8)  # salted


def test_malformed_hash_is_rejected():
    assert not verify_password("a", "garbage")


def test_jwt_roundtrip():
    u = User(id="usr_1", username="alice", role="analyst", password_hash="-")
    claims = decode_token(issue_token(u))
    assert claims["sub"] == "usr_1" and claims["role"] == "analyst"


def test_role_ordering():
    assert ROLE_RANK["viewer"] < ROLE_RANK["analyst"] < ROLE_RANK["admin"]
    p = Principal("u", "bob", "analyst")
    assert p.has("viewer") and p.has("analyst") and not p.has("admin")
