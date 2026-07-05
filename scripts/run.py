#!/usr/bin/env python3
"""Independent Wire — Run the daily pipeline."""

import argparse
import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path

# Repo root for resolving paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.bias_composite import BiasComposite
from src.editor_fallback import EditorWithFallback
from src.hydration_phase2_fallback import HydrationPhase2WithFallback
from src.perspective_fallback import PerspectiveWithFallback
from src.qa_fallback import QaAnalyzeWithFallback
from src.writer_fallback import WriterWithFallback
from src.runner.runner import PipelineRunner
from src.runner.stage_lists import (
    build_hydrated_stages,
    build_production_stages,
    hydrated_stage_names,
    production_stage_names,
)
from src.schemas import (
    BIAS_CANDIDATES_SCHEMA,
    BIAS_JUDGE_SCHEMA,
    CLUSTER_ASSIGNMENT_SCHEMA,
    CONSOLIDATOR_SCHEMA,
    CURATOR_TOPIC_DISCOVERY_SCHEMA,
    EDITOR_SCHEMA,
    HYDRATION_PHASE1_SCHEMA,
    HYDRATION_PHASE2_SCHEMA,
    PERSPECTIVE_SCHEMA,
    QA_ANALYZE_SCHEMA,
    RESEARCHER_ASSEMBLE_SCHEMA,
    RESEARCHER_PLAN_SCHEMA,
    RESOLVE_ACTOR_ALIASES_SCHEMA,
    WRITER_SCHEMA,
)
from src.tools import web_search_tool


