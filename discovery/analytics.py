"""Music Industry Analytics & Insights engine for trend analysis."""

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import structlog
from common import get_config
from neo4j import AsyncDriver, AsyncGraphDatabase
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine


logger = structlog.get_logger(__name__)


def convert_numpy_to_json_serializable(obj: Any) -> Any:
    """Convert numpy arrays and other non-serializable objects to JSON-serializable format."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer | np.floating):
        return obj.item()
    elif isinstance(obj, dict):
        return {key: convert_numpy_to_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_to_json_serializable(item) for item in obj]
    return obj


class AnalyticsRequest(BaseModel):
    """Request model for analytics queries."""

    analysis_type: str  # genre_trends, artist_evolution, label_insights, market_analysis
    time_range: tuple[int, int] | None = None  # (start_year, end_year)
    genre: str | None = None
    artist_name: str | None = None
    label_name: str | None = None
    limit: int = 20


class AnalyticsResult(BaseModel):
    """Result model for analytics data."""

    chart_type: str  # line, bar, pie, scatter, heatmap
    chart_data: dict[str, Any]  # Plotly chart configuration
    insights: list[str]  # Key insights from the analysis
    metadata: dict[str, Any]  # Additional metadata


class MusicAnalytics:
    """Music industry analytics and insights engine."""

    def __init__(self) -> None:
        self.config = get_config()
        self.neo4j_driver: AsyncDriver | None = None
        self.postgres_engine: Any | None = None

    async def initialize(self) -> None:
        """Initialize analytics engine with database connections."""
        logger.info("📊 Initializing analytics engine...")

        # Initialize Neo4j connection
        self.neo4j_driver = AsyncGraphDatabase.driver(self.config.neo4j_address, auth=(self.config.neo4j_username, self.config.neo4j_password))

        # Initialize PostgreSQL connection
        postgres_url = f"postgresql+asyncpg://{self.config.postgres_username}:{self.config.postgres_password}@{self.config.postgres_address}/{self.config.postgres_database}"
        self.postgres_engine = create_async_engine(postgres_url)

        logger.info("✅ Music Industry Analytics Engine initialized")

    async def analyze_genre_trends(self, time_range: tuple[int, int] | None = None) -> AnalyticsResult:
        """Analyze genre popularity trends over time."""
        logger.info("🎵 Analyzing genre trends over time...")

        assert self.neo4j_driver is not None, "Neo4j driver must be initialized"  # nosec B101
        # Default to last 30 years if no range specified
        current_year = datetime.now().year
        start_year, end_year = time_range or (current_year - 30, current_year)

        async with self.neo4j_driver.session() as session:
            result = await session.run(
                """
                MATCH (r:Release)-[:IS]->(g:Genre)
                WHERE r.year >= $start_year AND r.year <= $end_year
                WITH g.name as genre, r.year as year, count(r) as releases
                RETURN genre, year, releases
                ORDER BY year, releases DESC
            """,
                start_year=start_year,
                end_year=end_year,
            )

            data = []
            async for record in result:
                data.append(
                    {
                        "genre": record["genre"],
                        "year": record["year"],
                        "releases": record["releases"],
                    }
                )

        if not data:
            return AnalyticsResult(
                chart_type="line",
                chart_data={},
                insights=["No genre data available for the specified time range"],
                metadata={"time_range": (start_year, end_year)},
            )

        # Create DataFrame for analysis
        df = pd.DataFrame(data)

        # Get top genres by total releases
        top_genres = df.groupby("genre")["releases"].sum().nlargest(10).index.tolist()
        df_top = df[df["genre"].isin(top_genres)]

        # Create interactive line chart
        fig = px.line(
            df_top,
            x="year",
            y="releases",
            color="genre",
            title=f"Genre Popularity Trends ({start_year}-{end_year})",
            labels={"releases": "Number of Releases", "year": "Year"},
            hover_data=["genre", "releases"],
        )

        fig.update_layout(
            hovermode="x unified",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        )

        # Generate insights
        insights = []

        # Most popular genre overall
        most_popular = df.groupby("genre")["releases"].sum().idxmax()
        total_releases = df.groupby("genre")["releases"].sum().max()
        insights.append(f"Most popular genre overall: {most_popular} with {total_releases:,} releases")

        # Fastest growing genre (last 5 years vs previous 5 years)
        recent_years = df[df["year"] >= end_year - 5].groupby("genre")["releases"].sum()
        earlier_years = df[(df["year"] >= end_year - 10) & (df["year"] < end_year - 5)].groupby("genre")["releases"].sum()

        growth_rates = {}
        for genre in recent_years.index:
            if genre in earlier_years.index and earlier_years[genre] > 0:
                growth_rate = ((recent_years[genre] - earlier_years[genre]) / earlier_years[genre]) * 100
                growth_rates[genre] = growth_rate

        if growth_rates:
            fastest_growing = max(growth_rates, key=lambda x: growth_rates[x])
            growth_rate = growth_rates[fastest_growing]
            insights.append(f"Fastest growing genre (last 5 years): {fastest_growing} (+{growth_rate:.1f}%)")

        # Peak year for music releases
        yearly_totals = df.groupby("year")["releases"].sum()
        peak_year = yearly_totals.idxmax()
        peak_releases = yearly_totals.max()
        insights.append(f"Peak music release year: {peak_year} with {peak_releases:,} total releases")

        return AnalyticsResult(
            chart_type="line",
            chart_data=convert_numpy_to_json_serializable(fig.to_dict()),
            insights=insights,
            metadata={
                "time_range": (start_year, end_year),
                "top_genres": top_genres,
                "total_records": len(data),
            },
        )

    async def analyze_artist_evolution(self, artist_name: str) -> AnalyticsResult:
        """Analyze an artist's career evolution and collaboration patterns."""
        logger.info("🎤 Analyzing career evolution...", artist_name=artist_name)

        assert self.neo4j_driver is not None, "Neo4j driver must be initialized"  # nosec B101
        async with self.neo4j_driver.session() as session:
            # Get artist's releases over time with genres
            result = await session.run(
                """
                MATCH (a:Artist {name: $artist})<-[:BY]-(r:Release)
                OPTIONAL MATCH (r)-[:IS]->(g:Genre)
                OPTIONAL MATCH (r)-[:IS]->(s:Style)
                WITH r, collect(DISTINCT g.name) as genres, collect(DISTINCT s.name) as styles
                RETURN r.year as year,
                       r.title as title,
                       genres,
                       styles,
                       count(r) as releases
                ORDER BY year
            """,
                artist=artist_name,
            )

            releases_data = []
            async for record in result:
                releases_data.append(
                    {
                        "year": record["year"],
                        "title": record["title"],
                        "genres": record["genres"] or [],
                        "styles": record["styles"] or [],
                    }
                )

            # Get collaboration network
            collab_result = await session.run(
                """
                MATCH (a:Artist {name: $artist})<-[:BY]-(r:Release)-[:BY]->(other:Artist)
                WHERE other.name <> $artist
                RETURN other.name as collaborator, count(r) as collaborations
                ORDER BY collaborations DESC
                LIMIT 20
            """,
                artist=artist_name,
            )

            collaborators = []
            async for record in collab_result:
                collaborators.append({"name": record["collaborator"], "collaborations": record["collaborations"]})

        if not releases_data:
            return AnalyticsResult(
                chart_type="scatter",
                chart_data={},
                insights=[f"No release data found for artist: {artist_name}"],
                metadata={"artist": artist_name},
            )

        # Create timeline visualization
        df = pd.DataFrame(releases_data)

        # Extract all genres across career
        all_genres = set()
        for genres in df["genres"]:
            all_genres.update(genres)

        # Create genre evolution over time
        genre_timeline = []
        for _, row in df.iterrows():
            for genre in row["genres"]:
                genre_timeline.append({"year": row["year"], "genre": genre, "title": row["title"]})

        if genre_timeline:
            genre_df = pd.DataFrame(genre_timeline)

            # Create scatter plot showing genre evolution
            fig = px.scatter(
                genre_df,
                x="year",
                y="genre",
                title=f"{artist_name} - Musical Evolution Over Time",
                hover_data=["title"],
                size_max=15,
            )

            fig.update_traces(marker={"size": 12, "opacity": 0.7})
            fig.update_layout(yaxis_title="Musical Genres", xaxis_title="Year", height=600)
        else:
            fig = go.Figure()
            fig.add_annotation(
                text=f"No genre data available for {artist_name}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )

        # Generate insights
        insights = []

        if releases_data:
            career_span = max(r["year"] for r in releases_data if r["year"]) - min(r["year"] for r in releases_data if r["year"])
            insights.append(
                f"Career span: {career_span} years ({min(r['year'] for r in releases_data if r['year'])}-{max(r['year'] for r in releases_data if r['year'])})"
            )

            insights.append(f"Total releases analyzed: {len(releases_data)}")

            if all_genres:
                insights.append(f"Genres explored: {', '.join(sorted(all_genres))}")

        if collaborators:
            top_collaborator = collaborators[0]
            insights.append(f"Most frequent collaborator: {top_collaborator['name']} ({top_collaborator['collaborations']} releases)")
            insights.append(f"Total unique collaborators: {len(collaborators)}")

        return AnalyticsResult(
            chart_type="scatter",
            chart_data=convert_numpy_to_json_serializable(fig.to_dict()),
            insights=insights,
            metadata={
                "artist": artist_name,
                "career_span": career_span if releases_data else 0,
                "total_collaborators": len(collaborators),
            },
        )

    async def analyze_label_insights(self, label_name: str | None = None) -> AnalyticsResult:
        """Analyze record label market insights and artist rosters."""
        logger.info("🏢 Analyzing record label market insights...")

        assert self.neo4j_driver is not None, "Neo4j driver must be initialized"  # nosec B101
        async with self.neo4j_driver.session() as session:
            if label_name:
                # Specific label analysis
                result = await session.run(
                    """
                    MATCH (l:Label {name: $label})<-[:ON]-(r:Release)-[:BY]->(a:Artist)
                    OPTIONAL MATCH (r)-[:IS]->(g:Genre)
                    RETURN l.name as label,
                           a.name as artist,
                           r.year as year,
                           collect(DISTINCT g.name) as genres,
                           count(r) as releases
                    ORDER BY releases DESC
                """,
                    label=label_name,
                )

            else:
                # Market overview
                result = await session.run("""
                    MATCH (l:Label)<-[:ON]-(r:Release)
                    WITH l, count(r) as total_releases
                    WHERE total_releases > 50
                    MATCH (l)<-[:ON]-(r:Release)-[:BY]->(a:Artist)
                    RETURN l.name as label,
                           count(DISTINCT a) as artists,
                           count(r) as releases,
                           min(r.year) as first_release,
                           max(r.year) as last_release
                    ORDER BY releases DESC
                    LIMIT 20
                """)

            label_data = []
            async for record in result:
                label_data.append(
                    {
                        "label": record["label"],
                        "artists": record.get("artists", 0),
                        "releases": record["releases"],
                        "first_release": record.get("first_release"),
                        "last_release": record.get("last_release"),
                        "artist": record.get("artist", ""),
                        "year": record.get("year"),
                        "genres": record.get("genres", []),
                    }
                )

        if not label_data:
            return AnalyticsResult(
                chart_type="bar",
                chart_data={},
                insights=["No label data available"],
                metadata={"label": label_name},
            )

        df = pd.DataFrame(label_data)

        if label_name:
            # Artist roster for specific label
            fig = px.bar(
                df.head(15),
                x="releases",
                y="artist",
                orientation="h",
                title=f"{label_name} - Top Artists by Releases",
                labels={"releases": "Number of Releases", "artist": "Artist"},
            )

            insights = [
                f"Total artists on {label_name}: {df['artist'].nunique()}",
                f"Most prolific artist: {df.iloc[0]['artist']} ({df.iloc[0]['releases']} releases)",
                f"Total releases: {df['releases'].sum()}",
            ]
        else:
            # Market overview
            fig = px.bar(
                df.head(15),
                x="label",
                y="releases",
                title="Top Record Labels by Number of Releases",
                labels={"releases": "Number of Releases", "label": "Record Label"},
                hover_data=["artists"],
            )

            fig.update_xaxes(tickangle=45)

            insights = [
                f"Most prolific label: {df.iloc[0]['label']} ({df.iloc[0]['releases']} releases)",
                f"Average releases per top label: {df['releases'].mean():.0f}",
                f"Total labels analyzed: {len(df)}",
            ]

        return AnalyticsResult(
            chart_type="bar",
            chart_data=convert_numpy_to_json_serializable(fig.to_dict()),
            insights=insights,
            metadata={"label": label_name, "total_records": len(label_data)},
        )

    async def analyze_market_trends(self, analysis_focus: str = "format") -> AnalyticsResult:
        """Analyze music market trends and format adoption."""
        logger.info("📈 Analyzing market trends...", analysis_focus=analysis_focus)

        assert self.neo4j_driver is not None, "Neo4j driver must be initialized"  # nosec B101
        async with self.neo4j_driver.session() as session:
            if analysis_focus == "format":
                # Format adoption over time
                result = await session.run("""
                    MATCH (r:Release)
                    WHERE r.year >= 1950 AND r.year <= 2023
                    WITH r.year as year,
                         CASE
                           WHEN toLower(r.format) CONTAINS 'vinyl' OR toLower(r.format) CONTAINS 'lp' THEN 'Vinyl'
                           WHEN toLower(r.format) CONTAINS 'cd' THEN 'CD'
                           WHEN toLower(r.format) CONTAINS 'cassette' OR toLower(r.format) CONTAINS 'tape' THEN 'Cassette'
                           WHEN toLower(r.format) CONTAINS 'digital' OR toLower(r.format) CONTAINS 'file' THEN 'Digital'
                           ELSE 'Other'
                         END as format_type
                    RETURN year, format_type, count(r) as releases
                    ORDER BY year, format_type
                """)
            else:
                # Regional trends
                result = await session.run("""
                    MATCH (r:Release)
                    WHERE r.year >= 1980 AND r.country IS NOT NULL
                    WITH r.year as year, r.country as country, count(r) as releases
                    WHERE releases > 10
                    RETURN year, country, releases
                    ORDER BY year, releases DESC
                """)

            market_data = []
            async for record in result:
                market_data.append(
                    {
                        "year": record["year"],
                        "category": record.get("format_type") or record.get("country"),
                        "releases": record["releases"],
                    }
                )

        if not market_data:
            return AnalyticsResult(
                chart_type="line",
                chart_data={},
                insights=["No market trend data available"],
                metadata={"focus": analysis_focus},
            )

        df = pd.DataFrame(market_data)

        # Create stacked area chart for format trends
        if analysis_focus == "format":
            # Get top categories
            top_categories = df.groupby("category")["releases"].sum().nlargest(6).index.tolist()
            df_filtered = df[df["category"].isin(top_categories)]

            fig = px.area(
                df_filtered,
                x="year",
                y="releases",
                color="category",
                title="Music Format Adoption Over Time",
                labels={"releases": "Number of Releases", "year": "Year", "category": "Format"},
            )
        else:
            # Regional trends
            top_countries = df.groupby("category")["releases"].sum().nlargest(8).index.tolist()
            df_filtered = df[df["category"].isin(top_countries)]

            fig = px.line(
                df_filtered,
                x="year",
                y="releases",
                color="category",
                title="Regional Music Production Trends",
                labels={"releases": "Number of Releases", "year": "Year", "category": "Country"},
            )

        fig.update_layout(
            hovermode="x unified",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        )

        # Generate insights
        insights = []

        if analysis_focus == "format":
            # Most popular format overall
            format_totals = df.groupby("category")["releases"].sum().sort_values(ascending=False)
            insights.append(f"Most popular format overall: {format_totals.index[0]} ({format_totals.iloc[0]:,} releases)")

            # Format transitions
            recent_data = df[df["year"] >= 2010].groupby("category")["releases"].sum()
            if "Digital" in recent_data.index:
                digital_share = (recent_data["Digital"] / recent_data.sum()) * 100
                insights.append(f"Digital format market share (2010+): {digital_share:.1f}%")
        else:
            # Regional insights
            country_totals = df.groupby("category")["releases"].sum().sort_values(ascending=False)
            insights.append(f"Most productive region: {country_totals.index[0]} ({country_totals.iloc[0]:,} releases)")

        return AnalyticsResult(
            chart_type="area" if analysis_focus == "format" else "line",
            chart_data=convert_numpy_to_json_serializable(fig.to_dict()),
            insights=insights,
            metadata={"focus": analysis_focus, "total_records": len(market_data)},
        )

    async def close(self) -> None:
        """Close database connections."""
        if self.neo4j_driver:
            await self.neo4j_driver.close()
        if self.postgres_engine:
            await self.postgres_engine.dispose()


# Global analytics instance - initialized lazily
analytics: MusicAnalytics | None = None


def get_analytics_instance() -> MusicAnalytics:
    """Get or create the global analytics instance."""
    global analytics
    if analytics is None:
        analytics = MusicAnalytics()
    return analytics


async def get_analytics(request: AnalyticsRequest) -> AnalyticsResult:
    """Get analytics based on request type."""
    analytics_instance = get_analytics_instance()

    if request.analysis_type == "genre_trends":
        return await analytics_instance.analyze_genre_trends(request.time_range)
    elif request.analysis_type == "artist_evolution" and request.artist_name:
        return await analytics_instance.analyze_artist_evolution(request.artist_name)
    elif request.analysis_type == "label_insights":
        return await analytics_instance.analyze_label_insights(request.label_name)
    elif request.analysis_type == "market_analysis":
        focus = "format"  # Could be made configurable
        return await analytics_instance.analyze_market_trends(focus)

    return AnalyticsResult(
        chart_type="bar",
        chart_data={},
        insights=["Invalid analysis type"],
        metadata={"request": request.model_dump()},
    )
