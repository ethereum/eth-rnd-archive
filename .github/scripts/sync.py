#!/usr/bin/env python3
import datetime
import glob
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

GUILD = "595666850260713488"
API = "https://discord.com/api/v9"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
ARCHIVE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(ARCHIVE, ".github", "sync-state.json")
TOKEN = os.environ.get("DISCORD_TOKEN") or open(os.path.expanduser("~/.config/discord/token")).read().strip()
BOT_STOPPED = "2026-10-09T17:30:00+00:00"
EPOCH = 1420070400000
VIEW, HISTORY, ADMIN = 1 << 10, 1 << 16, 8
BURST = int(os.environ.get("SYNC_BURST", 0))
REST = float(os.environ.get("SYNC_REST", 600))
requests_made = 0


def log(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def snowflake(iso):
    ms = int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)
    return ((ms - EPOCH) << 22) | 0x3FFFFF


def pause():
    d = random.uniform(3, 9)
    if random.random() < 0.12:
        d += random.uniform(10, 30)
    time.sleep(d)


def api(path):
    global requests_made
    while True:
        req = urllib.request.Request(API + path, headers={"Authorization": TOKEN, "User-Agent": UA})
        try:
            body = urllib.request.urlopen(req, timeout=60).read()
            requests_made += 1
            pause()
            if BURST and requests_made % BURST == 0:
                rest = random.uniform(REST * 0.7, REST * 1.3)
                log(f"{requests_made} requests, resting {round(rest)}s")
                time.sleep(rest)
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = float(json.load(e).get("retry_after", 30)) + random.uniform(5, 20)
                log("429, waiting", round(wait))
                time.sleep(wait)
                continue
            if e.code == 401:
                sys.exit("token rejected (401)")
            log("HTTP", e.code, path)
            pause()
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            log("network error", e, "retrying")
            time.sleep(random.uniform(20, 40))


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {"last": {}, "threads_checked": {}}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    json.dump(state, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE_PATH)


def dir_last_id(d):
    files = sorted(glob.glob(os.path.join(glob.escape(d), "[0-9]*.json")))
    if not files:
        return None
    msgs = json.load(open(files[-1]))
    if not msgs:
        return None
    return snowflake(max(m["created_at"] for m in msgs))


def thread_dir(channel_name, name):
    flat = os.path.join(ARCHIVE, re.sub(r"[^A-Za-z0-9-]", "_", name))
    nested = os.path.join(ARCHIVE, channel_name, "_threads", re.sub(r"[^A-Za-z0-9 !#&'()+,\-.@\[\]_`{}]", "_", name).rstrip(". ") or "_")
    if not os.path.isdir(nested) and os.path.isdir(flat):
        return flat
    return nested


def fetch_attachment(a, d):
    try:
        data = urllib.request.urlopen(urllib.request.Request(a["url"], headers={"User-Agent": UA}), timeout=120).read()
    except Exception as e:
        log("attachment failed", a.get("filename"), e)
        return ""
    h = hashlib.sha256(data).hexdigest()
    os.makedirs(os.path.join(d, "attachments"), exist_ok=True)
    p = os.path.join(d, "attachments", h + ".bin")
    if not os.path.exists(p):
        open(p, "wb").write(data)
    time.sleep(random.uniform(1, 3))
    return h


def write_messages(d, msgs, category, parent):
    by_day = {}
    for m in msgs:
        entry = {
            "author": m["author"]["username"],
            "category": category,
            "parent": parent,
            "content": m["content"],
            "created_at": m["timestamp"],
            "attachments": [
                {"type": a.get("content_type", ""), "origin_name": a["filename"], "content": fetch_attachment(a, d)}
                for a in m.get("attachments", [])
            ],
        }
        by_day.setdefault(m["timestamp"][:10], []).append(entry)
    os.makedirs(d, exist_ok=True)
    for day, entries in by_day.items():
        p = os.path.join(d, day + ".json")
        existing = json.load(open(p)) if os.path.exists(p) else []
        seen = {(e["created_at"], e["author"], e["content"]) for e in existing}
        existing += [e for e in entries if (e["created_at"], e["author"], e["content"]) not in seen]
        existing.sort(key=lambda e: e["created_at"])
        open(p, "w").write(json.dumps(existing, indent=2, ensure_ascii=False))


