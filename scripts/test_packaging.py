"""Packaging, same-origin, and static path traversal security validation."""
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from starlette.testclient import TestClient
from scripts.prod_server import get_prod_app

def test_static_path_traversal_and_same_origin():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        dist_dir = tmp_path / "frontend" / "dist"
        dist_dir.mkdir(parents=True)
        (dist_dir / "index.html").write_text("<!DOCTYPE html><html><body>GraphRAG Portal</body></html>")
        
        assets_dir = dist_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "bundle.js").write_text("console.log('bundle');")

        # Create sensitive files outside dist_dir to verify traversal denial
        secret_file = tmp_path / "sensitive.key"
        secret_file.write_text("SENSITIVE_SECRET_TOKEN_DO_NOT_LEAK")
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET_KEY=leaked_secret")

        # Initialize prod app pointing to temporary dist
        app = get_prod_app(dist_path=dist_dir)
        client = TestClient(app)

        # 1. Root serves index.html (200 OK)
        root_resp = client.get("/")
        assert root_resp.status_code == 200
        assert "GraphRAG Portal" in root_resp.text

        # 2. Unknown API route returns 404 JSON, NOT static HTML
        unknown_api = client.get("/api/v1/non_existent_endpoint")
        assert unknown_api.status_code == 404
        assert unknown_api.headers["content-type"].startswith("application/json")
        assert unknown_api.json() == {"detail": "API endpoint not found"}
        assert "GraphRAG Portal" not in unknown_api.text

        # 3. Known API route returns 200 JSON
        health_resp = client.get("/api/v1/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "healthy"

        # 4. Legitimate static asset served (200 OK)
        asset_resp = client.get("/assets/bundle.js")
        assert asset_resp.status_code == 200
        assert "console.log('bundle');" in asset_resp.text

        # 5. Missing static file returns 404 Not Found
        missing_resp = client.get("/non_existent_file.txt")
        assert missing_resp.status_code == 404

        # 6. Path traversal attacks must return 404 and NEVER leak file contents
        traversal_attempts = [
            "/../sensitive.key",
            "/../../sensitive.key",
            "/..%2fsensitive.key",
            "/%2e%2e/sensitive.key",
            "/%2e%2e%2fsensitive.key",
            "/..%5csensitive.key",
            "/../.env",
            "/../../.env",
            "/..%2f.env",
        ]
        for attack_path in traversal_attempts:
            resp = client.get(attack_path)
            assert resp.status_code in (400, 404), f"Path {attack_path} returned {resp.status_code}"
            assert "SENSITIVE_SECRET_TOKEN_DO_NOT_LEAK" not in resp.text
            assert "leaked_secret" not in resp.text

def test_missing_dist_fails_actionable_unless_api_only():
    with tempfile.TemporaryDirectory() as empty_dir:
        non_existent = Path(empty_dir) / "non_existent_dist"
        
        # Unset API_ONLY: must raise RuntimeError
        os.environ.pop("API_ONLY", None)
        with pytest.raises(RuntimeError, match="Production frontend bundle not found"):
            get_prod_app(dist_path=non_existent)

        # Set API_ONLY=1: starts successfully in API-only mode
        os.environ["API_ONLY"] = "1"
        try:
            app = get_prod_app(dist_path=non_existent)
            client = TestClient(app)
            assert client.get("/api/v1/health").status_code == 200
        finally:
            os.environ.pop("API_ONLY", None)

if __name__ == "__main__":
    test_static_path_traversal_and_same_origin()
    test_missing_dist_fails_actionable_unless_api_only()
    print("All packaging, traversal 404, unknown api 404, and root 200 tests passed successfully!")
