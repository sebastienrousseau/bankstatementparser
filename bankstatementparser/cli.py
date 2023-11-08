# Copyright (C) 2023 Sebastien Rousseau.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This module provides a command line interface for parsing bank statement
files in various formats. Currently, it supports CAMT (ISO 20022) format, with
potential to extend support to other formats.
"""

import argparse
import os
import pandas as pd
import sys
from bankstatementparser import CamtParser, Pain001Parser


class BankStatementCLI:
    """A command line interface for parsing bank statement files."""

    def __init__(self):
        """Initialize the CLI by setting up the argument parser."""
        self.parser = self.setup_arg_parser()

    def setup_arg_parser(self):
        """
        Set up the command line argument parser.

        Returns:
            argparse.ArgumentParser: The configured argument parser.
        """
        parser = argparse.ArgumentParser(
            description='Parse bank statement files.')
        parser.add_argument(
            '--type', type=str, required=True, choices=['camt', 'pain001'],
            help='Type of the bank statement file: "camt" or "pain001".')
        parser.add_argument(
            '--input', type=str, required=True,
            help='Path to the bank statement file.')
        parser.add_argument(
            '--output', type=str, required=False,
            help='Path to save parsed data; if not provided, data is printed.')
        return parser

    def parse_camt(self, file_path, output_path=None):
        """
        Parse a CAMT format bank statement file and print or save the results.

        Args:
            file_path (str): Path to the CAMT file.
            output_path (str, optional): Path to save the parsed data. If None,
            data is printed to console.
        """
        try:
            parser = CamtParser(file_path)
            data = parser.get_statement_stats()
            print("Data returned by get_statement_stats:")
            print(data)
            print("Type of data:", type(data))

            if isinstance(data, dict):
                data = [data]

            data_df = pd.DataFrame(data)

            if output_path:
                data_df.to_csv(output_path, index=False)
                print(f"Parsed data saved to {output_path}")
            else:
                print(data_df)
        except Exception as e:
            print(f"Error: {str(e)}")
            sys.exit(1)

    def parse_pain(self, file_path, output_path=None):
        """
        Parse a PAIN.001 format bank statement file and print or save the
        results.

        Args:
            file_path (str): Path to the PAIN.001 file.
            output_path (str, optional): Path to save the parsed data. If None,
            data is printed to console.
        """
        try:
            # Instantiate the PAIN.001 parser
            parser = Pain001Parser(file_path)

            # Perform the parsing
            parsed_data = parser.parse()

            data_df = pd.DataFrame(parsed_data)

            if output_path:
                data_df.to_csv(output_path, index=False)
                print(f"Parsed data saved to {output_path}")
            else:
                print(data_df)
        except Exception as e:
            print(f"Error: {str(e)}")
            sys.exit(1)

    def run(self):
        """Parse command line arguments and perform the requested action."""
        if len(sys.argv) == 1:
            self.parser.print_help(sys.stderr)
            sys.exit(1)

        args = self.parser.parse_args()

        if not os.path.isfile(args.input):
            print("Error: The specified input file does not exist.")
            sys.exit(1)

        if args.type == 'camt':
            self.parse_camt(args.input, args.output)
        elif args.type == 'pain001':
            self.parse_pain(args.input, args.output)
        else:
            print("Error: The specified type is not supported.")
            sys.exit(1)


if __name__ == "__main__":
    cli = BankStatementCLI()
    cli.run()
