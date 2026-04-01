// ALDE knowledge hybrid schema for MongoDB
//
// Ziel:
// - dokumentorientierte Wahrheit fuer Entitaeten, Dokumente und Korrelationen
// - Graph-Layer fuer Relationen zwischen Entitaeten
// - Block-Layer fuer Chunking / RAG Retrieval
// - Embedding-Layer fuer Atlas Vector Search oder externes FAISS-Referencing
//
// Ausgelegt fuer mongosh + MongoDB 7/8.
// Fuer produktive Vector Search kann entweder MongoDB Atlas Search genutzt
// werden oder weiterhin FAISS ueber index_backend/index_namespace/index_item_key.

const databaseName = "alde_knowledge";
const dbRef = db.getSiblingDB(databaseName);

function ensureCollection(collectionName, validator) {
    const existing = dbRef.getCollectionInfos({ name: collectionName });
    if (existing.length === 0) {
        dbRef.createCollection(collectionName, { validator });
        return;
    }

    dbRef.runCommand({
        collMod: collectionName,
        validator,
        validationLevel: "moderate",
    });
}

ensureCollection("knowledge_namespaces", {
    $jsonSchema: {
        bsonType: "object",
        required: [
            "_id",
            "tenant_id",
            "slug",
            "name",
            "index_backend",
            "default_embedding_model",
            "default_embedding_dimension",
            "metadata",
            "created_at",
            "updated_at",
        ],
        properties: {
            _id: { bsonType: "string" },
            tenant_id: { bsonType: "string", maxLength: 24 },
            slug: { bsonType: "string", maxLength: 96 },
            name: { bsonType: "string", maxLength: 160 },
            description: { bsonType: "string" },
            index_backend: { enum: ["faiss", "atlas_vector", "redis_vector"] },
            default_embedding_model: { bsonType: "string", maxLength: 160 },
            default_embedding_dimension: { bsonType: "int", minimum: 1 },
            metadata: { bsonType: "object" },
            created_at: { bsonType: "date" },
            updated_at: { bsonType: "date" },
        },
    },
});

ensureCollection("entities", {
    $jsonSchema: {
        bsonType: "object",
        required: [
            "_id",
            "tenant_id",
            "namespace_id",
            "entity_type",
            "canonical_name",
            "status",
            "summary",
            "attributes",
            "aliases",
            "created_at",
            "updated_at",
        ],
        properties: {
            _id: { bsonType: "string" },
            tenant_id: { bsonType: "string", maxLength: 24 },
            namespace_id: { bsonType: "string" },
            entity_type: { bsonType: "string", maxLength: 64 },
            canonical_name: { bsonType: "string", maxLength: 320 },
            external_key: { bsonType: ["string", "null"], maxLength: 160 },
            correlation_id: { bsonType: ["string", "null"], maxLength: 128 },
            status: { enum: ["active", "merged", "archived"] },
            summary: { bsonType: "string" },
            attributes: { bsonType: "object" },
            aliases: {
                bsonType: "array",
                items: {
                    bsonType: "object",
                    required: ["alias", "alias_type", "confidence", "created_at"],
                    properties: {
                        alias: { bsonType: "string", maxLength: 320 },
                        alias_type: { bsonType: "string", maxLength: 48 },
                        locale: { bsonType: ["string", "null"], maxLength: 16 },
                        confidence: { bsonType: ["double", "int", "long", "decimal"] },
                        source_document_id: { bsonType: ["string", "null"] },
                        created_at: { bsonType: "date" },
                    },
                },
            },
            created_at: { bsonType: "date" },
            updated_at: { bsonType: "date" },
        },
    },
});

