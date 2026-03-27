"""Application entry point for the Agent Platform API server.

See docs/architecture/02-foundation.md Section 7.1.
"""

import uvicorn


def main() -> None:
    """Run the API server."""
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":
    main()
