# Neo4j Enterprise & Community Plugin Reference for Graph Memory

Graph Memory is built to take full advantage of native Neo4j 2025/2026 graph database acceleration libraries. When running locally on `bolt://127.0.0.1:7687` and `http://127.0.0.1:7474`, the following 4 plugin suites are supported and dynamically discovered:

---

## 1. APOC Core (Awesome Procedures On Cypher)
- **Procedures Count:** 174
- **Primary Use Cases:**
  - Fast subgraph expansion (`apoc.path.subgraphAll`)
  - Subgraph node filtering by relationship types (`CALLS|IMPORTS|CONTAINS`)
  - Dynamic Cypher statement construction and batched transactions (`apoc.periodic.iterate`)
  - Graph export to JSON, GraphML, and Cypher script formats (`apoc.export.json.*`)

### Example: Subgraph Extraction
```cypher
MATCH (root:Entity {name: "TimelineApp"})
CALL apoc.path.subgraphAll(root, {
    maxLevel: 2,
    relationshipFilter: "CALLS|IMPORTS"
})
YIELD nodes, relationships
RETURN nodes, relationships;
```

---

## 2. Graph Data Science (GDS)
- **Procedures Count:** 470
- **Primary Use Cases:**
  - High-performance in-memory graph projection (`gds.graph.project`)
  - PageRank and ArticleRank centrality scoring (`gds.pageRank.stream`)
  - Louvain Community Detection (`gds.louvain.stream`)
  - Node similarity and FastRP embedding generation for downstream vector index fusion

### Example: Projecting Graph & Running PageRank
```cypher
-- 1. Create in-memory projection
CALL gds.graph.project(
    'codebaseGraph',
    'Entity',
    {
        CALLS: {type: 'CALLS', orientation: 'NATURAL'},
        IMPORTS: {type: 'IMPORTS', orientation: 'NATURAL'}
    }
);

-- 2. Stream PageRank scores
CALL gds.pageRank.stream('codebaseGraph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS entityName, score
ORDER BY score DESC
LIMIT 15;
```

---

## 3. Neo4j GenAI Plugin (Vector & LLM Integration)
- **Procedures Count:** 2+
- **Primary Use Cases:**
  - Native vector index creation over entity embeddings (`CALL db.index.vector.createNodeIndex(...)`)
  - Exact or Approximate Nearest Neighbor (ANN) search over embeddings
  - Direct integration with local embedding models (Ollama, llama.cpp) and Gemini embeddings

### Example: Creating a Vector Index
```cypher
CREATE VECTOR INDEX entity_embeddings IF NOT EXISTS
FOR (e:Entity) ON (e.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};
```

---

## 4. Neo4j Bloom (Visual Graph Exploration)
- **Procedures Count:** 11
- **Primary Use Cases:**
  - Visual exploration in Neo4j Browser and Neo4j Bloom interfaces
  - Interactive rule-based styling by `community` cluster and node label
  - Search phrases and deep-linking into specific AST subgraphs

---

## 5. Persistent Episodic Memory Schema (`:Entity:Memory`)
Graph Memory maintains persistent memory nodes linked directly to code entities:

```cypher
(:Entity:Memory {
    id: "mem_1729581000000",
    content: "The timeline egui dock panel requires explicit state syncing before rendering ticks.",
    category: "architecture",
    timestamp: datetime(),
    created_at: 1729581000000
})-[:RELATES_TO]->(:Entity {name: "TimelineApp"})
```

This schema enables agents to store design decisions, debugging insights, and architecture constraints that survive across chat sessions and agent restarts.
