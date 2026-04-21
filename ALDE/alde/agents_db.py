from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import socketserver
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


_AGENTSDB_SOCKET_SERVER_LOCK = threading.RLock()
_AGENTSDB_SOCKET_SERVER_STATE: dict[tuple[str, int], dict[str, Any]] = {}
_LOGGER = logging.getLogger(__name__)
_AGENTSDB_CONNECTION_CONFIG_CACHE: dict[str, Any] | None = None


def _load_json_object_file(path: Path) -> dict[str, Any]:
    try:
        loaded_payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(loaded_payload) if isinstance(loaded_payload, Mapping) else {}


def _load_agentsdb_connection_config() -> dict[str, Any]:
    global _AGENTSDB_CONNECTION_CONFIG_CACHE
    if _AGENTSDB_CONNECTION_CONFIG_CACHE is not None:
        return dict(_AGENTSDB_CONNECTION_CONFIG_CACHE)

    env_config_path = str(os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_CONFIG_PATH", "")).strip()
    candidate_paths: list[Path] = []
    if env_config_path:
        raw_path = Path(env_config_path)
        if raw_path.is_absolute():
            candidate_paths.append(raw_path)
        else:
            base_paths = [Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]]
            candidate_paths.extend((base_path / raw_path).resolve() for base_path in base_paths)
    else:
        project_root = Path(__file__).resolve().parents[2]
        package_root = Path(__file__).resolve().parents[1]
        candidate_paths.extend(
            [
                (project_root / "AppData" / "agentsdb_connection.json").resolve(),
                (package_root / "AppData" / "agentsdb_connection.json").resolve(),
            ]
        )

    config_payload: dict[str, Any] = {}
    for path in candidate_paths:
        if not path.exists() or not path.is_file():
            continue
        config_payload = _load_json_object_file(path)
        if config_payload:
            break

    _AGENTSDB_CONNECTION_CONFIG_CACHE = dict(config_payload)
    return dict(_AGENTSDB_CONNECTION_CONFIG_CACHE)


def _connection_config_value(config_payload: Mapping[str, Any], key_candidates: Sequence[str]) -> str:
    for key_name in key_candidates:
        value = config_payload.get(str(key_name))
        if value is None:
            continue
        normalized_value = str(value).strip()
        if normalized_value:
            return normalized_value
    return ""


def _load_agentsdb_uri_from_connection_config(config_payload: Mapping[str, Any]) -> str:
    configured_uri = _connection_config_value(config_payload, ("agents_db_uri", "agentsdb_uri", "uri", "socket_uri"))
    if configured_uri:
        return configured_uri
    host_value = _connection_config_value(config_payload, ("host", "hostname")) or "127.0.0.1"
    port_value = _connection_config_value(config_payload, ("port",)) or "2331"
    try:
        resolved_port = int(port_value)
    except Exception:
        resolved_port = 2331
    return f"agentsdb://{host_value}:{resolved_port}"


def _is_true_env(value: str | None, default: bool = True) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return bool(default)
    return normalized not in {"0", "false", "no", "off"}


def _is_local_socket_host(host: str) -> bool:
    normalized_host = str(host or "").strip().lower()
    return normalized_host in {"127.0.0.1", "localhost", "::1"}


def _socket_endpoint_reachable(host: str, port: int, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=max(float(timeout_seconds), 0.2)):
            return True
    except Exception:
        return False


