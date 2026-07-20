#!/usr/bin/env python3
"""
DataBrokerOptOut — a guided, tracked workflow for removing yourself from data brokers.

Design philosophy
-----------------
Fully headless automation of broker opt-out forms is brittle (CAPTCHAs, layout
churn, phone verification) and often violates site terms. This tool instead
optimizes the human loop:

  * a curated broker database (brokers.json) with method, difficulty, and URLs
  * "auto-fill assist": your info pack on the clipboard + the form opened in
    your browser, plus fully drafted CCPA/GDPR/deletion-request emails
  * per-broker progress tracking with timestamps and notes
  * a verification scheduler that tells you when to re-check each broker and
    flags listings that reappear

Everything is stored locally in ./data (gitignored). No network calls are made
by this script itself — your browser and mail client do the talking.

Usage
-----
  python3 databroker_optout.py gui              # graphical interface
  python3 databroker_optout.py profile          # set up your info (one time)
  python3 databroker_optout.py list             # show all brokers + status
  python3 databroker_optout.py start spokeo     # open opt-out page, copy info
  python3 databroker_optout.py email mylife     # draft a CCPA email
  python3 databroker_optout.py mark spokeo submitted -n "used listing URL xyz"
  python3 databroker_optout.py status           # progress dashboard
  python3 databroker_optout.py verify           # what's due for a re-check
  python3 databroker_optout.py export out.csv   # export progress to CSV

License: MIT
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import textwrap
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# --------------------------------------------------------------------------- #
# Paths & constants
# --------------------------------------------------------------------------- #

APP_NAME = "DataBrokerOptOut"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTBOX_DIR = DATA_DIR / "outbox"
BROKERS_FILE = BASE_DIR / "brokers.json"
PROFILE_FILE = DATA_DIR / "profile.json"
PROGRESS_FILE = DATA_DIR / "progress.json"

STATUSES = [
    "not_started",
    "submitted",
    "awaiting_confirmation",
    "verified_removed",
    "reappeared",
]

STATUS_LABELS = {
    "not_started": "Not started",
    "submitted": "Submitted",
    "awaiting_confirmation": "Awaiting confirmation",
    "verified_removed": "Verified removed",
    "reappeared": "Reappeared!",
}

DATE_FMT = "%Y-%m-%d %H:%M"

# --------------------------------------------------------------------------- #
# Email templates ("auto-fill" for email-based brokers)
# --------------------------------------------------------------------------- #

TEMPLATES = {
    "ccpa": {
        "subject": "Request to Delete Personal Information — {full_name}",
        "body": """\
To whom it may concern at {broker_name},

I am a consumer exercising my rights under applicable U.S. state privacy law,
including (where applicable) the California Consumer Privacy Act as amended by
the CPRA, Cal. Civ. Code § 1798.100 et seq.

I request that you:

  1. DELETE all personal information you hold about me;
  2. OPT ME OUT of the sale or sharing of my personal information;
  3. SUPPRESS my information from reappearing in your products; and
  4. CONFIRM in writing when these actions are complete.

Information to locate my records:

  Full name:        {full_name}
  Also known as:    {aliases}
  Email address(es): {emails}
  Phone number(s):  {phones}
  Current address:  {current_address}
  Past address(es): {past_addresses}
  Approximate age:  {age}

Please treat this as a verifiable consumer request. If you require additional
verification, contact me at {primary_email}. Note that state law requires a
response within the statutory deadline (45 days under the CCPA/CPRA).

Please do not use the information in this request for any purpose other than
processing it.

Regards,
{full_name}
{date}
""",
    },
    "gdpr": {
        "subject": "Erasure Request under GDPR Article 17 — {full_name}",
        "body": """\
Dear Data Protection Officer at {broker_name},

I am exercising my right to erasure under Article 17 of the General Data
Protection Regulation (GDPR), and my right to object to processing under
Article 21, including processing for direct marketing purposes.

I request that you:

  1. ERASE all personal data you hold concerning me;
  2. CEASE all processing of my personal data, including profiling;
  3. INFORM any recipients to whom my data has been disclosed of this
     erasure, per Article 19; and
  4. CONFIRM completion in writing within one month, per Article 12(3).

Information to locate my records:

  Full name:        {full_name}
  Also known as:    {aliases}
  Email address(es): {emails}
  Phone number(s):  {phones}
  Current address:  {current_address}
  Past address(es): {past_addresses}

