"""Static PyInstaller entry for the standalone Site Agent."""

from mklink.remote.package_agent import main


if __name__ == "__main__":
    raise SystemExit(main())
