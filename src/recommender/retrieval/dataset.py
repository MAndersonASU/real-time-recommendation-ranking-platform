import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


class TwoTowerDataset(Dataset):
    """One example per (impression, candidate item) pair. History arrays
    are stored once per impression and looked up by index, not duplicated
    per candidate row.

    Content vectors are gathered per example out of the shared catalog
    content matrix rather than stored per row: the matrix is one array
    for the whole catalog, while a materialized per-example copy of the
    history's content would be (examples x max_history x content_dim)
    floats -- far larger than the split itself.
    """

    def __init__(
        self,
        exploded,
        impression_row: pd.Series,
        history_category: np.ndarray,
        history_subcategory: np.ndarray,
        history_mask: np.ndarray,
        history_item_rows: np.ndarray,
        item_vocab: dict,
        content_matrix: np.ndarray,
        row_by_news_id: dict,
    ):
        self.impression_row = exploded["impression_id"].map(impression_row).to_numpy()
        cand_cat, cand_subcat = zip(*(item_vocab.get(nid, (0, 0)) for nid in exploded["news_id"]))
        self.cand_category = np.array(cand_cat, dtype=np.int64)
        self.cand_subcategory = np.array(cand_subcat, dtype=np.int64)
        self.cand_item_row = np.array(
            [row_by_news_id.get(nid, 0) for nid in exploded["news_id"]], dtype=np.int64
        )
        self.labels = exploded["clicked"].to_numpy().astype(np.float32)

        self.history_category = history_category
        self.history_subcategory = history_subcategory
        self.history_mask = history_mask
        self.history_item_rows = history_item_rows
        self.content_matrix = content_matrix

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int):
        row = self.impression_row[idx]
        return (
            torch.from_numpy(self.history_category[row]),
            torch.from_numpy(self.history_subcategory[row]),
            torch.from_numpy(self.history_mask[row]),
            torch.from_numpy(self.content_matrix[self.history_item_rows[row]]),
            torch.tensor(self.cand_category[idx]),
            torch.tensor(self.cand_subcategory[idx]),
            torch.from_numpy(self.content_matrix[self.cand_item_row[idx]]),
            torch.tensor(self.labels[idx]),
        )


class SampledNegativeDataset(Dataset):
    """One example per (positive impression, sampled random negative
    item). Reuses the same per-impression history arrays as
    TwoTowerDataset -- a sampled negative is evaluated against that same
    user's history, not a different one. Output shape matches
    TwoTowerDataset exactly, so the two combine via ConcatDataset.
    """

    def __init__(
        self,
        impression_rows: np.ndarray,
        negative_rows: np.ndarray,
        history_category: np.ndarray,
        history_subcategory: np.ndarray,
        history_mask: np.ndarray,
        history_item_rows: np.ndarray,
        catalog_category: np.ndarray,
        catalog_subcategory: np.ndarray,
        content_matrix: np.ndarray,
    ):
        num_negatives = negative_rows.shape[1]
        self.impression_row = np.repeat(impression_rows, num_negatives)
        self.negative_row = negative_rows.ravel()

        self.history_category = history_category
        self.history_subcategory = history_subcategory
        self.history_mask = history_mask
        self.history_item_rows = history_item_rows
        self.catalog_category = catalog_category
        self.catalog_subcategory = catalog_subcategory
        self.content_matrix = content_matrix

    def __len__(self) -> int:
        return len(self.negative_row)

    def __getitem__(self, idx: int):
        row = self.impression_row[idx]
        neg_row = self.negative_row[idx]
        return (
            torch.from_numpy(self.history_category[row]),
            torch.from_numpy(self.history_subcategory[row]),
            torch.from_numpy(self.history_mask[row]),
            torch.from_numpy(self.content_matrix[self.history_item_rows[row]]),
            torch.tensor(self.catalog_category[neg_row]),
            torch.tensor(self.catalog_subcategory[neg_row]),
            torch.from_numpy(self.content_matrix[neg_row]),
            torch.tensor(0.0),
        )
