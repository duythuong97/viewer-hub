"""Premium unlock codes: Ed25519 (RFC 8032 vectors), code format, and unlocking a running app (core/unlock.py)."""
from __future__ import annotations

import pytest

from viewer_hub.core import ed25519, unlock

TEST_KEY = bytes(range(32))  # stands in for the author's key; the app's PUBLIC_KEY is swapped for its public key


@pytest.fixture()
def signed(monkeypatch):
    monkeypatch.setattr(unlock, "PUBLIC_KEY", ed25519.public_key(TEST_KEY))
    return lambda *keys: unlock.issue(TEST_KEY, set(keys))


def test_ed25519_rfc8032_vectors():
    for secret, public, message, signature in (
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ):
        sk, pk, msg, sig = (bytes.fromhex(x) for x in (secret, public, message, signature))
        assert ed25519.public_key(sk) == pk
        assert ed25519.sign(sk, msg) == sig
        assert ed25519.verify(pk, msg, sig)
        assert not ed25519.verify(pk, msg + b"x", sig)
        assert not ed25519.verify(pk, msg, sig[:-1] + bytes([sig[-1] ^ 1]))


def test_codes_are_random_and_typed_loosely(signed):
    first, second = signed("bridge"), signed("bridge")
    assert first != second and first.startswith("VH2-")
    assert unlock.features(first) == unlock.features(second) == {"bridge"}
    messy = "  " + first.lower().replace("-", " \n") + " "
    assert unlock.features(messy) == {"bridge"}


def test_codes_carry_any_feature_name(signed):
    """A name no module of this build declares still unlocks: an addon made later only has to use it."""
    assert unlock.features(signed("bridge", "jira-reader")) == {"bridge", "jira-reader"}
    with pytest.raises(unlock.UnlockError):
        signed("Bad Name")


def test_bad_codes(signed):
    code = signed("bridge")
    tampered = code[:20] + ("A" if code[20] != "A" else "B") + code[21:]
    for bad in ("", "hello", "VH2-AAAA", "VH1-" + code[4:], tampered, code[:-8]):
        with pytest.raises(unlock.UnlockError):
            unlock.features(bad)


def test_real_public_key_rejects_test_codes():
    with pytest.raises(unlock.UnlockError):
        unlock.features(unlock.issue(TEST_KEY, {"bridge"}))


def _client(paths):
    from tests.test_core import _client_with

    return _client_with(paths, premium=False)


def test_unlock_opens_the_feature_without_restart(paths, signed):
    from tests.addon_kit import install

    install(paths, "secret-tool", label="Công cụ bí mật", premium="secret")
    client = _client(paths)
    assert client.get("/api/addons/secret-tool").status_code == 404  # locked: does not exist
    assert client.post("/api/premium/unlock", json={"code": "nope"}).status_code == 400
    answer = client.post("/api/premium/unlock", json={"code": signed("secret")})
    assert answer.status_code == 200, answer.get_json()
    body = answer.get_json()
    assert body["message"] == "Đã mở khoá: Công cụ bí mật" and body["path"] == "/x/secret-tool/"
    app = client.get("/api/app").get_json()
    assert "Công cụ bí mật" in [item["label"] for item in app["nav"]] and app["locked"] is False
    assert client.get("/api/addons/secret-tool").status_code == 200
    # Saved in hub.db: the next start is unlocked too, and the same code twice is kept once.
    client.post("/api/premium/unlock", json={"code": unlock.stored(_db(paths))[0]})
    assert len(unlock.stored(_db(paths))) == 1
    again = _client(paths).get("/api/app").get_json()
    assert again["locked"] is False


def test_code_for_an_addon_not_installed_yet(paths, signed):
    from tests.addon_kit import install

    client = _client(paths)
    answer = client.post("/api/premium/unlock", json={"code": signed("later")}).get_json()
    assert "chưa được cài" in answer["message"]
    install(paths, "later-tool", label="Công cụ sau", premium="later")
    assert "Công cụ sau" in [item["label"] for item in _client(paths).get("/api/app").get_json()["nav"]]


def _db(paths):
    from viewer_hub.core.migrate import open_hub

    return open_hub(paths).db