ensureCollection("documents", {
    $jsonSchema: {
        bsonType: "object",
        required: [
            "_id",
            "tenant_id",
            "namespace_id",
            "document_type",
            "title",
            "source_uri",
            "source_system",
            "mime_type",
            "content_sha256",
            "summary",
            "metadata",
            "blocks",
            "created_at",
            "updated_at",
        ],
        properties: {
            _id: { bsonType: "string" },
            tenant_id: { bsonType: "string", maxLength: 24 },
            namespace_id: { bsonType: "string" },
            document_type: { bsonType: "string", maxLength: 64 },
            title: { bsonType: "string", maxLength: 320 },
            source_uri: { bsonType: "string" },
            source_system: { bsonType: "string", maxLength: 64 },
            mime_type: { bsonType: "string", maxLength: 128 },
            language_code: { bsonType: ["string", "null"], maxLength: 16 },
            content_sha256: { bsonType: "string", minLength: 64, maxLength: 64 },
            correlation_id: { bsonType: ["string", "null"], maxLength: 128 },
            author_entity_id: { bsonType: ["string", "null"] },
            summary: { bsonType: "string" },
            metadata: { bsonType: "object" },
            blocks: {
                bsonType: "array",
                items: {
                    bsonType: "object",
                    required: [
                        "block_id",
                        "block_no",
                        "block_kind",
                        "content",
                        "metadata",
                        "mentions",
                        "created_at",
                    ],
                    properties: {
                        block_id: { bsonType: "string" },
                        block_no: { bsonType: "int", minimum: 0 },
                        block_kind: {
                            enum: ["chunk", "section", "table", "code", "quote", "summary"],
                        },
                        heading: { bsonType: ["string", "null"], maxLength: 320 },
                        content: { bsonType: "string" },
                        token_count: { bsonType: ["int", "null"], minimum: 0 },
                        char_start: { bsonType: ["int", "null"], minimum: 0 },
                        char_end: { bsonType: ["int", "null"], minimum: 1 },
                        parent_block_id: { bsonType: ["string", "null"] },
                        metadata: { bsonType: "object" },
                        mentions: {
                            bsonType: "array",
                            items: {
                                bsonType: "object",
                                required: ["entity_id", "mention_text", "extractor", "confidence", "created_at"],
                                properties: {
                                    entity_id: { bsonType: "string" },
                                    mention_text: { bsonType: "string", maxLength: 320 },
                                    char_start: { bsonType: ["int", "null"], minimum: 0 },
                                    char_end: { bsonType: ["int", "null"], minimum: 1 },
                                    extractor: { bsonType: "string", maxLength: 80 },
                                    confidence: { bsonType: ["double", "int", "long", "decimal"] },
                                    metadata: { bsonType: ["object", "null"] },
                                    created_at: { bsonType: "date" },
                                },
                            },
                        },
                        created_at: { bsonType: "date" },
                    },
                },
            },
            created_at: { bsonType: "date" },
            updated_at: { bsonType: "date" },
        },
    },
});

ensureCollection("entity_relations", {
    $jsonSchema: {
        bsonType: "object",
        required: [
            "_id",
            "tenant_id",
            "namespace_id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            "direction",
            "weight",
            "confidence",
            "metadata",
            "evidence",
            "created_at",
            "updated_at",
        ],
        properties: {
            _id: { bsonType: "string" },
            tenant_id: { bsonType: "string", maxLength: 24 },
            namespace_id: { bsonType: "string" },
            source_entity_id: { bsonType: "string" },
            target_entity_id: { bsonType: "string" },
            relation_type: { bsonType: "string", maxLength: 80 },
            direction: { enum: ["directed", "undirected"] },
            weight: { bsonType: ["double", "int", "long", "decimal"] },
            confidence: { bsonType: ["double", "int", "long", "decimal"] },
            valid_from: { bsonType: ["date", "null"] },
            valid_to: { bsonType: ["date", "null"] },
            correlation_id: { bsonType: ["string", "null"], maxLength: 128 },
            metadata: { bsonType: "object" },
            evidence: {
                bsonType: "array",
                items: {
                    bsonType: "object",
                    required: ["block_id", "evidence_role", "created_at"],
                    properties: {
                        block_id: { bsonType: "string" },
                        evidence_role: {
                            enum: ["supporting", "contradicting", "mention", "source"],
                        },
                        created_at: { bsonType: "date" },
                    },
                },
            },
            created_at: { bsonType: "date" },
            updated_at: { bsonType: "date" },
        },
    },
});

ensureCollection("embedding_models", {
    $jsonSchema: {
        bsonType: "object",
        required: [
            "_id",
            "namespace_id",
            "model_name",
            "provider",
            "task_type",
            "dimension",
            "distance_metric",
            "is_active",
            "config",
            "created_at",
        ],
        properties: {
            _id: { bsonType: "string" },
            namespace_id: { bsonType: "string" },
            model_name: { bsonType: "string", maxLength: 160 },
            provider: { bsonType: "string", maxLength: 64 },
            task_type: { bsonType: "string", maxLength: 32 },
            dimension: { bsonType: "int", minimum: 1 },
            distance_metric: { enum: ["cosine", "l2", "ip"] },
            is_active: { bsonType: "bool" },
            config: { bsonType: "object" },
            created_at: { bsonType: "date" },
        },
    },
});

