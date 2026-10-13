"""Tool registry. Every tool the model may call is declared here as a Tool.

To add a tool later:
  1. write a handler(**resolved_args) -> dict (JSON-serialisable result)
  2. write a validator(raw_args, scope) -> resolved_args  (raise ValidationError)
  3. register(Tool(...)) and add an example section to help.md
"""
from dataclasses import dataclass, field
from typing import Callable, Any, Optional


class ValidationError(Exception):
    """Raised when the model's tool call does not make sense.

    kind: "invalid" | "not_found" | "ambiguous" | "out_of_scope" | "unavailable"
    folder: for out_of_scope, the directory the user could grant access to.
    """

    def __init__(self, message: str, kind: str = "invalid", folder=None):
        super().__init__(message)
        self.kind = kind
        self.folder = folder


class ToolError(Exception):
    """Raised by a handler when execution fails for a reason the user should hear."""


@dataclass
class Tool:
    name: str
    description: str
    params: dict                         # JSON-schema "properties" for the args
    required: list
    handler: Callable[..., dict]
    validate: Callable[[dict, Any], dict]
    confirm: bool = False                # must the user approve before running?
    describe: Optional[Callable[[dict], str]] = None   # sentence shown at the gate
    read_only: bool = True


TOOLS: dict = {}


def register(tool: Tool) -> Tool:
    TOOLS[tool.name] = tool
    return tool


def tool_names() -> list:
    return list(TOOLS.keys())


def merged_arg_properties() -> dict:
    """Union of all tools' arg schemas, used for the flat constrained-output schema."""
    merged = {}
    for t in TOOLS.values():
        for k, v in t.params.items():
            merged.setdefault(k, v)
    return merged


def render_tool_docs() -> str:
    """Human/LLM-readable listing of tools for the system prompt."""
    lines = []
    for t in TOOLS.values():
        args = ", ".join(
            f"{k}{'' if k in t.required else '?'}: {v.get('type','string')}"
            for k, v in t.params.items()
        )
        gate = " [needs user approval]" if t.confirm else ""
        lines.append(f"- {t.name}({args}){gate}: {t.description}")
    return "\n".join(lines)
