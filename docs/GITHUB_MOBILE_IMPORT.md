# Import the prepared branch from a phone

> Recovery-only path. The GitHub App is now installed on the private `Codework` repository and PR
> #2 was created programmatically. Use the steps below only if the repository must be reconstructed
> from an exported source archive.

No GitHub folder needs to be created in advance. Git creates `.github/workflows`, `scripts`, `mcp`, and the other paths when the branch is committed.

## Preferred route: browser Codespace

1. Keep the `Codework` repository private before connecting a genomic VM or storing operational metadata.
2. Open the repository in GitHub, choose **Code → Codespaces → Create codespace on main**. If the menu is hidden on the phone, request the desktop site.
3. In the Codespace file explorer, use **Upload…** and select `codework-genome-runtime-2026-08-15.zip` from the phone.
4. Open the Codespace terminal and run:

```bash
git switch -c codex/genome-runtime-mcp
unzip -o codework-genome-runtime-2026-08-15.zip -d .
chmod 0755 scripts/*.sh scripts/*.py
python3 scripts/validate_repo.py
python3 -m unittest discover -s tests -v
npm ci --prefix mcp --ignore-scripts
npm test --prefix mcp
git status --short
```

5. Inspect the listed files. The ZIP contains no DNA, no GRCh38 payload, no key, no token, and no approved lock.
6. Stage only the prepared scaffold:

```bash
git add -- \
  .dockerignore .fallowrc.json .github .gitignore Dockerfile \
  deploy docs environment.yml main.nf manifests mcp nextflow.config scripts tests
git commit -m "chore: prepare private genomic analysis runtime"
git push -u origin codex/genome-runtime-mcp
```

7. Open the compare page for the current private repository and compare `main...codex/genome-runtime-mcp`.
8. Use the title and text in `docs/PR_BODY.md`, select **Create draft pull request**, and wait for both workflows to finish.
9. Do not merge if Fallow, the repository contract, MCP tests, container build, or synthetic GATK/bcftools canary fails.

## GitHub App access

Open <https://github.com/settings/installations>. Choose **Configure** for the ChatGPT/OpenAI GitHub App. Under **Repository access**, select `Codework` and save. Reauthorizing the user identity alone is not enough: the App must appear as an installation. The App itself must request repository-content and pull-request write permissions; selecting a repository cannot add permissions the App did not request.

If the connector still returns `Unknown tool`, close and start a new ChatGPT conversation after reconnecting. If it returns `403 Resource not accessible by integration`, revisit the app installation and repository selection.

## Actions policy

Open **Repository Settings → Actions → General**. Allow GitHub-authored actions and `fallow-rs/fallow@v3.16.0` (or allow all actions if that policy is acceptable). Keep the default restricted token posture; the workflow grants `packages: write` only to the GHCR publishing job.

Do not add a self-hosted runner to a public repository. Never permit workflows from untrusted forks to execute on the genomic VM.
