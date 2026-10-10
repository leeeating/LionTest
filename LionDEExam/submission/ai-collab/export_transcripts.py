#!/usr/bin/env python3
"""把 Claude Code 自動存下的 session 紀錄（.jsonl）轉成可讀的 Markdown。

確定性轉換：除了「遮蔽」與「截斷」之外，內容一律保留原文，不摘要、不改寫。

用法：
    python3 export_transcripts.py                  # 轉換來源目錄下所有 session
    python3 export_transcripts.py --session <id>   # 只轉一個 session
    python3 export_transcripts.py --source-dir <dir> --out-dir <dir>

輸出（預設在本腳本同目錄的 transcripts/）：
    <session-id>.md                 主對話
    <session-id>__agent-<id>.md     該 session 派出的每個 subagent 對話
重跑會覆寫同名檔；同樣的輸入產生位元組完全相同的輸出。
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 設定（要增補遮蔽規則，改這一區即可）
# ---------------------------------------------------------------------------

def find_repo_root(start: Path) -> Path:
    """從本腳本位置往上找，第一個含 CLAUDE.md 的目錄即專案根目錄。"""
    for d in [start, *start.parents]:
        if (d / "CLAUDE.md").is_file():
            return d
    sys.exit(f"從 {start} 往上找不到含 CLAUDE.md 的專案根目錄；請用 --source-dir 指定來源")


def claude_project_key(path: Path) -> str:
    """Claude Code 存 session 的目錄名：絕對路徑中非英數字元一律換成 '-'。"""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = SCRIPT_DIR / "transcripts"

# 遮蔽規則分兩部分：
# 1. 通用規則（寫在這裡）：email 位址、使用者家目錄（執行時用 Path.home() 取得）。
# 2. 本機規則（不進版控）：<專案根目錄>/.claude/redact.local.json，放所有具體要遮的字串。
#    格式：[{"category": "類別（會寫進檔頭）", "pattern": "要遮的字串",
#            "replacement": "〔已遮蔽：…〕", "ignore_case": true, "regex": false}, ...]
#    依檔內順序套用（較長的字串要排在較短的前面）。regex 預設 false，pattern 當純字串比對。
#    設定檔不存在或格式錯誤時，腳本報錯停止，不會產出未遮蔽的檔。
REDACT_CONFIG_NAME = ".claude/redact.local.json"
EMAIL_RULE = ("email 位址", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "〔已遮蔽：email〕", 0)


def load_redactions(config_path: Path):
    """回傳 [(類別, compiled regex, 取代字串)]。"""
    if not config_path.is_file():
        sys.exit(f"錯誤：找不到遮蔽設定檔 {config_path}，停止執行（不產出未遮蔽的檔）")
    try:
        entries = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"錯誤：遮蔽設定檔不是合法 JSON（{e}），停止執行")
    if not isinstance(entries, list) or not entries:
        sys.exit("錯誤：遮蔽設定檔必須是非空的 JSON 陣列，停止執行")
    rules = [(EMAIL_RULE[0], re.compile(EMAIL_RULE[1]), EMAIL_RULE[2])]
    home = str(Path.home())
    rules.append(("使用者家目錄路徑", re.compile(re.escape(home)), "~"))
    for i, e in enumerate(entries):
        try:
            pat = e["pattern"] if e.get("regex") else re.escape(e["pattern"])
            flags = re.I if e.get("ignore_case") else 0
            rules.append((e["category"], re.compile(pat, flags), e["replacement"]))
        except (KeyError, TypeError, re.error) as err:
            sys.exit(f"錯誤：遮蔽設定檔第 {i + 1} 條格式錯誤（{err!r}），停止執行")
    return rules


REDACTIONS = []  # 由 main() 載入後填入

# 截斷：單一工具輸入欄位或工具結果超過 TRUNCATE_OVER 行時，只保留前 TRUNCATE_KEEP 行。
TRUNCATE_OVER = 60
TRUNCATE_KEEP = 40

# 時間戳顯示時區（使用者在台灣）
DISPLAY_TZ = timezone(timedelta(hours=8))
DISPLAY_TZ_LABEL = "UTC+8"

# ---------------------------------------------------------------------------
# 工具函式
# ---------------------------------------------------------------------------

def redact(text: str) -> str:
    for _cat, rx, rep in REDACTIONS:
        text = rx.sub(rep, text)
    return text


def fence(content: str, lang: str = "") -> str:
    """放進 fenced code block；內容含 ``` 時自動用更長的 fence。"""
    longest = max((len(m) for m in re.findall(r"`{3,}", content)), default=0)
    f = "`" * max(3, longest + 1)
    if not content.endswith("\n"):
        content += "\n"
    return f"{f}{lang}\n{content}{f}"


