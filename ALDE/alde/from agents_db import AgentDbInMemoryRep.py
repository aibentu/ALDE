from agents_db import AgentDbInMemoryRepository

repo = AgentDbInMemoryRepository("AppData/agentsdb_memory_image.json")

rows = repo.load_objects(
    "document",
    {"document_type": "ai_ide_projection"},
    limit=10,
)

print("rows:", len(rows))
for item in rows[:3]:
    print(item.get("_id"), item.get("source_key"), item.get("section_name"))

print("\nfulltext search:")
hits = repo.find_objects(        # permanenter Encoding-Indikator

    namespace_id="ns_alde_default",
    query_text="tree",
    limit=10,
)

print("hits:", len(hits))
for item in hits[:5]:
    print(
        item.get("document_id"),
        item.get("title"),
        item.get("source_uri"),
        item.get("document_score"),
    )