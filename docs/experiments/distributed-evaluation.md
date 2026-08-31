# Distributed-tooling decision

The measured model and index fit easily on one machine. TorchRec-style
embedding sharding is not justified for this project.

## What TorchRec actually solves

TorchRec distributes embedding tables that cannot fit on one device.
That is a memory-capacity solution for models with very large parameter
tables.

## What this project actually has

The current item tower has 17 categories, 264 subcategories, a
32-dimensional embedding, and a projection from a 64-dimensional
content vector.

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

At fp32, 14,241 parameters require 55.6 KB; the saved model is 59 KB.
`item_content.npz` is a separate 13.7 MB artifact. Together they remain
under 14 MB.

The MIND-small Faiss index is 6.26 MB. At roughly twice the catalog size,
MIND-large would produce an estimated 12–13 MB index. These files do not
need multi-device sharding.

## The bottleneck this project actually has

The [load test](load-test.md) found CPU saturation on an 8-logical-core
machine. More serving processes or machines could address that limit.
Splitting a 14,241-parameter model would add coordination without fixing
CPU request throughput.

## Conclusion

Do not add distributed embedding infrastructure at the current scale.
Reconsider only if model or index memory no longer fits on one target
device.

See [architecture](../architecture.md) and
[MIND-large scale check](mind-large.md).
