# TODO: Shopify Admin REST API connector
# Reads products from a Shopify store via SHOPIFY_API_KEY
from .base import BaseConnector
class ShopifyConnector(BaseConnector):
    async def extract(self, limit=500): raise NotImplementedError
