"""HTTP Digest auth — pure logic, runs without Home Assistant."""

import hashlib

from conftest import load_module

digest = load_module("transport/digest.py")
DigestAuth = digest.DigestAuth
parse_challenge = digest.parse_challenge


def md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


def test_rfc2617_vector():
    """Matches the canonical RFC 2617 §3.5 worked example."""
    challenge = parse_challenge(
        'Digest realm="testrealm@host.com", qop="auth", '
        'nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", '
        'opaque="5ccc069c403ebaf9f0171e9517f40e41", algorithm=MD5'
    )
    auth = DigestAuth("Mufasa", "Circle Of Life")
    header = auth.authorization("GET", "/dir/index.html", challenge, cnonce="0a4f113b")

    ha1 = md5("Mufasa:testrealm@host.com:Circle Of Life")
    ha2 = md5("GET:/dir/index.html")
    expected = md5(
        f"{ha1}:dcd98b7102dd2f0e8b11d0f600bfb0c093:00000001:0a4f113b:auth:{ha2}"
    )
    assert f'response="{expected}"' in header
    assert "qop=auth" in header
    assert "nc=00000001" in header
    assert 'opaque="5ccc069c403ebaf9f0171e9517f40e41"' in header


def test_parses_echostar_challenge():
    """The exact challenge a Wally/Hopper sends on port 80."""
    challenge = parse_challenge(
        'Digest realm="Please provide user name and password", '
        'charset="UTF-8", algorithm="MD5", '
        'nonce="65e56150:a8684559f28611e14b90c2562078a44f", qop="auth"'
    )
    assert challenge["realm"] == "Please provide user name and password"
    assert challenge["nonce"] == "65e56150:a8684559f28611e14b90c2562078a44f"
    assert challenge["qop"] == "auth"
    assert challenge["algorithm"] == "MD5"


def test_nonce_count_increments():
    challenge = parse_challenge('Digest realm="r", qop="auth", nonce="abc"')
    auth = DigestAuth("u", "p")
    first = auth.authorization("GET", "/a", challenge)
    second = auth.authorization("GET", "/a", challenge)
    assert "nc=00000001" in first
    assert "nc=00000002" in second


def test_without_qop_falls_back_to_rfc2069():
    challenge = parse_challenge('Digest realm="r", nonce="abc"')
    auth = DigestAuth("u", "p")
    header = auth.authorization("GET", "/x", challenge)
    ha1 = md5("u:r:p")
    ha2 = md5("GET:/x")
    expected = md5(f"{ha1}:abc:{ha2}")
    assert f'response="{expected}"' in header
    assert "qop=" not in header


def test_rejects_non_digest_scheme():
    import pytest

    with pytest.raises(ValueError):
        parse_challenge('Basic realm="x"')


# --- EchoStar SGS variant (the one the receiver actually enforces) ----------

echostar_authorization = digest.echostar_authorization
REALM = "Please provide user name and password"


def test_echostar_matches_rti_algorithm():
    """Reproduces HTTPDigest.js exactly: response + message-digest + format."""
    user, pw = "paireduser", "secretpass"
    nonce = "65e565fb:f0c70dca37ff31a58dc36017fcdbd95c"
    uri = "/www/sgs"
    body = (
        '{"receiver": "XT1aabbccddeeff","key_name": "guide","tv_id": "0",'
        '"stb": "R0000000000-00","command": "remote_key"}'
    )
    cnonce = "0a4f113b"

    ha1 = md5(f"{user}:{REALM}:{pw}")
    ha2 = md5(f"POST:{uri}")
    response = md5(f"{ha1}:{nonce}:00000001:{cnonce}:auth:{ha2}")
    message_digest = md5(f"{ha1}:{nonce}:{md5(body)}")

    header = echostar_authorization(
        user, pw, nonce, body, uri=uri, realm=REALM, cnonce=cnonce
    )
    assert f'response="{response}"' in header
    assert f'message-digest="{message_digest}"' in header


def test_echostar_username_unquoted_qop_unquoted_algorithm_quoted():
    header = echostar_authorization(
        "bob", "pw", "n0nce", "{}", uri="/www/sgs", realm=REALM, cnonce="aabbccdd"
    )
    assert "username=bob," in header  # NOT username="bob"
    assert "qop=auth," in header      # NOT qop="auth"
    assert 'algorithm="MD5"' in header


def test_echostar_field_order():
    header = echostar_authorization(
        "u", "p", "n", "{}", uri="/www/sgs", realm=REALM, cnonce="0"
    )
    order = [
        "username=", "realm=", "nonce=", "uri=", "algorithm=",
        "qop=", "nc=", "cnonce=", "response=", "message-digest=",
    ]
    positions = [header.index(tok) for tok in order]
    assert positions == sorted(positions)


def test_echostar_body_integrity_changes_message_digest():
    a = echostar_authorization("u", "p", "n", '{"a":1}', uri="/www/sgs", realm=REALM, cnonce="0")
    b = echostar_authorization("u", "p", "n", '{"a":2}', uri="/www/sgs", realm=REALM, cnonce="0")
    # Same creds/nonce/cnonce but different body → different message-digest.
    md_a = a.split('message-digest="')[1]
    md_b = b.split('message-digest="')[1]
    assert md_a != md_b
