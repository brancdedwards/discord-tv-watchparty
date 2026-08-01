"""
IMDb Search Utility
Uses the FindPageSearch GraphQL endpoint for full results (25+ per page, paginated).
Falls back to the autocomplete API if GraphQL is unavailable.
"""

import json
import logging
import re
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL endpoint config
# ---------------------------------------------------------------------------
_GRAPHQL_URL = "https://api.graphql.imdb.com/"
_FIND_PAGE_SEARCH_QUERY = """
query FindPageSearch(
    $skipHasExact: Boolean!
    $numResults: Int!
    $searchTerm: String!
    $includeAdult: Boolean!
    $isExactMatch: Boolean!
    $typeFilter: [MainSearchType!]
    $titleSearchOptions: TitleSearchOptions
    $after: String
) {
    results: mainSearch(
        first: $numResults
        after: $after
        options: {
            searchTerm: $searchTerm
            type: $typeFilter
            includeAdult: $includeAdult
            isExactMatch: $isExactMatch
            titleSearchOptions: $titleSearchOptions
        }
    ) {
        edges {
            node {
                entity {
                    __typename
                    ... on Title {
                        id
                        titleText { text }
                        releaseYear { year }
                        titleType { id text }
                        primaryImage { url }
                        ratingsSummary { aggregateRating }
                        titleGenres { genres { genre { text } } }
                    }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
    hasExact: mainSearch(
        first: 1
        options: {
            searchTerm: $searchTerm
            type: $typeFilter
            includeAdult: $includeAdult
            isExactMatch: true
            titleSearchOptions: $titleSearchOptions
        }
    ) {
        edges @skip(if: $skipHasExact) {
            node {
                entity {
                    __typename
                }
            }
        }
    }
}
"""
_GRAPHQL_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "x-imdb-user-language": "en-US",
    "x-imdb-client-name": "imdb-web-next-localized",
    "content-type": "application/json",
    "origin": "https://www.imdb.com",
    "referer": "https://www.imdb.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
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
        "numResults": num_results,
        "searchTerm": query.strip(),
        "skipHasExact": True,
        "titleSearchOptions": None,
        "typeFilter": ["TITLE"],
        "after": after,
    }

    payload = {
        "query": _FIND_PAGE_SEARCH_QUERY,
        "variables": variables,
    }

    session, using_curl = _get_session()
    response = session.post(_GRAPHQL_URL, json=payload, headers=_GRAPHQL_HEADERS, timeout=8)
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        logger.warning(f"GraphQL search '{query}' returned errors: {data.get('errors')}")

    results_block = (data.get("data") or {}).get("results") or {}
    edges = results_block.get("edges", [])
    page_info = results_block.get("pageInfo") or {}

    results = _parse_graphql_edges(edges, content_type)
    next_cursor = page_info.get("endCursor")
    has_next_page = page_info.get("hasNextPage", False)

    logger.info(
        f"GraphQL search '{query}': {len(results)} results "
        f"(raw_edges={len(edges)}, has_next={has_next_page}, curl_cffi={using_curl})"
    )
    if edges and not results:
        logger.warning(
            f"GraphQL returned {len(edges)} raw edges for '{query}', but none matched the expected title schema/type filter."
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
    query_clean = query.strip().lower().replace(" ", "_")
    first_char = query_clean[0] if query_clean else "a"
    url = f"https://sg.media-imdb.com/suggests/{first_char}/{query_clean}.json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    session, using_curl = _get_session()
    response = session.get(url, headers=headers, timeout=5)
    response.raise_for_status()
    logger.info(f"Autocomplete request '{query}' completed (curl_cffi={using_curl})")

    text = response.text
    if "imdb$" not in text:
        return []

    json_str = text[text.index("(") + 1: text.rindex(")")]
    data = json.loads(json_str)

    results = []
    for source_rank, item in enumerate(data.get("d", [])):
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
            "type_description": item.get("q"),
            "summary": item.get("s"),
            "year_range": item.get("yr"),
            "poster_url": poster_url,
            "rating": None,
            "genres": [],
            "source_rank": source_rank,
        })

    return results


def _normalize_genres(raw_genres) -> List[str]:
    """Return IMDb JSON-LD genres as a simple list."""
    if isinstance(raw_genres, list):
        return [genre for genre in raw_genres if genre]
    if isinstance(raw_genres, str) and raw_genres:
        return [raw_genres]
    return []


def _enrich_result_from_title_page(result: Dict, session=None) -> bool:
    """
    Fill missing rating/genre/poster data from the IMDb title page JSON-LD.
    Returns True when at least one field was added.
    """
    imdb_id = result.get("imdb_id")
    if not imdb_id:
        return False

    own_session = session is None
    if own_session:
        session, _ = _get_session()

    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://www.imdb.com/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
    }
    url = f"https://www.imdb.com/title/{imdb_id}/"

    try:
        response = session.get(url, headers=headers, timeout=4)
        response.raise_for_status()
        match = re.search(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            response.text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return False

        title_data = json.loads(match.group(1).strip())
        changed = False

        aggregate_rating = title_data.get("aggregateRating") or {}
        rating_value = aggregate_rating.get("ratingValue")
        if rating_value and not result.get("rating"):
            result["rating"] = rating_value
            changed = True

        genres = _normalize_genres(title_data.get("genre"))
        if genres and not result.get("genres"):
            result["genres"] = genres
            changed = True

        image = title_data.get("image")
        if image and not result.get("poster_url"):
            result["poster_url"] = image
            changed = True

        return changed
    except Exception as e:
        logger.info(f"Title page enrichment skipped for {imdb_id}: {e}")
        return False


def _enrich_missing_details(results: List[Dict], limit: int = 3) -> int:
    """Enrich the first few results that lack ratings or genres."""
    if not results:
        return 0

    session, _ = _get_session()
    enriched = 0
    for result in results[:limit]:
        if result.get("rating") and result.get("genres"):
            continue
        if _enrich_result_from_title_page(result, session=session):
            enriched += 1

    return enriched


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
        for source_rank, result in enumerate(graphql_results):
            result["source_rank"] = source_rank
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
    enriched_count = _enrich_missing_details(combined, limit=3)
    logger.info(
        f"Combined: {len(combined)} results ({len(extras)} unique from autocomplete, "
        f"{enriched_count} enriched from title pages)"
    )
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
