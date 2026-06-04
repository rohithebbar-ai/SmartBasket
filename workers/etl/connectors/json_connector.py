# TODO: JSON file connector (e.g. data/sample/hm_sample_100.json)
from .base import BaseConnector
class JSONConnector(BaseConnector):
    async def extract(self, limit=500): raise NotImplementedError
