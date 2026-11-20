"""robots.txt: obeyed by default (the mentor's answer), read as RFC 9309 says, with the test switch."""
from __future__ import annotations

import httpx
import pytest

from app.checks import robots_check, transport_check
from app.fetch import RobotsForbidden, RobotsUnavailable
from tests.fetch.conftest import BASE, html, make_fetcher


def site(robots: httpx.Response | str, pages: dict[str, httpx.Response] | None = None):
    def handler(request):
        if request.url.path == "/robots.txt":
            return robots if isinstance(robots, httpx.Response) else httpx.Response(200, text=robots)
        return (pages or {}).get(request.url.path, html("page"))
    return handler


def test_a_disallowed_path_is_never_requested():
    fetcher, server, _ = make_fetcher(site("User-agent: *\nDisallow: /private/\n"), robots=True)
    assert fetcher.fetch("p1", f"{BASE}/tenders").ok
    with pytest.raises(RobotsForbidden):
        fetcher.fetch("p1", f"{BASE}/private/list")
    assert server.paths() == ["/robots.txt", "/tenders"]  # robots.txt once, and it takes a slot too
    assert server.times() == [0.0, 1.0]


def test_a_portal_that_forbids_every_path_is_a_block_unless_the_switch_is_on():
    rules = "User-agent: *\nDisallow: /\n"
    fetcher, _, _ = make_fetcher(site(rules), robots=True)
    assert fetcher.robots_forbids_every_path("p1", f"{BASE}/tenders")
    check = robots_check("run1", forbids_every_path=True, ignored=fetcher.settings.ignore_robots_txt)
    assert not check.passed

    switched, server, _ = make_fetcher(site(rules), robots=True, ignore_robots_txt=True)
    assert switched.fetch("p1", f"{BASE}/tenders").ok
    assert server.paths() == ["/tenders"]


def test_the_group_for_our_agent_wins_over_the_star_group():
    fetcher, _, _ = make_fetcher(site("User-agent: Watchtower\nDisallow: /\n\nUser-agent: *\nAllow: /\n"),
                                 robots=True)
    assert fetcher.robots_forbids_every_path("p1", f"{BASE}/")


def test_disallowing_the_root_but_allowing_a_path_does_not_forbid_every_path():
    fetcher, _, _ = make_fetcher(site("User-agent: *\nAllow: /tenders\nDisallow: /\n"), robots=True)
    assert not fetcher.robots_forbids_every_path("p1", f"{BASE}/")
    assert fetcher.fetch("p1", f"{BASE}/tenders").ok
    with pytest.raises(RobotsForbidden):
        fetcher.fetch("p1", f"{BASE}/admin")


def test_no_robots_txt_means_no_rules():
    fetcher, _, _ = make_fetcher(site(httpx.Response(404)), robots=True)
    assert fetcher.fetch("p1", f"{BASE}/anything").ok
    assert not fetcher.robots_forbids_every_path("p1", f"{BASE}/")


def test_an_unreachable_robots_txt_is_an_outage_not_a_block():
    fetcher, server, _ = make_fetcher(site(httpx.Response(503)), robots=True)
    with pytest.raises(RobotsUnavailable) as caught:
        fetcher.fetch("p1", f"{BASE}/tenders")
    assert server.paths() == ["/robots.txt"] * 3  # tried as rule T1 says; the page itself never requested
    fetched = caught.value.fetched
    check = transport_check("run1", fetched.answer, tries=fetched.tries)
    assert check.name == "outage" and not check.passed


def test_rules_are_kept_for_24_hours():
    fetcher, server, clock = make_fetcher(site("User-agent: *\nDisallow: /private/\n"), robots=True)
    fetcher.fetch("p1", f"{BASE}/a")
    fetcher.fetch("p1", f"{BASE}/b")
    clock.now += 86400
    fetcher.fetch("p1", f"{BASE}/c")
    assert server.paths().count("/robots.txt") == 2


def test_a_redirect_to_another_host_obeys_that_hosts_robots_txt():
    def handler(request):
        if request.url.host == "files.example":
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
            return html("file")
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://files.example/doc/1"})

    fetcher, server, _ = make_fetcher(handler, robots=True)
    with pytest.raises(RobotsForbidden):
        fetcher.fetch("p1", f"{BASE}/doc/1")
    assert "https://files.example/doc/1" not in [url for _, _, url in server.seen]


