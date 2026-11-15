# Convert corpus (gate)

20 PDF fixtures from pdf-stand + expected table JSON + golden `.xlsx` from live `pdfexel-api`.

`tests/test_corpus.py` runs on every CI/push: orchestrator must call pdf-stand → json-stand and produce cells matching `expected/*.json`.
