"""
Compat shim: legacy capture_ingest CLI moved under app._legacy.capture.
"""

from app._legacy.capture.capture_ingest import main  # noqa: F401

if __name__ == "__main__":
    main()
