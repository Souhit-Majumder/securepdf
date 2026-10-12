import sys
import argparse
from app.database.database import init_db
from app.cli.commands.verify import verify_cmd
from app.cli.commands.demo import demo_cmd
from app.cli.commands.register import register_document_cmd, register_student_cmd
from app.cli.commands.distribute import distribute_cmd
from app.cli.commands.interactive import interactive_mode

def main(args=None):
    """Entry point for the SecurePDF CLI."""
    init_db()
    
    parser = argparse.ArgumentParser(
        prog="securepdf-cli",
        description="SecurePDF Cryptographic Document Fingerprinting and Attribution CLI"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # verify
    verify_parser = subparsers.add_parser("verify", help="Verify a PDF and identify recipient")
    verify_parser.add_argument("pdf_path", help="Path to the PDF file to inspect")

    # demo
    demo_parser = subparsers.add_parser("demo", help="Run automated multi-student demo workflow")
    demo_parser.add_argument("--output-dir", default=None, help="Directory to save generated copies")

    # register-document
    reg_doc_parser = subparsers.add_parser("register-document", help="Register an original PDF")
    reg_doc_parser.add_argument("pdf_path", help="Path to the original PDF")
    reg_doc_parser.add_argument("--title", default=None, help="Document title/description")
    reg_doc_parser.add_argument("--uid", default=None, help="Custom document UID")

    # register-student
    reg_stu_parser = subparsers.add_parser("register-student", help="Register a student recipient")
    reg_stu_parser.add_argument("uid", help="Student unique ID (e.g. roll number)")
    reg_stu_parser.add_argument("name", help="Student full name")

    # distribute
    dist_parser = subparsers.add_parser("distribute", help="Generate a fingerprinted PDF for a student")
    dist_parser.add_argument("doc_uid", help="Document UID or path")
    dist_parser.add_argument("student_uid", help="Student UID")
    dist_parser.add_argument("--output", default=None, help="Output PDF file path")

    parsed = parser.parse_args(args)

    if not parsed.subcommand:
        interactive_mode()
        return 0

    if parsed.subcommand == "verify":
        res = verify_cmd(parsed.pdf_path)
        return 0 if res.get("status") == "VALID" else 1
    elif parsed.subcommand == "demo":
        demo_cmd(parsed.output_dir)
        return 0
    elif parsed.subcommand == "register-document":
        doc = register_document_cmd(parsed.pdf_path, title=parsed.title, doc_uid=parsed.uid)
        return 0 if doc else 1
    elif parsed.subcommand == "register-student":
        stu = register_student_cmd(parsed.uid, parsed.name)
        return 0 if stu else 1
    elif parsed.subcommand == "distribute":
        out = distribute_cmd(parsed.doc_uid, parsed.student_uid, output_path=parsed.output)
        return 0 if out else 1

if __name__ == "__main__":
    sys.exit(main())
