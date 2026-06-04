"""
H&M connector — streams from HuggingFace `Qdrant/hm_ecommerce_products`.

The dataset has pre-built embeddings and image URLs hosted on S3.
We ignore the pre-built embeddings and generate our own with Jina v3.
"""
import logging
from typing import AsyncIterator

from .base import BaseConnector

log = logging.getLogger(__name__)

HM_SCHEMA = [
    "article_id", "prod_name", "product_type_name", "product_group_name",
    "graphical_appearance_name", "colour_group_name", "perceived_colour_master_name",
    "department_name", "index_group_name", "section_name", "garment_group_name",
    "detail_desc", "image_url",
]


class HMConnector(BaseConnector):
    """Streams H&M fashion products from HuggingFace."""

    def validate_connection(self) -> bool:
        try:
            import datasets  # noqa: F401
            return True
        except ImportError:
            log.error("datasets library not installed — run: uv add datasets")
            return False

    async def extract(self, limit: int = 500) -> list[dict]:
        """Not used — use fetch_batches() for streaming."""
        rows = []
        async for batch in self.fetch_batches(limit=limit):
            rows.extend(batch)
        return rows

    async def fetch_batches(
        self, limit: int = 500, batch_size: int = 100
    ) -> AsyncIterator[list[dict]]:
        """Yields batches of raw H&M product dicts, up to `limit` total rows."""
        import datasets as hf_datasets

        # Disable local caching — data streams directly to Supabase, nothing written to disk
        hf_datasets.disable_caching()

        log.info("Loading H&M dataset from HuggingFace (streaming, no local cache)…")
        ds = hf_datasets.load_dataset(
            "Qdrant/hm_ecommerce_products",
            split="train",
            streaming=True,
        )

        batch: list[dict] = []
        total = 0

        for row in ds:
            if limit and total >= limit:
                break
            batch.append(row)
            total += 1
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

        log.info("HM connector: streamed %d rows total", total)

    def get_schema(self) -> list[str]:
        return HM_SCHEMA
