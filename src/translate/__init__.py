"""German translation feature — standalone, post-pipeline.

A SEPARATE feature for German reach: it runs AFTER the daily production run, reads the
finished run state read-only, and writes German JSON to its own output location. It is
never imported by scripts/run.py, never a Stage, and never wired into the Bus.

  core       table lookup, entity index + glossary, 5-block segmentation, schema guard,
             prompt assembly, defensive JSON parse (validated bench logic, promoted)
  transport  the per-TP fallback chain (ollama-cloud -> deepseek-direct -> openrouter)
  run        translate_tp: one TP with one provider, guard + temperature-ladder repair
  brackets   deterministic Policy-A gloss bracket-normalization post-pass
"""
