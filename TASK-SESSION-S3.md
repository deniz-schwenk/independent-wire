# Task: TASKS.md English Rewrite + Repo Cleanup + Quick Fix

**Date:** 2026-04-07
**Context:** Read `SESSION-HANDOFF-2026-04-07-S2.md` for full pipeline state.

---

## Step 1: Commit current state first

Before any changes, commit the current state:

```bash
git add -A && git commit -m "chore: snapshot before session 3 cleanup"
```

---

## Step 2: Rewrite docs/TASKS.md in English

The current `docs/TASKS.md` is partially in German. Rewrite the entire file in English.
Keep the same structure and content but translate all German text to English.

Update the status of ALL work packages based on SESSION-HANDOFF-2026-04-07-S2.md:

### Completed WPs to mark as ✅ Done:
- WP-AGENT, WP-TOOLS (v1-v3), WP-PIPELINE, WP-STRUCTURED-RETRY
- WP-AGENTS, WP-INTEGRATION, WP-RSS, WP-DEBUG-OUTPUT, WP-REASONING
- WP-RESEARCH, WP-PARTIAL-RUN, WP-QA, WP-PERSPEKTIV
- WP-RESEARCHER-SPLIT, WP-BIAS

### Completed fixes to mark as ✅:
- QF-04 (max_tokens 65536)
- QF-08 (output_schema for QA-Analyze)
- All P-01 through P-08
- All F-01 through F-05

### Update Lauf history:
- Add Lauf 7 (2/3 topics, Hormuz crash → triggered WP-RESEARCHER-SPLIT)
- Add Lauf 9 (3/3 topics, 0 failures, 391K tokens, 48 min — first complete run with new architecture)

### Add new upcoming items:
- Feed expansion (WorldMonitor catalog, target 50+ feeds)
- Model evaluation (8 models across 4 agent roles)
- WP-RENDERING (Topic Package → HTML, deferred to next session)

Commit: `docs: rewrite TASKS.md in English with full status update`

---

## Step 3: Repo Cleanup

Add to `.gitignore`:

```
# Internal planning files (not for public repo)
SESSION-HANDOFF-*.md
TASK-*.md
WP-*.md
CLAUDE.md
```

Remove from git tracking (files stay on disk):

```bash
git rm --cached SESSION-HANDOFF-*.md TASK-*.md WP-*.md CLAUDE.md 2>/dev/null
git commit -m "chore: remove internal planning files from git tracking"
```

---

## Step 4: Quick Fix — Researcher Assembler → GLM-5

In `scripts/run.py` (or wherever the researcher_assemble agent is configured):
Change the model to `z-ai/glm-5` (same as researcher_plan).

Do NOT change the bias_detector temperature — keep it at 0.1.

Commit: `fix: researcher assembler model → GLM-5`

---

## What NOT to do
- Do NOT rewrite any agent prompts
- Do NOT change pipeline architecture
- Do NOT add new feeds yet (that's the next step, done together with the architect)
- Do NOT change bias_detector temperature

## Claude Code Prompt

```
Read TASK-SESSION-S3.md and execute Steps 1-4 in order.
Step 1: Commit current state.
Step 2: Rewrite docs/TASKS.md fully in English with updated status from SESSION-HANDOFF-2026-04-07-S2.md.
Step 3: Add internal files to .gitignore and remove from tracking.
Step 4: Change researcher_assemble model to z-ai/glm-5.
Commit after each step with the specified commit message.
```
