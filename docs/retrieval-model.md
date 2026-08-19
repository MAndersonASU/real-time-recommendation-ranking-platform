# Two-Tower Retrieval Model

Phase 3's first learned model. Architecture and training only — full
retrieval evaluation against the frozen protocol
(`docs/evaluation-protocol.md`) is a separate, later evaluation pass, not
this one. Implementation: `src/recommender/retrieval/` (`features.py`,
`model.py`, `dataset.py`, `train.py`).

## Architecture

- **Item tower**: category + subcategory embeddings, concatenated and
  projected to a 32-dimensional vector. Defined for every catalog item
  regardless of click history, since these features never depend on it.
- **User tower**: not a separate set of parameters. A user's vector is the
  mean of the item tower's vectors for whatever's in their (fixed-length,
  masked) click history — the same idea as the earlier content-similarity
  baseline (`docs/baselines.md`), now built from learned rather than fixed
  vectors.
- **History length**: capped at the 20 most recent items (median training
  history length: 19; 90th percentile: 77; max: 558 — a fixed cap keeps
  batching tractable without variable-length sequence handling).
- **Score**: dot product of the user and item vectors, plus a single
  learnable global bias term.
- **Training labels**: the click/no-click labels MIND's own impression log
  already provides — not yet a deliberately engineered negative-sampling
  strategy, which is explicitly out of scope here and reserved for
  dedicated follow-up work.

## A real bug found during verification, not glossed over

The first full training run (one epoch, 2,257 steps, no bias term) plateaued
at a loss of ~0.675 and stopped improving. Before accepting that as "trained,"
it was checked against the actual entropy floor for this problem: with the
training set's real class balance (~4% positive), a trivial model that always
predicts the base rate achieves a binary cross-entropy loss of exactly
`-p·ln(p) - (1-p)·ln(1-p) ≈ 0.168`. The model's plateau (0.675) sat far above
even that trivial floor — it hadn't learned the base rate, let alone anything
about individual users or items.

The cause: the score was a raw dot product with nothing else, so representing
"clicks are rare overall" required the embedding geometry itself to encode it
— a slow, indirect path for gradient descent. Adding a single learnable
scalar (`global_bias`, added to the dot product) let the model absorb the
base rate directly. Re-run under the same conditions, loss dropped steadily
and predictably instead of plateauing early.

## Real training result

6,000 steps, batch size 2,048, embedding dimension 32, on the `train`
split (`docs/splits.md`, 4,621,015 examples) — about 1.3 passes over the
full training set. Elapsed: 7m35s locally (CPU only).

| Step | Mean loss (last 500) |
|---|---|
| 500 | 0.6288 |
| 1,500 | 0.3437 |
| 3,000 | 0.2140 |
| 4,500 | 0.1774 |
| 6,000 | 0.1678 |

Final loss (0.1678) essentially matches the theoretical entropy floor
(0.1679) for this label distribution — confirmation the bias-term fix
worked and training is behaving correctly, not evidence by itself that the
embeddings learned meaningful per-user or per-item signal beyond the base
rate. Distinguishing "the model learned the base rate" from "the model
learned to actually rank candidates well" is exactly what a dedicated
evaluation pass against the frozen protocol is for, using the same Recall@K,
NDCG@K, MRR, hit rate, and catalog coverage metrics already applied to all
three Phase 2 baselines — not something this step's training loss can
answer on its own.

Model saved to `data/processed/mind_small/two_tower_model.pt` (gitignored,
reproducible via `python -m recommender.retrieval.train`); reload verified
to reproduce the trained parameters exactly before treating this step as
done.
