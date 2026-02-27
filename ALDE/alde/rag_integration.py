"""
RAG Integration with Agent System

This module integrates the RAG core with the agent-based architecture,
providing RAG context to agents for improved decision-making and document generation.

FEATURES:
    - Automatic context injection into agent prompts
    - RAG-enhanced tool calling for cover letter generation
    - Memory management for conversation context
    - Score-based relevance filtering

INTEGRATION POINTS:
    1. Agent Initialization: RAGContext attached to agent metadata
    2. Tool Calling: vectordb_tool uses RAG internally
    3. Response Generation: Cover letter agent uses @rag tool group
    4. History Logging: RAG context stored in chat history
"""

from __future__ import annotations

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

try:
    from .rag_core import RAGSystem, RetrievalResult, create_rag_system
except ImportError as e:  # allow running directly from the repository root
    msg = str(e)
    if "no known parent package" in msg or "attempted relative import" in msg:
        from rag_core import RAGSystem, RetrievalResult, create_rag_system
    else:
        raise

logger = logging.getLogger(__name__)


class RAGContext:
    """Manages RAG context for an agent conversation."""
    
    def __init__(
        self,
        agent_name: str,
        rag_system: RAGSystem | None = None,
        min_relevance_score: float = 0.5
    ):
        self.agent_name = agent_name
        self.rag_system = rag_system or create_rag_system()
        self.min_relevance_score = min_relevance_score
        
        # Context history for this conversation
        self.context_history: List[dict] = []
        self.last_query: str | None = None
        self.last_results: List[RetrievalResult] = []
    
    def retrieve_context(
        self,
        query: str,
        k: int = 5,
        filter_by_score: bool = True
    ) -> str:
        """
        Retrieve RAG context for a query.
        
        Args:
            query: The query text
            k: Number of results to retrieve
            filter_by_score: Filter by minimum relevance score
        
        Returns:
            Formatted context string for injection into prompts
        """
        # Get results from RAG system
        results = self.rag_system.retrieve(query, k=k)
        
        # Filter by relevance score if enabled
        if filter_by_score:
            results = [
                r for r in results
                if r.relevance_score >= self.min_relevance_score
            ]
        
        # Store for history
        self.last_query = query
        self.last_results = results
        
        # Log retrieval
        self.context_history.append({
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "result_count": len(results),
            "min_score": min((r.relevance_score for r in results), default=0.0)
        })
        
        # Format context
        if not results:
            return "(No relevant documents found for this query)"
        
        context_lines = []
        context_lines.append(f"Retrieved {len(results)} relevant documents:")
        context_lines.append("-" * 60)
        
        for i, result in enumerate(results, 1):
            context_lines.append(f"\n[Document {i}]")
            context_lines.append(f"Source: {result.source}")
            if result.title:
                context_lines.append(f"Title: {result.title}")
            context_lines.append(f"Relevance: {result.relevance_score:.2%}")
            context_lines.append("-" * 40)
            context_lines.append(result.content[:500] + ("..." if len(result.content) > 500 else ""))
        
        return "\n".join(context_lines)
    
    def add_document(self, content: str, source: str, title: str = "") -> bool:
        """Add document to RAG index."""
        try:
            count = self.rag_system.add_document(content, source, title)
            return count > 0
        except Exception as e:
            logger.error(f"Could not add document to RAG: {e}")
            return False
    
    def get_summary(self) -> dict:
        """Get summary of RAG operations in this context."""
        return {
            "agent_name": self.agent_name,
            "retrievals": len(self.context_history),
            "last_query": self.last_query,
            "last_result_count": len(self.last_results),
            "stats": self.rag_system.get_stats()
        }


class AgentRAGManager:
    """Manages RAG contexts for multiple agents."""
    
    def __init__(self, default_store_path: str = "AppData/VSM_1_Data"):
        self.default_store_path = default_store_path
        self.shared_rag_system = create_rag_system(store_path=default_store_path)
        self.agent_contexts: Dict[str, RAGContext] = {}
    
    def get_or_create_context(
        self,
        agent_name: str,
        min_relevance_score: float = 0.5
    ) -> RAGContext:
        """Get or create RAG context for an agent."""
        if agent_name not in self.agent_contexts:
            self.agent_contexts[agent_name] = RAGContext(
                agent_name=agent_name,
                rag_system=self.shared_rag_system,
                min_relevance_score=min_relevance_score
            )
        return self.agent_contexts[agent_name]
    
    def retrieve_for_agent(
        self,
        agent_name: str,
        query: str,
        k: int = 5
    ) -> str:
        """Retrieve RAG context for a specific agent."""
        context = self.get_or_create_context(agent_name)
        return context.retrieve_context(query, k=k)
    
    def add_document_for_agent(
        self,
        agent_name: str,
        content: str,
        source: str,
        title: str = ""
    ) -> bool:
        """Add document accessible to a specific agent."""
        context = self.get_or_create_context(agent_name)
        return context.add_document(content, source, title)
    
    def get_all_summaries(self) -> Dict[str, dict]:
        """Get summaries for all agent contexts."""
        return {
            name: context.get_summary()
            for name, context in self.agent_contexts.items()
        }


# ─────────────────────────── Global Instance ───────────────────────────

_GLOBAL_RAG_MANAGER: AgentRAGManager | None = None


