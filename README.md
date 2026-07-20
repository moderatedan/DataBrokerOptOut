# 🕵️ DataBrokerOptOut

> Data brokers scraped your life without asking. This is the checklist that gets it back — with auto-drafted legal requests, progress tracking, and a verification scheduler that catches listings when they sneak back.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)
![Brokers](https://img.shields.io/badge/brokers%20covered-40-orange.svg)

Opting out of data brokers is deliberately tedious: 40+ sites, each with its own form, email address, or suppression portal — and half of them quietly re-list you months later. DataBrokerOptOut turns that mess into a tracked workflow you can actually finish.

**Design honesty:** this tool does *not* headlessly auto-submit forms. Broker forms use CAPTCHAs, phone verification, and constant layout churn, so "fully automatic" tools silently fail. Instead, DataBrokerOptOut optimizes every second of the human loop: your info lands on the clipboard, the right page opens in your browser, email-based brokers get a fully drafted CCPA/GDPR request in your mail client, and everything is timestamped and scheduled for re-verification.

---

## ✨ Features

- **40-broker curated database** (`brokers.json`) — people-search sites, B2B contact scrapers, marketing-data giants (Acxiom, Epsilon), and risk-data brokers (LexisNexis, CoreLogic), each with method, difficulty rating, and re-check interval. Community PRs to extend it are welcome.
- **Auto-fill assist** — one command copies your "info pack" to the clipboard and opens the broker's opt-out page. Email-based brokers get a fully drafted request opened straight in your mail client.
- **Legal request templates** — CCPA/CPRA, GDPR Article 17, and a generic removal letter, auto-filled from your profile and saved to `data/outbox/` for your records.
- **GUI** — a tkinter interface (no dependencies) with a sortable broker table, status color-coding, filtering, one-click actions, and a progress bar.
- **Progress tracking** — five statuses per broker (`not_started → submitted → awaiting_confirmation → verified_removed`, plus `reappeared`), with timestamps, notes, and full history in `data/progress.json`.
- **Verification system** — every broker has a re-check interval (30–120 days). `verify` tells you exactly what's due, opens a site-scoped search for your name, and tracks reappearances so repeat offenders get re-submitted.
- **CSV export** — for your records, or for a CCPA complaint paper trail.
- **Local-only by design** — the script itself makes zero network requests. Your profile lives in `./data/` (gitignored) and never leaves your machine.

## 📸 Screenshots

> _Add your screenshots here:_

| GUI overview | Verification due | CLI dashboard |
|---|---|---|
| ![GUI](docs/screenshot-gui.png) | ![Verify](docs/screenshot-verify.png) | ![CLI](docs/screenshot-cli.png) |

## 🚀 Installation

```bash
git clone https://github.com/YOUR_USERNAME/DataBrokerOptOut.git
cd DataBrokerOptOut
python3 databroker_optout.py   # that's it — zero dependencies, launches the GUI
```

Requires Python 3.9+. The GUI needs tkinter, which ships with Python on Windows and macOS; on Linux: `sudo apt install python3-tk` (Debian/Ubuntu) or `sudo dnf install python3-tkinter` (Fedora).

## 📖 Usage

### GUI (easiest)

```bash
python3 databroker_optout.py gui
```

1. Click **Edit profile** and fill in the info brokers use to index you (name, emails, addresses). It's saved locally only.
2. Select a broker → **Open opt-out page**. Your info pack is on the clipboard; paste into the form. The broker is auto-marked *Submitted*.
3. For email-based brokers, click **Draft email** and pick `ccpa`, `gdpr`, or `generic` — the finished request opens in your mail client.
4. When confirmation emails arrive, mark **✓ Confirmed**; once you've checked the listing is gone, **✓✓ Verified removed**.
5. Check the **Due for re-check only** box periodically — brokers that quietly re-list you will show up here. Mark them **✗ Reappeared** and re-submit.

### CLI

```bash
python3 databroker_optout.py profile              # one-time setup
python3 databroker_optout.py list                 # all brokers + status
python3 databroker_optout.py list --status not_started --category people-search
python3 databroker_optout.py start spokeo truepeoplesearch fastpeoplesearch
python3 databroker_optout.py email mylife --law ccpa
python3 databroker_optout.py mark spokeo awaiting_confirmation -n "conf email received"
python3 databroker_optout.py status               # progress dashboard
python3 databroker_optout.py verify --open        # what's due, opened in browser
python3 databroker_optout.py export progress.csv
```

**Suggested first session:** knock out the easy ones in ~20 minutes:

```bash
python3 databroker_optout.py start truepeoplesearch fastpeoplesearch usphonebook peoplefinders spokeo
```

## 🗂️ How data is stored

```
data/                     ← gitignored, local only
├── profile.json          ← your info (plaintext — see privacy note)
├── progress.json         ← per-broker status + full history
└── outbox/               ← copies of every email you drafted
```

**Privacy note:** `profile.json` is plaintext on your own disk. That's the same information you're typing into broker forms anyway, but if the machine is shared, consider full-disk encryption. Never commit `data/` — the `.gitignore` already blocks it.

## ⚖️ Legal background (US)

The CCPA/CPRA (California) and a growing list of state laws (Virginia, Colorado, Connecticut, Texas, and others) give consumers deletion and opt-out rights, with statutory response deadlines. The bundled templates cite these; brokers frequently honor CCPA-styled requests from non-Californians rather than maintain separate flows. California residents can also use the state's [DELETE Act / Delete Request and Opt-out Platform (DROP)](https://cppa.ca.gov/) as it rolls out. None of this is legal advice — for disputes, consult a lawyer or your state AG's consumer division.

## 🤔 FAQ

**Why not fully automatic?** CAPTCHAs, phone verification, email confirmation loops, and weekly form redesigns. Tools that claim full automation either break silently (worse than manual — you *think* you're removed) or are paid services with human operators. This tool makes the manual loop ~10x faster and, crucially, *verified*.

**Why do listings come back?** Brokers continuously re-ingest public records and purchased datasets. That's exactly what the re-check scheduler and the `reappeared` status exist for. Suppression at upstream sources (Acxiom, Epsilon, LexisNexis — all in the database) reduces re-listing downstream.

**Paid alternatives?** DeleteMe, Optery, and Kanary do this as a subscription service. This tool is the free, local, auditable version.

## 🤝 Contributing

The most valuable PRs update `brokers.json`: fixing dead opt-out URLs, adding brokers, correcting methods. Broker endpoints change constantly — if you hit a 404, you've found a contribution.

## 📄 License

[MIT](LICENSE)
