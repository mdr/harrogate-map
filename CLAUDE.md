See README.md for what this is and how to run it. Agent-specific notes:

- Run Python through the flake (`direnv exec . <cmd>` or `nix develop
  --command <cmd>`); system Python lacks the dependencies.
- The repo is **public** and every push to `main` re-renders and redeploys the
  Pages site. Never commit the home location or anything else personal — it
  comes from 1Password at render time only.
- `op` has both a work and a personal account signed in; always pass
  `--account my.1password.com` for this project. Reads need the user to
  approve a 1Password prompt, so ask them to be present first.
- `gh` may default to a work account. The repo belongs to `mdr`; git pushes go
  over the `github.com-mdr` SSH alias and need no `gh` switch. If you must use
  `gh` against the repo, `gh auth switch -u mdr`, then switch back afterwards.
- Overpass rate-limits heavily; keep `cache/` around and avoid needless
  re-fetches. To check a rendering change, crop the relevant area of
  `map.png` rather than viewing the whole 32 MB image.
