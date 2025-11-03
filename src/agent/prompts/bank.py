QLIB_GENERATE_INSTRUCTION = """
**Arithmetic / Logic**
- Add(x,y), Sub(x,y), Mul(x,y), Div(x,y)  
- Power(x,y), Log(x), Sqrt(x), Abs(x), Sign(x), Delta(x,n)  
- And(x,y), Or(x,y), Not(x)  
- Sqrt(x), Tanh(x) 
- Comparators: Greater(x,y), Less(x,y), Gt(x,y), Ge(x,y), Lt(x,y), Le(x,y), Eq(x,y), Ne(x,y)

**Rolling (n is positive integer)**
- Mean(x,n), Std(x,n), Var(x,n), Max(x,n), Min(x,n)  
- Skew(x,n), Kurt(x,n), Sum(x,n), Med(x,n), Mad(x,n), Count(x,n)  | Med is for median and Mad for Mean Absolute Deviation
- EMA(x,n), WMA(x,n), Corr(x,y,n), Cov(x,y,n)  
- Slope(x,n), Rsquare(x,n), Resi(x,n)

**Ranking / Conditional**
- Rank(x,n), Ref(x,n), IdxMax(x,n), IdxMin(x,n), Quantile(x,n,qscore (float number between 0-1)) 
- If(cond,x,y), Mask(cond,x), Clip(x,a,b)

Note: function signatures must be complete.  
- Corr(x,y,n) requires 3 arguments 
- Quantile(x,n,qscore) requires 3 arguments
- Rank(x,n) requires 2 arguments  
- Ref(x,n) requires 2 arguments

Important rules:
a. For arithmetic operations, do NOT use symbols. Instead, use: Add for +, Sub for -, Mul for *, Div for /
b. Parentheses must balance.  
c. Correct arity — no missing arguments.  
d. Rolling windows (n) must be positive integers.  
e. Division safety — always add epsilon:  
   - Div(x, Add(den, 1e-12)) correct
   - Div(x, den) incorrect
   Sqrt safely, ensure no negative inputs.
f. No undefined / banned functions (e.g., SMA, RSI), and above operation is low/upper-case sensitive.  
g. Expressions must be plain strings, no comments or backticks.

"""

# src/stock_news_pipeline/agent/prompts/bank.py
"""
Prompt templates collection for news-related agent tasks.

Keep templates simple and parameterized. Use placeholders:
- {news_text}
- {source}
- {published_at}
- {tickers}

These templates are intended to be used with safe formatting utilities in formatter.py.
"""
from typing import Dict

# System-level high-level behavior for the agent
SYSTEM_SUMMARIZE_TEMPLATE = (
    "You are a helpful financial news assistant. Extract structured information and produce a concise summary. "
    "Be precise, use neutral language, and ensure output matches requested schema when provided."
)

# User-level template for summary + extraction
USER_SUMMARIZE_TEMPLATE = (
    "Task: Read the provided news article and perform the following:\n"
    "1) Provide a one-sentence concise summary.\n"
    "2) Extract the main companies mentioned and map to tickers if possible.\n"
    "3) Identify the event type (e.g., earnings, product launch, acquisition, regulation, guidance, other).\n"
    "4) Provide the estimated sentiment (positive/neutral/negative) and a short justification.\n\n"
    "Article (source: {source} | published_at: {published_at} | tickers: {tickers}):\n"
    "{news_text}\n\n"
    "Return the results in JSON. Keys: summary, companies, event_type, sentiment, reasoning. "
    "If a JSON schema is provided, follow it strictly."
)

# Short instruction fragment for tool access (optional)
TOOL_INSTRUCTIONS = (
    "If you need to resolve company names to tickers, you may call an external price/ticker lookup. "
    "When unable to map, return an empty array for tickers."
)

# Example JSON schema the agent can be asked to follow (used to prompt models)
DEFAULT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ticker": {"type": ["string", "null"]},
                },
                "required": ["name", "ticker"],
            },
        },
        "event_type": {"type": "string"},
        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
        "reasoning": {"type": "string"},
    },
    "required": ["summary", "companies", "event_type", "sentiment", "reasoning"],
}