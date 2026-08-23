import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from recommender.explanation.contract import ExplanationResponse
from recommender.explanation.retrieval import SupportContext

MODEL_NAME = "google/flan-t5-small"
# A real bug, found by audit: from_pretrained(MODEL_NAME) with no
# revision resolves to whatever "main" currently points to on the Hub
# at download time -- a later push to that repo (a genuine update, or a
# compromised/hijacked one) would silently change which weights this
# project loads, with no way to know it happened. Pinned to the exact
# commit this project has always actually used and tested against
# (confirmed via `huggingface_hub.scan_cache_dir()` against this
# machine's real local cache). A future, deliberate model upgrade
# updates this constant explicitly, rather than an update happening
# invisibly.
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


# Ordinary sentence openers a real, faithful rewrite routinely starts
# with -- allowed regardless of case or position, since flagging every
# sentence-initial capital would reject harmless rewrites, not just
# fabricated ones. Deliberately small and specific to this project's
# own template vocabulary, not a general stopword list.
_COMMON_SENTENCE_STARTERS = {
    "the", "this", "it", "a", "an", "that", "these", "recommended", "its", "you", "your",
}


def _introduces_an_unfounded_capitalized_word(text: str, template: str) -> bool:
    """True if `text` contains a capitalized word that isn't just a
    re-casing of a word the template already had (e.g. "sports" ->
    "SPORTS" is fine) and isn't an ordinary sentence opener -- what a
    real invented proper noun or claim looks like ("The President...",
    "NASA recommends..."). Compared case-insensitively against every
    word in the template, not only the template's own capitalized
    words, and checked by word regardless of position, so a genuine
    proper noun that happens to start the sentence ("NASA...") is still
    caught, not excluded just for being first.

    Not a guarantee against every possible failure mode -- a cheap,
    honest check against the specific failures this project's own real
    testing actually found, not a general hallucination detector.
    """
    template_words = {w.lower() for w in re.findall(r"\b[A-Za-z]+\b", template)}
    for word in re.findall(r"\b[A-Za-z]+\b", text):
        if not word[0].isupper():
            continue
        lowered = word.lower()
        if lowered in _COMMON_SENTENCE_STARTERS or lowered in template_words:
            continue
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
       introduce an unfounded capitalized word absent from the
       deterministic template -- catches the rewrite inventing a claim
       it was never given at all. A real, reproduced example of
       exactly this: given only a content-similarity signal (no
       category to check), the model produced "The President
       personally selected this story for you" and the original
       version of this gate accepted it unchanged, since it only ever
       checked the category-match branch.
    """
    if context.category_match and context.category.lower() not in text.lower():
        return False
    return not _introduces_an_unfounded_capitalized_word(text, template)


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
