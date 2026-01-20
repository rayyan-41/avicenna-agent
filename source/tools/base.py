import inspect
from typing import Callable, Any

class Tool:
    """
    Represents a capability that the AI can use.
    It wraps a standard Python function with metadata for the LLM.
    """
    def __init__(self, name: str, func: Callable, description: str):
        self.name = name
        self.func = func
        self.description = description
        # Automatically capture the function signature for validation
        self.signature = inspect.signature(func)

    def to_dict(self) -> dict:
        """
        Converts the tool into a format the LLM can understand.
        """
        return {
            "name": self.name,
            "description": self.description,
        }

    def run(self, **kwargs) -> Any:
        """Executes the actual function with arguments provided by the AI."""
        try:
            return self.func(**kwargs)
        except Exception as e:
            return f"Error executing tool '{self.name}': {str(e)}"
