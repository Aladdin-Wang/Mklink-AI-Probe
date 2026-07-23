"""FastAPI route inspection helpers shared by regression tests."""


def iter_routes(router):
    """Yield concrete routes across old and lazy include_router layouts."""
    for route in router.routes:
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            yield from iter_routes(included_router)
        else:
            yield route


def find_route(app, path):
    return next(
        route
        for route in iter_routes(app)
        if getattr(route, "path", None) == path
    )
