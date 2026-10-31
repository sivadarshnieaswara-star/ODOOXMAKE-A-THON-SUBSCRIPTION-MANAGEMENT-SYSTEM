"""Start the Brightloop server: python run.py (or uv run run.py)."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")),
                reload=os.getenv("RELOAD", "0") == "1")