If you do not normally handle GDPR requests, please forward this to the person
responsible for data protection in your organization. If you believe an
exemption applies, please identify it and the reasoning in your response.

Regards,
{full_name}
{date}
""",
    },
    "generic": {
        "subject": "Data Removal / Opt-Out Request — {full_name}",
        "body": """\
Hello {broker_name} team,

Please remove all records about me from your website, databases, and any
derived or affiliated products, and suppress my information from future
collection where your systems support it.

Information to locate my records:

  Full name:        {full_name}
  Also known as:    {aliases}
  Email address(es): {emails}
  Phone number(s):  {phones}
  Current address:  {current_address}
  Past address(es): {past_addresses}

Please confirm by email to {primary_email} once the removal is complete, and
do not use the information in this request for any other purpose.

Thank you,
{full_name}
{date}
""",
    },
}

# --------------------------------------------------------------------------- #
# Storage helpers
# --------------------------------------------------------------------------- #


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    OUTBOX_DIR.mkdir(exist_ok=True)


def load_json(path: Path, default):
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return default


def save_json(path: Path, data) -> None:
    ensure_dirs()
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def load_brokers() -> list[dict]:
    if not BROKERS_FILE.exists():
        sys.exit(f"brokers.json not found next to {Path(__file__).name} — "
                 "re-clone the repository or restore the file.")
    data = load_json(BROKERS_FILE, {})
    return data.get("brokers", [])


def load_profile() -> dict:
    return load_json(PROFILE_FILE, {})


def load_progress() -> dict:
    return load_json(PROGRESS_FILE, {})


# --------------------------------------------------------------------------- #
# Domain logic
# --------------------------------------------------------------------------- #


@dataclass
class BrokerView:
    """A broker joined with its progress record."""

    broker: dict
    record: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.broker["id"]

    @property
    def status(self) -> str:
        return self.record.get("status", "not_started")

    @property
    def last_action(self) -> datetime | None:
        ts = self.record.get("updated")
        return datetime.strptime(ts, DATE_FMT) if ts else None

    @property
    def next_check(self) -> datetime | None:
        """When this broker is due for a verification pass."""
        if self.status in ("not_started", "reappeared"):
            return None
        last = self.last_action
        if not last:
            return None
        return last + timedelta(days=int(self.broker.get("recheck_days", 45)))

    @property
    def is_due(self) -> bool:
        nxt = self.next_check
        return bool(nxt and datetime.now() >= nxt)


def get_views() -> list[BrokerView]:
    progress = load_progress()
    return [BrokerView(b, progress.get(b["id"], {})) for b in load_brokers()]


def find_view(broker_id: str) -> BrokerView:
    for v in get_views():
        if v.id == broker_id:
            return v
    ids = ", ".join(b["id"] for b in load_brokers())
    sys.exit(f"Unknown broker '{broker_id}'. Known ids: {ids}")


def set_status(broker_id: str, status: str, note: str = "") -> None:
    if status not in STATUSES:
        sys.exit(f"Invalid status '{status}'. Choose from: {', '.join(STATUSES)}")
    progress = load_progress()
    rec = progress.setdefault(broker_id, {"history": []})
    rec["status"] = status
    rec["updated"] = datetime.now().strftime(DATE_FMT)
    rec["history"].append(
        {"ts": rec["updated"], "status": status, "note": note}
    )
    if note:
        rec["note"] = note
    save_json(PROGRESS_FILE, progress)


def profile_fields(profile: dict) -> dict:
    """Flatten the profile for template substitution, with safe fallbacks."""
    join = lambda xs: ", ".join(xs) if xs else "—"
    return {
        "full_name": profile.get("full_name", "—"),
        "aliases": join(profile.get("aliases", [])),
        "emails": join(profile.get("emails", [])),
        "primary_email": (profile.get("emails") or ["—"])[0],
        "phones": join(profile.get("phones", [])),
        "current_address": profile.get("current_address", "—"),
        "past_addresses": join(profile.get("past_addresses", [])),
        "age": profile.get("age", "—"),
        "date": datetime.now().strftime("%B %d, %Y"),
    }


def build_email(view: BrokerView, law: str) -> tuple[str, str]:
    tpl = TEMPLATES[law]
    fields = profile_fields(load_profile())
    fields["broker_name"] = view.broker["name"]
    subject = tpl["subject"].format(**fields)
    body = tpl["body"].format(**fields)
    return subject, body


def info_pack(profile: dict) -> str:
    """A paste-ready block for filling web forms quickly."""
    f = profile_fields(profile)
    return (
        f"Full name: {f['full_name']}\n"
        f"Aliases: {f['aliases']}\n"
        f"Email: {f['emails']}\n"
        f"Phone: {f['phones']}\n"
        f"Current address: {f['current_address']}\n"
        f"Past addresses: {f['past_addresses']}\n"
    )


def copy_to_clipboard(text: str) -> bool:
    """Clipboard via tkinter (stdlib, cross-platform). Returns success."""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()  # keeps the clipboard after the window is destroyed
        root.destroy()
        return True
    except Exception:
        return False


def search_url_for(view: BrokerView, profile: dict) -> str:
    """A best-effort 'am I still listed?' search URL on the broker's own site."""
    name = profile.get("full_name", "")
    site = view.broker["optout_url"].split("/")[2] if "//" in view.broker["optout_url"] else ""
    return f"https://duckduckgo.com/?q={quote(f'site:{site} {name}')}"


