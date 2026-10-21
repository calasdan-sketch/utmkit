"""utmkit — batch UTM campaign links, slugs, validation and QR codes."""

from .core import Campaign, Finding, build_url, slugify, validate_campaign

__version__ = "0.1.0"
__all__ = ["Campaign", "Finding", "build_url", "slugify", "validate_campaign", "__version__"]
