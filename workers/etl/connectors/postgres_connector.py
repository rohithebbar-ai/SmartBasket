# TODO: PostgreSQL connector — read products from a client's existing Postgres DB
from .base import BaseConnector
class PostgresConnector(BaseConnector):
    async def extract(self, limit=500): raise NotImplementedError
