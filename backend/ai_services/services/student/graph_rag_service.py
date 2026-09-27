"""GraphRAG service for the student AI assistant."""

from __future__ import annotations

from platform_ai.llm import llm_facade
from platform_ai.rag import student_learning_rag
from platform_ai.rag.runtime import student_graphrag_runtime
from ai_services.services.demo_fallback import demo_mode_enabled, mark_demo_payload
from ai_services.services.student.graph_rag_support import answer_graph_question, search_graph_points


class StudentGraphRAGService:
    """Provide graph search and graph-grounded Q&A capabilities."""

    def search_points(self, *, user, course_id: int, query: str, limit: int = 8) -> dict[str, object]:
        """Search knowledge points within the current course graph."""
        return search_graph_points(user=user, course_id=course_id, query=query, limit=limit)

    def ask(self, *, user, course_id: int, question: str, point_id: int | None = None) -> dict[str, object]:
        """Run GraphRAG question answering under the current course context."""
        result = answer_graph_question(user=user, course_id=course_id, question=question, point_id=point_id)
        if demo_mode_enabled() and not llm_facade.is_available:
            return mark_demo_payload(result)
        return result


student_graph_rag_service = StudentGraphRAGService()