ensureCollection("embeddings", {
    $jsonSchema: {
        bsonType: "object",
        required: [
            "tenant_id",
            "namespace_id",
            "model_id",
            "owner_type",
            "owner_id",
            "content_sha256",
            "dimension",
            "index_backend",
            "index_namespace",
            "index_item_key",
            "metadata",
            "created_at",
            "updated_at",
        ],
        properties: {
            tenant_id: { bsonType: "string", maxLength: 24 },
            namespace_id: { bsonType: "string" },
            model_id: { bsonType: "string" },
            owner_type: { enum: ["document", "block", "entity", "relation", "query_template"] },
            owner_id: { bsonType: "string" },
            content_sha256: { bsonType: "string", minLength: 64, maxLength: 64 },
            chunk_hash: { bsonType: ["string", "null"], minLength: 64, maxLength: 64 },
            embedding: {
                bsonType: ["array", "null"],
                items: { bsonType: ["double", "int", "long", "decimal"] },
            },
            dimension: { bsonType: "int", minimum: 1 },
            index_backend: { bsonType: "string", maxLength: 32 },
            index_namespace: { bsonType: "string", maxLength: 160 },
            index_item_key: { bsonType: "string", maxLength: 160 },
            metadata: { bsonType: "object" },
            created_at: { bsonType: "date" },
            updated_at: { bsonType: "date" },
        },
    },
});

ensureCollection("retrieval_runs", {
    $jsonSchema: {
        bsonType: "object",
        required: [
            "_id",
            "tenant_id",
            "namespace_id",
            "query_text",
            "requested_k",
            "rerank_strategy",
            "filters",
            "results",
            "created_at",
        ],
        properties: {
            _id: { bsonType: "string" },
            tenant_id: { bsonType: "string", maxLength: 24 },
            namespace_id: { bsonType: "string" },
            query_text: { bsonType: "string" },
            requested_k: { bsonType: "int", minimum: 1 },
            lexical_k: { bsonType: ["int", "null"], minimum: 1 },
            graph_hops: { bsonType: ["int", "null"], minimum: 0 },
            vector_k: { bsonType: ["int", "null"], minimum: 1 },
            rerank_strategy: { bsonType: "string", maxLength: 48 },
            correlation_id: { bsonType: ["string", "null"], maxLength: 128 },
            filters: { bsonType: "object" },
            results: {
                bsonType: "array",
                items: {
                    bsonType: "object",
                    required: ["rank_no", "result_type", "result_id", "source_stage", "chosen"],
                    properties: {
                        rank_no: { bsonType: "int", minimum: 1 },
                        result_type: { enum: ["document", "block", "entity", "relation"] },
                        result_id: { bsonType: "string" },
                        source_stage: { enum: ["sql", "fts", "graph", "vector", "rerank", "manual"] },
                        lexical_score: { bsonType: ["double", "int", "long", "decimal", "null"] },
                        vector_score: { bsonType: ["double", "int", "long", "decimal", "null"] },
                        graph_score: { bsonType: ["double", "int", "long", "decimal", "null"] },
                        rerank_score: { bsonType: ["double", "int", "long", "decimal", "null"] },
                        chosen: { bsonType: "bool" },
                        metadata: { bsonType: ["object", "null"] },
                    },
                },
            },
            created_at: { bsonType: "date" },
        },
    },
});

dbRef.knowledge_namespaces.createIndex(
    { tenant_id: 1, slug: 1 },
    { unique: true, name: "uq_knowledge_namespaces_tenant_slug" }
);
dbRef.knowledge_namespaces.createIndex({ tenant_id: 1 }, { name: "ix_knowledge_namespaces_tenant_id" });
dbRef.knowledge_namespaces.createIndex({ metadata: 1 }, { name: "ix_knowledge_namespaces_metadata" });

