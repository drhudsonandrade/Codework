"""Classify what a POST-DEPLOYMENT smoke run actually talked to.

Section 260 of the ruleset asks for the fifteen cases to be run *live* — the clause is held
in this repository as `scripts/bootstrap_attestation.py::BOOTSTRAP_CLAUSES`
["post_deployment_requires_live_15_of_15_zero_critical"]: "executar ao vivo os 15 casos da
seção 260, exigindo 15/15 sem falha crítica". The ceremony workflow satisfied it by starting
a container on the GitHub runner and pointing the smoke at ``127.0.0.1:8787``
(`.github/workflows/genoma-production-ceremony.yml`, the ``docker run -p 127.0.0.1:8787:8787``
step and the ``--base-url http://127.0.0.1:8787`` the smoke is invoked with; the same pair
appears in `genoma-production-witness.yml`).

The run is real — the HTTP requests happen, a real container answers them — but the thing
certified is an ephemeral CI container that ceases to exist when the job ends, while the
witness recorded a fixed string, ``"classification": "live HTTP execution against a real
container instance; not a unit fixture"``, assigned unconditionally in
`scripts/run_live_post_deployment_smoke.py` and therefore identical whichever address had
been dialled. Nothing in the resulting evidence distinguished that from a certification taken
against the host a laboratory will actually send samples to, so POST-DEPLOYMENT: VERIFICADO
on a report meant either one.

Each statement above is a reading of files in this repository at the paths named, not a
record of a deployment: this module makes no claim about what any past ceremony run reached.
What that run reached is exactly what it now has to record.

The distinction is therefore *measured*, not declared. A ``--deployment-kind deployed-host``
flag would be one more self-declared field feeding the gate that reads it — the defect class
this project keeps finding. Instead the base URL the smoke was given is parsed, its host
resolved, and the addresses classified; a run against loopback cannot record anything but
loopback, whatever its operator intended.

`refusal` recomputes the class from the recorded addresses rather than believing the
recorded class, so editing ``"network_class": "public-host"`` into a witness taken against
127.0.0.1 does not survive being read. `tests/test_post_deployment_target_binding.py` pins
both halves: the classification of each address family, and that refusal.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

#: The smoke reached the machine it ran on: a local process or a container on the runner.
LOOPBACK = "loopback"
#: A host on a private, link-local or otherwise non-routable network.
PRIVATE = "private-network"
#: A host at a publicly routable address.
PUBLIC = "public-host"
#: The name was given but resolved to nothing. Kept as a class of its own rather than
#: folded into loopback, because "we could not tell" and "it was local" are different facts.
UNRESOLVED = "unresolved"

NETWORK_CLASSES = (LOOPBACK, PRIVATE, PUBLIC, UNRESOLVED)

#: Classes that certify a service something other than the verifier could reach.
REACHABLE_BEYOND_THIS_MACHINE = (PRIVATE, PUBLIC)

#: Ordered weakest claim first. A name resolving to several addresses is classified by the
#: weakest of them: the smoke connected to one, and which one is not recorded, so the only
#: defensible statement is the one that holds whichever it was.
_RANK = {UNRESOLVED: 0, LOOPBACK: 1, PRIVATE: 2, PUBLIC: 3}

NOTES = {
    LOOPBACK: (
        "o alvo resolve para o próprio host que executou a verificação; certifica um serviço "
        "local ou contêiner efêmero, não uma implantação alcançável por terceiros"
    ),
    PRIVATE: (
        "o alvo resolve para endereço de rede privada; certifica o serviço alcançável de onde "
        "a verificação rodou, e um auditor externo não consegue reencontrar esse endereço"
    ),
    PUBLIC: "o alvo resolve para endereço roteável publicamente",
    UNRESOLVED: "o nome do alvo não resolveu para endereço algum",
}


def _class_of_address(text: str) -> str:
    """Classify one literal address. Loopback is tested first: in `ipaddress`, 127.0.0.1 is
    `is_private` as well as `is_loopback`, and collapsing the two would let the local
    container be recorded as a private-network deployment."""
    address = ipaddress.ip_address(text)
    if address.is_loopback:
        return LOOPBACK
    if address.is_private or address.is_link_local or address.is_reserved or address.is_unspecified:
        return PRIVATE
    return PUBLIC


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return sorted({info[4][0] for info in infos})


def aggregate(addresses: list[str]) -> str:
    """The class of a set of addresses, or UNRESOLVED if there are none or none parse."""
    classes = []
    for text in addresses:
        try:
            classes.append(_class_of_address(text))
        except ValueError:
            continue
    if not classes:
        return UNRESOLVED
    return min(classes, key=lambda name: _RANK[name])


def _authority(scheme: str, host: str, port: int) -> str:
    """Scheme, host and port only: any userinfo in the supplied URL is a credential and is
    dropped rather than written into an artifact that gets published as evidence."""
    shown = f"[{host}]" if ":" in host else host
    return f"{scheme}://{shown}:{port}"


def _split(base_url: str) -> tuple[str, str, int]:
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:  # a non-numeric port in the URL
        port = None
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    return parts.scheme, host, port


def authority(base_url: str) -> str:
    """`scheme://host:port` with no resolution, for comparing two URLs for the same target.

    Two artifacts about "the deployment" have to be shown to be about the *same* deployment
    before one may support the other; string equality on the raw URLs would make a trailing
    slash or a capitalised hostname look like a different service.
    """
    scheme, host, port = _split(base_url)
    return _authority(scheme, host.lower(), port)


def classify(base_url: str) -> dict[str, Any]:
    """Everything the witness should record about the target it was pointed at."""
    parts = urlsplit(base_url)
    _, host, port = _split(base_url)
    addresses = _resolve(host, port) if host else []
    network_class = aggregate(addresses)
    return {
        "authority": _authority(parts.scheme, host.lower(), port),
        "scheme": parts.scheme,
        "host": host,
        "port": port,
        "resolved_addresses": addresses,
        "network_class": network_class,
        "reachable_beyond_this_machine": network_class in REACHABLE_BEYOND_THIS_MACHINE,
        "note": NOTES[network_class],
    }


def refusal(target: Any) -> str | None:
    """Why this target block may not be read as recorded, or None if it may.

    Called by whatever consumes a witness. The recorded class is recomputed from the
    recorded addresses, so a witness cannot claim a target class its own evidence
    contradicts.
    """
    if not isinstance(target, dict):
        return (
            "a testemunha não registra contra qual alvo foi executada; sem isso um contêiner "
            "efêmero de CI e um host implantado produzem exatamente a mesma face PASS"
        )
    declared = target.get("network_class")
    if declared not in NETWORK_CLASSES:
        return (
            f"a testemunha declara a classe de alvo {declared!r}, que não pertence ao "
            f"vocabulário {list(NETWORK_CLASSES)}"
        )
    addresses = target.get("resolved_addresses")
    if not isinstance(addresses, list) or not all(isinstance(item, str) for item in addresses):
        return "a testemunha não registra os endereços para os quais o alvo resolveu"
    recomputed = aggregate(addresses)
    if recomputed != declared:
        return (
            f"a testemunha declara o alvo como {declared!r}, mas os endereços que ela mesma "
            f"registra ({addresses}) classificam como {recomputed!r}"
        )
    # Coherence was the only test here: a witness that honestly recorded 127.0.0.1 and
    # honestly classified it as loopback passed, and certified POST-DEPLOYMENT. But the
    # question a post-deployment witness answers is whether something other than the
    # verifier can reach the service, and loopback and unresolved answer no. The module
    # already computes exactly this as `reachable_beyond_this_machine`; it was recorded in
    # the artifact and never enforced.
    if recomputed not in REACHABLE_BEYOND_THIS_MACHINE:
        return (
            f"a testemunha certifica um alvo {recomputed!r}: {NOTES[recomputed]}. Uma "
            "certificação pós-implantação exige um serviço alcançável além da máquina que "
            "verificou, então este veredicto fica PENDENTE"
        )
    return None


def describe(target: Any) -> str:
    """One clause naming the target, for the sentence a reader consults."""
    if not isinstance(target, dict):
        return "alvo não registrado"
    return f"alvo {target.get('authority')!r} ({target.get('network_class')}: {target.get('note')})"


#: Short enough to sit on the report's identity header, where a reader meets the PASS. The
#: header used to print the bare word, so the strongest claim the project makes carried no
#: hint of whether a laboratory's server or a CI container had been certified.
SHORT = {
    LOOPBACK: "verificado contra serviço local ou contêiner efêmero, não um host implantado",
    PRIVATE: "verificado contra host em rede privada",
    PUBLIC: "verificado contra host implantado em endereço público",
    UNRESOLVED: "alvo não resolvido",
}


def qualifier(target: Any) -> str:
    """The header clause, or an empty string when there is no target to qualify."""
    if not isinstance(target, dict):
        return ""
    label = SHORT.get(target.get("network_class"))
    if not label:
        return ""
    return f"{label} ({target.get('authority')})"
