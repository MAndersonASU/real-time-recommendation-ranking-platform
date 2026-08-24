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


def build_template_explanation(context: SupportContext) -> str:
    """A deterministic sentence built directly from the real matched
    signals -- guaranteed to contain no fact beyond what is actually
    true. Used both as the safe fallback and as the only thing a real
    model paraphrase is ever allowed to reword, never as raw material
    the model free-generates from.

    This design exists because of a real, measured limitation, not a
    guess: an early version of this step let the model generate freely
    from the article's title and abstract, and real output on real
    recommended items included at least one outright factual
    corruption (a title's "Bosses" rewritten as "boyfriends") alongside
    several redundant or uninformative sentences. Two further real
    attempts -- a fill-in-the-blank prompt that withheld the title, and
    asking the model to paraphrase this exact template sentence --
    both reliably avoided inventing new facts, but the paraphrase
    attempt regularly dropped the one real fact it was given entirely
    (rewriting a category-specific sentence into content-free filler
    like "It is a good choice for you"). `docs/explanation-generation.md`
    records the real examples from all three attempts.
    """
    clauses = []
    if context.category_match:
        clauses.append(f"it matches your interest in {context.category}")
    if context.content_similarity >= MIN_CONTENT_SIMILARITY_FOR_GROUNDING:
        clauses.append("its content closely resembles articles you've read before")
    return "Recommended because " + " and ".join(clauses) + "."


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
    context: SupportContext, generator: TextGenerator | None = None
) -> ExplanationResponse:
    """Refuses outright, with no model call at all, when neither real
    signal supports the recommendation. Otherwise builds the safe
    deterministic template first, asks the local model only to reword
    it more naturally, and falls back to the unmodified template
    whenever the rewrite fails the faithfulness gate above -- the
    model's role is narrowed specifically to reduce the real, measured
    risk of it inventing or dropping a fact, not eliminated outright.
    """
    if not has_sufficient_evidence(context):
        return ExplanationResponse(
            news_id=context.news_id, explanation="", refused=True, evidence_used=[]
        )

    template = build_template_explanation(context)
    active_generator = generator if generator is not None else load_generator()
    prompt = (
        "Rewrite the following sentence to sound more natural. Do not add any new "
        f"facts or names. Sentence: {template}"
    )
    rewritten = active_generator.generate(prompt)
    explanation = rewritten if _preserves_required_facts(rewritten, context, template) else template

    return ExplanationResponse(
        news_id=context.news_id,
        explanation=explanation,
        refused=False,
        evidence_used=_evidence_used(context),
    )