def test_forget_drops_the_rules():
    fetcher, server, _ = make_fetcher(site("User-agent: *\nAllow: /\n"), robots=True)
    fetcher.fetch("p1", f"{BASE}/a")
    fetcher.forget("p1")
    fetcher.fetch("p1", f"{BASE}/a")
    assert server.paths().count("/robots.txt") == 2


# == RFC 9309, section 2.2: our own matcher ==

def reads(rules: str | bytes, path: str) -> bool:
    body = rules if isinstance(rules, bytes) else rules.encode("utf-8")
    fetcher, _, _ = make_fetcher(site(httpx.Response(200, content=body)), robots=True)
    try:
        return fetcher.fetch("p1", f"{BASE}{path}").ok
    except RobotsForbidden:
        return False


def test_the_longest_match_wins_whatever_the_order_and_allow_wins_a_tie():
    rules = "User-agent: *\nDisallow: /\nAllow: /tenders\nDisallow: /tenders/private\n"
    assert reads(rules, "/tenders") and reads(rules, "/tenders/17")
    assert not reads(rules, "/admin") and not reads(rules, "/tenders/private/1")
    assert reads("User-agent: *\nDisallow: /list\nAllow: /list\n", "/list")
    fetcher, _, _ = make_fetcher(site(rules), robots=True)
    assert not fetcher.robots_forbids_every_path("p1", f"{BASE}/")


def test_star_and_dollar_are_obeyed():
    rules = "User-agent: *\nDisallow: /*?sort=\nDisallow: /*.pdf$\nDisallow: /search*/all\nAllow: /$\n"
    assert not reads(rules, "/list?sort=date") and reads(rules, "/list?page=2")
    assert not reads(rules, "/doc/a.pdf") and reads(rules, "/doc/a.pdf?download=1") and reads(rules, "/doc/a.pdfx")
    assert not reads(rules, "/search/2026/all") and reads(rules, "/search/2026")
    assert reads(rules, "/")


def test_a_byte_order_mark_comments_and_unknown_lines_do_not_hide_the_rules():
    rules = (b"\xef\xbb\xbf# our rules\nSitemap: https://portal.example/sitemap.xml\n"
             b"USER-AGENT: *   # everyone\nCrawl-delay: 5\nDisallow: /private/ # staff\n\nDisallow: /intern\n")
    assert not reads(rules, "/private/x") and not reads(rules, "/intern") and reads(rules, "/tenders")


def test_groups_are_chosen_by_our_name_and_fall_back_to_the_star_group():
    rules = ("User-agent: googlebot\nUser-agent: watchtower\nDisallow: /a\n\n"
             "User-agent: *\nDisallow: /b\n\nUser-agent: Watchtower/2.0\nDisallow: /c\n")
    assert not reads(rules, "/a") and not reads(rules, "/c")  # every group that names us counts
    assert reads(rules, "/b")                                   # the star group is only a fallback
    other = "User-agent: watchtowerbot\nDisallow: /\n\nUser-agent: *\nDisallow: /b\n"
    assert reads(other, "/a") and not reads(other, "/b")       # another robot's name is not ours
    assert reads("User-agent: googlebot\nDisallow: /\n", "/a")  # no group for us at all: no rules
    assert reads("Disallow: /\n", "/a") and reads("User-agent: *\nDisallow:\n", "/a")


@pytest.mark.parametrize("rules, forbids", [
    ("User-agent: *\nDisallow: /\n", True),
    ("User-agent: *\nDisallow: /*\n", True),
    ("User-agent: *\nDisallow: *\n", True),
    ("User-agent: Watchtower\nDisallow: /\n\nUser-agent: *\nAllow: /\n", True),
    ("User-agent: *\nDisallow: /\n\nUser-agent: watchtower\nDisallow: /private\n", False),
    ("User-agent: *\nDisallow: /\nAllow: /tenders\n", False),
    ("User-agent: *\nDisallow: /$\n", False),
    ("User-agent: *\nDisallow:\n", False),
    ("", False),
])
def test_forbids_every_path_is_read_off_our_own_rules(rules, forbids):
    fetcher, _, _ = make_fetcher(site(rules), robots=True)
    assert fetcher.robots_forbids_every_path("p1", f"{BASE}/") is forbids
    if forbids:
        with pytest.raises(RobotsForbidden):
            fetcher.fetch("p1", f"{BASE}/tenders")
