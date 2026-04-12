"""
IMDb Search Utility
Uses the FindPageSearch GraphQL endpoint for full results (25+ per page, paginated).
Falls back to the autocomplete API if GraphQL is unavailable.
"""

import json
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL endpoint config
# ---------------------------------------------------------------------------
_GRAPHQL_URL = "https://caching.graphql.imdb.com/"
_GRAPHQL_HASH = "b6a7c673cfb2d2cc8d78570a7d5f6e0d65601021fcbbdc71cde7a53468641fa1"
_GRAPHQL_HEADERS = {
    "x-imdb-user-country": "US",
    "x-imdb-user-language": "en-US",
    "x-imdb-client-name": "imdb-web-next-localized",
    "accept": "application/graphql+json, application/json",
    "content-type": "application/json",
    "Referer": "https://www.imdb.com/",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 8.0.0; SM-G955U Build/R16NW) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Mobile Safari/537.36"
    ),
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "DNT": "1",
}

# titleType.id values returned by GraphQL → our content_type
_MOVIE_TYPES = {"movie", "tvMovie", "video", "short", "tvShort", "musicVideo"}
_TV_TYPES = {"tvSeries", "tvMiniSeries", "tvSpecial"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
    """Return a curl_cffi session (Chrome impersonation) or fall back to requests."""
    try:
        from curl_cffi.requests import Session
        session = Session(impersonate="chrome120")
        return session, True
    except ImportError:
        import requests
        return requests.Session(), False


def _map_type(title_type_id: str) -> Optional[str]:
    """Map GraphQL titleType.id → 'movie' | 'tv_series' | None (skip)."""
    if title_type_id in _MOVIE_TYPES:
        return "movie"
    if title_type_id in _TV_TYPES:
        return "tvSeries"
    return None


def _parse_graphql_edges(edges: list, content_type: str) -> List[Dict]:
    """Parse GraphQL edge nodes into our standard result dicts."""
    results = []
    for edge in edges:
        entity = (edge.get("node") or {}).get("entity") or {}
        if not entity:
            continue

        title_type_id = (entity.get("titleType") or {}).get("id", "")
        mapped_type = _map_type(title_type_id)
        if not mapped_type:
            continue
        if content_type != "all" and mapped_type != content_type:
            continue

        imdb_id = entity.get("id", "")
        title = (entity.get("titleText") or {}).get("text", "")
        if not imdb_id or not title:
            continue

        year = (entity.get("releaseYear") or {}).get("year")
        poster_url = (entity.get("primaryImage") or {}).get("url")
        rating = (entity.get("ratingsSummary") or {}).get("aggregateRating")

        # Genres (bonus data the autocomplete API doesn't return)
        genres = [
            g["genre"]["text"]
            for g in (entity.get("titleGenres") or {}).get("genres", [])
            if g.get("genre", {}).get("text")
        ]

        results.append({
            "imdb_id": imdb_id,
            "title": title,
            "year": year,
            "type": mapped_type,
            "poster_url": poster_url,
            "rating": rating,
            "genres": genres,
        })
    return results


# ---------------------------------------------------------------------------
# Primary: GraphQL FindPageSearch
# ---------------------------------------------------------------------------

def search_imdb_graphql(
    query: str,
    content_type: str = "all",
    num_results: int = 25,
    after: Optional[str] = None,
) -> Tuple[List[Dict], Optional[str], bool]:
    """
    Search IMDb using the FindPageSearch GraphQL endpoint.

    Args:
        query:        Search term (e.g. "batman")
        content_type: 'all' | 'movie' | 'tvSeries'
        num_results:  Results per page (max ~25 from IMDb)
        after:        Pagination cursor from a previous call

    Returns:
        (results, next_cursor, has_next_page)
        - results:       List of dicts with imdb_id, title, year, type, poster_url, rating, genres
        - next_cursor:   Opaque string to pass as `after` for the next page, or None
        - has_next_page: True if more pages exist
    """
    variables: Dict = {
        "includeAdult": False,
        "isExactMatch": False,
        "locale": "en-US",
        "numResults": num_results,
        "originalTitleText": False,
        "refTagQueryParam": None,
        "searchTerm": query.strip(),
        "skipHasExact": True,
        "typeFilter": "TITLE",
    }
    if after:
        variables["after"] = after

    extensions = {
        "persistedQuery": {
            "sha256Hash": _GRAPHQL_HASH,
            "version": 1,
        }
    }

    params = {
        "operationName": "FindPageSearch",
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(extensions, separators=(",", ":")),
    }

    session, using_curl = _get_session()
    response = session.get(_GRAPHQL_URL, params=params, headers=_GRAPHQL_HEADERS, timeout=8)
    response.raise_for_status()
    data = response.json()

    results_block = (data.get("data") or {}).get("results") or {}
    edges = results_block.get("edges", [])
    page_info = results_block.get("pageInfo") or {}

    results = _parse_graphql_edges(edges, content_type)
    next_cursor = page_info.get("endCursor")
    has_next_page = page_info.get("hasNextPage", False)

    logger.info(
        f"GraphQL search '{query}': {len(results)} results "
        f"(has_next={has_next_page}, curl_cffi={using_curl})"
    )
    return results, next_cursor, has_next_page


# ---------------------------------------------------------------------------
# Fallback: autocomplete API (legacy, returns ~5 results)
# ---------------------------------------------------------------------------

def _search_imdb_autocomplete(query: str, content_type: str = "all") -> List[Dict]:
    """
    Fall back to IMDb's suggestion/autocomplete API.
    Returns up to ~8 results with no pagination.
    """
    import requests

    query_clean = query.strip().lower().replace(" ", "_")
    first_char = query_clean[0] if query_clean else "a"
    url = f"https://sg.media-imdb.com/suggests/{first_char}/{query_clean}.json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    response = requests.get(url, headers=headers, timeout=5)
    response.raise_for_status()

    text = response.text
    if "imdb$" not in text:
        return []

    json_str = text[text.index("(") + 1: text.rindex(")")]
    data = json.loads(json_str)

    results = []
    for item in data.get("d", []):
        imdb_type = item.get("q", "").lower()
        if "tv series" in imdb_type or "tv mini series" in imdb_type:
            mapped_type = "tvSeries"
        elif any(k in imdb_type for k in ("feature", "movie", "short film")):
            mapped_type = "movie"
        else:
            continue

        if content_type != "all" and mapped_type != content_type:
            continue

        imdb_id = item.get("id", "")
        title = item.get("l", "")
        if not imdb_id or not title:
            continue

        # "i" is either a list [url, w, h] or a dict {"imageUrl": ...}
        raw_image = item.get("i")
        if isinstance(raw_image, list) and raw_image:
            poster_url = raw_image[0]
        elif isinstance(raw_image, dict):
            poster_url = raw_image.get("imageUrl")
        else:
            poster_url = None

        results.append({
            "imdb_id": imdb_id,
            "title": title,
            "year": item.get("y"),
            "type": mapped_type,
            "poster_url": poster_url,
            "rating": None,
            "genres": [],
        })

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_imdb(query: str, content_type: str = "all") -> List[Dict]:
    """
    Search IMDb for titles using BOTH the GraphQL FindPageSearch endpoint
    AND the autocomplete API, then merges and deduplicates the results.

    GraphQL returns 25 results with ratings + genres.
    Autocomplete returns ~8 results quickly and sometimes surfaces different hits.
    On overlap, GraphQL data wins (richer). Unique autocomplete hits are appended.

    Args:
        query:        Search term (e.g. "batman", "breaking bad")
        content_type: Filter — 'all' | 'movie' | 'tvSeries'

    Returns:
        List of dicts:
            imdb_id   (str)         e.g. "tt0468569"
            title     (str)         e.g. "The Dark Knight"
            year      (int|None)    e.g. 2008
            type      (str)         'movie' | 'tvSeries'
            poster_url(str|None)    CDN URL
            rating    (float|None)  IMDb aggregate rating (from GraphQL)
            genres    (list[str])   e.g. ["Action", "Crime"] (from GraphQL)
    """
    if not query or not query.strip():
        return []

    logger.info(f"Searching IMDb: '{query}' (type={content_type})")

    graphql_results: List[Dict] = []
    autocomplete_results: List[Dict] = []

    # 1. GraphQL — 25 results with ratings + genres
    try:
        graphql_results, _, _ = search_imdb_graphql(query, content_type=content_type)
        logger.info(f"GraphQL: {len(graphql_results)} results")
    except Exception as e:
        logger.warning(f"GraphQL search failed: {e}")

    # 2. Autocomplete — quick, different ranking, sometimes unique hits
    try:
        autocomplete_results = _search_imdb_autocomplete(query, content_type=content_type)
        logger.info(f"Autocomplete: {len(autocomplete_results)} results")
    except Exception as e:
        logger.warning(f"Autocomplete search failed: {e}")

    # 3. Merge — GraphQL results first, then any autocomplete hits not already present
    seen_ids = {r["imdb_id"] for r in graphql_results}
    extras = [r for r in autocomplete_results if r["imdb_id"] not in seen_ids]

    combined = graphql_results + extras
    logger.info(f"Combined: {len(combined)} results ({len(extras)} unique from autocomplete)")
    return combined


def search_imdb_paginated(
    query: str,
    content_type: str = "all",
    max_results: int = 50,
) -> List[Dict]:
    """
    Search IMDb and automatically follow pagination until max_results is reached.

    Useful for populating the queue with everything IMDb has for a broad term.
    Uses GraphQL only (no autocomplete fallback for pagination).

    Args:
        query:       Search term
        content_type: 'all' | 'movie' | 'tvSeries'
        max_results: Stop after collecting this many results (default 50)

    Returns:
        Combined list of results across pages.
    """
    all_results: List[Dict] = []
    cursor: Optional[str] = None

    while len(all_results) < max_results:
        try:
            batch, cursor, has_next = search_imdb_graphql(
                query,
                content_type=content_type,
                num_results=25,
                after=cursor,
            )
        except Exception as e:
            logger.error(f"Paginated search error on page {len(all_results)//25 + 1}: {e}")
            break

        all_results.extend(batch)

        if not has_next or not cursor:
            break

    return all_results[:max_results]
