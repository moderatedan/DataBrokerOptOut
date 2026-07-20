# Publishing DataBrokerOptOut

This is a local desktop tool — "deployment" means publishing the repo and
optionally packaging it for non-technical users.

## Push to GitHub

```bash
git init
git add .
git commit -m "v2: 40-broker database, GUI, CCPA/GDPR templates, verification scheduler"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/DataBrokerOptOut.git
git push -u origin main
```

Before pushing, double-check nothing personal is staged:

```bash
git status --ignored | grep data/   # should show data/ as ignored
```

## Recommended repo settings

- **Topics:** `privacy`, `data-brokers`, `ccpa`, `gdpr`, `opt-out`, `osint-defense`, `python`
- **About:** "Guided, tracked opt-outs from 40 data brokers. Zero dependencies, local-only."
- Enable **Issues** — dead opt-out URLs are the main community contribution.
- Add an issue template asking for: broker name, old URL, new URL, date checked.

## Optional: single-file executable for non-technical users

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "brokers.json:." databroker_optout.py
# result in dist/  — attach to a GitHub Release
```

Note: when packaged, add `brokers.json` beside the executable or adjust
BROKERS_FILE to check sys._MEIPASS for the bundled copy.

## Post-publish checklist

- [ ] Replace `YOUR_USERNAME` in README.md, `YOUR_NAME` in LICENSE
- [ ] Take the three screenshots referenced in README (`docs/`)
- [ ] Spot-check 5–10 opt-out URLs in brokers.json before your first release —
      they rot quickly, and accuracy is this project's whole value
- [ ] Tag a release: `git tag v2.0.0 && git push --tags`
