import argparse

import uvicorn

from futurework.app import create_app
from futurework.config import load_config
from futurework.home import ensure_home


def main():
    parser = argparse.ArgumentParser(prog="futurework", description="FutureWork Agent Team")
    parser.add_argument("--home", help="配置和数据目录；默认 ~/.futurework")
    parser.add_argument("command", nargs="?", choices=("init", "serve", "paths"), default="serve")
    args = parser.parse_args()
    home = ensure_home(args.home)
    if args.command in {"init", "paths"}:
        print(home)
        return
    config = load_config(home=home)
    server = config["server"]
    uvicorn.run(create_app(home=home), host=server["host"], port=server["port"])
