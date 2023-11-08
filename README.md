<!-- markdownlint-disable MD033 MD041 -->

<img
    src="https://kura.pro/bankstatementparser/images/logos/bankstatementparser.webp"
    alt="Logo of Bank Statement Parser"
    width="261"
    align="right" />

<!-- markdownlint-enable MD033 MD041 -->

# Bank Statement Parser: Automate Your Bank Statement Processing

![Bank Statement Parser banner][banner]

## The Bank Statement Parser is a Python library built for Finance and Treasury Professionals

[![PyPI][pypi-badge]][03] [![PyPI Downloads][pypi-downloads-badge]][07] [![License][license-badge]][01] [![Codecov][codecov-badge]][06]

## Overview

The Bank Statement Parser is an essential Python library for financial data management. Developed for the busy finance and treasury professional, it simplifies the task of parsing bank statements.

This tool simplifies the process of analysing CAMT and SEPA transaction files. Its streamlined design removes cumbersome manual data review and provides you with a concise, accurate report to facilitate further analysis.

Bank Statement Parser helps you save time by quickly and accurately processing data, allowing you to focus on your financial insights and decisions. Its reliable precision is powered by Python, making it the smarter, more efficient way to manage bank statements.

## Key Features

- **Versatile Parsing**: Easily handle formats like CAMT (ISO 20022) and beyond.
- **Financial Insights**: Unlock detailed analysis with powerful calculation utilities.
- **Simple CLI**: Automate and integrate with a straightforward command-line interface.

### Why Choose the Bank Statement Parser

- **Designed for Finance**: Tailored features for the finance sector's needs.
- **Efficiency at Heart**: Transform complex data tasks into simple ones.
- **Community First**: Built and enhanced by experts, for experts.

### Functionality

- **CamtParser**: Parse CAMT format files with ease.
- **Pain001Parser**: Handle SEPA PAIN.001 files effortlessly.

## Installation

### Create a Virtual Environment

We recommend creating a virtual environment to install the Bank Statement Parser. This will ensure that the package is installed in an isolated environment and will not affect other projects.

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
```

### Getting Started

Install `bankstatementparser` with just one command:

```bash
pip install bankstatementparser
```

## Usage

### CAMT Files

```python
from bankstatementparser import CamtParser

# Initialize the parser with the CAMT file path
camt_parser = CamtParser('path/to/camt/file.xml')

# Parse the file and get the results
results = camt_parser.parse()
```

### PAIN.001 Files

```python
from bankstatementparser import Pain001Parser

# Initialize the parser with the PAIN.001 file path
pain_parser = Pain001Parser('path/to/pain/file.xml')

# Parse the file and get the results
results = pain_parser.parse()
```

## Command Line Interface (CLI) Guide

Leverage the CLI for quick parsing tasks:

### Basic Command

```bash
python cli.py --type <file_type> --input <input_file> [--output <output_file>]
```

- `--type`: Type of the bank statement file. Currently supported types are "camt" and "pain001".
- `--input`: Path to the bank statement file.
- `--output`: (Optional) Path to save the parsed data. If not provided, data is printed to the console.

### Examples for CAMT Files

1. Parse a CAMT file and print the results to the console:

   ```bash
   python cli.py --type camt --input path/to/camt/camt_file.xml
   ```

   Using the test data:

   ```bash
   python ./bankstatementparser/cli.py --type camt --input ./tests/test_data/camt.053.001.02.xml
   ```

2. Parse a CAMT file and save the results to a CSV file:

   ```bash
   python cli.py --type camt --input path/to/camt/file.xml --output path/to/output/file.csv
   ```

   Using the test data:

   ```bash
   python ./bankstatementparser/cli.py --type camt --input ./tests/test_data/camt.053.001.02.xml --output ./tests/test_data/camt_file.csv
   ```

### Examples for PAIN.001 Files

1. Parse a PAIN.001.001.03 file and print the results to the console:

```bash
python cli.py --type pain001 --input path/to/pain.001.001.03.xml
```

Using the test data:

```bash
python ./bankstatementparser/cli.py --type pain001 --input ./tests/test_data/pain.001.001.03.xml
```

2. Parse a PAIN.001.001.03 file and save the results to a CSV file:

```bash
python cli.py --type pain001 --input path/to/pain.001.001.03.xml --output path/to/output/file.csv
```

Using the test data:

```bash
python ./bankstatementparser/cli.py --type pain001 --input ./tests/test_data/pain.001.001.03.xml --output ./tests/test_data/pain_file.csv
```

## License

The project is licensed under the terms of both the MIT license and the
Apache License (Version 2.0).

- [Apache License, Version 2.0][01]
- [MIT license][02]

## Contribution

We welcome contributions to **bankstatementparser**. Please see the
[contributing instructions][04] for more information.

Unless you explicitly state otherwise, any contribution intentionally
submitted for inclusion in the work by you, as defined in the
Apache-2.0 license, shall be dual licensed as above, without any
additional terms or conditions.

## Acknowledgements

We would like to extend a big thank you to all the awesome contributors
of [bankstatementparser][05] for their help and support.

This repo was inspired by [khorevkp/KK_Tools][08]'s innovative use of data
structures and algorithms, and was forked to build upon its foundation. Thank
you to [Konstantin Khorev][09]

[01]: https://opensource.org/license/apache-2-0/ "Apache License, Version 2.0"
[02]: http://opensource.org/licenses/MIT "MIT license"
[03]: https://github.com/sebastienrousseau/bankstatementparser "Bank Statement Parser on GitHub"
[04]: https://github.com/sebastienrousseau/bankstatementparser/blob/main/CONTRIBUTING.md "Contributing instructions"
[05]: https://github.com/sebastienrousseau/bankstatementparser/graphs/contributors "Contributors"
[06]: https://codecov.io/github/sebastienrousseau/bankstatementparser?branch=main "Codecov"
[07]: https://pypi.org/project/bankstatementparser/ "Bank Statement Parser on PyPI"
[08]: https://github.com/khorevkp/KK_Tools "KK_Tools on GitHub"
[09]: https://github.com/khorevkp "Konstantin Khorev on GitHub"

[banner]: https://kura.pro/bankstatementparser/images/titles/title-bankstatementparser.webp "Bank Statement Parser banner"
[codecov-badge]: https://img.shields.io/codecov/c/github/sebastienrousseau/pain001?style=for-the-badge&token=AaUxKfRiou 'Codecov badge'
[license-badge]: https://img.shields.io/pypi/l/pain001?style=for-the-badge 'License badge'
[pypi-badge]: https://img.shields.io/pypi/pyversions/pain001.svg?style=for-the-badge 'PyPI badge'
[pypi-downloads-badge]:https://img.shields.io/pypi/dm/pain001.svg?style=for-the-badge 'PyPI Downloads badge'
