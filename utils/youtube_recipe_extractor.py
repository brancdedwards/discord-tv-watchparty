"""
Extract recipe-like context from YouTube URLs.

The extractor treats the creator-provided description as the primary source and
captions/transcripts as secondary context. A YouTube Data API key is optional:
without one, the extractor falls back to the public watch page metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
import argparse
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class YouTubeRecipeExtraction:
    video_id: str
    url: str
    title: str | None = None
    channel: str | None = None
    description: str = ""
    transcript: str = ""
    comments: list[str] = field(default_factory=list)
    extraction_sources: list[str] = field(default_factory=list)
    recipe_status: str = "video_only"
    confidence: str = "low"
    recipe_title: str | None = None
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "url": self.url,
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
            "transcript_preview": self.transcript[:1000],
            "comments": self.comments,
            "warnings": self.warnings,
        }


def extract_video_id(url_or_id: str) -> str:
    """Return a YouTube video id from common YouTube URL formats."""
    value = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if "youtu.be" in host and path:
        return path.split("/")[0]

    if "youtube.com" in host:
        query_id = parse_qs(parsed.query).get("v")
        if query_id:
            return query_id[0]
        if path.startswith("shorts/"):
            return path.split("/")[1]
        if path.startswith("embed/"):
            return path.split("/")[1]

    raise ValueError(f"Could not find a YouTube video id in: {url_or_id}")


def extract_youtube_recipe(
    url_or_id: str,
    recipe_title: str | None = None,
    api_key: str | None = None,
    include_comments: bool = False,
) -> YouTubeRecipeExtraction:
    """Fetch YouTube metadata and classify whether it contains recipe details."""
    video_id = extract_video_id(url_or_id)
    url = f"https://www.youtube.com/watch?v={video_id}"
    result = YouTubeRecipeExtraction(video_id=video_id, url=url, recipe_title=recipe_title)

    api_key = api_key or os.getenv("YOUTUBE_API_KEY")
    player_response: dict[str, Any] = {}

    if api_key:
        try:
            snippet = _fetch_video_snippet(video_id, api_key)
            result.title = snippet.get("title")
            result.channel = snippet.get("channelTitle")
            result.description = snippet.get("description") or ""
            result.extraction_sources.append("youtube_api_description")
        except Exception as exc:
            result.warnings.append(f"YouTube Data API metadata failed: {exc}")

    try:
        watch_html = _http_get(url)
        player_response = _parse_player_response(watch_html)
        details = player_response.get("videoDetails", {})
        result.title = result.title or details.get("title")
        result.channel = result.channel or details.get("author")
        if not result.description:
            result.description = details.get("shortDescription") or ""
            if result.description:
                result.extraction_sources.append("watch_page_description")
    except Exception as exc:
        result.warnings.append(f"Watch page metadata failed: {exc}")

    if player_response:
        transcript = _fetch_transcript_from_player_response(player_response)
        if transcript:
            result.transcript = transcript
            result.extraction_sources.append("caption_transcript")

    if api_key and include_comments:
        try:
            result.comments = _fetch_top_comments(video_id, api_key)
            if result.comments:
                result.extraction_sources.append("youtube_api_comments")
        except Exception as exc:
            result.warnings.append(f"YouTube comments failed: {exc}")

    _classify_recipe(result)
    return result


def _fetch_video_snippet(video_id: str, api_key: str) -> dict[str, Any]:
    params = urlencode({"part": "snippet", "id": video_id, "key": api_key})
    data = json.loads(_http_get(f"https://www.googleapis.com/youtube/v3/videos?{params}"))
    items = data.get("items") or []
    if not items:
        raise ValueError("No video returned by YouTube Data API")
    return items[0].get("snippet") or {}


def _fetch_top_comments(video_id: str, api_key: str, max_results: int = 10) -> list[str]:
    params = urlencode(
        {
            "part": "snippet",
            "videoId": video_id,
            "key": api_key,
            "order": "relevance",
            "textFormat": "plainText",
            "maxResults": max_results,
        }
    )
    data = json.loads(_http_get(f"https://www.googleapis.com/youtube/v3/commentThreads?{params}"))
    comments = []
    for item in data.get("items") or []:
        top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        text = (top.get("textDisplay") or "").strip()
        if text:
            comments.append(text)
    return comments


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


def _parse_player_response(html: str) -> dict[str, Any]:
    patterns = [
        r"ytInitialPlayerResponse\s*=\s*(\{.+?\});",
        r"ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*</script>",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise ValueError("ytInitialPlayerResponse not found")


def _fetch_transcript_from_player_response(player_response: dict[str, Any]) -> str:
    tracks = (
        player_response.get("captions", {})
        .get("playerCaptionsTracklistRenderer", {})
        .get("captionTracks")
        or []
    )
    if not tracks:
        return ""

    manual_tracks = [track for track in tracks if track.get("kind") != "asr"]
    track = (manual_tracks or tracks)[0]
    base_url = track.get("baseUrl")
    if not base_url:
        return ""

    separator = "&" if "?" in base_url else "?"
    caption_xml = _http_get(f"{base_url}{separator}fmt=srv3")
    return _parse_caption_xml(caption_xml)


def _parse_caption_xml(caption_xml: str) -> str:
    try:
        root = ElementTree.fromstring(caption_xml)
    except ElementTree.ParseError:
        return ""

    lines = []
    for elem in root.iter():
        if elem.tag.endswith("text") and elem.text:
            text = unescape(unquote(elem.text)).strip()
            if text:
                lines.append(text)
    return " ".join(lines)


def _classify_recipe(result: YouTubeRecipeExtraction) -> None:
    source_text = "\n".join(
        part for part in [result.description, "\n".join(result.comments), result.transcript] if part
    )
    normalized = _normalize_text(source_text)
    description_lower = result.description.lower()

    result.ingredients = _extract_ingredients(result.description)
    result.instructions = _extract_instructions(result.description)
    result.tags = _detect_tags(normalized)

    has_recipe_words = any(
        word in normalized
        for word in [
            "ingredient",
            "recipe",
            "instructions",
            "directions",
            "tablespoon",
            "teaspoon",
            "cup ",
            "preheat",
        ]
    )
    has_ingredient_section = "ingredient" in description_lower
    has_instruction_section = any(word in description_lower for word in ["instruction", "direction", "method"])

    if result.ingredients and result.instructions:
        result.recipe_status = "complete_recipe"
        result.confidence = "high" if has_ingredient_section and has_instruction_section else "medium"
    elif result.ingredients or has_recipe_words:
        result.recipe_status = "partial_recipe"
        result.confidence = "medium" if result.ingredients else "low"
    elif result.transcript:
        result.recipe_status = "video_only"
        result.confidence = "low"
    else:
        result.recipe_status = "inspiration_only"
        result.confidence = "low"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _extract_ingredients(description: str) -> list[str]:
    lines = _clean_lines(description)
    section = _section_after_heading(lines, ("ingredients", "ingredient list"))
    candidates = section or lines

    ingredient_lines = []
    amount_pattern = re.compile(
        r"(^|\s)(\d+([./]\d+)?|\d+\s*/\s*\d+|[¼½¾⅓⅔⅛⅜⅝⅞])\s*"
        r"(cup|cups|tbsp|tablespoon|tablespoons|tsp|teaspoon|teaspoons|oz|ounce|ounces|"
        r"lb|lbs|pound|pounds|g|gram|grams|kg|ml|l|clove|cloves|can|cans|stick|sticks)\b",
        re.IGNORECASE,
    )
    bullet_pattern = re.compile(r"^[-*•]\s+")

    for line in candidates:
        if _is_non_recipe_line(line):
            continue
        if _looks_like_new_section(line) and ingredient_lines:
            break
        cleaned = bullet_pattern.sub("", line).strip()
        if _looks_like_instruction(cleaned):
            continue
        if amount_pattern.search(cleaned) or (section and 3 <= len(cleaned.split()) <= 14):
            ingredient_lines.append(cleaned)
        if len(ingredient_lines) >= 30:
            break

    return _dedupe_preserve_order(ingredient_lines)


def _extract_instructions(description: str) -> list[str]:
    lines = _clean_lines(description)
    section = _section_after_heading(lines, ("instructions", "directions", "method", "steps"))
    candidates = section or lines
    instructions = []

    for line in candidates:
        if _is_non_recipe_line(line):
            continue
        if _looks_like_new_section(line) and instructions:
            break
        cleaned = re.sub(r"^(\d+[.)]|[-*•])\s*", "", line).strip()
        if len(cleaned.split()) >= 4 and (_looks_like_instruction(cleaned) or section):
            instructions.append(cleaned)
        if len(instructions) >= 20:
            break

    return _dedupe_preserve_order(instructions)


def _clean_lines(text: str) -> list[str]:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in cleaned.split("\n") if line.strip()]


def _section_after_heading(lines: list[str], headings: tuple[str, ...]) -> list[str]:
    for index, line in enumerate(lines):
        normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
        if any(heading in normalized for heading in headings):
            return lines[index + 1 :]
    return []


def _looks_like_new_section(line: str) -> bool:
    normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
    return normalized in {
        "instructions",
        "directions",
        "method",
        "steps",
        "ingredients",
        "ingredient list",
        "notes",
        "links",
        "follow me",
        "chapters",
    }


def _detect_tags(text: str) -> list[str]:
    tag_rules = {
        "chicken": ("chicken breast", "chicken thigh", "chicken thighs", "whole chicken"),
        "pasta": ("pasta", "spaghetti", "linguine", "penne"),
        "beef": ("beef", "steak", "ground beef"),
        "seafood": ("shrimp", "salmon", "fish", "seafood"),
        "dessert": ("dessert", "cake", "cookie", "brownie", "sweet"),
        "slow-cooker": ("slow cooker", "crockpot"),
        "air-fryer": ("air fryer",),
        "weeknight": ("weeknight", "easy dinner", "quick dinner"),
        "vegetarian": ("vegetarian", "veggie"),
    }
    return [tag for tag, needles in tag_rules.items() if any(needle in text for needle in needles)]


def _is_non_recipe_line(line: str) -> bool:
    lowered = line.lower().strip()
    if not lowered:
        return True
    if lowered.startswith(("http://", "https://", "www.")):
        return True
    promo_markers = ("subscribe", "substack", "follow me", "join the", "link in bio")
    return any(marker in lowered for marker in promo_markers)


def _looks_like_instruction(line: str) -> bool:
    lowered = line.lower().strip()
    verbs = (
        "add",
        "bake",
        "boil",
        "brown",
        "chop",
        "cook",
        "drain",
        "fold",
        "garnish",
        "heat",
        "mix",
        "preheat",
        "reduce",
        "roast",
        "saute",
        "sauté",
        "season",
        "simmer",
        "stir",
        "whisk",
    )
    return lowered.startswith(verbs) or bool(re.match(r"^\d+[.)]\s+", lowered))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    return deduped


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract recipe-like details from a YouTube URL.")
    parser.add_argument("url", help="YouTube URL or video id")
    parser.add_argument("--title", help="Canonical recipe title supplied by the user")
    parser.add_argument("--comments", action="store_true", help="Fetch comments with YOUTUBE_API_KEY")
    args = parser.parse_args()

    extraction = extract_youtube_recipe(args.url, recipe_title=args.title, include_comments=args.comments)
    print(json.dumps(extraction.as_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
