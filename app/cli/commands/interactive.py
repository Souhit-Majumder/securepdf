from app.cli.commands.register import register_document_cmd, register_student_cmd
from app.cli.commands.distribute import distribute_cmd
from app.cli.commands.verify import verify_cmd

def print_banner():
    print("\n╔══════════════════════════════╗")
    print("║         SecurePDF            ║")
    print("╚══════════════════════════════╝\n")

def interactive_mode():
    """Runs the interactive console menu for SecurePDF."""
    while True:
        print_banner()
        print("1. Register Document")
        print("2. Register Student")
        print("3. Generate Student Copy")
        print("4. Verify PDF")
        print("5. Exit\n")
        
        try:
            choice = input("Select option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break
        
        if choice == "1":
            path = input("Path to original PDF: ").strip()
            register_document_cmd(path)
            
        elif choice == "2":
            name = input("Student Name: ").strip()
            uid = input("Student UID (e.g. roll number): ").strip()
            register_student_cmd(uid, name)
            
        elif choice == "3":
            doc_uid = input("Document UID: ").strip()
            stu_uid = input("Student UID: ").strip()
            distribute_cmd(doc_uid, stu_uid)
                
        elif choice == "4":
            path = input("Path to PDF to verify: ").strip()
            verify_cmd(path)
            
        elif choice == "5":
            print("Exiting...")
            break
        else:
            print("Invalid choice.")
