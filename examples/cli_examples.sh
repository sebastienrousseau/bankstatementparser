#!/usr/bin/env bash
set -euo pipefail

python -m bankstatementparser.cli \
  --type camt \
  --input ./tests/test_data/camt.053.001.02.xml

python -m bankstatementparser.cli \
  --type camt \
  --input ./tests/test_data/camt.053.001.02.xml \
  --output /tmp/camt-cli.csv \
  --streaming

python -m bankstatementparser.cli \
  --type pain001 \
  --input ./tests/test_data/pain.001.001.03.xml \
  --output /tmp/pain001-cli.csv
