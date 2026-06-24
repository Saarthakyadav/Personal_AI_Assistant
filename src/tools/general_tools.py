# src/tools/general_tools.py
"""
General-purpose tools for Nova — code execution, HTTP fetch, file reading.

These tools fill the "General (long tail)" box in the Architecture v3 flowchart:
  code exec · browser · HTTP · files

All side-effecting tools require confirmation.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from typing import Optional

from src.tools import Tool


# ── 1. execute_python ─────────────────────────────────────────────────────────

def _execute_python(code: str, timeout: int = 10) -> str:
    """
    Execute a Python code snippet in a sandboxed subprocess.
    Returns stdout and stderr.  Hard 10-second timeout.
    """
    if not code or not code.strip():
        return json.dumps({"error": "No code provided."})

    # Clamp timeout
    try:
        timeout = min(max(int(timeout), 1), 30)
    except (ValueError, TypeError):
        timeout = 10

    # Write code to a temp file and execute in a subprocess for isolation
    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        tmp.write(code)
        tmp.close()

        # Construct minimal environment to strip sensitive system variables and credentials (Security fix #5)
        # On Windows, SystemRoot and SystemDrive are required for cryptographically secure random number generation.
        env = {
            "PYTHONPATH": "",
        }
        if sys.platform == "win32":
            sys_root = os.environ.get("SystemRoot", "C:\\Windows")
            env["PATH"] = os.path.pathsep.join([
                os.path.join(sys_root, "system32"),
                sys_root,
                os.environ.get("PATH", "")
            ])
            env["SystemRoot"] = sys_root
            if "SystemDrive" in os.environ:
                env["SystemDrive"] = os.environ["SystemDrive"]
        else:
            env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin" + (os.path.pathsep + os.environ.get("PATH", "") if os.environ.get("PATH") else "")

        env["TEMP"] = tempfile.gettempdir()
        env["TMP"] = tempfile.gettempdir()

        result = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(tmp.name),
            env=env,
        )

        output = {
            "stdout": result.stdout[:5000] if result.stdout else "",
            "stderr": result.stderr[:2000] if result.stderr else "",
            "return_code": result.returncode,
            "status": "ok" if result.returncode == 0 else "error",
        }
        return json.dumps(output, indent=2)

    except subprocess.TimeoutExpired:
        return json.dumps({
            "error": f"Code execution timed out after {timeout} seconds.",
            "hint": "Reduce the complexity or add early termination.",
        })
    except Exception as e:
        return json.dumps({"error": f"Execution failed: {str(e)}"})
    finally:
        if tmp and os.path.exists(tmp.name):
            try:
                os.unlink(tmp.name)
            except Exception:
                pass


EXECUTE_PYTHON = Tool(
    name="execute_python",
    description=(
        "Execute a Python code snippet and return the output. "
        "Use this for calculations, data processing, or running small scripts. "
        "The code runs in an isolated subprocess with a 10-second timeout. "
        "NOTE: While system credentials and user variables are stripped for security, "
        "network access and filesystem access are still possible within the subprocess. "
        "IMPORTANT: This runs real code on the user's machine — always explain "
        "what the code does before executing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max execution time in seconds (default 10, max 30).",
            },
        },
        "required": ["code"],
    },
    handler=_execute_python,
    requires_confirmation=True,
)


# ── 2. http_fetch ─────────────────────────────────────────────────────────────

def _http_fetch(url: str, method: str = "GET", max_chars: int = 5000) -> str:
    """Fetch a URL and return the response body (text only, truncated)."""
    if not url or not url.startswith(("http://", "https://")):
        return json.dumps({"error": "Invalid URL. Must start with http:// or https://."})

    try:
        max_chars = min(max(int(max_chars), 100), 10000)
    except (ValueError, TypeError):
        max_chars = 5000

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NovaAssistant/1.0"},
            method=method.upper(),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8", errors="replace")

            return json.dumps({
                "url": url,
                "status_code": resp.status,
                "content_type": content_type,
                "body": body[:max_chars],
                "truncated": len(body) > max_chars,
                "total_length": len(body),
            })
    except urllib.error.HTTPError as e:
        return json.dumps({"error": f"HTTP {e.code}: {e.reason}", "url": url})
    except urllib.error.URLError as e:
        return json.dumps({"error": f"URL error: {str(e.reason)}", "url": url})
    except Exception as e:
        return json.dumps({"error": f"Fetch failed: {str(e)}", "url": url})


HTTP_FETCH = Tool(
    name="http_fetch",
    description=(
        "Fetch content from a URL via HTTP. Returns the response body as text. "
        "Use this for reading API responses, downloading text content, "
        "or checking if a URL is accessible. Only returns text — not binary files."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The full URL to fetch, e.g. 'https://api.example.com/data'.",
            },
            "method": {
                "type": "string",
                "description": "HTTP method: GET (default) or HEAD.",
                "enum": ["GET", "HEAD"],
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return (default 5000, max 10000).",
            },
        },
        "required": ["url"],
    },
    handler=_http_fetch,
    requires_confirmation=False,
)


# ── 3. read_file ──────────────────────────────────────────────────────────────

def _read_file(filepath: str, max_chars: int = 5000) -> str:
    """Read a local text file and return its contents."""
    if not filepath:
        return json.dumps({"error": "No filepath provided."})

    # Resolve to physical real path, resolving any symbolic links
    filepath = os.path.realpath(filepath)

    # Restrict read to allowed directories for security (Security fix #4)
    general_tools_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(general_tools_dir)
    project_root = os.path.dirname(src_dir)

    allowed_roots = [
        project_root,
        tempfile.gettempdir(),
    ]

    is_allowed = False
    for root in allowed_roots:
        real_root = os.path.realpath(root)
        try:
            # Check if filepath is within real_root using commonpath
            if os.path.commonpath([real_root, filepath]) == real_root:
                is_allowed = True
                break
        except ValueError:
            continue

    if not is_allowed:
        return json.dumps({
            "error": "Access denied: Reading files outside the workspace directory is restricted for security.",
            "filepath": filepath
        })

    if not os.path.exists(filepath):
        return json.dumps({"error": f"File not found: {filepath}"})

    if not os.path.isfile(filepath):
        return json.dumps({"error": f"Not a file: {filepath}"})

    try:
        max_chars = min(max(int(max_chars), 100), 20000)
    except (ValueError, TypeError):
        max_chars = 5000

    # Check file size before reading
    file_size = os.path.getsize(filepath)
    if file_size > 1_000_000:  # 1MB safety limit
        return json.dumps({
            "error": f"File too large ({file_size:,} bytes). Max 1MB.",
            "filepath": filepath,
        })

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars + 1)

        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        return json.dumps({
            "filepath": filepath,
            "content": content,
            "truncated": truncated,
            "file_size": file_size,
            "status": "ok",
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to read file: {str(e)}", "filepath": filepath})


READ_FILE = Tool(
    name="read_file",
    description=(
        "Read the contents of a local text file. Use this when the user asks about "
        "a specific file on their system, or when you need to inspect a configuration "
        "file, log, or source code. Only works with text files (not binary)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": "Path to the file to read (absolute or relative).",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return (default 5000, max 20000).",
            },
        },
        "required": ["filepath"],
    },
    handler=_read_file,
    requires_confirmation=True,
)


# ── Exported list ─────────────────────────────────────────────────────────────

GENERAL_TOOLS = [EXECUTE_PYTHON, HTTP_FETCH, READ_FILE]
