<!-- markdownlint-disable MD033 MD041 -->

<img
    src="https://kura.pro/bankstatementparser/images/logos/bankstatementparser.webp"
    alt="Logo of Bank Statement Parser"
    width="261"
    align="right" />

<!-- markdownlint-enable MD033 MD041 -->

# Bank Statement Parser v0.0.1 🐍

![Bank Statement Parser banner][banner]

## The Bank Statement Parser is a Python library built for Finance and Treasury Professionals

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

[banner]: https://kura.pro/bankstatementparser/images/titles/title-bankstatementparser.webp "Bank Statement Parser banner"

## Changelog