def progress_summary(views: list[BrokerView]) -> dict:
    total = len(views)
    counts = {s: 0 for s in STATUSES}
    for v in views:
        counts[v.status] += 1
    done = counts["verified_removed"]
    started = total - counts["not_started"]
    return {
        "total": total,
        "counts": counts,
        "done": done,
        "started": started,
        "pct_started": round(100 * started / total) if total else 0,
        "pct_done": round(100 * done / total) if total else 0,
    }


# --------------------------------------------------------------------------- #
# CLI commands
# --------------------------------------------------------------------------- #


def cmd_profile(args) -> None:
    profile = load_profile()
    if args.show:
        if not profile:
            print("No profile yet. Run:  python3 databroker_optout.py profile")
            return
        print(json.dumps(profile, indent=2))
        return

    print("Set up the info used to locate and remove your records.")
    print("Stored ONLY in ./data/profile.json on this machine (gitignored).")
    print("Press Enter to keep the value shown in [brackets].\n")

    def ask(prompt, key, is_list=False):
        current = profile.get(key, [] if is_list else "")
        shown = ", ".join(current) if is_list else current
        raw = input(f"{prompt} [{shown}]: ").strip()
        if not raw:
            return current
        return [x.strip() for x in raw.split(",") if x.strip()] if is_list else raw

    profile["full_name"] = ask("Full legal name", "full_name")
    profile["aliases"] = ask("Aliases/maiden names (comma-separated)", "aliases", True)
    profile["emails"] = ask("Email addresses (comma-separated)", "emails", True)
    profile["phones"] = ask("Phone numbers (comma-separated)", "phones", True)
    profile["current_address"] = ask("Current address", "current_address")
    profile["past_addresses"] = ask("Past addresses (comma-separated)", "past_addresses", True)
    profile["age"] = ask("Approximate age (helps disambiguate)", "age")

    save_json(PROFILE_FILE, profile)
    print(f"\nSaved to {PROFILE_FILE}")


def cmd_list(args) -> None:
    views = get_views()
    if args.category:
        views = [v for v in views if v.broker["category"] == args.category]
    if args.status:
        views = [v for v in views if v.status == args.status]

    print(f"{'ID':<22} {'Broker':<26} {'Method':<6} {'Diff.':<7} {'Status':<22} Next check")
    print("-" * 100)
    for v in views:
        nxt = v.next_check.strftime("%Y-%m-%d") if v.next_check else "—"
        if v.is_due:
            nxt += "  << DUE"
        print(f"{v.id:<22} {v.broker['name']:<26} {v.broker['method']:<6} "
              f"{v.broker['difficulty']:<7} {STATUS_LABELS[v.status]:<22} {nxt}")
    print(f"\n{len(views)} broker(s). Categories: "
          f"{', '.join(sorted({b['category'] for b in load_brokers()}))}")


def cmd_start(args) -> None:
    profile = load_profile()
    if not profile:
        sys.exit("Set up your profile first:  python3 databroker_optout.py profile")

    for broker_id in args.brokers:
        v = find_view(broker_id)
        b = v.broker
        print(f"\n=== {b['name']} ({b['method']}, difficulty: {b['difficulty']}) ===")
        if b.get("notes"):
            print(f"Note: {b['notes']}")
        if b["method"] == "email":
            print("This broker works best by email — generating a draft:")
            _draft_email(v, args.law)
        else:
            if copy_to_clipboard(info_pack(profile)):
                print("Your info pack is on the clipboard — paste as needed.")
            else:
                print("Clipboard unavailable; your info pack:\n" + info_pack(profile))
            print(f"Opening opt-out page: {b['optout_url']}")
            webbrowser.open(b["optout_url"])
        if v.status == "not_started":
            set_status(broker_id, "submitted", "started via CLI")
            print("Marked as 'submitted'. Use `mark` to adjust if you didn't finish.")


