from app.main import app


def test_collection_routes_are_canonical_without_trailing_slashes():
    route_paths = {route.path for route in app.routes}

    assert "/repositories" in route_paths
    assert "/repositories/{repository_id}/reviews" in route_paths
    assert "/repositories/{repository_id}/pull-requests" in route_paths
    assert "/repositories/{repository_id}/analytics" in route_paths
    assert "/repositories/{repository_id}/analytics/sync" in route_paths