dbRef.entities.createIndex(
    { namespace_id: 1, entity_type: 1, canonical_name: 1 },
    { unique: true, name: "uq_entities_namespace_type_name" }
);
dbRef.entities.createIndex(
    { namespace_id: 1, external_key: 1 },
    {
        unique: true,
        partialFilterExpression: { external_key: { $type: "string" } },
        name: "uq_entities_namespace_external_key",
    }
);
dbRef.entities.createIndex({ tenant_id: 1 }, { name: "ix_entities_tenant_id" });
dbRef.entities.createIndex({ namespace_id: 1, correlation_id: 1 }, { name: "ix_entities_namespace_correlation_id" });
dbRef.entities.createIndex({ "aliases.alias": 1 }, { name: "ix_entities_aliases_alias" });
dbRef.entities.createIndex(
    {
        canonical_name: "text",
        summary: "text",
        "aliases.alias": "text",
        "attributes.skills": "text",
    },
    {
        default_language: "none",
        weights: { canonical_name: 10, "aliases.alias": 8, summary: 4 },
        name: "fts_entities",
    }
);

dbRef.documents.createIndex(
    { namespace_id: 1, content_sha256: 1 },
    { unique: true, name: "uq_documents_namespace_sha" }
);
dbRef.documents.createIndex(
    { namespace_id: 1, source_uri: 1 },
    { unique: true, name: "uq_documents_namespace_source_uri" }
);
dbRef.documents.createIndex({ tenant_id: 1 }, { name: "ix_documents_tenant_id" });
dbRef.documents.createIndex({ namespace_id: 1, correlation_id: 1 }, { name: "ix_documents_namespace_correlation_id" });
dbRef.documents.createIndex({ author_entity_id: 1 }, { name: "ix_documents_author_entity_id" });
dbRef.documents.createIndex(
    {
        title: "text",
        summary: "text",
        source_uri: "text",
        "blocks.heading": "text",
        "blocks.content": "text",
        "blocks.mentions.mention_text": "text",
    },
    {
        default_language: "none",
        weights: { title: 8, summary: 5, "blocks.heading": 4, "blocks.content": 2 },
        name: "fts_documents_blocks",
    }
);
dbRef.documents.createIndex(
    { namespace_id: 1, "blocks.block_id": 1 },
    { name: "ix_documents_blocks_block_id" }
);

dbRef.entity_relations.createIndex({ tenant_id: 1 }, { name: "ix_entity_relations_tenant_id" });
dbRef.entity_relations.createIndex(
    { namespace_id: 1, source_entity_id: 1, target_entity_id: 1 },
    { name: "ix_entity_relations_source_target" }
);
dbRef.entity_relations.createIndex(
    { namespace_id: 1, relation_type: 1 },
    { name: "ix_entity_relations_relation_type" }
);
dbRef.entity_relations.createIndex(
    { namespace_id: 1, correlation_id: 1 },
    { name: "ix_entity_relations_correlation_id" }
);

dbRef.embedding_models.createIndex(
    { namespace_id: 1, model_name: 1, task_type: 1 },
    { unique: true, name: "uq_embedding_models_namespace_model_task" }
);
dbRef.embedding_models.createIndex({ namespace_id: 1, is_active: 1 }, { name: "ix_embedding_models_active" });

dbRef.embeddings.createIndex(
    { namespace_id: 1, owner_type: 1, owner_id: 1, model_id: 1, content_sha256: 1 },
    { unique: true, name: "uq_embeddings_owner_model_sha" }
);
dbRef.embeddings.createIndex(
    { index_backend: 1, index_namespace: 1, index_item_key: 1 },
    { unique: true, name: "uq_embeddings_index_item" }
);
dbRef.embeddings.createIndex({ tenant_id: 1 }, { name: "ix_embeddings_tenant_id" });
dbRef.embeddings.createIndex({ namespace_id: 1, model_id: 1 }, { name: "ix_embeddings_namespace_model" });
dbRef.embeddings.createIndex({ owner_type: 1, owner_id: 1 }, { name: "ix_embeddings_owner" });

dbRef.retrieval_runs.createIndex({ tenant_id: 1 }, { name: "ix_retrieval_runs_tenant_id" });
dbRef.retrieval_runs.createIndex({ namespace_id: 1, correlation_id: 1 }, { name: "ix_retrieval_runs_namespace_correlation_id" });
dbRef.retrieval_runs.createIndex(
    { namespace_id: 1, query_text: "text", "results.metadata.reason": "text" },
    { default_language: "none", name: "fts_retrieval_runs" }
);

