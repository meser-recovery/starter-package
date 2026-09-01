# AGENTS.md — meser-recovery/starter-package

## Project role

This repository is maintained with Codex as an implementation agent.

All architecture decisions, product planning, UX decisions, task decomposition, and technology choices are made outside Codex.

Codex must primarily EXECUTE explicitly defined tasks.

Do not spend tokens on broad planning, alternative architectures, future roadmaps, or unsolicited recommendations unless the task explicitly asks for them.

---

## Core execution rules

For every task:

1. Read the requested scope literally.
2. Inspect only the repository areas needed to perform the task safely.
3. Implement the requested changes.
4. Preserve unrelated behavior.
5. Run appropriate validation.
6. Fix failures introduced by the changes.
7. Report exactly what was changed and validated.

Prefer the smallest implementation that fully satisfies the task.

If the requested implementation is genuinely impossible or unsafe, stop before making speculative changes and report the blocker precisely.

---

## Scope discipline

Do NOT:

* redesign the architecture unless explicitly instructed;
* expand the scope beyond the requested task;
* introduce frameworks, services, infrastructure, build systems, or dependencies unless explicitly requested;
* refactor unrelated code;
* rename existing public URLs unless explicitly requested;
* remove functionality because it appears unused or obsolete;
* change GitHub Pages configuration unless explicitly requested;
* modify organization settings, repository ownership, secrets, credentials, or billing;
* modify external services unless explicitly requested;
* expose tokens, passwords, credentials, or secrets in source code;
* commit secrets;
* perform production mutations that are not explicitly part of the task.

When uncertain between a narrow change and a broader cleanup, choose the narrow change.

---

## Current project direction

The repository is a lightweight static website hosted on GitHub Pages.

The site is being gradually migrated away from Nicepage-generated code toward a maintainable static frontend.

Target characteristics:

* GitHub Pages remains the hosting platform.
* Existing public URLs should be preserved whenever possible.
* Frontend should remain lightweight.
* Preferred frontend stack:

  * semantic HTML;
  * CSS;
  * vanilla JavaScript.
* Avoid unnecessary frontend frameworks.
* Nicepage and jQuery are to be removed progressively as pages are migrated.
* Do not reintroduce Nicepage dependencies after they have been removed.
* Existing content and functionality must be preserved during UI migration unless the task explicitly changes them.
* Mobile usability and accessibility are priorities.
* Keep dependency count low.
* Prefer simple, transparent code over abstraction for its own sake.

Do NOT introduce React, Next.js, Vite, Astro, Vue, Angular, or another frontend framework unless explicitly instructed.

---

## Existing functionality

The repository contains existing static pages and assets, including:

* the public landing page;
* literature pages;
* meetings pages;
* audiobook functionality;
* calculator functionality;
* service/admin pages;
* existing audio assets;
* Python-based generation of meeting data/pages;
* GitHub Actions automation.

The existing Python meeting-generation workflow is independent from the UI modernization.

Do not change:

* `build_na_html.py`;
* the existing scheduled GitHub Actions workflow;
* generated meeting behavior;

unless the current task explicitly concerns them.

---

## Audio functionality

Future tasks may add:

* audio silence processing;
* an audio archive;
* GitHub Releases-based storage;
* upload/download functionality.

Do not implement any of these merely because they are mentioned here.

Implement only the audio functionality explicitly requested in the current task.

Do not store large working audio files directly in normal Git history unless explicitly instructed.

---

## Git workflow

Unless the task explicitly says otherwise:

* work on a dedicated feature branch;
* never commit directly to `main`;
* keep changes scoped to the current task;
* use clear commit messages;
* do not merge automatically;
* do not delete branches automatically;
* leave the working tree clean when finished.

If a task explicitly instructs you to create, merge, or clean up a pull request, follow those instructions only after required validation passes.

Do not rewrite unrelated Git history.

---

## Validation

Use the smallest meaningful validation set for the task.

For frontend changes, validate as applicable:

* HTML structure;
* JavaScript syntax;
* referenced local assets;
* relative links affected by the change;
* browser-visible functionality affected by the change;
* responsive behavior when layout is modified;
* obvious accessibility regressions.

For Python or workflow changes, run the relevant existing checks or scripts without causing unintended production mutations.

Do not claim a test or validation was performed unless it was actually run.

If a useful check cannot be run, state that explicitly.

---

## Preservation rules

Unless explicitly instructed otherwise, preserve:

* public page URLs;
* page content;
* user-facing functionality;
* existing audio files;
* existing generated meeting data;
* existing GitHub Pages behavior;
* existing automation unrelated to the task.

Visual modernization does not imply permission to change content or functionality.

---

## Dependency policy

Before adding a dependency, verify that the task actually requires it.

Prefer:

1. browser-native APIs;
2. existing project dependencies;
3. small self-contained libraries;
4. new framework-level dependencies only when explicitly requested.

Do not introduce a package manager or build pipeline merely for convenience.

---

## Security

Never place credentials or write-capable GitHub tokens in public frontend code.

Never assume a client-side password gate is a real security boundary.

Any operation requiring privileged credentials must keep those credentials outside publicly served repository files.

Do not weaken existing security controls without explicit instruction.

---

## Task instructions take priority

Each Codex task may contain explicit sections such as:

* MODEL
* REASONING
* TASK
* REQUIRED CHANGES
* DO NOT
* VALIDATION
* GIT

Follow those task-specific instructions precisely.

The model and reasoning depth are chosen outside Codex.

Do not broaden the task because a stronger model or higher reasoning level was selected.

---

## Completion report

At the end of each task, report concisely:

1. Branch name.
2. Files changed.
3. What was implemented.
4. Validation performed and results.
5. Commit SHA(s), if commits were created.
6. Pull request number/status, if applicable.
7. Any blocker or limitation directly relevant to the requested task.

Do not append a new roadmap, future plan, architectural recommendations, or unrelated improvement suggestions unless explicitly requested.

---

## Governing principle

**Planning outside Codex. Execution inside Codex.**
