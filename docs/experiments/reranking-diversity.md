# Diversity reranking

The ranker scores individual items. Diversity reranking adjusts the
top-10 as a group.

Implementation: `src/recommender/reranking/diversity.py`.

## Measured before building anything

The initial measurement used 3,000 validation impressions:

| Observation | Value |
|---|---|
| Slates with at least 4 items from one category | 53.1% |
| Slates containing one category only | 4.6% |
| Mean pairwise TF-IDF similarity | 0.017 |
| Median pairwise TF-IDF similarity | 0.0 |
| Pairs with similarity at least 0.5 | About 0.25% |
| Pairs with similarity at least 0.7 | About 0.12% |

Category concentration is common; near-duplicate text is rare. The
category cap therefore does most of the work. A 0.5 similarity threshold
acts as a secondary duplicate guard.

## The policy

`build_diverse_slate` follows the ranker's score order:

1. Sort candidates by score.
2. Select a candidate unless its category already has 3 items or its
   TF-IDF similarity with a selected item is at least 0.5.
3. If fewer than K items remain, fill the open positions by score
   without constraints.

The policy may reorder a slate, but it does not shorten one.

## Verification

`tests/test_diversity.py` confirms that:

- the category cap blocks an excess item;
- an exact duplicate is suppressed even when the category cap allows it;
- relaxed fill returns K items when enough candidates exist; and
- the output never contains more items than the input.
