# Infra Folder

Use this folder for project code that should remain stable across experiment designs.

Typical contents:
- dataset/data access utilities
- metrics and evaluation helpers
- logging/checkpoint helpers
- shared constants and reusable utilities

Contract:
- Treat files here as shared infrastructure.
- Change only when the user ask you to and double check with the user.
