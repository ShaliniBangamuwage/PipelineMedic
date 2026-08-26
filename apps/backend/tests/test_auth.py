from app.services.auth import hash_password, verify_password

def test_password_hash_is_not_reversible():
    hashed=hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)