def truncate(text: str) -> str:
    lines = text.split("\n")
    if len(lines) > TRUNCATE_OVER:
        return "\n".join(lines[:TRUNCATE_KEEP]) + f"\n〔輸出截斷，共 {len(lines)} 行〕"
    return text


def fmt_ts(ts) -> str:
    if not ts:
        return "（無時間戳）"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S") + f" ({DISPLAY_TZ_LABEL})"


def load_jsonl(path: Path):
    records = []
    with path.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # 寫入中途的最後一行可能不完整；明確標出而不是默默略過
                records.append({"type": "_unparseable", "lineno": n, "raw": line})
    return records


def block_text_of_tool_result(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for item in content:
        t = item.get("type")
        if t == "text":
            parts.append(item.get("text", ""))
        elif t == "image":
            parts.append("〔圖片，未收錄〕")
        else:
            parts.append(json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True))
    return "\n".join(parts)


SR_RX = re.compile(r"<system-reminder>.*?</system-reminder>\s*", re.S)


# ---------------------------------------------------------------------------
# Markdown 產生器
# ---------------------------------------------------------------------------


class Renderer:
    def __init__(self, session_id: str, agent_links: dict):
        self.session_id = session_id
        self.agent_links = agent_links  # tool_use_id -> (agent_id, description, md filename)
        self.out = []
        self.pending_injected = []  # (timestamp, label, text)
        self.counts = {"user": 0, "assistant_text": 0, "tool_use": 0, "tool_result": 0}

    # 系統注入內容：連續的合併成一個折疊區塊
    def inject(self, ts, label, text):
        self.pending_injected.append((ts, label, text))

    def flush_injected(self):
        if not self.pending_injected:
            return
        n = len(self.pending_injected)
        first_ts = self.pending_injected[0][0]
        self.out.append(f"<details><summary>系統注入內容（{n} 項，{fmt_ts(first_ts)}）</summary>\n")
        for ts, label, text in self.pending_injected:
            self.out.append(f"**{label}**（{fmt_ts(ts)}）\n")
            self.out.append(fence(text) + "\n")
        self.out.append("</details>\n")
        self.pending_injected = []

    def section(self, title, ts):
        self.flush_injected()
        self.out.append(f"### {title}　·　{fmt_ts(ts)}\n")

    def text(self, body):
        self.out.append(body.rstrip("\n") + "\n")

    # --- 各種內容 ---

    def user_text(self, ts, text, title="使用者"):
        # 使用者訊息裡若夾帶 system-reminder，抽出來放進折疊區
        reminders = [m.group(0).strip() for m in SR_RX.finditer(text)]
        body = SR_RX.sub("", text)
        self.counts["user"] += 1
        self.section(title, ts)
        self.text(body if body.strip() else "（空白訊息）")
        for r in reminders:
            self.inject(ts, "訊息中夾帶的 system-reminder", r)

    def tool_use(self, ts, block):
        self.counts["tool_use"] += 1
        name = block.get("name", "?")
        inp = block.get("input", {}) or {}
        tid = block.get("id", "")
        self.section(f"工具呼叫：{name}", ts)
        self.text(f"`tool_use_id: {tid}`\n")
        if name == "Bash":
            if "description" in inp:
                self.text(f"說明：{inp['description']}\n")
            self.text(fence(truncate(str(inp.get("command", ""))), "bash") + "\n")
            rest = {k: v for k, v in inp.items() if k not in ("command", "description")}
            if rest:
                self.text("其他參數：\n\n" + fence(truncate(json.dumps(rest, ensure_ascii=False, indent=2, sort_keys=True)), "json") + "\n")
        elif name in ("Write", "Edit", "MultiEdit", "Read", "Agent", "Task", "SubagentHandback"):
            # 已知工具：純量參數列成清單，長文字參數各自放 code block
            def is_long(v):
                return isinstance(v, str) and ("\n" in v or len(v) > 200)
            short = [k for k in sorted(inp) if not is_long(inp[k])]
            if short:
                items = []
                for k in short:
                    v = inp[k]
                    sv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
                    items.append(f"- `{k}`：`{sv}`" if "`" not in sv else f"- `{k}`：{sv}")
                self.text("\n".join(items) + "\n")
            for k in sorted(inp):
                if is_long(inp[k]):
                    self.text(f"`{k}`：\n")
                    self.text(fence(truncate(inp[k])) + "\n")
        else:
            self.text(fence(truncate(json.dumps(inp, ensure_ascii=False, indent=2, sort_keys=True)), "json") + "\n")
        link = self.agent_links.get(tid)
        if link:
            agent_id, desc, fname = link
            self.text(f"➡️ subagent 完整對話：[{desc}（agent-{agent_id}）]({fname})\n")

    def tool_result(self, ts, block, is_error=None):
        self.counts["tool_result"] += 1
        tid = block.get("tool_use_id", "")
        err = block.get("is_error")
        title = "工具結果（錯誤）" if err else "工具結果"
        self.section(title, ts)
        self.text(f"`tool_use_id: {tid}`\n")
        body = block_text_of_tool_result(block.get("content"))
        self.text(fence(truncate(body)) + "\n")

    def render(self, records, is_subagent=False):
        first_prompt_done = False
        for d in records:
            t = d.get("type")
            ts = d.get("timestamp")
            if t == "_unparseable":
                self.section("無法解析的紀錄行", None)
                self.text(fence(truncate(d["raw"])) + "\n")
                continue
            if t == "user":
                c = d.get("message", {}).get("content")
                origin = (d.get("origin") or {}).get("kind")
                if isinstance(c, str):
                    if origin == "human":
                        self.user_text(ts, c)
                    elif origin == "peer":
                        frm = (d.get("origin") or {}).get("from", "")
                        self.section("Subagent 回報（系統轉交給主對話）", ts)
                        if frm:
                            fname = f"{self.session_id}__agent-{frm}.md"
                            self.text(f"來源：[agent-{frm}]({fname})\n")
                        self.text(fence(c))
                    elif is_subagent and not d.get("isMeta") and not first_prompt_done:
                        first_prompt_done = True
                        self.section("派工指示（主對話 → subagent）", ts)
                        self.text(c)
                    elif d.get("isMeta") or origin in ("task-notification",) or c.lstrip().startswith("<"):
                        self.inject(ts, f"user 角色的系統訊息（origin: {origin or '無'}）", c)
                    elif origin is None and "promptSource" not in d and not is_subagent:
                        # 舊版紀錄沒有 origin 欄位：視為使用者輸入
                        self.user_text(ts, c)
                    else:
                        self.section(f"系統訊息（origin: {origin or '無'}）", ts)
                        self.text(c)
                elif isinstance(c, list):
                    for b in c:
                        bt = b.get("type")
                        if bt == "tool_result":
                            self.tool_result(ts, b)
                        elif bt == "text":
                            txt = b.get("text", "")
                            if origin == "human":
                                self.user_text(ts, txt)
                            elif txt.startswith("[Request interrupted"):
                                self.section("系統標記：使用者中斷", ts)
                                self.text(fence(txt))
                            elif d.get("isMeta") or txt.lstrip().startswith("<"):
                                self.inject(ts, "user 角色的系統訊息", txt)
                            else:
                                self.section("系統訊息", ts)
                                self.text(txt)
                        elif bt == "image":
                            self.section("使用者附圖", ts)
                            self.text("〔圖片，未收錄〕")
                        else:
                            self.section(f"其他內容（{bt}）", ts)
                            self.text(fence(truncate(json.dumps(b, ensure_ascii=False, indent=2, sort_keys=True)), "json"))
            elif t == "assistant":
                msg = d.get("message", {})
                synthetic = msg.get("model") == "<synthetic>" or d.get("isApiErrorMessage")
                for b in msg.get("content", []) or []:
                    bt = b.get("type")
                    if bt in ("thinking", "redacted_thinking"):
                        continue
                    if bt == "text":
                        if synthetic:
                            self.section("系統訊息（Claude Code 產生，非模型輸出）", ts)
                            self.text(fence(b.get("text", "")))
                        else:
                            self.counts["assistant_text"] += 1
                            self.section("AI", ts)
                            self.text(b.get("text", ""))
                    elif bt == "tool_use":
                        self.tool_use(ts, b)
                    else:
                        self.section(f"AI 其他內容（{bt}）", ts)
                        self.text(fence(truncate(json.dumps(b, ensure_ascii=False, indent=2, sort_keys=True)), "json"))
            elif t == "attachment":
                a = d.get("attachment", {})
                at = a.get("type")
                if at == "queued_command" and (a.get("origin") or {}).get("kind") == "human":
                    # 使用者在 AI 執行中途送出的訊息
                    self.user_text(ts, str(a.get("prompt", "")), title="使用者（AI 執行中插話）")
                    continue
                if "rendered" in d:
                    parts = []
                    for r in d.get("rendered") or []:
                        parts.append(r.get("content", "") if isinstance(r, dict) else str(r))
                    self.inject(ts, f"attachment：{at}", "\n".join(parts))
                # 沒有 rendered 的 attachment 沒有送進模型（hook 執行紀錄、系統提示快照等），不輸出
            elif t == "system":
                st = d.get("subtype")
                if st == "local_command":
                    self.section("本機指令（使用者在 CLI 執行）", ts)
                    self.text(fence(str(d.get("content", ""))))
                elif st in ("turn_duration", "stop_hook_summary"):
                    continue  # 計時與 hook 統計，不屬對話內容
                elif d.get("content"):
                    self.inject(ts, f"system 紀錄（{st}）", str(d.get("content")))
            # 其他紀錄類型（mode、file-history-snapshot、ai-title、queue-operation 等）是
            # Claude Code 的內部狀態，不是對話內容，不輸出。queue-operation 的使用者訊息
            # 另有 user 紀錄或 queued_command attachment 對應，已在上面輸出。
        self.flush_injected()
        return "\n".join(self.out)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def time_range(records):
    tss = sorted(r["timestamp"] for r in records if isinstance(r.get("timestamp"), str))
    if not tss:
        return "（無時間戳）"
    return f"{fmt_ts(tss[0])} ～ {fmt_ts(tss[-1])}"


