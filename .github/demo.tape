# Renders .github/demo.gif with VHS (https://github.com/charmbracelet/vhs).
# Run `make demo` from a `poetry install --with dev -E excel` checkout.
# Every command is the project's own, against the fixtures in
# tests/test_data; nothing touches the network.

Output .github/demo.gif

Set Shell "bash"
Set FontSize 16
Set Width 1400
Set Height 540
Set Padding 20
Set TypingSpeed 25ms
Set Theme "Dracula"

Hide
Type "source .venv/bin/activate && export PS1='$ ' COLUMNS=120 && clear"
Enter
Show

Type "# Parse a CAMT.053 statement: the CLI masks PII by default"
Enter
Type "bankstatementparser --type camt --input tests/test_data/camt.053.001.02.xml 2>/dev/null"
Enter
Sleep 2.5s

Type "# The same file from Python, as a DataFrame"
Enter
Type `python -c "from bankstatementparser import CamtParser; print(CamtParser('tests/test_data/camt.053.001.02.xml').parse()[['Amount', 'Currency', 'DrCr', 'ValDt']])"`
Enter
Sleep 3s

Type "# detect_statement_format + create_parser across formats"
Enter
Type "python examples/parse_detected_formats.py 2>/dev/null"
Enter
Sleep 4s
