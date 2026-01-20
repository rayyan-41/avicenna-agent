import datetime
import math
from .base import Tool

# --- Actual Functions ---

def get_current_time():
    """Returns the current date and time."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def calculate(expression: str):
    """
    Evaluates a mathematical expression.
    Example: 'sqrt(16) * 2' or '15 * 24'
    """
    # Safety: Limit the calculator to math functions only (no system commands)
    allowed_names = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
    allowed_names["abs"] = abs
    allowed_names["round"] = round
    
    try:
        # We strip dangerous double underscores just in case
        safe_expr = expression.replace("__", "")
        # Evaluate the string as code, but with a restricted namespace
        result = eval(safe_expr, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Math Error: {e}"

# --- Tool Definitions ---

# This list is what we will import into the main agent
BASIC_TOOLS = [
    Tool(
        name="get_current_time",
        func=get_current_time,
        description="Get the current real-world date and time."
    ),
    Tool(
        name="calculate",
        func=calculate,
        description="Perform mathematical calculations. Input should be a python math expression string."
    )
]