def rules_summary():
    cats = []
    for cat, _rx, rep in REDACTIONS:
        item = f"{cat} → `{rep}`"
        if item not in cats:
            cats.append(item)
    lines = [
        "## 轉換規則",
        "",
        "本檔由 `export_transcripts.py` 從 Claude Code 自動存下的 `.jsonl` 確定性轉出。"
        "除下列遮蔽與截斷外，使用者訊息、AI 文字回覆、工具呼叫與工具結果皆為原文，未摘要、未改寫。",
        "",
        "- **遮蔽**（取代為可見標記）：" + "；".join(cats),
        f"- **截斷**：單一工具輸入欄位或工具結果超過 {TRUNCATE_OVER} 行時，保留前 {TRUNCATE_KEEP} 行並標註總行數。使用者與 AI 的文字訊息不截斷。",
        "- **AI 內部推理（thinking）未收錄。**",
        "- **系統注入內容**（system-reminder、全域規則檔、環境資訊等送進模型 context 的內容）保留原文，收在可展開的折疊區塊。",
        "- 未輸出：未送進模型的 Claude Code 內部狀態紀錄（hook 執行紀錄、系統提示快照、檔案快照、計時、標題等）。",
        f"- 時間戳以 {DISPLAY_TZ_LABEL} 顯示。訊息依 `.jsonl` 檔內順序排列。",
        "",
    ]
    return "\n".join(lines)