def get_global_rag_manager() -> AgentRAGManager:
    """Get or create global RAG manager."""
    global _GLOBAL_RAG_MANAGER
    if _GLOBAL_RAG_MANAGER is None:
        _GLOBAL_RAG_MANAGER = AgentRAGManager()
    return _GLOBAL_RAG_MANAGER


def init_global_rag_manager(store_path: str = "AppData/VSM_1_Data") -> AgentRAGManager:
    """Initialize global RAG manager with specific store path."""
    global _GLOBAL_RAG_MANAGER
    _GLOBAL_RAG_MANAGER = AgentRAGManager(default_store_path=store_path)
    return _GLOBAL_RAG_MANAGER


# ─────────────────────────── Tool Implementations ───────────────────────────

def vectordb_tool_rag(query: str, k: int = 5) -> Dict[str, Any]:
    """
    Enhanced vectordb_tool that uses RAG internally.
    
    This is a drop-in replacement for the original vectordb_tool in tools.py
    that uses the RAG system instead of direct FAISS subprocess calls.
    
    AGENT USAGE:
        Agent calls vectordb_tool(query="Find covering letter templates", k=3)
        → Returns ranked, scored results
        → Agent includes in response
    
    Args:
        query: Search query text
        k: Number of results to return (1-50)
    
    Returns:
        dict with results and metadata
    """
    try:
        manager = get_global_rag_manager()
        # Use primary agent context for shared RAG
        context = manager.get_or_create_context("_primary_agent")
        results = context.rag_system.retrieve(query, k=min(k, 50))
        
        if not results:
            return {
                "ok": False,
                "error": f"No documents found matching: {query}",
                "result": []
            }
        
        formatted_results = [
            {
                "content": r.content[:500],
                "source": r.source,
                "title": r.title,
                "score": round(float(r.relevance_score), 4),
                "chunk_index": r.chunk_index
            }
            for r in results
        ]
        
        return {
            "ok": True,
            "result": formatted_results,
            "query": query,
            "count": len(formatted_results)
        }
    except Exception as e:
        logger.error(f"vectordb_tool_rag failed: {e}")
        return {
            "ok": False,
            "error": f"RAG query failed: {e}"
        }


def memorydb_tool_rag(query: str, k: int = 5) -> Dict[str, Any]:
    """
    Enhanced memorydb_tool that uses RAG internally (session-specific store).
    
    Similar to vectordb_tool_rag but retrieves from session memory store.
    
    Args:
        query: Search query text
        k: Number of results to return
    
    Returns:
        dict with results and metadata
    """
    try:
        manager = get_global_rag_manager()
        # Use session memory store path
        context = manager.get_or_create_context("_session_memory")
        results = context.rag_system.retrieve(query, k=min(k, 50))
        
        if not results:
            return {
                "ok": False,
                "error": f"No session memory found for: {query}",
                "result": []
            }
        
        formatted_results = [
            {
                "content": r.content[:500],
                "source": r.source,
                "score": round(float(r.relevance_score), 4)
            }
            for r in results
        ]
        
        return {
            "ok": True,
            "result": formatted_results,
            "query": query,
            "count": len(formatted_results)
        }
    except Exception as e:
        logger.error(f"memorydb_tool_rag failed: {e}")
        return {
            "ok": False,
            "error": f"RAG query failed: {e}"
        }


# ─────────────────────────── Example Usage ───────────────────────────────

if __name__ == "__main__":
    print("RAG Agent Integration - Reference Implementation")
    print("=" * 60)
    
    # Initialize RAG manager
    manager = init_global_rag_manager()
    print(f"✓ Initialized RAG manager with shared store")
    
    # Example 1: Add documents
    print("\n[Example 1] Adding sample documents...")
    sample_docs = [
        {
            "title": "Cover Letter Tips",
            "source": "docs/cover_letter_tips.md",
            "content": """
            # How to Write a Great Cover Letter
            
            1. Personalize for each job
            2. Use specific examples from your experience
            3. Match keywords from job description
            4. Show enthusiasm for the role
            5. Keep it concise (3-4 paragraphs)
            
            Good openings:
            - "I was excited to see the opening for..."
            - "With my experience in X, I'm confident I can..."
            """
        },
        {
            "title": "Resume Best Practices",
            "source": "docs/resume_best_practices.md",
            "content": """
            # Resume Best Practices
            
            - Use action verbs (Led, Developed, Implemented)
            - Quantify achievements with numbers
            - Keep format consistent
            - Use industry keywords
            - Tailor for each application
            """
        }
    ]
    
    for doc in sample_docs:
        success = manager.add_document_for_agent(
            "_cover_letter_generator",
            doc["content"],
            doc["source"],
            doc["title"]
        )
        print(f"  {'✓' if success else '✗'} Added: {doc['title']}")
    
    # Example 2: Retrieve context
    print("\n[Example 2] Retrieving context for query...")
    query = "How to write a compelling cover letter for a tech role"
    context = manager.retrieve_for_agent("_cover_letter_generator", query, k=2)
    print(f"Query: {query}")
    print(f"Results:\n{context[:300]}...")
    
    # Example 3: Get summaries
    print("\n[Example 3] RAG System Summary:")
    summaries = manager.get_all_summaries()
    for agent, summary in summaries.items():
        print(f"\n  Agent: {agent}")
        print(f"    Retrievals: {summary['retrievals']}")
        print(f"    Chunks indexed: {summary['stats']['total_chunks']}")
