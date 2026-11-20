# Engineering workflow

- Keep `main` protected. Work on a dedicated branch for each independent change and open a pull request; never push directly to `main` or bypass required checks.
- Wait for CI and fix failures before presenting a PR as ready. Keep PRs open for user review unless merging has been requested. Dependent changes may use stacked PRs with their dependencies stated explicitly.
- Preserve the user's configured Git identity and omit assistant/co-author attribution from commits and PR descriptions.
- Use the existing Mantine dependencies and project design-system references when implementing UI. Support phone, tablet and laptop widths with usable video previews and controls.
- Keep backend/media tests meaningful and temporary. Do not recreate deleted test-review documents or persistent demo/validation videos. Preserve application data.
- Read `web/AGENTS.md` and the relevant installed Next.js guide before changing frontend code.
