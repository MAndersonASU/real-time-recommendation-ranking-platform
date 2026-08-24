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
- **Training labels**: MIND's own in-impression click/no-click labels,
  plus randomly sampled catalog negatives per positive example (see
  "Negative sampling" below) — narrow reranking-style negatives alone
  aren't sufficient once the model has to judge the full catalog, not a
  pre-filtered shortlist.

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

## Initial training result (in-impression negatives only)

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

## Negative sampling

In-impression negatives were only ever items MIND's own candidate
generation already considered relevant enough to show — a narrow signal,
adequate for reranking a pre-filtered shortlist but not for retrieval,
which has to judge the entire catalog. Every positive example now also
gets 4 randomly sampled catalog items as additional negatives
(`src/recommender/retrieval/negatives.py`), rejected and redrawn if the
sampled item is one that specific user is actually known to have clicked
elsewhere in `train` — an unfiltered random negative that happens to be
something the user likes would be false training data, not harmless
noise. The click history used for this check is built exclusively from
`train`; using validation or replay clicks here would leak evaluation-time
information into what training treats as a legitimate negative.

Implementation: `build_catalog_arrays` and `build_user_clicked_rows`
(`features.py`), `sample_negative_rows`/`sample_negatives_for_positives`
(`negatives.py`), `SampledNegativeDataset` (`dataset.py`) — combined with
the original in-impression dataset via `ConcatDataset`. The model, loss
function, and training loop from the initial run are unchanged; only what
feeds into them changed.

### Real result with sampled negatives added

Same 6,000-step budget, same batch size and embedding dimension, for a
direct comparison against the initial run. Dataset grew from 4,621,015 to
5,379,091 examples (189,519 real positive clicks × 4 sampled negatives
each = 758,076 added rows — matches the arithmetic exactly). Elapsed:
8m3s locally.

| Step | Mean loss (last 500) |
|---|---|
| 500 | 0.6189 |
| 1,500 | 0.3366 |
| 3,000 | 0.2012 |
| 4,500 | 0.1609 |
| 6,000 | 0.1510 |

Adding sampled negatives changes the overall label balance (positives now
3.52% of examples, down from 4.04%), so the entropy floor to compare
against is a different, recomputed number:
`-0.03523·ln(0.03523) - 0.96477·ln(0.96477) ≈ 0.1525`. Final loss (0.1510)
again essentially matches this recomputed floor — the same honest
conclusion as before: this confirms training is behaving correctly for
the new label distribution, not that the embeddings have learned
meaningful signal beyond the base rate. That's still a question for a
dedicated evaluation pass against the frozen protocol, not for training
loss alone.

Model saved to `data/processed/mind_small/two_tower_model.pt` (gitignored,
reproducible via `python -m recommender.retrieval.train`); reload verified
to reproduce the trained parameters exactly before treating this step as
done.


## Item tower features: category, subcategory, and per-article content

The item tower originally encoded an article from its category and
subcategory alone. Those two fields take only 284 distinct combinations
across a 51,282-item catalog, so the tower emitted 284 distinct vectors
and retrieval could identify a topic but never an article within it
(`docs/retrieval-evaluation.md`, `docs/faiss-index.md`).

Each article now also carries a dense content vector built from its own
title and abstract: TF-IDF reduced to a fixed width by `TruncatedSVD`
and row-normalized (`build_item_content_matrix` in
`src/recommender/retrieval/features.py`). The item tower projects that
alongside the two embeddings and mixes them in a single linear layer.

Two properties of this choice matter:

- **Content-derived, not id-derived.** There is no per-item embedding
  table, so an article never seen during training still receives a real
  vector from its own text. The tower keeps working for cold items,
  which an id-embedding approach would have given up.
- **Deterministic.** `TruncatedSVD` uses a randomized solver, so it is
  seeded for the same reason training is — a retrained model has to be
  reproducible, and the catalog vectors feed both training and serving.

Measured effect: distinct catalog embeddings rose from 284 to 50,704,
and every retrieval metric improved by 7.6x to 13.5x
(`docs/retrieval-evaluation.md`). The user tower is unchanged — it is
still the masked mean of the item tower's vectors over a user's click
history, so it inherits the richer item representation automatically.
