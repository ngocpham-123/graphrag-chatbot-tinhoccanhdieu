"""Shared test fixtures. Curriculum tests are integration tests that need a
live GraphDB; skip the whole session if it is unreachable."""
import pytest
from SPARQLWrapper import SPARQLWrapper, JSON

from backend.app.services.curriculum_service import SPARQL_ENDPOINT


@pytest.fixture(scope="session", autouse=True)
def require_graphdb():
    wrapper = SPARQLWrapper(SPARQL_ENDPOINT)
    wrapper.setReturnFormat(JSON)
    wrapper.setQuery("ASK { ?s ?p ?o }")
    try:
        wrapper.query().convert()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"GraphDB not reachable at {SPARQL_ENDPOINT}: {e}")
