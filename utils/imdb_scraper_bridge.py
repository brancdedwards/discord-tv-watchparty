"""
Bridge to the review_analyzer scraper.
Handles spawning and managing the scraper subprocess.
"""
import asyncio
import logging
import os
from pathlib import Path
from config import REVIEW_ANALYZER_PATH, SCRAPER_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class ScraperBridge:
    """Interface to the review_analyzer scraper via subprocess."""

    @staticmethod
    def get_scraper_path() -> Path:
        """Get the path to the review_analyzer project."""
        # Try to resolve relative path first
        analyzer_path = Path(REVIEW_ANALYZER_PATH).resolve()
        if analyzer_path.exists():
            return analyzer_path

        # Try absolute path
        analyzer_path = Path(REVIEW_ANALYZER_PATH)
        if analyzer_path.exists():
            return analyzer_path

        raise FileNotFoundError(
            f"review_analyzer project not found at {REVIEW_ANALYZER_PATH}"
        )

    @staticmethod
    async def scrape_show(imdb_id: str, content_type: str = "tvSeries") -> dict:
        """
        Trigger a scrape for a show/movie using the review_analyzer scraper.

        Args:
            imdb_id: IMDb ID (e.g., "tt4574334")
            content_type: "tvSeries" or "movie"

        Returns:
            Dict with status, output, and any errors
        """
        try:
            analyzer_path = ScraperBridge.get_scraper_path()
            scraper_script = analyzer_path / "imdb_scraper_project" / "run_scraper.py"

            if not scraper_script.exists():
                return {
                    "success": False,
                    "error": f"Scraper script not found at {scraper_script}",
                    "imdb_id": imdb_id
                }

            # Build command
            cmd = [
                "python",
                str(scraper_script),
                imdb_id,
                "--yes"  # Auto-confirm prompts
            ]

            logger.info(f"Spawning scraper: {' '.join(cmd)}")

            # Spawn subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(analyzer_path)
            )

            logger.info(f"Scraper process spawned with PID {process.pid}")

            return {
                "success": True,
                "process": process,
                "imdb_id": imdb_id,
                "pid": process.pid
            }

        except Exception as e:
            logger.error(f"Error spawning scraper: {e}")
            return {
                "success": False,
                "error": str(e),
                "imdb_id": imdb_id
            }

    @staticmethod
    async def wait_for_scrape(process, timeout: int = SCRAPER_TIMEOUT_SECONDS) -> dict:
        """
        Wait for a scraper process to complete.

        Args:
            process: The asyncio Process object
            timeout: Max seconds to wait

        Returns:
            Dict with completion status, stdout, stderr
        """
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            return {
                "success": process.returncode == 0,
                "returncode": process.returncode,
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace')
            }

        except asyncio.TimeoutError:
            logger.warning(f"Scraper timed out after {timeout}s")
            process.kill()
            await process.wait()

            return {
                "success": False,
                "error": f"Scraper timed out after {timeout} seconds",
                "returncode": -1
            }

        except Exception as e:
            logger.error(f"Error waiting for scraper: {e}")
            return {
                "success": False,
                "error": str(e),
                "returncode": -1
            }

    @staticmethod
    async def scrape_and_wait(
        imdb_id: str,
        content_type: str = "tvSeries",
        timeout: int = SCRAPER_TIMEOUT_SECONDS
    ) -> dict:
        """
        Scrape and wait for completion in one call.

        Args:
            imdb_id: IMDb ID
            content_type: "tvSeries" or "movie"
            timeout: Max seconds to wait

        Returns:
            Combined result dict
        """
        # Spawn scraper
        spawn_result = await ScraperBridge.scrape_show(imdb_id, content_type)

        if not spawn_result.get("success"):
            return spawn_result

        # Wait for completion
        process = spawn_result["process"]
        wait_result = await ScraperBridge.wait_for_scrape(process, timeout)

        return {
            **spawn_result,
            **wait_result,
            "process": None  # Don't include process object in final result
        }