// Atlas Vector Search example. Needs MongoDB Atlas Search support.
// Adjust numDimensions to the namespace/model configuration.
//
// dbRef.runCommand({
//     createSearchIndexes: "embeddings",
//     indexes: [
//         {
//             name: "embedding_cosine",
//             definition: {
//                 fields: [
//                     {
//                         type: "vector",
//                         path: "embedding",
//                         numDimensions: 1536,
//                         similarity: "cosine",
//                     },
//                     {
//                         type: "filter",
//                         path: "namespace_id",
//                     },
//                     {
//                         type: "filter",
//                         path: "owner_type",
//                     },
//                 ],
//             },
//         },
//     ],
// });

// Example document layout.
dbRef.knowledge_namespaces.updateOne(
    { _id: "ns_jobs_de" },
    {
        $setOnInsert: {
            _id: "ns_jobs_de",
            tenant_id: "tenant_demo",
            slug: "jobs-de",
            name: "Jobs Deutschland",
            description: "Wissensraum fuer Stellen, Profile und Skills.",
            index_backend: "faiss",
            default_embedding_model: "text-embedding-3-large",
            default_embedding_dimension: 3072,
            metadata: { locale: "de-DE" },
            created_at: new Date(),
            updated_at: new Date(),
        },
    },
    { upsert: true }
);

dbRef.entities.updateOne(
    { _id: "ent_skill_python" },
    {
        $set: {
            tenant_id: "tenant_demo",
            namespace_id: "ns_jobs_de",
            entity_type: "skill",
            canonical_name: "Python",
            external_key: "skill:python",
            correlation_id: "corr-skill-python",
            status: "active",
            summary: "Programmiersprache fuer Backend, Datenverarbeitung und KI.",
            attributes: { category: "language", level_scale: ["junior", "mid", "senior"] },
            aliases: [
                {
                    alias: "Python 3",
                    alias_type: "synonym",
                    locale: "de",
                    confidence: 1.0,
                    source_document_id: null,
                    created_at: new Date(),
                },
            ],
            updated_at: new Date(),
        },
        $setOnInsert: { created_at: new Date() },
    },
    { upsert: true }
);

dbRef.documents.updateOne(
    { _id: "doc_job_0001" },
    {
        $set: {
            tenant_id: "tenant_demo",
            namespace_id: "ns_jobs_de",
            document_type: "job_posting",
            title: "Senior Python Engineer",
            source_uri: "https://example.org/jobs/0001",
            source_system: "crawler",
            mime_type: "text/html",
            language_code: "de",
            content_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            correlation_id: "corr-job-0001",
            author_entity_id: null,
            summary: "Backend-Rolle mit Fokus auf Python, APIs und Retrieval.",
            metadata: { company_name: "Example GmbH", location: "Berlin" },
            blocks: [
                {
                    block_id: "blk_job_0001_001",
                    block_no: 1,
                    block_kind: "section",
                    heading: "Anforderungen",
                    content: "Sehr gute Python-Kenntnisse, API-Design, Vektorsuche und RAG.",
                    token_count: 20,
                    char_start: 0,
                    char_end: 78,
                    parent_block_id: null,
                    metadata: { source_heading_level: 2 },
                    mentions: [
                        {
                            entity_id: "ent_skill_python",
                            mention_text: "Python",
                            char_start: 10,
                            char_end: 16,
                            extractor: "ner",
                            confidence: 0.99,
                            metadata: { model: "alde-ner-v1" },
                            created_at: new Date(),
                        },
                    ],
                    created_at: new Date(),
                },
            ],
            updated_at: new Date(),
        },
        $setOnInsert: { created_at: new Date() },
    },
    { upsert: true }
);

dbRef.entity_relations.updateOne(
    { _id: "rel_job_skill_0001" },
    {
        $set: {
            tenant_id: "tenant_demo",
            namespace_id: "ns_jobs_de",
            source_entity_id: "ent_job_0001",
            target_entity_id: "ent_skill_python",
            relation_type: "requires_skill",
            direction: "directed",
            weight: 1.0,
            confidence: 0.98,
            valid_from: null,
            valid_to: null,
            correlation_id: "corr-job-0001",
            metadata: { source_system: "extraction_pipeline" },
            evidence: [
                {
                    block_id: "blk_job_0001_001",
                    evidence_role: "supporting",
                    created_at: new Date(),
                },
            ],
            updated_at: new Date(),
        },
        $setOnInsert: { created_at: new Date() },
    },
    { upsert: true }
);

