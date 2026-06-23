# src/tools/rag_tool.py
"""
RAG search tool for Nova — searches indexed PDF documents.
"""

import json
from typing import Optional
from src.tools import Tool


def create_rag_tool(retriever) -> Tool:
    """Create a Tool wired to the given RAGRetriever instance."""

    def _search_documents(query: str, top_k: int = 4, filename: Optional[str] = None) -> str:
        """Search indexed PDF documents for relevant information."""
        try:
            # Optionally filter by filename → find doc_id
            doc_id = None
            if filename:
                for doc in retriever.list_documents():
                    if filename.lower() in doc.get("filename", "").lower():
                        doc_id = doc["doc_id"]
                        break

            results = retriever.search(query, top_k=top_k, doc_id=doc_id)
            if not results:
                docs = retriever.list_documents()
                if not docs:
                    return json.dumps({
                        "results": [],
                        "note": "No documents have been indexed yet. Upload a PDF first via the Documents tab.",
                    })
                return json.dumps({
                    "results": [],
                    "note": f"No relevant content found for '{query}' in indexed documents.",
                    "indexed_documents": [d["filename"] for d in docs],
                })

            return json.dumps({
                "query": query,
                "results": [
                    {
                        "text": r["text"],
                        "source": r["filename"],
                        "relevance_score": r["score"],
                    }
                    for r in results
                ],
                "count": len(results),
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Document search failed: {str(e)}"})

    def _list_documents() -> str:
        """List all indexed documents."""
        try:
            docs = retriever.list_documents()
            if not docs:
                return json.dumps({"documents": [], "note": "No documents indexed."})
            return json.dumps({
                "documents": [
                    {"filename": d["filename"], "chunks": d["chunk_count"], "indexed_at": d["indexed_at"]}
                    for d in docs
                ],
                "count": len(docs),
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    search_tool = Tool(
        name="search_documents",
        description=(
            "Search through uploaded PDF documents to answer questions about their content. "
            "Use this when the user asks about something that might be in a document they uploaded. "
            "Returns the most relevant passages with source filenames."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language question or search query about the document content.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of relevant passages to return (default 4, max 8).",
                },
                "filename": {
                    "type": "string",
                    "description": "Optional: restrict search to a specific document by filename.",
                },
            },
            "required": ["query"],
        },
        handler=_search_documents,
        requires_confirmation=False,
    )

    list_tool = Tool(
        name="list_documents",
        description="List all PDF documents that have been uploaded and indexed for search.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_list_documents,
        requires_confirmation=False,
    )

    # Return the primary search tool; list_documents can be registered separately
    # (server.py registers both via a small extension below)
    search_tool._list_companion = list_tool
    return search_tool
