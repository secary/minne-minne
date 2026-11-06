"""Local schema export and candidate checks; never publishes or changes pages."""

import argparse
import json
from pathlib import Path, PurePosixPath
from uuid import UUID

from pydantic import TypeAdapter

from backend.app.domain.markdown import parse_document
from backend.app.domain.validation import ValidationIssue, validate_documents
from backend.app.domain.wiki import EvidenceRecord, WikiPage


def main() -> int:
    parser = argparse.ArgumentParser(description="Wiki schema tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("export-schema", help="print frontmatter JSON Schema")
    check = commands.add_parser("check", help="validate a Wiki directory or page")
    check.add_argument("path", type=Path)
    check.add_argument(
        "--publish", action="store_true", help="apply publication checks"
    )
    check.add_argument("--evidence-catalog", type=Path)
    args = parser.parse_args()
    if args.command == "export-schema":
        print(json.dumps(WikiPage.model_json_schema(), ensure_ascii=False, indent=2))
        return 0

    documents, issues = [], []
    try:
        catalog = None
        if args.evidence_catalog:
            catalog = TypeAdapter(dict[UUID, EvidenceRecord]).validate_json(
                args.evidence_catalog.read_text(encoding="utf-8")
            )
        if args.path.is_dir():
            root = args.path
            paths = sorted(root.rglob("*.md"))
        elif args.path.is_file():
            # A standalone page still lives in its type directory, e.g. ships/x.md.
            root = args.path.parent.parent
            paths = [args.path]
        else:
            raise ValueError(f"Wiki path does not exist: {args.path}")
        for path in paths:
            try:
                documents.append(
                    parse_document(
                        path.read_text(encoding="utf-8"),
                        path=PurePosixPath(path.relative_to(root).as_posix()),
                    )
                )
            except (OSError, ValueError) as exc:
                issues.append(ValidationIssue("invalid_document", f"{path}: {exc}"))
        issues.extend(
            validate_documents(
                documents, evidence_catalog=catalog, for_publication=args.publish
            )
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    for issue in issues:
        print(
            f"{issue.severity.upper()} {issue.page_id or '-'} {issue.code}: {issue.message}"
        )
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = len(issues) - errors
    print(
        f"Checked {len(documents)} page(s): {errors} error(s), {warnings} warning(s)."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
