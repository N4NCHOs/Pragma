"""Reset generated JSON data before a test run."""

from pathlib import Path


def main():
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(exist_ok=True)
    for name in ("rss_temp.json", "rss_history.json", "scraped_news.json"):
        (output_dir / name).write_text("[]\n", encoding="utf-8")
        print(f"Reset output/{name}")


if __name__ == "__main__":
    main()
