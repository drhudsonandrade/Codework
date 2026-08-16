# Cloudflare adapter — optional

Recommended use: Cloudflare Tunnel + Access/WAF in front of the core HTTP service. Keep the GENOMA origin on a private/loopback interface and never make Cloudflare the policy authority or canonical evidence store.

The system must continue to run with this directory deleted. No Cloudflare token, account ID or tunnel credential is committed to Git.
