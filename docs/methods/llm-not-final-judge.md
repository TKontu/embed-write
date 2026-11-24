# Why an LLM is not the final judge of candidate quality

This note explains one rule of the verification panel: no language model decides whether a
proposed rewrite is good. It is written for the expert reading the panel.

## What the system does instead

Each candidate is checked on separate axes (move preserved, meaning preserved, support
preserved, register fit, grammar, length delta), each with its own method and value
(`docs/architecture.md` §5.9 "Proposals and verification"). A candidate that changes meaning is
filtered out, but stays countable and viewable on request. Everything else is shown with its
panel, and the expert decides. No single score merges the axes, and no model's opinion of
"overall quality" stands in for the expert's judgment.

## Known biases of LLM judges

Studies of LLMs used as judges report systematic biases. Three of them would distort the
ranking of candidates here.

**Position bias.** An LLM comparing options tends to favour one based on where it appears in
the prompt (for example, first) rather than on its content. Candidates are shown in an order;
if a model judged them, the order in which they were generated or listed would leak into which
one "wins", and swapping the order could change the verdict.

**Verbosity bias.** LLM judges tend to prefer longer, more elaborate answers. In scientific
writing a longer rewrite is often worse: it adds hedges, filler or claims the source does not
support. A judge with this bias would systematically push the expert toward wordier text, which
is why length delta is reported and never judged.

**Self-preference bias.** An LLM tends to rate text it (or a similar model) produced higher than
text written by others, partly because that text is familiar to it. The candidates here are
LLM-built, while the original and the target genre style are human-written. A judge with this
bias would favour default LLM style over the genre, which is the very gap the system exists to
close.

## What an LLM is used for

- **Generation.** LLMs produce candidate rewrites and drafts. Their output is LLM-built text, to
  be checked by the panel and decided by the expert.
- **Default ordering (VF-09).** A critic may order candidates by move and register fit, subject to
  the filters. That ordering is a default for display, not a verdict; the expert sees every
  unfiltered candidate with its panel and may pick any of them.

## Literature

- Zheng et al. (2023), "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena": position,
  verbosity and self-enhancement biases in LLM judges.
- Panickssery et al. (2024), "LLM Evaluators Recognize and Favor Their Own Generations":
  self-preference and its link to self-recognition.
