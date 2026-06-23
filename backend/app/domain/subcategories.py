from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CategoryBatch:
    name: str
    slug: str
    df: pd.DataFrame


def split_by_subcategory(df: pd.DataFrame) -> list[CategoryBatch]:
    if "Sub Category" not in df.columns:
        raise KeyError("Input workbook must contain 'Sub Category'.")

    output = df.copy()
    output["Sub Category"] = output["Sub Category"].apply(normalize_subcategory_name)
    category_names = output["Sub Category"].drop_duplicates().tolist()
    slug_map = build_unique_slug_map(category_names)
    return [
        CategoryBatch(
            name=category_name,
            slug=slug_map[category_name],
            df=output.loc[output["Sub Category"] == category_name].reset_index(drop=True).copy(),
        )
        for category_name in category_names
    ]


def normalize_subcategory_name(value: object) -> str:
    if pd.isna(value):
        return "Uncategorized"

    name = str(value).strip()
    return name or "Uncategorized"


def build_unique_slug_map(category_names: list[str]) -> dict[str, str]:
    slug_counts: dict[str, int] = {}
    slug_map: dict[str, str] = {}

    for category_name in category_names:
        base_slug = slugify(category_name)
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        suffix = slug_counts[base_slug]
        slug_map[category_name] = base_slug if suffix == 1 else f"{base_slug}-{suffix}"

    return slug_map


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "uncategorized"