def sync_messages(cid, after, d, category, parent, state):
    total = 0
    while True:
        page = api(f"/channels/{cid}/messages?after={after}&limit=100")
        if not page:
            break
        page.sort(key=lambda m: int(m["id"]))
        write_messages(d, page, category, parent)
        after = int(page[-1]["id"])
        state["last"][cid] = after
        save_state(state)
        total += len(page)
        if len(page) < 100:
            break
    return total


def threads_since(cid, since):
    out = {}
    for archived in ("false", "true"):
        offset = 0
        while True:
            r = api(f"/channels/{cid}/threads/search?archived={archived}&sort_by=last_message_time&sort_order=desc&limit=25&offset={offset}")
            if not r or not r.get("threads"):
                break
            fresh = [t for t in r["threads"] if int(t.get("last_message_id") or 0) > since]
            for t in fresh:
                out[t["id"]] = t
            if len(fresh) < len(r["threads"]) or not r.get("has_more"):
                break
            offset += 25
    return out.values()


def main():
    state = load_state()
    run_started = snowflake(datetime.datetime.now(datetime.timezone.utc).isoformat())
    guild = api(f"/guilds/{GUILD}")
    channels = api(f"/guilds/{GUILD}/channels")
    me = api(f"/users/@me/guilds/{GUILD}/member")
    uid, my_roles = me["user"]["id"], set(me["roles"])
    role_perms = {r["id"]: int(r["permissions"]) for r in guild["roles"]}
    base = role_perms[GUILD]
    for r in my_roles:
        base |= role_perms.get(r, 0)

    def readable(c):
        if base & ADMIN or guild.get("owner_id") == uid:
            return True
        p = base
        ow = {o["id"]: o for o in c.get("permission_overwrites", [])}
        if GUILD in ow:
            p = (p & ~int(ow[GUILD]["deny"])) | int(ow[GUILD]["allow"])
        allow = deny = 0
        for r in my_roles:
            if r in ow:
                allow |= int(ow[r]["allow"])
                deny |= int(ow[r]["deny"])
        p = (p & ~deny) | allow
        if uid in ow:
            p = (p & ~int(ow[uid]["deny"])) | int(ow[uid]["allow"])
        return p & VIEW and p & HISTORY

    cats = {c["id"]: c["name"] for c in channels if c["type"] == 4}
    todo = [c for c in channels if c["type"] in (0, 5) and readable(c)]
    random.shuffle(todo)
    default_after = snowflake(BOT_STOPPED)
    grand = 0
    for n, c in enumerate(todo, 1):
        cid, name = c["id"], c["name"]
        category = cats.get(c.get("parent_id"), "")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        d = os.path.join(ARCHIVE, safe)
        after = state["last"].get(cid) or dir_last_id(d) or default_after
        got = 0
        if int(c.get("last_message_id") or 0) > after:
            got = sync_messages(cid, after, d, category, "", state)
        tgot = tcount = 0
        if "Graveyard" not in category:
            since = state["threads_checked"].get(cid, default_after)
            for t in threads_since(cid, since):
                td = thread_dir(safe, t["name"])
                tafter = state["last"].get(t["id"]) or dir_last_id(td) or 0
                if int(t.get("last_message_id") or 0) <= tafter:
                    continue
                k = sync_messages(t["id"], tafter, td, category, name, state)
                tgot += k
                tcount += 1
            state["threads_checked"][cid] = run_started
            save_state(state)
        grand += got + tgot
        log(f"[{n}/{len(todo)}] #{name}: {got} msgs, {tgot} msgs in {tcount} threads (requests so far: {requests_made})")
    log(f"done: {grand} messages, {requests_made} requests")


if __name__ == "__main__":
    main()
