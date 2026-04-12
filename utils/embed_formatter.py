"""
Format data into Discord embeds for display in chat.
"""
import discord
from typing import Optional, Dict, List


class EmbedFormatter:
    """Create formatted Discord embeds for IMDb data."""

    @staticmethod
    def format_series_summary(
        series_data: dict,
        seasons_data: dict,
        genres: List[str]
    ) -> discord.Embed:
        """
        Format series/movie data into a summary embed.

        Args:
            series_data: Dict from db_bridge.get_series_by_imdb_id()
            seasons_data: Dict from db_bridge.get_episode_ratings_by_season()
            genres: List of genre strings

        Returns:
            discord.Embed object
        """
        if not series_data:
            return EmbedFormatter.format_error("Series not found")

        title = series_data.get("title", "Unknown")
        imdb_id = series_data.get("imdb_id", "")
        rating = series_data.get("rating")
        num_seasons = series_data.get("num_seasons", 0)
        total_episodes = series_data.get("total_episodes", 0)
        certification = series_data.get("certification", "Not rated")

        # Create embed
        embed = discord.Embed(
            title=title,
            url=f"https://www.imdb.com/title/{imdb_id}/",
            color=discord.Color.gold()
        )

        # Rating and basic info
        rating_text = f"⭐ {rating}" if rating else "⭐ Not rated"
        embed.add_field(name="Rating", value=rating_text, inline=True)
        embed.add_field(name="Seasons", value=str(num_seasons), inline=True)
        embed.add_field(name="Episodes", value=str(total_episodes), inline=True)

        # Certification
        if certification:
            embed.add_field(name="Certification", value=certification, inline=True)

        # Genres
        if genres:
            genre_text = ", ".join(genres[:5])  # Max 5 genres
            embed.add_field(name="Genres", value=genre_text, inline=False)

        # Season ratings (top 3)
        if seasons_data:
            season_ratings = []
            for season_num in sorted(seasons_data.keys()):
                season_info = seasons_data[season_num]
                avg_rating = season_info.get("avg_rating")
                if avg_rating:
                    season_ratings.append((season_num, avg_rating))

            if season_ratings:
                # Show top 3 rated seasons
                top_seasons = sorted(season_ratings, key=lambda x: x[1], reverse=True)[:3]
                season_text = "\n".join(
                    f"Season {s[0]}: ⭐ {s[1]}"
                    for s in top_seasons
                )
                embed.add_field(
                    name="Top Seasons",
                    value=season_text,
                    inline=False
                )

        embed.set_footer(text=f"IMDb ID: {imdb_id}")
        return embed

    @staticmethod
    def format_scraping_status(
        title: str,
        status: str,
        details: str = ""
    ) -> discord.Embed:
        """
        Format a scraping status embed.

        Args:
            title: Show title
            status: Status string (e.g., "starting", "in_progress", "complete")
            details: Optional details

        Returns:
            discord.Embed object
        """
        status_emoji = {
            "starting": "🔄",
            "in_progress": "⏳",
            "complete": "✅",
            "error": "❌"
        }.get(status, "⏳")

        embed = discord.Embed(
            title=f"{status_emoji} {title}",
            color=discord.Color.blue() if status == "in_progress" else discord.Color.green()
        )

        status_text = {
            "starting": "Starting scrape...",
            "in_progress": "Scraping in progress... This may take 5-15 minutes.",
            "complete": "Scrape complete!",
            "error": "Scrape encountered an error."
        }.get(status, status)

        embed.description = status_text
        if details:
            embed.add_field(name="Details", value=details, inline=False)

        return embed

    @staticmethod
    def format_imdb_search_results(
        results: List[dict]
    ) -> discord.Embed:
        """
        Format IMDb search results.

        Args:
            results: List of search result dicts from imdb_search

        Returns:
            discord.Embed object
        """
        if not results:
            return EmbedFormatter.format_error("No results found")

        embed = discord.Embed(
            title="IMDb Search Results",
            color=discord.Color.blue(),
            description="Click the button below to select a show"
        )

        for i, result in enumerate(results[:5], 1):
            title = result.get("title", "Unknown")
            year = result.get("year", "N/A")
            content_type = result.get("type", "unknown")
            imdb_id = result.get("imdb_id", "")

            embed.add_field(
                name=f"{i}. {title} ({year})",
                value=f"Type: {content_type} | ID: {imdb_id}",
                inline=False
            )

        return embed

    @staticmethod
    def format_error(message: str) -> discord.Embed:
        """
        Format an error embed.

        Args:
            message: Error message

        Returns:
            discord.Embed object
        """
        embed = discord.Embed(
            title="❌ Error",
            description=message,
            color=discord.Color.red()
        )
        return embed

    @staticmethod
    def format_info(title: str, message: str) -> discord.Embed:
        """
        Format an info embed.

        Args:
            title: Embed title
            message: Info message

        Returns:
            discord.Embed object
        """
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=message,
            color=discord.Color.blurple()
        )
        return embed

    @staticmethod
    def truncate(text: str, max_length: int = 1024) -> str:
        """
        Truncate text to Discord's embed field limit.

        Args:
            text: Text to truncate
            max_length: Max length (Discord limit is 1024 for fields)

        Returns:
            Truncated text
        """
        if len(text) > max_length:
            return text[:max_length - 3] + "..."
        return text
