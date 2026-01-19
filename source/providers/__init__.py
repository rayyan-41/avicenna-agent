from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """
    Abstract Base Class that all AI models must implement.
    This allows Avicenna to swap brains without changing core logic.
    """
    
    @abstractmethod
    def send_message(self, message: str, history: list = None) -> str:
        """Send a message to the model and get a text response."""
        pass
    
    @abstractmethod
    def clear_history(self):
        """Reset the conversation memory."""
        pass