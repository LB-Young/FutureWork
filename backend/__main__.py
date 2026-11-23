import uvicorn

from backend.config import load_config


def main():
    server = load_config()["server"]
    uvicorn.run("backend.app:create_app", factory=True, host=server["host"], port=server["port"])


if __name__ == "__main__":
    main()
