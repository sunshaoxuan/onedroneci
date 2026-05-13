from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.parse
import urllib.request
from typing import Any


@dataclass(frozen=True)
class DroneBuildRef:
    repo: str
    build_number: int
    url: str | None = None


class DroneExecutorAdapter:
    def __init__(self, server_url: str, token: str, control_repo: str, control_branch: str = "master") -> None:
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.control_repo = control_repo.strip("/")
        self.control_branch = control_branch

    def trigger(self, request: dict[str, Any], build_id: str) -> DroneBuildRef:
        params = {
            "branch": self.control_branch,
            "BUILD_ID": build_id,
            "OHR_BACK_BRANCH": request["backend_branch"],
            "FRONTEND_WORKSPACE_BRANCH": request["frontend_workspace_branch"],
            "FRONTEND_RELEASE_BRANCH": request["frontend_release_branch"],
            "FRONTEND_FEELIN_BRANCH": request.get("frontend_feelin_branch", ""),
            "FRONTEND_LOWCODE_ENGINE_BRANCH": request.get("frontend_lowcode_engine_branch", ""),
            "FRONTEND_MICRO_FRONTENDS_BRANCH": request.get("frontend_micro_frontends_branch", ""),
            "FRONTEND_NOCODE_ENGINE_BRANCH": request.get("frontend_nocode_engine_branch", ""),
        }
        path = f"/api/repos/{self.control_repo}/builds?{urllib.parse.urlencode(params)}"
        data = self._request("POST", path)
        number = int(data["number"])
        return DroneBuildRef(
            repo=self.control_repo,
            build_number=number,
            url=f"{self.server_url}/{self.control_repo}/{number}",
        )

    def get_build(self, ref: DroneBuildRef) -> dict[str, Any]:
        return self._request("GET", f"/api/repos/{ref.repo}/builds/{ref.build_number}")

    def get_logs(self, ref: DroneBuildRef, stage: int, step: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/repos/{ref.repo}/builds/{ref.build_number}/logs/{stage}/{step}")

    def _request(self, method: str, path: str) -> Any:
        req = urllib.request.Request(
            self.server_url + path,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None
