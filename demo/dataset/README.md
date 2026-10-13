# Demo Forensic ML Dataset Directory

This directory stores all ML forensic datasets and manifests generated exclusively for the demonstration.

## Structure
- `manifests/`: Dataset JSON and CSV manifests recording provenance, splits, and feature vectors.
- `variants/`: Generated fingerprinted baseline documents and controlled transformation variants.

## Safety and Isolation Invariants
- **Source-Grouped Splits**: All variants originating from a single source document are assigned to the same split (train or test). No source variants cross splits.
- **Genuine Baselines**: Every labeled tampering example begins from a cryptographically verified, SecurePDF-personalized baseline.
- **Isolated Storage**: Ephemeral keys and temporary demo database instances prevent any modification of the production key or database.