// Example 1: lexical retrieval over document truth + chunk layer.
const lexicalResults = dbRef.documents.aggregate([
    {
        $match: {
            namespace_id: "ns_jobs_de",
            $text: { $search: "Python Retrieval RAG" },
        },
    },
    {
        $project: {
            title: 1,
            source_uri: 1,
            score: { $meta: "textScore" },
            top_blocks: {
                $slice: [
                    {
                        $filter: {
                            input: "$blocks",
                            as: "block",
                            cond: {
                                $or: [
                                    { $regexMatch: { input: { $ifNull: ["$$block.heading", ""] }, regex: /Python|RAG|Retrieval/i } },
                                    { $regexMatch: { input: "$$block.content", regex: /Python|RAG|Retrieval/i } },
                                ],
                            },
                        },
                    },
                    5,
                ],
            },
        },
    },
    { $sort: { score: -1 } },
    { $limit: 5 },
]).toArray();

// Example 2: graph expansion from one entity across relations.
const graphResults = dbRef.entity_relations.aggregate([
    {
        $match: {
            namespace_id: "ns_jobs_de",
            source_entity_id: "ent_job_0001",
        },
    },
    {
        $graphLookup: {
            from: "entity_relations",
            startWith: "$target_entity_id",
            connectFromField: "target_entity_id",
            connectToField: "source_entity_id",
            as: "reachable_relations",
            maxDepth: 2,
            restrictSearchWithMatch: { namespace_id: "ns_jobs_de" },
            depthField: "hop_count",
        },
    },
]).toArray();

// Example 3: vector candidate lookup when embeddings are stored in MongoDB.
// Replace queryVector with a real embedding generated by the application.
//
// const queryVector = [0.0123, -0.0044, 0.9812];
// const vectorResults = dbRef.embeddings.aggregate([
//     {
//         $vectorSearch: {
//             index: "embedding_cosine",
//             path: "embedding",
//             queryVector,
//             numCandidates: 100,
//             limit: 10,
//             filter: {
//                 namespace_id: "ns_jobs_de",
//                 owner_type: "block",
//             },
//         },
//     },
//     {
//         $project: {
//             owner_id: 1,
//             model_id: 1,
//             score: { $meta: "vectorSearchScore" },
//             index_backend: 1,
//             index_namespace: 1,
//             index_item_key: 1,
//         },
//     },
// ]).toArray();

// Example 4: persist a retrieval run with fused results.
dbRef.retrieval_runs.updateOne(
    { _id: "retr_0001" },
    {
        $set: {
            tenant_id: "tenant_demo",
            namespace_id: "ns_jobs_de",
            query_text: "Senior Python Retrieval Engineer Berlin",
            requested_k: 5,
            lexical_k: 20,
            graph_hops: 2,
            vector_k: 40,
            rerank_strategy: "cross_encoder_v1",
            correlation_id: "corr-retr-0001",
            filters: { location: "Berlin", entity_type: ["job_posting", "skill"] },
            results: [
                {
                    rank_no: 1,
                    result_type: "document",
                    result_id: "doc_job_0001",
                    source_stage: "rerank",
                    lexical_score: 18.2,
                    vector_score: 0.93,
                    graph_score: 0.71,
                    rerank_score: 0.97,
                    chosen: true,
                    metadata: { explanation: "lexical + vector + graph overlap" },
                },
            ],
            created_at: new Date(),
        },
    },
    { upsert: true }
);

print(`MongoDB hybrid knowledge example prepared in database ${databaseName}`);
printjson({ lexicalResults, graphResults });

// Redis note:
// Redis/Redis Stack kann den Vector-Layer und sekundenschnelle Key-Lookups gut
// abdecken, ist aber fuer dieses Datenmodell als alleinige Wahrheitsquelle unguenstiger.
// Fuer dieselben Anforderungen waere Redis hier eher ein Beschleuniger fuer
// caching, vector search und adjacency sets, waehrend MongoDB die dokument-orientierte
// Wahrheit fuer Namespace, Entitaeten, Dokumente, Bloecke und Retrieval-Runs haelt.