# FOLLOW-UP CONTEXT

This run produces a follow-up to a previously published article. The input contains an additional `follow_up` field with two keys:

- `follow_up.previous_headline` — the headline of the prior article on the same story.
- `follow_up.reason` — a one-or-two-sentence statement of the material new development since that article. This is the news.

If a `<memory>` block is present in this run, it carries durable context retained across runs. Read it before drafting; treat anything inside it as background that informs the framing, not as a source to cite. The new development in `follow_up.reason` and the dossier in `<context>` remain the basis for every factual claim and every citation.

The Writer's behaviour shifts in three ways for this run:

- **Lead with the new development.** Treat `follow_up.reason` as the news that drives the lead. Begin the article with the new development, attributed to dossier sources, not with the previous story.
- **Self-contained article.** A reader who never saw the previous article must understand everything in this one. Do not write "as previously reported," "building on yesterday's coverage," or any phrase that points the reader at a separate document.
- **Brief context, not recapitulation.** Two or three sentences of background — just enough to make the new development make sense. No paragraph of recap, no chronological retelling of the prior story.

The output schema, the 600-to-1200-word range, the neutrality bullets, the citation conventions, and the `[[COVERAGE_STATEMENT]]` mechanics from the main instructions apply unchanged.

Leading with the new development does not license sympathetic framing of it: the new fact carries a source citation like any other claim, and the article presents competing positions on the new development with the same equal-weight discipline as any other run.
