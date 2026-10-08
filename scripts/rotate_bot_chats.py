#!/usr/bin/env python3
"""轮换 bot 主对话：归档旧 Bot Chat → 建新 Bot Chat（同名注册）→ 首句读旧对话。

走桌面后端（Electron 起的 hermes serve）的 WS JSON-RPC，与 Bots 面板点击同一条路。
不要用 `hermes -p X chat -q`：那建的不是 Bot Chat，点 bot 不会落到它上面。

跨机器/跨 profile 通用：profile 名单从后端 roster 取；后端端口自己找；缺 websockets 时自动
re-exec 到 Hermes venv 的 python。

用法（默认只重置脚本所在的那个 profile——发给哪个 bot 就重置哪个）：
    python rotate_bot_chats.py --dry-run         # 只看会动谁（默认：本 profile）
    python rotate_bot_chats.py                   # 轮换本 profile
    python rotate_bot_chats.py research steward  # 指定 profile
    python rotate_bot_chats.py --all             # 本机全部 profile（显式全量）
    python rotate_bot_chats.py --no-prompt       # 附加：只归档 + 建新，不投开场句
环境变量（可选）：HERMES_PYTHON / HERMES_DESKTOP_URL / HERMES_SESSION_TOKEN
"""
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

OPENING = """【新主对话开场 · 承接已归档的主对话】

你上一条主对话（本 profile 原来的 “Bot Chat”，会话 id {old}，共 {n} 条消息，起于 {date}）已按用户指示归档；本条会话就是接替它的新主对话。

先读完旧对话，再开始：
1. session_search(session_id="{old}") —— 默认返回开头 20 条 + 结尾 10 条；
2. 中段用同一个 session_id 配 around_message_id 分几次滚动读完（也可直接读本 profile 的 state.db）。

读完用一份承接记录开新对话（40 行以内）：① 这条线在做什么；② 已完成并落盘的产出（给路径）；③ 未完成或卡住的点；④ 需要用户拍板的事项（每条带建议）。只写读到的、盘上能核的，不要猜数。"""

HERE = os.path.dirname(os.path.abspath(__file__))


# ── 环境探测 ────────────────────────────────────────────────────────────────
def hermes_home():
    env = os.environ.get("HERMES_HOME")
    if env:
        return env
    local = os.environ.get("LOCALAPPDATA")
    if local and os.path.isdir(os.path.join(local, "hermes")):
        return os.path.join(local, "hermes")
    return os.path.expanduser("~/.hermes")


def current_profile():
    """The profile this script belongs to: each bot runs ITS OWN copy, so the default target is 'me'."""
    env = os.environ.get("HERMES_HOME")
    if env:
        home = os.path.abspath(env)
        return os.path.basename(home) if os.path.basename(os.path.dirname(home)) == "profiles" else "default"
    # No HERMES_HOME: read it off the install path …/<home>/skills/<category>/<skill>/scripts/
    for parent in pathlib.Path(__file__).resolve().parents:
        if parent.name == "skills":
            home = parent.parent
            return os.path.basename(home) if os.path.basename(os.path.dirname(home)) == "profiles" else "default"
    return None


def has_websockets(python=None):
    if python is None:
        try:
            import websockets  # noqa: F401
            return True
        except Exception:
            return False
    try:
        return subprocess.run([python, "-c", "import websockets"], capture_output=True, timeout=60).returncode == 0
    except Exception:
        return False


