"""Read-only HA API client for exports and reports. Tokens stay in the environment."""

import json
from datetime import datetime
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .validation import mapping, sequence, string


class HaReader:
    def __init__(self, url: str, token: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
            raise ValueError("HA_URL must be an HTTP(S) server URL without credentials")
        self.url, self._token = url.rstrip("/"), token

    def state(self, entity: str) -> object:
        request = Request(
            f"{self.url}/api/states/{quote(entity, safe='')}",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        with urlopen(request, timeout=30) as response:
            data: object = json.load(response)
        return data

    def history(self, start: datetime, end: datetime, entities: list[str]) -> list[object]:
        url = (
            f"{self.url}/api/history/period/{quote(start.isoformat(), safe='')}"
            f"?end_time={quote(end.isoformat(), safe='')}"
            f"&filter_entity_id={quote(','.join(entities), safe='')}"
        )
        request = Request(url, headers={"Authorization": f"Bearer {self._token}"})
        with urlopen(request, timeout=30) as response:
            data: object = json.load(response)
        return sequence(data)

    def statistics(self, start: datetime, end: datetime, ids: list[str]) -> dict[str, object]:
        import websocket

        url = self.url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        ws = websocket.create_connection(f"{url}/api/websocket", timeout=45)
        try:
            hello = mapping(json.loads(ws.recv()))
            if hello.get("type") != "auth_required":
                raise RuntimeError("Unexpected HA authentication handshake")
            ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            if mapping(json.loads(ws.recv())).get("type") != "auth_ok":
                raise RuntimeError("HA authentication rejected")
            result: dict[str, object] = {}
            # Bound message size for hundreds of comfort counters.
            for index, offset in enumerate(range(0, len(ids), 100), 1):
                ws.send(
                    json.dumps(
                        {
                            "id": index,
                            "type": "recorder/statistics_during_period",
                            "start_time": start.isoformat(),
                            "end_time": end.isoformat(),
                            "period": "hour",
                            "statistic_ids": ids[offset : offset + 100],
                            "types": ["sum", "mean"],
                        }
                    )
                )
                message = mapping(json.loads(ws.recv()))
                if message.get("id") != index or message.get("success") is not True:
                    raise RuntimeError("HA statistics request failed")
                result.update(mapping(message["result"]))
            return result
        finally:
            ws.close()


def reader_from_environment() -> HaReader:
    import os

    return HaReader(string(os.environ["HA_URL"]), string(os.environ["HA_TOKEN"]))
