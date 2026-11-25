"""Data collection: local LanguageServer RPC and disk transcript scanning."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import (
    ALIAS_FILE,
    BRAIN_DIRS,
    CLI_HISTORY_FILE,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    DEFAULT_MODEL,
    MAX_DISCOVER_SESSIONS,
    ModelRegistry,
    PIN_FILE,
    parse_ts,
)
from .platform_utils import discover_ls_processes

_GENERIC_DIR_NAMES = {"users", "home", "desktop", Path.home().name.lower()}


class SessionData:
    def __init__(
        self,
        cid,
        summary,
        step_count,
        last_modified,
        model_tag,
        limit,
        tokens,
        ctx_pct,
        is_pinned=False,
        is_cli=False,
    ):
        self.cid = cid
        self.summary = summary or "Session"
        self.step_count = step_count
        self.last_modified = last_modified
        self.model_tag = model_tag
        self.limit = limit
        self.tokens = tokens
        self.ctx_pct = ctx_pct
        self.is_pinned = is_pinned
        self.is_cli = is_cli
        self.planner_response_count = -1


class MonitorCore:
    def __init__(self):
        self.port = None
        self.token = None
        self.pinned_ids = set(self._load_json(PIN_FILE, []))
        self.aliases = self._load_json(ALIAS_FILE, {})
        loaded_cfg = self._load_json(CONFIG_FILE, None)
        self.config = dict(DEFAULT_CONFIG)
        if isinstance(loaded_cfg, dict):
            self.config.update(loaded_cfg)
        else:
            self._save_json(CONFIG_FILE, self.config)
        self.model_registry = ModelRegistry(self.config.get("custom_models"))
        self._pr_cache = {}
        self.known_subagents = set()
        self.cli_history = self.load_cli_history()

    def set_filter_short_cli(self, enabled: bool):
        self.config["filter_short_cli"] = bool(enabled)
        self._save_json(CONFIG_FILE, self.config)

    def save_config(self):
        self._save_json(CONFIG_FILE, self.config)

    def is_cli_session(self, cid, is_cli=False, sdata=None) -> bool:
        if is_cli or (cid in self.cli_history):
            return True
        if sdata:
            raw = (sdata.get("summary") or "").strip().lower()
            if raw in ("agy cli", "cli"):
                return True
        return len(BRAIN_DIRS) > 1 and os.path.exists(os.path.join(BRAIN_DIRS[1], cid))

    def should_skip_short_cli(self, cid, step_count, last_modified_ts, is_cli=False, sdata=None) -> bool:
        if not self.config.get("filter_short_cli", True):
            return False
        if not self.is_cli_session(cid, is_cli=is_cli, sdata=sdata):
            return False
        if cid in self.pinned_ids or cid in self.aliases:
            return False
        min_steps = int(self.config.get("min_cli_steps", 10))
        if step_count >= min_steps:
            return False
        grace_sec = float(self.config.get("cli_active_grace_min", 15)) * 60.0
        if last_modified_ts > 0 and (time.time() - last_modified_ts) <= grace_sec:
            return False
        return True

    @staticmethod
    def _load_json(path, default):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return default

    @staticmethod
    def _save_json(path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def toggle_pin(self, cid):
        if cid in self.pinned_ids:
            self.pinned_ids.remove(cid)
        else:
            self.pinned_ids.add(cid)
        self._save_json(PIN_FILE, list(self.pinned_ids))

    def set_alias(self, cid, alias):
        alias = alias.strip()
        if alias:
            self.aliases[cid] = alias
        elif cid in self.aliases:
            del self.aliases[cid]
        self._save_json(ALIAS_FILE, self.aliases)

    def is_subagent_sdata(self, sdata):
        meta = sdata.get("trajectoryMetadata") or {}
        return bool(
            meta.get("parentConversationId")
            or meta.get("subagentSpec")
            or (meta.get("nestingDepth", 0) > 0)
        )

    def get_transcript_path(self, cid):
        for bdir in BRAIN_DIRS:
            p = os.path.join(bdir, cid, ".system_generated", "logs", "transcript.jsonl")
            if os.path.exists(p):
                return p
        return None

    def load_cli_history(self):
        hist = {}
        if not os.path.exists(CLI_HISTORY_FILE):
            return hist
        try:
            with open(CLI_HISTORY_FILE, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        cid = rec.get("sessionId") or rec.get("conversationId")
                        if not cid:
                            continue
                        ws_raw = (
                            rec.get("workspace")
                            or rec.get("workspaceDirectory")
                            or rec.get("workingDirectory")
                            or ""
                        )
                        ws_clean = os.path.basename(ws_raw.rstrip("\\/")) if ws_raw else ""
                        disp = rec.get("display") or ""
                        if cid not in hist:
                            hist[cid] = {"workspace": ws_clean, "displays": []}
                        elif ws_clean and not hist[cid]["workspace"]:
                            hist[cid]["workspace"] = ws_clean
                        if disp and disp not in hist[cid]["displays"]:
                            hist[cid]["displays"].append(disp)
                    except Exception:
                        pass
        except Exception:
            pass
        return hist

    @staticmethod
    def _clean_ws_path(val):
        if not val or not isinstance(val, str):
            return ""
        val = urllib.parse.unquote(val)
        if val.startswith("file:///"):
            # Windows drive letter URI: file:///C:/... -> C:/..., POSIX: file:///home/... -> /home/...
            val = val[8:] if (len(val) > 9 and val[9] == ":") else val[7:]
        val = val.replace("/", os.sep).strip()
        if any(c in val for c in ("\n", "\r", "{", "}", '"', "'", ";")):
            return ""
        bname = os.path.basename(val.rstrip("\\/"))
        if bname and (":" in bname or len(bname) <= 1 or bname.startswith(".")):
            return ""
        if bname and bname.lower() in _GENERIC_DIR_NAMES:
            return ""
        return bname

    def extract_workspace_from_sdata(self, sdata):
        meta = sdata.get("trajectoryMetadata") or {}
        for ws_list in (sdata.get("workspaces"), meta.get("workspaces")):
            if isinstance(ws_list, list):
                for w in ws_list:
                    if isinstance(w, dict):
                        for k in ("workspaceFolderAbsoluteUri", "uri", "path"):
                            name = self._clean_ws_path(w.get(k))
                            if name:
                                return name
        for uris in (meta.get("workspaceUris"), sdata.get("workspaceUris")):
            if isinstance(uris, list):
                for u in uris:
                    name = self._clean_ws_path(u)
                    if name:
                        return name
        for key in ("workspaceUri", "workspacePath", "rootPath", "workingDirectory"):
            for container in (meta, sdata):
                name = self._clean_ws_path(container.get(key))
                if name:
                    return name
        return ""

    def extract_workspace_from_transcript(self, cid):
        tpath = self.get_transcript_path(cid)
        if not tpath:
            return ""
        try:
            with open(tpath, "rb") as f:
                head = f.read(65536).decode("utf-8", errors="ignore")
                m = re.search(r'workspaceUris.*?file:///([^\\"\r\n]+)', head, flags=re.DOTALL)
                if m:
                    name = self._clean_ws_path(m.group(1))
                    if name:
                        return name
                m2 = re.search(r"Active Workspaces:\s*[\r\n]+-\s*([^\r\n]+)", head)
                if m2:
                    name = self._clean_ws_path(m2.group(1).strip())
                    if name:
                        return name
                m3 = re.search(r"Command Working Directory:\s*([^\r\n]+)", head)
                if m3:
                    name = self._clean_ws_path(m3.group(1).strip())
                    if name:
                        return name
                m4 = re.search(
                    r'"(?:Cwd|cwd|workingDirectory|workspaceDirectory)"\s*:\s*"([^"\r\n]+)"', head
                )
                if not m4:
                    m4 = re.search(
                        r'\\"(?:Cwd|cwd|workingDirectory|workspaceDirectory)\\"\s*:\s*\\"([^\\"\r\n]+)\\"',
                        head,
                    )
                if m4:
                    name = self._clean_ws_path(m4.group(1).replace(r"\\", "\\"))
                    if name:
                        return name
        except Exception:
            pass
        return ""

    def clean_intent_text(self, text, max_len=16):
        if not text:
            return ""
        t = re.sub(
            r"<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)>[\s\S]*?</(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE)>",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        t = re.sub(r"</?[a-zA-Z0-9_\-]+(\s+[^>]*)?>", " ", t)
        t = re.sub(r"agy(?:\.cmd|\.exe|\.bat)?\s+.*", " ", t)
        lines = [l.strip(" \t\r\n#*-`'\"") for l in t.splitlines() if l.strip(" \t\r\n#*-`'\"")]
        candidate = ""
        for l in lines:
            if not l.startswith("/") and len(l) >= 2:
                candidate = l
                break
        if not candidate and lines:
            candidate = lines[0]
        candidate = re.sub(r"\s+", " ", candidate).strip()
        return candidate[:max_len].strip()

    def extract_intent_from_transcript(self, cid, max_len=16):
        tpath = self.get_transcript_path(cid)
        if not tpath:
            return ""
        try:
            with open(tpath, "rb") as f:
                head = f.read(16384).decode("utf-8", errors="ignore").splitlines()
                for l in head:
                    if "USER_INPUT" in l:
                        try:
                            obj = json.loads(l)
                            cleaned = self.clean_intent_text(obj.get("content", ""), max_len=max_len)
                            if cleaned:
                                return cleaned
                        except Exception:
                            pass
        except Exception:
            pass
        return ""

    def resolve_session_title(self, cid, official_summary, sdata=None, is_cli=False):
        if cid in self.aliases:
            return self.aliases[cid]

        raw_title = (official_summary or "").strip()
        is_cli_session = is_cli or (cid in self.cli_history)
        is_vague = (
            not raw_title
            or raw_title == cid[:8]
            or raw_title.lower() in ("agy cli", "cli", "session", "idle (no session)")
        )

        ws_name = self.cli_history.get(cid, {}).get("workspace", "")
        if not ws_name and sdata:
            ws_name = self.extract_workspace_from_sdata(sdata)
        if not ws_name:
            ws_name = self.extract_workspace_from_transcript(cid)

        if not is_cli_session and not is_vague:
            if ws_name and not raw_title.startswith(f"[{ws_name}]"):
                return f"[{ws_name}] {raw_title}"
            return raw_title

        intent = ""
        if cid in self.cli_history:
            for d in self.cli_history[cid].get("displays", []):
                c = self.clean_intent_text(d, max_len=16)
                if c and not c.startswith("/") and len(c) > len(intent):
                    intent = c
                    if len(intent) >= 6:
                        break
        if not intent:
            intent = self.extract_intent_from_transcript(cid, max_len=16)

        core_title = intent or (
            raw_title if (raw_title and raw_title.lower() not in ("agy cli", "cli")) else cid[:8]
        )
        if ws_name:
            return f"[{ws_name}] {core_title}"
        return core_title

    def count_planner_responses(self, cid):
        tpath = self.get_transcript_path(cid)
        if not tpath:
            return 0
        try:
            mtime = os.path.getmtime(tpath)
            cached_mtime, cached_cnt = self._pr_cache.get(cid, (0, -1))
            if cached_cnt >= 0 and mtime == cached_mtime:
                return cached_cnt

            cnt = 0
            with open(tpath, "rb") as f:
                for line in f:
                    if b'"PLANNER_RESPONSE"' in line:
                        cnt += 1
            self._pr_cache[cid] = (mtime, cnt)
            return cnt
        except Exception:
            return 0

    def discover_hub_ls(self):
        procs = discover_ls_processes()
        if not procs:
            return False

        procs.sort(key=lambda x: (10 if "hub" in (x.get("cmdline") or "") else 0), reverse=True)
        for item in procs:
            cl = item.get("cmdline") or ""
            m = re.search(r"--csrf_token\s+([^\s]+)", cl)
            if not m:
                continue
            token = m.group(1)
            for port in item.get("ports") or []:
                try:
                    url = f"http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetAllCascadeTrajectories"
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(
                            {"metadata": {"ideName": "antigravity", "extensionName": "antigravity", "locale": "en"}}
                        ).encode("utf-8"),
                        headers={
                            "Connect-Protocol-Version": "1",
                            "X-Codeium-Csrf-Token": token,
                            "Content-Type": "application/json",
                        },
                    )
                    res = urllib.request.urlopen(req, timeout=1.2)
                    if res.status == 200:
                        data = json.loads(res.read().decode("utf-8"))
                        sums = data.get("trajectorySummaries", {})
                        if sums or not self.port:
                            self.port = str(port)
                            self.token = token
                        if sums:
                            return True
                except Exception:
                    continue
        return bool(self.port and self.token)

    def rpc_call(self, endpoint, payload):
        if not self.port or not self.token:
            if not self.discover_hub_ls():
                return None
        url = f"http://127.0.0.1:{self.port}/exa.language_server_pb.LanguageServerService/{endpoint}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Connect-Protocol-Version": "1",
                "X-Codeium-Csrf-Token": self.token,
                "Content-Type": "application/json",
            },
        )
        try:
            res = urllib.request.urlopen(req, timeout=2.0)
            return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            if he.code in (401, 403):
                self.port = self.token = None
            return None
        except Exception:
            self.port = self.token = None
            return None

    def scan_disk_sessions(self, max_count=MAX_DISCOVER_SESSIONS):
        sessions = []
        entries = []
        for bdir in BRAIN_DIRS:
            if not os.path.exists(bdir):
                continue
            is_cli_dir = "antigravity-cli" in bdir
            try:
                for cid in os.listdir(bdir):
                    tpath = os.path.join(bdir, cid, ".system_generated", "logs", "transcript.jsonl")
                    if os.path.exists(tpath):
                        try:
                            entries.append((cid, os.path.getmtime(tpath), tpath, is_cli_dir))
                        except Exception:
                            pass
            except Exception:
                continue

        entries.sort(key=lambda x: x[1], reverse=True)
        for cid, mtime, tpath, is_cli in entries:
            if len(sessions) >= max_count:
                break
            if cid in self.known_subagents:
                continue

            is_sub = False
            try:
                with open(tpath, "rb") as f:
                    head_chunk = f.read(16384)
                    if b'"invoke_subagent"' in head_chunk or b"Created the following subagents" in head_chunk:
                        for sub_match in re.finditer(rb'"conversationId":\s*"([0-9a-f-]{36})"', head_chunk):
                            self.known_subagents.add(sub_match.group(1).decode("ascii"))
                    if (b'"send_message"' in head_chunk and b'"Recipient"' in head_chunk) or (
                        b"sender=" in head_chunk and b'"USER_INPUT"' not in head_chunk
                    ):
                        is_sub = True
            except Exception:
                pass

            if is_sub or cid in self.known_subagents:
                self.known_subagents.add(cid)
                continue

            summary = self.aliases.get(cid, cid[:8])
            sc = exact_tokens = fsize = 0
            model_tag, limit = DEFAULT_MODEL

            try:
                fsize = os.path.getsize(tpath)
                with open(tpath, "rb") as f:
                    f.seek(max(0, fsize - 65536))
                    lines = f.read().decode("utf-8", errors="ignore").splitlines()
                    for l in reversed(lines):
                        if not l.strip():
                            continue
                        try:
                            obj = json.loads(l)
                            if sc == 0 and "step_index" in obj:
                                sc = obj["step_index"]
                            if exact_tokens == 0 and obj.get("type") == "PLANNER_RESPONSE":
                                in_tok = int(obj.get("input_tokens") or 0)
                                cache_tok = int(obj.get("cache_read_tokens") or 0)
                                out_tok = int(obj.get("output_tokens") or 0)
                                exact_tokens = in_tok + cache_tok + out_tok
                                model_tag, limit = self.model_registry.resolve(obj.get("model") or "")
                            if sc > 0 and exact_tokens > 0:
                                break
                        except Exception:
                            pass
                if self.should_skip_short_cli(cid, sc, mtime, is_cli=is_cli):
                    continue
                summary = self.resolve_session_title(cid, summary, sdata=None, is_cli=is_cli)
            except Exception:
                pass

            if self.should_skip_short_cli(cid, sc, mtime, is_cli=is_cli):
                continue

            tokens = exact_tokens if exact_tokens > 0 else (min(int(fsize / 3.5), limit) if fsize > 0 else 0)
            ctx_pct = (tokens / limit) * 100 if limit > 0 else 0.0
            is_cli_flag = self.is_cli_session(cid, is_cli=is_cli, sdata=None)
            sessions.append(
                SessionData(
                    cid=cid,
                    summary=summary,
                    step_count=sc,
                    last_modified=datetime.fromtimestamp(mtime).isoformat(),
                    model_tag=model_tag,
                    limit=limit,
                    tokens=tokens,
                    ctx_pct=ctx_pct,
                    is_pinned=(cid in self.pinned_ids),
                    is_cli=is_cli_flag,
                )
            )
        return sessions

    def fetch_all(self):
        connected = bool(self.port and self.token)
        quota_pct = 100.0
        reset_str = "--"

        quota_resp = self.rpc_call("GetCascadeTrajectoryQuotaStatus", {})
        if quota_resp:
            connected = True
            self.model_registry.register_from_quota_response(quota_resp)
            for q in quota_resp.get("quotas", []):
                val = q.get("value") or q.get("percentage") or q.get("fraction")
                if val is not None:
                    try:
                        v = float(val)
                        quota_pct = v * 100.0 if v <= 1.0 else v
                    except Exception:
                        pass
                rt = q.get("resetTime")
                if rt and isinstance(rt, str):
                    try:
                        dt = datetime.fromisoformat(rt.replace("Z", "+00:00"))
                        secs = int((dt - datetime.now(timezone.utc)).total_seconds())
                        if secs > 0:
                            h, rem = divmod(secs, 3600)
                            m, s = divmod(rem, 60)
                            reset_str = f"{h}h{m:02d}m" if h > 0 else f"{m}m{s:02d}s"
                        else:
                            reset_str = "Now"
                    except Exception:
                        reset_str = rt[:10]
                    break

        sessions = []
        self.cli_history = self.load_cli_history()
        traj_resp = self.rpc_call("GetAllCascadeTrajectories", {})
        if traj_resp:
            connected = True
        summaries = traj_resp.get("trajectorySummaries", {}) if traj_resp else {}

        if summaries:
            main_items = [(cid, sd) for cid, sd in summaries.items() if not self.is_subagent_sdata(sd)]
            sorted_items = sorted(main_items, key=lambda x: x[1].get("lastModifiedTime", ""), reverse=True)

            for cid, sdata in sorted_items:
                if len(sessions) >= MAX_DISCOVER_SESSIONS:
                    break
                sc = sdata.get("stepCount", 0)
                lm = sdata.get("lastModifiedTime", "")
                if self.should_skip_short_cli(cid, sc, parse_ts(lm), is_cli=False, sdata=sdata):
                    continue
                display_name = self.resolve_session_title(
                    cid, sdata.get("summary") or cid[:8], sdata=sdata, is_cli=False
                )
                model_tag, limit = DEFAULT_MODEL
                total_tokens = 0

                if sc > 0 and self.port and self.token:
                    try:
                        steps_resp = self.rpc_call(
                            "GetCascadeTrajectorySteps",
                            {"cascadeId": cid, "startIndex": max(0, sc - 5), "endIndex": sc},
                        )
                        if steps_resp:
                            for st in reversed(steps_resp.get("steps", [])):
                                mu = st.get("metadata", {}).get("modelUsage")
                                if mu:
                                    model_tag, limit = self.model_registry.resolve(mu.get("model", ""))
                                    total_tokens = (
                                        int(mu.get("inputTokens") or 0)
                                        + int(mu.get("outputTokens") or 0)
                                        + int(mu.get("cacheReadTokens") or 0)
                                    )
                                    break
                    except Exception:
                        pass

                ctx_pct = (total_tokens / limit) * 100 if limit > 0 else 0.0
                is_cli_flag = self.is_cli_session(cid, is_cli=False, sdata=sdata)
                sessions.append(
                    SessionData(
                        cid=cid,
                        summary=display_name,
                        step_count=sc,
                        last_modified=lm,
                        model_tag=model_tag,
                        limit=limit,
                        tokens=total_tokens,
                        ctx_pct=ctx_pct,
                        is_pinned=(cid in self.pinned_ids),
                        is_cli=is_cli_flag,
                    )
                )

        disk_sessions = self.scan_disk_sessions(max_count=MAX_DISCOVER_SESSIONS)
        if not sessions:
            sessions = disk_sessions
        else:
            existing = {s.cid for s in sessions}
            sessions.extend(ds for ds in disk_sessions if ds.cid not in existing)
            sessions.sort(key=lambda s: s.last_modified, reverse=True)

        return {"connected": connected, "sessions": sessions, "quota_pct": quota_pct, "reset_str": reset_str}
