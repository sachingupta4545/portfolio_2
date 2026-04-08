from qdrant_client import QdrantClient
import json

# Connect to local qdrant_data folder
client = QdrantClient(path="./qdrant_data")

# List all collections
collections = client.get_collections().collections
print("=" * 50)
print(f"  Collections Found: {len(collections)}")
print("=" * 50)

for col in collections:
    name = col.name
    info = client.get_collection(name)
    count = info.points_count

    print(f"\n📁 Collection: '{name}'")
    print(f"   Total Points (chunks): {count}")
    print(f"   Vector size: {info.config.params.vectors.size}")

    if count == 0:
        print("   ⚠️  Collection is empty — no resume uploaded yet.")
        continue

    # Fetch first 10 points
    points, _ = client.scroll(
        collection_name=name,
        limit=10,
        with_payload=True,
        with_vectors=False
    )

    print(f"\n   --- Showing first {len(points)} point(s) ---")
    for i, point in enumerate(points, 1):
        payload = point.payload or {}
        doc_text = payload.get("document", "")[:200]  # Show first 200 chars
        metadata = {k: v for k, v in payload.items() if k != "document"}
        print(f"\n   [{i}] ID: {point.id}")
        print(f"       Metadata : {json.dumps(metadata, indent=8)}")
        print(f"       Text     : {doc_text}...")

print("\n" + "=" * 50)
print("  Done.")
print("=" * 50)