# --- DeepSeek fp8 quantization pin (TASK-DEEPSEEK-FP8-PIN) --------------------
# fp4 quantization causes fabrications in DeepSeek V4 (QA-stage eval;
# docs/DEEPSEEK-FP8-PIN-2026-07.md). Unpinned, OpenRouter routes these 5 stages
# freely — including to fp4 providers (DeepInfra, AtlasCloud). Each pin below
# restricts routing to the providers empirically verified on 2026-07-02 to serve
# fp8 WITH working strict structured outputs (forced single-provider test calls;
# see the decision record). Routing is guaranteed fp8 by construction (both the
# `/fp8` endpoint tags and the `quantizations` filter) and fails LOUD
# (`allow_fallbacks=False` → stage error) rather than silently dropping to an
# unknown/fp4 quantization. `order` is priority order; `require_parameters=True`
# is added per-request by Agent for schema calls. Regenerate the verified lists
# before adding providers — do not hand-edit toward unverified endpoints.
DEEPSEEK_V4_PRO_FP8_ROUTING = {
    "order": ["baidu/fp8", "wandb/fp8", "parasail/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}
DEEPSEEK_V4_FLASH_FP8_ROUTING = {
    "order": ["baidu/fp8", "wandb/fp8", "streamlake/fp8", "parasail/fp8", "akashml/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}

# --- GLM-5.2 fp8 pin for qa_analyze (TASK-QA-SWAP-GLM) ------------------------
# The QA shadow eval (docs/QA-STAGE-MODEL-EVAL-SHADOW-BACKFILL.md v2) made
# GLM-5.2 @ xhigh the qa_analyze model; the provider verification
# (docs/GLM-PROVIDER-VERIFICATION-2026-07.md) established which fp8 providers
# serve it with working strict structured outputs and enough completion-budget
# headroom for xhigh reasoning (>= the 120000 floor). Order is priority:
# Baidu (primary), Ambient (leanest), Venice (lean; transient upstream 429s).
# StreamLake was capability-verified but excluded operationally (~89k xhigh
# reasoning tokens on a trivial input → truncates real inputs); GMICloud and
# Novita failed strict-schema. ``allow_fallbacks:false`` + ``quantizations:
# ["fp8"]`` fail LOUD rather than dropping to an unverified/fp4 provider.
# All three pins accept max_tokens=120000 (verified caps: Baidu 131072,
# Ambient 202752, Venice 131072).
GLM_5_2_QA_FP8_ROUTING = {
    "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}

# --- GLM-5.2 fp8 pin for writer (TASK-WRITER-SWAP-GLM) -----------------------
# The writer eval (docs/WRITER-STAGE-MODEL-EVAL-2026-07.md, FINAL section) ran
# GLM-5.2 @ xhigh under exactly this pin — the same three fp8 providers verified
# for GLM strict structured outputs with >= the 120000 completion-budget floor
# (docs/GLM-PROVIDER-VERIFICATION-2026-07.md). Same value as the qa pin today;
# kept as a separate named constant so the two stages can diverge independently.
# ``allow_fallbacks:false`` + ``quantizations:["fp8"]`` fail LOUD rather than
# dropping to an unverified/fp4 provider.
GLM_5_2_WRITER_FP8_ROUTING = {
    "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}

# Editor GLM-5.2 fp8 pin (TASK-EDITOR-SWAP-GLM). Same three providers as the
# writer/QA pins — all re-probed under EDITOR_SCHEMA in the eval — but named
# separately so a per-stage divergence never requires editing another stage's
# routing.
GLM_5_2_EDITOR_FP8_ROUTING = {
    "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}

# Hydration-Phase-2 GLM-5.2 fp8 pin (TASK-HYDRATION-P2-GLM-SWAP). Same three fp8
# providers verified for the editor/qa/writer swaps
# (docs/GLM-PROVIDER-VERIFICATION-2026-07.md) and the exact pin the phase-2 eval
# arm ran under (docs/HYDRATION-P2-MODEL-EVAL-2026-07.md). Named separately so a
# per-stage divergence never requires editing another stage's routing.
# ``allow_fallbacks:false`` + ``quantizations:["fp8"]`` fail LOUD rather than
# dropping to an unverified/fp4 provider.
GLM_5_2_HYDRATION_P2_FP8_ROUTING = {
    "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
    "allow_fallbacks": False,
    "quantizations": ["fp8"],
}


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_agents() -> dict[str, Agent]:
    """Create all pipeline agents with their configurations.

    As of 2026-05-19, the non-hydrated path is legacy. The hydrated
    pipeline (``--hydrated`` flag) is canonical for daily production.
    The base agent configs below are inherited by
    :func:`create_agents_hydrated` and are the production source of truth.

    Models via OpenRouter (eval-validated, April 2026; Researcher Plan promoted
    to Opus 4.6 in Researcher-Polish iter 1, May 2026; Researcher Assemble
    migrated to DeepSeek V4 Flash per Wave-1 Sweep #3, 2026-05-18; Curator
    Topic Discovery + Resolve Actor Aliases migrated to DeepSeek V4 Flash
    per Wave-2 + variance smoke, 2026-05-19):
    - google/gemini-3-flash-preview: (no production agents currently)
    - deepseek/deepseek-v4-flash: Curator Topic Discovery (reasoning=medium), Researcher Assemble (reasoning=none), Resolve Actor Aliases (reasoning=none)
    - anthropic/claude-opus-4.6: Editor, Researcher Plan, Perspective, Writer, Bias Language (reasoning=none)
    - anthropic/claude-sonnet-4.6: QA-Analyze (reasoning=none, NEVER use r-medium)
    """
    agents_dir = ROOT / "agents"

    return {
        # DISABLED: Collector deactivated — RSS feeds provide sufficient coverage.
        # Reactivate when scaling to 200+ feeds as pre-filter for the Curator.
        # "collector_plan": Agent(
        #     name="collector_plan",
        #     model="z-ai/glm-5",
        #     system_prompt_path=str(agents_dir / "collector" / "PLAN-SYSTEM.md"),
        #     instructions_path=str(agents_dir / "collector" / "PLAN-INSTRUCTIONS.md"),
        #     tools=[],
        #     temperature=0.5,
        #     provider="openrouter",
        # ),
        # "collector_assemble": Agent(
        #     name="collector_assemble",
        #     model="minimax/minimax-m2.7",
        #     system_prompt_path=str(agents_dir / "collector" / "ASSEMBLE-SYSTEM.md"),
        #     instructions_path=str(agents_dir / "collector" / "ASSEMBLE-INSTRUCTIONS.md"),
        #     tools=[],
        #     temperature=0.2,
        #     provider="openrouter",
        # ),
        # Triple-stage Curator — Brief 5 cutover removed the legacy
        # single-pass "curator" agent. "curator_topic_discovery" is
        # the only Curator-side LLM in the new architecture; the
        # gravitational-assign and assemble stages are deterministic
        # Python and need no agent.
        # DeepSeek V4 Flash per Wave-2 + curator-variance smoke 2026-05-19 — see
        # docs/curator-variance-2026-05-19/curator-variance-report.md.
        # Variant dskflash-t05-rmedium: zero emission-count variance
        # (25.0 ± 0.0), zero duplicates across 3 reps. max_tokens=160k per
        # architect's Wave-2 DeepSeek uniform setting.
        "curator_topic_discovery": Agent(
            name="curator_topic_discovery",
            model="deepseek/deepseek-v4-flash",
            system_prompt_path=str(agents_dir / "curator" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "curator" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            provider="openrouter",
            reasoning="medium",
            max_tokens=160000,
            provider_routing=DEEPSEEK_V4_FLASH_FP8_ROUTING,
            output_schema=CURATOR_TOPIC_DISCOVERY_SCHEMA,
        ),
        # Hypothesis 2 LLM-based cluster→topic assignment — TASK-CLUSTER-
        # LLM-ASSIGNMENT. Not wired into build_production_stages /
        # build_hydrated_stages; only the opt-in
        # build_production_stages_llm_assignment() constructor uses it.
        # Temperature 1.0 by architect's choice — the cluster-to-topic
        # judgement benefits from full reasoning latitude; the prompt's
        # conservative borderline rule absorbs the spread. max_tokens
        # cushion for ~200 entries × ~30 tokens ≈ 6K plus reasoning room.
        "assign_clusters": Agent(
            name="assign_clusters",
            model="google/gemini-3-flash-preview",
            system_prompt_path=str(agents_dir / "assign_clusters" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "assign_clusters" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=1.0,
            max_tokens=8000,
            provider="openrouter",
            reasoning="none",
            output_schema=CLUSTER_ASSIGNMENT_SCHEMA,
        ),
        # editor — swapped to GLM-5.2 @ xhigh (TASK-EDITOR-SWAP-GLM). The
        # editor-stage eval made this operating point binding (GLM won the blind
        # Architect tally 13/20 and is the cheapest arm — docs/EDITOR-STAGE-MODEL-
        # EVAL-2026-07.md, FINAL). GLM is retry-fragile under the strict
        # EDITOR_SCHEMA at xhigh (55% first-attempt valid, 22/22 after retries),
        # and the editor runs once per day with no native fallback, so it is
        # wrapped in EditorWithFallback: primary GLM-5.2 (fp8-pinned), and exactly
        # one Sonnet-5 fallback if GLM finally fails (transport across all pinned
        # providers, or a schema-invalid/structured=None output) — loud, never
        # silent (model_used/provider_used/editor_fallback_used in
        # run_stage_log.jsonl). Sonnet-5 was the eval's 22/22 first-attempt arm
        # and editorial #2 — a validated known-good safety net.
        #
        # ROLLBACK (single-edit revert to the pre-swap production editor):
        #   "editor": Agent(
        #       name="editor", model="anthropic/claude-opus-4.6",
        #       system_prompt_path=str(agents_dir / "editor" / "SYSTEM.md"),
        #       instructions_path=str(agents_dir / "editor" / "INSTRUCTIONS.md"),
        #       tools=[], temperature=0.3, provider="openrouter",
        #       reasoning="none", output_schema=EDITOR_SCHEMA),
        "editor": EditorWithFallback(
            primary=Agent(
                name="editor",
                model="z-ai/glm-5.2",
                system_prompt_path=str(agents_dir / "editor" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "editor" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=0.3,
                max_tokens=120000,
                provider="openrouter",
                reasoning="xhigh",
                provider_routing=GLM_5_2_EDITOR_FP8_ROUTING,
                output_schema=EDITOR_SCHEMA,
            ),
            # 4th line of defence. Sonnet-5 (Claude 5 family): adaptive thinking
            # via reasoning {enabled:true, effort:high} — the eval's exact 22/22
            # first-attempt operating point — and NO temperature (the 5 family
            # 400s on any non-default temperature). Deliberately Sonnet-5, not
            # the pre-swap Opus-4.6 incumbent: Sonnet-5 is the validated
            # known-good reliability net for this stage.
            fallback=Agent(
                name="editor_fallback",
                model="anthropic/claude-sonnet-5",
                system_prompt_path=str(agents_dir / "editor" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "editor" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=None,
                max_tokens=64000,
                provider="openrouter",
                reasoning={"enabled": True, "effort": "high"},
                output_schema=EDITOR_SCHEMA,
            ),
            output_schema=EDITOR_SCHEMA,
        ),
        "researcher_plan": Agent(
            name="researcher_plan",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "researcher" / "PLAN-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher" / "PLAN-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            provider="openrouter",
            reasoning="none",
            output_schema=RESEARCHER_PLAN_SCHEMA,
        ),
        # Researcher Assemble: DeepSeek V4 Flash per Wave-1 Sweep #3 — see docs/cost-efficiency-sweep-2026-05-18/researcher_assemble-report.md.
        # max_tokens raised from 16k → 160k 2026-05-19 to align with Wave-2 uniform DeepSeek setting.
        "researcher_assemble": Agent(
            name="researcher_assemble",
            model="deepseek/deepseek-v4-flash",
            system_prompt_path=str(agents_dir / "researcher" / "ASSEMBLE-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher" / "ASSEMBLE-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            max_tokens=160000,
            provider="openrouter",
            reasoning="none",
            provider_routing=DEEPSEEK_V4_FLASH_FP8_ROUTING,
            output_schema=RESEARCHER_ASSEMBLE_SCHEMA,
        ),
        # DeepSeek V4 Flash per Wave-2 Sweep #2 (2026-05-18) — see
        # docs/cost-efficiency-sweep-wave-2-2026-05-18/resolve_actor_aliases-report.md.
        # Matches/exceeds baseline on alias pairs, 0 uncovered input IDs across
        # 3 topics, 10-15× cheaper. reasoning lowered from medium → none
        # (Wave-2 showed extraction-class doesn't benefit from reasoning on
        # this role). max_tokens=160k per architect's Wave-2 DeepSeek uniform
        # setting.
        "resolve_actor_aliases": Agent(
            name="resolve_actor_aliases",
            model="deepseek/deepseek-v4-flash",
            system_prompt_path=str(agents_dir / "resolve_actor_aliases" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "resolve_actor_aliases" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            max_tokens=160000,
            provider="openrouter",
            reasoning="none",
            provider_routing=DEEPSEEK_V4_FLASH_FP8_ROUTING,
            output_schema=RESOLVE_ACTOR_ALIASES_SCHEMA,
        ),
        # perspective — swapped to Sonnet-5 (TASK-PERSPECTIVE-SWAP-SONNET5). The
        # blind 5-arm eval made this operating point binding
        # (docs/PERSPECTIVE-STAGE-MODEL-EVAL-2026-07.md): Sonnet-5 beats the
        # incumbent Opus-4.6 19–2, matches the golden ceiling on the
        # product-core criteria (R1 0.98 / R5 0.84 / R9 0.95), emits the fewest
        # confirmed invented positions (2 vs incumbent's 5), and is fully
        # reliable 21/21. BOTH open-weight candidates (GLM-5.2, DeepSeek)
        # regressed BELOW the incumbent on this stage — the opposite of the
        # writer/QA evals — so this is a pure quality call.
        #
        # Operating point (the ONE documented config deviation): the Claude
        # 5-family REJECTS non-default temperature/top_p (400), so the
        # production temperature 0.1 cannot carry over — temperature is omitted
        # (temperature=None) and reasoning is the explicit block
        # {enabled, effort:"high"}, max_tokens 64000. Anthropic-served, so no
        # provider pin (served provider still recorded per call). Prompts +
        # PERSPECTIVE_SCHEMA unchanged; downstream deterministic enrichment
        # (enrich_perspective_clusters) is untouched by the unchanged schema.
        #
        # Wrapped in PerspectiveWithFallback: primary Sonnet-5, and exactly ONE
        # fallback attempt if Sonnet-5 finally fails (transport after retries,
        # OR schema-invalid/truncated output). The fallback is the PRE-SWAP
        # incumbent VERBATIM (Opus 4.6, temperature 0.1, reasoning=none, default
        # max_tokens 32000) — a validated known-good safety net. Loud, never
        # silent (model_used/provider_used/perspective_fallback_used in
        # run_stage_log.jsonl).
        #
        # ROLLBACK (single-edit revert to the pre-swap production perspective):
        #   "perspective": Agent(
        #       name="perspective", model="anthropic/claude-opus-4.6",
        #       system_prompt_path=str(agents_dir / "perspective" / "SYSTEM.md"),
        #       instructions_path=str(agents_dir / "perspective" / "INSTRUCTIONS.md"),
        #       tools=[], temperature=0.1, provider="openrouter",
        #       reasoning="none", output_schema=PERSPECTIVE_SCHEMA),
        "perspective": PerspectiveWithFallback(
            primary=Agent(
                name="perspective",
                model="anthropic/claude-sonnet-5",
                system_prompt_path=str(agents_dir / "perspective" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "perspective" / "INSTRUCTIONS.md"),
                tools=[],
                # 5-family rejects non-default temperature → omit it entirely.
                temperature=None,
                max_tokens=64000,
                provider="openrouter",
                reasoning={"enabled": True, "effort": "high"},
                output_schema=PERSPECTIVE_SCHEMA,
            ),
            # Safety net — the PRE-SWAP production perspective VERBATIM: Opus 4.6,
            # temperature 0.1, reasoning="none", the current default max_tokens
            # (32000, unset on the pre-swap entry), same prompts +
            # PERSPECTIVE_SCHEMA. Only the name differs (for log/metric clarity).
            fallback=Agent(
                name="perspective_fallback",
                model="anthropic/claude-opus-4.6",
                system_prompt_path=str(agents_dir / "perspective" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "perspective" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=0.1,
                provider="openrouter",
                reasoning="none",
                output_schema=PERSPECTIVE_SCHEMA,
            ),
            output_schema=PERSPECTIVE_SCHEMA,
        ),
        # writer — swapped to GLM-5.2 @ xhigh (TASK-WRITER-SWAP-GLM). The
        # authoritative full-21 eval (docs/WRITER-STAGE-MODEL-EVAL-2026-07.md,
        # FINAL section) made this operating point binding: GLM leads pooled
        # correctness (3.75 vs incumbent 3.30) and rubric, is deterministically
        # clean 21/21 (0 invented/phantom/orphan ids), and is the cheapest arm
        # (~$0.049/topic). Wrapped in WriterWithFallback: primary GLM-5.2
        # (fp8-pinned), and exactly ONE fallback attempt if GLM finally fails
        # (transport across all pinned providers after retries, OR schema-
        # invalid/truncated output) — loud, never silent.
        #
        # Deliberate difference from qa_analyze: the writer fallback is the
        # PRE-SWAP incumbent (Opus 4.6, reasoning=none), NOT Sonnet-5. Sonnet-5's
        # citation hygiene proved unstable twice in the eval (empty sources[]
        # with inline cites on 1/3 of the completion window), so it is not a safe
        # last resort for the writer.
        #
        # ROLLBACK (single revert): replace this whole entry with the incumbent
        #   "writer": Agent(
        #       name="writer", model="anthropic/claude-opus-4.6",
        #       system_prompt_path=str(agents_dir / "writer" / "SYSTEM.md"),
        #       instructions_path=str(agents_dir / "writer" / "INSTRUCTIONS.md"),
        #       tools=[], temperature=0.3, provider="openrouter",
        #       reasoning="none", output_schema=WRITER_SCHEMA),
        "writer": WriterWithFallback(
            primary=Agent(
                name="writer",
                model="z-ai/glm-5.2",
                system_prompt_path=str(agents_dir / "writer" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "writer" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=0.3,
                max_tokens=120000,
                provider="openrouter",
                reasoning="xhigh",
                provider_routing=GLM_5_2_WRITER_FP8_ROUTING,
                output_schema=WRITER_SCHEMA,
            ),
            # 4th line of defence — the PRE-SWAP production writer VERBATIM:
            # Opus 4.6, temperature 0.3, reasoning="none", the current default
            # max_tokens (32000, unset on the pre-swap entry), same prompts +
            # WRITER_SCHEMA. Only the name differs (for log/metric clarity).
            fallback=Agent(
                name="writer_fallback",
                model="anthropic/claude-opus-4.6",
                system_prompt_path=str(agents_dir / "writer" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "writer" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=0.3,
                provider="openrouter",
                reasoning="none",
                output_schema=WRITER_SCHEMA,
            ),
            output_schema=WRITER_SCHEMA,
        ),
        # qa_analyze — swapped to GLM-5.2 @ xhigh (TASK-QA-SWAP-GLM). The
        # shadow eval made this operating point binding (GLM beats the
        # incumbent 19/21, 1 vs 11 confirmed fabrications, plays at the golden
        # ceiling — docs/QA-STAGE-MODEL-EVAL-SHADOW-BACKFILL.md v2). Wrapped in
        # QaAnalyzeWithFallback: primary GLM-5.2 (fp8-pinned), and exactly one
        # Sonnet-5 fallback if GLM finally fails (transport across all pinned
        # providers, or schema-invalid/truncated output) — loud, never silent.
        #
        # ROLLBACK (single revert): replace this whole entry with the incumbent
        #   "qa_analyze": Agent(
        #       name="qa_analyze", model="anthropic/claude-sonnet-4.6",
        #       system_prompt_path=..., instructions_path=..., tools=[],
        #       temperature=0.1, max_tokens=64000, provider="openrouter",
        #       reasoning="none", output_schema=QA_ANALYZE_SCHEMA),
        "qa_analyze": QaAnalyzeWithFallback(
            primary=Agent(
                name="qa_analyze",
                model="z-ai/glm-5.2",
                system_prompt_path=str(agents_dir / "qa_analyze" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "qa_analyze" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=0.1,
                max_tokens=120000,
                provider="openrouter",
                reasoning="xhigh",
                provider_routing=GLM_5_2_QA_FP8_ROUTING,
                output_schema=QA_ANALYZE_SCHEMA,
            ),
            # 4th line of defence. Sonnet-5 (Claude 5 family): adaptive thinking
            # via reasoning.enabled=true (effort:none would be a no-op), and NO
            # temperature — the 4.7/5 family 400s on any non-default temperature.
            fallback=Agent(
                name="qa_analyze_fallback",
                model="anthropic/claude-sonnet-5",
                system_prompt_path=str(agents_dir / "qa_analyze" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "qa_analyze" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=None,
                max_tokens=64000,
                provider="openrouter",
                reasoning={"enabled": True},
                output_schema=QA_ANALYZE_SCHEMA,
            ),
            output_schema=QA_ANALYZE_SCHEMA,
        ),
        # bias_language — extract -> union -> judge composite (TASK-BIAS-STAGE-SPLIT).
        # Replaces the single-call bias_detector agent, whose emit-then-retract
        # verdict reproduced only ~51% of its spans cross-run
        # (docs/BIAS-STAGE-MODEL-EVAL-2026-07.md). The composite presents itself
        # as a single agent (same output shape) so BiasLanguageStage + every
        # downstream consumer are untouched. ROLLBACK = revert this commit (the
        # single-call Agent above + agents/bias_detector/ prompts return together).
        #   Phase A: deepseek-v4-pro, reasoning=none (the xhigh structured=None
        #     pathology does not apply at none — 5 prod stages prove it daily),
        #     temperature 0.8 both passes (natural variance = coverage), fp8 pin
        #     [baidu, wandb, parasail], default max_tokens.
        #   Phase B: opus-4.6, temp 0.1, reasoning=none, closed per-candidate
        #     judgment (BIAS_JUDGE_SCHEMA field order is load-bearing).
        "bias_language": BiasComposite(
            extractor=Agent(
                name="bias_candidate_extractor",
                model="deepseek/deepseek-v4-pro",
                system_prompt_path=str(
                    agents_dir / "bias_candidate_extractor" / "SYSTEM.md"),
                instructions_path=str(
                    agents_dir / "bias_candidate_extractor" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=0.8,
                provider="openrouter",
                reasoning="none",
                provider_routing=DEEPSEEK_V4_PRO_FP8_ROUTING,
                output_schema=BIAS_CANDIDATES_SCHEMA,
            ),
            judge=Agent(
                name="bias_judge",
                model="anthropic/claude-opus-4.6",
                system_prompt_path=str(agents_dir / "bias_judge" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "bias_judge" / "INSTRUCTIONS.md"),
                tools=[],
                temperature=0.1,
                provider="openrouter",
                reasoning="none",
                output_schema=BIAS_JUDGE_SCHEMA,
            ),
            name="bias_language",
        ),
        # Consolidator — replaces the legacy PerspectiveSyncStage,
        # validate_coverage_gaps_stage, and consolidate_missing_coverage
        # trio with a single LLM call that classifies + dedupes the
        # dossier's "what is missing" output. Inputs are small
        # (perspective_missing_positions ~5-15 entries +
        # merged_coverage_gaps ~3-10 entries); output is two arrays of
        # short English strings. Temperature 0.3 + reasoning=none +
        # max_tokens=32000 mirror the DeepSeek-V4-Pro default for
        # small structured tasks — see commit rationale.
        "consolidator": Agent(
            name="consolidator",
            model="deepseek/deepseek-v4-pro",
            system_prompt_path=str(agents_dir / "consolidator" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "consolidator" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.3,
            max_tokens=32000,
            provider="openrouter",
            reasoning="none",
            provider_routing=DEEPSEEK_V4_PRO_FP8_ROUTING,
            output_schema=CONSOLIDATOR_SCHEMA,
        ),
    }


def create_agents_hydrated() -> dict[str, Agent]:
    """Agents for the hydrated pipeline.

    Mirrors :func:`create_agents` for the agents shared with production,
    and adds the three hydrated-only agents (``researcher_hydrated_plan``,
    ``hydration_aggregator_phase1``, ``hydration_aggregator_phase2``).
    All agents carry their ``output_schema`` so strict-mode JSON
    enforcement applies on every LLM call.
    """
    agents_dir = ROOT / "agents"
    base = create_agents()
    base.update({
        "researcher_hydrated_plan": Agent(
            name="researcher_hydrated_plan",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "researcher_hydrated" / "PLAN-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher_hydrated" / "PLAN-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
            output_schema=RESEARCHER_PLAN_SCHEMA,
        ),
        # Hydration-Phase-1 model: production default is Gemini-3-Flash.
        # The DeepSeek-V4-Pro spec immediately below is a comment-toggleable
        # alternative used for the evidence-type-classification quality
        # smoke (see TASK-EVIDENCE-TYPE-MIGRATION). Swap by commenting out
        # the active block and uncommenting the alternative. Restore Flash
        # as the default after the smoke unless the eval result switches
        # production model.
        # Hydration-Phase-1 model: production default is DeepSeek-V4-Pro
        # (switched from Gemini-3-Flash per the evidence-type-classification
        # dual-model smoke — DeepSeek showed cleaner attributional fidelity
        # and correctly honoured the recipient-exclusion rule). The Flash
        # spec below is preserved as a fallback / comparison-only
        # alternative — see TASK-EVIDENCE-TYPE-MIGRATION A3 for rationale.
        "hydration_aggregator_phase1": Agent(
            name="hydration_aggregator_phase1",
            model="deepseek/deepseek-v4-pro",
            system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE1-SYSTEM.md"),
            instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE1-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.3,
            max_tokens=32000,
            provider="openrouter",
            reasoning="none",
            provider_routing=DEEPSEEK_V4_PRO_FP8_ROUTING,
            output_schema=HYDRATION_PHASE1_SCHEMA,
        ),
        # --- Fallback / comparison only — see TASK-EVIDENCE-TYPE-MIGRATION
        #     A3 for rationale. Swap by commenting out the active block
        #     above and uncommenting the block below ---
        # "hydration_aggregator_phase1": Agent(
        #     name="hydration_aggregator_phase1",
        #     model="google/gemini-3-flash-preview",
        #     system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE1-SYSTEM.md"),
        #     instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE1-INSTRUCTIONS.md"),
        #     tools=[],
        #     temperature=0.3,
        #     max_tokens=32000,
        #     provider="openrouter",
        #     reasoning="none",
        #     output_schema=HYDRATION_PHASE1_SCHEMA,
        # ),
        # --- END fallback alternative ---
        # hydration_aggregator_phase2 — swapped to GLM-5.2 @ xhigh
        # (TASK-HYDRATION-P2-GLM-SWAP). The phase-2 model eval made this operating
        # point binding (docs/HYDRATION-P2-MODEL-EVAL-2026-07.md): GLM-5.2 ties the
        # Opus-4.8 golden ceiling at overall 4.46, halves fabrications vs the
        # pre-swap Opus-4.6 incumbent (8 vs 14 across 21 topics — the incumbent
        # itself fabricated on 10/21), and is 2.7x cheaper (~$0.019/topic).
        # Wrapped in HydrationPhase2WithFallback: primary GLM-5.2 (fp8-pinned), and
        # exactly ONE fallback attempt if GLM finally fails (transport across all
        # pinned providers after retries, OR schema-invalid/structured=None
        # output) — loud, never silent (model_used/provider_used/
        # hydration_phase2_fallback_used in run_stage_log.jsonl).
        #
        # The fallback is the PRE-SWAP production incumbent VERBATIM (Opus 4.6,
        # temperature 0.1, reasoning=none, max_tokens 32000), so the worst case
        # degrades to the exact prior behaviour — same rationale as the writer swap.
        #
        # ROLLBACK (single-edit revert to the pre-swap production reducer):
        #   "hydration_aggregator_phase2": Agent(
        #       name="hydration_aggregator_phase2",
        #       model="anthropic/claude-opus-4.6",
        #       system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE2-SYSTEM.md"),
        #       instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE2-INSTRUCTIONS.md"),
        #       tools=[], temperature=0.1, max_tokens=32000, provider="openrouter",
        #       reasoning="none", output_schema=HYDRATION_PHASE2_SCHEMA),
        "hydration_aggregator_phase2": HydrationPhase2WithFallback(
            primary=Agent(
                name="hydration_aggregator_phase2",
                model="z-ai/glm-5.2",
                system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE2-SYSTEM.md"),
                instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE2-INSTRUCTIONS.md"),
                tools=[],
                temperature=0.1,
                max_tokens=120000,
                provider="openrouter",
                reasoning="xhigh",
                provider_routing=GLM_5_2_HYDRATION_P2_FP8_ROUTING,
                output_schema=HYDRATION_PHASE2_SCHEMA,
            ),
            # 4th line of defence — the PRE-SWAP production reducer VERBATIM:
            # Opus 4.6, temperature 0.1, reasoning="none", max_tokens 32000, same
            # PHASE2 prompts + HYDRATION_PHASE2_SCHEMA. Only the name differs (for
            # log/metric clarity).
            fallback=Agent(
                name="hydration_aggregator_phase2_fallback",
                model="anthropic/claude-opus-4.6",
                system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE2-SYSTEM.md"),
                instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE2-INSTRUCTIONS.md"),
                tools=[],
                temperature=0.1,
                max_tokens=32000,
                provider="openrouter",
                reasoning="none",
                output_schema=HYDRATION_PHASE2_SCHEMA,
            ),
            output_schema=HYDRATION_PHASE2_SCHEMA,
        ),
    })
    return base


def parse_args():
    parser = argparse.ArgumentParser(description="Independent Wire pipeline")
    parser.add_argument(
        "--from", dest="from_step", default=None,
        help=(
            "Start from this V2 stage (resume from on-disk snapshot). Stage "
            "names match the V2 stage list — see --help-stages for the full "
            "set per variant. Requires --reuse."
        ),
    )
    parser.add_argument(
        "--to", dest="to_step", default=None,
        help="Stop after this V2 stage (inclusive). Default: run to the end.",
    )
    parser.add_argument(
        "--topic", type=int, default=None,
        help=(
            "Only process the Nth selected topic (1-based index). "
            "Other topics are marked 'skipped' and excluded from render."
        ),
    )
    parser.add_argument(
        "--reuse", type=str, default=None,
        help=(
            "Reuse a prior run's snapshots. Accepts 'YYYY-MM-DD' (auto-resolves "
            "to the latest run_id under output/{date}/_state/) or "
            "'YYYY-MM-DD/run-YYYY-MM-DD-xxxxxxxx' for an exact run_id."
        ),
    )
    parser.add_argument(
        "--max-produce", dest="max_produce", type=int, default=3,
        help="Maximum number of topics to produce per run (default: 3).",
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="Run fetch_feeds.py before the pipeline",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Run publish.py after the pipeline (if at least 1 topic succeeded)",
    )
    parser.add_argument(
        "--hydrated", action="store_true",
        help=(
            "Run the hydrated pipeline (canonical for daily production as of "
            "2026-05-19). Adds T1 fetch + Phase 1/2 aggregator + Perspective-"
            "Sync on top of the base stage list. The non-hydrated path is "
            "preserved for backwards compatibility but not actively "
            "maintained. From-scratch hydrated runs are supported."
        ),
    )
    parser.add_argument(
        "--help-stages", action="store_true",
        help="Print the production and hydrated stage names, then exit.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help=(
            "Overwrite an existing run-state directory for --reuse {date} "
            "instead of aborting. Default behaviour without --force is to "
            "refuse to overwrite."
        ),
    )
    return parser.parse_args()


def _check_reuse_overwrite_safety(
    reuse_arg: str, output_dir: Path, force: bool
) -> None:
    """Refuse to overwrite prior --reuse snapshots without --force.

    --reuse {date} runs in-place against an existing state directory and
    overwrites per-stage snapshots. Without --force we abort early with an
    instructive error naming the conflicting paths.
    """
    if force:
        return
    run_date = reuse_arg.strip("/").split("/")[0]
    state_dir = output_dir / run_date / "_state"
    if not state_dir.is_dir():
        return
    existing = sorted(
        d for d in state_dir.iterdir()
        if d.is_dir() and d.name.startswith(f"run-{run_date}-")
    )
    if not existing:
        return
    paths = "\n".join(f"  {d}" for d in existing)
    sample = existing[-1]
    msg = (
        f"ERROR: Run-state for {run_date} already exists at:\n"
        f"{paths}\n\n"
        f"Re-running with --reuse {run_date} would overwrite the snapshots in\n"
        f"the run that minted the new run-id. To preserve the prior snapshots,\n"
        f"copy them first:\n"
        f"  cp -r {sample} {state_dir.parent}/_state-backup/\n\n"
        f"To proceed and overwrite, re-run with --force.\n"
    )
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def _resolve_reuse(reuse_arg: str, output_dir: Path) -> tuple[str, str]:
    """Resolve --reuse argument to (run_date, run_id).

    Accepts:
    - "2026-04-30" → latest run_id under output_dir/{date}/_state/
    - "2026-04-30/run-2026-04-30-abc12345" → exact run_id
    """
    parts = reuse_arg.strip("/").split("/")
    run_date = parts[0]
    state_dir = output_dir / run_date / "_state"

    if len(parts) == 2:
        run_id = parts[1]
        if not (state_dir / run_id).is_dir():
            raise RuntimeError(
                f"--reuse: run_id {run_id!r} not found under {state_dir}"
            )
        return run_date, run_id

    if not state_dir.is_dir():
        raise RuntimeError(
            f"--reuse: no state directory at {state_dir}. Was a prior run "
            f"completed for this date?"
        )

    candidates = sorted(
        [d for d in state_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(f"--reuse: no runs found under {state_dir}")
    return run_date, candidates[0].name


def _print_stage_help() -> None:
    print("V2 stage names (--from / --to choices)\n")
    print("  Production variant:")
    for n in production_stage_names():
        print(f"    {n}")
    print("\n  Hydrated variant:")
    for n in hydrated_stage_names():
        print(f"    {n}")


async def main():
    args = parse_args()
    setup_logging()
    logger = logging.getLogger("independent_wire")

    if args.help_stages:
        _print_stage_help()
        return

    # Pre-pipeline: fetch feeds if requested
    if args.fetch:
        logger.info("Fetching feeds...")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "fetch_feeds.py")],
        )
        if result.returncode != 0:
            logger.error("fetch_feeds.py failed (exit %d)", result.returncode)
            sys.exit(1)

    logger.info("Starting Independent Wire pipeline...")
    start = time.time()

    output_dir = ROOT / "output"
    if args.hydrated:
        agents = create_agents_hydrated()
        run_stages, topic_stages, post_run_stages = build_hydrated_stages(
            agents,
            web_search_tool=web_search_tool,
            max_produce=args.max_produce,
            output_dir=output_dir,
        )
        valid_names = hydrated_stage_names()
    else:
        agents = create_agents()
        run_stages, topic_stages, post_run_stages = build_production_stages(
            agents,
            web_search_tool=web_search_tool,
            max_produce=args.max_produce,
            output_dir=output_dir,
        )
        valid_names = production_stage_names()

    # Validate --from / --to against the active variant's stage names
    if args.from_step and args.from_step not in valid_names:
        logger.error(
            "--from %r is not a valid stage. Run with --help-stages for the "
            "%s stage list.",
            args.from_step,
            "hydrated" if args.hydrated else "production",
        )
        sys.exit(1)
    if args.to_step and args.to_step not in valid_names:
        logger.error(
            "--to %r is not a valid stage. Run with --help-stages for the "
            "%s stage list.",
            args.to_step,
            "hydrated" if args.hydrated else "production",
        )
        sys.exit(1)
    if args.from_step and args.to_step:
        if valid_names.index(args.to_step) < valid_names.index(args.from_step):
            logger.error(
                "--to %r is before --from %r in the stage order.",
                args.to_step, args.from_step,
            )
            sys.exit(1)

    # Resolve --reuse
    reuse_run_id = None
    reuse_run_date = None
    if args.reuse:
        _check_reuse_overwrite_safety(args.reuse, output_dir, args.force)
        try:
            reuse_run_date, reuse_run_id = _resolve_reuse(args.reuse, output_dir)
        except RuntimeError as e:
            logger.error("%s", e)
            sys.exit(1)

    if args.from_step and not reuse_run_id:
        logger.error("--from requires --reuse so prior snapshots can be loaded.")
        sys.exit(1)

    runner = PipelineRunner(
        run_stages=run_stages,
        topic_stages=topic_stages,
        post_run_stages=post_run_stages,
        output_dir=output_dir,
        from_stage=args.from_step,
        to_stage=args.to_step,
        reuse_run_id=reuse_run_id,
        reuse_run_date=reuse_run_date,
        topic_filter=args.topic,
    )

    if args.from_step or args.to_step or args.topic or args.reuse:
        logger.info(
            "Partial run:%s%s%s%s",
            f" --from {args.from_step}" if args.from_step else "",
            f" --to {args.to_step}" if args.to_step else "",
            f" --topic {args.topic}" if args.topic else "",
            f" --reuse {args.reuse}" if args.reuse else "",
        )

    try:
        run_bus = await runner.run()
        elapsed = time.time() - start

        manifest = run_bus.run_topic_manifest or []
        completed = [m for m in manifest if m["status"] == "success"]
        skipped = [m for m in manifest if m["status"] == "skipped"]
        failed = [m for m in manifest if m["status"] == "failed"]
        logger.info("Pipeline finished in %.1f seconds", elapsed)
        logger.info(
            "  Topics: %d completed, %d skipped, %d failed",
            len(completed), len(skipped), len(failed),
        )
        for m in completed:
            logger.info("  completed %s: %s", m["topic_id"], m.get("topic_slug", ""))
        for m in skipped:
            logger.info("  skipped %s: %s", m["topic_id"], m.get("topic_slug", ""))
        for m in failed:
            logger.info("  failed %s: %s", m["topic_id"], m.get("topic_slug", ""))

        # Post-pipeline: publish if requested and at least 1 topic succeeded
        if args.publish and completed:
            logger.info("Publishing site...")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "publish.py")],
            )
            if result.returncode == 0:
                logger.info("Deploying to GitHub Pages...")
                subprocess.run(
                    ["git", "add", "site/"],
                    cwd=str(ROOT),
                )
                date_str = run_bus.run_date or "unknown"
                commit_msg = f"Publish {date_str}: {len(completed)} dossier{'s' if len(completed) != 1 else ''}"
                commit_result = subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                )
                if commit_result.returncode == 0:
                    push_result = subprocess.run(
                        ["git", "push"],
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                    )
                    if push_result.returncode == 0:
                        logger.info("Deployed: %s", commit_msg)
                    else:
                        logger.error("Git push failed: %s", push_result.stderr)
                elif "nothing to commit" in commit_result.stdout:
                    logger.info("No site changes to deploy")
                else:
                    logger.error("Git commit failed: %s", commit_result.stderr)

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
