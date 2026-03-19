"""E2E browser tests for the Explore service UI."""

import re

from playwright.sync_api import Page, expect
import pytest


def _switch_pane(page: Page, pane: str) -> None:
    """Click a nav-link to switch panes, retrying if Firefox drops the click.

    Firefox in CI occasionally acknowledges the Playwright click but does not
    dispatch it to the JS handler, leaving the target pane without the
    ``active`` class.  We detect this and retry once before giving up.
    """
    link = page.locator(f"[data-pane='{pane}']")
    target = page.locator(f"#{pane}Pane")

    link.click()
    try:
        expect(target).to_have_class(re.compile(r"\bactive\b"), timeout=2000)
    except AssertionError:
        # Retry — the first click was swallowed
        link.click()
        expect(target).to_have_class(re.compile(r"\bactive\b"), timeout=5000)


def _goto_ready(page: Page, url: str) -> None:
    """Navigate to the explore page and wait for the JS app to initialise.

    Firefox can resolve ``domcontentloaded`` before all DOMContentLoaded
    listeners have finished, so we additionally wait for the ExploreApp
    instance (which binds all click handlers) to exist on ``window``.
    We also wait for Alpine.js to finish initialising ``x-data`` components
    since the search-type dropdown relies on Alpine reactivity.
    """
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_function("() => !!window.exploreApp", timeout=10000)
    page.wait_for_function(
        "() => typeof Alpine !== 'undefined' && Alpine.version !== undefined",
        timeout=10000,
    )


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreUI:
    """End-to-end tests for the Explore service web interface."""

    def test_page_loads(self, page: Page, test_server: str) -> None:
        """Test that the explore page loads successfully."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        expect(page).to_have_title(re.compile("Explore", re.IGNORECASE))

    def test_navbar_visible(self, page: Page, test_server: str) -> None:
        """Test that the navigation bar is visible."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)

        navbar = page.locator("nav").first
        expect(navbar).to_be_visible(timeout=5000)

    def test_search_input_visible(self, page: Page, test_server: str) -> None:
        """Test that the search input is visible."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)

        search_input = page.locator("#searchInput")
        expect(search_input).to_be_visible(timeout=5000)

    def test_search_type_dropdown(self, page: Page, test_server: str) -> None:
        """Test the search type dropdown works."""
        _goto_ready(page, test_server)

        # Find the search type button
        type_btn = page.locator("#searchTypeBtn")
        expect(type_btn).to_be_visible(timeout=5000)
        expect(type_btn).to_have_text("Artist")

    def test_pane_switching(self, page: Page, test_server: str) -> None:
        """Test switching between Explore and Trends panes."""
        _goto_ready(page, test_server)

        # Explore pane should be active by default
        explore_pane = page.locator("#explorePane")
        expect(explore_pane).to_have_class(re.compile("active"), timeout=5000)

        # Click Trends tab
        trends_link = page.locator("[data-pane='trends']")
        trends_link.click()

        # Trends pane should now be active
        trends_pane = page.locator("#trendsPane")
        expect(trends_pane).to_have_class(re.compile("active"), timeout=5000)

        # Click Explore tab again
        explore_link = page.locator("[data-pane='explore']")
        explore_link.click()
        expect(explore_pane).to_have_class(re.compile("active"), timeout=5000)

    def test_graph_placeholder_visible(self, page: Page, test_server: str) -> None:
        """Test that the graph placeholder is shown before search."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)

        placeholder = page.locator("#graphPlaceholder")
        expect(placeholder).to_be_visible(timeout=5000)

    def test_health_endpoint(self, page: Page, test_server: str) -> None:
        """Test the health API endpoint from browser."""
        response = page.request.get(f"{test_server}/health")
        assert response.ok
        data = response.json()
        assert data["service"] == "explore"
        assert data["status"] == "healthy"

    def test_responsive_layout(self, page: Page, test_server: str) -> None:
        """Test that the page responds to viewport changes."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)

        # Desktop viewport
        page.set_viewport_size({"width": 1280, "height": 720})
        search_input = page.locator("#searchInput")
        expect(search_input).to_be_visible(timeout=5000)

        # Mobile viewport
        page.set_viewport_size({"width": 375, "height": 667})
        expect(search_input).to_be_visible(timeout=5000)

    def test_info_panel_hidden_by_default(self, page: Page, test_server: str) -> None:
        """Test that the info panel is hidden before any node is clicked."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)

        info_panel = page.locator("#infoPanel")
        # The panel exists but should not have the 'open' class
        expect(info_panel).not_to_have_class(re.compile("open"), timeout=5000)


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreAPIEndpoints:
    """E2E tests for Explore API endpoints."""

    def test_autocomplete_artist_endpoint(self, page: Page, test_server: str) -> None:
        """Test the autocomplete API returns artist results."""
        response = page.request.get(f"{test_server}/api/autocomplete?q=radio&type=artist")
        assert response.ok
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_autocomplete_genre_endpoint(self, page: Page, test_server: str) -> None:
        """Test the autocomplete API returns genre results."""
        response = page.request.get(f"{test_server}/api/autocomplete?q=rock&type=genre")
        assert response.ok
        data = response.json()
        assert "results" in data

    def test_autocomplete_label_endpoint(self, page: Page, test_server: str) -> None:
        """Test the autocomplete API returns label results."""
        response = page.request.get(f"{test_server}/api/autocomplete?q=warp&type=label")
        assert response.ok
        data = response.json()
        assert "results" in data

    def test_explore_artist_endpoint(self, page: Page, test_server: str) -> None:
        """Test the explore API returns artist graph data."""
        response = page.request.get(f"{test_server}/api/explore?name=Radiohead&type=artist")
        assert response.ok
        data = response.json()
        assert "center" in data
        assert "categories" in data
        assert data["center"]["type"] == "artist"
        assert len(data["categories"]) == 3  # releases, labels, aliases

    def test_explore_genre_endpoint(self, page: Page, test_server: str) -> None:
        """Test the explore API returns genre graph data."""
        response = page.request.get(f"{test_server}/api/explore?name=Rock&type=genre")
        assert response.ok
        data = response.json()
        assert data["center"]["type"] == "genre"
        assert len(data["categories"]) == 4  # releases, artists, labels, styles

    def test_explore_label_endpoint(self, page: Page, test_server: str) -> None:
        """Test the explore API returns label graph data."""
        response = page.request.get(f"{test_server}/api/explore?name=Warp%20Records&type=label")
        assert response.ok
        data = response.json()
        assert data["center"]["type"] == "label"
        assert len(data["categories"]) == 3  # releases, artists, genres

    def test_expand_endpoint(self, page: Page, test_server: str) -> None:
        """Test the expand API returns child nodes."""
        response = page.request.get(f"{test_server}/api/expand?node_id=Radiohead&type=artist&category=releases")
        assert response.ok
        data = response.json()
        assert "children" in data
        assert isinstance(data["children"], list)
        assert len(data["children"]) > 0

    def test_node_details_endpoint(self, page: Page, test_server: str) -> None:
        """Test the node details API returns full node info."""
        response = page.request.get(f"{test_server}/api/node/1?type=artist")
        assert response.ok
        data = response.json()
        assert "name" in data
        assert "genres" in data
        assert isinstance(data["genres"], list)

    def test_trends_endpoint(self, page: Page, test_server: str) -> None:
        """Test the trends API returns time-series data."""
        response = page.request.get(f"{test_server}/api/trends?name=Radiohead&type=artist")
        assert response.ok
        data = response.json()
        assert data["name"] == "Radiohead"
        assert data["type"] == "artist"
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0
        # Verify time-series structure
        assert "year" in data["data"][0]
        assert "count" in data["data"][0]


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreSearchInteraction:
    """E2E tests for search interaction and autocomplete UI."""

    @staticmethod
    def _open_dropdown_and_select(page: Page, data_type: str) -> None:
        """Click the search-type button and select an item from the dropdown.

        Firefox occasionally fires ``@click.outside`` on the same tick as the
        button click, which closes the Alpine.js dropdown before Playwright
        can observe it.  We retry the click once if the item isn't visible.
        """
        btn = page.locator("#searchTypeBtn")
        item = page.locator(f"[data-type='{data_type}']")

        btn.click()
        try:
            expect(item).to_be_visible(timeout=2000)
        except AssertionError:
            # Dropdown closed immediately — retry
            btn.click()
            expect(item).to_be_visible(timeout=5000)
        item.click()

    def test_search_type_switching(self, page: Page, test_server: str) -> None:
        """Test switching between search types via dropdown."""
        _goto_ready(page, test_server)

        type_btn = page.locator("#searchTypeBtn")
        expect(type_btn).to_have_text("Artist", timeout=5000)

        # Open dropdown and click Genre
        self._open_dropdown_and_select(page, "genre")
        expect(type_btn).to_have_text("Genre", timeout=5000)

        # Switch to Label
        self._open_dropdown_and_select(page, "label")
        expect(type_btn).to_have_text("Label", timeout=5000)

        # Switch back to Artist
        self._open_dropdown_and_select(page, "artist")
        expect(type_btn).to_have_text("Artist", timeout=5000)

    def test_autocomplete_shows_results(self, page: Page, test_server: str) -> None:
        """Test that typing in search shows autocomplete results."""
        _goto_ready(page, test_server)

        search_input = page.locator("#searchInput")
        search_input.fill("Radio")

        # Wait for autocomplete debounce (300ms) and results to appear
        dropdown = page.locator("#autocompleteDropdown")
        expect(dropdown).to_have_class(re.compile("show"), timeout=5000)

        # Should have autocomplete items
        items = page.locator(".autocomplete-item")
        expect(items.first).to_be_visible(timeout=5000)

    def test_autocomplete_item_click_triggers_search(self, page: Page, test_server: str) -> None:
        """Test that clicking an autocomplete item triggers a search."""
        _goto_ready(page, test_server)

        search_input = page.locator("#searchInput")
        search_input.fill("Radio")

        # Wait for autocomplete results
        dropdown = page.locator("#autocompleteDropdown")
        expect(dropdown).to_have_class(re.compile("show"), timeout=5000)

        # Click the first result
        first_item = page.locator(".autocomplete-item").first
        expect(first_item).to_be_visible(timeout=5000)
        first_item.click()

        # Dropdown should close after selection
        expect(dropdown).not_to_have_class(re.compile("show"), timeout=5000)

        # Search input should have the selected name
        expect(search_input).not_to_have_value("", timeout=5000)

    def test_graph_appears_after_search(self, page: Page, test_server: str) -> None:
        """Test that the graph appears after performing a search."""
        _goto_ready(page, test_server)

        search_input = page.locator("#searchInput")
        search_input.fill("Radio")

        # Wait for autocomplete and click first result
        dropdown = page.locator("#autocompleteDropdown")
        expect(dropdown).to_have_class(re.compile("show"), timeout=5000)
        page.locator(".autocomplete-item").first.click()

        # Graph SVG should have content (nodes) after search
        svg = page.locator("#graphSvg")
        expect(svg).to_be_visible(timeout=5000)

        # Wait for graph to render - look for SVG child elements (circles/rects for nodes)
        page.wait_for_timeout(1000)  # Give D3 time to render
        # The placeholder should be hidden after data loads
        placeholder = page.locator("#graphPlaceholder")
        expect(placeholder).to_be_hidden(timeout=5000)

    def test_trends_pane_search(self, page: Page, test_server: str) -> None:
        """Test searching on the Trends pane loads chart data."""
        _goto_ready(page, test_server)

        # Switch to trends pane (with retry for Firefox)
        _switch_pane(page, "trends")

        # Type search query and select from autocomplete
        search_input = page.locator("#searchInput")
        search_input.fill("Radio")

        dropdown = page.locator("#autocompleteDropdown")
        expect(dropdown).to_have_class(re.compile("show"), timeout=5000)
        page.locator(".autocomplete-item").first.click()

        # Trends placeholder should be hidden after data loads
        page.wait_for_timeout(1000)  # Give Plotly time to render
        placeholder = page.locator("#trendsPlaceholder")
        expect(placeholder).to_be_hidden(timeout=5000)

    def test_graph_legend_visible(self, page: Page, test_server: str) -> None:
        """Test that the graph legend is visible on the explore pane."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)

        legend = page.locator("#graphLegend")
        expect(legend).to_be_visible(timeout=5000)

        # Check legend items
        legend_items = page.locator(".legend-item")
        expect(legend_items).to_have_count(5, timeout=5000)  # Artist, Release, Label, Genre/Style, Category

    def test_trends_placeholder_visible(self, page: Page, test_server: str) -> None:
        """Test that the trends placeholder is visible before search."""
        _goto_ready(page, test_server)

        # Switch to trends pane (with retry for Firefox)
        _switch_pane(page, "trends")

        placeholder = page.locator("#trendsPlaceholder")
        expect(placeholder).to_be_visible(timeout=5000)

    def test_static_css_loads(self, page: Page, test_server: str) -> None:
        """Test that custom CSS file is served correctly."""
        response = page.request.get(f"{test_server}/css/styles.css")
        assert response.ok
        assert "text/css" in response.headers.get("content-type", "")

    def test_static_js_files_load(self, page: Page, test_server: str) -> None:
        """Test that all JavaScript files are served correctly."""
        js_files = ["js/app.js", "js/api-client.js", "js/auth.js", "js/user-panes.js", "js/autocomplete.js", "js/graph.js", "js/trends.js"]
        for js_file in js_files:
            response = page.request.get(f"{test_server}/{js_file}")
            assert response.ok, f"Failed to load {js_file}"


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreGenreTree:
    """E2E tests for the genre tree feature."""

    def test_genres_tab_visible(self, page: Page, test_server: str) -> None:
        """Test that the Genres nav tab exists and is visible."""
        _goto_ready(page, test_server)

        genres_link = page.locator("[data-pane='genres']")
        expect(genres_link).to_be_visible(timeout=5000)

    def test_genres_pane_switchable(self, page: Page, test_server: str) -> None:
        """Test that clicking the Genres tab activates the genres pane."""
        _goto_ready(page, test_server)

        _switch_pane(page, "genres")

        genres_pane = page.locator("#genresPane")
        expect(genres_pane).to_have_class(re.compile(r"\bactive\b"), timeout=5000)

    def test_genre_tree_renders(self, page: Page, test_server: str) -> None:
        """Test that the genre tree loads and renders genre items."""
        _goto_ready(page, test_server)

        _switch_pane(page, "genres")

        # Wait for genre tree items to appear (fetched from /api/genre-tree)
        items = page.locator(".genre-tree-item")
        expect(items.first).to_be_visible(timeout=5000)

        # Verify genre names from mock data are present
        genres_pane = page.locator("#genresPane")
        expect(genres_pane).to_contain_text("Rock", timeout=5000)
        expect(genres_pane).to_contain_text("Electronic", timeout=5000)

    def test_genre_tree_api_endpoint(self, page: Page, test_server: str) -> None:
        """Test the genre-tree API returns genre data."""
        response = page.request.get(f"{test_server}/api/genre-tree")
        assert response.ok
        data = response.json()
        assert "genres" in data
        assert len(data["genres"]) == 2
        assert data["genres"][0]["name"] == "Rock"
        assert len(data["genres"][0]["styles"]) == 2


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreCollaborators:
    """E2E tests for the collaborators feature."""

    def test_collaborators_api_endpoint(self, page: Page, test_server: str) -> None:
        """Test the collaborators API returns collaborator data."""
        response = page.request.get(f"{test_server}/api/collaborators/1?limit=20")
        assert response.ok
        data = response.json()
        assert data["artist_id"] == "1"
        assert data["artist_name"] == "Radiohead"
        assert len(data["collaborators"]) == 2
        assert data["collaborators"][0]["artist_name"] == "Thom Yorke"
        assert data["collaborators"][1]["artist_name"] == "Jonny Greenwood"
        assert data["total"] == 2

    def test_collaborators_in_artist_detail(self, page: Page, test_server: str) -> None:
        """Test that the collaborators section appears in the artist info panel."""
        _goto_ready(page, test_server)

        # Search for an artist and select from autocomplete
        search_input = page.locator("#searchInput")
        search_input.fill("Radio")

        dropdown = page.locator("#autocompleteDropdown")
        expect(dropdown).to_have_class(re.compile("show"), timeout=5000)
        page.locator(".autocomplete-item").first.click()

        # Wait for graph to render
        placeholder = page.locator("#graphPlaceholder")
        expect(placeholder).to_be_hidden(timeout=5000)

        # Programmatically trigger the node-click handler for an artist node
        # (SVG <g> elements have no CSS class, so we call the app method directly)
        page.evaluate("window.exploreApp._onNodeClick('1', 'artist')")

        # The info panel should open and contain a Collaborators heading
        info_panel = page.locator("#infoPanel")
        expect(info_panel).to_have_class(re.compile("open"), timeout=5000)
        expect(info_panel).to_contain_text("Collaborators", timeout=5000)
