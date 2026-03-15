"""
Prompt formatter utilities for agents.

Provides:
- safe_format: safe placeholder replacement without inserting "None"
- sections: assemble system/user/tool sections with clear separators
- generate_news_structured_input: build a structured prompt for news summarization/extraction tasks

This file is designed to integrate with agent/prompts/bank.py-style templates.
"""
from typing import Dict, List, Optional
import json


def safe_format(template: str, values: Dict[str, Optional[str]]) -> str:
    """
    Replace placeholders in template with values.
    - Missing keys raise KeyError to force explicit handling.
    - None values are converted to empty strings (avoids "None" literal).
    """
    if template is None:
        raise ValueError("template must be a string")
    # Ensure keys present: str.format will raise if a placeholder missing.
    sanitized = {k: ("" if v is None else str(v)) for k, v in values.items()}
    try:
        return template.format(**sanitized)
    except KeyError as e:
        # Re-raise with clearer message
        raise KeyError(f"Missing placeholder for key: {e}") from e


def sections(parts: List[Dict[str, str]], sep: str = "\n\n") -> str:
    """
    Assemble prompt sections. Each part is a dict with optional 'title' and required 'content'.
    Returns a single string joining sections with separators and visible titles.
    Example part: {"title": "SYSTEM", "content": "..."}
    """
    out = []
    for p in parts:
        title = p.get("title")
        content = p.get("content", "")
        if title:
            out.append(f"=== {title} ===\n{content}")
        else:
            out.append(content)
    return sep.join(out)


def _ensure_json_schema_hint(schema: Dict) -> str:
    """
    Return a short textual hint for the model describing the expected JSON schema.
    Keeps the model instruction compact but precise.
    """
    # Keep a lightweight representation for model (avoid flooding prompt)
    try:
        # Build compact schema hint
        hint = json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception:
        hint = str(schema)
    return f"Expected JSON schema:\n{hint}"


def generate_news_structured_input(
    system_prompt: str,
    user_template: str,
    news_text: str,
    source: str = "unknown",
    published_at: str = "",
    tickers: Optional[List[str]] = None,
    tool_instructions: str = "",
    json_schema: Optional[Dict] = None,
) -> str:
    """
    Build a structured prompt for news summarization / extraction tasks.

    Parameters:
    - system_prompt: assistant role and high-level behavior
    - user_template: a user-task template with placeholders (e.g., {news_text}, {source}...)
    - news_text: the raw news content to summarize
    - source: source name or URL
    - published_at: timestamp string
    - tickers: optional list of ticker hints
    - tool_instructions: optional extra instructions about tools (price lookup, etc.)
    - json_schema: optional dict describing required JSON keys/types for the model output.
                   If provided, a compact hint will be appended to the prompt.

    Returns:
    - Combined prompt string (SYSTEM + USER + TOOLS sections) ready to pass to llm_client.
    """
    tickers_str = ", ".join(tickers or [])
    user_filled = safe_format(
        user_template,
        {
            "news_text": news_text,
            "source": source,
            "published_at": published_at,
            "tickers": tickers_str,
        },
    )

    parts = [
        {"title": "SYSTEM", "content": system_prompt},
        {"title": "USER", "content": user_filled},
    ]

    if tool_instructions:
        parts.append({"title": "TOOLS", "content": tool_instructions})

    if json_schema:
        parts.append({"title": "OUTPUT_SCHEMA", "content": _ensure_json_schema_hint(json_schema)})

    return sections(parts)