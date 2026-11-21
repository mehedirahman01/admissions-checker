"""A polite HTTP fetcher: obeys robots.txt, waits between requests to the same host,
retries temporary errors, and identifies itself honestly."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = (
    "AdmissionsCheckerBot/0.1 (+https://github.com/mehedirahman01/admissions-checker)"
)
MAX_BYTES = 20 * 1024 * 1024  # skip anything bigger than 20 MB
RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    error: str | None = None
    blocked: bool = False  # robots.txt says no: we never requested it

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code == 200 and self.body is not None


class PoliteFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        min_delay: float = 2.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client or httpx.Client(timeout=20, follow_redirects=True)
        self.client.headers["User-Agent"] = USER_AGENT
        self.min_delay = min_delay
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_errors: dict[str, str] = {}  # origin -> why robots.txt was unreachable
        self._last_request: dict[str, float] = {}

    # --- robots.txt ---------------------------------------------------------

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            try:
                self._wait(parts.netloc)
                response = self.client.get(f"{origin}/robots.txt")
                if response.status_code >= 500:
                    parser.disallow_all = True  # server trouble: stay away for now
                elif response.status_code >= 400:
                    parser.allow_all = True  # no robots.txt: everything allowed
                else:
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError as exc:
                parser.disallow_all = True  # can't check the rules, so don't crawl
                self._robots_errors[origin] = f"{type(exc).__name__}: {exc}"
            self._robots[origin] = parser
        return self._robots[origin]

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(USER_AGENT, url)

    # --- rate limiting --------------------------------------------------------

    def _delay_for(self, host: str) -> float:
        origin = next((o for o in self._robots if urlsplit(o).netloc == host), None)
        crawl_delay = self._robots[origin].crawl_delay(USER_AGENT) if origin else None
        return max(self.min_delay, float(crawl_delay or 0))

    def _wait(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            remaining = self._delay_for(host) - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()

    # --- fetching -------------------------------------------------------------

    def fetch(self, url: str) -> FetchResult:
        allowed = self.allowed(url)
        parts = urlsplit(url)
        robots_error = self._robots_errors.get(f"{parts.scheme}://{parts.netloc}")
        if robots_error:
            # A failure, not a "no": the site was unreachable, so report it.
            return FetchResult(url=url, error=f"robots.txt unreachable ({robots_error})")
        if not allowed:
            return FetchResult(url=url, error="blocked by robots.txt", blocked=True)

        host = urlsplit(url).netloc
        for attempt in range(self.max_retries + 1):
            self._wait(host)
            try:
                response = self.client.get(url)
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    return FetchResult(url=url, error=f"{type(exc).__name__}: {exc}")
                self._sleep(2**attempt * self.min_delay)
                continue

            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else 2**attempt * self.min_delay
                self._sleep(wait)
                continue

            body = response.content
            if len(body) > MAX_BYTES:
                return FetchResult(url=url, status_code=response.status_code, error="too large")
            return FetchResult(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                content_type=response.headers.get("content-type", "").split(";")[0].strip(),
                body=body,
            )
        return FetchResult(url=url, error="gave up")  # pragma: no cover
