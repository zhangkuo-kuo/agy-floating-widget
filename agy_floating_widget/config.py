"""Configuration, paths, and dynamic model resolution."""

from datetime import datetime
from pathlib import Path
import re

GEMINI_HOME = Path.home() / ".gemini"
STATE_DIR = GEMINI_HOME / "agy-floating-widget"
STATE_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = str(STATE_DIR / "widget_config.json")
PIN_FILE = str(STATE_DIR / "pinned_sessions.json")
ALIAS_FILE = str(STATE_DIR / "session_aliases.json")
PID_FILE = str(STATE_DIR / "widget.pid")
CRASH_LOG_FILE = str(STATE_DIR / "widget_crash.log")

BRAIN_DIRS = [
    str(GEMINI_HOME / "antigravity" / "brain"),
    str(GEMINI_HOME / "antigravity-cli" / "brain"),
]
CLI_HISTORY_FILE = str(GEMINI_HOME / "antigravity-cli" / "history.jsonl")

DEFAULT_CONFIG = {
    "filter_short_cli": True,
    "min_cli_steps": 10,
    "cli_active_grace_min": 15,
    "current_category": "ALL",
    "custom_models": {},
}

DEFAULT_MODEL = ("Model", 256000)
MAX_DISCOVER_SESSIONS = 50


class ModelRegistry:
    """Dynamically learns model names and limits from RPC/transcripts and user config."""

    def __init__(self, custom_models=None):
        self._models = {}
        if isinstance(custom_models, dict):
            for mid, spec in custom_models.items():
                if isinstance(spec, (list, tuple)) and len(spec) >= 2:
                    try:
                        self._models[str(mid)] = (str(spec[0]), int(spec[1]))
                    except (TypeError, ValueError):
                        pass

    def register_from_quota_response(self, quota_resp: dict):
        """Extract model metadata from GetCascadeTrajectoryQuotaStatus if provided."""
        if not isinstance(quota_resp, dict):
            return
        for q in quota_resp.get("quotas", []):
            if not isinstance(q, dict):
                continue
            mid = q.get("model") or q.get("modelId") or q.get("id")
            if not mid or mid in self._models:
                continue
            label = q.get("label") or q.get("displayName") or q.get("name")
            limit = q.get("contextLimit") or q.get("maxContextTokens") or q.get("tokenLimit")
            short_name = self._format_short_name(str(label or mid))
            ctx_limit = self._infer_limit(str(mid), limit)
            self._models[str(mid)] = (short_name, ctx_limit)

    def resolve(self, mid: str):
        if not mid:
            return DEFAULT_MODEL
        if mid in self._models:
            return self._models[mid]
        short_name = self._format_short_name(mid)
        ctx_limit = self._infer_limit(mid, None)
        return (short_name, ctx_limit)

    @staticmethod
    def _infer_limit(mid: str, explicit_limit) -> int:
        if explicit_limit is not None:
            try:
                val = int(explicit_limit)
                if val > 0:
                    return val
            except (TypeError, ValueError):
                pass
        low = mid.lower()
        if "sonnet" in low or "opus" in low:
            return 200000
        if "pro" in low or "gpt" in low:
            return 128000
        if "flash" in low or "gemini" in low:
            return 256000
        return DEFAULT_MODEL[1]

    @staticmethod
    def _format_short_name(raw: str) -> str:
        s = raw.strip()
        if not s:
            return DEFAULT_MODEL[0]
        if s.startswith("MODEL_PLACEHOLDER_"):
            return s.replace("MODEL_PLACEHOLDER_", "")[:12]
        # Compact common model IDs like gemini-3.8-flash-high or claude-sonnet-4-6
        s = re.sub(r"-thinking$", "", s, flags=re.IGNORECASE)
        parts = [p for p in re.split(r"[-_\s]+", s) if p]
        if len(parts) >= 2:
            if parts[0].lower() == "gemini":
                rest = "-".join(p.capitalize() if p.isalpha() else p for p in parts[1:4])
                return rest[:14]
            if parts[0].lower() == "claude":
                rest = "-".join(p.capitalize() if p.isalpha() else p for p in parts[1:4])
                return rest[:14]
        return s[:14]


def fmt_tok(tokens: int) -> str:
    return f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)


def parse_ts(lm) -> float:
    if isinstance(lm, (int, float)):
        return float(lm)
    if isinstance(lm, str) and lm:
        try:
            return datetime.fromisoformat(lm.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    return 0.0
