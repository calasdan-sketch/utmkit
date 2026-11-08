"""utmkit — batch UTM campaign links, slugs, validation and QR codes."""

from .core import Campaign, Finding, build_url, slugify, validate_campaign

__version__ = "0.2.0"
__author__ = "Calas Automations Inc."
__all__ = ["Campaign", "Finding", "build_url", "slugify", "validate_campaign", "__version__", "__author__"]
