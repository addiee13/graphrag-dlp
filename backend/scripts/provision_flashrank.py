"""Explicit online provisioning; runtime only accepts the frozen, hashed directory."""
import argparse
import hashlib
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True)
    args = parser.parse_args()
    from flashrank import Ranker
    model_name = "ms-marco-TinyBERT-L-2-v2"
    ranker = Ranker(model_name=model_name, cache_dir=args.cache_dir, max_length=256)
    directory = Path(args.cache_dir) / model_name
    files = {str(file.relative_to(directory)): hashlib.sha256(file.read_bytes()).hexdigest() for file in directory.rglob("*") if file.is_file() and file.name != "frozen-manifest.json"}
    (directory / "frozen-manifest.json").write_text(json.dumps({"model": model_name, "files": files}, indent=2) + "\n")
    print(f"Frozen {model_name}: {len(files)} hashed files in {directory}")

if __name__ == "__main__": main()
