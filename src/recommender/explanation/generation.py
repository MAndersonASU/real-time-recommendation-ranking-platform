import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from recommender.explanation.contract import ExplanationResponse
from recommender.explanation.retrieval import SupportContext

MODEL_NAME = "google/flan-t5-small"
# Pinned to a specific commit rather than left to resolve "main":
# from_pretrained(MODEL_NAME) with no revision would resolve to
# whatever "main" currently points to on the Hub at download time -- a
# later push to that repo (a genuine update, or a compromised/hijacked
# one) would then silently change which weights this project loads,
# with no way to know it happened. Pinned to the exact commit this
# project actually tests against (confirmed via
# `huggingface_hub.scan_cache_dir()` against this machine's real local
# cache). A future, deliberate model upgrade updates this constant
# explicitly, rather than an update happening invisibly.
MODEL_REVISION = "0fc9ddf78a1e988dac52e2dac162b0ede4fd74ab"
MAX_NEW_TOKENS = 60

# A recommendation resting entirely on the learned retrieval score alone
# (already diagnosed as weak on its own, docs/conclusions.md RQ1) has no
# real, human-checkable evidence an explanation could honestly cite --
# 0.05 is a low bar, chosen only to exclude a near-zero similarity that
# would be indistinguishable from no real content overlap at all.
MIN_CONTENT_SIMILARITY_FOR_GROUNDING = 0.05


class TextGenerator(Protocol):
    """The only capability generate_explanation actually needs -- a
    real model in production, a small deterministic stand-in in tests,
    so the wiring here is exercised in CI without downloading anything.
    """

    def generate(self, prompt: str) -> str: ...


@dataclass
class LocalT5Generator:
    """Wraps the real local flan-t5-small model -- loaded once via
    `load_generator()` and reused across every request, never
    re-downloaded or re-loaded per call.
    """

    tokenizer: object
    model: object

    def generate(self, prompt: str) -> str:
        inputs = self.tokenizer(prompt, return_tensors="pt")
        output = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS)
        return self.tokenizer.decode(output[0], skip_special_tokens=True).strip()


@lru_cache(maxsize=1)
def load_generator() -> LocalT5Generator:
    from transformers import T5ForConditionalGeneration, T5Tokenizer

    tokenizer = T5Tokenizer.from_pretrained(MODEL_NAME, revision=MODEL_REVISION)
    model = T5ForConditionalGeneration.from_pretrained(MODEL_NAME, revision=MODEL_REVISION)
    model.eval()
    return LocalT5Generator(tokenizer=tokenizer, model=model)


def has_sufficient_evidence(context: SupportContext) -> bool:
    """A recommendation is explainable only if at least one of the two
    real, checkable signals this project actually measures supports it:
    the item's category matching the user's own dominant history
    category, or a real, non-negligible content-similarity score.
    """
    return context.category_match or context.content_similarity >= MIN_CONTENT_SIMILARITY_FOR_GROUNDING


def _evidence_used(context: SupportContext) -> list[str]:
    evidence = []
    if context.category_match:
        evidence.append("category_match")
    if context.content_similarity >= MIN_CONTENT_SIMILARITY_FOR_GROUNDING:
        evidence.append("content_similarity")
    return evidence


@dataclass(frozen=True)
class ExplanationFacts:
    """The complete set of facts an explanation is permitted to state,
    extracted from real matched signals before any text exists.

    Separating the facts from the wording is what makes the explanation
    checkable: a template is chosen by which facts are present, and only
    validated values are ever substituted into it. Nothing downstream
    can introduce a fact that is not represented here.
    """

    category: str | None
    category_match: bool
    content_similarity: float

    @property
    def has_category_evidence(self) -> bool:
        return self.category_match and bool(self.category)

    @property
    def has_content_evidence(self) -> bool:
        return self.content_similarity >= MIN_CONTENT_SIMILARITY_FOR_GROUNDING


def extract_facts(context: SupportContext) -> ExplanationFacts:
    return ExplanationFacts(
        category=context.category,
        category_match=bool(context.category_match),
        content_similarity=float(context.content_similarity),
    )


# The complete set of sentences this system can produce. Each is chosen
# by which evidence is actually present, and `{category}` is the only
# substitution point -- filled solely from a validated real category.
APPROVED_TEMPLATES = {
    ("category", "content"): (
        "Recommended because it matches your interest in {category} "
        "and its content closely resembles articles you've read before."
    ),
    ("category",): "Recommended because it matches your interest in {category}.",
    ("content",): (
        "Recommended because its content closely resembles articles you've read before."
    ),
}


def select_template_key(facts: ExplanationFacts) -> tuple:
    key = []
    if facts.has_category_evidence:
        key.append("category")
    if facts.has_content_evidence:
        key.append("content")
    return tuple(key)


_CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9 &/-]{0,40}$", re.IGNORECASE)


