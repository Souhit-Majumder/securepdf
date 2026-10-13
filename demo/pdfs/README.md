# Demo Input PDFs Directory

Place original, unmodified source PDFs into this folder for the demonstration.

## Features
- **Automatic Discovery**: Any `.pdf` placed here is automatically scanned, validated, and hashed.
- **Source Preservation**: Input PDFs are opened strictly read-only and **never** modified in place.
- **Validation**: Ensures valid `%PDF` headers, parsable page structures, and non-empty sizes. Any malformed or corrupt file will be flagged with a detailed error while allowing valid files to proceed.

## Default Sample Files
1. `cs101_syllabus.pdf` — Computer Systems 101 course syllabus and policy.
2. `crypto_lecture.pdf` — Cryptographic protocols lecture notes.
