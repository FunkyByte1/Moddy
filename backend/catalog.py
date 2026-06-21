"""Shared Browse-catalog item shape.

Thunderstore, the Balatro Mod Index, and Nexus Mods all surface different upstream
schemas, but the Browse UI renders a single trimmed shape (typed `ThunderstorePackage`
on the frontend). This module formalizes that shape as `CatalogItem` and provides a
factory so every provider's parser produces it identically — the rule-of-three payoff
now that Nexus is the third source.

Note: this is ONLY the per-item shape. The whole-catalog disk cache that Thunderstore
and BMI use is NOT shared here — Nexus does server-side search + per-mod caching, not
bulk-catalog caching, so those providers keep their own catalog caches.
"""

from typing import Optional, TypedDict


class CatalogItemLatest(TypedDict):
    version_number: str
    description: str
    icon: str
    dependencies: list[str]   # provider-specific dep id strings (Thunderstore full_names; [] for Nexus v1)
    download_url: str         # may be "" when resolved lazily at install time (Nexus)
    file_size: int


class CatalogItem(TypedDict):
    name: str
    full_name: str            # stable install id, unique within the provider/community
    owner: str
    package_url: str
    donation_link: Optional[str]
    date_updated: str         # ISO-8601 (sorts chronologically as a string) or ""
    rating_score: int         # likes/endorsements; 0 when the provider has no such metric
    is_deprecated: bool
    has_nsfw_content: bool
    categories: list[str]
    is_library: bool          # a library/framework for other mods — hidden from Browse by default
    latest: CatalogItemLatest


def make_item(
    *,
    name: str,
    full_name: str,
    owner: str = "",
    package_url: str = "",
    donation_link: Optional[str] = None,
    date_updated: str = "",
    rating_score: int = 0,
    is_deprecated: bool = False,
    has_nsfw_content: bool = False,
    categories: Optional[list[str]] = None,
    is_library: bool = False,
    version_number: str = "",
    description: str = "",
    icon: str = "",
    dependencies: Optional[list[str]] = None,
    download_url: str = "",
    file_size: int = 0,
) -> CatalogItem:
    """Build a CatalogItem with sane defaults. Providers pass only the fields they have;
    callers that carry extra provider-only keys (e.g. BMI's requires_steamodded) add them
    to the returned dict afterwards."""
    return {
        "name": name,
        "full_name": full_name,
        "owner": owner,
        "package_url": package_url,
        "donation_link": donation_link,
        "date_updated": date_updated,
        "rating_score": rating_score,
        "is_deprecated": is_deprecated,
        "has_nsfw_content": has_nsfw_content,
        "categories": list(categories or []),
        "is_library": is_library,
        "latest": {
            "version_number": version_number,
            "description": description,
            "icon": icon,
            "dependencies": list(dependencies or []),
            "download_url": download_url,
            "file_size": file_size,
        },
    }
