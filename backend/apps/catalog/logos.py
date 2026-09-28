"""Service logos: what may be uploaded, and where a service's logo lives.

Two kinds of logo, one field. `Service.icon_url` is either a bundled asset the
web app serves ("/service-icons/<slug>.svg", generated from Simple Icons - see
service_icons.json) or the URL of a logo staff uploaded, which the API serves
from the database (`GET /api/v1/service-logos/<slug>/`).

Uploads are small, checked and inert:

* SVG or PNG only, at most 200 KB. SVG is preferred - it stays sharp at any
  size - and PNG must be at least 96 x 96 so it is not blurry on a phone.
* An SVG is refused if it could do anything but draw: scripts, event handlers,
  embedded documents, animation that can rewrite links, and any reference that
  leaves the file. It is served with a sandboxing Content-Security-Policy as
  well, so even an SVG that slipped through could not run if opened directly.
* Raw bytes in a BinaryField, not base64 text, and never large.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET

from apps.common.errors import ValidationFailed

MAX_LOGO_BYTES = 200 * 1024
MIN_PNG_SIDE = 96
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

BUNDLED_PATH = re.compile(r"^/service-icons/[a-z0-9_.-]+\.svg$")
UPLOADED_PATH = "/api/v1/service-logos/"

_FORBIDDEN_ELEMENTS = {
    "script", "foreignobject", "iframe", "object", "embed", "audio", "video", "canvas",
    "animate", "animatemotion", "animatetransform", "set", "handler", "listener",
}


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _check_svg(data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("That SVG is not valid UTF-8 text.") from exc
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValidationFailed("SVG logos may not contain a DOCTYPE or entities.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValidationFailed("That file is not a valid SVG.") from exc
    if _local(root.tag) != "svg":
        raise ValidationFailed("That file is not an SVG image.")

    for element in root.iter():
        if _local(element.tag) in _FORBIDDEN_ELEMENTS:
            raise ValidationFailed(f"SVG logos may not contain <{_local(element.tag)}>.")
        for attribute, value in element.attrib.items():
            name, value = _local(attribute), str(value).strip().lower()
            if name.startswith("on"):
                raise ValidationFailed("SVG logos may not contain event handlers.")
            if name == "href" and not value.startswith("#"):
                raise ValidationFailed("SVG logos may not link or load anything outside the file.")
            if "javascript:" in value or "data:" in value:
                raise ValidationFailed("SVG logos may not contain scripts or embedded data.")
            if "url(" in value and not re.fullmatch(r".*url\(\s*#[^)]*\).*", value):
                raise ValidationFailed("SVG logos may only reference their own gradients.")


def _check_png(data: bytes) -> None:
    # The IHDR chunk always comes first: width and height at bytes 16-24.
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise ValidationFailed("That PNG could not be read.")
    width, height = struct.unpack(">II", data[16:24])
    if min(width, height) < MIN_PNG_SIDE:
        raise ValidationFailed(
            f"PNG logos must be at least {MIN_PNG_SIDE} x {MIN_PNG_SIDE} pixels - use an SVG if you can."
        )


def validate_logo(data: bytes) -> str:
    """Check an upload and return its content type, or raise ValidationFailed."""
    if not data:
        raise ValidationFailed("Choose a logo file to upload.")
    if len(data) > MAX_LOGO_BYTES:
        raise ValidationFailed("Logos must be 200 KB or smaller.")
    if data.startswith(PNG_MAGIC):
        _check_png(data)
        return "image/png"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        _check_svg(data)
        return "image/svg+xml"
    raise ValidationFailed("Logos must be SVG or PNG.")


def validate_icon_url(value: str) -> str:
    """What staff may set directly: nothing, a bundled logo, or an uploaded one.

    Arbitrary third-party URLs are refused on purpose: hotlinked logos break,
    change under us, and would need the site's image policy opened up.
    """
    value = (value or "").strip()
    if not value or BUNDLED_PATH.match(value) or UPLOADED_PATH in value:
        return value
    raise ValidationFailed(
        "Use a bundled logo (/service-icons/<name>.svg) or upload one - external image "
        "links are not allowed."
    )
