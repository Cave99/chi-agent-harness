from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class BaseAgent(ABC):
    """
    Base class for all agents in the Chi Explorer ecosystem.
    Enforces a consistent interface for running analysis and streaming results.
    """
    
    @abstractmethod
    def run(self, *args, **kwargs) -> Any:
        """Execute the agent's primary logic synchronously or in a thread."""
        pass

    @abstractmethod
    async def run_async(self, *args, **kwargs) -> Any:
        """Execute the agent's primary logic asynchronously."""
        pass
