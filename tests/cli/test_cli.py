import pytest
import os
import fitz
from app.cli.main import main
from app.cli.commands.register import register_document_cmd, register_student_cmd
from app.cli.commands.distribute import distribute_cmd
from app.cli.commands.verify import verify_cmd
from app.cli.commands.demo import demo_cmd

@pytest.fixture
def sample_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "CLI Test Document")
    path = str(tmp_path / "sample.pdf")
    doc.save(path)
    doc.close()
    return path

def test_cli_register_and_distribute(sample_pdf, tmp_path):
    # 1. Register document
    doc = register_document_cmd(sample_pdf, title="Lecture 1", doc_uid="CLI-DOC-1")
    assert doc is not None
    assert doc.document_uid == "CLI-DOC-1"

    # 2. Register student
    student = register_student_cmd("CLI-STU-1", "Dave")
    assert student is not None
    assert student.student_uid == "CLI-STU-1"

    # 3. Distribute
    out_file = str(tmp_path / "dave_copy.pdf")
    generated = distribute_cmd("CLI-DOC-1", "CLI-STU-1", output_path=out_file)
    assert generated == out_file
    assert os.path.exists(out_file)

    # 4. Verify
    res = verify_cmd(out_file)
    assert res["status"] == "VALID"
    assert res["student_name"] == "Dave"
    assert res["student_uid"] == "CLI-STU-1"
    assert res["document_uid"] == "CLI-DOC-1"

def test_cli_demo_command(tmp_path):
    demo_out_dir = str(tmp_path / "demo_out")
    generated_files = demo_cmd(output_dir=demo_out_dir)
    assert len(generated_files) == 3
    for f in generated_files:
        assert os.path.exists(f)
        
    # Verify the second student (Bob)
    res_bob = verify_cmd(generated_files[1])
    assert res_bob["status"] == "VALID"
    assert res_bob["student_name"] == "Bob"

def test_cli_verify_unmarked_pdf(sample_pdf):
    res = verify_cmd(sample_pdf)
    assert res["status"] == "NOT_FOUND"

def test_cli_main_dispatch(sample_pdf, tmp_path):
    # Test main() with argument list
    ret_doc = main(["register-document", sample_pdf, "--uid", "MAIN-DOC-1", "--title", "Main Doc"])
    assert ret_doc == 0

    ret_stu = main(["register-student", "MAIN-STU-1", "Eve"])
    assert ret_stu == 0

    out_file = str(tmp_path / "eve_copy.pdf")
    ret_dist = main(["distribute", "MAIN-DOC-1", "MAIN-STU-1", "--output", out_file])
    assert ret_dist == 0

    ret_ver = main(["verify", out_file])
    assert ret_ver == 0
