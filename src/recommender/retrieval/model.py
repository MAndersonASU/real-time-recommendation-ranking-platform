import torch
from torch import nn

from recommender.retrieval.features import CONTENT_DIM


class ItemTower(nn.Module):
    """Category + subcategory + the article's own content vector -> item
    vector. Works for any catalog item, seen or unseen during training,
    since none of these features depend on click history or on an
    item-id embedding table.

    The content vector is what makes two articles in the same
    subcategory distinguishable. Category and subcategory together take
    only 284 distinct values across this catalog's 51,282 items, so a
    tower built from them alone emits just 284 distinct vectors and
    retrieval can only ever identify the right topic, never the right
    article inside it (`docs/experiments/retrieval-evaluation.md`).
    """

    def __init__(
        self,
        num_categories: int,
        num_subcategories: int,
        embedding_dim: int = 32,
        content_dim: int = CONTENT_DIM,
    ):
        super().__init__()
        self.category_emb = nn.Embedding(num_categories, embedding_dim)
        self.subcategory_emb = nn.Embedding(num_subcategories, embedding_dim)
        self.content_proj = nn.Linear(content_dim, embedding_dim)
        self.proj = nn.Linear(embedding_dim * 3, embedding_dim)

    def forward(
        self,
        category_idx: torch.Tensor,
        subcategory_idx: torch.Tensor,
        content_vec: torch.Tensor,
    ) -> torch.Tensor:
        x = torch.cat(
            [
                self.category_emb(category_idx),
                self.subcategory_emb(subcategory_idx),
                self.content_proj(content_vec),
            ],
            dim=-1,
        )
        return self.proj(x)


class TwoTowerModel(nn.Module):
    """User tower is not a separate set of parameters -- it's the mean of
    the item tower's vectors for whatever's in the user's click history,
    masked so padding positions never contribute.
    """

    def __init__(
        self,
        num_categories: int,
        num_subcategories: int,
        embedding_dim: int = 32,
        content_dim: int = CONTENT_DIM,
    ):
        super().__init__()
        self.item_tower = ItemTower(num_categories, num_subcategories, embedding_dim, content_dim)
        # A raw dot product has no way to represent "clicks are rare overall"
        # except by learning it into the embedding geometry itself, which is
        # slow. One learnable scalar lets the model absorb the base click
        # rate immediately, leaving the embeddings free to learn real signal.
        self.global_bias = nn.Parameter(torch.zeros(1))

    def user_vector(
        self,
        history_category_idx: torch.Tensor,
        history_subcategory_idx: torch.Tensor,
        history_mask: torch.Tensor,
        history_content: torch.Tensor,
    ) -> torch.Tensor:
        item_vecs = self.item_tower(
            history_category_idx, history_subcategory_idx, history_content
        )
        mask = history_mask.unsqueeze(-1)
        summed = (item_vecs * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1.0)
        return summed / counts

    def item_vector(
        self,
        category_idx: torch.Tensor,
        subcategory_idx: torch.Tensor,
        content_vec: torch.Tensor,
    ) -> torch.Tensor:
        return self.item_tower(category_idx, subcategory_idx, content_vec)

    def forward(
        self,
        history_category_idx: torch.Tensor,
        history_subcategory_idx: torch.Tensor,
        history_mask: torch.Tensor,
        history_content: torch.Tensor,
        cand_category_idx: torch.Tensor,
        cand_subcategory_idx: torch.Tensor,
        cand_content: torch.Tensor,
    ) -> torch.Tensor:
        u = self.user_vector(
            history_category_idx, history_subcategory_idx, history_mask, history_content
        )
        v = self.item_vector(cand_category_idx, cand_subcategory_idx, cand_content)
        return (u * v).sum(dim=-1) + self.global_bias