def build_template_explanation(context: SupportContext) -> str:
    """Selects one approved template by which evidence is present and
    fills its single placeholder with a validated category value.

    No generative model participates in stating the factual
    relationship. A model can only ever reword this sentence, and only
    when a caller explicitly opts in -- see `generate_explanation`.

    This design exists because of a real, measured limitation, not a
    guess: an early version let the model generate freely from the
    article's title and abstract, and real output on real recommended
    items included an outright factual corruption (a title's "Bosses"
    rewritten as "boyfriends"). A later paraphrase-only attempt avoided
    inventing facts but regularly dropped the one fact it was given,
    rewriting a category-specific sentence into content-free filler.
    `docs/explanation-generation.md` records those real examples.
    """
    facts = extract_facts(context)
    key = select_template_key(facts)
    if not key:
        return ""

    template = APPROVED_TEMPLATES[key]
    if "{category}" not in template:
        return template

    category = facts.category or ""
    if not _CATEGORY_PATTERN.match(category):
        # A category that does not look like a real category label is
        # not substituted into user-visible text. Falling back to the
        # content-only sentence keeps the output true rather than
        # rendering an unvalidated value.
        return APPROVED_TEMPLATES[("content",)] if facts.has_content_evidence else ""
    return template.format(category=category)


# Every word a rewrite is allowed to use that the template doesn't
# already contain -- pure closed-class grammatical connectives with no
# capacity to carry a factual claim on their own (no actor, no entity,
# no cause, no outcome). Deliberately does not include ordinary content
# verbs like "picked", "chose", or "selected": those are exactly the
# words a fabricated attribution reaches for ("the president selected
# this..."), so leaving them out forces any content-bearing word in the
# rewrite to come from the evidence-grounded template itself.
_SAFE_SCAFFOLDING_WORDS = {
    "a", "an", "the", "this", "that", "these", "those", "some", "any",
    "it", "its", "you", "your", "yours", "we", "our",
    "what", "which", "who", "whose",
    "and", "or", "but", "because", "since", "as", "so", "also",
    "of", "to", "for", "with", "in", "on", "by", "from", "about",
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "not", "no",
}


def _introduces_unsupported_content(text: str, template: str) -> bool:
    """True if `text` contains any word that is neither already in the
    deterministic template nor pure grammatical scaffolding -- closed-
    vocabulary, not a capitalization heuristic: a fabrication does not
    have to invent a capitalized proper noun to be a fabrication.
    "the president personally selected this story for you" introduces
    no capitalized word at all, but "president", "personally", and
    "selected" are all real, unsupported content the template never
    said. Checked case-insensitively and by word regardless of
    position, so a lowercase, mixed-case, or sentence-initial
    fabrication is caught the same way.

    Biased deliberately toward over-rejection: a rewrite that fails
    this check falls back to the safe template, which is never wrong,
    only less naturally worded -- so a genuine but differently-worded
    paraphrase being rejected is an acceptable cost for never accepting
    a fabricated claim.
    """
    template_words = {w.lower() for w in re.findall(r"\b[A-Za-z]+\b", template)}
    allowed = template_words | _SAFE_SCAFFOLDING_WORDS
    for word in re.findall(r"\b[A-Za-z]+\b", text):
        if word.lower() not in allowed:
            return True
    return False


def _preserves_required_facts(text: str, context: SupportContext, template: str) -> bool:
    """A real, checkable faithfulness gate applied before a model's
    rewrite is ever used, covering both real grounding signals, not
    only one of them:

    1. When the evidence is a category match, the real category word
       must still be present -- catches the rewrite dropping the one
       fact it was given.
    2. Regardless of which evidence applies, the rewrite must not
       introduce any word outside the template's own vocabulary plus a
       small, fixed set of grammatical connectives -- catches the
       rewrite inventing a claim it was never given at all, whether or
       not that claim happens to be capitalized.
    """
    if context.category_match and context.category.lower() not in text.lower():
        return False
    return not _introduces_unsupported_content(text, template)


def generate_explanation(
    context: SupportContext,
    generator: TextGenerator | None = None,
    allow_generative_rewrite: bool = False,
) -> ExplanationResponse:
    """Refuses outright, with no model call at all, when neither real
    signal supports the recommendation. Otherwise returns the
    deterministic, evidence-grounded sentence.

    `allow_generative_rewrite` is off by default, and that default is
    the substantive safety property. A generated rewrite can only be
    checked lexically -- that every word it uses was already available
    to it -- and a lexical check cannot validate meaning. Approved words
    can be reordered into a different claim, a subject and object can be
    swapped, and an unsupported assertion can be built entirely from
    allowed vocabulary. Those cases are demonstrated directly in
    `tests/test_explanation_generation.py`, and they are the reason the
    factual relationship is never delegated to a model here.

    With the flag on, the rewrite is still gated by
    `_preserves_required_facts` and still falls back to the template on
    failure, so the worst case is unchanged wording. What the flag
    cannot do is make a rewrite semantically verified.
    """
    if not has_sufficient_evidence(context):
        return ExplanationResponse(
            news_id=context.news_id, explanation="", refused=True, evidence_used=[]
        )

    template = build_template_explanation(context)
    explanation = template

    if allow_generative_rewrite:
        active_generator = generator if generator is not None else load_generator()
        prompt = (
            "Rewrite the following sentence to sound more natural. Do not add any new "
            f"facts or names. Sentence: {template}"
        )
        rewritten = active_generator.generate(prompt)
        if _preserves_required_facts(rewritten, context, template):
            explanation = rewritten

    return ExplanationResponse(
        news_id=context.news_id,
        explanation=explanation,
        refused=False,
        evidence_used=_evidence_used(context),
    )
