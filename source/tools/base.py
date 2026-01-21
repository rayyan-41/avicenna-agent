import inspect
from typing import Callable, Any, Dict


class Tool:
    """
    Represents a capability that the AI can use.
    It wraps a standard Python function with metadata for the LLM.
    """
    def __init__(self, name: str, func: Callable[..., Any], description: str) -> None:
        self.name: str = name
        self.func: Callable[..., Any] = func
        self.description: str = description
        # Automatically capture the function signature for validation
        self.signature = inspect.signature(func)

    def to_dict(self) -> Dict[str, str]:
        """
        Converts the tool into a format the LLM can understand.
        """
        return {
            "name": self.name,
            "description": self.description,
        }

    def run(self, **kwargs: Any) -> Any:
        """Executes the actual function with arguments provided by the AI."""
        try:
            return self.func(**kwargs)
        except TypeError as e:
            return f"Error: Invalid arguments for tool '{self.name}': {str(e)}"
        except ValueError as e:
            return f"Error: Invalid values for tool '{self.name}': {str(e)}"
        except Exception as e:
            return f"Error executing tool '{self.name}': {type(e).__name__} - {str(e)}"
