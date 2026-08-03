"""
Extract recipe data from regular recipe web pages.

This intentionally stays conservative: it reads schema.org Recipe JSON-LD when
the site provides it, and otherwise returns a saved-link idea without trying to
guess from arbitrary page text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import argparse
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class RecipeSiteExtraction:
    url: str
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    title: str | None = None
    channel: str | None = None
    description: str = ""
    source_links: list[str] = field(default_factory=list)
    extraction_sources: list[str] = field(default_factory=list)
    recipe_status: str = "idea_saved"
    confidence: str = "low"
    recipe_title: str | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    video_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "captured_at": self.captured_at,
            "title": self.title,
            "channel": self.channel,
            "recipe_title": self.recipe_title,
            "recipe_status": self.recipe_status,
            "confidence": self.confidence,
            "extraction_sources": self.extraction_sources,
            "ingredients": self.ingredients,
            "instructions": self.instructions,
            "tags": self.tags,
            "description_preview": self.description[:1000],
            "source_links": self.source_links,
            "warnings": self.warnings,
        }


class _JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_json_ld = False
        self.json_ld_blocks: list[str] = []
        self._current: list[str] = []
        self.title: str | None = None
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "script" and "ld+json" in attrs_dict.get("type", "").lower():
            self.in_json_ld = True
            self._current = []
        elif tag.lower() == "title":
            self._in_title = True
            self._title_parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.in_json_ld:
            self.json_ld_blocks.append("".join(self._current).strip())
            self.in_json_ld = False
            self._current = []
        elif tag.lower() == "title" and self._in_title:
            self.title = unescape("".join(self._title_parts)).strip() or None
            self._in_title = False

    def handle_data(self, data):
        if self.in_json_ld:
            self._current.append(data)
        elif self._in_title:
            self._title_parts.append(data)


def extract_recipe_site(url: str, recipe_title: str | None = None) -> RecipeSiteExtraction:
    """Fetch a web page and extract schema.org Recipe JSON-LD if available."""
    clean_url = url.strip()
    if not _is_http_url(clean_url):
        raise ValueError("Recipe site extraction requires an http or https URL.")

    result = RecipeSiteExtraction(url=clean_url, recipe_title=recipe_title, source_links=[clean_url])
    try:
        html = _http_get(clean_url)
    except Exception as exc:
        result.warnings.append(f"Recipe page fetch failed: {exc}")
        _classify(result)
        return result

    parser = _JsonLdParser()
    parser.feed(html)
    result.title = parser.title
    recipes = []
    for block in parser.json_ld_blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            cleaned = _strip_jsonld_html_comments(block)
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                continue
        recipes.extend(_find_recipe_nodes(data))

    if not recipes:
        result.warnings.append("No schema.org Recipe data found on the page.")
        _classify(result)
        return result

    recipe = recipes[0]
    result.extraction_sources.append("schema_org_recipe")
    result.recipe_title = recipe_title or _as_text(recipe.get("name")) or result.title
    result.title = result.title or result.recipe_title
    result.description = _as_text(recipe.get("description"))
    result.channel = _extract_author(recipe.get("author")) or _site_name(clean_url)
    result.ingredients = _as_text_list(recipe.get("recipeIngredient"))
    result.instructions = _extract_instructions(recipe.get("recipeInstructions"))
    result.tags = _extract_tags(recipe)
    _classify(result)
    return result


def _http_get(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _strip_jsonld_html_comments(text: str) -> str:
    return re.sub(r"^\s*<!--|-->\s*$", "", text.strip())


def _find_recipe_nodes(data: Any) -> list[dict]:
    found = []
    if isinstance(data, list):
        for item in data:
            found.extend(_find_recipe_nodes(item))
    elif isinstance(data, dict):
        if _is_recipe_type(data.get("@type")):
            found.append(data)
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            if key in data:
                found.extend(_find_recipe_nodes(data[key]))
    return found


def _is_recipe_type(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() == "recipe"
    if isinstance(value, list):
        return any(_is_recipe_type(item) for item in value)
    return False


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return unescape(re.sub(r"\s+", " ", value)).strip()
    if isinstance(value, dict):
        return _as_text(value.get("text") or value.get("name") or value.get("@id"))
    if isinstance(value, list):
        return " ".join(part for part in (_as_text(item) for item in value) if part)
    return str(value).strip()


def _as_text_list(value: Any) -> list[str]:
    if not value:
        return []
    values = value if isinstance(value, list) else [value]
    return _dedupe([text for text in (_as_text(item) for item in values) if text])


def _extract_author(value: Any) -> str:
    if isinstance(value, list) and value:
        return _extract_author(value[0])
    if isinstance(value, dict):
        return _as_text(value.get("name"))
    return _as_text(value)


def _extract_instructions(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return _split_instruction_text(value)
    if isinstance(value, list):
        instructions = []
        for item in value:
            instructions.extend(_extract_instructions(item))
        return _dedupe(instructions)
    if isinstance(value, dict):
        item_type = value.get("@type")
        if _type_contains(item_type, "HowToSection"):
            return _extract_instructions(value.get("itemListElement"))
        if _type_contains(item_type, "HowToStep"):
            text = _as_text(value.get("text") or value.get("name"))
            return [text] if text else []
        return _extract_instructions(value.get("itemListElement") or value.get("text"))
    return []


def _type_contains(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value.lower() == expected.lower()
    if isinstance(value, list):
        return any(_type_contains(item, expected) for item in value)
    return False


def _split_instruction_text(text: str) -> list[str]:
    cleaned = _as_text(text)
    if not cleaned:
        return []
    parts = re.split(r"(?:(?:^|\s)\d+[.)]\s+)|(?:\s{2,})", cleaned)
    return _dedupe([part.strip() for part in parts if len(part.strip()) > 3])


def _extract_tags(recipe: dict) -> list[str]:
    raw_values = []
    for key in ("keywords", "recipeCategory", "recipeCuisine"):
        value = recipe.get(key)
        if isinstance(value, str):
            raw_values.extend(part.strip() for part in re.split(r"[,;]", value))
        elif isinstance(value, list):
            raw_values.extend(_as_text(item) for item in value)
    return _dedupe([value.lower() for value in raw_values if value])


def _classify(result: RecipeSiteExtraction) -> None:
    if result.ingredients and result.instructions:
        result.recipe_status = "complete_recipe"
        result.confidence = "high"
    elif result.ingredients or result.instructions:
        result.recipe_status = "partial_recipe"
        result.confidence = "medium"
    elif result.extraction_sources:
        result.recipe_status = "partial_recipe"
        result.confidence = "low"
    else:
        result.recipe_status = "idea_saved"
        result.confidence = "low"


def _site_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract schema.org Recipe data from a web page.")
    parser.add_argument("url", help="Recipe page URL")
    parser.add_argument("--title", help="Canonical recipe title supplied by the user")
    args = parser.parse_args()
    extraction = extract_recipe_site(args.url, recipe_title=args.title)
    print(json.dumps(extraction.as_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
