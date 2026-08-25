# BACKLOG — Test suite hygiene (env-independence broken, local-state dependency)

Diagnosed 2026-08-25 during bias-gate verification. main (`221b6eb`) has 4
failed + 6 errors under the environment-independent invocation
(`env -i HOME=$HOME PATH=$PATH $(which uv) run pytest`). None block the
2026-08-26 production run (daily_run.sh sources .env; DEEPSEEK_API_KEY
present). All pre-exist the bias-gate branch; failure sets verified
byte-identical branch vs main.

## 1. Flash swap broke env-independence (2 failures)
`test_create_agents_hydrated_*` fail because c2cb451 makes
curator_topic_discovery construct with provider=deepseek-direct, and agent
construction raises `ValueError` when DEEPSEEK_API_KEY is unset. Under
`env -i` the key is deliberately absent. Suite was green under `env -i`
before the swap.

Fix direction (CC task, small): tests inject a dummy DEEPSEEK_API_KEY via
monkeypatch/env fixture at create_agents test scope. Do NOT add the real
key to the invocation; do NOT relax construction-time validation (loud
failure at construction is correct for production).

## 2. curator_monitor depends on deleted local snapshot (1 failure)
`test_empty_window_does_not_crash` raises FileNotFoundError:
`output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json`
is gone from disk. Test depends on untracked local state.

Fix direction: either restore/pin a tracked fixture, or skip-if-missing
with a loud reason. Decide whether the pathology baseline is still needed
post-V2 before choosing.

## 3. Social render tests (6 errors + 1 failure)
`tools/social/test_render_card.py` — ModuleNotFound (playwright) after the
deliberate vacation-recovery revert. Expected state until the deterministic
Mac-side auto-render step lands (Hermes workstream). No action here; listed
so the count is accounted for.
