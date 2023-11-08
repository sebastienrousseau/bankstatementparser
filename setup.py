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
#
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path
from setuptools import setup, find_packages

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup_requirements = []
test_requirements = ["pytest>=7.4.2"]

setup(
    name='bankstatementparser',
    version='0.0.1',
    description="""
BankStatementParser is your essential tool for easy bank statement management.
Designed with finance and treasury experts in mind, it offers a simple way to
handle CAMT (ISO 20022) formats and more. Get quick, accurate insights from
your financial data and spend less time on processing. It's the smart, hassle-
free way to stay on top of your transactions.
""",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Sebastien Rousseau",
    author_email="sebastian.rousseau@gmail.com",
    url="https://bankstatementparser.com",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS",
        "Operating System :: OS Independent",
        "Operating System :: POSIX",
        "Operating System :: Unix",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    install_requires=[
        'lxml>=4.9.3',
        'openpyxl>=3.1.2',
        'pandas>=2.1.1',
        'requests>=2.31.0'
    ],
    keywords="""
        banking, finance, parsing, CAMT, ISO20022, treasury, SEPA, analysis,
        transactions, reporting
    """,
    license="Apache Software License",
    packages=find_packages(exclude=['docs', 'tests*']),
    python_requires='>=3.9,<3.13',
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
    test_suite="tests",
)
