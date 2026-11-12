"""Production server mounting backend API and built frontend static assets."""
import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from backend.app.main import create_app

def get_prod_app(dist_path=None):
    app = create_app()

    # Determine frontend dist directory
    if dist_path is None:
        for candidate in [
            Path(__file__).resolve().parent.parent / "frontend" / "dist",
            Path("/app/frontend/dist"),
            Path("frontend/dist"),
        ]:
            if candidate.is_dir() and (candidate / "index.html").is_file():
                dist_path = candidate
                break

    api_only = os.getenv("API_ONLY", "").lower() in ("1", "true", "yes")

    if not dist_path or not Path(dist_path).is_dir():
        if not api_only:
            raise RuntimeError(
                "Production frontend bundle not found at frontend/dist. "
                "Build the frontend with 'npm --prefix frontend run build' "
                "or set API_ONLY=1 to start in API-only mode."
            )
        return app

    resolved_dist = Path(dist_path).resolve()
    index_file = resolved_dist / "index.html"
    if not index_file.is_file():
        raise RuntimeError(f"index.html missing from static bundle at {resolved_dist}")

    # Ensure any unmatched /api route returns 404 JSON, NOT static files
    @app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def api_catchall(full_path: str):
        return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})

    # Mount standard StaticFiles at root: handles index.html, static assets, and returns 404 on missing/traversal
    app.mount("/", StaticFiles(directory=str(resolved_dist), html=True), name="static")
    return app

if __name__ == "__main__":
    import uvicorn
    prod_app = get_prod_app()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(prod_app, host=host, port=port, workers=1)
