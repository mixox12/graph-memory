"""
Graph Memory: 100% Local-First Graph RAG Memory Engine fusing Neo4j, APOC, GDS, GenAI, and Graphify.
"""

from .client import GraphRagClient
from .engine import GraphRagEngine
from .server import start_server

__version__ = "1.0.0"
__all__ = ["GraphRagClient", "GraphRagEngine", "start_server"]
