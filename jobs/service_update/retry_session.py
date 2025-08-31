import logging
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import NameResolutionError
from urllib3.util.retry import Retry


class RetrySession(requests.Session):
    def __init__(
        self,
        retries: int = 3,
        backoff_factor: float = 0.5,
        status_forcelist: tuple[int, ...] = (500, 502, 504),
        allowed_methods: frozenset[str] = frozenset(["GET", "POST"]),
    ):
        super().__init__()

        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            allowed_methods=allowed_methods,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.mount("https://", adapter)
        self.mount("http://", adapter)

        self._dns_retries = retries
        self._backoff_factor = backoff_factor

    def request(self, *args, **kwargs) -> requests.Response:
        last_exception: Exception | None = None
        for attempt in range(self._dns_retries + 1):
            try:
                return super().request(*args, **kwargs)
            except requests.exceptions.ConnectionError as e:
                if isinstance(e.__cause__, NameResolutionError):
                    last_exception = e
                    sleep_time = self._backoff_factor * (2**attempt)
                    url = kwargs.get("url") or (
                        args[1] if len(args) > 1 else "<unknown>"
                    )
                    logging.warning(
                        "DNS resolution failed for %s, retrying in %.1fs (%d/%d)",
                        url,
                        sleep_time,
                        attempt + 1,
                        self._dns_retries,
                    )
                    time.sleep(sleep_time)
                    continue
                raise
        if last_exception is not None:
            raise last_exception
        raise requests.exceptions.ConnectionError(
            "DNS resolution retry failed, no exception captured"
        )
