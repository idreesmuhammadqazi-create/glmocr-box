import re


def check_structural(md: str) -> list[str]:
    findings = []
    in_fence = False
    for ln_no, line in enumerate(md.split("\n"), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        if "\\$" in line:
            findings.append(f"line {ln_no}: literal escape '\\\\$' present")

        if re.search(r"<table\b", line, re.IGNORECASE):
            findings.append(f"line {ln_no}: raw HTML table present")

        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            inner = line.strip()[1:-1]
            for cell in re.split(r"(?<!\\)\|", inner):
                if cell.count("$") % 2 == 1:
                    findings.append(f"line {ln_no}: table cell has unbalanced '$': {cell.strip()[:80]}")
    return findings
