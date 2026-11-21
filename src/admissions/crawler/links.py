"""Find links on a page that are likely to lead to study programs or admission rules,
and score them, so the crawler visits the most promising pages first."""

import html as html_lib
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

# Words that point to program pages and admission rules. Higher weight = more promising.
STRONG = {
    "zulassung": 5,
    "admission": 5,
    "pruefungsordnung": 5,
    "prüfungsordnung": 5,
    "zugangsvoraussetzung": 5,
    "requirements": 4,
    "bewerbung": 4,
    "apply": 3,
    "master": 4,
    "bachelor": 3,
    "studiengang": 4,
    "studiengaenge": 4,
    "studiengänge": 4,
    "studienangebot": 3,
    "degree-program": 3,
    "programme": 3,
    "program": 2,
    "english-taught": 4,
    "fristen": 3,
    "deadline": 3,
}
WEAK = {"studium": 1, "study": 1, "studierende": 1}
# Words that point away from admission rules. They lower the score.
NOISE = {
    "unimail": -6,
    "uniaccount": -6,
    "student-id": -6,
    "app": -3,
    "mensa": -6,
    "kantine": -6,
    "news": -4,
    "presse": -4,
    "aktuelles": -4,
    "veranstaltung": -4,
    "event": -4,
    "seniorenstudium": -5,
    "gasthoer": -5,
    "weiterbildung": -3,
    "promotion": -3,
    "video": -4,
    "ansprechpartner": -3,
    "kontakt": -3,
    "karriere": -4,
    "job": -2,
    "vorkurs": -3,
    "orientierung": -3,
    "vorlesungsverzeichnis": -3,
    "zertifikat": -3,
}
SKIP_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".mp4",
    ".mp3",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".ics",
    ".css",
    ".js",
)


@dataclass(frozen=True)
class Link:
    url: str
    score: int


def site_of(host: str) -> str:
    """'www.tu-dortmund.de' -> 'tu-dortmund.de', so subdomains count as the same site."""
    return host.lower().removeprefix("www.")


def same_site(url: str, root_url: str) -> bool:
    host, root = site_of(urlsplit(url).netloc), site_of(urlsplit(root_url).netloc)
    return host == root or host.endswith("." + root)


def score(url: str, anchor_text: str) -> int:
    """How promising a link is. 0 or less means: don't follow it."""
    haystack = f"{url} {anchor_text}".lower()
    points = 4 if url.lower().endswith(".pdf") else 0
    strong = sum(w for word, w in STRONG.items() if word in haystack)
    if strong == 0 and points == 0:
        strong = sum(w for word, w in WEAK.items() if word in haystack)
    if strong == 0 and points == 0:
        return 0  # not about studying at all
    return points + strong + sum(w for word, w in NOISE.items() if word in haystack)


def extract_links(html: bytes | str, page_url: str, root_url: str) -> list[Link]:
    soup = BeautifulSoup(html, "html.parser")
    best: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        href = html_lib.unescape(a["href"].strip())  # some sites escape "&" twice
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url, _fragment = urldefrag(urljoin(page_url, href))
        if urlsplit(url).scheme not in ("http", "https"):
            continue
        if url.lower().split("?")[0].endswith(SKIP_EXTENSIONS) or not same_site(url, root_url):
            continue
        points = score(url, a.get_text(" ", strip=True))
        if points > 0:
            best[url] = max(points, best.get(url, 0))
    return [Link(url, points) for url, points in best.items()]


def canonical_url(html: bytes | str, page_url: str) -> str | None:
    """The page's own statement of its main address: <link rel="canonical" href="...">."""
    tag = BeautifulSoup(html, "html.parser").find("link", rel="canonical", href=True)
    return urljoin(page_url, tag["href"].strip()) if tag else None
