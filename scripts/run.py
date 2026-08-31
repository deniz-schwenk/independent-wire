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
from src.flash_stage_fallback import FlashStageWithFallback
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


# --- DeepSeek fp8 quantization pin — RETIRED 2026-08-31 -----------------------
# DEEPSEEK_V4_PRO_FP8_ROUTING is GONE (TASK-DSV4-SWAPS-BUNDLE). It pinned the
# deepseek-v4-pro stages to fp8-verified providers because fp4 quantization
# causes fabrications in DeepSeek V4 (QA-stage eval;
# docs/DEEPSEEK-FP8-PIN-2026-07.md). Its last three users —
# `consolidator`, `hydration_aggregator_phase1` and the bias
# `bias_candidate_extractor` — moved to v4-flash-0731 on 2026-08-31, which
# runs full precision on the vendor's own endpoint and on OpenRouter's pin to
# that endpoint. No stage runs deepseek-v4-pro any more, so the constant was
# deleted rather than left to rot; the fp4 hazard it guarded is not reachable
# from a route that never leaves DeepSeek. tests/test_agent_provider_routing.py
# asserts it stays gone — a reintroduced pro fp8 pin would mean a swap was
# partially reverted.
#
# --- v4-flash-0731 channel routing (TASK-FLASH-0731-SWAP) --------------------
# DEEPSEEK_V4_FLASH_FP8_ROUTING is GONE for the same reason, since
# 2026-08-24: the flash stages run full precision on
# `deepseek-v4-flash-0731`, channel C (api.deepseek.com direct) primary with
# channel A (OpenRouter, pinned to the vendor's own endpoint) as the one-shot
# fallback. Evidence: docs/evals/dsv4-0731/{T2,T2B,T2D}-REPORT.md.
#
# Channel A pin. Two deliberate departures from every other pin in this file:
#   * NO `quantizations` filter. The DeepSeek endpoint reports quantization
#     "unknown"; an fp8 (or any) filter excludes it and the call 404s with
#     "No endpoints found" (T2b §1.1).
#   * The agents carry `structured_output_mode="json_object"`. This endpoint
#     declares no `structured_outputs`, so Agent's default strict-schema path
#     would send a `json_schema` response_format AND set
#     `require_parameters: true` — and the combination filters this very
#     endpoint out of the route (404, verified again 2026-08-31). It is the
#     unsupported PARAMETER that excludes it, not the flag: with
#     `json_object`, `require_parameters: true` routes and answers normally.
#     Schema conformance is enforced locally instead, by
#     FlashStageWithFallback.
# `allow_fallbacks: false` keeps the fail-loud contract: this is the vendor's
# own endpoint or nothing, never a third-party host of the same id.
DEEPSEEK_NATIVE_ROUTING = {
    "order": ["deepseek"],
    "allow_fallbacks": False,
}

# max_tokens for the three v4-flash-0731 stages (TASK-FLASH-0731-SWAP,
# superseding the fp8-era table from TASK-FLASH-PIN-REPAIR). The old ceiling
# arithmetic is gone with the pin: channel C's ceiling is 393 216 and channel
# A's is 384 000, so no pinned provider constrains these values any more. What
# remains is the >= 2x-worst-observed rule, measured on the SAME captured
# production inputs at the SAME operating point (T2d Part B, n = 6..18 real
# calls per row; T2b dsn-med for the channel-A column):
#
#   stage                    channel  effort  worst obs.  set to    headroom
#   curator_topic_discovery  C        medium      27 504  128 000     4.65x
#   researcher_assemble      C        low         61 573* 128 000     2.08x
#   resolve_actor_aliases    C        low          6 719   16 000     2.38x
#   curator (A fallback)     A        medium      38 949  128 000     3.29x
#   assemble (A fallback)    A        medium      38 418  128 000     3.33x
#   resolve  (A fallback)    A        medium       6 701   16 000     2.39x
#
#   * assemble's worst is measured at `medium`, the higher of the two shadow
#     arms, so 128 000 covers whichever effort the shadow phase selects.
#
# resolve shipped at 8 000 in the first draft of this change — the swap task's
# specified value, and the one row that fell BELOW the 2x convention at 1.19x
# over a 9-call worst of 6 719. Raised to 16 000 (2.38x) on review, which also
# makes the primary and its channel-A fallback agree. The failure mode it
# removes is cheap but real and self-inflicted: an overrun truncates, fails
# local validation, and burns a fallback call rather than dropping the topic,
# so the old value traded a fallback's cost and latency against tokens that
# are only billed if generated. `resolve_actor_aliases_fallback_used` in
# run_stage_log.jsonl remains the instrument if the tail turns out longer than
# 9 calls could show.
#
# Tight caps remain worth having for a second reason, unchanged from the fp8
# era: the 2026-08-23 probes caught a degenerate repetition runaway (one source
# emitted 127x, finish_reason "length"). A runaway produces no usable output at
# ANY ceiling, so the cap's job is to end it quickly and loudly.
#
# The values are set inline at each of the three registrations below.

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


