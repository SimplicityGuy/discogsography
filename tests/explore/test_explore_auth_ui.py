"""E2E browser tests for the Explore service auth UI and user panes."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect
import pytest


_MOCK_TOKEN = "mock-test-access-token-abc123"  # nosec B105


def _wait_for_alpine(page: Page) -> None:
    """Wait for Alpine.js to be fully initialised."""
    page.wait_for_function("() => !!window.Alpine && !!Alpine.store('modals')", timeout=10000)


def _set_logged_in(page: Page, test_server: str) -> None:
    """Helper: inject auth token into localStorage and reload so authManager initialises."""
    page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
    _wait_for_alpine(page)
    page.evaluate(f"window.localStorage.setItem('auth_token', '{_MOCK_TOKEN}')")
    page.reload(wait_until="domcontentloaded", timeout=30000)
    _wait_for_alpine(page)
    # Wait for authManager.init() async calls to complete and UI to update
    expect(page.locator("#userDropdown")).not_to_have_class(re.compile(r"\bhidden\b"), timeout=8000)


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreAuthNavbar:
    """E2E tests for auth-related navbar elements."""

    def test_login_button_visible_when_logged_out(self, page: Page, test_server: str) -> None:
        """Login button is visible in navbar when no token is stored."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)

        login_btn = page.locator("#navLoginBtn")
        expect(login_btn).to_be_visible(timeout=5000)

    def test_user_dropdown_hidden_when_logged_out(self, page: Page, test_server: str) -> None:
        """User dropdown is hidden when not authenticated."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)

        user_dropdown = page.locator("#userDropdown")
        expect(user_dropdown).to_have_class(re.compile(r"\bhidden\b"), timeout=5000)

    def test_collection_nav_hidden_when_logged_out(self, page: Page, test_server: str) -> None:
        """Secondary nav bar is hidden when logged out."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)

        expect(page.locator("#navSecondary")).to_have_class(re.compile(r"\bhidden\b"), timeout=5000)

    def test_user_dropdown_visible_when_logged_in(self, page: Page, test_server: str) -> None:
        """User dropdown is visible after injecting an auth token."""
        _set_logged_in(page, test_server)

        user_dropdown = page.locator("#userDropdown")
        expect(user_dropdown).not_to_have_class(re.compile(r"\bhidden\b"), timeout=5000)

    def test_auth_buttons_hidden_when_logged_in(self, page: Page, test_server: str) -> None:
        """Login button area is hidden once the user is authenticated."""
        _set_logged_in(page, test_server)

        auth_buttons = page.locator("#authButtons")
        expect(auth_buttons).to_have_class(re.compile(r"\bhidden\b"), timeout=5000)

    def test_user_email_displayed_in_dropdown(self, page: Page, test_server: str) -> None:
        """Logged-in user's email appears in the navbar dropdown toggle."""
        _set_logged_in(page, test_server)

        email_display = page.locator("#userEmailDisplay")
        expect(email_display).to_have_text("test@example.com", timeout=5000)

    def test_collection_nav_visible_when_logged_in(self, page: Page, test_server: str) -> None:
        """Secondary nav bar appears after login."""
        _set_logged_in(page, test_server)

        expect(page.locator("#navSecondary")).not_to_have_class(re.compile(r"\bhidden\b"), timeout=5000)

    def test_connect_discogs_button_visible_in_dropdown(self, page: Page, test_server: str) -> None:
        """Connect Discogs button is visible in the user dropdown when not connected."""
        _set_logged_in(page, test_server)

        # Open the user dropdown
        page.locator("#userMenuToggle").click()
        connect_btn = page.locator("#connectDiscogsBtn")
        expect(connect_btn).not_to_have_class(re.compile(r"\bhidden\b"), timeout=5000)

    def test_logout_button_visible_in_dropdown(self, page: Page, test_server: str) -> None:
        """Logout button is present in the user dropdown."""
        _set_logged_in(page, test_server)

        page.locator("#userMenuToggle").click()
        logout_btn = page.locator("#logoutBtn")
        expect(logout_btn).to_be_visible(timeout=5000)

    def test_logout_restores_logged_out_state(self, page: Page, test_server: str) -> None:
        """Clicking logout clears auth state and shows login button."""
        _set_logged_in(page, test_server)

        # Open dropdown and click logout
        page.locator("#userMenuToggle").click()
        page.locator("#logoutBtn").click()

        # Login button should reappear
        expect(page.locator("#navLoginBtn")).to_be_visible(timeout=5000)
        # User dropdown should hide
        expect(page.locator("#userDropdown")).to_have_class(re.compile(r"\bhidden\b"), timeout=5000)


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreAuthModal:
    """E2E tests for the login/register modal."""

    def test_auth_modal_exists_in_dom(self, page: Page, test_server: str) -> None:
        """The auth modal element is present in the DOM."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        modal = page.locator("#authModal")
        expect(modal).to_be_attached()

    def test_auth_modal_opens_on_login_click(self, page: Page, test_server: str) -> None:
        """Clicking the Login button opens the auth modal."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        _wait_for_alpine(page)

        page.locator("#navLoginBtn").click()
        modal = page.locator("#authModal")
        expect(modal).to_be_visible(timeout=5000)

    def test_auth_modal_has_login_tab(self, page: Page, test_server: str) -> None:
        """The auth modal has a Login tab."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        _wait_for_alpine(page)

        page.locator("#navLoginBtn").click()
        expect(page.locator("#login-tab")).to_be_visible(timeout=5000)

    def test_auth_modal_has_register_tab(self, page: Page, test_server: str) -> None:
        """The auth modal has a Register tab."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        _wait_for_alpine(page)

        page.locator("#navLoginBtn").click()
        expect(page.locator("#register-tab")).to_be_visible(timeout=5000)

    def test_login_form_has_email_and_password_fields(self, page: Page, test_server: str) -> None:
        """Login form contains email and password inputs."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        _wait_for_alpine(page)

        page.locator("#navLoginBtn").click()
        expect(page.locator("#loginEmail")).to_be_visible(timeout=5000)
        expect(page.locator("#loginPassword")).to_be_visible(timeout=5000)

    def test_register_tab_switches_on_click(self, page: Page, test_server: str) -> None:
        """Clicking the Register tab shows the register form."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        _wait_for_alpine(page)

        page.locator("#navLoginBtn").click()
        page.locator("#register-tab").click()

        # Register form fields should become visible
        expect(page.locator("#registerEmail")).to_be_visible(timeout=5000)
        expect(page.locator("#registerPassword")).to_be_visible(timeout=5000)

    def test_login_shows_error_for_invalid_credentials(self, page: Page, test_server: str) -> None:
        """Entering wrong credentials shows an error message."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        _wait_for_alpine(page)

        page.locator("#navLoginBtn").click()
        page.locator("#loginEmail").fill("wrong@example.com")
        page.locator("#loginPassword").fill("wrongpassword")
        page.locator("#loginSubmitBtn").click()

        error_el = page.locator("#loginError")
        expect(error_el).not_to_have_text("", timeout=8000)

    def test_successful_login_closes_modal(self, page: Page, test_server: str) -> None:
        """Correct credentials close the modal and show the user dropdown."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("window.localStorage.removeItem('auth_token')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        _wait_for_alpine(page)

        page.locator("#navLoginBtn").click()
        page.locator("#loginEmail").fill("test@example.com")
        page.locator("#loginPassword").fill("testpassword")
        page.locator("#loginSubmitBtn").click()

        # Modal should close
        modal = page.locator("#authModal")
        expect(modal).not_to_be_visible(timeout=8000)

        # User dropdown should appear
        expect(page.locator("#userDropdown")).not_to_have_class(re.compile(r"\bhidden\b"), timeout=8000)


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreUserPanes:
    """E2E tests for Collection, Wantlist, and Recommendations panes."""

    def test_collection_pane_exists_in_dom(self, page: Page, test_server: str) -> None:
        """The collection pane element exists in the DOM."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        expect(page.locator("#collectionPane")).to_be_attached()

    def test_wantlist_pane_exists_in_dom(self, page: Page, test_server: str) -> None:
        """The wantlist pane element exists in the DOM."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        expect(page.locator("#wantlistPane")).to_be_attached()

    def test_recommendations_pane_exists_in_dom(self, page: Page, test_server: str) -> None:
        """The recommendations pane element exists in the DOM."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        expect(page.locator("#recommendationsPane")).to_be_attached()

    def test_collection_pane_becomes_active_on_nav_click(self, page: Page, test_server: str) -> None:
        """Clicking the Collection nav item switches to the collection pane."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='collection']").click()

        collection_pane = page.locator("#collectionPane")
        expect(collection_pane).to_have_class(re.compile("active"), timeout=5000)

        # Explore pane should no longer be active
        explore_pane = page.locator("#explorePane")
        expect(explore_pane).not_to_have_class(re.compile("active"), timeout=5000)

    def test_wantlist_pane_becomes_active_on_nav_click(self, page: Page, test_server: str) -> None:
        """Clicking the Wantlist nav item switches to the wantlist pane."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='wantlist']").click()

        wantlist_pane = page.locator("#wantlistPane")
        expect(wantlist_pane).to_have_class(re.compile("active"), timeout=5000)

    def test_recommendations_pane_becomes_active_on_nav_click(self, page: Page, test_server: str) -> None:
        """Clicking the Discover nav item switches to the recommendations pane."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='recommendations']").click()

        rec_pane = page.locator("#recommendationsPane")
        expect(rec_pane).to_have_class(re.compile("active"), timeout=5000)

    def test_collection_pane_loads_release_data(self, page: Page, test_server: str) -> None:
        """Collection pane renders release titles from the API."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='collection']").click()

        # Wait for release list to appear (mock returns "OK Computer" and "Kid A")
        release_titles = page.locator(".release-list-title")
        expect(release_titles.first).to_be_visible(timeout=8000)
        expect(release_titles).to_have_count(2, timeout=8000)

    def test_collection_pane_shows_release_title(self, page: Page, test_server: str) -> None:
        """Collection pane shows known release title from mock data."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='collection']").click()

        expect(page.locator(".release-list-title").first).to_contain_text("OK Computer", timeout=8000)

    def test_wantlist_pane_loads_release_data(self, page: Page, test_server: str) -> None:
        """Wantlist pane renders release titles from the API."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='wantlist']").click()

        release_titles = page.locator(".release-list-title")
        expect(release_titles.first).to_be_visible(timeout=8000)
        expect(release_titles.first).to_contain_text("In Rainbows", timeout=8000)

    def test_recommendations_pane_loads_data(self, page: Page, test_server: str) -> None:
        """Recommendations pane shows recommendation items."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='recommendations']").click()

        rec_items = page.locator(".recommendation-item")
        expect(rec_items.first).to_be_visible(timeout=8000)
        expect(rec_items).to_have_count(2, timeout=8000)

    def test_collection_pane_has_refresh_button(self, page: Page, test_server: str) -> None:
        """Collection pane header contains a Refresh button."""
        _set_logged_in(page, test_server)

        page.locator("[data-pane='collection']").click()

        refresh_btn = page.locator("#collectionRefreshBtn")
        expect(refresh_btn).to_be_visible(timeout=5000)

    def test_logout_redirects_to_explore_pane(self, page: Page, test_server: str) -> None:
        """Logging out while on the collection pane redirects to the explore pane."""
        _set_logged_in(page, test_server)

        # Switch to collection pane
        page.locator("[data-pane='collection']").click()
        expect(page.locator("#collectionPane")).to_have_class(re.compile("active"), timeout=5000)

        # Logout
        page.locator("#userMenuToggle").click()
        page.locator("#logoutBtn").click()

        # Should be redirected to explore pane
        expect(page.locator("#explorePane")).to_have_class(re.compile("active"), timeout=5000)


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreDiscogsOAuth:
    """E2E tests for Discogs OAuth connect UI."""

    def test_discogs_modal_exists_in_dom(self, page: Page, test_server: str) -> None:
        """The Discogs OAuth verifier modal is present in the DOM."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        expect(page.locator("#discogsModal")).to_be_attached()

    def test_discogs_verifier_input_exists(self, page: Page, test_server: str) -> None:
        """The verifier code input field is present in the Discogs modal."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        expect(page.locator("#discogsVerifierInput")).to_be_attached()

    def test_discogs_verifier_submit_button_exists(self, page: Page, test_server: str) -> None:
        """The Connect button is present in the Discogs modal."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        submit_btn = page.locator("#discogsVerifierSubmit")
        expect(submit_btn).to_be_attached()


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreAuthAPIEndpoints:
    """E2E tests for auth and user API endpoints via page.request."""

    def test_login_endpoint_success(self, page: Page, test_server: str) -> None:
        """POST /api/auth/login returns a token for valid credentials."""
        response = page.request.post(
            f"{test_server}/api/auth/login",
            data={"email": "test@example.com", "password": "testpassword"},
        )
        assert response.ok
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

    def test_login_endpoint_rejects_invalid_credentials(self, page: Page, test_server: str) -> None:
        """POST /api/auth/login returns 401 for wrong credentials."""
        response = page.request.post(
            f"{test_server}/api/auth/login",
            data={"email": "nobody@example.com", "password": "wrongpassword"},
        )
        assert response.status == 401

    def test_register_endpoint_success(self, page: Page, test_server: str) -> None:
        """POST /api/auth/register returns 201 for a new account request."""
        response = page.request.post(
            f"{test_server}/api/auth/register",
            data={"email": "newuser@example.com", "password": "newpassword123"},
        )
        assert response.status == 201

    def test_me_endpoint_with_token(self, page: Page, test_server: str) -> None:
        """GET /api/auth/me returns user info for a valid Bearer token."""
        response = page.request.get(
            f"{test_server}/api/auth/me",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert data["email"] == "test@example.com"
        assert "id" in data

    def test_me_endpoint_requires_auth(self, page: Page, test_server: str) -> None:
        """GET /api/auth/me returns 401 when no token is provided."""
        response = page.request.get(f"{test_server}/api/auth/me")
        assert response.status == 401

    def test_logout_endpoint(self, page: Page, test_server: str) -> None:
        """POST /api/auth/logout accepts a Bearer token and confirms logout."""
        response = page.request.post(
            f"{test_server}/api/auth/logout",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert data.get("logged_out") is True

    def test_oauth_authorize_discogs_endpoint(self, page: Page, test_server: str) -> None:
        """GET /api/oauth/authorize/discogs returns an authorization URL."""
        response = page.request.get(
            f"{test_server}/api/oauth/authorize/discogs",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert "authorize_url" in data
        assert "state" in data

    def test_oauth_status_discogs_endpoint(self, page: Page, test_server: str) -> None:
        """GET /api/oauth/status/discogs returns connection status."""
        response = page.request.get(
            f"{test_server}/api/oauth/status/discogs",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert "connected" in data

    def test_user_collection_endpoint(self, page: Page, test_server: str) -> None:
        """GET /api/user/collection returns paginated releases."""
        response = page.request.get(
            f"{test_server}/api/user/collection",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert "releases" in data
        assert isinstance(data["releases"], list)
        assert "total" in data
        assert "has_more" in data

    def test_user_collection_requires_auth(self, page: Page, test_server: str) -> None:
        """GET /api/user/collection returns 401 without a token."""
        response = page.request.get(f"{test_server}/api/user/collection")
        assert response.status == 401

    def test_user_wantlist_endpoint(self, page: Page, test_server: str) -> None:
        """GET /api/user/wantlist returns paginated releases."""
        response = page.request.get(
            f"{test_server}/api/user/wantlist",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert "releases" in data
        assert isinstance(data["releases"], list)

    def test_user_recommendations_endpoint(self, page: Page, test_server: str) -> None:
        """GET /api/user/recommendations returns recommendation items."""
        response = page.request.get(
            f"{test_server}/api/user/recommendations",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    def test_user_collection_stats_endpoint(self, page: Page, test_server: str) -> None:
        """GET /api/user/collection/stats returns stat fields."""
        response = page.request.get(
            f"{test_server}/api/user/collection/stats",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert "total_releases" in data
        assert "unique_artists" in data

    def test_user_status_endpoint_anonymous(self, page: Page, test_server: str) -> None:
        """GET /api/user/status works without authentication."""
        response = page.request.get(f"{test_server}/api/user/status?ids=10,11")
        assert response.ok
        data = response.json()
        assert "status" in data
        assert "10" in data["status"]
        assert "11" in data["status"]

    def test_sync_trigger_endpoint(self, page: Page, test_server: str) -> None:
        """POST /api/sync returns 202 and a job ID."""
        response = page.request.post(
            f"{test_server}/api/sync",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.status == 202
        data = response.json()
        assert data["status"] == "started"
        assert "job_id" in data

    def test_sync_status_endpoint(self, page: Page, test_server: str) -> None:
        """GET /api/sync/status returns current sync state."""
        response = page.request.get(
            f"{test_server}/api/sync/status",
            headers={"Authorization": f"Bearer {_MOCK_TOKEN}"},
        )
        assert response.ok
        data = response.json()
        assert "status" in data


@pytest.mark.e2e
@pytest.mark.usefixtures("test_server")
class TestExploreNewStaticFiles:
    """E2E tests verifying new JavaScript files are served correctly."""

    def test_auth_js_loads(self, page: Page, test_server: str) -> None:
        """auth.js is served with the correct content type."""
        response = page.request.get(f"{test_server}/js/auth.js")
        assert response.ok, "auth.js must be served"
        assert "javascript" in response.headers.get("content-type", "")

    def test_user_panes_js_loads(self, page: Page, test_server: str) -> None:
        """user-panes.js is served with the correct content type."""
        response = page.request.get(f"{test_server}/js/user-panes.js")
        assert response.ok, "user-panes.js must be served"
        assert "javascript" in response.headers.get("content-type", "")

    def test_auth_manager_available_in_browser(self, page: Page, test_server: str) -> None:
        """window.authManager is defined after page load."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        # Give scripts time to execute
        page.wait_for_timeout(500)
        defined = page.evaluate("typeof window.authManager !== 'undefined'")
        assert defined, "window.authManager must be defined"

    def test_user_panes_class_available_in_browser(self, page: Page, test_server: str) -> None:
        """window.UserPanes is defined after page load."""
        page.goto(test_server, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(500)
        defined = page.evaluate("typeof window.UserPanes !== 'undefined'")
        assert defined, "window.UserPanes must be defined"