def venv_python():
    """The Hermes venv python (websockets lives there), or None."""
    cands = []

    def add(path):
        if path and os.path.isfile(path) and path not in cands:
            cands.append(path)

    add(os.environ.get("HERMES_PYTHON"))
    roots = []
    walk = os.path.abspath(hermes_home())
    for _ in range(4):  # HERMES_HOME 可能是 profile 目录，往上找安装根
        roots.append(walk)
        walk = os.path.dirname(walk)
    roots.append(os.path.expanduser("~/.hermes"))
    for root in roots:
        for rel in (("hermes-agent", "venv", "bin", "python"), ("hermes-agent", "venv", "Scripts", "python.exe")):
            add(os.path.join(root, *rel))
    shim = shutil.which("hermes")
    if shim:
        d = os.path.dirname(os.path.realpath(shim))
        for rel in (("python",), ("python.exe",), ("..", "bin", "python"), ("..", "Scripts", "python.exe")):
            add(os.path.normpath(os.path.join(d, *rel)))
    for cand in cands:
        if os.path.realpath(cand) != os.path.realpath(sys.executable) and has_websockets(cand):
            return cand
    return None


def listening_ports():
    """Candidate local ports, Hermes-owned listeners first. [] when nothing is discoverable."""
    if url := (os.environ.get("HERMES_DESKTOP_URL") or os.environ.get("HERMES_BACKEND_URL")):
        if m := re.search(r":(\d+)", url):
            return [int(m.group(1))]
    ports, others = [], []
    try:  # psutil ships with the Hermes venv
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                continue
            if conn.laddr.ip not in ("127.0.0.1", "::1"):
                continue
            try:
                cmd = " ".join(psutil.Process(conn.pid).cmdline()).lower()
            except Exception:
                cmd = ""
            (ports if any(k in cmd for k in ("hermes", "serve", "electron")) else others).append(conn.laddr.port)
    except Exception:
        pass
    if not ports and not others:
        for command in (["ss", "-ltn"], ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], ["netstat", "-ano"]):
            if not shutil.which(command[0]):
                continue
            try:
                out = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=30).stdout
            except Exception:
                continue
            for found in re.findall(r"(?:127\.0\.0\.1|\*|\[::1\]|0\.0\.0\.0):(\d+)", out):
                others.append(int(found))
            break
    seen = []
    for port in ports + others:
        if port not in seen:
            seen.append(port)
    return seen


def find_backend():
    """(port, token) of the desktop backend: the listening port whose GET / serves the session token."""
    token_env = os.environ.get("HERMES_SESSION_TOKEN")
    for port in listening_ports():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
                body = resp.read(3000).decode("utf-8", "replace")
        except Exception:
            if token_env:
                return port, token_env
            continue
        if found := re.search(r'HERMES_SESSION_TOKEN__\s*=\s*"([^"]*)"', body):
            return port, found.group(1)
    raise SystemExit("桌面后端没找到：没有本地端口在提供 session token 页（桌面应用在跑吗？）"
                     " 可用 HERMES_DESKTOP_URL / HERMES_SESSION_TOKEN 指定。")


