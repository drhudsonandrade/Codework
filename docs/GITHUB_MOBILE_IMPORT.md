# GitHub mobile workflow

This project is designed to remain usable from GitHub web/mobile without any external conversational platform.

## Repository

`drhudsonandrade/Codework`

## Template transport path

If a one-time manual upload is ever required, use the branch explicitly named by the active materialization PR and navigate to:

`template_store/v3.0/inbox/`

Then choose **Add file → Upload files** and commit only the file required by the active workflow contract.

Do not upload personal genotype data to the repository.

## Preferred model

The canonical template bytes are already maintained in the sealed template store. Normal operation should materialize from that checksum-locked store rather than depend on a mobile upload.

## Recovery

1. Open the private repository.
2. Confirm the current `main` SHA.
3. Review required checks and workflow results.
4. Never merge a materialization or safety PR before all blocking checks pass.
5. Any code change requires a fresh exact-SHA Production Witness before claiming post-deployment status for that revision.
