import datetime
import math
import ast
import operator
from typing import Union, Dict, Callable, Any
from .base import Tool

# --- Actual Functions ---

def get_current_time() -> str:
    """Returns the current date and time."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def calculate(expression: str) -> str:
    """
    Evaluates a mathematical expression safely using AST parsing.
    Example: 'sqrt(16) * 2' or '15 * 24'
    
    Supported operations: +, -, *, /, **, //, %, and math module functions
    """
    # Define safe operators
    safe_operators: Dict[type, Callable] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }
    
    # Define safe functions from math module
    safe_functions: Dict[str, Callable] = {
        k: v for k, v in math.__dict__.items() 
        if not k.startswith("__") and callable(v)
    }
    safe_functions.update({
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
    })
    
    def eval_node(node: ast.AST) -> Union[int, float]:
        """Recursively evaluate AST nodes."""
        if isinstance(node, ast.Constant):  # Python 3.8+
            return node.value
        elif isinstance(node, ast.Num):  # Python 3.7 fallback
            return node.n
        elif isinstance(node, ast.BinOp):
            left = eval_node(node.left)
            right = eval_node(node.right)
            op_type = type(node.op)
            if op_type not in safe_operators:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            return safe_operators[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            operand = eval_node(node.operand)
            op_type = type(node.op)
            if op_type not in safe_operators:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            return safe_operators[op_type](operand)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only simple function calls are allowed")
            func_name = node.func.id
            if func_name not in safe_functions:
                raise ValueError(f"Function '{func_name}' is not allowed")
            args = [eval_node(arg) for arg in node.args]
            return safe_functions[func_name](*args)
        else:
            raise ValueError(f"Unsupported expression type: {type(node).__name__}")
    
    try:
        # Parse the expression into an AST
        tree = ast.parse(expression, mode='eval')
        # Evaluate the AST safely
        result = eval_node(tree.body)
        return str(result)
    except SyntaxError as e:
        return f"Syntax Error: Invalid expression - {e}"
    except (ValueError, ZeroDivisionError, TypeError) as e:
        return f"Math Error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__} - {e}"

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