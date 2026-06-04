# Abstract connector interface — all connectors implement this
from abc import ABC, abstractmethod

class BaseConnector(ABC):
    @abstractmethod
    async def extract(self, limit: int = 500) -> list[dict]:
        """Pull raw product rows from the source."""
        ...
