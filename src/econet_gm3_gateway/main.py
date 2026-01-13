"""Main application entry point."""

from fastapi import FastAPI

from econet_gm3_gateway import __version__

app = FastAPI(
    title="econet GM3 Gateway",
    description="Local REST API gateway for GM3 protocol heat pump controllers",
    version=__version__,
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "econet GM3 Gateway",
        "version": __version__,
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


def main():
    """Run the application (for CLI entry point)."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
