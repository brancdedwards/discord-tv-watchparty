"""
Database bridge for querying the review_analyzer database.
Provides utilities to fetch series, episodes, genres, and aggregated data.
"""
import psycopg2
from psycopg2.extras import Json
from psycopg2 import Error
import logging
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger(__name__)


class DatabaseBridge:
    """Interface to the review_analyzer PostgreSQL database."""

    @staticmethod
    def get_connection():
        """Create and return a PostgreSQL database connection."""
        try:
            conn = psycopg2.connect(
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT
            )
            return conn
        except Error as e:
            logger.error(f"Database connection error: {e}")
            raise

    @staticmethod
    def title_exists(imdb_id: str) -> bool:
        """
        Check if a title exists in the database.

        Args:
            imdb_id: IMDb ID (e.g., "tt4574334")

        Returns:
            True if exists, False otherwise
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM titles WHERE title_id = %s",
                    (imdb_id,)
                )
                count = cur.fetchone()[0]
                return count > 0
        except Error as e:
            logger.error(f"Error checking if title exists: {e}")
            return False
        finally:
            if conn:
                conn.close()

    # Alias for backward compatibility
    @staticmethod
    def series_exists(imdb_id: str) -> bool:
        """Alias for title_exists for backward compatibility."""
        return DatabaseBridge.title_exists(imdb_id)

    @staticmethod
    def get_series_by_imdb_id(imdb_id: str) -> dict:
        """
        Get title metadata by IMDb ID.

        Args:
            imdb_id: IMDb ID (e.g., "tt4574334")

        Returns:
            Dict with title data or None if not found
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        title_id,
                        title_name,
                        num_seasons,
                        total_episodes,
                        imdb_rating,
                        vote_count,
                        certification,
                        primary_language,
                        origin_country
                    FROM titles
                    WHERE title_id = %s
                """, (imdb_id,))
                row = cur.fetchone()
                if row:
                    return {
                        "imdb_id": row[0],
                        "title": row[1],
                        "num_seasons": row[2],
                        "total_episodes": row[3],
                        "rating": row[4],
                        "vote_count": row[5],
                        "certification": row[6],
                        "language": row[7],
                        "origin_country": row[8]
                    }
                return None
        except Error as e:
            logger.error(f"Error fetching title {imdb_id}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_genres(imdb_id: str) -> list:
        """
        Get genres for a title.

        Args:
            imdb_id: IMDb ID

        Returns:
            List of genre strings
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT g.genre_name
                    FROM genres g
                    JOIN title_genres tg ON g.genre_id = tg.genre_id
                    WHERE tg.title_id = %s
                    ORDER BY g.genre_name
                """, (imdb_id,))
                rows = cur.fetchall()
                return [row[0] for row in rows] if rows else []
        except Error as e:
            logger.error(f"Error fetching genres for {imdb_id}: {e}")
            return []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_episode_ratings_by_season(imdb_id: str) -> dict:
        """
        Get average ratings per season for a series.

        Args:
            imdb_id: IMDb ID of series

        Returns:
            Dict mapping season number to avg rating
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        season,
                        ROUND(AVG(aggregaterating)::numeric, 1) as avg_rating,
                        COUNT(*) as episode_count
                    FROM episodes
                    WHERE title_id = %s
                    GROUP BY season
                    ORDER BY season
                """, (imdb_id,))
                rows = cur.fetchall()
                return {
                    row[0]: {
                        "avg_rating": float(row[1]) if row[1] else None,
                        "episode_count": row[2]
                    }
                    for row in rows
                }
        except Error as e:
            logger.error(f"Error fetching season ratings for {imdb_id}: {e}")
            return {}
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_series_by_title(title: str, limit: int = 10) -> list:
        """
        Search for series by title (case-insensitive).

        Args:
            title: Series title to search for
            limit: Max results

        Returns:
            List of matching series
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        title_id,
                        title_name,
                        num_seasons,
                        imdb_rating
                    FROM titles
                    WHERE LOWER(title_name) LIKE LOWER(%s)
                    LIMIT %s
                """, (f"%{title}%", limit))
                rows = cur.fetchall()
                return [
                    {
                        "imdb_id": row[0],
                        "title": row[1],
                        "num_seasons": row[2],
                        "rating": row[3]
                    }
                    for row in rows
                ]
        except Error as e:
            logger.error(f"Error searching for series: {e}")
            return []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_top_seasons(imdb_id: str, limit: int = 3) -> list:
        """
        Get top-rated seasons for a series.

        Args:
            imdb_id: IMDb ID
            limit: Number of top seasons to return

        Returns:
            List of (season_number, avg_rating) tuples
        """
        try:
            seasons_data = DatabaseBridge.get_episode_ratings_by_season(imdb_id)
            if not seasons_data:
                return []

            # Sort by rating descending
            sorted_seasons = sorted(
                seasons_data.items(),
                key=lambda x: x[1]["avg_rating"] if x[1]["avg_rating"] else 0,
                reverse=True
            )
            return sorted_seasons[:limit]
        except Exception as e:
            logger.error(f"Error getting top seasons for {imdb_id}: {e}")
            return []

    @staticmethod
    def get_random_title(limit: int = 1) -> list:
        """
        Get random titles from database.

        Args:
            limit: Number of random titles to return

        Returns:
            List of random title dicts
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        title_id,
                        title_name,
                        num_seasons,
                        imdb_rating
                    FROM titles
                    WHERE num_seasons > 0
                    ORDER BY RANDOM()
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
                return [
                    {
                        "imdb_id": row[0],
                        "title": row[1],
                        "num_seasons": row[2],
                        "rating": row[3]
                    }
                    for row in rows
                ]
        except Error as e:
            logger.error(f"Error fetching random title: {e}")
            return []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def add_to_queue(
        title: str,
        content_type: str = "tvSeries",
        imdb_id: str = None,
        year: int = None,
        poster_url: str = None,
        rating: float = None
    ) -> dict:
        """
        Add a title to the scrape queue.

        Args:
            title: Title name
            content_type: 'tvSeries' or 'movie'
            imdb_id: IMDb ID (optional)
            year: Release year (optional)
            poster_url: Poster image URL (optional)
            rating: IMDb rating (optional)

        Returns:
            Dict with queue entry or error
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO scrape_queue
                    (imdb_id, title, content_type, year, poster_url, rating, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                    RETURNING id, imdb_id, title, status, added_at
                """, (imdb_id, title, content_type, year, poster_url, rating))
                row = cur.fetchone()
                conn.commit()

                if row:
                    return {
                        "success": True,
                        "queue_id": row[0],
                        "imdb_id": row[1],
                        "title": row[2],
                        "status": row[3],
                        "added_at": row[4]
                    }
        except Error as e:
            logger.error(f"Error adding to queue: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_pending_queue(limit: int = 10) -> list:
        """
        Get pending items in the scrape queue.

        Args:
            limit: Max items to return

        Returns:
            List of pending queue items
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, imdb_id, title, content_type, year, rating, added_at
                    FROM scrape_queue
                    WHERE status = 'pending'
                    ORDER BY added_at ASC
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
                return [
                    {
                        "queue_id": row[0],
                        "imdb_id": row[1],
                        "title": row[2],
                        "content_type": row[3],
                        "year": row[4],
                        "rating": row[5],
                        "added_at": row[6]
                    }
                    for row in rows
                ]
        except Error as e:
            logger.error(f"Error fetching queue: {e}")
            return []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def update_queue_item(queue_id: int, imdb_id: str = None, status: str = None, error_message: str = None) -> bool:
        """
        Update a queue item with scrape results.

        Args:
            queue_id: Queue entry ID
            imdb_id: IMDb ID (optional)
            status: New status (pending, in_progress, completed, failed)
            error_message: Error message if failed (optional)

        Returns:
            True if successful
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                updates = []
                params = []

                if imdb_id:
                    updates.append("imdb_id = %s")
                    params.append(imdb_id)
                if status:
                    updates.append("status = %s")
                    params.append(status)
                    if status == 'completed':
                        updates.append("completed_at = NOW()")
                    elif status == 'in_progress':
                        updates.append("started_at = NOW()")
                if error_message:
                    updates.append("error_message = %s")
                    params.append(error_message)

                if not updates:
                    return False

                params.append(queue_id)
                query = f"UPDATE scrape_queue SET {', '.join(updates)} WHERE id = %s"
                cur.execute(query, params)
                conn.commit()
                return True
        except Error as e:
            logger.error(f"Error updating queue item: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_all_titles(content_type: str = "tv_series", limit: int = 10, offset: int = 0, sort_by: str = "title") -> tuple:
        """
        Get paginated list of all titles.

        Args:
            content_type: 'tv_series' or 'movie'
            limit: Results per page
            offset: Number to skip
            sort_by: 'title', 'rating', 'recent'

        Returns:
            (total_count, results_list)
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                # Get total count
                cur.execute(
                    "SELECT COUNT(*) FROM titles WHERE title_type = %s",
                    (content_type,)
                )
                total = cur.fetchone()[0]

                # Get paginated results
                if sort_by == "rating":
                    order = "imdb_rating DESC NULLS LAST"
                elif sort_by == "recent":
                    order = "updated_date DESC"
                else:  # title
                    order = "title_name ASC"

                cur.execute(f"""
                    SELECT
                        title_id,
                        title_name,
                        num_seasons,
                        imdb_rating,
                        vote_count
                    FROM titles
                    WHERE title_type = %s
                    ORDER BY {order}
                    LIMIT %s OFFSET %s
                """, (content_type, limit, offset))

                rows = cur.fetchall()
                results = [
                    {
                        "imdb_id": row[0],
                        "title": row[1],
                        "seasons": row[2],
                        "rating": row[3],
                        "votes": row[4]
                    }
                    for row in rows
                ]

                return (total, results)
        except Error as e:
            logger.error(f"Error fetching titles: {e}")
            return (0, [])
        finally:
            if conn:
                conn.close()

    @staticmethod
    def add_to_wishlist(title_id: str, title_name: str, content_type: str, added_by: str, aggregate_rating: float = None) -> bool:
        """
        Add a title to the wishlist.

        Args:
            title_id: IMDb ID
            title_name: Title name
            content_type: 'tvSeries' or 'movie'
            added_by: Username (Brandon or Morgan)
            aggregate_rating: Optional IMDb rating (populated from search)

        Returns:
            True if added, False if already in wishlist
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                # Check if already in wishlist
                cur.execute(
                    "SELECT COUNT(*) FROM wishlist WHERE title_id = %s",
                    (title_id,)
                )
                if cur.fetchone()[0] > 0:
                    return False

                # Add to wishlist with optional rating
                cur.execute("""
                    INSERT INTO wishlist (title_id, title_name, content_type, added_by, aggregate_rating)
                    VALUES (%s, %s, %s, %s, %s)
                """, (title_id, title_name, content_type, added_by, aggregate_rating))

                conn.commit()
                return True
        except Error as e:
            logger.error(f"Error adding to wishlist: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_wishlist() -> list:
        """
        Get all items in the wishlist.

        Returns:
            List of dicts with wishlist items
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT wishlist_id, title_id, title_name, content_type, added_by, added_at, aggregate_rating
                    FROM wishlist
                    ORDER BY added_at DESC
                """)
                rows = cur.fetchall()
                results = [
                    {
                        "wishlist_id": row[0],
                        "imdb_id": row[1],
                        "title": row[2],
                        "content_type": row[3],
                        "added_by": row[4],
                        "added_at": row[5],
                        "rating": row[6]
                    }
                    for row in rows
                ]
                return results
        except Error as e:
            logger.error(f"Error fetching wishlist: {e}")
            return []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def remove_from_wishlist(title_id: str) -> bool:
        """
        Remove a title from the wishlist.

        Args:
            title_id: IMDb ID

        Returns:
            True if removed, False if not found
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM wishlist WHERE title_id = %s",
                    (title_id,)
                )
                conn.commit()
                return cur.rowcount > 0
        except Error as e:
            logger.error(f"Error removing from wishlist: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def update_wishlist_rating(title_id: str, aggregate_rating: float) -> bool:
        """
        Update the aggregate rating for a wishlist item (called after scraping).

        Args:
            title_id: IMDb ID
            aggregate_rating: The rating to store

        Returns:
            True if updated, False otherwise
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE wishlist SET aggregate_rating = %s WHERE title_id = %s",
                    (aggregate_rating, title_id)
                )
                conn.commit()
                return cur.rowcount > 0
        except Error as e:
            logger.error(f"Error updating wishlist rating: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def wishlist_item_exists(title_id: str) -> bool:
        """
        Check if a title is in the wishlist by ID.

        Args:
            title_id: IMDb ID or pseudo-ID (unknown-xxx)

        Returns:
            True if in wishlist, False otherwise
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM wishlist WHERE title_id = %s",
                    (title_id,)
                )
                count = cur.fetchone()[0]
                return count > 0
        except Error as e:
            logger.error(f"Error checking wishlist: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def wishlist_item_exists_by_name(title_name: str) -> bool:
        """
        Check if a title is in the wishlist by name.

        Args:
            title_name: Title name

        Returns:
            True if in wishlist, False otherwise
        """
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM wishlist WHERE LOWER(title_name) = LOWER(%s)",
                    (title_name,)
                )
                count = cur.fetchone()[0]
                return count > 0
        except Error as e:
            logger.error(f"Error checking wishlist: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def ensure_recipes_schema() -> bool:
        """Create recipe storage tables if they do not exist."""
        conn = None
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS recipes (
                        recipe_id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        source_url TEXT,
                        source_type TEXT,
                        source_video_id TEXT,
                        source_title TEXT,
                        channel TEXT,
                        status TEXT NOT NULL DEFAULT 'idea_saved',
                        confidence TEXT NOT NULL DEFAULT 'low',
                        added_by TEXT,
                        notes TEXT,
                        source_description TEXT,
                        source_links JSONB NOT NULL DEFAULT '[]'::jsonb,
                        ingredients JSONB NOT NULL DEFAULT '[]'::jsonb,
                        instructions JSONB NOT NULL DEFAULT '[]'::jsonb,
                        tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                        extraction_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
                        warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
                        captured_at TIMESTAMPTZ,
                        added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recipes_added_at
                    ON recipes (added_at DESC)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_recipes_title_lower
                    ON recipes (LOWER(title))
                """)
                conn.commit()
                return True
        except Error as e:
            logger.error(f"Error ensuring recipes schema: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def add_recipe(recipe: dict) -> dict:
        """Add a recipe or recipe idea and return the saved row."""
        conn = None
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                source_url = recipe.get("source_url")
                if source_url:
                    cur.execute(
                        "SELECT recipe_id FROM recipes WHERE source_url = %s ORDER BY added_at DESC LIMIT 1",
                        (source_url,)
                    )
                    existing = cur.fetchone()
                    if existing:
                        return {"success": False, "duplicate_id": existing[0]}

                cur.execute("""
                    INSERT INTO recipes (
                        title, source_url, source_type, source_video_id, source_title,
                        channel, status, confidence, added_by, notes, source_description,
                        source_links, ingredients, instructions, tags, extraction_sources,
                        warnings, captured_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s
                    )
                    RETURNING recipe_id
                """, (
                    recipe.get("title"),
                    source_url,
                    recipe.get("source_type"),
                    recipe.get("source_video_id"),
                    recipe.get("source_title"),
                    recipe.get("channel"),
                    recipe.get("status", "idea_saved"),
                    recipe.get("confidence", "low"),
                    recipe.get("added_by"),
                    recipe.get("notes"),
                    recipe.get("source_description"),
                    Json(recipe.get("source_links", [])),
                    Json(recipe.get("ingredients", [])),
                    Json(recipe.get("instructions", [])),
                    Json(recipe.get("tags", [])),
                    Json(recipe.get("extraction_sources", [])),
                    Json(recipe.get("warnings", [])),
                    recipe.get("captured_at")
                ))
                recipe_id = cur.fetchone()[0]
                conn.commit()
                return {"success": True, "recipe_id": recipe_id}
        except Error as e:
            logger.error(f"Error adding recipe: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_recipes(limit: int = 10, offset: int = 0, query: str = None, sort: str = "newest") -> tuple:
        """Return (total_count, recipes) for the saved recipe list."""
        conn = None
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                params = []
                where = ""
                if query:
                    where = """
                        WHERE LOWER(title) LIKE LOWER(%s)
                           OR LOWER(COALESCE(notes, '')) LIKE LOWER(%s)
                           OR LOWER(COALESCE(source_title, '')) LIKE LOWER(%s)
                    """
                    like = f"%{query}%"
                    params.extend([like, like, like])

                cur.execute(f"SELECT COUNT(*) FROM recipes {where}", params)
                total = cur.fetchone()[0]
                order_by = {
                    "newest": "added_at DESC",
                    "oldest": "added_at ASC",
                    "title_asc": "LOWER(title) ASC, added_at DESC",
                    "title_desc": "LOWER(title) DESC, added_at DESC",
                    "updated": "updated_at DESC",
                }.get(sort, "added_at DESC")

                cur.execute(f"""
                    SELECT recipe_id, title, source_url, source_type, source_title,
                           channel, status, confidence, added_by, notes,
                           source_description, source_links, ingredients, instructions,
                           tags, extraction_sources, warnings, captured_at, added_at, updated_at
                    FROM recipes
                    {where}
                    ORDER BY {order_by}
                    LIMIT %s OFFSET %s
                """, params + [limit, offset])
                return total, [DatabaseBridge._recipe_row_to_dict(row) for row in cur.fetchall()]
        except Error as e:
            logger.error(f"Error fetching recipes: {e}")
            return 0, []
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_recipe(recipe_id: int) -> dict:
        """Get one saved recipe by ID."""
        conn = None
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT recipe_id, title, source_url, source_type, source_title,
                           channel, status, confidence, added_by, notes,
                           source_description, source_links, ingredients, instructions,
                           tags, extraction_sources, warnings, captured_at, added_at, updated_at
                    FROM recipes
                    WHERE recipe_id = %s
                """, (recipe_id,))
                row = cur.fetchone()
                return DatabaseBridge._recipe_row_to_dict(row) if row else None
        except Error as e:
            logger.error(f"Error fetching recipe {recipe_id}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    @staticmethod
    def update_recipe(recipe_id: int, title: str = None, notes: str = None, status: str = None) -> bool:
        """Update basic editable recipe fields."""
        updates = []
        params = []
        if title:
            updates.append("title = %s")
            params.append(title)
        if notes is not None:
            updates.append("notes = %s")
            params.append(notes)
        if status:
            updates.append("status = %s")
            params.append(status)
        if not updates:
            return False

        updates.append("updated_at = NOW()")
        params.append(recipe_id)
        conn = None
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute(f"UPDATE recipes SET {', '.join(updates)} WHERE recipe_id = %s", params)
                conn.commit()
                return cur.rowcount > 0
        except Error as e:
            logger.error(f"Error updating recipe {recipe_id}: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def remove_recipe(recipe_id: int) -> bool:
        """Remove a saved recipe."""
        conn = None
        try:
            conn = DatabaseBridge.get_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM recipes WHERE recipe_id = %s", (recipe_id,))
                conn.commit()
                return cur.rowcount > 0
        except Error as e:
            logger.error(f"Error removing recipe {recipe_id}: {e}")
            return False
        finally:
            if conn:
                conn.close()

    @staticmethod
    def _recipe_row_to_dict(row) -> dict:
        if not row:
            return None
        return {
            "recipe_id": row[0],
            "title": row[1],
            "source_url": row[2],
            "source_type": row[3],
            "source_title": row[4],
            "channel": row[5],
            "status": row[6],
            "confidence": row[7],
            "added_by": row[8],
            "notes": row[9],
            "source_description": row[10],
            "source_links": row[11] or [],
            "ingredients": row[12] or [],
            "instructions": row[13] or [],
            "tags": row[14] or [],
            "extraction_sources": row[15] or [],
            "warnings": row[16] or [],
            "captured_at": row[17],
            "added_at": row[18],
            "updated_at": row[19]
        }

    @staticmethod
    def close_connection(conn):
        """Close database connection."""
        if conn:
            try:
                conn.close()
            except Error:
                pass
