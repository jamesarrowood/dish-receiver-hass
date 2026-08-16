"""Minimal HTTP Digest (RFC 2617 / 7616, qop=auth) client helper.

EchoStar receivers challenge port-80 requests with
`WWW-Authenticate: Digest ... algorithm=MD5, qop=auth`. aiohttp has no built-in
client-side digest, so we compute the Authorization header ourselves. Kept
dependency-free and separately testable.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field

_TOKEN = re.compile(r'(\w+)=(?:"([^"]*)"|([^,]+))')


def _h(algorithm: str, data: str) -> str:
    if algorithm.lower().startswith("sha-256"):
        return hashlib.sha256(data.encode()).hexdigest()
    return hashlib.md5(data.encode()).hexdigest()


def parse_challenge(header: str) -> dict[str, str]:
    """Parse a `WWW-Authenticate: Digest ...` header value into a dict."""
    scheme, _, rest = header.strip().partition(" ")
    if scheme.lower() != "digest":
        raise ValueError(f"not a digest challenge: {header!r}")
    params: dict[str, str] = {}
    for match in _TOKEN.finditer(rest):
        params[match.group(1).lower()] = match.group(2) or match.group(3) or ""
    return params


@dataclass
class DigestAuth:
    """Holds credentials and the nonce-count state across requests."""

    username: str
    password: str
    _nc: int = field(default=0, repr=False)

    def authorization(
        self,
        method: str,
        uri: str,
        challenge: dict[str, str],
        cnonce: str | None = None,
    ) -> str:
        """Build the Authorization header value for one request."""
        realm = challenge.get("realm", "")
        nonce = challenge["nonce"]
        algorithm = challenge.get("algorithm", "MD5")
        qop = challenge.get("qop", "")
        opaque = challenge.get("opaque")

        ha1 = _h(algorithm, f"{self.username}:{realm}:{self.password}")
        ha2 = _h(algorithm, f"{method.upper()}:{uri}")

        parts = [
            f'username="{self.username}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'algorithm={algorithm}',
        ]

        if qop:
            # qop may be a comma list; we only implement "auth".
            self._nc += 1
            nc_value = f"{self._nc:08x}"
            client_nonce = cnonce or os.urandom(8).hex()
            response = _h(
                algorithm,
                f"{ha1}:{nonce}:{nc_value}:{client_nonce}:auth:{ha2}",
            )
            parts.append(f"qop=auth")
            parts.append(f"nc={nc_value}")
            parts.append(f'cnonce="{client_nonce}"')
        else:
            response = _h(algorithm, f"{ha1}:{nonce}:{ha2}")

        parts.append(f'response="{response}"')
        if opaque is not None:
            parts.append(f'opaque="{opaque}"')
        return "Digest " + ", ".join(parts)


def stale_nonce() -> str:
    """A cheap unique cnonce seed when os.urandom is undesirable in a test."""
    return f"{time.time_ns():x}"


_HEX = "abcdef0123456789"


def echostar_cnonce(source: str | None = None) -> str:
    """8-char lowercase-hex cnonce, matching the EchoStar SGS client."""
    if source is not None:
        return source
    return os.urandom(4).hex()


def echostar_authorization(
    username: str,
    password: str,
    nonce: str,
    body: str,
    *,
    uri: str,
    realm: str,
    cnonce: str | None = None,
) -> str:
    """Build the exact `Authorization: Digest` header EchoStar's SGS API wants.

    Verbatim from the RTI driver's HTTPDigest.js. Differences from stock RFC
    2617 that the receiver actually enforces:

    * `username=<value>` is emitted **without** surrounding quotes.
    * `qop=auth` is unquoted; `algorithm="MD5"` is quoted.
    * A non-standard **`message-digest`** field carries body integrity:
      MD5(HA1 : nonce : MD5(body)). The box rejects the request without it.

    Field order is fixed: username, realm, nonce, uri, algorithm, qop, nc,
    cnonce, response, message-digest.
    """
    nc = "00000001"  # the box issues a fresh nonce per request, so nc is always 1
    cnonce = echostar_cnonce(cnonce)

    ha1 = _h("MD5", f"{username}:{realm}:{password}")
    ha2 = _h("MD5", f"POST:{uri}")
    response = _h("MD5", f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")

    body_digest = _h("MD5", body)
    message_digest = _h("MD5", f"{ha1}:{nonce}:{body_digest}")

    return (
        "Digest "
        f"username={username}, "
        f'realm="{realm}", '
        f'nonce="{nonce}", '
        f'uri="{uri}", '
        f'algorithm="MD5", '
        f"qop=auth, "
        f"nc={nc}, "
        f'cnonce="{cnonce}", '
        f'response="{response}", '
        f'message-digest="{message_digest}"'
    )
