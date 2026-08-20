# Ingress adapter — optional

Recommended use: a reverse tunnel plus an access proxy and WAF in front of the core HTTP
service. Keep the GENOMA origin on a private or loopback interface, and never let the ingress
layer become the policy authority or the canonical evidence store.

The system must continue to run with this directory deleted. No tunnel token, account
identifier or credential of any provider is committed to Git.

Any provider that terminates TLS and forwards to a private origin satisfies this contract.
The choice is an operational one and is deliberately not named here: naming a supplier in the
architecture invites the assumption that the core depends on it, and it does not.
