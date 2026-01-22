"""MCP Server for Basic Tools (time, calculator)"""
import sys
from pathlib import Path
from datetime import datetime
import ast
import operator

# Add parent directory to path for imports when run as main
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Basic Tools")

# Safe math operators
OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}

def evaluate_expression(node):
    """Safely evaluate a mathematical expression AST node"""
    if isinstance(node, ast.Constant):  # Python 3.8+
        return node.value
    elif isinstance(node, ast.BinOp):
        left = evaluate_expression(node.left)
        right = evaluate_expression(node.right)
        return OPERATORS[type(node.op)](left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = evaluate_expression(node.operand)
        return OPERATORS[type(node.op)](operand)
    else:
        raise ValueError(f"Unsupported operation: {type(node).__name__}")

@mcp.tool()
def get_current_time() -> str:
    """
    Returns the current system date and time.
    
    Use this when the user asks for the current time, date, or day.
    Returns a human-readable timestamp.
    """
    return datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

@mcp.tool()
def calculate(expression: str) -> str:
    """
    Safely evaluates a mathematical expression.
    
    Supports: +, -, *, /, %, ** (power), parentheses
    Example: "2 + 2" returns "4"
    Example: "10 ** 2" returns "100"
    
    Args:
        expression: A mathematical expression as a string
        
    Returns:
        The result of the calculation as a string
    """
    try:
        # Remove whitespace
        expression = expression.strip()
        
        # Parse into AST
        tree = ast.parse(expression, mode='eval')
        
        # Evaluate safely
        result = evaluate_expression(tree.body)
        
        return str(result)
    except Exception as e:
        return f"❌ Calculation error: {str(e)}"

if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
