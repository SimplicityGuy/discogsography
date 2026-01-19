"""Genre and style evolution tracking over time.

This module analyzes how musical genres and styles have evolved,
tracking popularity trends, emergence, decline, and cross-pollination.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver
import structlog


logger = structlog.get_logger(__name__)


@dataclass
class GenreTrend:
    """Trend data for a genre over time."""

    genre: str
    timeline: dict[int, int]  # year -> count
    peak_year: int
    peak_count: int
    total_releases: int
    growth_rate: float
    status: str  # emerging, growing, stable, declining


class GenreEvolutionTracker:
    """Track genre and style evolution over time."""

    def __init__(self, driver: AsyncDriver) -> None:
        """Initialize genre evolution tracker.

        Args:
            driver: Neo4j async driver instance
        """
        self.driver = driver
        self.genre_timelines: dict[str, dict[int, int]] = {}
        self.style_timelines: dict[str, dict[int, int]] = {}
        self.genre_cooccurrence: dict[tuple[str, str], int] = {}

    async def analyze_genre_timeline(
        self,
        start_year: int = 1950,
        end_year: int = 2024,
    ) -> dict[str, GenreTrend]:
        """Analyze how genres have evolved over time.

        Args:
            start_year: Start year for analysis
            end_year: End year for analysis

        Returns:
            Dictionary mapping genres to their trend data
        """
        logger.info("📊 Analyzing genre evolution timeline...")

        async with self.driver.session() as session:
            # Get genre counts per year
            result = await session.run(
                """
                MATCH (r:Release)-[:IS]->(g:Genre)
                WHERE r.year >= $start_year AND r.year <= $end_year
                RETURN g.name AS genre, r.year AS year, count(*) AS count
                ORDER BY g.name, r.year
                """,
                start_year=start_year,
                end_year=end_year,
            )

            # Build timelines
            genre_data: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

            async for record in result:
                genre = record["genre"]
                year = record["year"]
                count = record["count"]

                genre_data[genre][year] = count

        # Analyze trends
        trends = {}

        for genre, timeline in genre_data.items():
            self.genre_timelines[genre] = dict(timeline)
            trends[genre] = self._analyze_trend(genre, timeline, start_year, end_year)

        logger.info("✅ Analyzed genre evolution", genres=len(trends))

        return trends

    async def analyze_style_timeline(
        self,
        start_year: int = 1950,
        end_year: int = 2024,
    ) -> dict[str, GenreTrend]:
        """Analyze how styles have evolved over time.

        Args:
            start_year: Start year for analysis
            end_year: End year for analysis

        Returns:
            Dictionary mapping styles to their trend data
        """
        logger.info("📊 Analyzing style evolution timeline...")

        async with self.driver.session() as session:
            # Get style counts per year
            result = await session.run(
                """
                MATCH (r:Release)-[:IS]->(s:Style)
                WHERE r.year >= $start_year AND r.year <= $end_year
                RETURN s.name AS style, r.year AS year, count(*) AS count
                ORDER BY s.name, r.year
                """,
                start_year=start_year,
                end_year=end_year,
            )

            # Build timelines
            style_data: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

            async for record in result:
                style = record["style"]
                year = record["year"]
                count = record["count"]

                style_data[style][year] = count

        # Analyze trends
        trends = {}

        for style, timeline in style_data.items():
            self.style_timelines[style] = dict(timeline)
            trends[style] = self._analyze_trend(style, timeline, start_year, end_year)

        logger.info("✅ Analyzed style evolution", styles=len(trends))

        return trends

    def _analyze_trend(
        self,
        name: str,
        timeline: dict[int, int],
        start_year: int,  # noqa: ARG002
        end_year: int,
    ) -> GenreTrend:
        """Analyze trend for a single genre/style.

        Args:
            name: Genre or style name
            timeline: Year -> count mapping
            start_year: Analysis start year
            end_year: Analysis end year

        Returns:
            Trend analysis
        """
        if not timeline:
            return GenreTrend(
                genre=name,
                timeline={},
                peak_year=0,
                peak_count=0,
                total_releases=0,
                growth_rate=0.0,
                status="unknown",
            )

        # Find peak
        peak_year = max(timeline.items(), key=lambda x: x[1])[0]
        peak_count = timeline[peak_year]

        # Calculate total
        total_releases = sum(timeline.values())

        # Calculate growth rate (recent 5 years vs previous 5 years)
        recent_years = [y for y in range(end_year - 4, end_year + 1) if y in timeline]
        previous_years = [y for y in range(end_year - 9, end_year - 4) if y in timeline]

        recent_count = sum(timeline[y] for y in recent_years)
        previous_count = sum(timeline[y] for y in previous_years)

        growth_rate = (recent_count - previous_count) / previous_count if previous_count > 0 else 1.0 if recent_count > 0 else 0.0

        # Determine status
        status = self._determine_status(growth_rate, recent_count, peak_year, end_year)

        return GenreTrend(
            genre=name,
            timeline=dict(timeline),
            peak_year=peak_year,
            peak_count=peak_count,
            total_releases=total_releases,
            growth_rate=growth_rate,
            status=status,
        )

    def _determine_status(
        self,
        growth_rate: float,
        recent_count: int,
        peak_year: int,  # noqa: ARG002
        current_year: int,  # noqa: ARG002
    ) -> str:
        """Determine the current status of a genre/style.

        Args:
            growth_rate: Recent growth rate
            recent_count: Recent release count
            peak_year: Year of peak popularity
            current_year: Current year

        Returns:
            Status string
        """
        # Emerging: high growth rate, low volume
        if growth_rate > 0.5 and recent_count < 100:
            return "emerging"

        # Growing: positive growth, not at peak recently
        if growth_rate > 0.2:
            return "growing"

        # Declining: negative growth
        if growth_rate < -0.2:
            return "declining"

        # Stable: steady state
        return "stable"

    async def analyze_genre_crossover(
        self,
        start_year: int = 1950,
        end_year: int = 2024,
        min_cooccurrence: int = 10,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Analyze genre cross-pollination (releases with multiple genres).

        Args:
            start_year: Start year
            end_year: End year
            min_cooccurrence: Minimum co-occurrences to include

        Returns:
            Dictionary of genre pairs and their co-occurrence data
        """
        logger.info("📊 Analyzing genre crossover patterns...")

        async with self.driver.session() as session:
            # Get releases with multiple genres
            result = await session.run(
                """
                MATCH (r:Release)-[:IS]->(g1:Genre)
                MATCH (r)-[:IS]->(g2:Genre)
                WHERE r.year >= $start_year AND r.year <= $end_year
                  AND g1.name < g2.name
                WITH g1.name AS genre1, g2.name AS genre2,
                     count(DISTINCT r) AS count,
                     collect(DISTINCT r.year) AS years
                WHERE count >= $min_cooccurrence
                RETURN genre1, genre2, count, years
                ORDER BY count DESC
                """,
                start_year=start_year,
                end_year=end_year,
                min_cooccurrence=min_cooccurrence,
            )

            crossover_data = {}

            async for record in result:
                genre1 = record["genre1"]
                genre2 = record["genre2"]
                count = record["count"]
                years = record["years"]

                # Calculate year range
                year_range = (min(years), max(years)) if years else (0, 0)

                crossover_data[(genre1, genre2)] = {
                    "count": count,
                    "year_range": year_range,
                    "years": sorted(years),
                    "strength": count / min_cooccurrence,  # Normalized strength
                }

                self.genre_cooccurrence[(genre1, genre2)] = count

        logger.info("✅ Analyzed genre crossover", pairs=len(crossover_data))

        return crossover_data

    async def get_decade_summary(
        self,
        decade: int,
    ) -> dict[str, Any]:
        """Get summary of genres/styles for a specific decade.

        Args:
            decade: Decade year (e.g., 1980, 1990)

        Returns:
            Summary of the decade's musical landscape
        """
        logger.info(f"📊 Analyzing decade {decade}s...")

        start_year = decade
        end_year = decade + 9

        async with self.driver.session() as session:
            # Top genres of the decade
            genre_result = await session.run(
                """
                MATCH (r:Release)-[:IS]->(g:Genre)
                WHERE r.year >= $start_year AND r.year <= $end_year
                RETURN g.name AS genre, count(*) AS count
                ORDER BY count DESC
                LIMIT 10
                """,
                start_year=start_year,
                end_year=end_year,
            )

            top_genres = []
            async for record in genre_result:
                top_genres.append(
                    {
                        "genre": record["genre"],
                        "count": record["count"],
                    }
                )

            # Top styles of the decade
            style_result = await session.run(
                """
                MATCH (r:Release)-[:IS]->(s:Style)
                WHERE r.year >= $start_year AND r.year <= $end_year
                RETURN s.name AS style, count(*) AS count
                ORDER BY count DESC
                LIMIT 10
                """,
                start_year=start_year,
                end_year=end_year,
            )

            top_styles = []
            async for record in style_result:
                top_styles.append(
                    {
                        "style": record["style"],
                        "count": record["count"],
                    }
                )

            # Most active labels
            label_result = await session.run(
                """
                MATCH (r:Release)-[:ON]->(l:Label)
                WHERE r.year >= $start_year AND r.year <= $end_year
                RETURN l.name AS label, count(*) AS count
                ORDER BY count DESC
                LIMIT 10
                """,
                start_year=start_year,
                end_year=end_year,
            )

            top_labels = []
            async for record in label_result:
                top_labels.append(
                    {
                        "label": record["label"],
                        "count": record["count"],
                    }
                )

        return {
            "decade": f"{decade}s",
            "year_range": (start_year, end_year),
            "top_genres": top_genres,
            "top_styles": top_styles,
            "top_labels": top_labels,
        }

    async def find_emerging_genres(
        self,
        min_growth_rate: float = 1.0,
        min_recent_releases: int = 20,
    ) -> list[dict[str, Any]]:
        """Find genres that are currently emerging.

        Args:
            min_growth_rate: Minimum growth rate to be considered emerging
            min_recent_releases: Minimum recent releases

        Returns:
            List of emerging genres with trend data
        """
        if not self.genre_timelines:
            await self.analyze_genre_timeline()

        emerging = []

        for genre, timeline in self.genre_timelines.items():
            trend = self._analyze_trend(genre, timeline, 1950, 2024)

            # Check if recent releases meet minimum
            recent_years = [y for y in range(2020, 2025) if y in timeline]
            recent_count = sum(timeline[y] for y in recent_years)

            if trend.growth_rate >= min_growth_rate and recent_count >= min_recent_releases:
                emerging.append(
                    {
                        "genre": genre,
                        "growth_rate": trend.growth_rate,
                        "recent_releases": recent_count,
                        "status": trend.status,
                        "peak_year": trend.peak_year,
                    }
                )

        # Sort by growth rate
        emerging.sort(key=lambda x: float(x["growth_rate"]), reverse=True)  # type: ignore[arg-type]

        logger.info("✅ Found emerging genres", count=len(emerging))

        return emerging

    async def compare_decades(
        self,
        decade1: int,
        decade2: int,
    ) -> dict[str, Any]:
        """Compare musical landscape between two decades.

        Args:
            decade1: First decade
            decade2: Second decade

        Returns:
            Comparison data
        """
        logger.info(f"📊 Comparing {decade1}s vs {decade2}s...")

        summary1 = await self.get_decade_summary(decade1)
        summary2 = await self.get_decade_summary(decade2)

        # Find common genres
        genres1 = {g["genre"] for g in summary1["top_genres"]}
        genres2 = {g["genre"] for g in summary2["top_genres"]}

        common_genres = genres1 & genres2
        new_genres = genres2 - genres1
        disappeared_genres = genres1 - genres2

        return {
            "decade1": summary1,
            "decade2": summary2,
            "common_genres": list(common_genres),
            "new_genres": list(new_genres),
            "disappeared_genres": list(disappeared_genres),
            "genre_diversity_change": len(genres2) - len(genres1),
        }

    def get_genre_lifecycle(self, genre: str) -> dict[str, Any]:
        """Get the complete lifecycle of a genre.

        Args:
            genre: Genre name

        Returns:
            Lifecycle information
        """
        if genre not in self.genre_timelines:
            return {"genre": genre, "error": "Genre not found"}

        timeline = self.genre_timelines[genre]
        trend = self._analyze_trend(genre, timeline, 1950, 2024)

        # Find emergence year (first significant activity)
        emergence_year = min(timeline.keys()) if timeline else 0

        # Find decline start (if declining)
        decline_year = None
        if trend.status == "declining":
            # Find when it started declining (post-peak)
            years_sorted = sorted(timeline.items())
            peak_idx = next(i for i, (y, _) in enumerate(years_sorted) if y == trend.peak_year)

            for i in range(peak_idx + 1, len(years_sorted) - 1):
                curr_year, curr_count = years_sorted[i]
                _next_year, next_count = years_sorted[i + 1]

                if next_count < curr_count * 0.8:  # 20% drop
                    decline_year = curr_year
                    break

        return {
            "genre": genre,
            "emergence_year": emergence_year,
            "peak_year": trend.peak_year,
            "peak_count": trend.peak_count,
            "decline_year": decline_year,
            "current_status": trend.status,
            "total_releases": trend.total_releases,
            "growth_rate": trend.growth_rate,
            "timeline": timeline,
        }

    def export_evolution_data(self) -> dict[str, Any]:
        """Export all evolution data for visualization.

        Returns:
            Complete evolution dataset
        """
        return {
            "genre_timelines": self.genre_timelines,
            "style_timelines": self.style_timelines,
            "genre_cooccurrence": {f"{g1}_{g2}": count for (g1, g2), count in self.genre_cooccurrence.items()},
        }