def _draft_email(view: BrokerView, law: str) -> Path:
    subject, body = build_email(view, law)
    ensure_dirs()
    fname = OUTBOX_DIR / f"{view.id}-{law}-{datetime.now():%Y%m%d-%H%M%S}.txt"
    fname.write_text(f"To: {view.broker.get('email') or '(find address on their privacy page)'}\n"
                     f"Subject: {subject}\n\n{body}", encoding="utf-8")
    print(f"Draft saved: {fname}")
    if view.broker.get("email"):
        mailto = (f"mailto:{view.broker['email']}?subject={quote(subject)}"
                  f"&body={quote(body)}")
        webbrowser.open(mailto)
        print("Opened in your mail client.")
    return fname


def cmd_email(args) -> None:
    if not load_profile():
        sys.exit("Set up your profile first:  python3 databroker_optout.py profile")
    v = find_view(args.broker)
    _draft_email(v, args.law)


def cmd_mark(args) -> None:
    find_view(args.broker)  # validates id
    set_status(args.broker, args.status, args.note or "")
    print(f"{args.broker} → {STATUS_LABELS[args.status]}")


def cmd_status(_args) -> None:
    views = get_views()
    s = progress_summary(views)
    bar_len = 40
    filled = int(bar_len * s["pct_done"] / 100)
    started_fill = int(bar_len * s["pct_started"] / 100)
    bar = "█" * filled + "▒" * max(0, started_fill - filled) + "·" * (bar_len - started_fill)

    print(f"\n{APP_NAME} — progress\n")
    print(f"  [{bar}] {s['pct_done']}% verified, {s['pct_started']}% started\n")
    for status in STATUSES:
        print(f"  {STATUS_LABELS[status]:<24} {s['counts'][status]:>3}")
    due = [v for v in views if v.is_due]
    reappeared = [v for v in views if v.status == "reappeared"]
    if due:
        print(f"\n  ⚠ {len(due)} broker(s) due for verification — run: "
              f"python3 databroker_optout.py verify")
    if reappeared:
        print(f"  ⚠ {len(reappeared)} listing(s) reappeared — re-submit those opt-outs.")
    print()


def cmd_verify(args) -> None:
    profile = load_profile()
    due = [v for v in get_views() if v.is_due]
    if not due:
        print("Nothing is due for verification. 🎉  (Re-checks are scheduled per "
              "broker; see `list` for dates.)")
        return
    print(f"{len(due)} broker(s) due for a re-check:\n")
    for v in due:
        url = search_url_for(v, profile)
        print(f"  {v.broker['name']:<26} last action {v.record.get('updated')}")
        print(f"    search: {url}")
        if args.open:
            webbrowser.open(url)
    print(textwrap.dedent("""
        After checking each one:
          still gone  → python3 databroker_optout.py mark <id> verified_removed
          it's back   → python3 databroker_optout.py mark <id> reappeared
    """))


def cmd_export(args) -> None:
    views = get_views()
    with open(args.path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "name", "category", "method", "difficulty",
                    "status", "last_action", "next_check", "note", "optout_url"])
        for v in views:
            w.writerow([
                v.id, v.broker["name"], v.broker["category"], v.broker["method"],
                v.broker["difficulty"], v.status,
                v.record.get("updated", ""),
                v.next_check.strftime("%Y-%m-%d") if v.next_check else "",
                v.record.get("note", ""), v.broker["optout_url"],
            ])
    print(f"Exported {len(views)} rows to {args.path}")


# --------------------------------------------------------------------------- #
# GUI (tkinter — stdlib, no extra dependencies)
# --------------------------------------------------------------------------- #