def _flash_0731_primary(
    *,
    name: str,
    system_prompt_path: str,
    instructions_path: str,
    reasoning: str,
    max_tokens: int,
    output_schema: dict,
    temperature: float = 0.5,
) -> Agent:
    """Channel C — the PRIMARY for a v4-flash-0731 stage: api.deepseek.com
    direct (TASK-FLASH-0731-SWAP, owner decision on the T2d matrix).

    Three things here are load-bearing and none of them are obvious:

    * ``model="deepseek-v4-flash"`` is not a typo for the dated id. The vendor
      exposes exactly one flash id and 400s on every dated form; it serves the
      0731 build by alias. That alias is unpinnable, which is why Agent logs
      the SERVER-ECHOED model id on every call (T2d §1.1).
    * ``reasoning`` is a plain string and reaches the wire as
      ``reasoning_effort``. The OpenRouter ``{"effort": ...}`` object is
      *accepted and ignored* by this API, so the wrong shape fails silently
      into the default; Agent raises on a dict for this provider rather than
      let that happen (T2d §1.3).
    * The effort levels are NOT interchangeable with channel A's. Measured
      paired at an identical cap, C·medium spends 2.64x the reasoning of
      A·medium on resolve, and **A·medium corresponds to C·low** (T2d §1.3).
      Hence the fallbacks below all run `medium` while these primaries run
      lower — that is parity, not a downgrade.

    ``temperature`` defaults to 0.5, the value the first three stages shipped
    with. It is a parameter rather than a constant because the stages added by
    TASK-DSV4-SWAPS-BUNDLE carry their own eval-validated decode temperature
    (consolidator 0.3, phase1 0.3, bias extractor 0.8 — the extractor's
    spread is deliberate: natural variance across the three passes IS the
    recall mechanism). A swap must not silently re-tune the sampling of the
    stage it swaps.

    ``structured_output_mode`` is coerced to json_object by Agent for this
    provider; schema conformance is enforced by FlashStageWithFallback."""
    return Agent(
        name=name,
        model="deepseek-v4-flash",
        system_prompt_path=system_prompt_path,
        instructions_path=instructions_path,
        tools=[],
        temperature=temperature,
        max_tokens=max_tokens,
        provider="deepseek_direct",
        reasoning=reasoning,
        output_schema=output_schema,
        structured_output_mode="json_object",
    )


def _flash_0731_fallback(
    *,
    name: str,
    system_prompt_path: str,
    instructions_path: str,
    max_tokens: int,
    output_schema: dict,
    temperature: float = 0.5,
) -> Agent:
    """Channel A — the one-shot FALLBACK for a v4-flash-0731 stage: OpenRouter
    on the dated id, pinned to the vendor's own endpoint.

    Same weights as the primary reached by a different route, which is the
    point: a direct-API outage or rate-limit does not take this down with it,
    and OpenRouter's dated id is the only *pinnable* handle on the 0731 build
    that exists anywhere. It replaces the pre-2026-08-24
    ``google/gemini-3-flash-preview`` net — a different model on a different
    ecosystem, which bought ecosystem independence at the price of serving a
    different model's output into the pipeline.

    Runs at ``reasoning="medium"``, the T2b-calibrated operating point, which
    is the channel-A equivalent of the primaries' lower settings (see
    ``_flash_0731_primary``). ``structured_output_mode="json_object"`` is
    mandatory, not stylistic: the strict-schema path would inject
    ``require_parameters: true`` and 404 this endpoint out of its own route."""
    return Agent(
        name=name,
        model="deepseek/deepseek-v4-flash-0731",
        system_prompt_path=system_prompt_path,
        instructions_path=instructions_path,
        tools=[],
        temperature=temperature,
        max_tokens=max_tokens,
        provider="openrouter",
        reasoning="medium",
        provider_routing=DEEPSEEK_NATIVE_ROUTING,
        output_schema=output_schema,
        structured_output_mode="json_object",
    )


