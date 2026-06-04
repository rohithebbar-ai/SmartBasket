# TODO: Snowflake connector — reads from a client's Snowflake warehouse
# Credentials injected via env (SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD)
from .base import BaseConnector
class SnowflakeConnector(BaseConnector):
    async def extract(self, limit=500): raise NotImplementedError
