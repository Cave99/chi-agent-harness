"""
pipeline/sandbox.py — Python execution sandbox for the Data Agent.

Provides a safe-ish environment for executing LLM-generated Python code
using Pandas to analyze records and generate Recharts JSON.
"""
from __future__ import annotations

import ast
import base64
import io
import json
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

ALLOWED_IMPORTS = {"pandas", "json", "math", "collections", "statistics", "datetime"}
FORBIDDEN_NAMES = {
    "exec", "eval", "open", "subprocess", "os", "sys", "shutil", 
    "__import__", "getattr", "setattr", "delattr", "globals", "locals"
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
    _lint_code(code_str)

    df = pd.DataFrame(records)

    # We expect the script to populate these variables
    output_context = {
        "df": df,
        "pd": pd,
        "json": json,
        "answer": "",
        "charts": []
    }

    try:
        # Use a restricted global namespace
        exec_globals = {
            "__builtins__": {
                k: __builtins__[k] for k in (
                    "abs", "all", "any", "bool", "dict", "enumerate", "float", 
                    "int", "len", "list", "map", "max", "min", "range", "round", 
                    "set", "sorted", "str", "sum", "tuple", "zip", "print"
                ) if k in __builtins__ # type: ignore
            },
            "pd": pd,
            "json": json,
        }
        
        # Execute the script
        exec(code_str, exec_globals, output_context)

        answer = output_context.get("answer", "")
        charts = output_context.get("charts", [])

        if not isinstance(charts, list):
            logger.warning("Sandbox script returned 'charts' that is not a list: %s", type(charts))
            charts = []

        return str(answer), charts

    except Exception as exc:
        logger.exception("Sandbox execution failed")
        raise SandboxError(f"Execution error: {exc}") from exc


def _lint_code(code_str: str) -> None:
    """
    Analyze the AST of the code to block dangerous calls or imports.
    """
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        raise SandboxError(f"Syntax error in generated code: {e}")

    for node in ast.walk(tree):
        # Block forbidden imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name not in ALLOWED_IMPORTS:
                    raise SandboxError(f"Import of '{name}' is forbidden.")
        
        # Block forbidden function calls
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_NAMES:
                raise SandboxError(f"Call to '{node.func.id}' is forbidden.")
        
        # Block access to forbidden attributes (e.g. __subclasses__)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                raise SandboxError(f"Access to private attribute '{node.attr}' is forbidden.")

    logger.debug("Sandbox linting passed.")
