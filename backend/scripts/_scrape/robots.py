"""robots.txt compliance check — called once at scraper startup."""

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx


class RobotsTxtError(RuntimeError):
    pass


def check_robots(api_base: str, user_agent: str, client: httpx.Client) -> None:
    """Fetch robots.txt for api_base's host and abort if /api.php is disallowed."""
    parsed = urlparse(api_base)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    try:
        response = client.get(robots_url, follow_redirects=True)
        robots_text = response.text if response.status_code == 200 else ""
    except httpx.TransportError:
        # Unreachable robots.txt — treat as permissive; don't block the scrape.
        robots_text = ""

    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(robots_text.splitlines())

    if not parser.can_fetch(user_agent, api_base):
        raise RobotsTxtError(
            f"robots.txt at {robots_url} disallows fetching {api_base} "
            f"for user-agent '{user_agent}'. Aborting."
        )
