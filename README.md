# Codework```bash
git switch -c codex/genome-runtime-mcp
unzip -o codework-genome-runtime.zip -d .
chmod 0755 scripts/*.sh scripts/*.py
python3 scripts/validate_repo.py
python3 -m unittest discover -s tests -v
npm ci --prefix mcp --ignore-scripts
npm test --prefix mcp
git status --short
```