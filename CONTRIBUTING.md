# Contributing

1. Fork the repo and create a branch.
2. Set up the project as described in "Run from source" in the README.
3. Keep changes modular:
   - Python 3.10+ with docstrings on public functions.
   - TypeScript/Svelte for `ui/`.
   - macOS access only through AppleScript (`osascript`) or the standard library.
4. Before opening a PR, run these checks:
   ```bash
   cd ui && pnpm check && pnpm build
   python3 -m compileall -q api core tools interface config
   ```
5. Never commit `.env`, `ui/.env`, tokens or anything under `data/`.

Report security issues privately to the maintainers. Do not open a public issue for them.
