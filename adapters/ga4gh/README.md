# GA4GH federation adapter — future-compatible and optional

The four-plane architecture is intentionally compatible with future GA4GH adapters:

- WES: submit/observe portable workflows;
- TES: abstract task execution across cloud/HPC;
- DRS: resolve data objects without coupling scientific logic to a storage vendor.

No GA4GH service is required by the core today. Adding these adapters must preserve the same execution manifest, content hashes and policy gates.
