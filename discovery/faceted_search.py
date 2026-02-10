"""Faceted search with dynamic filters.

This module provides faceted search capabilities allowing users to filter
search results by multiple dimensions (genres, years, labels, etc.) with
dynamic filter updates based on current results.
"""

from collections import Counter
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine
import structlog


logger = structlog.get_logger(__name__)


class FacetType:
    """Available facet types."""

    GENRE = "genre"
    STYLE = "style"
    LABEL = "label"
    YEAR = "year"
    DECADE = "decade"
    COUNTRY = "country"
    FORMAT = "format"


class FacetedSearchEngine:
    """Faceted search engine with dynamic filters."""

    def __init__(self, db_engine: AsyncEngine) -> None:
        """Initialize faceted search engine.

        Args:
            db_engine: PostgreSQL async engine (SQLAlchemy)
        """
        self.db_engine = db_engine
        self.facet_cache: dict[str, dict[str, Any]] = {}

    async def search_with_facets(
        self,
        query: str,
        entity_type: str = "artist",
        selected_facets: dict[str, list[str]] | None = None,
        facets_to_return: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Perform search with faceted filters.

        Args:
            query: Search query
            entity_type: Type of entity to search (artist, release, etc.)
            selected_facets: Dictionary of selected facet values
            facets_to_return: List of facets to compute and return
            limit: Result limit
            offset: Result offset

        Returns:
            Dictionary with search results and facet counts
        """
        selected_facets = selected_facets or {}
        facets_to_return = facets_to_return or [FacetType.GENRE, FacetType.STYLE, FacetType.YEAR]

        if entity_type == "artist":
            results, facets = await self._search_artists_with_facets(
                query,
                selected_facets,
                facets_to_return,
                limit,
                offset,
            )
        elif entity_type == "release":
            results, facets = await self._search_releases_with_facets(
                query,
                selected_facets,
                facets_to_return,
                limit,
                offset,
            )
        else:
            results, facets = [], {}

        logger.info(
            "🔍 Faceted search completed",
            query=query,
            entity=entity_type,
            results=len(results),
            facets=list(facets.keys()),
        )

        return {
            "results": results,
            "facets": facets,
            "total": len(results),
            "query": query,
            "selected_facets": selected_facets,
        }

    async def _search_artists_with_facets(
        self,
        query: str,
        selected_facets: dict[str, list[str]],
        facets_to_return: list[str],
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """Search artists with faceted filtering.

        Args:
            query: Search query
            selected_facets: Selected facet filters
            facets_to_return: Facets to compute
            limit: Result limit
            offset: Result offset

        Returns:
            Tuple of (results, facet_counts)
        """
        # Build WHERE conditions based on selected facets
        conditions = ["LOWER(a.name) LIKE LOWER(%s)"]
        params: list[Any] = [f"%{query}%"]

        # Join tables based on needed facets
        joins = []

        if FacetType.GENRE in selected_facets or FacetType.GENRE in facets_to_return:
            joins.append("LEFT JOIN artist_genres ag ON a.id = ag.artist_id")
            joins.append("LEFT JOIN genres g ON ag.genre_id = g.id")

            if FacetType.GENRE in selected_facets:
                genre_placeholders = ", ".join(["%s"] * len(selected_facets[FacetType.GENRE]))
                conditions.append(f"g.name IN ({genre_placeholders})")
                params.extend(selected_facets[FacetType.GENRE])

        if FacetType.STYLE in selected_facets or FacetType.STYLE in facets_to_return:
            joins.append("LEFT JOIN artist_styles ast ON a.id = ast.artist_id")
            joins.append("LEFT JOIN styles s ON ast.style_id = s.id")

            if FacetType.STYLE in selected_facets:
                style_placeholders = ", ".join(["%s"] * len(selected_facets[FacetType.STYLE]))
                conditions.append(f"s.name IN ({style_placeholders})")
                params.extend(selected_facets[FacetType.STYLE])

        if FacetType.LABEL in selected_facets or FacetType.LABEL in facets_to_return:
            joins.append("LEFT JOIN artist_labels al ON a.id = al.artist_id")
            joins.append("LEFT JOIN labels l ON al.label_id = l.id")

            if FacetType.LABEL in selected_facets:
                label_placeholders = ", ".join(["%s"] * len(selected_facets[FacetType.LABEL]))
                conditions.append(f"l.name IN ({label_placeholders})")
                params.extend(selected_facets[FacetType.LABEL])

        # Build query
        join_clause = " ".join(joins) if joins else ""
        where_clause = " AND ".join(conditions)

        # Safe: Dynamic SQL with parameterized values
        query_sql = f"""
            SELECT DISTINCT a.id, a.name
            FROM artists a
            {join_clause}
            WHERE {where_clause}
            ORDER BY a.name
            LIMIT %s OFFSET %s
        """  # noqa: S608  # nosec: B608

        params.extend([limit, offset])

        # Execute search
        async with self.db_engine.connect() as conn:
            result = await conn.execute(text(query_sql), params)
            results = [dict(row) for row in result.mappings().all()]

        # Compute facets for the results
        facets = await self._compute_facets_for_artists(
            results,
            facets_to_return,
        )

        return results, facets

    async def _search_releases_with_facets(
        self,
        query: str,
        selected_facets: dict[str, list[str]],
        facets_to_return: list[str],
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """Search releases with faceted filtering.

        Args:
            query: Search query
            selected_facets: Selected facet filters
            facets_to_return: Facets to compute
            limit: Result limit
            offset: Result offset

        Returns:
            Tuple of (results, facet_counts)
        """
        # Build WHERE conditions
        conditions = ["LOWER(r.title) LIKE LOWER(%s)"]
        params: list[Any] = [f"%{query}%"]

        # Add year filter
        if FacetType.YEAR in selected_facets:
            year_placeholders = ", ".join(["%s"] * len(selected_facets[FacetType.YEAR]))
            conditions.append(f"r.year IN ({year_placeholders})")
            params.extend(selected_facets[FacetType.YEAR])

        if FacetType.DECADE in selected_facets:
            decade_conditions = []
            for decade_str in selected_facets[FacetType.DECADE]:
                decade = int(decade_str)
                decade_conditions.append("(r.year >= %s AND r.year < %s)")
                params.extend([decade, decade + 10])

            if decade_conditions:
                conditions.append(f"({' OR '.join(decade_conditions)})")

        # Join for genre/style filters
        joins = []

        if FacetType.GENRE in selected_facets or FacetType.GENRE in facets_to_return:
            joins.append("LEFT JOIN release_genres rg ON r.id = rg.release_id")
            joins.append("LEFT JOIN genres g ON rg.genre_id = g.id")

            if FacetType.GENRE in selected_facets:
                genre_placeholders = ", ".join(["%s"] * len(selected_facets[FacetType.GENRE]))
                conditions.append(f"g.name IN ({genre_placeholders})")
                params.extend(selected_facets[FacetType.GENRE])

        if FacetType.STYLE in selected_facets or FacetType.STYLE in facets_to_return:
            joins.append("LEFT JOIN release_styles rs ON r.id = rs.release_id")
            joins.append("LEFT JOIN styles s ON rs.style_id = s.id")

            if FacetType.STYLE in selected_facets:
                style_placeholders = ", ".join(["%s"] * len(selected_facets[FacetType.STYLE]))
                conditions.append(f"s.name IN ({style_placeholders})")
                params.extend(selected_facets[FacetType.STYLE])

        # Build query
        join_clause = " ".join(joins) if joins else ""
        where_clause = " AND ".join(conditions)

        # Safe: Dynamic SQL with parameterized values
        query_sql = f"""
            SELECT DISTINCT r.id, r.title, r.year
            FROM releases r
            {join_clause}
            WHERE {where_clause}
            ORDER BY r.year DESC, r.title
            LIMIT %s OFFSET %s
        """  # noqa: S608  # nosec: B608

        params.extend([limit, offset])

        # Execute search
        async with self.db_engine.connect() as conn:
            result = await conn.execute(text(query_sql), params)
            results = [dict(row) for row in result.mappings().all()]

        # Compute facets
        facets = await self._compute_facets_for_releases(
            results,
            facets_to_return,
        )

        return results, facets

    async def _compute_facets_for_artists(
        self,
        artists: list[dict[str, Any]],
        facets_to_compute: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Compute facet counts for artist results.

        Args:
            artists: List of artist results
            facets_to_compute: List of facets to compute

        Returns:
            Dictionary of facet counts
        """
        if not artists:
            return {}

        facets: dict[str, list[dict[str, Any]]] = {}
        artist_ids = [a["id"] for a in artists]

        # Genre facet
        if FacetType.GENRE in facets_to_compute:
            genre_counts = await self._get_genre_counts_for_artists(artist_ids)
            facets[FacetType.GENRE] = [{"value": genre, "count": count} for genre, count in genre_counts.most_common(20)]

        # Style facet
        if FacetType.STYLE in facets_to_compute:
            style_counts = await self._get_style_counts_for_artists(artist_ids)
            facets[FacetType.STYLE] = [{"value": style, "count": count} for style, count in style_counts.most_common(20)]

        # Label facet
        if FacetType.LABEL in facets_to_compute:
            label_counts = await self._get_label_counts_for_artists(artist_ids)
            facets[FacetType.LABEL] = [{"value": label, "count": count} for label, count in label_counts.most_common(20)]

        return facets

    async def _compute_facets_for_releases(
        self,
        releases: list[dict[str, Any]],
        facets_to_compute: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Compute facet counts for release results.

        Args:
            releases: List of release results
            facets_to_compute: List of facets to compute

        Returns:
            Dictionary of facet counts
        """
        if not releases:
            return {}

        facets: dict[str, list[dict[str, Any]]] = {}
        release_ids = [r["id"] for r in releases]

        # Year facet
        if FacetType.YEAR in facets_to_compute:
            year_counts = Counter(r["year"] for r in releases if r.get("year"))
            facets[FacetType.YEAR] = [{"value": str(year), "count": count} for year, count in sorted(year_counts.items(), reverse=True)]

        # Decade facet
        if FacetType.DECADE in facets_to_compute:
            decade_counts: Counter[int] = Counter()
            for r in releases:
                if r.get("year"):
                    decade = (r["year"] // 10) * 10
                    decade_counts[decade] += 1

            facets[FacetType.DECADE] = [{"value": f"{decade}s", "count": count} for decade, count in sorted(decade_counts.items(), reverse=True)]

        # Genre facet
        if FacetType.GENRE in facets_to_compute:
            genre_counts = await self._get_genre_counts_for_releases(release_ids)
            facets[FacetType.GENRE] = [{"value": genre, "count": count} for genre, count in genre_counts.most_common(20)]

        # Style facet
        if FacetType.STYLE in facets_to_compute:
            style_counts = await self._get_style_counts_for_releases(release_ids)
            facets[FacetType.STYLE] = [{"value": style, "count": count} for style, count in style_counts.most_common(20)]

        return facets

    async def _get_genre_counts_for_artists(self, artist_ids: list[int]) -> Counter[str]:
        """Get genre counts for artists.

        Args:
            artist_ids: List of artist IDs

        Returns:
            Counter of genre names
        """
        if not artist_ids:
            return Counter()

        query = text("""
            SELECT g.name, COUNT(DISTINCT ag.artist_id) as count
            FROM artist_genres ag
            JOIN genres g ON ag.genre_id = g.id
            WHERE ag.artist_id IN :artist_ids
            GROUP BY g.name
        """).bindparams(bindparam("artist_ids", expanding=True))

        async with self.db_engine.connect() as conn:
            result = await conn.execute(query, {"artist_ids": artist_ids})
            rows = result.mappings().all()

        return Counter({row["name"]: row["count"] for row in rows})

    async def _get_style_counts_for_artists(self, artist_ids: list[int]) -> Counter[str]:
        """Get style counts for artists.

        Args:
            artist_ids: List of artist IDs

        Returns:
            Counter of style names
        """
        if not artist_ids:
            return Counter()

        query = text("""
            SELECT s.name, COUNT(DISTINCT ast.artist_id) as count
            FROM artist_styles ast
            JOIN styles s ON ast.style_id = s.id
            WHERE ast.artist_id IN :artist_ids
            GROUP BY s.name
        """).bindparams(bindparam("artist_ids", expanding=True))

        async with self.db_engine.connect() as conn:
            result = await conn.execute(query, {"artist_ids": artist_ids})
            rows = result.mappings().all()

        return Counter({row["name"]: row["count"] for row in rows})

    async def _get_label_counts_for_artists(self, artist_ids: list[int]) -> Counter[str]:
        """Get label counts for artists.

        Args:
            artist_ids: List of artist IDs

        Returns:
            Counter of label names
        """
        if not artist_ids:
            return Counter()

        query = text("""
            SELECT l.name, COUNT(DISTINCT al.artist_id) as count
            FROM artist_labels al
            JOIN labels l ON al.label_id = l.id
            WHERE al.artist_id IN :artist_ids
            GROUP BY l.name
        """).bindparams(bindparam("artist_ids", expanding=True))

        async with self.db_engine.connect() as conn:
            result = await conn.execute(query, {"artist_ids": artist_ids})
            rows = result.mappings().all()

        return Counter({row["name"]: row["count"] for row in rows})

    async def _get_genre_counts_for_releases(self, release_ids: list[int]) -> Counter[str]:
        """Get genre counts for releases.

        Args:
            release_ids: List of release IDs

        Returns:
            Counter of genre names
        """
        if not release_ids:
            return Counter()

        query = text("""
            SELECT g.name, COUNT(DISTINCT rg.release_id) as count
            FROM release_genres rg
            JOIN genres g ON rg.genre_id = g.id
            WHERE rg.release_id IN :release_ids
            GROUP BY g.name
        """).bindparams(bindparam("release_ids", expanding=True))

        async with self.db_engine.connect() as conn:
            result = await conn.execute(query, {"release_ids": release_ids})
            rows = result.mappings().all()

        return Counter({row["name"]: row["count"] for row in rows})

    async def _get_style_counts_for_releases(self, release_ids: list[int]) -> Counter[str]:
        """Get style counts for releases.

        Args:
            release_ids: List of release IDs

        Returns:
            Counter of style names
        """
        if not release_ids:
            return Counter()

        query = text("""
            SELECT s.name, COUNT(DISTINCT rs.release_id) as count
            FROM release_styles rs
            JOIN styles s ON rs.style_id = s.id
            WHERE rs.release_id IN :release_ids
            GROUP BY s.name
        """).bindparams(bindparam("release_ids", expanding=True))

        async with self.db_engine.connect() as conn:
            result = await conn.execute(query, {"release_ids": release_ids})
            rows = result.mappings().all()

        return Counter({row["name"]: row["count"] for row in rows})

    async def get_available_facets(self, entity_type: str = "artist") -> dict[str, list[str]]:
        """Get all available facet values for an entity type.

        Args:
            entity_type: Entity type (artist or release)

        Returns:
            Dictionary of available facet values
        """
        facets: dict[str, list[str]] = {}

        if entity_type == "artist":
            # Get all genres
            async with self.db_engine.connect() as conn:
                result = await conn.execute(text("SELECT DISTINCT name FROM genres ORDER BY name"))
                facets[FacetType.GENRE] = [row["name"] for row in result.mappings().all()]

                result = await conn.execute(text("SELECT DISTINCT name FROM styles ORDER BY name"))
                facets[FacetType.STYLE] = [row["name"] for row in result.mappings().all()]

                result = await conn.execute(text("SELECT DISTINCT name FROM labels ORDER BY name LIMIT 100"))
                facets[FacetType.LABEL] = [row["name"] for row in result.mappings().all()]

        elif entity_type == "release":
            async with self.db_engine.connect() as conn:
                result = await conn.execute(text("SELECT DISTINCT year FROM releases WHERE year IS NOT NULL ORDER BY year DESC"))
                facets[FacetType.YEAR] = [str(row["year"]) for row in result.mappings().all()]

        logger.info("📊 Retrieved available facets", entity=entity_type, facets=list(facets.keys()))

        return facets
