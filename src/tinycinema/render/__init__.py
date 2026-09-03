"""Pixels in, terminal cells out."""

from .base import (
    RenderOptions,
    Renderer,
    available_modes,
    create,
)
from .images import (  # noqa: F401 - imported for the side effect of registering
    ImageRenderer,
    ITermRenderer,
    KittyRenderer,
    SixelRenderer,
)
from .modes import (  # noqa: F401 - imported for the side effect of registering
    AsciiColorRenderer,
    AsciiRenderer,
    BlocksRenderer,
    BrailleRenderer,
    HalfBlockRenderer,
)
from .ramps import RAMPS

__all__ = [
    "RAMPS",
    "ImageRenderer",
    "RenderOptions",
    "Renderer",
    "available_modes",
    "cell_modes",
    "create",
    "image_modes",
]


def image_modes() -> list[str]:
    """Modes that hand the terminal a bitmap instead of characters."""
    return [m for m in available_modes() if getattr(create(m), "is_image", False)]


def cell_modes() -> list[str]:
    return [m for m in available_modes() if not getattr(create(m), "is_image", False)]
