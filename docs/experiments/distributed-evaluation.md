# Evaluating Distributed Recommender Tools

Asks whether TorchRec's distributed embedding/sharding concepts are
justified by anything this project has measured — and
concludes, with numbers, that they aren't. No new code: this
analysis's own framing is conditional ("introduce only if local scale
measurements justify the conclusion"), and the Interpretation here is no.

## What TorchRec actually solves

TorchRec exists to shard embedding tables that are too large to fit on
a single device — industrial-scale recommenders with tables spanning
hundreds of millions to billions of parameters, split across many GPUs
or machines because no single one has enough memory to hold them.

## What this project actually has

The item tower embeds category and subcategory — **17 categories, 264
subcategories** at `embedding_dim=32` — and additionally projects a
64-dimensional per-article content vector into the same space. Counting
every parameter in the trained model:

| Parameter block | Shape | Parameters |
|---|---|---|
| `item_tower.category_emb.weight` | (18, 32) | 576 |
| `item_tower.subcategory_emb.weight` | (265, 32) | 8,480 |
| `item_tower.content_proj.weight` | (32, 64) | 2,048 |
| `item_tower.content_proj.bias` | (32,) | 32 |
| `item_tower.proj.weight` | (32, 96) | 3,072 |
| `item_tower.proj.bias` | (32,) | 32 |
| `global_bias` | (1,) | 1 |
| **Total** | | **14,241** |

14,241 parameters is 55.6 KB at fp32; the serialized model file on disk
is 59 KB. The per-article content vectors are a separate artifact —
`item_content.npz` is 13.7 MB for MIND-small's catalog — and they are
read at index-build and serving time rather than being model parameters.
Even counting them, the whole model plus content matrix is under 14 MB.
The Faiss index
over MIND-small's full ~51,000-item catalog is 6.26 MB; even at
MIND-large's roughly 2× catalog growth (`docs/experiments/mind-large.md`), the
index would land around 12–13 MB — still trivially small enough to sit
in memory on one ordinary machine, let alone need sharding across
several.

## The bottleneck this project actually has

`docs/experiments/load-test.md` found this project's ceiling: single-machine
CPU saturation, at 8 logical cores, confirmed by real concurrent load
testing. That is a horizontal-scaling problem — more machines or
processes serving requests — not the problem TorchRec solves at all.
Sharding a 14,241-parameter model across multiple devices would add
coordination overhead to solve a memory-capacity problem this project
does not have, while doing nothing for the actual, measured
CPU-bound ceiling.

## Conclusion

Every piece of evidence gathered across this component — model size,
index size, catalog size at MIND-large scale, and the measured
bottleneck — points the same direction: this project's scale is many
orders of magnitude below where a distributed embedding framework earns
its cost. The complexity-boundary policy already named this
family of tools as "introduce only if a measured requirement justifies
it" (`docs/architecture.md`); this component produced the measurements, and they say no.