def cmd_gui(_args) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog, ttk
    except Exception as exc:  # pragma: no cover
        sys.exit(f"tkinter is unavailable ({exc}). On Debian/Ubuntu: "
                 "sudo apt install python3-tk")

    COLORS = {
        "not_started": "#6b7280",
        "submitted": "#d97706",
        "awaiting_confirmation": "#2563eb",
        "verified_removed": "#059669",
        "reappeared": "#dc2626",
    }

    root = tk.Tk()
    root.title(f"{APP_NAME} — take your data back")
    root.geometry("1024x640")

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("Treeview", rowheight=26)

    # ---- top bar: progress + filter ------------------------------------- #
    top = ttk.Frame(root, padding=(12, 10))
    top.pack(fill="x")

    progress_var = tk.DoubleVar()
    progress_lbl = ttk.Label(top, text="")
    progress_lbl.pack(side="left")
    pbar = ttk.Progressbar(top, variable=progress_var, length=260, maximum=100)
    pbar.pack(side="left", padx=12)

    ttk.Label(top, text="Filter:").pack(side="left", padx=(24, 4))
    filter_var = tk.StringVar()
    ttk.Entry(top, textvariable=filter_var, width=22).pack(side="left")

    only_due_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(top, text="Due for re-check only",
                    variable=only_due_var).pack(side="left", padx=12)

    # ---- table ----------------------------------------------------------- #
    cols = ("name", "category", "method", "difficulty", "status", "updated", "next")
    tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
    headings = {
        "name": ("Broker", 190), "category": ("Category", 120),
        "method": ("Method", 70), "difficulty": ("Difficulty", 80),
        "status": ("Status", 170), "updated": ("Last action", 130),
        "next": ("Next check", 120),
    }
    for c, (label, width) in headings.items():
        tree.heading(c, text=label)
        tree.column(c, width=width, anchor="w")
    tree.pack(fill="both", expand=True, padx=12)
    for status, color in COLORS.items():
        tree.tag_configure(status, foreground=color)

    # ---- buttons --------------------------------------------------------- #
    btns = ttk.Frame(root, padding=12)
    btns.pack(fill="x")

    def refresh(*_):
        query = filter_var.get().lower().strip()
        tree.delete(*tree.get_children())
        views = get_views()
        for v in views:
            if only_due_var.get() and not v.is_due:
                continue
            hay = f"{v.broker['name']} {v.broker['category']} {v.status}".lower()
            if query and query not in hay:
                continue
            nxt = v.next_check.strftime("%Y-%m-%d") if v.next_check else "—"
            if v.is_due:
                nxt += "  ⚠ due"
            tree.insert("", "end", iid=v.id, tags=(v.status,), values=(
                v.broker["name"], v.broker["category"], v.broker["method"],
                v.broker["difficulty"], STATUS_LABELS[v.status],
                v.record.get("updated", "—"), nxt,
            ))
        s = progress_summary(views)
        progress_var.set(s["pct_done"])
        progress_lbl.config(
            text=f"{s['done']}/{s['total']} verified removed · "
                 f"{s['pct_started']}% started")

    def selected() -> BrokerView | None:
        sel = tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a broker in the table first.")
            return None
        return find_view(sel[0])

    def need_profile() -> dict | None:
        profile = load_profile()
        if not profile:
            messagebox.showwarning(
                APP_NAME,
                "Set up your profile first (Edit profile button, or the "
                "`profile` CLI command).")
            return None
        return profile

    def act_open():
        v = selected()
        profile = need_profile()
        if not v or profile is None:
            return
        if copy_to_clipboard(info_pack(profile)):
            note = "Your info pack is on the clipboard — paste into the form."
        else:
            note = "Clipboard unavailable — use Edit profile to view your info."
        webbrowser.open(v.broker["optout_url"])
        if v.status == "not_started":
            set_status(v.id, "submitted", "opened opt-out page via GUI")
            refresh()
        messagebox.showinfo(APP_NAME, f"Opened {v.broker['name']} opt-out page.\n{note}")

    def act_email():
        v = selected()
        if not v or need_profile() is None:
            return
        law = simpledialog.askstring(
            APP_NAME, "Template: ccpa / gdpr / generic", initialvalue="ccpa")
        if law not in TEMPLATES:
            return
        path = _draft_email(v, law)
        if v.status == "not_started":
            set_status(v.id, "submitted", f"emailed ({law}) via GUI")
        refresh()
        messagebox.showinfo(APP_NAME, f"Draft saved to:\n{path}")

    def act_verify_search():
        v = selected()
        profile = need_profile()
        if not v or profile is None:
            return
        webbrowser.open(search_url_for(v, profile))

    def marker(status):
        def _do():
            v = selected()
            if not v:
                return
            note = simpledialog.askstring(APP_NAME, "Optional note:") or ""
            set_status(v.id, status, note)
            refresh()
        return _do

    def act_profile():
        profile = load_profile()
        win = tk.Toplevel(root)
        win.title("Your profile (stored locally only)")
        entries = {}
        spec = [
            ("full_name", "Full legal name", False),
            ("aliases", "Aliases (comma-separated)", True),
            ("emails", "Emails (comma-separated)", True),
            ("phones", "Phones (comma-separated)", True),
            ("current_address", "Current address", False),
            ("past_addresses", "Past addresses (comma-separated)", True),
            ("age", "Approximate age", False),
        ]
        for row, (key, label, is_list) in enumerate(spec):
            ttk.Label(win, text=label).grid(row=row, column=0, sticky="w",
                                            padx=10, pady=5)
            var = tk.StringVar(value=", ".join(profile.get(key, []))
                               if is_list else profile.get(key, ""))
            ttk.Entry(win, textvariable=var, width=52).grid(
                row=row, column=1, padx=10, pady=5)
            entries[key] = (var, is_list)

        def save():
            data = {}
            for key, (var, is_list) in entries.items():
                raw = var.get().strip()
                data[key] = ([x.strip() for x in raw.split(",") if x.strip()]
                             if is_list else raw)
            save_json(PROFILE_FILE, data)
            win.destroy()
            messagebox.showinfo(APP_NAME, f"Saved to {PROFILE_FILE}")

        ttk.Button(win, text="Save", command=save).grid(
            row=len(spec), column=1, sticky="e", padx=10, pady=10)

    def act_export():
        path = DATA_DIR / f"progress-{datetime.now():%Y%m%d}.csv"
        cmd_export(argparse.Namespace(path=str(path)))
        messagebox.showinfo(APP_NAME, f"Exported to {path}")

    for label, fn in [
        ("Open opt-out page", act_open),
        ("Draft email", act_email),
        ("Check if I'm listed", act_verify_search),
        ("✓ Confirmed", marker("awaiting_confirmation")),
        ("✓✓ Verified removed", marker("verified_removed")),
        ("✗ Reappeared", marker("reappeared")),
        ("Edit profile", act_profile),
        ("Export CSV", act_export),
    ]:
        ttk.Button(btns, text=label, command=fn).pack(side="left", padx=4)

    filter_var.trace_add("write", refresh)
    only_due_var.trace_add("write", refresh)
    tree.bind("<Double-1>", lambda e: act_open())
    refresh()
    root.mainloop()


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="databroker_optout.py",
        description="Guided, tracked opt-outs from data brokers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with no arguments to launch the GUI.",
    )
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("profile", help="set up or show your info")
    sp.add_argument("--show", action="store_true", help="print current profile")
    sp.set_defaults(fn=cmd_profile)

    sp = sub.add_parser("list", help="list brokers and their status")
    sp.add_argument("--category", help="filter by category")
    sp.add_argument("--status", choices=STATUSES, help="filter by status")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("start", help="open opt-out page(s) with your info ready")
    sp.add_argument("brokers", nargs="+", help="broker id(s), see `list`")
    sp.add_argument("--law", choices=list(TEMPLATES), default="ccpa",
                    help="template for email-based brokers")
    sp.set_defaults(fn=cmd_start)

    sp = sub.add_parser("email", help="draft an opt-out email for a broker")
    sp.add_argument("broker", help="broker id")
    sp.add_argument("--law", choices=list(TEMPLATES), default="ccpa")
    sp.set_defaults(fn=cmd_email)

    sp = sub.add_parser("mark", help="update a broker's status")
    sp.add_argument("broker")
    sp.add_argument("status", choices=STATUSES)
    sp.add_argument("-n", "--note", help="optional note")
    sp.set_defaults(fn=cmd_mark)

    sp = sub.add_parser("status", help="progress dashboard")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("verify", help="show brokers due for a re-check")
    sp.add_argument("--open", action="store_true",
                    help="open each verification search in the browser")
    sp.set_defaults(fn=cmd_verify)

    sp = sub.add_parser("export", help="export progress to CSV")
    sp.add_argument("path", help="output .csv path")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("gui", help="launch the graphical interface")
    sp.set_defaults(fn=cmd_gui)

    args = p.parse_args(argv)
    if not args.command:
        cmd_gui(args)
    else:
        args.fn(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # Piping into `head`/`grep` closes stdout early — exit quietly.
        sys.stderr.close()
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