def export_session(src_dir: Path, session_id: str, out_dir: Path):
    main_path = src_dir / f"{session_id}.jsonl"
    sub_dir = src_dir / session_id / "subagents"
    agents = []  # (agent_id, path, meta)
    if sub_dir.is_dir():
        for p in sorted(sub_dir.glob("agent-*.jsonl")):
            agent_id = p.stem[len("agent-"):]
            meta_p = p.with_name(p.stem + ".meta.json")
            meta = {}
            if meta_p.exists():
                try:
                    meta = json.loads(meta_p.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = {}
            agents.append((agent_id, p, meta))

    agent_links = {}
    for agent_id, _p, meta in agents:
        if meta.get("toolUseId"):
            agent_links[meta["toolUseId"]] = (
                agent_id,
                meta.get("description", ""),
                f"{session_id}__agent-{agent_id}.md",
            )

    written = []

    # 主對話
    recs = load_jsonl(main_path)
    r = Renderer(session_id, agent_links)
    body = r.render(recs)
    head = [f"# Session 紀錄：{session_id}", ""]
    head.append(f"- **Session ID**：`{session_id}`")
    head.append(f"- **時間範圍**：{time_range(recs)}")
    if agents:
        head.append("- **Subagent 對話**：")
        for agent_id, _p, meta in agents:
            head.append(f"  - [{meta.get('description', '') or 'agent-' + agent_id}（agent-{agent_id}）]({session_id}__agent-{agent_id}.md)")
    head.append(
        f"- **統計**：使用者訊息 {r.counts['user']} 則、AI 文字回覆 {r.counts['assistant_text']} 則、"
        f"工具呼叫 {r.counts['tool_use']} 次、工具結果 {r.counts['tool_result']} 則"
    )
    head.append("")
    doc = "\n".join(head) + "\n" + rules_summary() + "\n## 對話\n\n" + body
    out = out_dir / f"{session_id}.md"
    out.write_text(redact(doc), encoding="utf-8")
    written.append(out)

    # subagents
    for agent_id, p, meta in agents:
        recs = load_jsonl(p)
        r = Renderer(session_id, {})
        body = r.render(recs, is_subagent=True)
        head = [f"# Subagent 紀錄：agent-{agent_id}", ""]
        head.append(f"- **所屬 Session**：[`{session_id}`]({session_id}.md)")
        if meta.get("description"):
            head.append(f"- **任務描述**：{meta['description']}")
        for key, label in (("agentType", "Agent 類型"), ("model", "模型"), ("toolUseId", "主對話中的 tool_use_id")):
            if meta.get(key):
                head.append(f"- **{label}**：`{meta[key]}`")
        head.append(f"- **時間範圍**：{time_range(recs)}")
        head.append(
            f"- **統計**：AI 文字回覆 {r.counts['assistant_text']} 則、"
            f"工具呼叫 {r.counts['tool_use']} 次、工具結果 {r.counts['tool_result']} 則"
        )
        head.append("")
        doc = "\n".join(head) + "\n" + rules_summary() + "\n## 對話\n\n" + body
        out = out_dir / f"{session_id}__agent-{agent_id}.md"
        out.write_text(redact(doc), encoding="utf-8")
        written.append(out)
    return written


def main():
    ap = argparse.ArgumentParser(description="把 Claude Code session jsonl 轉成可讀 Markdown")
    ap.add_argument("--session", help="只轉這個 session id")
    ap.add_argument("--source-dir", type=Path, help="session jsonl 所在目錄（預設由專案根目錄推導）")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--redact-config", type=Path, help=f"遮蔽設定檔（預設 <專案根目錄>/{REDACT_CONFIG_NAME}）")
    args = ap.parse_args()

    repo_root = None
    if args.source_dir is None or args.redact_config is None:
        repo_root = find_repo_root(SCRIPT_DIR)
    config = args.redact_config.expanduser() if args.redact_config else repo_root / REDACT_CONFIG_NAME
    REDACTIONS[:] = load_redactions(config)  # 先載入遮蔽規則；失敗就停止，不產出任何檔

    if args.source_dir is not None:
        src = args.source_dir.expanduser()
    else:
        src = Path.home() / ".claude" / "projects" / claude_project_key(repo_root)
    if not src.is_dir():
        sys.exit(f"找不到來源目錄：{src}")
    if args.session:
        ids = [args.session]
        if not (src / f"{args.session}.jsonl").exists():
            sys.exit(f"找不到 session：{args.session}")
    else:
        ids = sorted(p.stem for p in src.glob("*.jsonl"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for sid in ids:
        for p in export_session(src, sid, args.out_dir):
            print(p)


if __name__ == "__main__":
    main()
