"""
pipeline/sandbox.py — Python execution sandbox for the Data Agent.

Provides a safe-ish environment for executing LLM-generated Python code
using Pandas to analyze records and generate Recharts JSON.
"""
from __future__ import annotations

import ast
import json
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Allowed modules for 'import' or 'from ... import'
ALLOWED_IMPORTS = {"pandas", "pd", "numpy", "np", "json", "math", "collections", "statistics", "datetime", "re"}

# Forbidden names that cannot be called or accessed
FORBIDDEN_NAMES = {
    "exec", "eval", "open", "subprocess", "os", "sys", "shutil", 
    "setattr", "delattr", "globals", "locals"
}

class SandboxError(Exception):
    """Raised when the sandbox rejects a script or execution fails."""
    pass


def execute_data_script(code_str: str, records: list[dict]) -> tuple[str, list[dict]]:
    """
    Execute an LLM-generated Python script against a dataset.

    Args:
        code_str: The Python code to execute.
        records:  The list of enriched records to load into the 'df' variable.

    Returns:
        A tuple of (text_answer, charts_json_list).
    """
    # 1. Security Check (Linting)
    _lint_code(code_str)
    
    logger.info("Executing sandbox script (first 200 chars): %s...", code_str[:200].replace("\n", " "))

    # 2. Prepare Environment
    df = pd.DataFrame(records)

    # These are the variables the script can modify to return data
    output_context = {
        "df": df,
        "pd": pd,
        "json": json,
        "answer": "",
        "charts": []
    }

    try:
        # We MUST include __import__ in builtins so that the 'import' statement works
        # for our ALLOWED_IMPORTS. The linter above ensures only safe modules are imported.
        safe_builtins = {
            k: __builtins__[k] for k in (
                "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable",
                "chr", "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset",
                "getattr", "hasattr", "hash", "hex", "id", "int", "isinstance", "issubclass",
                "iter", "len", "list", "map", "max", "min", "next", "object", "oct", "ord",
                "pow", "print", "property", "range", "repr", "reversed", "round", "set",
                "slice", "sorted", "str", "sum", "tuple", "type", "zip", "__import__",
                "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError",
                "StopIteration", "RuntimeError"
            ) if k in __builtins__ # type: ignore
        }
        
        # Use a restricted global namespace
        exec_globals = {
            "__builtins__": safe_builtins,
            "pd": pd,
            "json": json,
        }
        
        # 3. Execution
        exec(code_str, exec_globals, output_context)

        answer = output_context.get("answer", "")
        charts = output_context.get("charts", [])

        if not isinstance(charts, list):
            logger.warning("Sandbox script returned 'charts' that is not a list: %s", type(charts))
            charts = []

        return str(answer), charts

    except Exception as exc:
        logger.error("Sandbox execution failed: %s", exc)
        # We re-raise as SandboxError to be caught by the app task handler
        raise SandboxError(f"Execution error: {exc}") from exc


def _lint_code(code_str: str) -> None:
    """
    Analyze the AST of the code to block dangerous calls or imports.
    """
    if not code_str.strip():
        raise SandboxError("Generated code is empty.")

    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        raise SandboxError(f"Syntax error in generated code: {e}")

    for node in ast.walk(tree):
        # A. Block forbidden imports (Import)
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_base = alias.name.split(".")[0]
                if module_base not in ALLOWED_IMPORTS:
                    raise SandboxError(f"Import of module '{alias.name}' is forbidden.")
        
        # B. Block forbidden imports (ImportFrom)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_base = node.module.split(".")[0]
                if module_base not in ALLOWED_IMPORTS:
                    raise SandboxError(f"Import from module '{node.module}' is forbidden.")
            else:
                # Relative imports (from . import ...) are also blocked
                raise SandboxError("Relative imports are forbidden.")
        
        # C. Block forbidden function calls
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_NAMES:
                raise SandboxError(f"Call to forbidden function '{node.func.id}' is blocked.")
            if node.func.id == "__import__":
                raise SandboxError("Direct calls to __import__ are blocked.")
        
        # D. Block access to private/internal attributes (e.g. __subclasses__)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr != "__name__":
                raise SandboxError(f"Access to private attribute '{node.attr}' is blocked.")

    logger.debug("Sandbox linting passed.")
