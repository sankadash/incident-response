# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Incident Response Environment Client."""

from typing import Dict, Optional

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State
from websockets.asyncio.client import connect as ws_connect

from .models import (
    IncidentResponseAction,
    IncidentResponseObservation,
    QueryResult,
    ServiceStatus,
)


class IncidentResponseEnv(
    EnvClient[IncidentResponseAction, IncidentResponseObservation, State]
):
    """Client for the Incident Response Environment."""

    async def _connect(self) -> None:
        """Override to set generous ping timeout for slow LLM inference loops."""
        if self._ws is not None:
            return
        self._ws = await ws_connect(
            self._ws_url,
            open_timeout=self._connect_timeout,
            max_size=self._max_message_size,
            ping_timeout=90,
            ping_interval=20,
        )

    def _step_payload(self, action: IncidentResponseAction) -> Dict:
        """Convert IncidentResponseAction to JSON payload."""
        # Use Pydantic model_dump to include all non-None fields
        payload = action.model_dump(exclude_none=True, exclude={"metadata"})
        return payload

    def _parse_result(self, payload: Dict) -> StepResult[IncidentResponseObservation]:
        """Parse server response into StepResult[IncidentResponseObservation]."""
        obs_data = payload.get("observation", {})

        service_statuses = [
            ServiceStatus(**s) for s in obs_data.get("service_statuses", [])
        ]

        last_query_result = None
        qr_data = obs_data.get("last_query_result")
        if qr_data is not None:
            last_query_result = QueryResult(**qr_data)

        observation = IncidentResponseObservation(
            alert=obs_data.get("alert"),
            service_statuses=service_statuses,
            last_query_result=last_query_result,
            step_number=obs_data.get("step_number", 0),
            max_steps=obs_data.get("max_steps", 15),
            available_actions=obs_data.get("available_actions", []),
            done=payload.get("done", False),
            reward=payload.get("reward"),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        """Parse server response into State object."""
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