def find_db(bot):
    """This machine's state.db for a profile, or None (verification is best-effort)."""
    roots = []
    walk = os.path.abspath(hermes_home())
    for _ in range(5):
        if walk not in roots:
            roots.append(walk)
        walk = os.path.dirname(walk)
    for root in roots:
        # A root that IS a profile dir (…/profiles/<name>) holds that profile's DB at its top,
        # never the default profile's — only a real home root owns <root>/state.db for 'default'.
        inside_profiles = os.path.basename(os.path.dirname(root)) == "profiles"
        cands = [os.path.join(root, "state.db")] if bot == "default" and not inside_profiles else []
        cands.append(os.path.join(root, "profiles", bot, "state.db"))
        for cand in cands:
            if os.path.isfile(cand):
                return cand
    return None


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    no_prompt = "--no-prompt" in argv
    all_flag = "--all" in argv
    want = [a for a in argv if not a.startswith("--")]

    from websockets.sync.client import connect

    port, token = find_backend()
    print(f"桌面后端 127.0.0.1:{port}{'  [dry-run]' if dry else ''}")
    ws = connect(f"ws://127.0.0.1:{port}/api/ws?token={token}", open_timeout=10, max_size=None)
    seq = 0

    def call(method, params=None, timeout=180):
        nonlocal seq
        seq += 1
        ws.send(json.dumps({"jsonrpc": "2.0", "id": seq, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv(timeout=timeout))
            if msg.get("id") == seq and ("result" in msg or "error" in msg):
                return msg

    def canonical(bot):
        found = call("session.list", {"title": "Bot Chat", "include_hidden": True, "profile": bot})
        return ((found.get("result") or {}).get("sessions") or [None])[0]

    roster = (call("profiles.list").get("result") or {}).get("profiles") or []
    names = [p["name"] for p in roster]
    if want:
        bots = [b for b in names if b in want]
        for miss in (b for b in want if b not in names):
            print(f"跳过 {miss}：不在后端 roster 里")
    elif all_flag:
        bots = names
    else:
        me = current_profile()
        if me not in names:
            raise SystemExit(f"本 profile（{me}）不在后端 roster 里；请显式传名字，或 --all。")
        bots = [me]
    print(f"目标：{', '.join(bots) if bots else '(空)'}")
    rows = []
    for bot in bots:
        entry = {"bot": bot}
        old = canonical(bot)
        entry["old"] = (old or {}).get("id")
        entry["msgs"] = (old or {}).get("message_count") or 0

        if not dry:
            if old:
                call("session.archive", {"session_id": old["id"], "archived": True, "profile": bot})
            created = call("session.create", {"profile": bot, "title": "Bot Chat", "hidden": True,
                                            "follow_profile_config": True, "source": "desktop"})
            res = created.get("result") or {}
            runtime, stored = res.get("session_id"), res.get("stored_session_id")
            entry["new"] = stored
            if not runtime:
                entry["error"] = created.get("error")
                rows.append(entry)
                print(json.dumps(entry, ensure_ascii=False))
                continue
            # 立刻落标题：懒建的行现在就有名字，注册名同时从旧行让到新行
            titled = call("session.title", {"session_id": runtime, "title": "Bot Chat"})
            entry["title"] = titled.get("result") or titled.get("error")
            if old and not no_prompt:
                date = time.strftime("%Y-%m-%d", time.localtime(old.get("started_at") or time.time()))
                sent = call("prompt.submit", {"session_id": runtime,
                                              "text": OPENING.format(old=old["id"], n=entry["msgs"], date=date)})
                entry["submit"] = sent.get("result") or sent.get("error")
        rows.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

    if dry:
        return

    time.sleep(2)
    print("\n== 核验 ==")
    for entry in rows:
        bot, old, new = entry["bot"], entry.get("old"), entry.get("new")
        ctx = [f"title_holders={[s['id'] for s in ((call('session.list', {'title': 'Bot Chat', 'include_hidden': True, 'profile': bot}).get('result') or {}).get('sessions') or [])]}"]
        db_path = find_db(bot)
        if db_path and old and new:
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                o = cur.execute("SELECT archived, hidden, title FROM sessions WHERE id=?", (old,)).fetchone()
                n = cur.execute("SELECT title, hidden, source, archived FROM sessions WHERE id=?", (new,)).fetchone()
                con.close()
                if o:
                    ctx.append(f"old archived={o['archived']} hidden={o['hidden']} title={o['title']!r}")
                if n:
                    ctx.append(f"new title={n['title']!r} hidden={n['hidden']} source={n['source']!r} archived={n['archived']}")
            except Exception as exc:
                ctx.append(f"db ERR {exc}")
        else:
            ctx.append("state.db 不在本机，仅 RPC 侧核验")
        print(f"  {bot}: " + " | ".join(ctx))

    roster = {p["name"]: (p.get("canonical_session") or {}).get("id") for p in
              (call("profiles.list").get("result") or {}).get("profiles", [])}
    for entry in rows:
        print(f"  roster {entry['bot']}: canonical={roster.get(entry['bot'])} (new={entry.get('new')})")


if __name__ == "__main__":
    if not has_websockets():
        python = venv_python()
        if python:
            os.execv(python, [python, os.path.abspath(__file__), *sys.argv[1:]])
        raise SystemExit("需要 websockets：用 Hermes venv 的 python 跑，或 HERMES_PYTHON=<python> 指定。")
    main()
