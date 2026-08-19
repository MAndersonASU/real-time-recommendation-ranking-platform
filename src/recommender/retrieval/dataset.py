import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


class TwoTowerDataset(Dataset):
    """One example per (impression, candidate item) pair. History arrays
    are stored once per impression and looked up by index, not duplicated
    per candidate row.
    """

    def __init__(
        self,
        exploded,
        impression_row: pd.Series,
        history_category: np.ndarray,
        history_subcategory: np.ndarray,
        history_mask: np.ndarray,
        item_vocab: dict,
    ):
        self.impression_row = exploded["impression_id"].map(impression_row).to_numpy()
        cand_cat, cand_subcat = zip(*(item_vocab.get(nid, (0, 0)) for nid in exploded["news_id"]))
        self.cand_category = np.array(cand_cat, dtype=np.int64)
        self.cand_subcategory = np.array(cand_subcat, dtype=np.int64)
        self.labels = exploded["clicked"].to_numpy().astype(np.float32)

        self.history_category = history_category
        self.history_subcategory = history_subcategory
        self.history_mask = history_mask

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int):
        row = self.impression_row[idx]
        return (
            torch.from_numpy(self.history_category[row]),
            torch.from_numpy(self.history_subcategory[row]),
            torch.from_numpy(self.history_mask[row]),
            torch.tensor(self.cand_category[idx]),
            torch.tensor(self.cand_subcategory[idx]),
            torch.tensor(self.labels[idx]),
        )
