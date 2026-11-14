"""Download the person-detector weights into server/models/. Safe to run again.

    cd server && uv run python -m app.vision.fetch_models
"""

from app.vision.detector import fetch_default_model


def main() -> None:
    path = fetch_default_model()
    print(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
