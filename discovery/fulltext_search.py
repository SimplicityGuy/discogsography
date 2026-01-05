"""Full-text search capabilities using PostgreSQL.

This module provides advanced full-text search functionality using PostgreSQL's
tsvector and tsquery for efficient text searching across artists, releases, and labels.
"""

from enum import Enum
from typing import Any

import structlog
from psycopg import AsyncConnection
from psycopg.rows import dict_row


logger = structlog.get_logger(__name__)


class SearchEntity(str, Enum):
    """Entity types that can be searched."""

    ARTIST = "artist"
    RELEASE = "release"
    LABEL = "label"
    MASTER = "master"
    ALL = "all"


class SearchOperator(str, Enum):
    """Full-text search operators."""

    AND = "and"  # All terms must match
    OR = "or"  # Any term can match
    PHRASE = "phrase"  # Exact phrase match
    PROXIMITY = "proximity"  # Terms within N words


class FullTextSearch:
    """Full-text search engine using PostgreSQL."""

    def __init__(self, db_conn: AsyncConnection) -> None:
        """Initialize full-text search.

        Args:
            db_conn: PostgreSQL async connection
        """
        self.db_conn = db_conn

    async def search(
        self,
        query: str,
        entity: SearchEntity = SearchEntity.ALL,
        operator: SearchOperator = SearchOperator.AND,
        limit: int = 50,
        offset: int = 0,
        rank_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Perform full-text search across entities.

        Args:
            query: Search query string
            entity: Entity type to search
            operator: Search operator to use
            limit: Maximum number of results
            offset: Number of results to skip
            rank_threshold: Minimum ranking score (0.0 to 1.0)

        Returns:
            List of search results with relevance scores
        """
        # Build tsquery from user input
        tsquery = self._build_tsquery(query, operator)

        if entity == SearchEntity.ALL:
            results = await self._search_all_entities(tsquery, limit, offset, rank_threshold)
        elif entity == SearchEntity.ARTIST:
            results = await self._search_artists(tsquery, limit, offset, rank_threshold)
        elif entity == SearchEntity.RELEASE:
            results = await self._search_releases(tsquery, limit, offset, rank_threshold)
        elif entity == SearchEntity.LABEL:
            results = await self._search_labels(tsquery, limit, offset, rank_threshold)
        else:  # SearchEntity.MASTER
            results = await self._search_masters(tsquery, limit, offset, rank_threshold)

        logger.info(
            "🔍 Full-text search completed",
            query=query,
            entity=entity,
            results=len(results),
        )

        return results

    def _build_tsquery(self, query: str, operator: SearchOperator) -> str:
        """Build PostgreSQL tsquery from user input.

        Args:
            query: User search query
            operator: Search operator

        Returns:
            Formatted tsquery string
        """
        # Clean and tokenize query
        terms = query.strip().split()

        if not terms:
            return ""

        if operator == SearchOperator.PHRASE:
            # Exact phrase: "term1 term2"
            return " <-> ".join(terms)

        elif operator == SearchOperator.AND:
            # All terms: term1 & term2
            return " & ".join(terms)

        elif operator == SearchOperator.OR:
            # Any term: term1 | term2
            return " | ".join(terms)

        else:  # SearchOperator.PROXIMITY
            # Terms within proximity: term1 <2> term2 (within 2 words)
            return " <2> ".join(terms)

    async def _search_artists(
        self,
        tsquery: str,
        limit: int,
        offset: int,
        rank_threshold: float,
    ) -> list[dict[str, Any]]:
        """Search artist names using full-text search.

        Args:
            tsquery: PostgreSQL tsquery
            limit: Result limit
            offset: Result offset
            rank_threshold: Minimum rank

        Returns:
            List of matching artists with scores
        """
        query = """
            SELECT
                id,
                name,
                ts_rank(to_tsvector('english', name), to_tsquery('english', %s)) AS rank,
                'artist' AS entity_type
            FROM artists
            WHERE to_tsvector('english', name) @@ to_tsquery('english', %s)
                AND ts_rank(to_tsvector('english', name), to_tsquery('english', %s)) > %s
            ORDER BY rank DESC, name
            LIMIT %s OFFSET %s
        """

        async with self.db_conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                query,
                (tsquery, tsquery, tsquery, rank_threshold, limit, offset),
            )
            results = await cursor.fetchall()

        return [dict(row) for row in results]

    async def _search_releases(
        self,
        tsquery: str,
        limit: int,
        offset: int,
        rank_threshold: float,
    ) -> list[dict[str, Any]]:
        """Search release titles using full-text search.

        Args:
            tsquery: PostgreSQL tsquery
            limit: Result limit
            offset: Result offset
            rank_threshold: Minimum rank

        Returns:
            List of matching releases with scores
        """
        query = """
            SELECT
                id,
                title,
                year,
                ts_rank(to_tsvector('english', title), to_tsquery('english', %s)) AS rank,
                'release' AS entity_type
            FROM releases
            WHERE to_tsvector('english', title) @@ to_tsquery('english', %s)
                AND ts_rank(to_tsvector('english', title), to_tsquery('english', %s)) > %s
            ORDER BY rank DESC, title
            LIMIT %s OFFSET %s
        """

        async with self.db_conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                query,
                (tsquery, tsquery, tsquery, rank_threshold, limit, offset),
            )
            results = await cursor.fetchall()

        return [dict(row) for row in results]

    async def _search_labels(
        self,
        tsquery: str,
        limit: int,
        offset: int,
        rank_threshold: float,
    ) -> list[dict[str, Any]]:
        """Search label names using full-text search.

        Args:
            tsquery: PostgreSQL tsquery
            limit: Result limit
            offset: Result offset
            rank_threshold: Minimum rank

        Returns:
            List of matching labels with scores
        """
        query = """
            SELECT
                id,
                name,
                ts_rank(to_tsvector('english', name), to_tsquery('english', %s)) AS rank,
                'label' AS entity_type
            FROM labels
            WHERE to_tsvector('english', name) @@ to_tsquery('english', %s)
                AND ts_rank(to_tsvector('english', name), to_tsquery('english', %s)) > %s
            ORDER BY rank DESC, name
            LIMIT %s OFFSET %s
        """

        async with self.db_conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                query,
                (tsquery, tsquery, tsquery, rank_threshold, limit, offset),
            )
            results = await cursor.fetchall()

        return [dict(row) for row in results]

    async def _search_masters(
        self,
        tsquery: str,
        limit: int,
        offset: int,
        rank_threshold: float,
    ) -> list[dict[str, Any]]:
        """Search master release titles using full-text search.

        Args:
            tsquery: PostgreSQL tsquery
            limit: Result limit
            offset: Result offset
            rank_threshold: Minimum rank

        Returns:
            List of matching masters with scores
        """
        query = """
            SELECT
                id,
                title,
                year,
                ts_rank(to_tsvector('english', title), to_tsquery('english', %s)) AS rank,
                'master' AS entity_type
            FROM masters
            WHERE to_tsvector('english', title) @@ to_tsquery('english', %s)
                AND ts_rank(to_tsvector('english', title), to_tsquery('english', %s)) > %s
            ORDER BY rank DESC, title
            LIMIT %s OFFSET %s
        """

        async with self.db_conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                query,
                (tsquery, tsquery, tsquery, rank_threshold, limit, offset),
            )
            results = await cursor.fetchall()

        return [dict(row) for row in results]

    async def _search_all_entities(
        self,
        tsquery: str,
        limit: int,
        offset: int,
        rank_threshold: float,
    ) -> list[dict[str, Any]]:
        """Search across all entity types.

        Args:
            tsquery: PostgreSQL tsquery
            limit: Result limit
            offset: Result offset
            rank_threshold: Minimum rank

        Returns:
            Combined list of results from all entities
        """
        # Search each entity type in parallel would be ideal, but for now we'll do it sequentially
        per_entity_limit = max(limit // 4, 10)  # Distribute limit across entity types

        artists = await self._search_artists(tsquery, per_entity_limit, 0, rank_threshold)
        releases = await self._search_releases(tsquery, per_entity_limit, 0, rank_threshold)
        labels = await self._search_labels(tsquery, per_entity_limit, 0, rank_threshold)
        masters = await self._search_masters(tsquery, per_entity_limit, 0, rank_threshold)

        # Combine and sort by rank
        all_results = artists + releases + labels + masters
        all_results.sort(key=lambda x: x["rank"], reverse=True)

        # Apply offset and limit to combined results
        return all_results[offset : offset + limit]

    async def suggest_completions(
        self,
        prefix: str,
        entity: SearchEntity = SearchEntity.ARTIST,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Suggest completions for a search prefix.

        Args:
            prefix: Search prefix
            entity: Entity type
            limit: Maximum number of suggestions

        Returns:
            List of completion suggestions
        """
        if entity == SearchEntity.ARTIST:
            table = "artists"
            column = "name"
        elif entity == SearchEntity.RELEASE:
            table = "releases"
            column = "title"
        elif entity == SearchEntity.LABEL:
            table = "labels"
            column = "name"
        elif entity == SearchEntity.MASTER:
            table = "masters"
            column = "title"
        else:
            # For ALL, default to artists
            table = "artists"
            column = "name"

        # Safe: table and column names are from enum mapping, values are parameterized
        query = f"""
            SELECT
                id,
                {column} AS name,
                '{entity.value}' AS entity_type
            FROM {table}
            WHERE LOWER({column}) LIKE LOWER(%s)
            ORDER BY {column}
            LIMIT %s
        """  # noqa: S608  # nosec: B608

        search_pattern = f"{prefix}%"

        async with self.db_conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, (search_pattern, limit))
            results = await cursor.fetchall()

        return [dict(row) for row in results]

    async def search_with_filters(
        self,
        query: str,
        entity: SearchEntity,
        filters: dict[str, Any],
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search with additional filters.

        Args:
            query: Search query
            entity: Entity type
            filters: Additional filters (e.g., year_range, genre, style)
            limit: Result limit
            offset: Result offset

        Returns:
            Filtered search results
        """
        tsquery = self._build_tsquery(query, SearchOperator.AND)

        if entity == SearchEntity.RELEASE:
            return await self._search_releases_with_filters(tsquery, filters, limit, offset)
        elif entity == SearchEntity.ARTIST:
            return await self._search_artists_with_filters(tsquery, filters, limit, offset)
        else:
            # Fallback to basic search
            return await self.search(query, entity, SearchOperator.AND, limit, offset)

    async def _search_releases_with_filters(
        self,
        tsquery: str,
        filters: dict[str, Any],
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Search releases with year and other filters.

        Args:
            tsquery: PostgreSQL tsquery
            filters: Filter criteria
            limit: Result limit
            offset: Result offset

        Returns:
            Filtered release results
        """
        conditions = ["to_tsvector('english', title) @@ to_tsquery('english', %s)"]
        params: list[Any] = [tsquery]

        # Year range filter
        if "year_min" in filters:
            conditions.append("year >= %s")
            params.append(filters["year_min"])

        if "year_max" in filters:
            conditions.append("year <= %s")
            params.append(filters["year_max"])

        where_clause = " AND ".join(conditions)

        # Safe: where_clause built from validated conditions, values are parameterized
        query = f"""
            SELECT
                id,
                title,
                year,
                ts_rank(to_tsvector('english', title), to_tsquery('english', %s)) AS rank,
                'release' AS entity_type
            FROM releases
            WHERE {where_clause}
            ORDER BY rank DESC, title
            LIMIT %s OFFSET %s
        """  # noqa: S608  # nosec: B608

        # Add tsquery for rank calculation
        params = [tsquery, *params, limit, offset]

        async with self.db_conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, params)
            results = await cursor.fetchall()

        return [dict(row) for row in results]

    async def _search_artists_with_filters(
        self,
        tsquery: str,
        filters: dict[str, Any],  # noqa: ARG002
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Search artists with additional filters (filters reserved for future use).

        Args:
            tsquery: PostgreSQL tsquery
            filters: Filter criteria
            limit: Result limit
            offset: Result offset

        Returns:
            Filtered artist results
        """
        # For now, just basic artist search
        # Could be extended with filters for genre, active years, etc.
        query = """
            SELECT
                id,
                name,
                ts_rank(to_tsvector('english', name), to_tsquery('english', %s)) AS rank,
                'artist' AS entity_type
            FROM artists
            WHERE to_tsvector('english', name) @@ to_tsquery('english', %s)
            ORDER BY rank DESC, name
            LIMIT %s OFFSET %s
        """

        async with self.db_conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(query, (tsquery, tsquery, limit, offset))
            results = await cursor.fetchall()

        return [dict(row) for row in results]

    async def get_search_statistics(self) -> dict[str, Any]:
        """Get statistics about searchable content.

        Returns:
            Dictionary with search statistics
        """
        stats = {}

        # Count each entity type
        for entity in [SearchEntity.ARTIST, SearchEntity.RELEASE, SearchEntity.LABEL, SearchEntity.MASTER]:
            if entity == SearchEntity.ARTIST:
                table = "artists"
            elif entity == SearchEntity.RELEASE:
                table = "releases"
            elif entity == SearchEntity.LABEL:
                table = "labels"
            elif entity == SearchEntity.MASTER:
                table = "masters"
            else:
                continue

            # Safe: table name from enum mapping
            query = f"SELECT COUNT(*) as count FROM {table}"  # noqa: S608  # nosec B608

            async with self.db_conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query)
                result = await cursor.fetchone()
                stats[entity.value] = result["count"] if result else 0

        stats["total_searchable"] = sum(stats.values())

        logger.info("📊 Search statistics", **stats)

        return stats