def _ensure_local_agentsdb_socket_server(agents_db_uri: str, timeout_seconds: float = 3.0) -> bool:
    connection_config = _load_agentsdb_connection_config()
    auto_start_value = str(os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_AUTO_START", "")).strip()
    if not auto_start_value:
        auto_start_value = _connection_config_value(connection_config, ("auto_start", "autostart", "socket_auto_start"))
    if not _is_true_env(auto_start_value, default=True):
        return False
    parsed_uri = urlparse(str(agents_db_uri or "").strip())
    if str(parsed_uri.scheme or "").strip().lower() != "agentsdb":
        return False
    resolved_host = str(parsed_uri.hostname or "127.0.0.1").strip() or "127.0.0.1"
    resolved_port = int(parsed_uri.port or 2331)
    if not _is_local_socket_host(resolved_host):
        return False
    if _socket_endpoint_reachable(resolved_host, resolved_port, timeout_seconds):
        return True

    server_key = (resolved_host, resolved_port)
    with _AGENTSDB_SOCKET_SERVER_LOCK:
        server_state = _AGENTSDB_SOCKET_SERVER_STATE.get(server_key)
        if server_state is not None:
            server_thread = server_state.get("thread")
            if isinstance(server_thread, threading.Thread) and server_thread.is_alive():
                pass
            else:
                _AGENTSDB_SOCKET_SERVER_STATE.pop(server_key, None)
                server_state = None
        if server_state is None:
            try:
                service = AgentDbSocketServerService.load_from_env()
                socket_server = _AgentDbSocketTCPServer((resolved_host, resolved_port), _AgentDbSocketRequestHandler, service)
            except Exception as exc:
                _LOGGER.warning(
                    "agentsdb auto-start failed during server setup for %s:%s (%s: %s)",
                    resolved_host,
                    resolved_port,
                    type(exc).__name__,
                    exc,
                )
                return _socket_endpoint_reachable(resolved_host, resolved_port, timeout_seconds)

            server_thread = threading.Thread(target=socket_server.serve_forever, name=f"agentsdb-socket:{resolved_host}:{resolved_port}", daemon=True)
            server_thread.start()
            _AGENTSDB_SOCKET_SERVER_STATE[server_key] = {
                "server": socket_server,
                "thread": server_thread,
            }
            _LOGGER.info(
                "agentsdb auto-start: started local socket server on %s:%s",
                resolved_host,
                resolved_port,
            )

    deadline = time.monotonic() + max(float(timeout_seconds), 0.5)
    while time.monotonic() < deadline:
        if _socket_endpoint_reachable(resolved_host, resolved_port, timeout_seconds=0.25):
            return True
        time.sleep(0.05)
    return _socket_endpoint_reachable(resolved_host, resolved_port, timeout_seconds=0.25)

def _is_agentsdb_socket_uri(uri: str | None) -> bool:
    return str(uri or "").strip().lower().startswith("agentsdb://")


def _json_safe_object(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe_object(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe_object(item) for item in value]
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _deepcopy_object(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _deepcopy_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deepcopy_object(item) for item in value]
    return value


def _dataclass_payload(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _dataclass_payload(asdict(value))
    if isinstance(value, dict):
        return {str(key): _dataclass_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dataclass_payload(item) for item in value]
    return value


def _normalize_document_object_name(obj_name: str | None) -> str:
    normalized_obj_name = str(obj_name or "document").strip().lower().replace("-", "_")
    alias_map = {
        "job_postings": "job_posting",
        "profiles": "profile",
        "cover_letters": "cover_letter",
        "documents": "document",
    }
    if normalized_obj_name in alias_map:
        return alias_map[normalized_obj_name]
    if normalized_obj_name.endswith("ies"):
        return f"{normalized_obj_name[:-3]}y"
    if normalized_obj_name.endswith("s") and len(normalized_obj_name) > 1:
        return normalized_obj_name[:-1]
    return normalized_obj_name or "document"


def _stable_sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _first_non_empty_string(values: Iterable[Any]) -> str | None:
    for value in values:
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None


def _first_number(values: Iterable[Any]) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized_value = value.strip()
            if not normalized_value:
                continue
            try:
                return float(normalized_value)
            except Exception:
                continue
    return None


def _mapping_value(payload: Mapping[str, Any], key: str) -> Any:
    current: Any = payload
    for segment in str(key or "").split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current


def _slugify_object_name(value: Any, *, fallback_prefix: str = "value") -> str:
    normalized_value = str(value or "").strip().lower()
    slug_value = re.sub(r"[^a-z0-9]+", "_", normalized_value).strip("_")
    if slug_value:
        return slug_value
    return f"{fallback_prefix}_{_stable_sha256(str(value or ''))[:12]}"


def _load_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized_value = value.strip()
        return [normalized_value] if normalized_value else []
    if isinstance(value, Mapping):
        values: list[str] = []
        for key in ("name", "label", "value", "title", "text"):
            values.extend(_load_string_list(value.get(key)))
        return values
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values: list[str] = []
        for item in value:
            values.extend(_load_string_list(item))
        return values
    normalized_value = str(value).strip()
    return [normalized_value] if normalized_value else []


def _load_bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"true", "1", "yes", "ja", "remote"}:
            return True
        if normalized_value in {"false", "0", "no", "nein"}:
            return False
    return None


def _normalize_pattern_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _load_type_key_from_pattern(
    value: Any,
    *,
    fallback_type_key: str,
    type_key_pattern_map: Mapping[str, Sequence[str]] | None = None,
) -> str:
    normalized_value = _normalize_pattern_key(value)
    if not normalized_value:
        return fallback_type_key
    for type_key, pattern_value_list in dict(type_key_pattern_map or {}).items():
        for pattern_value in pattern_value_list:
            if normalized_value == _normalize_pattern_key(pattern_value):
                return str(type_key).strip() or fallback_type_key
    return fallback_type_key


def _build_namespace_object_from_runtime_config(
    runtime_config: RuntimeConfigObject,
    *,
    handoff_metadata: Mapping[str, Any] | None = None,
    handoff_payload: Mapping[str, Any] | None = None,
) -> NamespaceObject:
    tenant_id = str(
        (handoff_payload or {}).get("tenant_id")
        or (handoff_metadata or {}).get("tenant_id")
        or runtime_config.tenant_id
    ).strip() or runtime_config.tenant_id
    namespace_id = str(
        (handoff_payload or {}).get("knowledge_namespace_id")
        or (handoff_metadata or {}).get("knowledge_namespace_id")
        or runtime_config.namespace_id
    ).strip() or runtime_config.namespace_id
    namespace_slug = str(
        (handoff_payload or {}).get("knowledge_namespace_slug")
        or (handoff_metadata or {}).get("knowledge_namespace_slug")
        or runtime_config.namespace_slug
    ).strip() or runtime_config.namespace_slug
    namespace_name = str(
        (handoff_payload or {}).get("knowledge_namespace_name")
        or (handoff_metadata or {}).get("knowledge_namespace_name")
        or runtime_config.namespace_name
    ).strip() or runtime_config.namespace_name
    return NamespaceObject(
        id=namespace_id,
        tenant_id=tenant_id,
        slug=namespace_slug,
        name=namespace_name,
        description="Optional MongoDB mirror of the ALDE document pipeline.",
        index_backend=runtime_config.index_backend,
        default_embedding_model=runtime_config.default_embedding_model,
        default_embedding_dimension=runtime_config.default_embedding_dimension,
        metadata={"source": "alde_document_pipeline"},
    )


def _demo_dataset_timestamp() -> datetime:
    return datetime.now( tzinfo=UTC)


def _demo_embedding_vector(seed: str, dimension: int = 8) -> list[float]:
    digest_source = str(seed or "demo-seed").encode("utf-8")
    vector: list[float] = []
    while len(vector) < max(1, int(dimension)):
        digest = hashlib.sha256(digest_source).digest()
        for byte in digest:
            vector.append(round((float(byte) / 127.5) - 1.0, 6))
            if len(vector) >= max(1, int(dimension)):
                break
        digest_source = digest
    return vector


@dataclass(slots=True)
class NamespaceObject:
    id: str
    tenant_id: str
    slug: str
    name: str
    default_embedding_model: str
    default_embedding_dimension: int
    description: str = ""
    index_backend: str = "faiss"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class EntityAliasObject:
    alias: str
    alias_type: str = "synonym"
    locale: str | None = None
    confidence: float = 1.0
    source_document_id: str | None = None
    created_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class EntityObject:
    id: str
    tenant_id: str
    namespace_id: str
    entity_type: str
    canonical_name: str
    external_key: str | None = None
    correlation_id: str | None = None
    status: str = "active"
    summary: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    aliases: list[EntityAliasObject] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class EntityMentionObject:
    entity_id: str
    mention_text: str
    extractor: str = "manual"
    confidence: float = 1.0
    char_start: int | None = None
    char_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class BlockObject:
    block_id: str
    block_no: int
    content: str
    block_kind: str = "chunk"
    heading: str | None = None
    token_count: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    parent_block_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    mentions: list[EntityMentionObject] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class DocumentObject:
    id: str
    tenant_id: str
    namespace_id: str
    document_type: str
    title: str
    source_uri: str
    content_sha256: str
    source_system: str = "local"
    mime_type: str = "text/plain"
    language_code: str | None = None
    correlation_id: str | None = None
    author_entity_id: str | None = None
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: list[BlockObject] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class RelationEvidenceObject:
    block_id: str
    evidence_role: str = "supporting"
    created_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class EntityRelationObject:
    id: str
    tenant_id: str
    namespace_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    direction: str = "directed"
    weight: float = 1.0
    confidence: float = 1.0
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: list[RelationEvidenceObject] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class EmbeddingObject:
    tenant_id: str
    namespace_id: str
    model_id: str
    owner_type: str
    owner_id: str
    content_sha256: str
    dimension: int
    index_namespace: str
    index_item_key: str
    chunk_hash: str | None = None
    embedding: list[float] | None = None
    index_backend: str = "faiss"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class RetrievalResultObject:
    rank_no: int
    result_type: str
    result_id: str
    source_stage: str
    chosen: bool = True
    lexical_score: float | None = None
    vector_score: float | None = None
    graph_score: float | None = None
    rerank_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalRunObject:
    id: str
    tenant_id: str
    namespace_id: str
    query_text: str
    requested_k: int
    lexical_k: int | None = None
    graph_hops: int | None = None
    vector_k: int | None = None
    rerank_strategy: str = "none"
    correlation_id: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    results: list[RetrievalResultObject] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class DispatcherRunObject:
    id: str
    tenant_id: str
    namespace_id: str
    correlation_id: str
    processing_state: str
    processed: bool
    failed_reason: str | None = None
    source_system: str = "alde_dispatcher"
    dispatcher_db_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)


@dataclass(slots=True)
class RuntimeConfigObject:
    agents_db_uri: str
    database_name: str = "alde_knowledge"
    tenant_id: str = "tenant_default"
    namespace_id: str = "ns_alde_default"
    namespace_slug: str = "alde-default"
    namespace_name: str = "ALDE Default Knowledge"
    default_embedding_model: str = "text-embedding-3-large"
    default_embedding_dimension: int = 3072
    index_backend: str = "faiss"

    @property
    def mongo_uri(self) -> str:
        return self.agents_db_uri

    @mongo_uri.setter
    def mongo_uri(self, value: str) -> None:
        self.agents_db_uri = str(value)


@dataclass(slots=True)
class MappingBlockSeedObject:
    section_key: str
    block_id: str
    block_no: int
    heading: str
    content: str
    block_kind: str = "chunk"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MappingSeedEntityObject:
    seed_key: str
    type_key: str
    canonical_name: str
    section_key: str | None = None
    relation_type_key: str | None = None
    confidence: float = 0.95
    mention_text: str | None = None
    summary: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


TECHNICAL_TYPE_KEY_PATTERN_MAP: dict[str, tuple[str, ...]] = {
    "tool": ("jira", "topdesk", "servicenow"),
    "framework": ("itil", "scrum", "kanban"),
    "database": ("postgresql", "postgres", "oracle", "mysql", "mongodb"),
    "protocol": ("tcp/ip", "tcpip", "http", "https", "http(s)", "rdp", "ssh"),
}


OBJECT_MAPPING_PATTERN_BY_NAME: dict[str, dict[str, Any]] = {
    "job_posting": {
        "subject_pattern": {
            "seed_key": "subject",
            "type_key": "job_posting",
            "section_key": "header",
            "value_path_list": ("job_title", "title"),
            "summary": "Primary object mapped from the parsed result.",
            "attribute_path_map": {
                "position_type": "position.type",
                "position_level": "position.level",
                "department": "position.department",
                "remote": "location_details.remote",
            },
        },
        "section_pattern_list": [
            {
                "section_key": "header",
                "heading": "Object Header",
                "section_type_key": "header",
                "block_kind": "section",
                "field_line_list": [
                    {"label": "Title", "path": "job_title"},
                    {"label": "Organization", "path": "company_name"},
                    {"label": "Location", "path_list": ("company_info.location", "location_details.office")},
                    {"label": "Object Type", "path": "position.type"},
                    {"label": "Object Level", "path": "position.level"},
                    {"label": "Department", "path": "position.department"},
                ],
            },
            {
                "section_key": "requirements",
                "heading": "Requirements",
                "section_type_key": "requirements",
                "field_line_list": [
                    {"label": "Education", "path": "requirements.education"},
                    {"label": "Experience Years", "path": "requirements.experience_years"},
                    {"label": "Experience", "path": "requirements.experience_description"},
                ],
                "group_line_list": [
                    {"label": "Technical Skills", "path": "requirements.technical_skills"},
                    {"label": "Soft Skills", "path": "requirements.soft_skills"},
                    {"label": "Languages", "path": "requirements.languages"},
                ],
            },
            {
                "section_key": "responsibilities",
                "heading": "Responsibilities",
                "section_type_key": "responsibilities",
                "group_line_list": [
                    {"label": "Responsibilities", "path": "responsibilities", "emit_label_only_when_items": False},
                ],
            },
            {
                "section_key": "offer",
                "heading": "Offer",
                "section_type_key": "offer",
                "group_line_list": [
                    {"label": "Benefits", "path": "compensation.benefits"},
                    {"label": "What We Offer", "path": "what_we_offer"},
                ],
            },
            {
                "section_key": "application",
                "heading": "Application",
                "section_type_key": "application",
                "field_line_list": [
                    {"label": "Deadline", "path": "application.deadline"},
                    {"label": "Application Link", "path": "application.application_link"},
                    {"label": "Contact Email", "path": "application.contact_email"},
                    {"label": "Contact Person", "path": "application.contact_person"},
                ],
            },
        ],
        "entity_pattern_list": [
            {
                "seed_key": "organization",
                "type_key": "organization",
                "section_key": "header",
                "relation_type_key": "offered_by",
                "value_path_list": ("company_name",),
                "source_field": "company_name",
                "summary": "Organization associated with the mapped object.",
                "attribute_path_map": {
                    "industry": "company_info.industry",
                    "size": "company_info.size",
                    "website": "company_info.website",
                },
            },
            {
                "seed_key": "location",
                "type_key": "location",
                "section_key": "header",
                "relation_type_key": "located_in",
                "value_path_list": ("company_info.location", "location_details.office"),
                "source_field": "company_info.location",
                "summary": "Location associated with the mapped object.",
                "attribute_path_map": {
                    "office": "location_details.office",
                    "remote": "location_details.remote",
                    "travel_required": "location_details.travel_required",
                },
            },
            {
                "seed_key": "employment_type",
                "type_key": "employment_type",
                "section_key": "header",
                "relation_type_key": "employment_type",
                "value_path_list": ("position.type",),
                "source_field": "position.type",
                "summary": "Employment type associated with the mapped object.",
            },
            {
                "seed_key": "contact_person",
                "type_key": "person",
                "section_key": "application",
                "relation_type_key": "application_contact",
                "value_path_list": ("application.contact_person",),
                "source_field": "application.contact_person",
                "summary": "Contact person associated with the application flow.",
            },
        ],
        "collection_entity_pattern_list": [
            {
                "seed_key_prefix": "technical_requirement",
                "section_key": "requirements",
                "collection_path": "requirements.technical_skills",
                "source_field": "requirements.technical_skills",
                "fallback_type_key": "skill",
                "type_key_pattern_map": TECHNICAL_TYPE_KEY_PATTERN_MAP,
                "relation_type_key_map": {
                    "skill": "requires_skill",
                    "tool": "requires_tool",
                    "framework": "requires_framework_knowledge",
                    "database": "requires_database_knowledge",
                    "protocol": "requires_protocol_knowledge",
                },
                "summary_prefix": "Technical capability associated with the mapped object.",
            },
            {
                "seed_key_prefix": "competency_requirement",
                "section_key": "requirements",
                "collection_path": "requirements.soft_skills",
                "source_field": "requirements.soft_skills",
                "fallback_type_key": "competency",
                "relation_type_key_map": {
                    "competency": "requires_competency",
                },
                "summary_prefix": "Behavioral capability associated with the mapped object.",
            },
            {
                "seed_key_prefix": "language_requirement",
                "section_key": "requirements",
                "collection_path": "requirements.languages",
                "source_field": "requirements.languages",
                "fallback_type_key": "language",
                "relation_type_key_map": {
                    "language": "requires_language",
                },
                "summary_prefix": "Language capability associated with the mapped object.",
            },
        ],
    },
}

class KnowledgeRepository():
    """Knowledge repository mirroring the ALDE hybrid knowledge model."""
    _OBJECT_COLLECTION_MAP = {
        "namespace": "knowledge_namespaces",
        "entity": "entities",
        "document": "documents",
        "relation": "entity_relations",
        "embedding": "embeddings",
        "retrieval_run": "retrieval_runs",
        "dispatcher_run": "dispatcher_runs",
    }

    def __init__(self, database: Mapping[str, Any] | None = None, *, image_path: str | None = None) -> None:
        self._lock = threading.RLock()
        self._image_path = str(image_path or "").strip() or None
        self._collections: dict[str, dict[str, dict[str, Any]]] = {
            collection_name: {}
            for collection_name in self._OBJECT_COLLECTION_MAP.values()
        }
        self._index_objects: dict[str, Any] = {}
        self._load_from_mapping(database)
        self._load_image()

    def _load_from_mapping(self, database: Mapping[str, Any] | None) -> None:
        if not isinstance(database, Mapping):
            return
        collections_payload = database.get("collections") if isinstance(database.get("collections"), Mapping) else database
        if not isinstance(collections_payload, Mapping):
            return
        for collection_name, collection_payload in collections_payload.items():
            normalized_collection_name = str(collection_name or "").strip()
            if normalized_collection_name not in self._collections:
                continue
            if not isinstance(collection_payload, Mapping):
                continue
            self._collections[normalized_collection_name] = {
                str(record_id): dict(record_payload)
                for record_id, record_payload in collection_payload.items()
                if isinstance(record_payload, Mapping)
            }

    def _load_image(self) -> None:
        if not self._image_path:
            return
        path = os.path.abspath(os.path.expanduser(self._image_path))
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as image_file:
                image_payload = json.load(image_file)
        except Exception:
            return
        collections_payload = image_payload.get("collections") if isinstance(image_payload, Mapping) else None
        if not isinstance(collections_payload, Mapping):
            return
        self._load_from_mapping({"collections": collections_payload})

    def _flush_image(self) -> None:
        if not self._image_path:
            return
        path = os.path.abspath(os.path.expanduser(self._image_path))
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "schema": "agentsdb_repository_image_v1",
            "updated_at": _now_utc().isoformat(),
            "collections": _json_safe_object(self._collections),
            "index_objects": _json_safe_object(self._index_objects),
        }
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as image_file:
            json.dump(payload, image_file, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    @classmethod
    def create_from_uri(cls, agents_db_uri: str, database_name: str = "alde_knowledge") -> KnowledgeRepository:
        _ = (agents_db_uri, database_name)
        image_path = str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_MEMORY_IMAGE_PATH", "")
            or os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_FLUSH_IMAGE_PATH", "")
            or os.path.join("AppData", "agentsdb_memory_image.json")
        ).strip()
        return cls(image_path=image_path)

    def load_collection(self, object_name: str) -> dict[str, dict[str, Any]]:
        collection_name = self._OBJECT_COLLECTION_MAP[str(object_name).strip().lower()]
        return self._collections[collection_name]

    def ensure_index_objects(self) -> None:
        self._index_objects["knowledge_namespaces"] = {
        "slug":1,
            "unique": True,
            "name": "uq_knowledge_namespaces_tenant_slug",
        }
        self._index_objects["entities_unique"] = {
           "namespace_id": 1, 
           "entity_type": 1, 
           "canonical_name": 1,
            "unique": True,
            "name": "uq_entities_namespace_type_name",
        }

        self._index_objects["entities_text"] = {
          "canonical_name": "text", "summary": "text", "aliases.alias": "text",
            "default_language": "none",
            "name": "fts_entities",
        }
        self._index_objects["documents_unique"] = {
            "namespace_id": 1, "content_sha256": 1,
            "unique": True,
            "name": "uq_documents_namespace_sha",
        }
        self._index_objects["documents_text"] = {
          "title": "text", "summary": "text", "blocks.heading": "text", "blocks.content": "text",
            "default_language": "none",
            "name": "fts_documents_blocks",
        }
        self._index_objects["entity_relations"] = {
            "namespace_id": 1, "source_entity_id": 1, "target_entity_id": 1,
            "name": "ix_entity_relations_source_target",
        }
        self._index_objects["embeddings"] = {
            "namespace_id": 1, "owner_type": 1, "owner_id": 1, "model_id": 1, "content_sha256": 1,
            "unique": True,
            "name": "uq_embeddings_owner_model_sha",
        }
        self._index_objects["retrieval_runs"] = {
            "namespace_id": 1, "correlation_id": 1,
            "name": "ix_retrieval_runs_namespace_correlation_id",
        }
        self._index_objects["dispatcher_runs_unique"] = {
            "namespace_id": 1, "correlation_id": 1,
            "unique": True,
            "name": "uq_dispatcher_runs_namespace_correlation_id",
        }
        self._index_objects["dispatcher_runs_state"] = {
            "namespace_id": 1, "processing_state": 1, "updated_at": -1,
            "name": "ix_dispatcher_runs_namespace_state_updated_at",
        }
        self._flush_image()

    def upsert_object(self, object_name: str, object_id: str, object_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._lock:
            collection = self.load_collection(object_name)
            existing_payload = collection.get(str(object_id)) if isinstance(collection.get(str(object_id)), Mapping) else {}
            payload = _deepcopy_object(dict(existing_payload))
            payload.update(_deepcopy_object(dict(object_payload)))
            payload["_id"] = str(object_id)
            payload["updated_at"] = payload.get("updated_at") or _now_utc().isoformat()
            payload["created_at"] = payload.get("created_at") or existing_payload.get("created_at") or payload["updated_at"]
            collection[str(object_id)] = dict(payload)
            self._flush_image()
            return payload

    def load_object(self, object_name: str, object_id: str) -> dict[str, Any] | None:
        with self._lock:
            collection = self.load_collection(object_name)
            payload = collection.get(str(object_id))
            return dict(payload) if isinstance(payload, Mapping) else None

    def load_objects(self, object_name: str, object_filter: Mapping[str, Any] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            collection = self.load_collection(object_name)
            filter_payload = dict(object_filter or {})
            result_payload_list: list[dict[str, Any]] = []
            for object_payload in collection.values():
                if not isinstance(object_payload, Mapping):
                    continue
                if any(object_payload.get(key) != value for key, value in filter_payload.items()):
                    continue
                result_payload_list.append(dict(object_payload))
                if len(result_payload_list) >= max(1, int(limit)):
                    break
            return result_payload_list

    def find_objects(self, *, namespace_id: str, query_text: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized_query = str(query_text or "").strip().lower()
        if not normalized_query:
            return []
        with self._lock:
            collection = self._collections["documents"]
            result_payload_list: list[dict[str, Any]] = []
            for document_payload in collection.values():
                if not isinstance(document_payload, Mapping):
                    continue
                if str(document_payload.get("namespace_id") or "").strip() != str(namespace_id):
                    continue
                haystack = json.dumps(_json_safe_object(document_payload), ensure_ascii=False).lower()
                if normalized_query not in haystack:
                    continue
                result_payload_list.append(
                    {
                        "document_id": str(document_payload.get("_id") or ""),
                        "title": str(document_payload.get("title") or ""),
                        "source_uri": str(document_payload.get("source_uri") or ""),
                        "document_score": 1.0,
                        "block": {},
                    }
                )
                if len(result_payload_list) >= max(1, int(limit)):
                    break
            return result_payload_list

    def load_relation_graph(self, *, namespace_id: str, source_entity_id: str, max_depth: int = 2) -> list[dict[str, Any]]:
        max_hops = max(0, int(max_depth))
        with self._lock:
            relation_collection = self._collections["entity_relations"]
            visited_sources = {str(source_entity_id)}
            frontier = {str(source_entity_id)}
            result_payload_list: list[dict[str, Any]] = []
            for _ in range(max_hops + 1):
                if not frontier:
                    break
                next_frontier: set[str] = set()
                for relation_payload in relation_collection.values():
                    if not isinstance(relation_payload, Mapping):
                        continue
                    if str(relation_payload.get("namespace_id") or "") != str(namespace_id):
                        continue
                    src = str(relation_payload.get("source_entity_id") or "")
                    tgt = str(relation_payload.get("target_entity_id") or "")
                    if src not in frontier:
                        continue
                    result_payload_list.append(dict(relation_payload))
                    if tgt and tgt not in visited_sources:
                        next_frontier.add(tgt)
                visited_sources.update(next_frontier)
                frontier = next_frontier
            return result_payload_list

    def build_vector_search_pipeline(
        self,
        *,
        query_vector: Sequence[float],
        namespace_id: str,
        owner_type: str = "block",
        limit: int = 10,
        num_candidates: int = 100,
        index_name: str = "embedding_cosine",
    ) -> list[dict[str, Any]]:
        return [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": "embedding",
                    "queryVector": list(query_vector),
                    "numCandidates": max(1, int(num_candidates)),
                    "limit": max(1, int(limit)),
                    "filter": {"namespace_id": namespace_id, "owner_type": owner_type},
                },
            },
            {
                "$project": {
                    "_id": 0,
                    "owner_id": 1,
                    "owner_type": 1,
                    "model_id": 1,
                    "score": {"$meta": "vectorSearchScore"},
                    "index_backend": 1,
                    "index_namespace": 1,
                    "index_item_key": 1,
                },
            },
        ]


class AgentDbSocketRepository:
    """Knowledge repository backed by a custom agentsdb socket endpoint."""

    _OBJECT_COLLECTION_MAP = KnowledgeRepository._OBJECT_COLLECTION_MAP

    def __init__(self, agents_db_uri: str, database_name: str = "alde_knowledge", timeout_seconds: float = 5.0) -> None:
        self._agents_db_uri = str(agents_db_uri or "").strip()
        self._database_name = str(database_name or "alde_knowledge").strip() or "alde_knowledge"
        self._timeout_seconds = max(float(timeout_seconds), 0.5)
        parsed_uri = urlparse(self._agents_db_uri)
        self._host = str(parsed_uri.hostname or "127.0.0.1")
        self._port = int(parsed_uri.port or 1998)

    @classmethod
    def create_from_uri(
        cls,
        agents_db_uri: str,
        database_name: str = "alde_knowledge",
        timeout_seconds: float = 5.0,
    ) -> AgentDbSocketRepository:
        return cls(
            agents_db_uri=agents_db_uri,
            database_name=database_name,
            timeout_seconds=timeout_seconds,
        )

    def _request_object(self, action_name: str, action_payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        request_payload = {
            "cmd": action_name,
            "database_name": self._database_name,
            "payload": _deepcopy_object(dict(action_payload or {})),
        }
        try:
            response_bytes = self._send_request_bytes(request_payload)
        except OSError:
            if _ensure_local_agentsdb_socket_server(self._agents_db_uri, timeout_seconds=self._timeout_seconds):
                response_bytes = self._send_request_bytes(request_payload)
            else:
                raise
        if not response_bytes:
            raise RuntimeError("agentsdb socket returned no response")
        raw_line = response_bytes.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
        try:
            response_payload = json.loads(raw_line)
        except Exception as exc:
            raise RuntimeError(f"agentsdb socket returned invalid JSON: {raw_line}") from exc
        if not isinstance(response_payload, Mapping):
            raise RuntimeError("agentsdb socket returned non-object response")
        if not bool(response_payload.get("ok", True)):
            raise RuntimeError(str(response_payload.get("error") or "agentsdb socket request failed"))
        return dict(response_payload)

    def _send_request_bytes(self, request_payload: Mapping[str, Any]) -> bytes:
        with socket.create_connection((self._host, self._port), timeout=self._timeout_seconds) as connection:
            connection.sendall((json.dumps(request_payload, separators=(",", ":")) + "\n").encode("utf-8"))
            response_bytes = b""
            while b"\n" not in response_bytes:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response_bytes += chunk
        return response_bytes

    def load_collection(self, object_name: str) -> str:
        return str(self._OBJECT_COLLECTION_MAP[str(object_name).strip().lower()])

    def ensure_index_objects(self) -> None:
        self._request_object("ensure_index_objects")

    def upsert_object(self, object_name: str, object_id: str, object_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = _deepcopy_object(dict(object_payload))
        if "updated_at" not in payload:
            payload["updated_at"] = _now_utc().isoformat()
        if "created_at" not in payload:
            payload["created_at"] = payload["updated_at"]
        response_payload = self._request_object(
            "upsert_object",
            {
                "object_name": str(object_name),
                "object_id": str(object_id),
                "object_payload": payload,
            },
        )
        return dict(response_payload.get("object_payload") or payload)

    def load_object(self, object_name: str, object_id: str) -> dict[str, Any] | None:
        response_payload = self._request_object(
            "load_object",
            {
                "object_name": str(object_name),
                "object_id": str(object_id),
            },
        )
        object_payload = response_payload.get("object_payload")
        return dict(object_payload) if isinstance(object_payload, Mapping) else None

    def load_objects(self, object_name: str, object_filter: Mapping[str, Any] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        response_payload = self._request_object(
            "load_objects",
            {
                "object_name": str(object_name),
                "object_filter": _deepcopy_object(dict(object_filter or {})),
                "limit": max(1, int(limit)),
            },
        )
        object_payload_list = response_payload.get("object_payload_list")
        if not isinstance(object_payload_list, list):
            return []
        return [dict(item) for item in object_payload_list if isinstance(item, Mapping)]

    def find_objects(self, *, namespace_id: str, query_text: str, limit: int = 10) -> list[dict[str, Any]]:
        response_payload = self._request_object(
            "find_objects",
            {
                "namespace_id": str(namespace_id),
                "query_text": str(query_text),
                "limit": max(1, int(limit)),
            },
        )
        object_payload_list = response_payload.get("object_payload_list")
        if not isinstance(object_payload_list, list):
            return []
        return [dict(item) for item in object_payload_list if isinstance(item, Mapping)]

    def load_relation_graph(self, *, namespace_id: str, source_entity_id: str, max_depth: int = 2) -> list[dict[str, Any]]:
        response_payload = self._request_object(
            "load_relation_graph",
            {
                "namespace_id": str(namespace_id),
                "source_entity_id": str(source_entity_id),
                "max_depth": max(0, int(max_depth)),
            },
        )
        object_payload_list = response_payload.get("object_payload_list")
        if not isinstance(object_payload_list, list):
            return []
        return [dict(item) for item in object_payload_list if isinstance(item, Mapping)]

    def build_vector_search_pipeline(
        self,
        *,
        query_vector: Sequence[float],
        namespace_id: str,
        owner_type: str = "block",
        limit: int = 10,
        num_candidates: int = 100,
        index_name: str = "embedding_cosine",
    ) -> list[dict[str, Any]]:
        return KnowledgeRepository.build_vector_search_pipeline(
            self,
            query_vector=query_vector,
            namespace_id=namespace_id,
            owner_type=owner_type,
            limit=limit,
            num_candidates=num_candidates,
            index_name=index_name,
        )


class AgentDbInMemoryRepository:
    """Knowledge repository that stores all objects in-memory and flushes snapshots to disk."""

    _OBJECT_COLLECTION_MAP = KnowledgeRepository._OBJECT_COLLECTION_MAP

    def __init__(self, image_path: str | None = None) -> None:
        self._lock = threading.RLock()
        self._image_path = str(image_path or "").strip() or None
        self._collections: dict[str, dict[str, dict[str, Any]]] = {
            collection_name: {}
            for collection_name in self._OBJECT_COLLECTION_MAP.values()
        }
        self._load_image()

    def _load_image(self) -> None:
        if not self._image_path:
            return
        path = os.path.abspath(os.path.expanduser(self._image_path))
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as image_file:
                image_payload = json.load(image_file)
        except Exception:
            return
        collections_payload = image_payload.get("collections") if isinstance(image_payload, Mapping) else None
        if not isinstance(collections_payload, Mapping):
            return
        with self._lock:
            for collection_name, collection_payload in collections_payload.items():
                normalized_collection = str(collection_name or "").strip()
                if normalized_collection not in self._collections:
                    continue
                if not isinstance(collection_payload, Mapping):
                    continue
                self._collections[normalized_collection] = {
                    str(record_id): dict(record_payload)
                    for record_id, record_payload in collection_payload.items()
                    if isinstance(record_payload, Mapping)
                }

    def _flush_image(self) -> None:
        if not self._image_path:
            return
        path = os.path.abspath(os.path.expanduser(self._image_path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        image_payload = {
            "schema": "agentsdb_inmemory_image_v1",
            "updated_at": _now_utc().isoformat(),
            "collections": _json_safe_object(self._collections),
        }
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as image_file:
            json.dump(image_payload, image_file, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    def _load_collection_object(self, object_name: str) -> dict[str, dict[str, Any]]:
        collection_name = self._OBJECT_COLLECTION_MAP[str(object_name).strip().lower()]
        return self._collections[collection_name]

    def ensure_index_objects(self) -> None:
        return None

    def upsert_object(self, object_name: str, object_id: str, object_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._lock:
            collection = self._load_collection_object(object_name)
            existing_payload = collection.get(object_id) if isinstance(collection.get(object_id), Mapping) else {}
            payload:dict = _deepcopy_object(dict(existing_payload))
            payload.update(_deepcopy_object(dict(object_payload)))
            payload["_id"] = object_id
            payload["updated_at"] = payload.get("updated_at") or _now_utc().isoformat()
            payload["created_at"] = payload.get("created_at") or existing_payload.get("created_at") or payload["updated_at"]
            collection[object_id] = dict(payload)
            self._flush_image()
            return dict(payload)

    def load_object(self, object_name: str, object_id: str) -> dict[str, Any] | None:
        with self._lock:
            collection = self._load_collection_object(object_name)
            payload = collection.get(object_id)
            return dict(payload) if isinstance(payload, Mapping) else None

    def load_objects(self, object_name: str, object_filter: Mapping[str, Any] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            collection = self._load_collection_object(object_name)
            filter_payload = dict(object_filter or {})
            result_payload_list: list[dict[str, Any]] = []
            for object_payload in collection.values():
                if not isinstance(object_payload, Mapping):
                    continue
                if any(object_payload.get(key) != value for key, value in filter_payload.items()):
                    continue
                result_payload_list.append(dict(object_payload))
                if len(result_payload_list) >= max(1, int(limit)):
                    break
            return result_payload_list

    def find_objects(self, *, namespace_id: str, query_text: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized_query = str(query_text or "").strip().lower()
        if not normalized_query:
            return []
        with self._lock:
            collection = self._collections["documents"]
            result_payload_list: list[dict[str, Any]] = []
            for document_payload in collection.values():
                if not isinstance(document_payload, Mapping):
                    continue
                if str(document_payload.get("namespace_id") or "").strip() != str(namespace_id):
                    continue
                haystack = json.dumps(_json_safe_object(document_payload), ensure_ascii=False).lower()
                if normalized_query not in haystack:
                    continue
                result_payload_list.append({
                    "document_id": str(document_payload.get("_id") or ""),
                    "title": str(document_payload.get("title") or ""),
                    "source_uri": str(document_payload.get("source_uri") or ""),
                    "document_score": 1.0,
                    "block": {},
                })
                if len(result_payload_list) >= max(1, int(limit)):
                    break
            return result_payload_list

    def load_relation_graph(self, *, namespace_id: str, source_entity_id: str, max_depth: int = 2) -> list[dict[str, Any]]:
        max_hops = max(0, int(max_depth))
        with self._lock:
            relation_collection = self._collections["entity_relations"]
            visited_sources = {str(source_entity_id)}
            frontier = {str(source_entity_id)}
            result_payload_list: list[dict[str, Any]] = []
            for _ in range(max_hops + 1):
                if not frontier:
                    break
                next_frontier: set[str] = set()
                for relation_payload in relation_collection.values():
                    if not isinstance(relation_payload, Mapping):
                        continue
                    if str(relation_payload.get("namespace_id") or "") != str(namespace_id):
                        continue
                    src = str(relation_payload.get("source_entity_id") or "")
                    tgt = str(relation_payload.get("target_entity_id") or "")
                    if src not in frontier:
                        continue
                    result_payload_list.append(dict(relation_payload))
                    if tgt and tgt not in visited_sources:
                        next_frontier.add(tgt)
                visited_sources.update(next_frontier)
                frontier = next_frontier
            return result_payload_list


def _is_memory_backend_uri(uri: str | None) -> bool:
    normalized_uri = str(uri or "").strip().lower()
    return normalized_uri.startswith("agentsdb://") or normalized_uri.startswith("memodb://") or normalized_uri.startswith("inmemdb://")


class AgentDbSocketServerService:
    """Socket server service that exposes KnowledgeRepository commands via JSON-lines."""

    def __init__(self, backend_uri: str, default_database_name: str = "alde_knowledge", memory_image_path: str | None = None) -> None:
        normalized_backend_uri = str(backend_uri or "").strip()
        if not normalized_backend_uri:
            normalized_backend_uri = "agentsdb://local"
        if _is_agentsdb_socket_uri(normalized_backend_uri):
            raise RuntimeError("agentsdb socket server backend URI must not use agentsdb://")
        self._backend_uri = normalized_backend_uri
        self._default_database_name = str(default_database_name or "alde_knowledge").strip() or "alde_knowledge"
        self._memory_image_path = str(memory_image_path or "").strip() or None
        self._repository_cache: dict[str, Any] = {}

    @classmethod
    def load_from_env(cls) -> AgentDbSocketServerService:
        connection_config = _load_agentsdb_connection_config()
        backend_uri = str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_BACKEND_URI", "")
            or os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_URI", ""),
        ).strip()
        if not backend_uri:
            backend_uri = _connection_config_value(connection_config, ("backend_uri", "agents_db_backend_uri", "storage_uri", "storage_backend_uri"))
        if not backend_uri:
            backend_uri = "agentsmem://local"
        memory_image_path = str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_MEMORY_IMAGE_PATH", "")
            or os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_FLUSH_IMAGE_PATH", "")
            or os.path.join("AppData", "agentsdb_memory_image.json"),
        ).strip()
        if not memory_image_path:
            memory_image_path = _connection_config_value(connection_config, ("memory_image_path", "flush_image_path"))
        database_name = str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_NAME", "")
            or "alde_knowledge",
        ).strip() or "alde_knowledge"
        if not database_name:
            database_name = _connection_config_value(connection_config, ("database_name", "database")) or "alde_knowledge"
        return cls(backend_uri=backend_uri, default_database_name=database_name, memory_image_path=memory_image_path)

    def load_repository(self, database_name: str | None = None) -> Any:
        resolved_database_name = str(database_name or self._default_database_name).strip() or self._default_database_name
        repository:AgentDbInMemoryRepository|KnowledgeRepository = self._repository_cache.get(resolved_database_name)
        if repository is not None:
            return repository
        if _is_memory_backend_uri(self._backend_uri):
            repository = AgentDbInMemoryRepository(self._memory_image_path)
        else:
            repository = KnowledgeRepository.create_from_uri(self._backend_uri, resolved_database_name)
        self._repository_cache[resolved_database_name] = repository
        return repository

    def dispatch_object(self, cmd: str, payload: Mapping[str, Any], database_name: str | None = None) -> dict[str, Any]:
        normalized_cmd = str(cmd or "").strip().lower()
        if normalized_cmd == "health":
            return {
                "ok": True,
                "status": "ok",
                "backend": "agents_db",
                "storage_backend": "inmemory" if _is_memory_backend_uri(self._backend_uri) else "dict",
                "database_name": str(database_name or self._default_database_name),
            }
        repository: AgentDbInMemoryRepository | KnowledgeRepository = self.load_repository(database_name)
        if normalized_cmd == "ensure_index_objects":
            repository.ensure_index_objects()
            return {"ok": True, "ensured": True}
        if normalized_cmd == "upsert_object":
            object_name = str(payload.get("object_name") or "").strip()
            object_id = str(payload.get("object_id") or "").strip()
            object_payload = payload.get("object_payload")
            if not object_name or not object_id or not isinstance(object_payload, Mapping):
                raise ValueError("upsert_object requires object_name, object_id, and object_payload")
            stored_payload = repository.upsert_object(object_name, object_id, dict(object_payload))
            return {"ok": True, "object_payload": _json_safe_object(stored_payload)}
        if normalized_cmd == "load_object":
            object_name = str(payload.get("object_name") or "").strip()
            object_id = str(payload.get("object_id") or "").strip()
            if not object_name or not object_id:
                raise ValueError("load_object requires object_name and object_id")
            object_payload = repository.load_object(object_name, object_id)
            return {"ok": True, "object_payload": _json_safe_object(object_payload) if object_payload is not None else None}
        if normalized_cmd == "load_objects":
            object_name = str(payload.get("object_name") or "").strip()
            object_filter = payload.get("object_filter")
            limit = payload.get("limit", 50)
            if not object_name:
                raise ValueError("load_objects requires object_name")
            if object_filter is not None and not isinstance(object_filter, Mapping):
                raise ValueError("load_objects object_filter must be an object")
            object_payload_list = repository.load_objects(
                object_name,
                dict(object_filter or {}),
                max(1, int(limit)),
            )
            return {"ok": True, "object_payload_list": _json_safe_object(object_payload_list)}
        if normalized_cmd == "find_objects":
            namespace_id = str(payload.get("namespace_id") or "").strip()
            query_text = str(payload.get("query_text") or "").strip()
            limit = payload.get("limit", 10)
            if not namespace_id or not query_text:
                raise ValueError("find_objects requires namespace_id and query_text")
            object_payload_list = repository.find_objects(
                namespace_id=namespace_id,
                query_text=query_text,
                limit=max(1, int(limit)),
            )
            return {"ok": True, "object_payload_list": _json_safe_object(object_payload_list)}
        if normalized_cmd == "load_relation_graph":
            namespace_id = str(payload.get("namespace_id") or "").strip()
            source_entity_id = str(payload.get("source_entity_id") or "").strip()
            max_depth = payload.get("max_depth", 2)
            if not namespace_id or not source_entity_id:
                raise ValueError("load_relation_graph requires namespace_id and source_entity_id")
            object_payload_list = repository.load_relation_graph(
                namespace_id=namespace_id,
                source_entity_id=source_entity_id,
                max_depth=max(0, int(max_depth)),
            )
            return {"ok": True, "object_payload_list": _json_safe_object(object_payload_list)}
        raise ValueError(f"unknown cmd: {normalized_cmd or '<empty>'}")


def _parse_agentsdb_socket_request_line(raw_line: bytes) -> tuple[str, str | None, dict[str, Any]]:
    decoded_line = raw_line.decode("utf-8", errors="replace")
    normalized_line = decoded_line.strip()
    if not normalized_line:
        return "health", None, {}

    normalized_command = normalized_line.lower()
    if normalized_command in {"health", "ping", "status"}:
        return "health", None, {}
    if normalized_command.startswith("cmd="):
        legacy_cmd = normalized_command.partition("=")[2].strip()
        if legacy_cmd in {"ping", "status"}:
            legacy_cmd = "health"
        return legacy_cmd, None, {}
    if normalized_command.startswith(("get ", "head ", "options ")):
        return "health", None, {}

    try:
        request_payload = json.loads(normalized_line)
    except Exception as exc:
        raise ValueError("request payload must be a JSON object") from exc

    if not isinstance(request_payload, Mapping):
        raise ValueError("request payload must be a JSON object")

    cmd = str(request_payload.get("cmd") or "").strip()
    database_name = str(request_payload.get("database_name") or "").strip() or None
    payload = request_payload.get("payload")
    if payload is not None and not isinstance(payload, Mapping):
        raise ValueError("payload must be a JSON object")
    return cmd, database_name, dict(payload or {})


class _AgentDbSocketRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        service: AgentDbSocketServerService = self.server.service
        raw_line = self.rfile.readline()
        if not raw_line:
            return
        response_payload: dict[str, Any]
        try:
            cmd, database_name, payload = _parse_agentsdb_socket_request_line(raw_line)
            response_payload = service.dispatch_object(cmd=cmd, payload=payload, database_name=database_name)
        except Exception as exc:
            response_payload = {
                "ok": False,
                "error": "agents_db_socket_request_failed",
                "detail": str(exc),
            }
        self.wfile.write((json.dumps(_json_safe_object(response_payload), separators=(",", ":")) + "\n").encode("utf-8"))


class _AgentDbSocketTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], request_handler_class: type[_AgentDbSocketRequestHandler], service: AgentDbSocketServerService) -> None:
        self.service = service
        super().__init__(server_address, request_handler_class)


def run_agentsdb_socket_server(
    *,
    host: str = "127.0.0.1",
    port: int = 2331,
    backend_uri: str,
    database_name: str = "alde_knowledge",
) -> None:
    service = AgentDbSocketServerService(backend_uri=backend_uri, default_database_name=database_name)
    with _AgentDbSocketTCPServer((str(host).strip() or "127.0.0.1", int(port)), _AgentDbSocketRequestHandler, service) as server:
        server.serve_forever()


def run_agentsdb_socket_server_from_env(host: str | None = None, port: int | None = None) -> None:
    connection_config = _load_agentsdb_connection_config()
    agents_db_uri = str(os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_URI", "")).strip()
    if not agents_db_uri:
        agents_db_uri = _load_agentsdb_uri_from_connection_config(connection_config)
    parsed_uri = urlparse(agents_db_uri or "agentsdb://127.0.0.1:2331")
    resolved_host = str(host or parsed_uri.hostname or "127.0.0.1").strip() or "127.0.0.1"
    resolved_port = int(port or parsed_uri.port or 2331)
    service = AgentDbSocketServerService.load_from_env()
    with _AgentDbSocketTCPServer((resolved_host, resolved_port), _AgentDbSocketRequestHandler, service) as server:
        server.serve_forever()


class KnowledgeObjectService:
    """Domain service for storing and querying the knowledge model."""

    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    def store_namespace_object(self, namespace_object: NamespaceObject) -> Mapping[str, Any]:
        return self._repository.upsert_object("namespace", namespace_object.id, _dataclass_payload(namespace_object))

    def store_entity_object(self, entity_object: EntityObject) -> Mapping[str, Any]:
        return self._repository.upsert_object("entity", entity_object.id, _dataclass_payload(entity_object))

    def store_document_object(self, document_object: DocumentObject) -> Mapping[str, Any]:
        return self._repository.upsert_object("document", document_object.id, _dataclass_payload(document_object))

    def store_relation_object(self, relation_object: EntityRelationObject) -> Mapping[str, Any]:
        return self._repository.upsert_object("relation", relation_object.id, _dataclass_payload(relation_object))

    def store_embedding_object(self, embedding_object: EmbeddingObject) -> Mapping[str, Any]:
        object_id = ":".join(
            [
                embedding_object.namespace_id,
                embedding_object.owner_type,
                embedding_object.owner_id,
                embedding_object.model_id,
            ],
        )
        return self._repository.upsert_object("embedding", object_id, _dataclass_payload(embedding_object))

    def store_retrieval_run_object(self, retrieval_run_object: RetrievalRunObject) -> Mapping[str, Any]:
        return self._repository.upsert_object(
            "retrieval_run",
            retrieval_run_object.id,
            _dataclass_payload(retrieval_run_object),
        )

    def store_dispatcher_run_object(self, dispatcher_run_object: DispatcherRunObject) -> Mapping[str, Any]:
        return self._repository.upsert_object(
            "dispatcher_run",
            dispatcher_run_object.id,
            _dataclass_payload(dispatcher_run_object),
        )

    def find_objects(self, *, namespace_id: str, query_text: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._repository.find_objects(namespace_id=namespace_id, query_text=query_text, limit=limit)

    def load_relation_object_graph(
        self,
        *,
        namespace_id: str,
        source_entity_id: str,
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        return self._repository.load_relation_graph(
            namespace_id=namespace_id,
            source_entity_id=source_entity_id,
            max_depth=max_depth,
        )

    def build_vector_candidate_pipeline( 
        self,
        *,
        query_vector: Sequence[float],
        namespace_id: str,
        owner_type: str = "block",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self._repository.build_vector_search_pipeline(
            query_vector=query_vector,
            namespace_id=namespace_id,
            owner_type=owner_type,
            limit=limit,
        )


class PipelineService:
    """AgentsDB bridge for runtime retrieval telemetry and shared namespace resolution."""

    def __init__(self, knowledge_service: KnowledgeObjectService, runtime_config: RuntimeConfigObject) -> None:
        self._knowledge_service = knowledge_service
        self._runtime_config = runtime_config

    def load_tenant_id(
        self,
        *,
        handoff_metadata: Mapping[str, Any] | None = None,
        handoff_payload: Mapping[str, Any] | None = None,
    ) -> str:
        return str(
            (handoff_payload or {}).get("tenant_id")
            or (handoff_metadata or {}).get("tenant_id")
            or self._runtime_config.tenant_id
        ).strip() or self._runtime_config.tenant_id

    def load_namespace_object(
        self,
        *,
        handoff_metadata: Mapping[str, Any] | None = None,
        handoff_payload: Mapping[str, Any] | None = None,
    ) -> NamespaceObject:
        return _build_namespace_object_from_runtime_config(
            self._runtime_config,
            handoff_metadata=handoff_metadata,
            handoff_payload=handoff_payload,
        )


class ObjectMappingService:
    """Map parsed result objects to generic document, entity, and relation objects."""

    def __init__(self, knowledge_service: KnowledgeObjectService, runtime_config: RuntimeConfigObject) -> None:
        self._knowledge_service = knowledge_service
        self._runtime_config = runtime_config

    def load_namespace_object(
        self,
        *,
        handoff_metadata: Mapping[str, Any] | None = None,
        handoff_payload: Mapping[str, Any] | None = None,
    ) -> NamespaceObject:
        return _build_namespace_object_from_runtime_config(
            self._runtime_config,
            handoff_metadata=handoff_metadata,
            handoff_payload=handoff_payload,
        )

    def load_object_payload(self, *, object_name: str, result_payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized_object_name = _normalize_document_object_name(object_name)
        object_payload = result_payload.get(normalized_object_name)
        if isinstance(object_payload, Mapping):
            return dict(object_payload)
        if normalized_object_name != "job_posting":
            return {}
        raw_text_payload = self.load_raw_text_document_payload(result_payload=result_payload)
        entity_payload_list = self.load_explicit_entity_payload_list(result_payload=result_payload)
        compatibility_payload: dict[str, Any] = {}
        subject_payload = next(
            (
                entity_payload
                for entity_payload in entity_payload_list
                if str(entity_payload.get("entity_key") or "").strip() == "subject"
                or str((entity_payload.get("metadata") or {}).get("role") if isinstance(entity_payload.get("metadata"), Mapping) else "").strip() == "subject"
                or str(entity_payload.get("entity_type") or entity_payload.get("type_key") or "").strip() == "job_posting"
            ),
            {},
        )
        organization_payload = next(
            (
                entity_payload
                for entity_payload in entity_payload_list
                if str(entity_payload.get("entity_type") or entity_payload.get("type_key") or "").strip() == "organization"
            ),
            {},
        )
        location_payload = next(
            (
                entity_payload
                for entity_payload in entity_payload_list
                if str(entity_payload.get("entity_type") or entity_payload.get("type_key") or "").strip() == "location"
            ),
            {},
        )
        contact_payload = next(
            (
                entity_payload
                for entity_payload in entity_payload_list
                if str(entity_payload.get("entity_type") or entity_payload.get("type_key") or "").strip() == "person"
            ),
            {},
        )
        title = _first_non_empty_string(
            [
                subject_payload.get("canonical_name") if isinstance(subject_payload, Mapping) else None,
                raw_text_payload.get("title"),
            ],
        )
        if title:
            compatibility_payload["job_title"] = title
        company_name = _first_non_empty_string(
            [organization_payload.get("canonical_name") if isinstance(organization_payload, Mapping) else None],
        )
        if company_name:
            compatibility_payload["company_name"] = company_name
        raw_text = _first_non_empty_string([raw_text_payload.get("raw_text"), raw_text_payload.get("text")])
        if raw_text:
            compatibility_payload["raw_text"] = raw_text
        summary = _first_non_empty_string(
            [
                subject_payload.get("summary") if isinstance(subject_payload, Mapping) else None,
                raw_text_payload.get("summary"),
            ],
        )
        if summary:
            compatibility_payload["summary"] = summary
        metadata_payload = raw_text_payload.get("metadata") if isinstance(raw_text_payload.get("metadata"), Mapping) else {}
        language_code = _first_non_empty_string([raw_text_payload.get("language"), metadata_payload.get("language")])
        if metadata_payload or language_code:
            compatibility_payload["metadata"] = dict(metadata_payload)
            if language_code:
                compatibility_payload["metadata"]["language"] = language_code
        if company_name or location_payload:
            compatibility_payload.setdefault("company_info", {})
        if location_payload:
            compatibility_payload["company_info"]["location"] = location_payload.get("canonical_name")
        if contact_payload:
            compatibility_payload.setdefault("application", {})
            compatibility_payload["application"]["contact_person"] = contact_payload.get("canonical_name")
        return compatibility_payload

    def load_raw_text_document_payload(self, *, result_payload: Mapping[str, Any]) -> dict[str, Any]:
        raw_text_payload = result_payload.get("raw_text_document")
        return dict(raw_text_payload) if isinstance(raw_text_payload, Mapping) else {}

    def load_explicit_entity_payload_list(self, *, result_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        entity_payload_list = result_payload.get("entity_objects")
        if not isinstance(entity_payload_list, Sequence) or isinstance(entity_payload_list, (str, bytes, bytearray)):
            return []
        return [dict(entity_payload) for entity_payload in entity_payload_list if isinstance(entity_payload, Mapping)]

    def load_explicit_relation_payload_list(self, *, result_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        relation_payload_list = result_payload.get("relation_objects")
        if not isinstance(relation_payload_list, Sequence) or isinstance(relation_payload_list, (str, bytes, bytearray)):
            return []
        return [dict(relation_payload) for relation_payload in relation_payload_list if isinstance(relation_payload, Mapping)]

    def load_correlation_id(
        self,
        *,
        result_payload: Mapping[str, Any],
        fallback_correlation_id: str | None = None,
    ) -> str:
        return _first_non_empty_string(
            [
                fallback_correlation_id,
                result_payload.get("correlation_id"),
                (result_payload.get("db_updates") or {}).get("correlation_id") if isinstance(result_payload.get("db_updates"), Mapping) else None,
                (result_payload.get("file") or {}).get("content_sha256") if isinstance(result_payload.get("file"), Mapping) else None,
            ],
        ) or _stable_sha256(str(result_payload))

    def load_document_title(self, *, object_name: str, object_payload: Mapping[str, Any], correlation_id: str) -> str:
        normalized_object_name = _normalize_document_object_name(object_name)
        if normalized_object_name == "job_posting":
            return _first_non_empty_string(
                [
                    object_payload.get("job_title"),
                    object_payload.get("title"),
                    object_payload.get("external_id"),
                    correlation_id,
                ],
            ) or correlation_id
        return _first_non_empty_string(
            [
                object_payload.get("title"),
                object_payload.get("name"),
                object_payload.get("full_name"),
                correlation_id,
            ],
        ) or correlation_id

    def load_document_source_uri(
        self,
        *,
        result_payload: Mapping[str, Any],
        handoff_payload: Mapping[str, Any] | None = None,
    ) -> str:
        file_payload = result_payload.get("file") if isinstance(result_payload.get("file"), Mapping) else {}
        link_payload = result_payload.get("link") if isinstance(result_payload.get("link"), Mapping) else {}
        source_payload = handoff_payload if isinstance(handoff_payload, Mapping) else {}
        return _first_non_empty_string(
            [
                file_payload.get("source_uri"),
                file_payload.get("path"),
                link_payload.get("url"),
                source_payload.get("url"),
                source_payload.get("source_path"),
            ],
        ) or "local://parser_result"

    def load_document_text(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        result_payload: Mapping[str, Any],
    ) -> str:
        normalized_object_name = _normalize_document_object_name(object_name)
        raw_text_payload = self.load_raw_text_document_payload(result_payload=result_payload)
        if normalized_object_name == "job_posting":
            return _first_non_empty_string(
                [
                    raw_text_payload.get("raw_text"),
                    raw_text_payload.get("text"),
                    object_payload.get("raw_text"),
                    (result_payload.get("parse") or {}).get("raw_text") if isinstance(result_payload.get("parse"), Mapping) else None,
                ],
            ) or ""
        return _first_non_empty_string(
            [
                object_payload.get("raw_text"),
                (result_payload.get("parse") or {}).get("raw_text") if isinstance(result_payload.get("parse"), Mapping) else None,
            ],
        ) or ""

    def build_block_seed_objects(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        correlation_id: str,
        result_payload: Mapping[str, Any] | None = None,
    ) -> list[MappingBlockSeedObject]:
        normalized_object_name = _normalize_document_object_name(object_name)
        raw_text_payload = self.load_raw_text_document_payload(result_payload=result_payload or {})
        explicit_block_seed_objects = self._build_explicit_block_seed_objects(
            object_name=normalized_object_name,
            correlation_id=correlation_id,
            raw_text_payload=raw_text_payload,
        )
        if explicit_block_seed_objects:
            return explicit_block_seed_objects
        object_pattern = self.load_object_pattern(object_name=normalized_object_name)
        if object_pattern:
            return self._build_pattern_block_seed_objects(
                object_name=normalized_object_name,
                object_payload=object_payload,
                correlation_id=correlation_id,
                object_pattern=object_pattern,
            )
        return self._build_generic_block_seed_objects(
            object_name=normalized_object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
        )

    def build_entity_candidate_objects(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        correlation_id: str,
        result_payload: Mapping[str, Any] | None = None,
    ) -> list[MappingSeedEntityObject]:
        normalized_object_name = _normalize_document_object_name(object_name)
        explicit_entity_candidate_objects = self._build_explicit_entity_candidate_objects(
            object_name=normalized_object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
            entity_payload_list=self.load_explicit_entity_payload_list(result_payload=result_payload or {}),
        )
        if explicit_entity_candidate_objects:
            return explicit_entity_candidate_objects
        object_pattern = self.load_object_pattern(object_name=normalized_object_name)
        if object_pattern:
            return self._build_pattern_seed_entity_objects(
                object_name=normalized_object_name,
                object_payload=object_payload,
                correlation_id=correlation_id,
                object_pattern=object_pattern,
            )
        return self._build_generic_entity_candidate_objects(
            object_name=normalized_object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
        )

    def build_document_block_objects(
        self,
        *,
        document_text: str,
        block_seed_objects: Sequence[MappingBlockSeedObject],
        entity_candidate_objects: Sequence[MappingSeedEntityObject],
        entity_id_by_key: Mapping[str, str],
        timestamp: datetime,
    ) -> list[BlockObject]:
        current_offset = 0
        block_objects: list[BlockObject] = []
        for block_seed_object in block_seed_objects:
            char_start = document_text.find(block_seed_object.content, current_offset) if document_text else -1
            char_end = char_start + len(block_seed_object.content) if char_start >= 0 else None
            if char_end is not None:
                current_offset = max(current_offset, char_end)
            mentions: list[EntityMentionObject] = []
            for entity_candidate_object in entity_candidate_objects:
                if entity_candidate_object.section_key != block_seed_object.section_key:
                    continue
                entity_id = entity_id_by_key.get(entity_candidate_object.seed_key)
                if not entity_id:
                    continue
                mention_text = str(entity_candidate_object.mention_text or entity_candidate_object.canonical_name).strip()
                if not mention_text:
                    continue
                mention_char_start = block_seed_object.content.find(mention_text)
                if mention_char_start < 0:
                    continue
                mentions.append(
                    EntityMentionObject(
                        entity_id=entity_id,
                        mention_text=mention_text,
                        extractor="parser_mapping",
                        confidence=entity_candidate_object.confidence,
                        char_start=mention_char_start,
                        char_end=mention_char_start + len(mention_text),
                        metadata={
                            "source_field": entity_candidate_object.metadata.get("source_field"),
                            "mapped_from": "parser_result",
                        },
                        created_at=timestamp,
                    ),
                )
            block_objects.append(
                BlockObject(
                    block_id=block_seed_object.block_id,
                    block_no=block_seed_object.block_no,
                    content=block_seed_object.content,
                    block_kind=block_seed_object.block_kind,
                    heading=block_seed_object.heading,
                    token_count=len(block_seed_object.content.split()),
                    char_start=char_start if char_start >= 0 else None,
                    char_end=char_end,
                    metadata=_deepcopy_object(block_seed_object.metadata),
                    mentions=mentions,
                    created_at=timestamp,
                ),
            )
        return block_objects

    def build_document_object(
        self,
        *,
        object_name: str,
        result_payload: Mapping[str, Any],
        namespace_object: NamespaceObject,
        correlation_id: str,
        handoff_payload: Mapping[str, Any] | None = None,
    ) -> DocumentObject | None:
        object_payload = self.load_object_payload(object_name=object_name, result_payload=result_payload)
        if not object_payload:
            return None
        timestamp = _now_utc()
        document_id = f"doc:{_normalize_document_object_name(object_name)}:{correlation_id}"
        document_text = self.load_document_text(
            object_name=object_name,
            object_payload=object_payload,
            result_payload=result_payload,
        )
        block_seed_objects = self.build_block_seed_objects(
            object_name=object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
            result_payload=result_payload,
        )
        if not document_text:
            document_text = "\n\n".join(block_seed_object.content for block_seed_object in block_seed_objects if block_seed_object.content)
        entity_candidate_objects = self.build_entity_candidate_objects(
            object_name=object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
            result_payload=result_payload,
        )
        entity_objects = self.build_entity_objects(
            object_name=object_name,
            namespace_object=namespace_object,
            correlation_id=correlation_id,
            document_id=document_id,
            entity_candidate_objects=entity_candidate_objects,
            timestamp=timestamp,
        )
        entity_id_by_key = {
            entity_candidate_object.seed_key: entity_object.id
            for entity_candidate_object, entity_object in zip(entity_candidate_objects, entity_objects)
        }
        block_objects = self.build_document_block_objects(
            document_text=document_text,
            block_seed_objects=block_seed_objects,
            entity_candidate_objects=entity_candidate_objects,
            entity_id_by_key=entity_id_by_key,
            timestamp=timestamp,
        )
        file_payload = result_payload.get("file") if isinstance(result_payload.get("file"), Mapping) else {}
        parse_payload = result_payload.get("parse") if isinstance(result_payload.get("parse"), Mapping) else {}
        content_sha256 = _first_non_empty_string(
            [
                file_payload.get("content_sha256"),
                (result_payload.get("db_updates") or {}).get("content_sha256") if isinstance(result_payload.get("db_updates"), Mapping) else None,
                _stable_sha256(document_text) if document_text else None,
            ],
        ) or _stable_sha256(correlation_id)
        return DocumentObject(
            id=document_id,
            tenant_id=namespace_object.tenant_id,
            namespace_id=namespace_object.id,
            document_type=_normalize_document_object_name(object_name),
            title=self.load_document_title(object_name=object_name, object_payload=object_payload, correlation_id=correlation_id),
            source_uri=self.load_document_source_uri(result_payload=result_payload, handoff_payload=handoff_payload),
            content_sha256=content_sha256,
            source_system=_first_non_empty_string([
                result_payload.get("agent"),
                (handoff_payload or {}).get("platform") if isinstance(handoff_payload, Mapping) else None,
                "parser_result",
            ]) or "parser_result",
            mime_type=_first_non_empty_string([file_payload.get("mime_type"), "text/plain"]) or "text/plain",
            language_code=_first_non_empty_string([parse_payload.get("language"), _mapping_value(object_payload, "metadata.language")]),
            correlation_id=correlation_id,
            summary=_first_non_empty_string([
                object_payload.get("summary"),
                _mapping_value(object_payload, "position.level"),
                _mapping_value(object_payload, "requirements.experience_description"),
            ]) or "",
            metadata={
                "object_name": _normalize_document_object_name(object_name),
                "source_agent": result_payload.get("agent"),
                "parse": _deepcopy_object(parse_payload),
            },
            blocks=block_objects,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def build_entity_objects(
        self,
        *,
        object_name: str,
        namespace_object: NamespaceObject,
        correlation_id: str,
        document_id: str,
        entity_candidate_objects: Sequence[MappingSeedEntityObject],
        timestamp: datetime,
    ) -> list[EntityObject]:
        entity_objects: list[EntityObject] = []
        for entity_candidate_object in entity_candidate_objects:
            entity_id = self._build_entity_id(
                object_name=object_name,
                entity_type=entity_candidate_object.type_key,
                canonical_name=entity_candidate_object.canonical_name,
            )
            alias_objects = [
                EntityAliasObject(
                    alias=alias_value,
                    source_document_id=document_id,
                    created_at=timestamp,
                )
                for alias_value in dict.fromkeys(
                    alias_value.strip()
                    for alias_value in entity_candidate_object.aliases
                    if alias_value.strip() and alias_value.strip() != entity_candidate_object.canonical_name
                )
            ]
            entity_objects.append(
                EntityObject(
                    id=entity_id,
                    tenant_id=namespace_object.tenant_id,
                    namespace_id=namespace_object.id,
                    entity_type=entity_candidate_object.type_key,
                    canonical_name=entity_candidate_object.canonical_name,
                    external_key=f"{entity_candidate_object.type_key}:{_slugify_object_name(entity_candidate_object.canonical_name)}",
                    correlation_id=correlation_id,
                    summary=entity_candidate_object.summary,
                    attributes=_deepcopy_object(entity_candidate_object.attributes),
                    aliases=alias_objects,
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
            )
        return entity_objects

    def build_relation_objects(
        self,
        *,
        object_name: str,
        namespace_object: NamespaceObject,
        correlation_id: str,
        entity_candidate_objects: Sequence[MappingSeedEntityObject],
        entity_objects: Sequence[EntityObject],
        block_seed_objects: Sequence[MappingBlockSeedObject],
        timestamp: datetime,
        result_payload: Mapping[str, Any] | None = None,
    ) -> list[EntityRelationObject]:
        entity_id_by_key: dict[str, str] = {}
        for entity_candidate_object, entity_object in zip(entity_candidate_objects, entity_objects):
            entity_id_by_key[entity_candidate_object.seed_key] = entity_object.id
        explicit_relation_payload_list = self.load_explicit_relation_payload_list(result_payload=result_payload or {})
        if explicit_relation_payload_list:
            block_id_by_key = {block_seed_object.section_key: block_seed_object.block_id for block_seed_object in block_seed_objects}
            relation_objects: list[EntityRelationObject] = []
            for relation_payload in explicit_relation_payload_list:
                source_entity_key = _first_non_empty_string(
                    [
                        relation_payload.get("source_entity_key"),
                        relation_payload.get("source_seed_key"),
                    ],
                )
                target_entity_key = _first_non_empty_string(
                    [
                        relation_payload.get("target_entity_key"),
                        relation_payload.get("target_seed_key"),
                    ],
                )
                relation_type = _first_non_empty_string([relation_payload.get("relation_type")])
                if not source_entity_key or not target_entity_key or not relation_type:
                    continue
                source_entity_id = entity_id_by_key.get(source_entity_key)
                target_entity_id = entity_id_by_key.get(target_entity_key)
                if not source_entity_id or not target_entity_id:
                    continue
                relation_payload_value = f"{source_entity_id}|{relation_type}|{target_entity_id}"
                relation_metadata = _deepcopy_object(
                    relation_payload.get("metadata") if isinstance(relation_payload.get("metadata"), Mapping) else {},
                )
                source_field = _first_non_empty_string([relation_payload.get("source_field"), relation_metadata.get("source_field")])
                if source_field:
                    relation_metadata["source_field"] = source_field
                relation_metadata: dict = relation_metadata
                relation_metadata.setdefault("mapped_from", "explicit_relation_model")
                evidence_objects: list[RelationEvidenceObject] = []
                block_id = block_id_by_key.get(str(relation_payload.get("section_key") or "").strip())
                if block_id:
                    evidence_objects.append(RelationEvidenceObject(block_id=block_id, created_at=timestamp))
                for evidence_payload in relation_payload.get("evidence") or []:
                    if not isinstance(evidence_payload, Mapping):
                        continue
                    evidence_block_id = _first_non_empty_string([evidence_payload.get("block_id")])
                    if not evidence_block_id:
                        continue
                    evidence_objects.append(
                        RelationEvidenceObject(
                            block_id=evidence_block_id,
                            evidence_role=str(evidence_payload.get("evidence_role") or "supporting"),
                            created_at=timestamp,
                        ),
                    )
                confidence = _first_number([relation_payload.get("confidence"), relation_payload.get("weight")]) or 0.95
                weight = _first_number([relation_payload.get("weight"), relation_payload.get("confidence")]) or confidence
                relation_objects.append(
                    EntityRelationObject(
                        id=f"rel:{_normalize_document_object_name(object_name)}:{_stable_sha256(relation_payload_value)[:16]}",
                        tenant_id=namespace_object.tenant_id,
                        namespace_id=namespace_object.id,
                        source_entity_id=source_entity_id,
                        target_entity_id=target_entity_id,
                        relation_type=relation_type,
                        direction=_first_non_empty_string([relation_payload.get("direction")]) or "directed",
                        weight=weight,
                        confidence=confidence,
                        correlation_id=correlation_id,
                        metadata=relation_metadata,
                        evidence=evidence_objects,
                        created_at=timestamp,
                        updated_at=timestamp,
                    ),
                )
            if relation_objects:
                return relation_objects
        source_entity_id = entity_id_by_key.get("subject")
        if not source_entity_id:
            return []
        block_id_by_key = {block_seed_object.section_key: block_seed_object.block_id for block_seed_object in block_seed_objects}
        relation_objects: list[EntityRelationObject] = []
        for entity_candidate_object in entity_candidate_objects:
            if entity_candidate_object.seed_key == "subject" or not entity_candidate_object.relation_type_key:
                continue
            target_entity_id = entity_id_by_key.get(entity_candidate_object.seed_key)
            if not target_entity_id:
                continue
            relation_payload = f"{source_entity_id}|{entity_candidate_object.relation_type_key}|{target_entity_id}"
            evidence: list[RelationEvidenceObject] = []
            block_id = block_id_by_key.get(entity_candidate_object.section_key or "")
            if block_id:
                evidence.append(RelationEvidenceObject(block_id=block_id, created_at=timestamp))
            relation_objects.append(
                EntityRelationObject(
                    id=f"rel:{_normalize_document_object_name(object_name)}:{_stable_sha256(relation_payload)[:16]}",
                    tenant_id=namespace_object.tenant_id,
                    namespace_id=namespace_object.id,
                    source_entity_id=source_entity_id,
                    target_entity_id=target_entity_id,
                    relation_type=entity_candidate_object.relation_type_key,
                    direction="directed",
                    weight=entity_candidate_object.confidence,
                    confidence=entity_candidate_object.confidence,
                    correlation_id=correlation_id,
                    metadata={
                        "source_field": entity_candidate_object.metadata.get("source_field"),
                        "mapped_from": "parser_result",
                    },
                    evidence=evidence,
                    created_at=timestamp,
                    updated_at=timestamp,
                ),
            )
        return relation_objects

    def store_mapped_object(
        self,
        *,
        object_name: str,
        result_payload: Mapping[str, Any],
        fallback_correlation_id: str | None = None,
        handoff_metadata: Mapping[str, Any] | None = None,
        handoff_payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        normalized_object_name = _normalize_document_object_name(object_name)
        object_payload = self.load_object_payload(object_name=normalized_object_name, result_payload=result_payload)
        if not object_payload:
            return {
                "ok": True,
                "stored": False,
                "backend": "agents_db",
                "object_name": normalized_object_name,
                "reason": "missing_object_payload",
            }
        parse_payload = result_payload.get("parse") if isinstance(result_payload.get("parse"), Mapping) else {}
        if normalized_object_name == "job_posting" and parse_payload.get("is_job_posting") is False:
            return {
                "ok": True,
                "stored": False,
                "backend": "agents_db",
                "object_name": normalized_object_name,
                "reason": "parse_marked_non_matching",
            }
        correlation_id = self.load_correlation_id(
            result_payload=result_payload,
            fallback_correlation_id=fallback_correlation_id,
        )
        namespace_object = self.load_namespace_object(
            handoff_metadata=handoff_metadata,
            handoff_payload=handoff_payload,
        )
        timestamp = _now_utc()
        document_object = self.build_document_object(
            object_name=normalized_object_name,
            result_payload=result_payload,
            namespace_object=namespace_object,
            correlation_id=correlation_id,
            handoff_payload=handoff_payload,
        )
        if document_object is None:
            return {
                "ok": True,
                "stored": False,
                "backend": "agents_db",
                "object_name": normalized_object_name,
                "reason": "document_mapping_failed",
            }
        block_seed_objects = self.build_block_seed_objects(
            object_name=normalized_object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
            result_payload=result_payload,
        )
        entity_candidate_objects = self.build_entity_candidate_objects(
            object_name=normalized_object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
            result_payload=result_payload,
        )
        entity_objects = self.build_entity_objects(
            object_name=normalized_object_name,
            namespace_object=namespace_object,
            correlation_id=correlation_id,
            document_id=document_object.id,
            entity_candidate_objects=entity_candidate_objects,
            timestamp=timestamp,
        )
        relation_objects = self.build_relation_objects(
            object_name=normalized_object_name,
            namespace_object=namespace_object,
            correlation_id=correlation_id,
            entity_candidate_objects=entity_candidate_objects,
            entity_objects=entity_objects,
            block_seed_objects=block_seed_objects,
            timestamp=timestamp,
            result_payload=result_payload,
        )
        self._knowledge_service.store_namespace_object(namespace_object)
        self._knowledge_service.store_document_object(document_object)
        for entity_object in entity_objects:
            self._knowledge_service.store_entity_object(entity_object)
        for relation_object in relation_objects:
            self._knowledge_service.store_relation_object(relation_object)
        return {
            "ok": True,
            "stored": True,
            "backend": "agents_db",
            "object_name": normalized_object_name,
            "namespace_id": namespace_object.id,
            "document_id": document_object.id,
            "entity_count": len(entity_objects),
            "relation_count": len(relation_objects),
        }

    def load_object_pattern(self, *, object_name: str) -> dict[str, Any] | None:
        return _deepcopy_object(OBJECT_MAPPING_PATTERN_BY_NAME.get(_normalize_document_object_name(object_name)))

    def _load_pattern_value(
        self,
        *,
        object_payload: Mapping[str, Any],
        value_path_list: Sequence[str],
    ) -> str | None:
        return _first_non_empty_string(_mapping_value(object_payload, value_path) for value_path in value_path_list)

    def _load_pattern_attribute_map(
        self,
        *,
        object_payload: Mapping[str, Any],
        attribute_path_map: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        attribute_map: dict[str, Any] = {}
        for attribute_key, value_path in dict(attribute_path_map or {}).items():
            attribute_map[str(attribute_key)] = _mapping_value(object_payload, value_path)
        return attribute_map

    def _build_pattern_section_line_list(
        self,
        *,
        object_payload: Mapping[str, Any],
        section_pattern: Mapping[str, Any],
    ) -> list[str]:
        line_list: list[str] = []
        for field_pattern in section_pattern.get("field_line_list") or []:
            path_list = tuple(field_pattern.get("path_list") or ()) or ((field_pattern.get("path"),) if field_pattern.get("path") else ())
            field_value = self._load_pattern_value(object_payload=object_payload, value_path_list=path_list)
            if not field_value:
                continue
            line_list.append(f"{field_pattern.get('label')}: {field_value}")
        for group_pattern in section_pattern.get("group_line_list") or []:
            item_list = _load_string_list(_mapping_value(object_payload, str(group_pattern.get("path") or "")))
            if not item_list:
                continue
            if bool(group_pattern.get("emit_label_only_when_items", True)):
                line_list.append(f"{group_pattern.get('label')}:")
            line_list.extend(f"- {item_value}" for item_value in item_list)
        return line_list

    def _build_pattern_block_seed_objects(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        correlation_id: str,
        object_pattern: Mapping[str, Any],
    ) -> list[MappingBlockSeedObject]:
        seed_object_list: list[MappingBlockSeedObject] = []
        for section_pattern in object_pattern.get("section_pattern_list") or []:
            line_list = self._build_pattern_section_line_list(object_payload=object_payload, section_pattern=section_pattern)
            if not line_list:
                continue
            seed_object_list.append(
                MappingBlockSeedObject(
                    section_key=str(section_pattern.get("section_key") or f"section_{len(seed_object_list) + 1}"),
                    block_id=f"blk:{correlation_id}:{len(seed_object_list) + 1}",
                    block_no=len(seed_object_list) + 1,
                    heading=str(section_pattern.get("heading") or object_name.replace("_", " ").title()),
                    content="\n".join(line_list),
                    block_kind=str(section_pattern.get("block_kind") or "chunk"),
                    metadata={"section_type": str(section_pattern.get("section_type_key") or section_pattern.get("section_key") or "section")},
                ),
            )
        if seed_object_list:
            return seed_object_list
        return self._build_generic_block_seed_objects(
            object_name=object_name,
            object_payload=object_payload,
            correlation_id=correlation_id,
        )

    def _build_explicit_block_seed_objects(
        self,
        *,
        object_name: str,
        correlation_id: str,
        raw_text_payload: Mapping[str, Any],
    ) -> list[MappingBlockSeedObject]:
        if not raw_text_payload:
            return []
        seed_object_list: list[MappingBlockSeedObject] = []
        section_payload_list = raw_text_payload.get("sections")
        if isinstance(section_payload_list, Sequence) and not isinstance(section_payload_list, (str, bytes, bytearray)):
            for section_payload in section_payload_list:
                if not isinstance(section_payload, Mapping):
                    continue
                section_text = _first_non_empty_string([section_payload.get("text"), section_payload.get("content")])
                if not section_text:
                    continue
                section_key = _first_non_empty_string([section_payload.get("section_key")]) or f"section_{len(seed_object_list) + 1}"
                section_metadata = _deepcopy_object(section_payload.get("metadata") if isinstance(section_payload.get("metadata"), Mapping) else {})
                section_metadata.setdefault("section_type", section_key)
                seed_object_list.append(
                    MappingBlockSeedObject(
                        section_key=section_key,
                        block_id=f"blk:{correlation_id}:{len(seed_object_list) + 1}",
                        block_no=len(seed_object_list) + 1,
                        heading=_first_non_empty_string([section_payload.get("heading"), raw_text_payload.get("title")]) or object_name.replace("_", " ").title(),
                        content=section_text,
                        block_kind=_first_non_empty_string([section_payload.get("block_kind")]) or "section",
                        metadata=section_metadata,
                    ),
                )
        if seed_object_list:
            return seed_object_list
        raw_text = _first_non_empty_string([raw_text_payload.get("raw_text"), raw_text_payload.get("text")])
        if not raw_text:
            return []
        return [
            MappingBlockSeedObject(
                section_key="document",
                block_id=f"blk:{correlation_id}:1",
                block_no=1,
                heading=_first_non_empty_string([raw_text_payload.get("title")]) or object_name.replace("_", " ").title(),
                content=raw_text,
                block_kind="document",
                metadata={"section_type": "document"},
            ),
        ]

    def _build_pattern_seed_entity_objects(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        correlation_id: str,
        object_pattern: Mapping[str, Any],
    ) -> list[MappingSeedEntityObject]:
        seed_object_list: list[MappingSeedEntityObject] = []
        subject_pattern = dict(object_pattern.get("subject_pattern") or {})
        subject_name = self._load_pattern_value(
            object_payload=object_payload,
            value_path_list=tuple(subject_pattern.get("value_path_list") or ("title", "name", "full_name")),
        ) or correlation_id
        seed_object_list.append(
            MappingSeedEntityObject(
                seed_key=str(subject_pattern.get("seed_key") or "subject"),
                type_key=str(subject_pattern.get("type_key") or object_name),
                canonical_name=subject_name,
                section_key=str(subject_pattern.get("section_key") or "primary"),
                mention_text=subject_name,
                confidence=float(subject_pattern.get("confidence") or 0.99),
                summary=str(subject_pattern.get("summary") or f"Primary {object_name.replace('_', ' ')} object mapped from the parsed result."),
                attributes=self._load_pattern_attribute_map(
                    object_payload=object_payload,
                    attribute_path_map=subject_pattern.get("attribute_path_map"),
                ),
            ),
        )
        for entity_pattern in object_pattern.get("entity_pattern_list") or []:
            canonical_name = self._load_pattern_value(
                object_payload=object_payload,
                value_path_list=tuple(entity_pattern.get("value_path_list") or ()),
            )
            if not canonical_name:
                continue
            type_key = str(entity_pattern.get("type_key") or object_name)
            seed_object_list.append(
                MappingSeedEntityObject(
                    seed_key=f"{type_key}:{_slugify_object_name(canonical_name)}",
                    type_key=type_key,
                    canonical_name=canonical_name,
                    section_key=str(entity_pattern.get("section_key") or "primary"),
                    relation_type_key=str(entity_pattern.get("relation_type_key") or "").strip() or None,
                    confidence=float(entity_pattern.get("confidence") or 0.95),
                    mention_text=canonical_name,
                    summary=str(entity_pattern.get("summary") or f"{type_key.replace('_', ' ').title()} associated with the mapped object."),
                    attributes=self._load_pattern_attribute_map(
                        object_payload=object_payload,
                        attribute_path_map=entity_pattern.get("attribute_path_map"),
                    ),
                    metadata={"source_field": entity_pattern.get("source_field")},
                ),
            )
        for entity_pattern in object_pattern.get("collection_entity_pattern_list") or []:
            collection_value_list = _load_string_list(_mapping_value(object_payload, str(entity_pattern.get("collection_path") or "")))
            for collection_value in collection_value_list:
                type_key = _load_type_key_from_pattern(
                    collection_value,
                    fallback_type_key=str(entity_pattern.get("fallback_type_key") or object_name),
                    type_key_pattern_map=entity_pattern.get("type_key_pattern_map"),
                )
                relation_type_key_map = dict(entity_pattern.get("relation_type_key_map") or {})
                relation_type_key = str(relation_type_key_map.get(type_key) or relation_type_key_map.get(str(entity_pattern.get("fallback_type_key") or "")) or "").strip() or None
                seed_object_list.append(
                    MappingSeedEntityObject(
                        seed_key=f"{str(entity_pattern.get('seed_key_prefix') or type_key)}:{_slugify_object_name(collection_value)}",
                        type_key=type_key,
                        canonical_name=collection_value,
                        section_key=str(entity_pattern.get("section_key") or "primary"),
                        relation_type_key=relation_type_key,
                        confidence=float(entity_pattern.get("confidence") or 0.9),
                        mention_text=collection_value,
                        summary=str(entity_pattern.get("summary_prefix") or "Associated capability mapped from the parsed result."),
                        metadata={"source_field": entity_pattern.get("source_field")},
                    ),
                )
        unique_seed_object_list: list[MappingSeedEntityObject] = []
        seen_seed_key_set: set[str] = set()
        for seed_object in seed_object_list:
            if seed_object.seed_key in seen_seed_key_set:
                continue
            seen_seed_key_set.add(seed_object.seed_key)
            unique_seed_object_list.append(seed_object)
        return unique_seed_object_list

    def _build_explicit_entity_candidate_objects(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        correlation_id: str,
        entity_payload_list: Sequence[Mapping[str, Any]],
    ) -> list[MappingSeedEntityObject]:
        if not entity_payload_list:
            return []
        seed_object_list: list[MappingSeedEntityObject] = []
        for entity_payload in entity_payload_list:
            type_key = _first_non_empty_string([entity_payload.get("entity_type"), entity_payload.get("type_key")]) or object_name
            canonical_name = _first_non_empty_string(
                [
                    entity_payload.get("canonical_name"),
                    entity_payload.get("name"),
                    entity_payload.get("title"),
                    entity_payload.get("mention_text"),
                ],
            )
            if not canonical_name:
                continue
            entity_metadata = _deepcopy_object(entity_payload.get("metadata") if isinstance(entity_payload.get("metadata"), Mapping) else {})
            source_field = _first_non_empty_string([entity_payload.get("source_field"), entity_metadata.get("source_field")])
            if source_field:
                entity_metadata["source_field"] = source_field
            entity_metadata.setdefault("mapped_from", "explicit_entity_model")
            seed_key = _first_non_empty_string([entity_payload.get("entity_key"), entity_payload.get("seed_key")]) or f"{type_key}:{_slugify_object_name(canonical_name)}"
            seed_object_list.append(
                MappingSeedEntityObject(
                    seed_key=seed_key,
                    type_key=type_key,
                    canonical_name=canonical_name,
                    section_key=_first_non_empty_string([entity_payload.get("section_key")]) or "primary",
                    relation_type_key=_first_non_empty_string([entity_payload.get("relation_type"), entity_payload.get("relation_type_key")]),
                    confidence=_first_number([entity_payload.get("confidence")]) or 0.95,
                    mention_text=_first_non_empty_string([entity_payload.get("mention_text")]) or canonical_name,
                    summary=_first_non_empty_string([entity_payload.get("summary")]) or "",
                    attributes=_deepcopy_object(entity_payload.get("attributes") if isinstance(entity_payload.get("attributes"), Mapping) else {}),
                    aliases=_load_string_list(entity_payload.get("aliases")),
                    metadata=entity_metadata,
                ),
            )
        if not any(seed_object.seed_key == "subject" for seed_object in seed_object_list):
            canonical_name = _first_non_empty_string(
                [
                    object_payload.get("job_title"),
                    object_payload.get("title"),
                    correlation_id,
                ],
            ) or correlation_id
            seed_object_list.insert(
                0,
                MappingSeedEntityObject(
                    seed_key="subject",
                    type_key=object_name,
                    canonical_name=canonical_name,
                    section_key="primary",
                    confidence=0.99,
                    mention_text=canonical_name,
                    summary=f"Primary {object_name.replace('_', ' ')} entity mapped from parser result.",
                    metadata={"mapped_from": "compatibility_subject"},
                ),
            )
        unique_seed_object_list: list[MappingSeedEntityObject] = []
        seen_seed_key_set: set[str] = set()
        for seed_object in seed_object_list:
            if seed_object.seed_key in seen_seed_key_set:
                continue
            seen_seed_key_set.add(seed_object.seed_key)
            unique_seed_object_list.append(seed_object)
        return unique_seed_object_list

    def _build_generic_block_seed_objects(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        correlation_id: str,
    ) -> list[MappingBlockSeedObject]:
        content = _first_non_empty_string([
            object_payload.get("raw_text"),
            object_payload.get("summary"),
            object_payload.get("description"),
        ]) or str(object_payload)
        return [
            MappingBlockSeedObject(
                section_key="primary",
                block_id=f"blk:{correlation_id}:1",
                block_no=1,
                heading=object_name.replace("_", " ").title(),
                content=content,
                block_kind="section",
                metadata={"section_type": "primary"},
            ),
        ]

    def _build_generic_entity_candidate_objects(
        self,
        *,
        object_name: str,
        object_payload: Mapping[str, Any],
        correlation_id: str,
    ) -> list[MappingSeedEntityObject]:
        canonical_name = _first_non_empty_string([
            object_payload.get("title"),
            object_payload.get("name"),
            object_payload.get("full_name"),
            correlation_id,
        ]) or correlation_id
        return [
            MappingSeedEntityObject(
                seed_key="subject",
                type_key=object_name,
                canonical_name=canonical_name,
                section_key="primary",
                relation_type_key=None,
                confidence=0.99,
                mention_text=canonical_name,
                summary=f"Primary {object_name.replace('_', ' ')} entity mapped from parser result.",
            ),
        ]

    def _build_entity_id(self, *, object_name: str, entity_type: str, canonical_name: str) -> str:
        return f"ent:{_normalize_document_object_name(object_name)}:{entity_type}:{_slugify_object_name(canonical_name, fallback_prefix=entity_type)}"

    def build_retrieval_result_objects(
        self,
        *,
        tool_name: str,
        retrieval_result: Any,
    ) -> list[RetrievalResultObject]:
        if not isinstance(retrieval_result, list):
            return []
        retrieval_result_objects: list[RetrievalResultObject] = []
        for index, item in enumerate(retrieval_result, start=1):
            if isinstance(item, Mapping):
                item_payload = dict(item)
                result_id = _first_non_empty_string([
                    item_payload.get("result_id"),
                    item_payload.get("document_id"),
                    item_payload.get("id"),
                    item_payload.get("source"),
                    item_payload.get("path"),
                    item_payload.get("title"),
                ]) or f"{tool_name}:{index}"
                result_type = _first_non_empty_string([
                    item_payload.get("result_type"),
                    item_payload.get("owner_type"),
                ]) or "document"
                source_stage = _first_non_empty_string([
                    item_payload.get("source_stage"),
                    item_payload.get("backend"),
                ]) or tool_name
                metadata = _deepcopy_object(item_payload)
                lexical_score = _first_number([
                    item_payload.get("lexical_score"),
                    item_payload.get("document_score"),
                ])
                vector_score = _first_number([
                    item_payload.get("vector_score"),
                    item_payload.get("relevance_score"),
                    item_payload.get("score"),
                ])
                graph_score = _first_number([
                    item_payload.get("graph_score"),
                ])
                rerank_score = _first_number([
                    item_payload.get("rerank_score"),
                ])
            else:
                result_id = f"{tool_name}:{index}"
                result_type = "document"
                source_stage = tool_name
                metadata = {"value": _deepcopy_object(item)}
                lexical_score = None
                vector_score = None
                graph_score = None
                rerank_score = None
            retrieval_result_objects.append(
                RetrievalResultObject(
                    rank_no=index,
                    result_type=result_type,
                    result_id=result_id,
                    source_stage=source_stage,
                    chosen=True,
                    lexical_score=lexical_score,
                    vector_score=vector_score,
                    graph_score=graph_score,
                    rerank_score=rerank_score,
                    metadata=metadata,
                ),
            )
        return retrieval_result_objects

    def build_retrieval_run_object(
        self,
        *,
        tool_name: str,
        query_event: Mapping[str, Any],
        outcome_event: Mapping[str, Any],
        retrieval_result: Any,
    ) -> RetrievalRunObject:
        namespace_object = self.load_namespace_object(
            handoff_metadata=query_event if isinstance(query_event, Mapping) else None,
            handoff_payload=query_event if isinstance(query_event, Mapping) else None,
        )
        policy_snapshot = query_event.get("policy_snapshot") if isinstance(query_event.get("policy_snapshot"), Mapping) else {}
        return RetrievalRunObject(
            id=f"retrieval:{query_event.get('event_id')}",
            tenant_id=namespace_object.tenant_id,
            namespace_id=namespace_object.id,
            query_text=str(query_event.get("query_text") or ""),
            requested_k=max(1, int(query_event.get("k") or 1)),
            lexical_k=int(policy_snapshot.get("fetch_k") or 0) or None,
            graph_hops=None,
            vector_k=max(1, int(query_event.get("k") or 1)),
            rerank_strategy=str(policy_snapshot.get("rerank_method") or "none") or "none",
            correlation_id=_first_non_empty_string([
                query_event.get("event_id"),
                outcome_event.get("query_event_id"),
            ]),
            filters=_deepcopy_object(dict(policy_snapshot.get("metadata_filters") or {})),
            results=self.build_retrieval_result_objects(tool_name=tool_name, retrieval_result=retrieval_result),
            created_at=_now_utc(),
        )

    def store_retrieval_run(
        self,
        *,
        tool_name: str,
        query_event: Mapping[str, Any],
        outcome_event: Mapping[str, Any],
        retrieval_result: Any,
    ) -> Mapping[str, Any]:
        namespace_object = self.load_namespace_object(
            handoff_metadata=query_event if isinstance(query_event, Mapping) else None,
            handoff_payload=query_event if isinstance(query_event, Mapping) else None,
        )
        retrieval_run_object = self.build_retrieval_run_object(
            tool_name=tool_name,
            query_event=query_event,
            outcome_event=outcome_event,
            retrieval_result=retrieval_result,
        )
        retrieval_run_object.filters.update(
            {
                "tool_name": tool_name,
                "session_id": query_event.get("session_id"),
                "agent": query_event.get("agent"),
                "success": bool(outcome_event.get("success")),
                "latency_ms": outcome_event.get("latency_ms"),
                "reward": outcome_event.get("reward"),
            },
        )
        if outcome_event.get("error"):
            retrieval_run_object.filters["error"] = outcome_event.get("error")
        self._knowledge_service.store_namespace_object(namespace_object)
        self._knowledge_service.store_retrieval_run_object(retrieval_run_object)
        return {
            "ok": True,
            "stored": True,
            "backend": "agents_db",
            "namespace_id": namespace_object.id,
            "retrieval_run_id": retrieval_run_object.id,
        }


_AGENTS_DB_PIPELINE_SERVICE_CACHE: dict[tuple[str, ...], PipelineService] = {}


def load_agentsdb_runtime_config_from_env() -> RuntimeConfigObject | None:
    connection_config = _load_agentsdb_connection_config()
    agents_db_uri = str(
        os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_URI", "")
        or os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_BACKEND_URI", ""),
    ).strip()
    if not agents_db_uri:
        configured_socket_uri = _load_agentsdb_uri_from_connection_config(connection_config)
        backend_uri = _connection_config_value(connection_config, ("backend_uri", "agents_db_backend_uri", "storage_uri", "storage_backend_uri"))
        agents_db_uri = configured_socket_uri or backend_uri
    if not agents_db_uri:
        return None
    try:
        default_embedding_dimension = int(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_EMBEDDING_DIMENSION", "")
            or "3072"
            or 3072,
        )
    except Exception:
        default_embedding_dimension = 3072
    return RuntimeConfigObject(
        agents_db_uri=agents_db_uri,
        database_name=str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_NAME", "")
            or "alde_knowledge",
        ).strip()
        or _connection_config_value(connection_config, ("database_name", "database"))
        or "alde_knowledge",
        tenant_id=str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_TENANT_ID", "")
            or "tenant_default",
        ).strip()
        or "tenant_default",
        namespace_id=str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_NAMESPACE_ID", "")
            or "ns_alde_default",
        ).strip()
        or "ns_alde_default",
        namespace_slug=str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_NAMESPACE_SLUG", "")
            or "alde-default",
        ).strip()
        or "alde-default",
        namespace_name=str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_NAMESPACE_NAME", "")
            or "ALDE Default Knowledge",
        ).strip()
        or "ALDE Default Knowledge",
        default_embedding_model=str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_EMBEDDING_MODEL", "")
            or "text-embedding-3-large",
        ).strip()
        or "text-embedding-3-large",
        default_embedding_dimension=max(1, default_embedding_dimension),
        index_backend=str(
            os.getenv("AI_IDE_KNOWLEDGE_AGENTS_DB_INDEX_BACKEND", "")
            or "faiss",
        ).strip()
        or "faiss",
    )


def load_mongodb_runtime_config_from_env() -> RuntimeConfigObject | None:
    return load_agentsdb_runtime_config_from_env()


def load_agentsdb_pipeline_service(runtime_config: RuntimeConfigObject) -> PipelineService:
    cache_key = (
        runtime_config.agents_db_uri,
        runtime_config.database_name,
        runtime_config.tenant_id,
        runtime_config.namespace_id,
        runtime_config.namespace_slug,
        runtime_config.namespace_name,
        runtime_config.default_embedding_model,
        str(runtime_config.default_embedding_dimension),
        runtime_config.index_backend,
    )
    existing_service = _AGENTS_DB_PIPELINE_SERVICE_CACHE.get(cache_key)
    if existing_service is not None:
        return existing_service
    if _is_agentsdb_socket_uri(runtime_config.agents_db_uri):
        repository: Any = AgentDbSocketRepository.create_from_uri(
            runtime_config.agents_db_uri,
            runtime_config.database_name,
        )
    else:
        repository = KnowledgeRepository.create_from_uri(runtime_config.agents_db_uri, runtime_config.database_name)
    repository.ensure_index_objects()
    pipeline_service = PipelineService(KnowledgeObjectService(repository), runtime_config)
    _AGENTS_DB_PIPELINE_SERVICE_CACHE[cache_key] = pipeline_service
    return pipeline_service


def load_mongodb_pipeline_service(runtime_config: RuntimeConfigObject) -> PipelineService:
    return load_agentsdb_pipeline_service(runtime_config)


def sync_retrieval_run_to_agentsdb_knowledge(
    *,
    tool_name: str,
    query_event: Mapping[str, Any],
    outcome_event: Mapping[str, Any],
    retrieval_result: Any,
) -> Mapping[str, Any] | None:
    runtime_config = load_agentsdb_runtime_config_from_env()
    if runtime_config is None:
        return None
    try:
        pipeline_service = load_agentsdb_pipeline_service(runtime_config)
        return pipeline_service.store_retrieval_run(
            tool_name=tool_name,
            query_event=query_event,
            outcome_event=outcome_event,
            retrieval_result=retrieval_result,
        )
    except Exception as exc:
        return {
            "ok": False,
            "stored": False,
            "backend": "agents_db",
            "error": "agents_db_sync_failed",
            "detail": str(exc),
        }


def sync_parser_result_to_agentsdb_knowledge(
    *,
    object_name: str,
    result_payload: Mapping[str, Any],
    correlation_id: str | None = None,
    handoff_metadata: Mapping[str, Any] | None = None,
    handoff_payload: Mapping[str, Any] | None = None,
) -> Mapping[str, Any] | None:
    runtime_config = load_agentsdb_runtime_config_from_env()
    if runtime_config is None:
        return None
    try:
        pipeline_service = load_agentsdb_pipeline_service(runtime_config)
        mapping_service = ObjectMappingService(
            pipeline_service._knowledge_service,
            runtime_config,
        )
        return mapping_service.store_mapped_object(
            object_name=object_name,
            result_payload=result_payload,
            fallback_correlation_id=correlation_id,
            handoff_metadata=handoff_metadata,
            handoff_payload=handoff_payload,
        )
    except Exception as exc:
        return {
            "ok": False,
            "stored": False,
            "backend": "agents_db",
            "object_name": _normalize_document_object_name(object_name),
            "error": "agents_db_parser_sync_failed",
            "detail": str(exc),
        }


def build_demo_agentsdb_service(database: Any) -> KnowledgeObjectService:
    repository = KnowledgeRepository(database)
    repository.ensure_index_objects()
    return KnowledgeObjectService(repository)


# Legacy compatibility aliases: keep until downstream imports are migrated.
sync_retrieval_run_to_mongodb_knowledge = sync_retrieval_run_to_agentsdb_knowledge
sync_parser_result_to_mongodb_knowledge = sync_parser_result_to_agentsdb_knowledge
load_mongodb_runtime_config_from_env = load_agentsdb_runtime_config_from_env
load_mongodb_pipeline_service = load_agentsdb_pipeline_service
AgnDB = KnowledgeRepository
AgnDBService = KnowledgeObjectService
PsrObjMapSvc = ObjectMappingService
ParserBlockSeedObject = MappingBlockSeedObject
ParserEntityCandidateObject = MappingSeedEntityObject
ParserObjectKnowledgeMappingService = ObjectMappingService
DocumentBlockObject = BlockObject
KnowledgeNamespaceObject = NamespaceObject
AgentsDBKnowledgeRepository = KnowledgeRepository
AgentsDBKnowledgeRuntimeConfigObject = RuntimeConfigObject
AgentsDBKnowledgeService = KnowledgeObjectService
AgentsDBKnowledgePipelineService = PipelineService

# Legacy compatibility aliases for old Mongo naming.
MongoKnowledgeRepository = AgentsDBKnowledgeRepository
MongoKnowledgeRuntimeConfigObject = AgentsDBKnowledgeRuntimeConfigObject
MongoKnowledgeService = AgentsDBKnowledgeService
MongoKnowledgePipelineService = AgentsDBKnowledgePipelineService
build_demo_mongodb_service = build_demo_agentsdb_service


class JobPostingKnowledgeDatasetExampleService:
    """Build a complete example dataset from a single extracted job-offer PDF."""

    def __init__(self) -> None:
        self._timestamp = _demo_dataset_timestamp()
        self._tenant_id = "tenant_demo"
        self._namespace_id = "ns_jobs_de"
        self._namespace_slug = "jobs-de"
        self._namespace_name = "Jobs Deutschland"
        self._correlation_id = "job-offer:examplecorp:it-service-desk-coordinator"
        self._document_type = "job_posting"
        self._document_id = f"doc:{self._document_type}:{self._correlation_id}"
        self._source_uri = "file://AppData/job_offer_examplecorp_it_service_desk_coordinator.pdf"
        self._embedding_model = "demo-text-embedding-8d"
        self._embedding_dimension = 8

    def load_namespace_object(self) -> NamespaceObject:
        return NamespaceObject(
            id=self._namespace_id,
            tenant_id=self._tenant_id,
            slug=self._namespace_slug,
            name=self._namespace_name,
            description="Beispielhafter Wissensraum fuer Job-Posting-Extraktion aus PDFs.",
            default_embedding_model=self._embedding_model,
            default_embedding_dimension=self._embedding_dimension,
            metadata={"locale": "de-DE", "example": True},
            created_at=self._timestamp,
            updated_at=self._timestamp,
        )

    def load_job_posting_object(self) -> dict[str, Any]:
        return {
            "$schema_version": "1.0",
            "jobtitel": "IT Service Desk Coordinator (m/w/d)",
            "arbeitgeber": "ExampleCorp",
            "arbeitsort": "Remote (EU)",
            "anstellungsart": "Vollzeit",
            "befristung": "unbefristet",
            "beginn": "ab sofort",
            "berufsbezeichnung": "IT-Produktkoordinator/in",
            "mission": "Example job posting used to demonstrate the job posting schema and downstream parsing workflows.",
            "aufgaben": [
                "Koordination des Servicedesk-Teams zur Sicherstellung der effizienten, zuverlaessigen Bearbeitung der Anfragen interner IT-Anwender",
                "Mitarbeit bei und Ueberpruefung von schwierigen bzw. besonderen Tickets",
                "Ueberwachung und Betreuung von Eskalationen zur Unterstuetzung schneller, prozesstreuer Loesungen",
                "Analyse von Ursachen fuer Loesungsverzoegerungen oder Incidents und Ableitung geeigneter Massnahmen",
                "Customizing und Optimierung des Ticket-Systems",
                "Etablierung von KPIs zur Steuerung eines erfolgreichen Servicedesks",
                "Zustaendigkeit fuer die Endpoint-Verwaltung (Beschaffung, Asset Management)",
            ],
            "profil": [
                "Abgeschlossene Ausbildung zum Fachinformatiker (m/w/d) oder vergleichbar",
                "Erfahrung im IT-Support",
                "Erfahrung in der Koordination eines IT-Service-Teams",
                "Erfahrung in Administration und Konfiguration von Ticket-Systemen (z. B. TOPdesk), Servicedesk-Prozessen, gaengigen IT-Standards und ITIL-Framework",
                "Strukturierte, organisierte, prozessorientierte und eigenstaendige Arbeitsweise",
                "Zuverlaessigkeit, Verantwortungs- und Qualitaetsbewusstsein",
                "Service- und loesungsorientiertes Arbeiten, analytische und konzeptionelle Staerke, Faehigkeit, Probleme schnell zu erfassen",
                "Sichere Kommunikation mit verschiedenen Ansprechpartnern im Unternehmen",
                "Sehr gute Deutschkenntnisse in Wort und Schrift; gute Englischkenntnisse von Vorteil",
            ],
            "angebot": [
                "Krisen- und zukunftssicherer Arbeitsplatz in der wachsenden Pharmabranche",
                "Teil eines innovativen und modernen Familienunternehmens",
                "Vielseitige Taetigkeiten und Aufgaben in einem spannenden Arbeitsumfeld",
                "Ausfuehrliche und fundierte fachliche Einarbeitung",
                "Langfristige Perspektiven und interne Weiterentwicklungsmoeglichkeiten",
                "Attraktive Verguetung gemaess Chemie-Tarifvertrag",
                "Zusammenarbeit mit motivierten und professionellen KollegInnen",
            ],
            "gehalt": "",
            "bewerbungsart": "E-Mail",
            "anschrift_arbeitgeber": "",
            "email": "jobs@example.com",
            "telefon": "",
        }

    def load_raw_text(self) -> str:
        job_posting_object = self.load_job_posting_object()
        tasks_text = "\n".join(f"- {item}" for item in job_posting_object["aufgaben"])
        profile_text = "\n".join(f"- {item}" for item in job_posting_object["profil"])
        offer_text = "\n".join(f"- {item}" for item in job_posting_object["angebot"])
        return "\n\n".join(
            [
                f"Jobtitel: {job_posting_object['jobtitel']}\nArbeitgeber: {job_posting_object['arbeitgeber']}\nArbeitsort: {job_posting_object['arbeitsort']}\nAnstellungsart: {job_posting_object['anstellungsart']}\nBeginn: {job_posting_object['beginn']}\nMission: {job_posting_object['mission']}",
                f"Aufgaben\n{tasks_text}",
                f"Profil\n{profile_text}",
                f"Angebot\n{offer_text}\n\nBewerbungsart: {job_posting_object['bewerbungsart']}\nE-Mail: {job_posting_object['email']}",
            ],
        )

    def load_source_pdf_metadata(self) -> dict[str, Any]:
        raw_text = self.load_raw_text()
        return {
            "file_name": "job_offer_examplecorp_it_service_desk_coordinator.pdf",
            "source_path": "AppData/job_offer_examplecorp_it_service_desk_coordinator.pdf",
            "source_uri": self._source_uri,
            "mime_type": "application/pdf",
            "page_count": 2,
            "language": "de",
            "content_sha256": _stable_sha256(raw_text),
            "extractor_backend": "demo_pdf_text_extractor",
            "ocr_used": False,
            "layout_retained": True,
            "extracted_at": self._timestamp.isoformat(),
            "metadata": {
                "producer": "example-demo",
                "example": True,
                "document_family": "job_offer_pdf",
            },
        }

    def build_block_seed_objects(self) -> list[dict[str, Any]]:
        job_posting_object = self.load_job_posting_object()
        return [
            {
                "block_id": f"blk:{self._correlation_id}:1",
                "block_no": 1,
                "block_kind": "section",
                "heading": "Stammdaten",
                "content": (
                    f"Jobtitel: {job_posting_object['jobtitel']}\n"
                    f"Arbeitgeber: {job_posting_object['arbeitgeber']}\n"
                    f"Arbeitsort: {job_posting_object['arbeitsort']}\n"
                    f"Anstellungsart: {job_posting_object['anstellungsart']}\n"
                    f"Beginn: {job_posting_object['beginn']}\n"
                    f"Mission: {job_posting_object['mission']}"
                ),
                "metadata": {"section_type": "header", "page_no": 1},
            },
            {
                "block_id": f"blk:{self._correlation_id}:2",
                "block_no": 2,
                "block_kind": "chunk",
                "heading": "Aufgaben",
                "content": "Aufgaben\n" + "\n".join(f"- {item}" for item in job_posting_object["aufgaben"]),
                "metadata": {"section_type": "responsibilities", "page_no": 1},
            },
            {
                "block_id": f"blk:{self._correlation_id}:3",
                "block_no": 3,
                "block_kind": "chunk",
                "heading": "Profil",
                "content": "Profil\n" + "\n".join(f"- {item}" for item in job_posting_object["profil"]),
                "metadata": {"section_type": "requirements", "page_no": 2},
            },
            {
                "block_id": f"blk:{self._correlation_id}:4",
                "block_no": 4,
                "block_kind": "chunk",
                "heading": "Angebot und Bewerbung",
                "content": (
                    "Angebot\n" +
                    "\n".join(f"- {item}" for item in job_posting_object["angebot"]) +
                    f"\n\nBewerbungsart: {job_posting_object['bewerbungsart']}\nE-Mail: {job_posting_object['email']}"
                ),
                "metadata": {"section_type": "benefits", "page_no": 2},
            },
        ]

    def load_entity_objects(self) -> list[EntityObject]:
        return [
            EntityObject(
                id="ent_job_it_service_desk_coordinator",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="job_posting",
                canonical_name="IT Service Desk Coordinator (m/w/d)",
                external_key="job:examplecorp:it-service-desk-coordinator",
                correlation_id=self._correlation_id,
                summary="Stellenprofil fuer die Koordination eines IT-Service-Desk-Teams.",
                attributes={"employment_type": "Vollzeit", "work_mode": "Remote (EU)", "start_date": "ab sofort"},
                aliases=[EntityAliasObject(alias="IT-Produktkoordinator/in", locale="de", confidence=0.96, source_document_id=self._document_id, created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_company_examplecorp",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="organization",
                canonical_name="ExampleCorp",
                external_key="org:examplecorp",
                correlation_id=self._correlation_id,
                summary="Arbeitgeber der Beispiel-Stellenanzeige.",
                attributes={"industry": "pharma", "organization_kind": "familienunternehmen"},
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_location_remote_eu",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="location",
                canonical_name="Remote (EU)",
                external_key="location:remote-eu",
                correlation_id=self._correlation_id,
                summary="Arbeitsort der Stelle innerhalb der EU im Remote-Modell.",
                attributes={"mode": "remote", "region": "EU"},
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_employment_vollzeit",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="employment_type",
                canonical_name="Vollzeit",
                external_key="employment:full-time",
                correlation_id=self._correlation_id,
                summary="Anstellungsart der Stelle.",
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_skill_it_support",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="skill",
                canonical_name="IT-Support",
                external_key="skill:it-support",
                correlation_id=self._correlation_id,
                summary="Praxis in der Unterstuetzung interner IT-Anwender.",
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_tool_topdesk",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="tool",
                canonical_name="TOPdesk",
                external_key="tool:topdesk",
                correlation_id=self._correlation_id,
                summary="Beispiel fuer ein Ticket-System im Stellenprofil.",
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_framework_itil",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="framework",
                canonical_name="ITIL",
                external_key="framework:itil",
                correlation_id=self._correlation_id,
                summary="IT-Service-Management-Framework im Anforderungsprofil.",
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_language_deutsch",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="language",
                canonical_name="Deutsch",
                external_key="language:de",
                correlation_id=self._correlation_id,
                summary="Erforderliche Sprachkompetenz fuer die Stelle.",
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityObject(
                id="ent_language_englisch",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                entity_type="language",
                canonical_name="Englisch",
                external_key="language:en",
                correlation_id=self._correlation_id,
                summary="Wuenschenswerte Sprachkompetenz fuer die Stelle.",
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
        ]

    def load_entity_object_map(self) -> dict[str, EntityObject]:
        entity_objects = self.load_entity_objects()
        return {entity_object.id: entity_object for entity_object in entity_objects}

    def _load_mention(self, block_content: str, *, entity_id: str, mention_text: str, extractor: str, confidence: float) -> EntityMentionObject:
        char_start = block_content.find(mention_text)
        char_end = char_start + len(mention_text) if char_start >= 0 else None
        return EntityMentionObject(
            entity_id=entity_id,
            mention_text=mention_text,
            extractor=extractor,
            confidence=confidence,
            char_start=char_start if char_start >= 0 else None,
            char_end=char_end,
            metadata={"example": True, "extractor_version": "demo-v1"},
            created_at=self._timestamp,
        )

    def build_document_block_objects(self) -> list[BlockObject]:
        raw_text = self.load_raw_text()
        block_seed_objects = self.build_block_seed_objects()
        current_offset = 0
        block_objects: list[BlockObject] = []
        for index, block_seed_object in enumerate(block_seed_objects):
            block_content = str(block_seed_object["content"])
            char_start = raw_text.find(block_content, current_offset)
            char_end = char_start + len(block_content) if char_start >= 0 else None
            current_offset = max(current_offset, char_end or current_offset)
            mentions: list[EntityMentionObject] = []
            if index == 0:
                mentions.extend(
                    [
                        self._load_mention(block_content, entity_id="ent_job_it_service_desk_coordinator", mention_text="IT Service Desk Coordinator", extractor="layout_rule", confidence=0.99),
                        self._load_mention(block_content, entity_id="ent_company_examplecorp", mention_text="ExampleCorp", extractor="layout_rule", confidence=0.99),
                        self._load_mention(block_content, entity_id="ent_location_remote_eu", mention_text="Remote (EU)", extractor="layout_rule", confidence=0.98),
                        self._load_mention(block_content, entity_id="ent_employment_vollzeit", mention_text="Vollzeit", extractor="layout_rule", confidence=0.98),
                    ],
                )
            elif index == 2:
                mentions.extend(
                    [
                        self._load_mention(block_content, entity_id="ent_skill_it_support", mention_text="IT-Support", extractor="ner", confidence=0.95),
                        self._load_mention(block_content, entity_id="ent_tool_topdesk", mention_text="TOPdesk", extractor="ner", confidence=0.97),
                        self._load_mention(block_content, entity_id="ent_framework_itil", mention_text="ITIL", extractor="ner", confidence=0.97),
                        self._load_mention(block_content, entity_id="ent_language_deutsch", mention_text="Deutschkenntnisse", extractor="ner", confidence=0.93),
                        self._load_mention(block_content, entity_id="ent_language_englisch", mention_text="Englischkenntnisse", extractor="ner", confidence=0.9),
                    ],
                )
            block_objects.append(
               BlockObject(
                    block_id=str(block_seed_object["block_id"]),
                    block_no=int(block_seed_object["block_no"]),
                    content=block_content,
                    block_kind=str(block_seed_object["block_kind"]),
                    heading=str(block_seed_object["heading"]),
                    token_count=len(block_content.split()),
                    char_start=char_start if char_start >= 0 else None,
                    char_end=char_end,
                    metadata=_deepcopy_object(dict(block_seed_object["metadata"])),
                    mentions=mentions,
                    created_at=self._timestamp,
                ),
            )
        return block_objects

    def build_document_object(self) -> DocumentObject:
        job_posting_object = self.load_job_posting_object()
        raw_text = self.load_raw_text()
        source_pdf_metadata = self.load_source_pdf_metadata()
        return DocumentObject(
            id=self._document_id,
            tenant_id=self._tenant_id,
            namespace_id=self._namespace_id,
            document_type=self._document_type,
            title=str(job_posting_object["jobtitel"]),
            source_uri=self._source_uri,
            content_sha256=str(source_pdf_metadata["content_sha256"]),
            source_system="pdf_upload",
            mime_type="application/pdf",
            language_code="de",
            correlation_id=self._correlation_id,
            summary=str(job_posting_object["mission"]),
            metadata={
                "company_name": job_posting_object["arbeitgeber"],
                "location": job_posting_object["arbeitsort"],
                "employment_type": job_posting_object["anstellungsart"],
                "source_pdf": source_pdf_metadata,
                "raw_text_sha256": _stable_sha256(raw_text),
                "example": True,
            },
            blocks=self.build_document_block_objects(),
            created_at=self._timestamp,
            updated_at=self._timestamp,
        )

    def build_relation_objects(self) -> list[EntityRelationObject]:
        return [
            EntityRelationObject(
                id="rel_job_company_examplecorp",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_company_examplecorp",
                relation_type="offered_by",
                direction="directed",
                weight=1.0,
                confidence=0.99,
                correlation_id=self._correlation_id,
                metadata={"source": "header_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:1", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityRelationObject(
                id="rel_job_location_remote_eu",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_location_remote_eu",
                relation_type="located_in",
                direction="directed",
                weight=0.92,
                confidence=0.98,
                correlation_id=self._correlation_id,
                metadata={"source": "header_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:1", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityRelationObject(
                id="rel_job_employment_vollzeit",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_employment_vollzeit",
                relation_type="employment_type",
                direction="directed",
                weight=0.88,
                confidence=0.98,
                correlation_id=self._correlation_id,
                metadata={"source": "header_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:1", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityRelationObject(
                id="rel_job_skill_it_support",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_skill_it_support",
                relation_type="requires_skill",
                direction="directed",
                weight=0.95,
                confidence=0.95,
                correlation_id=self._correlation_id,
                metadata={"source": "requirements_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:3", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityRelationObject(
                id="rel_job_tool_topdesk",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_tool_topdesk",
                relation_type="uses_tool",
                direction="directed",
                weight=0.81,
                confidence=0.97,
                correlation_id=self._correlation_id,
                metadata={"source": "requirements_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:3", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityRelationObject(
                id="rel_job_framework_itil",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_framework_itil",
                relation_type="requires_framework_knowledge",
                direction="directed",
                weight=0.84,
                confidence=0.97,
                correlation_id=self._correlation_id,
                metadata={"source": "requirements_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:3", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityRelationObject(
                id="rel_job_language_deutsch",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_language_deutsch",
                relation_type="requires_language",
                direction="directed",
                weight=0.9,
                confidence=0.93,
                correlation_id=self._correlation_id,
                metadata={"source": "requirements_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:3", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
            EntityRelationObject(
                id="rel_job_language_englisch",
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                source_entity_id="ent_job_it_service_desk_coordinator",
                target_entity_id="ent_language_englisch",
                relation_type="prefers_language",
                direction="directed",
                weight=0.45,
                confidence=0.9,
                correlation_id=self._correlation_id,
                metadata={"source": "requirements_section", "example": True},
                evidence=[RelationEvidenceObject(block_id=f"blk:{self._correlation_id}:3", created_at=self._timestamp)],
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
        ]

    def build_embedding_objects(self) -> list[EmbeddingObject]:
        document_object = self.build_document_object()
        embedding_objects = [
            EmbeddingObject(
                tenant_id=self._tenant_id,
                namespace_id=self._namespace_id,
                model_id=self._embedding_model,
                owner_type="document",
                owner_id=document_object.id,
                content_sha256=document_object.content_sha256,
                dimension=self._embedding_dimension,
                index_namespace=self._namespace_id,
                index_item_key=document_object.id,
                embedding=_demo_embedding_vector(document_object.id, self._embedding_dimension),
                index_backend="faiss",
                metadata={"source_stage": "document_embedding", "example": True},
                created_at=self._timestamp,
                updated_at=self._timestamp,
            ),
        ]
        for block_object in document_object.blocks:
            embedding_objects.append(
                EmbeddingObject(
                    tenant_id=self._tenant_id,
                    namespace_id=self._namespace_id,
                    model_id=self._embedding_model,
                    owner_type="block",
                    owner_id=block_object.block_id,
                    content_sha256=_stable_sha256(block_object.content),
                    dimension=self._embedding_dimension,
                    index_namespace=self._namespace_id,
                    index_item_key=block_object.block_id,
                    chunk_hash=_stable_sha256(f"{block_object.block_id}:{block_object.content}"),
                    embedding=_demo_embedding_vector(block_object.block_id, self._embedding_dimension),
                    index_backend="faiss",
                    metadata={
                        "source_stage": "chunk_embedding",
                        "heading": block_object.heading,
                        "block_no": block_object.block_no,
                        "example": True,
                    },
                    created_at=self._timestamp,
                    updated_at=self._timestamp,
                ),
            )
        return embedding_objects

    def build_db_record(self) -> dict[str, Any]:
        job_posting_object = self.load_object()
        source_pdf_metadata = self.load_source_pdf_metadata()
        raw_text = self.load_raw_text()
        return {
            "correlation_id": self._correlation_id,
            "created_at": self._timestamp.isoformat(),
            "updated_at": self._timestamp.isoformat(),
            "source_agent": "job_posting_pdf_parser",
            "link": {
                "source_uri": self._source_uri,
                "url": "https://example.org/jobs/it-service-desk-coordinator",
                "label": "Originale Stellenanzeige",
            },
            "file": source_pdf_metadata,
            "parse": {
                "raw_text": raw_text,
                "language": "de",
                "page_count": 2,
                "extractor_backend": "demo_pdf_text_extractor",
                "extractor_method": "layout_aware_pdf_parse",
                "chunk_strategy": "section_aware",
                "chunk_count": len(self.build_block_seed_objects()),
                "is_job_posting": True,
                "warnings": [],
                "errors": [],
            },
            "job_posting": job_posting_object,
            "db_updates": {
                "processing_state": "processed",
                "processed": True,
                "document_id": self._document_id,
                "entity_count": len(self.load_entity_objects()),
                "relation_count": len(self.build_relation_objects()),
                "embedding_count": len(self.build_embedding_objects()),
            },
            "handoff_metadata": {
                "source_agent": "job_posting_pdf_parser",
                "tenant_id": self._tenant_id,
                "knowledge_namespace_id": self._namespace_id,
                "knowledge_namespace_slug": self._namespace_slug,
                "knowledge_namespace_name": self._namespace_name,
            },
            "source_payload": {
                "input_kind": "pdf_upload",
                "file_name": source_pdf_metadata["file_name"],
                "source_path": source_pdf_metadata["source_path"],
                "uploaded_by": "demo-user",
                "example": True,
            },
        }

    def build_entity_relation_graph(self) -> dict[str, Any]:
        entity_objects = self.load_entity_objects()
        relation_objects = self.build_relation_objects()
        return {
            "nodes": [
                {
                    "entity_id": entity_object.id,
                    "entity_type": entity_object.entity_type,
                    "canonical_name": entity_object.canonical_name,
                }
                for entity_object in entity_objects
            ],
            "edges": [
                {
                    "relation_id": relation_object.id,
                    "source_entity_id": relation_object.source_entity_id,
                    "target_entity_id": relation_object.target_entity_id,
                    "relation_type": relation_object.relation_type,
                    "direction": relation_object.direction,
                    "weight": relation_object.weight,
                    "confidence": relation_object.confidence,
                }
                for relation_object in relation_objects
            ],
        }

    def build_dataset(self) -> dict[str, Any]:
        namespace_object = self.load_namespace_object()
        document_object = self.build_document_object()
        entity_objects = self.load_entity_objects()
        relation_objects = self.build_relation_objects()
        embedding_objects = self.build_embedding_objects()
        db_record = self.build_db_record()
        return {
            "dataset_metadata": {
                "dataset_kind":self._namespace_id ,
                "example": True,
                "tenant_id": self._tenant_id,
                "namespace_id": self._namespace_id,
                "correlation_id": self._correlation_id,
                "generated_at": self._timestamp.isoformat(),
            },
            "source_pdf": self.load_source_pdf_metadata(),
            "raw_text": self.load_raw_text(),
            "db_record": db_record,
            "agents_db_objects": {
                "namespace": _dataclass_payload(namespace_object),
                "document": _dataclass_payload(document_object),
                "chunks": [_dataclass_payload(block_object) for block_object in document_object.blocks],
                "entities": [_dataclass_payload(entity_object) for entity_object in entity_objects],
                "relations": [_dataclass_payload(relation_object) for relation_object in relation_objects],
                "embeddings": [_dataclass_payload(embedding_object) for embedding_object in embedding_objects],
            },
            "mongodb_objects": {
                "namespace": _dataclass_payload(namespace_object),
                "document": _dataclass_payload(document_object),
                "chunks": [_dataclass_payload(block_object) for block_object in document_object.blocks],
                "entities": [_dataclass_payload(entity_object) for entity_object in entity_objects],
                "relations": [_dataclass_payload(relation_object) for relation_object in relation_objects],
                "embeddings": [_dataclass_payload(embedding_object) for embedding_object in embedding_objects],
            },
            "entity_relation_graph": self.build_entity_relation_graph(),
        }


def build_demo_job_posting_knowledge_dataset() -> dict[str, Any]:
    return JobPostingKnowledgeDatasetExampleService().build_dataset()


def build_demo_seed_objects() -> dict[str, Any]:
    namespace_object = NamespaceObject(
        id="ns_jobs_de",
        tenant_id="tenant_demo",
        slug="jobs-de",
        name="Jobs Deutschland",
        description="Wissensraum fuer Stellen, Profile und Skills.",
        default_embedding_model="text-embedding-3-large",
        default_embedding_dimension=3072,
        metadata={"locale": "de-DE"},
    )
    entity_object = EntityObject(
        id="ent_skill_python",
        tenant_id="tenant_demo",
        namespace_id="ns_jobs_de",
        entity_type="skill",
        canonical_name="Python",
        external_key="skill:python",
        correlation_id="corr-skill-python",
        summary="Programmiersprache fuer Backend, Datenverarbeitung und KI.",
        attributes={"category": "language"},
        aliases=[EntityAliasObject(alias="Python 3", locale="de")],
    )
    document_object = DocumentObject(
        id="doc_job_0001",
        tenant_id="tenant_demo",
        namespace_id="ns_jobs_de",
        document_type="job_posting",
        title="Senior Python Engineer",
        source_uri="https://example.org/jobs/0001",
        source_system="crawler",
        mime_type="text/html",
        language_code="de",
        content_sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        correlation_id="corr-job-0001",
        summary="Backend-Rolle mit Fokus auf Python, APIs und Retrieval.",
        metadata={"company_name": "Example GmbH", "location": "Berlin"},
        blocks=[
           BlockObject(
                block_id="blk_job_0001_001",
                block_no=1,
                block_kind="section",
                heading="Anforderungen",
                content="Sehr gute Python-Kenntnisse, API-Design, Vektorsuche und RAG.",
                token_count=20,
                char_start=0,
                char_end=66,
                mentions=[
                    EntityMentionObject(
                        entity_id="ent_skill_python",
                        mention_text="Python",
                        extractor="ner",
                        confidence=0.99,
                        char_start=10,
                        char_end=16,
                        metadata={"model": "alde-ner-v1"},
                    ),
                ],
            ),
        ],
    )
    relation_object = EntityRelationObject(
        id="rel_job_skill_0001",
        tenant_id="tenant_demo",
        namespace_id="ns_jobs_de",
        source_entity_id="ent_job_0001",
        target_entity_id="ent_skill_python",
        relation_type="requires_skill",
        confidence=0.98,
        correlation_id="corr-job-0001",
        metadata={"source_system": "extraction_pipeline"},
        evidence=[RelationEvidenceObject(block_id="blk_job_0001_001")],
    )
    retrieval_run_object = RetrievalRunObject(
        id="retr_0001",
        tenant_id="tenant_demo",
        namespace_id="ns_jobs_de",
        query_text="Senior Python Retrieval Engineer Berlin",
        requested_k=5,
        lexical_k=20,
        graph_hops=2,
        vector_k=40,
        rerank_strategy="cross_encoder_v1",
        correlation_id="corr-retr-0001",
        filters={"location": "Berlin", "entity_type": ["job_posting", "skill"]},
        results=[
            RetrievalResultObject(
                rank_no=1,
                result_type="document",
                result_id="doc_job_0001",
                source_stage="rerank",
                lexical_score=18.2,
                vector_score=0.93,
                graph_score=0.71,
                rerank_score=0.97,
                metadata={"explanation": "lexical + vector + graph overlap"},
            ),
        ],
    )
    dispatcher_run_object = DispatcherRunObject(
        id="dispatcher:corr-job-0001",
        tenant_id="tenant_demo",
        namespace_id="ns_jobs_de",
        correlation_id="corr-job-0001",
        processing_state="processed",
        processed=True,
        source_system="job_dispatcher",
        dispatcher_db_path="AppData/dispatcher_db.json",
        metadata={"source_agent": "job_dispatcher", "last_seen_at": "2025-01-01T00:00:00Z"},
    )
    return {
        "namespace": namespace_object,
        "entity": entity_object,
        "document": document_object,
        "relation": relation_object,
        "retrieval_run": retrieval_run_object,
        "dispatcher_run": dispatcher_run_object,
    }


def load_demo_usage_lines() -> list[str]:
    return [
        "from alde.agents_db import KnowledgeRepository, build_demo_seed_objects, build_demo_agentsdb_service",
        "repository = KnowledgeRepository.create_from_uri('agents_db://localhost:27017', 'alde_knowledge')",
        "# Start socket endpoint: from alde.agents_db import run_agentsdb_socket_server_from_env; run_agentsdb_socket_server_from_env()",
        "service = build_demo_agentsdb_service(repository._database)",
        "seed = build_demo_seed_objects()",
        "service.store_namespace_object(seed['namespace'])",
        "service.store_entity_object(seed['entity'])",
        "service.store_document_object(seed['document'])",
        "service.store_relation_object(seed['relation'])",
        "service.store_dispatcher_run_object(seed['dispatcher_run'])",
        "service.store_retrieval_run_object(seed['retrieval_run'])",
        "blocks = service.search_block_objects(namespace_id='ns_jobs_de', query_text='Python RAG', limit=5)",
        "graph = service.load_relation_object_graph(namespace_id='ns_jobs_de', source_entity_id='ent_job_0001', max_depth=2)",
        "# Optional pipeline mirror: export AI_IDE_KNOWLEDGE_AGENTS_DB_URI, AI_IDE_KNOWLEDGE_AGENTS_DB_NAME and namespace vars.",
    ]


__all__ = [
    "DocumentBlockObject",
    "DocumentObject",
    "DispatcherRunObject",
    "EmbeddingObject",
    "EntityAliasObject",
    "EntityMentionObject",
    "EntityObject",
    "EntityRelationObject",
    "JobPostingKnowledgeDatasetExampleService",
    "AgentDbSocketRepository",
    "KnowledgeObjectService",
    "KnowledgeRepository",
    "KnowledgeNamespaceObject",
    "MappingBlockSeedObject",
    "MappingSeedEntityObject",
    "ObjectMappingService",
    "ParserObjectKnowledgeMappingService",
    "AgentsDBKnowledgeRepository",
    "AgentsDBKnowledgeRuntimeConfigObject",
    "AgentsDBKnowledgeService",
    "AgentsDBKnowledgePipelineService",
    "MongoKnowledgeRepository",
    "MongoKnowledgeRuntimeConfigObject",
    "MongoKnowledgeService",
    "MongoKnowledgePipelineService",
    "RelationEvidenceObject",
    "RetrievalResultObject",
    "RetrievalRunObject",
    "build_demo_agentsdb_service",
    "build_demo_mongodb_service",
    "build_demo_job_posting_knowledge_dataset",
    "build_demo_seed_objects",
    "load_agentsdb_pipeline_service",
    "load_agentsdb_runtime_config_from_env",
    "load_mongodb_pipeline_service",
    "load_mongodb_runtime_config_from_env",
    "load_demo_usage_lines",
    "run_agentsdb_socket_server",
    "run_agentsdb_socket_server_from_env",
    "sync_parser_result_to_agentsdb_knowledge",
    "sync_parser_result_to_mongodb_knowledge",
    "sync_retrieval_run_to_agentsdb_knowledge",
    "sync_retrieval_run_to_mongodb_knowledge",
]