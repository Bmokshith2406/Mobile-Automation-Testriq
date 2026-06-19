"""API versioning support."""

from fastapi import Request, HTTPException, status


async def extract_api_version(request: Request) -> str:
    """Extract API version from request path or header."""
    # Try path-based versioning first (/api/v1/)
    path_parts = request.url.path.split("/")
    if len(path_parts) > 2 and path_parts[2].startswith("v"):
        try:
            version = path_parts[2]  # e.g., "v1", "v2"
            if version[0] == "v" and version[1:].isdigit():
                return version
        except (IndexError, ValueError):
            pass
    
    # Fall back to header-based versioning (API-Version header)
    version = request.headers.get("API-Version")
    if version:
        return version
    
    # Default to v1
    return "v1"


def get_supported_versions() -> list[str]:
    """Get list of supported API versions."""
    return ["v1", "v2"]  # Add new versions as they're supported


def is_version_supported(version: str) -> bool:
    """Check if API version is supported."""
    return version in get_supported_versions()


class DeprecationWarning:
    """Deprecation notice for API versions."""
    
    WARNINGS = {
        "v1": None,  # v1 is current
        "v2": None,  # v2 is current
    }
    
    @staticmethod
    def get_warning(version: str) -> str | None:
        """Get deprecation warning for a version if any."""
        return DeprecationWarning.WARNINGS.get(version)
