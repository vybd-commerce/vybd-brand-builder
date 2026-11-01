# ruff: noqa
# Ported verbatim from the example-brand build (../brain/image_gen.py). Unused in v0.
# STUB: wrap behind an OpenAI-compat/agnostic image interface when the content builder moves here.
# Needs `requests` / `google-genai` installed; not imported anywhere in v0.
"""
image_gen.py — swappable image generation, one ImageGenerator interface,
two provider adapters. campaign.py never talks to a provider SDK directly.

Providers:
  - SegmindHiggsfieldSoul — Segmind's `higgsfield-text2image-soul` (see
    PROVIDER_NOTES.md for why Segmind and not WaveSpeed — WaveSpeed's Soul
    endpoint has no pure text-to-image mode). Async submit/poll/download.
    Env: SEGMIND_API_KEY

  - VertexNanoBanana — Gemini 2.5 Flash Image ("Nano Banana") via Vertex AI.
    Synchronous, single call. Env: GOOGLE_GENAI_USE_VERTEXAI,
    GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION + `gcloud auth
    application-default login`.

CAUTION (see PROVIDER_NOTES.md "Not confirmed"): for Segmind, the exact auth
header name, the full 13-value width_and_height enum, and the result JSON
field name were not confirmed against a live account. For Vertex, the exact
model id (gemini-2.5-flash-image vs. -preview vs. a newer generation) and
whether the seed truly reproduces output were not confirmed. Both adapters
defend against the least-guessable failure (unrecognized result shape / no
image part) by raising a clear error rather than guessing silently. Run
smoke_test_image_gen.py / smoke_test_vertex.py against real keys before
trusting either in a real campaign.
"""

from __future__ import annotations

import base64
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests

SEGMIND_BASE = "https://api.segmind.com"
SUBMIT_PATH = "/v2/higgsfield-text2image-soul"
STATUS_PATH = "/v2/requests/{id}/status"
RESULT_PATH = "/v2/requests/{id}"

# Confirmed exact matches for the two ratios we know for certain; 4:5 (the IG
# feed default) is the closest known size to 4:5 among the examples the docs
# fetch surfaced, NOT a confirmed exact enum value. Verify against a live
# 400 response (Segmind typically echoes valid enum values on rejection)
# before a real campaign run, and update this map.
ASPECT_RATIO_TO_SIZE = {
    "4:5": "1536x2048",   # closest known option; NOT confirmed exact (true 4:5 target)
    "9:16": "1152x2048",  # confirmed exact: 1152/2048 = 9/16
    "1:1": "1536x1536",   # confirmed exact
}

DEFAULT_STYLE_ID = "b3c8075a-cb4c-42de-b8b3-7099dd2df672"

DEFAULT_TIMEOUT_S = 180
POLL_INTERVAL_S = 3
MAX_SUBMIT_RETRIES = 3


class ImageGenerationError(Exception):
    """Raised for a real failure: RAI/content block, provider error, timeout."""


@dataclass
class ImageResult:
    local_path: str
    prompt: str
    seed: int
    provider: str


class ImageGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        aspect_ratio: str = "4:5",
        reference_image: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> ImageResult:
        ...


