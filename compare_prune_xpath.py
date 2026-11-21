"""Offline, controlled Trafilatura prune_xpath comparison on saved HTTP HTML.

No requests, model inference, RSS polling, database writes, or access-state changes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from lxml import etree, html
import trafilatura

from pipeline_experiment_data import atomic_write_json
from rss_scrape_scheduler import clean_full_body
from test_article_body_scraper import (
    FIELDS, base_record, html_filename, meta_values, normalized,
    publication_date, valid_url,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_RUN = ROOT / "output/article_body_scrape_test/full_20261031_01"
VERSION = "coindesk_prune_comparison_v1"
FOOTER_XPATH = '//footer[@data-module-name="footer"]'
BOTTOM_XPATH = '//*[@data-module-name="article-bottom-news"]'
TRENDING_ATTRIBUTE = "data-pragma-prune-trending"
TRENDING_XPATH = f'//*[@{TRENDING_ATTRIBUTE}="true"]'
PRUNE_XPATH = " | ".join([FOOTER_XPATH, BOTTOM_XPATH, TRENDING_XPATH])
BODY_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " document-body ")'
WRAPPER_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " article-content-wrapper ")'
LIVE_CLASS = 'contains(concat(" ", normalize-space(@class), " "), " live-news-article ")'
LIVE_BODY_XPATH = (
    f'//main//*[{LIVE_CLASS}]//article/div['
    'contains(concat(" ", normalize-space(@class), " "), " font-body-lg ") and '
    'contains(concat(" ", normalize-space(@class), " "), " text-xl ")]'
)
OPTIONS = {"include_comments": False, "include_tables": False, "favor_precision": False}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def heading_level(node: Any) -> int | None:
    return int(node.tag[1]) if isinstance(node.tag, str) and node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} else None


def plan_pruning(tree: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Mark bounded trending siblings; return exact removal plan without deleting.

    A section ends at the next equal/higher heading within the SAME parent or
    that parent's end. Ambiguous nested boundaries/non-whitespace tail text are
    retained and flagged. Existing article lists outside that section are kept.
    """
    if tree.xpath(f'//*[@{TRENDING_ATTRIBUTE}]'):
        raise ValueError("Input already uses the private experimental pruning attribute")
    targets: list[tuple[str, Any]] = []
    warnings: list[str] = []
    targets.extend(("site_footer", node) for node in tree.xpath(FOOTER_XPATH))
    targets.extend(("article_bottom_news", node) for node in tree.xpath(BOTTOM_XPATH))
    headings = tree.xpath(f'//main//*[{BODY_CLASS}]//*[self::h2 or self::h3 or self::h4 or self::h5 or self::h6]')
    for heading in headings:
        if normalized(heading.text_content()).casefold().replace("’", "'") != "what's trending":
            continue
        level = heading_level(heading)
        section = [heading]
        ambiguous = False
        for sibling in heading.itersiblings():
            if not isinstance(sibling.tag, str):
                continue
            sibling_level = heading_level(sibling)
            if sibling_level is not None and sibling_level <= level:
                break
            if any((heading_level(child) or 99) <= level for child in sibling.iterdescendants()):
                ambiguous = True
                break
            section.append(sibling)
        if ambiguous or any((node.tail or "").strip() for node in section):
            warnings.append("ambiguous_trending_section_retained_for_review")
            continue
        for node in section:
            node.set(TRENDING_ATTRIBUTE, "true")
            targets.append(("whats_trending", node))

    target_nodes = {node for _, node in targets}
    removals: list[dict[str, Any]] = []
    for rule, node in targets:
        if any(parent in target_nodes for parent in node.iterancestors()):
            continue
        removals.append({
            "rule": rule, "path": tree.getroottree().getpath(node),
            "tag": node.tag, "text": node.text_content(),
            "html": html.tostring(node, encoding="unicode", with_tail=False),
        })
    return removals, sorted(set(warnings))


def pruned_copy(tree: Any) -> Any:
    """Mirror Trafilatura's subtree deletion for retained-source auditing only."""
    copy = deepcopy(tree)
    for node in copy.xpath(PRUNE_XPATH):
        if node.getparent() is not None:
            node.drop_tree()  # Keep tail text, matching Trafilatura's behavior.
    return copy


def narrative_nodes(tree: Any) -> list[Any]:
    standard = tree.xpath(f'//main//*[{WRAPPER_CLASS}]/*[{BODY_CLASS}]')
    return [node for node in standard + tree.xpath(LIVE_BODY_XPATH) if not any(
        parent.tag in {"footer", "nav", "aside"}
        or parent.get("data-module-name") == "article-bottom-news"
        or (parent.get("id") or "").startswith("se-")
        for parent in node.iterancestors()
    )]


def source_segments(tree: Any) -> list[str]:
    segments: list[str] = []
    for root in narrative_nodes(tree):
        for node in root.xpath('.//p | .//li | .//h2 | .//h3 | .//h4 | .//h5 | .//h6'):
            if node.xpath('ancestor::table') or node.xpath('.//p | .//li'):
                continue
            value = normalized(node.text_content())
            if value:
                segments.append(value)
    return list(dict.fromkeys(segments))


