"""Static file handler with cache-friendly headers for versioned assets."""

from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class VersionedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code != 200:
            return response

        query = scope.get("query_string", b"").decode()
        if "v=" in query:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response
