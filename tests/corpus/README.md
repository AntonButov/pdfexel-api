# Convert corpus (gate)

- **20** base fixtures from pdf-stand (`01_`…`20_`)
- **5** hard fixtures (`H01_`…`H05_`): long invoice, wide finance, Russian act, multipage catalog, dense dual tables

Each case: `pass/*.pdf` + `expected/*.json` + `golden/*.xlsx`.

`tests/test_corpus.py` runs on every CI/push: orchestrator must call pdf-stand → json-stand and produce cells matching `expected/*.json`.