class SegmindHiggsfieldSoul(ImageGenerator):
    def __init__(
        self,
        api_key: Optional[str] = None,
        output_dir: str = "./campaigns/_images",
        style_id: str = DEFAULT_STYLE_ID,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key or os.environ["SEGMIND_API_KEY"]
        self.output_dir = output_dir
        self.style_id = style_id
        self.session = session or requests.Session()
        os.makedirs(self.output_dir, exist_ok=True)

    def _headers(self) -> dict:
        # Header name per Segmind's documented convention; verify against
        # your account's dashboard code sample (see PROVIDER_NOTES.md).
        return {"x-api-key": self.api_key}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = "4:5",
        reference_image: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> ImageResult:
        if aspect_ratio not in ASPECT_RATIO_TO_SIZE:
            raise ValueError(
                f"Unsupported aspect_ratio {aspect_ratio!r}; supported: "
                f"{sorted(ASPECT_RATIO_TO_SIZE)}"
            )
        if seed is None:
            seed = int.from_bytes(os.urandom(4), "big") % 1_000_000

        body = {
            "prompt": prompt,
            "width_and_height": ASPECT_RATIO_TO_SIZE[aspect_ratio],
            "style_id": self.style_id,
            "seed": seed,
        }
        if reference_image:
            body["image_url"] = self._to_data_uri(reference_image)

        request_id = self._submit(body)
        status_payload = self._poll_until_done(request_id)
        image_bytes, ext = self._extract_image(status_payload, request_id)

        local_path = os.path.join(self.output_dir, f"{request_id}.{ext}")
        with open(local_path, "wb") as f:
            f.write(image_bytes)

        return ImageResult(
            local_path=local_path,
            prompt=prompt,
            seed=seed,
            provider="segmind:higgsfield-text2image-soul",
        )

    # ---------- internals ----------

    @staticmethod
    def _to_data_uri(path: str) -> str:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        return f"data:image/{mime};base64,{encoded}"

    def _submit(self, body: dict) -> str:
        last_err: Optional[Exception] = None
        for attempt in range(MAX_SUBMIT_RETRIES):
            try:
                resp = self.session.post(
                    SEGMIND_BASE + SUBMIT_PATH,
                    json=body,
                    headers=self._headers(),
                    timeout=30,
                )
                if resp.status_code >= 500:
                    raise ImageGenerationError(
                        f"Segmind submit failed {resp.status_code}: {resp.text[:500]}"
                    )
                if resp.status_code != 200:
                    # 4xx (bad request, RAI block on submit, insufficient credits,
                    # rate limit) is a real error, not a transient one — surface it.
                    raise ImageGenerationError(
                        f"Segmind submit rejected ({resp.status_code}): {resp.text[:500]}"
                    )
                data = resp.json()
                request_id = data.get("request_id") or data.get("id")
                if not request_id:
                    raise ImageGenerationError(
                        f"Segmind submit response missing request_id: {data}"
                    )
                return request_id
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
                time.sleep(2**attempt)
        raise ImageGenerationError(f"Segmind submit failed after retries: {last_err}")

    def _poll_until_done(self, request_id: str) -> dict:
        deadline = time.time() + DEFAULT_TIMEOUT_S
        url = SEGMIND_BASE + STATUS_PATH.format(id=request_id)
        while time.time() < deadline:
            resp = self.session.get(url, headers=self._headers(), timeout=30)
            if resp.status_code == 404:
                raise ImageGenerationError(
                    f"Segmind request {request_id} not found/expired while polling"
                )
            resp.raise_for_status()
            payload = resp.json()
            status = (payload.get("status") or "").upper()
            if status == "COMPLETED":
                return self._fetch_result(request_id)
            if status == "FAILED":
                detail = payload.get("error") or payload.get("message") or payload
                raise ImageGenerationError(
                    f"Segmind generation FAILED for {request_id}: {detail}"
                )
            time.sleep(POLL_INTERVAL_S)
        raise ImageGenerationError(
            f"Segmind generation timed out after {DEFAULT_TIMEOUT_S}s for {request_id}"
        )

    def _fetch_result(self, request_id: str) -> dict:
        url = SEGMIND_BASE + RESULT_PATH.format(id=request_id)
        resp = self.session.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _extract_image(self, payload: dict, request_id: str) -> tuple[bytes, str]:
        """Result field name wasn't confirmed live — probe likely keys."""
        candidates = [
            payload.get("output"),
            payload.get("image"),
            payload.get("url"),
            (payload.get("outputs") or [None])[0],
            (payload.get("data") or {}).get("outputs", [None])[0]
            if isinstance(payload.get("data"), dict)
            else None,
            (payload.get("result") or {}).get("image")
            if isinstance(payload.get("result"), dict)
            else None,
        ]
        value = next((c for c in candidates if c), None)
        if value is None:
            raise ImageGenerationError(
                f"Could not find image in Segmind result for {request_id}. "
                f"Update _extract_image in image_gen.py once the real shape "
                f"is confirmed. Raw payload: {payload}"
            )

        if isinstance(value, str) and value.startswith("data:image"):
            header, b64data = value.split(",", 1)
            ext = "jpeg" if "jpeg" in header or "jpg" in header else "png"
            return base64.b64decode(b64data), ext

        if isinstance(value, str) and value.startswith("http"):
            img_resp = self.session.get(value, timeout=60)
            img_resp.raise_for_status()
            ext = value.rsplit(".", 1)[-1].split("?")[0].lower()
            if ext not in ("png", "jpg", "jpeg", "webp"):
                ext = "png"
            return img_resp.content, ext

        raise ImageGenerationError(
            f"Unrecognized image value shape for {request_id}: {value!r}"
        )


# Nano Banana's ImageConfig.aspect_ratio only supports these 8 values
# (confirmed by reading google-genai's types.py directly) — there is no
# native "4:5". "3:4" is the closest available; this changes the actual
# output ratio from this project's IG-feed default, not just the label.
VERTEX_ASPECT_RATIO_MAP = {
    "4:5": "3:4",   # NOT an exact match — closest supported ratio
    "9:16": "9:16",  # exact
    "1:1": "1:1",    # exact
}

# NOT confirmed against a live account: exact model id. ai.google.dev
# (Gemini API) documents "gemini-2.5-flash-image"; a Vertex-specific blog
# post documented "gemini-2.5-flash-image-preview"; one source also flagged
# this generation as possibly superseded already ("Nano Banana 2"). Verify
# which id your project actually has access to before relying on this.
DEFAULT_NANO_BANANA_MODEL = "gemini-2.5-flash-image"


class VertexNanoBanana(ImageGenerator):
    """Nano Banana (Gemini 2.5 Flash Image) via Vertex AI, using google-genai.

    Unlike SegmindHiggsfieldSoul, this call is synchronous — one
    generate_content call returns the image inline, no submit/poll/download
    cycle. See PROVIDER_NOTES.md for what's confirmed vs. not.

    Env (full-project + ADC path):
        GOOGLE_GENAI_USE_VERTEXAI=true
        GOOGLE_CLOUD_PROJECT
        GOOGLE_CLOUD_LOCATION
        (credentials via `gcloud auth application-default login`)
    """

    def __init__(
        self,
        output_dir: str = "./campaigns/_images",
        model: str = DEFAULT_NANO_BANANA_MODEL,
        client=None,
    ):
        from google import genai

        self.output_dir = output_dir
        self.model = model
        self.client = client or genai.Client()
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = "4:5",
        reference_image: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> ImageResult:
        from google.genai import types

        if aspect_ratio not in VERTEX_ASPECT_RATIO_MAP:
            raise ValueError(
                f"Unsupported aspect_ratio {aspect_ratio!r}; supported: "
                f"{sorted(VERTEX_ASPECT_RATIO_MAP)}"
            )
        if seed is None:
            seed = int.from_bytes(os.urandom(4), "big") % 1_000_000

        contents: list = [prompt]
        if reference_image:
            contents.append(self._load_reference(reference_image))

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=VERTEX_ASPECT_RATIO_MAP[aspect_ratio]
            ),
            # "Best effort" reproducibility per Google's own docstring on this
            # field — not a guarantee. See smoke_test_vertex.py.
            seed=seed,
        )

        # Nano Banana intermittently returns finish_reason=NO_IMAGE with no
        # safety block involved (observed live, seemingly load/burst-related
        # since identical prompt+seed succeeds in isolation) — retry with
        # backoff before surfacing, since a 14-day campaign shouldn't die on
        # a transient blip.
        last_err: Optional[Exception] = None
        for attempt in range(5):
            if attempt > 0:
                time.sleep(2 * attempt)
            resp = self.client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
            try:
                image_bytes, ext = self._extract_image(resp)
                break
            except ImageGenerationError as e:
                last_err = e
        else:
            raise last_err

        local_path = os.path.join(self.output_dir, f"{uuid.uuid4().hex}.{ext}")
        with open(local_path, "wb") as f:
            f.write(image_bytes)

        return ImageResult(
            local_path=local_path,
            prompt=prompt,
            seed=seed,
            provider=f"vertex:{self.model}",
        )

    @staticmethod
    def _load_reference(path: str):
        from google.genai import types

        with open(path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
        mime_type = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
        return types.Part.from_bytes(data=data, mime_type=mime_type)

    @staticmethod
    def _extract_image(resp) -> tuple[bytes, str]:
        for part in resp.parts or []:
            if part.inline_data and part.inline_data.data:
                mime = part.inline_data.mime_type or "image/png"
                ext = "jpeg" if "jpeg" in mime else mime.split("/")[-1]
                return part.inline_data.data, ext

        # No image part — likely a RAI/safety block or the model responded
        # with text instead of an image. Surface the real reason, don't
        # silently skip (per build brief).
        finish_reason = None
        if getattr(resp, "candidates", None):
            finish_reason = getattr(resp.candidates[0], "finish_reason", None)
        raise ImageGenerationError(
            f"Nano Banana returned no image part (finish_reason="
            f"{finish_reason!r}). Full response: {resp!r}"
        )
