# src/tools/builtins.py
"""
Built-in stateless tools for the Nova agent.

All tools return a plain string (or JSON string) that gets fed back to the LLM.
No tool here requires confirmation — they are read-only / side-effect-free.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from src.tools import Tool


# ── 1. get_current_datetime ──────────────────────────────────────────────────

def _get_current_datetime() -> str:
    """Return the current date, time, day of week, and timezone."""
    # FIX #18: explicitly create a timezone-aware datetime instead of
    # calling .astimezone() on a naive datetime (which is implicit and
    # triggers DeprecationWarning in some Python versions).
    now = datetime.now(timezone.utc).astimezone()
    return (
        f"Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}. "
        f"Timezone: {now.tzname()}."
    )


GET_CURRENT_DATETIME = Tool(
    name="get_current_datetime",
    description="Get the current date, time, day of week, and timezone.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    handler=_get_current_datetime,
    requires_confirmation=False,
)


# ── 2. web_search ────────────────────────────────────────────────────────────

def _web_search(query: str) -> str:
    """Search the web via DuckDuckGo and return top 3 results."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return json.dumps({"error": "duckduckgo-search not installed. Run: pip install duckduckgo-search"})

    try:
        ddgs = DDGS()
        results = list(ddgs.text(query, max_results=3))
    except Exception as e:
        return json.dumps({"error": f"Web search failed: {str(e)}"})

    if not results:
        return "No results found."

    return "\n\n".join(
        f"**{r['title']}**\n{r['body']}\nURL: {r['href']}"
        for r in results
    )


WEB_SEARCH = Tool(
    name="web_search",
    description=(
        "Search the web for current information. Use this when the user asks "
        "about recent events, news, facts you're unsure about, or anything "
        "that requires up-to-date information."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up on the web.",
            },
        },
        "required": ["query"],
    },
    handler=_web_search,
    requires_confirmation=False,
)


# ── 3. get_weather ───────────────────────────────────────────────────────────

def _get_weather(location: str) -> str:
    """Get current weather for a city via wttr.in (free, no API key)."""
    try:
        encoded = urllib.parse.quote(location)
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "NovaAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return json.dumps({"error": f"Weather lookup failed: {str(e)}"})

    try:
        current = data["current_condition"][0]
        area = data.get("nearest_area", [{}])[0]
        area_name = area.get("areaName", [{}])[0].get("value", location)
        country = area.get("country", [{}])[0].get("value", "")

        return (
            f"Weather in {area_name}, {country}: "
            f"{current['weatherDesc'][0]['value']}, "
            f"{current['temp_C']}°C (feels like {current['FeelsLikeC']}°C), "
            f"Humidity: {current['humidity']}%, "
            f"Wind: {current['windspeedKmph']} km/h {current.get('winddir16Point', '')}."
        )
    except (KeyError, IndexError) as e:
        return json.dumps({"error": f"Could not parse weather data: {str(e)}"})


GET_WEATHER = Tool(
    name="get_weather",
    description=(
        "Get the current weather for a given city or location. "
        "Returns temperature, conditions, humidity, and wind."
    ),
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The city name, e.g. 'Delhi', 'New York', 'London'.",
            },
        },
        "required": ["location"],
    },
    handler=_get_weather,
    requires_confirmation=False,
)


# ── All built-in tools ───────────────────────────────────────────────────────

ALL_BUILTIN_TOOLS = [GET_CURRENT_DATETIME, WEB_SEARCH, GET_WEATHER]
