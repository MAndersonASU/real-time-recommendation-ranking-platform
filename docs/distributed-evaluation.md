# Evaluating Distributed Recommender Tools

Asks whether TorchRec's distributed embedding/sharding concepts are
justified by anything this project has actually measured — and
concludes, with real numbers, that they aren't. No new code: this
step's own framing is conditional ("introduce only if local scale
measurements justify the lesson"), and the honest answer here is no.

## What TorchRec actually solves

TorchRec exists to shard embedding tables that are too large to fit on
a single device — industrial-scale recommenders with tables spanning
hundreds of millions to billions of parameters, split across many GPUs
or machines because no single one has enough memory to hold them.

## What this project actually has

This project's two-tower model embeds only category and subcategory —
**17 categories, 264 subcategories**, at `embedding_dim=32`. The entire
embedding table:

```
(17 + 1 + 264 + 1) categories/subcategories × 32 dims × 4 bytes ≈ 35.4 KB
```

Thirty-five kilobytes. `docs/profile-hotspots.md` measured the actual
serialized model file at 0.05 MB, consistent with this. The Faiss index
over MIND-small's full ~51,000-item catalog is 6.26 MB; even at
MIND-large's roughly 2× catalog growth (`docs/mind-large.md`), the
index would land around 12–13 MB — still trivially small enough to sit
in memory on one ordinary machine, let alone need sharding across
several.

## The bottleneck this project actually has

`docs/load-test.md` found this project's real ceiling: single-machine
CPU saturation, at 8 logical cores, confirmed by real concurrent load
testing. That is a horizontal-scaling problem — more machines or
processes serving requests — not the problem TorchRec solves at all.
Sharding a 35 KB embedding table across multiple devices would add
real coordination overhead to solve a memory-capacity problem this
project doesn't have, while doing nothing for the actual, measured
CPU-bound ceiling.

## Conclusion

Every piece of real evidence gathered across this phase — model size,
index size, catalog size at MIND-large scale, and the actual measured
bottleneck — points the same direction: this project's scale is many
orders of magnitude below where a distributed embedding framework earns
its real cost. The complexity-boundary policy already named this
family of tools as "introduce only if a measured requirement justifies
it" (`docs/architecture.md`); this phase produced the actual
measurements, and they say no.