def create_agents() -> dict[str, Agent]:
    """Create all pipeline agents with their configurations.

    As of 2026-05-19, the non-hydrated path is legacy. The hydrated
    pipeline (``--hydrated`` flag) is canonical for daily production.
    The base agent configs below are inherited by
    :func:`create_agents_hydrated` and are the production source of truth.

    Model/provider assignments: the return dict below is the single source
    of truth. Do not duplicate model names here (duplicated truth drifts);
    see also the docs/ARCHITECTURE.md model table. Historical migration
    notes live in git history.
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
        # v4-flash-0731 since 2026-08-24 (TASK-FLASH-0731-SWAP); before that,
        # deepseek-v4-flash fp8-pinned since the Wave-2 curator-variance smoke
        # (docs/curator-variance-2026-05-19/). Channel C primary, channel A
        # fallback — see _flash_0731_primary / _flash_0731_fallback.
        #
        # `medium` on BOTH channels here, unlike the other two stages: T2d §1.3
        # found the effort mismatch is stage-dependent and the curator's two
        # mediums already agree (C 23 110 vs A 25 388 reasoning tokens), so no
        # translation is needed. `none` is not an option at all — T2b §2.2
        # scored it BELOW control on both channels through wholesale topic
        # repetition (29 and 24 duplicate titles, against 0 at medium).
        #
        # curator_topic_discovery is RUN-LEVEL: a failure kills the whole day's
        # run (no per-topic isolation), so the fallback matters most here. Loud
        # marker curator_topic_discovery_fallback_used. See
        # src/flash_stage_fallback.py.
        "curator_topic_discovery": FlashStageWithFallback(
            primary=_flash_0731_primary(
                name="curator_topic_discovery",
                system_prompt_path=str(agents_dir / "curator" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "curator" / "INSTRUCTIONS.md"),
                reasoning="medium",
                max_tokens=128000,   # 4.65x worst observed; see the note above
                output_schema=CURATOR_TOPIC_DISCOVERY_SCHEMA,
            ),
            fallback=_flash_0731_fallback(
                name="curator_topic_discovery_fallback",
                system_prompt_path=str(agents_dir / "curator" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "curator" / "INSTRUCTIONS.md"),
                max_tokens=128000,   # 3.29x worst observed on channel A
                output_schema=CURATOR_TOPIC_DISCOVERY_SCHEMA,
            ),
            output_schema=CURATOR_TOPIC_DISCOVERY_SCHEMA,
            name="curator_topic_discovery",
            fallback_marker_key="curator_topic_discovery_fallback_used",
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
        # v4-flash-0731 since 2026-08-24 (TASK-FLASH-0731-SWAP); DeepSeek V4
        # Flash before that, per Wave-1 Sweep #3
        # (docs/cost-efficiency-sweep-2026-05-18/researcher_assemble-report.md).
        # This is the stage the eval programme recommended swapping FIRST:
        # 18/18 judged better than control on channel A · medium, +0.750 per
        # pair (T2b §2.2).
        #
        # Effort `low`, not `medium`: T2d §1.3 measured C·medium at 1.51x
        # A·medium's reasoning here, so `low` is the parity setting and the
        # cheaper of the two. That mapping was calibrated on `resolve`, not on
        # this stage, so the swap's shadow phase ran both arms on identical
        # inputs (2026-08-23, 3 topics). Result: `low` was clean 3/3 at
        # $0.1467; `medium` cost $0.1869 (+27%) and produced a schema-invalid
        # body on 1 of 3 topics, which burned a channel-A fallback. `medium`
        # did extract ~9% more canonical actors after dedup — but it sits
        # ABOVE the operating point any quality eval validated, and it failed
        # once. Lower effort wins, and here it does not even need the
        # tie-break.
        #
        # A topic dies if this stage fails, so the one-shot channel-A fallback
        # is the difference between a thin day and a missing package. Loud,
        # never silent (researcher_assemble_fallback_used in
        # run_stage_log.jsonl). See src/flash_stage_fallback.py.
        "researcher_assemble": FlashStageWithFallback(
            primary=_flash_0731_primary(
                name="researcher_assemble",
                system_prompt_path=str(agents_dir / "researcher" / "ASSEMBLE-SYSTEM.md"),
                instructions_path=str(agents_dir / "researcher" / "ASSEMBLE-INSTRUCTIONS.md"),
                reasoning="low",
                max_tokens=128000,   # 2.08x worst observed; see the note above
                output_schema=RESEARCHER_ASSEMBLE_SCHEMA,
            ),
            fallback=_flash_0731_fallback(
                name="researcher_assemble_fallback",
                system_prompt_path=str(agents_dir / "researcher" / "ASSEMBLE-SYSTEM.md"),
                instructions_path=str(agents_dir / "researcher" / "ASSEMBLE-INSTRUCTIONS.md"),
                max_tokens=128000,   # 3.33x worst observed on channel A
                output_schema=RESEARCHER_ASSEMBLE_SCHEMA,
            ),
            output_schema=RESEARCHER_ASSEMBLE_SCHEMA,
            name="researcher_assemble",
            fallback_marker_key="researcher_assemble_fallback_used",
        ),
        # v4-flash-0731 since 2026-08-24 (TASK-FLASH-0731-SWAP); DeepSeek V4
        # Flash before that, per Wave-2 Sweep #2
        # (docs/cost-efficiency-sweep-wave-2-2026-05-18/resolve_actor_aliases-report.md).
        #
        # Effort `low`, up from `none`. Wave-2 concluded this extraction-class
        # role gained nothing from reasoning, but that was measured on the old
        # weights: on 0731, T2b §2.2 scored medium at +1.150 per pair against
        # control while `none` managed +0.500, and reproducibility roughly
        # doubled (Jaccard 0.47 -> 0.84). `low` on channel C is the calibrated
        # equivalent of channel A's `medium` — the pairing is measured on THIS
        # stage, 9/9 inputs, ratio 1.10 (T2d §1.3).
        #
        # max_tokens 16 000 is 2.38x the observed worst, and the same value
        # the channel-A fallback carries. It replaces a first-draft 8 000
        # (1.19x) — see the note above the routing constant for why that was a
        # fallback-burn risk rather than a data-loss one, and which counter to
        # watch.
        #
        # Per-topic; loud marker resolve_actor_aliases_fallback_used. See
        # src/flash_stage_fallback.py.
        "resolve_actor_aliases": FlashStageWithFallback(
            primary=_flash_0731_primary(
                name="resolve_actor_aliases",
                system_prompt_path=str(agents_dir / "resolve_actor_aliases" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "resolve_actor_aliases" / "INSTRUCTIONS.md"),
                reasoning="low",
                max_tokens=16000,    # 2.38x worst observed; see the note above
                output_schema=RESOLVE_ACTOR_ALIASES_SCHEMA,
            ),
            fallback=_flash_0731_fallback(
                name="resolve_actor_aliases_fallback",
                system_prompt_path=str(agents_dir / "resolve_actor_aliases" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "resolve_actor_aliases" / "INSTRUCTIONS.md"),
                max_tokens=16000,    # 2.39x worst observed on channel A
                output_schema=RESOLVE_ACTOR_ALIASES_SCHEMA,
            ),
            output_schema=RESOLVE_ACTOR_ALIASES_SCHEMA,
            name="resolve_actor_aliases",
            fallback_marker_key="resolve_actor_aliases_fallback_used",
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
        #   Phase A: v4-flash-0731 @ minimal since 2026-08-31
        #     (TASK-DSV4-SWAPS-BUNDLE, component TASK-BIAS-EXTRACTOR-COUPLED),
        #     temperature 0.8 on every pass (natural variance = coverage),
        #     channel C primary + channel A one-shot fallback,
        #     max_tokens 32 000 (caps.json bias_extractor@minimal).
        #   Phase B: opus-4.6, temp 0.1, reasoning=none, closed per-candidate
        #     judgment (BIAS_JUDGE_SCHEMA field order is load-bearing).
        #
        # The model swap and the own-voice prompt fix landed TOGETHER, and the
        # coupling is not stylistic. The prompt fix drives quote-harvest to
        # 0.000 and D3 1.42 -> 5.00 on the 0813/0731 builds, but on the April
        # v4-pro build production was running it is the WORST cell measured
        # (judged 2.60 against flash's 4.30 — spans inflate to whole
        # sentences). Landing the prompt alone would have made the stage worse.
        # Either both, or neither.
        #
        # The extractor is the only agent in the pipeline deliberately run at
        # high temperature and repeated: three passes' disagreement IS the
        # recall mechanism, unioned deterministically in src/bias_composite.py.
        # A pass that comes back thin therefore costs coverage, which is what
        # the adaptive 4th pass in that module addresses.
        #
        # Loud marker extractor_fallback_used, surfaced through the composite's
        # extra_log_fields (BiasComposite is the stage's agent, so the runner
        # reads the composite, not this wrapper). See
        # src/flash_stage_fallback.py.
        "bias_language": BiasComposite(
            extractor=FlashStageWithFallback(
                primary=_flash_0731_primary(
                    name="bias_candidate_extractor",
                    system_prompt_path=str(
                        agents_dir / "bias_candidate_extractor" / "SYSTEM.md"),
                    instructions_path=str(
                        agents_dir / "bias_candidate_extractor" / "INSTRUCTIONS.md"),
                    reasoning="minimal",
                    temperature=0.8,
                    max_tokens=32000,   # caps.json bias_extractor@minimal
                    output_schema=BIAS_CANDIDATES_SCHEMA,
                ),
                fallback=_flash_0731_fallback(
                    name="bias_candidate_extractor_fallback",
                    system_prompt_path=str(
                        agents_dir / "bias_candidate_extractor" / "SYSTEM.md"),
                    instructions_path=str(
                        agents_dir / "bias_candidate_extractor" / "INSTRUCTIONS.md"),
                    temperature=0.8,
                    max_tokens=32000,   # caps.json bias_extractor@medium
                    output_schema=BIAS_CANDIDATES_SCHEMA,
                ),
                output_schema=BIAS_CANDIDATES_SCHEMA,
                name="bias_candidate_extractor",
                fallback_marker_key="extractor_fallback_used",
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
        # short English strings.
        #
        # v4-flash-0731 since 2026-08-31 (TASK-DSV4-SWAPS-BUNDLE, component
        # TASK-CONSOLIDATOR-SWAP-FLASH0731); deepseek-v4-pro on the OpenRouter
        # fp8 pin before that. Channel C primary, channel A fallback — the same
        # two-route wiring as the three stages swapped on 2026-08-24, via
        # _flash_0731_primary / _flash_0731_fallback.
        #
        # Effort `minimal`, the T3b operating point: T3B-REPORT §7.1 judged
        # flash@minimal at 4.75 against the v4-pro baseline's 4.48, with
        # candidate counts inside each other's noise, at the lowest cost of the
        # arms measured. This is a classify-and-dedupe task over a handful of
        # short strings — the reasoning budget buys nothing above triage level,
        # and `minimal` is where the eval put it.
        #
        # temperature 0.3 and max_tokens 32000 are UNCHANGED across the swap
        # (32000 is also scratch/eval/t3b/caps.json consolidator@minimal —
        # >= 2x the worst observed completion for the cell). A model swap is
        # not licence to re-tune decode parameters the eval held fixed.
        #
        # The empty-emission guard in ConsolidatorStage
        # (_CONSOLIDATOR_EMPTY_MAX_ATTEMPTS, merged 2026-08-31) sits ABOVE this
        # wrapper and is untouched: each of its retries is a fresh wrapper call,
        # so a retry re-rolls the primary and can itself fall back. Loud marker
        # consolidator_fallback_used. See src/flash_stage_fallback.py.
        "consolidator": FlashStageWithFallback(
            primary=_flash_0731_primary(
                name="consolidator",
                system_prompt_path=str(agents_dir / "consolidator" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "consolidator" / "INSTRUCTIONS.md"),
                reasoning="minimal",
                temperature=0.3,
                max_tokens=32000,   # caps.json consolidator@minimal
                output_schema=CONSOLIDATOR_SCHEMA,
            ),
            fallback=_flash_0731_fallback(
                name="consolidator_fallback",
                system_prompt_path=str(agents_dir / "consolidator" / "SYSTEM.md"),
                instructions_path=str(agents_dir / "consolidator" / "INSTRUCTIONS.md"),
                temperature=0.3,
                max_tokens=32000,   # caps.json consolidator@medium
                output_schema=CONSOLIDATOR_SCHEMA,
            ),
            output_schema=CONSOLIDATOR_SCHEMA,
            name="consolidator",
            fallback_marker_key="consolidator_fallback_used",
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
        # Hydration-Phase-1 model: v4-flash-0731 @ medium since 2026-08-31
        # (TASK-DSV4-SWAPS-BUNDLE, component TASK-P1-SWAP-FLASH0731);
        # deepseek-v4-pro on the OpenRouter fp8 pin before that, and
        # Gemini-3-Flash before THAT (the evidence-type-classification
        # dual-model smoke, TASK-EVIDENCE-TYPE-MIGRATION A3 — the
        # comment-toggleable Gemini alternative that lived here went with the
        # swap: a third model behind a comment is not a fallback, it is a trap,
        # and the stage now has a real one).
        #
        # Effort `medium`, not the consolidator's `minimal`: T3b §7.2 plus
        # docs/evals/t3b-p1-confirm/REPORT.md measured 4.23 against the v4-pro
        # baseline's 3.80 across all 27 chunks (t = 5.56, +0.435 paired, better
        # on 24 of 27), driven by D2 actor recall 2.31 -> 3.60, with no
        # dimension regressing. Phase 1 reads whole fetched articles and has to
        # find the actors in them — this is the one stage in the bundle where
        # the reasoning budget buys measured recall.
        #
        # max_tokens 160 000 is caps.json phase1@medium, and the reason phase1
        # has its own row there: medium spends reasoning INSIDE the total
        # budget and its spend explodes with effort (flash/minimal 20 727
        # completion vs flash/medium 57 460 on the same chunk). Carrying the
        # minimal cap would truncate. temperature 0.3 unchanged.
        #
        # Chunking is untouched by the swap: ceil(N/10) distribution,
        # asyncio.gather parallelism, the missing-indices retry and the
        # cache-cold empty-retry wrapper all still sit ABOVE this agent, so a
        # per-chunk empty re-rolls the primary and can itself fall back. Loud
        # marker hydration_phase1_fallback_used (the sibling naming of
        # hydration_phase2_fallback_used). See src/flash_stage_fallback.py.
        "hydration_aggregator_phase1": FlashStageWithFallback(
            primary=_flash_0731_primary(
                name="hydration_aggregator_phase1",
                system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE1-SYSTEM.md"),
                instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE1-INSTRUCTIONS.md"),
                reasoning="medium",
                temperature=0.3,
                max_tokens=160000,   # caps.json phase1@medium
                output_schema=HYDRATION_PHASE1_SCHEMA,
            ),
            fallback=_flash_0731_fallback(
                name="hydration_aggregator_phase1_fallback",
                system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE1-SYSTEM.md"),
                instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE1-INSTRUCTIONS.md"),
                temperature=0.3,
                max_tokens=160000,   # caps.json phase1@medium
                output_schema=HYDRATION_PHASE1_SCHEMA,
            ),
            output_schema=HYDRATION_PHASE1_SCHEMA,
            name="hydration_aggregator_phase1",
            fallback_marker_key="hydration_phase1_fallback_used",
        ),
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
