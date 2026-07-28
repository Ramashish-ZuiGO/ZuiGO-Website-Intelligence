# Presentation Readiness Checklist

## Environment

- [ ] The current branch is `task-030-presentation-mode`.
- [ ] No secrets, local environment files, generated reports, or downloaded
      exports are staged.
- [ ] PostgreSQL, Redis, API, worker, and web containers are running.
- [ ] API health responds successfully and the worker remains available.
- [ ] `celery inspect ping` returns `pong` from the worker.
- [ ] The web production build has completed successfully.
- [ ] The browser can open `http://localhost:3000/presentation`.
- [ ] The presenter display uses a common laptop resolution (at least 1366×768).
- [ ] Browser zoom is set so the controls and stage flow are visible (normally
      90–100%).
- [ ] Desktop, browser, chat, and calendar notifications are disabled.

## Prepared evidence

- [ ] **Open Prepared Demo Report** succeeds without a public network call.
- [ ] The identity is `ZuiGO Demo Website` at `https://demo.local/`.
- [ ] Overall score is `76/100`; confidence is separately labelled `88%`.
- [ ] Coverage is shown explicitly as `15/16 (93.75%)`.
- [ ] Exactly eight agents appear with statuses and contributions.
- [ ] The performance section labels CrUX field evidence unavailable.
- [ ] Top findings contain page URLs and evidence states.
- [ ] The Action Plan contains owner, priority, and verification.
- [ ] HTML, PDF, and JSON downloads have safe filenames and checksums.
- [ ] The presentation PDF contains exactly 15 pages and never exceeds 20.
- [ ] The Technical Appendix is separate from the presentation PDF.
- [ ] Page Inventory JSON contains all 12 discovered URL states.
- [ ] Chromium, Firefox, and WebKit are labelled as Playwright browser engines.
- [ ] Desktop 1440 x 900 and mobile 390 x 844 coverage is explicit.
- [ ] The compatibility matrix includes Pass, Partial, Fail, Not tested, and
      Inconclusive labels without unsupported branded-browser claims.
- [ ] A verified backup PDF is available locally without requiring internet
      access.

## Live presentation flow

- [ ] **Reset Demo** clears only the managed presentation project.
- [ ] **Run Demo Analysis** shows all six stages.
- [ ] Performance, accessibility, and site diagnostics are visibly parallel.
- [ ] The completed result automatically opens the report viewer.
- [ ] Keyboard focus is visible on actions, navigation, and downloads.
- [ ] Status and errors are announced through a live region and are not
      communicated by colour alone.
- [ ] Repeating the same run safely reuses its execution and report.

## Failure rehearsal

- [ ] A failed live execution remains `failed` in persistence.
- [ ] The last verified report is labelled **Prepared fallback report**.
- [ ] The fallback message does not claim that the failed execution completed.
- [ ] If both live and prepared data are unavailable, the screen shows a safe
      error and no score, coverage, or clean-result claim.

## Product assertions

- [ ] All demonstration evidence is described as synthetic and local.
- [ ] No public crawl, public API, remote model, embedding, or LLM is used.
- [ ] Overall Score Formula remains version `1.0.0`.
- [ ] Priority Formula remains version `1.0.0`.
- [ ] Automated accessibility checks are not presented as full compliance.
- [ ] Laboratory and field performance remain distinct.
- [ ] No untested browser support or actual indexing claim is made.

## After the presentation

- [ ] Select **Reset Demo** if the local prepared history is no longer needed.
- [ ] Remove any downloaded exports from the presenter machine as appropriate.
- [ ] Confirm Git status contains no generated report or environment files.
- [ ] Complete one final timed rehearsal using this checklist and the demo
      script.