def page_fields(tree: Any, article: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Read fixed metadata once, before pruning; do not reuse the old title/body."""
    record = base_record(article)
    origins = {name: "saved_rss_provenance" for name in ("source", "guid", "url", "rss_summary", "rss_fetched_at")}
    headers = tree.xpath('//main//h1[not(ancestor::*[@data-module-name="article-bottom-news"])]')
    if len(headers) == 1:
        record["title"] = normalized(headers[0].text_content())
    origins["title"] = "page:main_h1" if record["title"] else "unavailable_no_old_title_fallback"

    objects: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if isinstance(kinds, list) and set(kinds) & {"NewsArticle", "Article", "LiveBlogPosting"}:
                objects.append(value)
            if "@graph" in value:
                visit(value["@graph"])

    for node in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            visit(json.loads(node.text or ""))
        except ValueError:
            continue
    matching = [obj for obj in objects if obj.get("identifier") == article.get("guid")]
    metadata = matching[0] if len(matching) == 1 else {}
    image = metadata.get("image")
    images = meta_values(tree, "og:image") + [image.get("url") if isinstance(image, dict) else image]
    fresh_image = next((value for value in images if valid_url(value)), None)
    if fresh_image:
        record["image_url"] = fresh_image
    origins["image_url"] = "page:article_image_metadata" if fresh_image else "saved_rss_fallback"
    dates = [metadata.get("datePublished")] + meta_values(tree, "article:published_time") + meta_values(tree, "parsely-pub-date")
    fresh_date = next((value for date in dates if (value := publication_date(date))), None)
    if fresh_date:
        record["published_at"] = fresh_date
    origins["published_at"] = "page:publication_metadata" if fresh_date else "saved_rss_fallback"
    section = metadata.get("articleSection")
    values = section if isinstance(section, list) else [section]
    tags = metadata.get("keywords", [])
    tags = tags.split(",") if isinstance(tags, str) else tags
    values += (tags if isinstance(tags, list) else []) + meta_values(tree, "parsely-section")
    values += [value.strip() for raw in meta_values(tree, "parsely-tags") for value in raw.split(",")]
    categories = list(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))
    if categories:
        record["categories"] = categories
    origins["categories"] = "page:article_section_and_tags" if categories else "saved_rss_fallback"
    return record, origins


def compare_page(raw: bytes, article: dict[str, Any]) -> dict[str, Any]:
    """Only extraction difference: prune_xpath, including marked trending nodes."""
    tree = html.fromstring(raw)
    fixed_record, origins = page_fields(tree, article)
    available_nodes = narrative_nodes(tree)
    available = bool(available_nodes and fixed_record["title"])
    marked = deepcopy(tree)
    removals, warnings = plan_pruning(marked)
    # Feed identical marked DOMs to both conditions; markers themselves delete nothing.
    baseline_text = trafilatura.extract(deepcopy(marked), **OPTIONS) or ""
    # Actual experimental extraction uses the public prune_xpath argument.
    pruned_text = trafilatura.extract(deepcopy(marked), prune_xpath=PRUNE_XPATH, **OPTIONS) or ""
    before = clean_full_body(baseline_text)
    after = clean_full_body(pruned_text)
    retained = pruned_copy(marked)
    segments = source_segments(retained)
    before_normalized, after_normalized = normalized(before), normalized(after)
    checked = [text for text in segments if text in before_normalized]
    missing = [text for text in checked if text not in after_normalized]
    if missing:
        warnings.append("retained_article_segments_lost_from_extraction")
    if baseline_text != before or pruned_text != after:
        warnings.append("existing_cleanup_changed_extracted_text")

    records: dict[str, dict[str, Any]] = {}
    for name, text in [("baseline", before), ("pruned", after)]:
        record = deepcopy(fixed_record)
        success = available and bool(text.strip())
        record.update(full_body=text if success else None,
                      scrape_status="success" if success else "failed",
                      scrape_error=None if success else "No verified rendered article body/headline in saved response; nonempty navigation is not accepted")
        assert set(record) == set(FIELDS)
        records[name] = record
    protected = {}
    for label, needle in [("read_more", "Read more"), ("subscription", "Sign up here"), ("later_signal_section", "Today’s signal")]:
        protected[label] = {"in_baseline": needle in before, "in_pruned": needle in after}
    return {
        **records, "rendered_content_available": available,
        "baseline_extracted_text": baseline_text, "pruned_extracted_text": pruned_text,
        "baseline_after_existing_cleanup": before, "pruned_after_existing_cleanup": after,
        "baseline_characters": len(before), "pruned_characters": len(after),
        "text_changed": before != after, "removals": removals,
        "rules_matched": dict(Counter(item["rule"] for item in removals)),
        "metadata_origins": origins, "retained_source_segment_count": len(segments),
        "baseline_present_source_segment_count": len(checked),
        "retained_segments_missing_after_pruning": missing,
        "protected_text_checks": protected, "warnings": sorted(set(warnings)),
        "diff": "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile="baseline", tofile="pruned", lineterm="")),
    }


def run_comparison(input_run: Path, output_dir: Path) -> dict[str, Any]:
    source_bytes = (input_run / "source_snapshot.json").read_bytes()
    articles = json.loads(source_bytes)
    if not isinstance(articles, list) or not articles:
        raise ValueError("Expected saved source snapshot to be a nonempty article list")
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "source_snapshot.json").write_bytes(source_bytes)
    comparisons: list[dict[str, Any]] = []
    baseline, pruned = [], []
    for index, article in enumerate(articles, 1):
        path = input_run / "html" / html_filename(index, article["url"])
        raw = path.read_bytes()
        result = compare_page(raw, article)
        baseline.append(result.pop("baseline"))
        pruned.append(result.pop("pruned"))
        comparisons.append({"source_index": index, "dataset_article_id": article.get("dataset_article_id"),
                            "guid": article.get("guid"), "url": article["url"],
                            "saved_html": str(path.resolve()), "saved_html_sha256": sha(raw), **result})
    available = [row for row in comparisons if row["rendered_content_available"]]
    report = {
        "status": "complete", "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_run": str(input_run.resolve()), "source_sha256": sha(source_bytes),
        "script_sha256": sha(Path(__file__).read_bytes()), "trafilatura_version": trafilatura.__version__,
        "extraction_options": OPTIONS, "prune_xpath": PRUNE_XPATH,
        "articles": len(articles), "rendered_content_available": len(available),
        "unavailable_rendered_content": len(articles) - len(available),
        "changed_available_articles": sum(row["text_changed"] for row in available),
        "retained_segment_loss_articles": [row["source_index"] for row in available if row["retained_segments_missing_after_pruning"]],
        "removal_counts": dict(Counter(item["rule"] for row in comparisons for item in row["removals"])),
        "matched_article_counts": {rule: sum(rule in row["rules_matched"] for row in comparisons)
                                   for rule in ["site_footer", "article_bottom_news", "whats_trending"]},
        "warning_counts": dict(Counter(warning for row in comparisons for warning in row["warnings"])),
        "network_requests": 0, "new_models_or_database_calls": 0,
        "limitation": "Rendered availability is validated against known narrative/live-update containers; JSON-LD fallback is deliberately not added in this pruning-only experiment. Locked/header-only pages are not called successes even if Trafilatura emits text.",
    }
    atomic_write_json(output_dir / "baseline_scraped_news.json", baseline, indent=2)
    atomic_write_json(output_dir / "pruned_scraped_news.json", pruned, indent=2)
    atomic_write_json(output_dir / "comparison.json", comparisons, indent=2)
    atomic_write_json(output_dir / "report.json", report, indent=2)
    lines = ["# Offline prune_xpath comparison", "",
             f"Saved responses: **{len(articles)}**; rendered article content available: **{len(available)}**; "
             f"unavailable: **{len(articles)-len(available)}**. New requests: **0**.", "",
             "Both methods use the same HTML, Trafilatura version, comments/tables exclusions, "
             "favor_precision=False, and existing pagination/duplicate-line cleanup. "
             "Only the experimental method applies the audited pruning plan.", "",
             "Remove: site footer, article-bottom-news modules, and bounded exact What's trending "
             "sections. No new rules target Read more, subscription text, publisher summary widgets, "
             "titles, article headers, market-price chips, or other article sections.", "",
             f"Available articles with changed extracted text: **{report['changed_available_articles']}**. "
             f"Articles with baseline-present retained source segments lost: **{len(report['retained_segment_loss_articles'])}**.", "",
             "The segment audit measures verbatim retention of source segments present in the baseline, "
             "not factuality or a complete semantic quality score. Inline widgets may already differ "
             "from source text before either condition. Inspect comparison.json and full diffs.", "",
             "Failed rows remain in both scraper-shaped exports with full_body=null. Their raw extraction "
             "text remains in comparison.json for diagnosis and is not relabeled as article content. "
             "The 43 regular locked responses plus one locked live blog have no supported rendered body; "
             "this test does not retrieve withheld text or add structured-data fallback.", "",
             "| Source # | Article | Rendered body | Before chars | After chars | Loss flags |",
             "|---:|---|---|---:|---:|---:|"]
    for row, record in zip(comparisons, pruned):
        label = (record["title"] or "No rendered headline").replace("|", "\\|")
        lines.append(f"| {row['source_index']} | {label} | {'yes' if row['rendered_content_available'] else 'no'} | "
                     f"{row['baseline_characters']} | {row['pruned_characters']} | {len(row['retained_segments_missing_after_pruning'])} |")
    lines += ["", "Outputs: baseline_scraped_news.json, pruned_scraped_news.json (same 13 fields), "
              "comparison.json (full text, exact removals, diffs, checks and provenance), report.json, "
              "and the byte-identical source_snapshot.json. No prior files were overwritten.", ""]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir.resolve()), **report}, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d_%H%M%S_%f")
    output = args.output_dir or ROOT / "output/article_body_scrape_test" / f"prune_xpath_{stamp}"
    run_comparison(args.input_run, output)


if __name__ == "__main__":
    main()
