# One-shot private template transport — v3.1

Upload exactly `GENOMA_REPORT_TEMPLATES_v3.1_DETERMINISTIC.zip` to this directory on the v3.4 hardening branch.

Required SHA-256: `9ea777466fd9f8823c67f862e73d11bca5bf13c58765da4ef4d9bd4d08bb7776`.

The package contains exactly the 11 v3.1 PDF models identified by `template_store/v3.1/MANIFEST.json`. No personal genotype or case data may be placed here.

The transport is one-shot. Installation must verify ZIP hash, exact member set, PDF header, byte size, per-file SHA-256, page count and forbidden provider terms before committing physical PDFs. A failed check must exit non-zero and leave the active template store unchanged.
