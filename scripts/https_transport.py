#!/usr/bin/env python3
"""One transport policy for the network fetchers, applied to every hop of a request.

A scheme check on the request the caller built is not a transport policy. `urlopen` installs
an `HTTPRedirectHandler` that follows `Location` without consulting the caller, so an
`https://` request answered with `Location: http://…` is downgraded in silence: the fetcher
has already passed its check, and it accepts the unauthenticated bytes that come back as if
the guard still held. The same handler will move a request to a different host, and
`urlopen` will follow a redirect into `ftp:` as readily as into `https:`.

So the policy has to live where the hops are taken. Each fetcher builds an opener from here
instead of calling `urlopen`, and the predicate it passes is re-applied to the target of
every redirect. A refused hop raises rather than returning the 3xx response: returning
`None` from `redirect_request` makes urllib hand the redirect body back to the caller, which
would look like a successful fetch of a very short document.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Callable


class TransportPolicyError(RuntimeError):
    """A request, or one of its redirect hops, used a transport the caller refuses."""


def is_https(url: str) -> bool:
    """The policy every public-data fetcher applies: HTTPS and nothing else.

    `file:`, `ftp:` and `data:` are all things `urlopen` will open, and a download that
    quietly read the local filesystem would hand a caller bytes it never fetched.
    """
    return urllib.parse.urlparse(url).scheme == "https"


def loopback_http_or_https(url: str) -> bool:
    """HTTPS anywhere, or plain HTTP only against the ceremony's own loopback endpoint.

    The live smoke deliberately dials `http://127.0.0.1:8787`, so HTTP cannot be refused
    outright. It can be confined: `127.0.0.1` is this machine, and a payload sent there
    reaches the service under test rather than a third party. Any other HTTP host — reached
    directly or by redirect — would receive the smoke's request bodies.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.netloc == LOOPBACK_ENDPOINT


#: Host and port the post-deployment ceremony serves on. The one HTTP destination allowed.
LOOPBACK_ENDPOINT = "127.0.0.1:8787"


class PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-applies the caller's transport policy to the target of every redirect."""

    def __init__(self, allow: Callable[[str], bool], what: str) -> None:
        """Take the predicate to enforce and a phrase naming who is enforcing it."""
        super().__init__()
        self._allow = allow
        self._what = what

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Refuse a hop the policy rejects; otherwise defer to urllib's own handling.

        Raising, rather than returning `None`: urllib reads `None` as "do not redirect" and
        returns the 3xx response itself, so the caller would parse a redirect body as the
        document it asked for. Deferring to `super()` for an allowed hop keeps urllib's
        method and header rules — dropping the body on a 303, not carrying credentials
        across hosts — which reimplementing here would silently lose.
        """
        if not self._allow(newurl):
            raise TransportPolicyError(
                f"refusing a redirect to a transport {self._what} does not allow: {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def policy_opener(allow: Callable[[str], bool], what: str) -> urllib.request.OpenerDirector:
    """An opener that enforces `allow` on every redirect hop it follows."""
    return urllib.request.build_opener(PolicyRedirectHandler(allow, what))
