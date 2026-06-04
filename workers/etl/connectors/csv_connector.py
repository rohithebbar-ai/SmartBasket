# TODO: CSV file connector
# Reads a local CSV, returns list[dict] up to limit rows
from .base import BaseConnector
class CSVConnector(BaseConnector):
    async def extract(self, limit=500): raise NotImplementedError
