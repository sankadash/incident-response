# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
FastAPI application for the Incident Response Environment.

Endpoints:
    - POST /reset: Reset the environment
    - POST /step: Execute an action
    - GET /state: Get current environment state
    - GET /schema: Get action/observation schemas
    - WS /ws: WebSocket endpoint for persistent sessions
    - /web: Custom Incident Response dashboard
"""

try:
    from openenv.core.env_server.http_server import create_app
except Exception as e:  # pragma: no cover
    raise ImportError(
        "openenv is required for the web interface. Install dependencies with '\n    uv sync\n'"
    ) from e

try:
    from ..models import IncidentResponseAction, IncidentResponseObservation
    from .incident_response_environment import IncidentResponseEnvironment
    from .gradio_app import build_gradio_demo
except (ImportError, ModuleNotFoundError):
    from models import IncidentResponseAction, IncidentResponseObservation
    from server.incident_response_environment import IncidentResponseEnvironment
    from server.gradio_app import build_gradio_demo


def _custom_gradio_builder(web_manager, action_fields, metadata, is_chat_env, title, quick_start_md):
    """Wrapper that adapts our custom UI to the gradio_builder signature expected by create_app.

    Our build_gradio_demo() creates its own environment instances internally,
    so we ignore the web_manager and just return our custom Blocks.
    """
    return build_gradio_demo()


# Create the app with custom Gradio UI.
# When ENABLE_WEB_INTERFACE=true (set by openenv push for HF Spaces),
# create_app uses our _custom_gradio_builder for /web instead of the default.
# When false (local dev), we mount it manually below.
app = create_app(
    IncidentResponseEnvironment,
    IncidentResponseAction,
    IncidentResponseObservation,
    env_name="incident_response",
    max_concurrent_envs=1,
    gradio_builder=_custom_gradio_builder,
)

# For local dev (ENABLE_WEB_INTERFACE not set), mount manually so /web works
import os
if os.getenv("ENABLE_WEB_INTERFACE", "false").lower() not in ("true", "1", "yes"):
    import gradio as gr
    gradio_demo = build_gradio_demo()
    gr.mount_gradio_app(app, gradio_demo, path="/web", root_path="/web")


def main(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
