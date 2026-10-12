# SecurePDF Frontend (GUI)

This directory is designated for the future GUI application.

## Architectural Boundary

The frontend client will operate independently of the core library and database:
1. **API Communication**: The GUI communicates with the SecurePDF backend strictly over HTTP via the FastAPI endpoints (`/documents/`, `/students/`, `/verify/`).
2. **Decoupled Architecture**: The frontend does not directly import internal cryptographic (`app.crypto`), PDF (`app.pdf`), or database (`app.database`) modules.
3. **Authentication & Roles**: Future user sessions (Teacher/Administrator) will be enforced at the API boundary.

*Note: Frontend implementation is scheduled for a future milestone.*
