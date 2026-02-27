#!/usr/bin/env python3
"""
Test-Script für Vector Store Performance Monitoring und Validierung.
Demonstriert die neuen Features für Performance-Tracking und Store-Validierung.
"""

from vector_smanager import VectorStoreManager, query_vector_store
from get_path import GetPath
import time

def test_performance_monitoring():
    """Testet das Performance Monitoring."""
    print("\n" + "="*80)
    print("TEST: Performance Monitoring")
    print("="*80 + "\n")
    
    # Store mit aktiviertem Monitoring erstellen
    store_path = GetPath()._parent(parg=__file__) + "AppData/VSM_1_Data"
    manifest_file = GetPath()._parent(parg=__file__) + "AppData/VSM_1_Data/manifest.json"
    
    vsm = VectorStoreManager(
        store_path=store_path,
        manifest_file=manifest_file,
        enable_monitoring=True
    )
    
    # Index aufbauen falls nötig
    print("📦 Building/Loading Vector Store...")
    vsm.build(GetPath().get_path(parg=__file__, opt='p'))
    
    # Mehrere Test-Queries durchführen
    test_queries = [
        "Python function definition",
        "Vector store implementation",
        "FAISS index query",
        "Performance optimization",
        "Error handling"
    ]
    
    print("\n🔍 Executing test queries with performance monitoring...\n")
    for i, query in enumerate(test_queries, 1):
        print(f"\nQuery {i}/{len(test_queries)}: '{query}'")
        vsm.query(query, k=5, monitor=True)
        time.sleep(0.5)  # Kurze Pause zwischen Queries
    
    # Performance-Zusammenfassung ausgeben
    print("\n" + "="*80)
    print("📊 PERFORMANCE SUMMARY")
    print("="*80)
    summary = vsm.get_performance_summary()
    
    if 'message' in summary:
        print(summary['message'])
    else:
        print(f"Total Queries: {summary['total_queries']}")
        print(f"Avg Execution Time: {summary['avg_execution_time_ms']:.2f} ms")
        print(f"Avg Results per Query: {summary['avg_results_per_query']:.2f}")
        print(f"Avg Score: {summary['avg_score']:.4f}")
        
        if summary['last_query']:
            print(f"\nLast Query Details:")
            print(f"  Text: {summary['last_query']['query_text']}")
            print(f"  Execution Time: {summary['last_query']['execution_time_ms']:.2f} ms")
            print(f"  Results: {summary['last_query']['num_results']}")
    
    print("="*80 + "\n")
    
    return vsm

def test_validation():
    """Testet die Store-Validierung."""
    print("\n" + "="*80)
    print("TEST: Vector Store Validation")
    print("="*80 + "\n")
    
    store_path = GetPath()._parent(parg=__file__) + "AppData/VSM_1_Data"
    manifest_file = GetPath()._parent(parg=__file__) + "AppData/VSM_1_Data/manifest.json"
    
    vsm = VectorStoreManager(
        store_path=store_path,
        manifest_file=manifest_file,
        enable_monitoring=False
    )
    
    # Validierung durchführen
    print("🔍 Running validation checks...\n")
    result = vsm.validate()
    
    # Detaillierte Ergebnisse
    print("\n📋 Validation Result Details:")
    print(f"  Is Valid: {result.is_valid}")
    print(f"  Vectors: {result.num_vectors}")
    print(f"  Documents: {result.num_documents}")
    print(f"  Embedding Dimension: {result.embedding_dimension}")
    print(f"  Errors: {len(result.errors)}")
    print(f"  Warnings: {len(result.warnings)}")
    print(f"  Timestamp: {result.timestamp}")
    
    # JSON-Export testen
    print("\n📄 JSON Export:")
    import json
    print(json.dumps(result.to_dict(), indent=2))
    
    return result

def test_combined():
    """Testet Monitoring und Validierung zusammen."""
    print("\n" + "="*80)
    print("TEST: Combined Monitoring & Validation")
    print("="*80 + "\n")
    
    # 1. Validierung vor Queries
    print("1️⃣ Pre-Query Validation:")
    vsm = VectorStoreManager(
        store_path=GetPath()._parent(parg=__file__) + "AppData/VSM_1_Data",
        manifest_file=GetPath()._parent(parg=__file__) + "AppData/VSM_1_Data/manifest.json",
        enable_monitoring=True
    )
    
    pre_validation = vsm.validate()
    
    # 2. Queries mit Monitoring
    print("\n2️⃣ Executing monitored queries:")
    vsm.query("test query performance", k=3, monitor=True)
    vsm.query("vector search validation", k=3, monitor=True)
    
    # 3. Performance-Statistiken
    print("\n3️⃣ Performance Statistics:")
    summary = vsm.get_performance_summary()
    print(json.dumps(summary, indent=2))
    
    # 4. Validierung nach Queries
    print("\n4️⃣ Post-Query Validation:")
    post_validation = vsm.validate()
    
    # Vergleich
    print("\n📊 Comparison:")
    print(f"  Vectors unchanged: {pre_validation.num_vectors == post_validation.num_vectors}")
    print(f"  Still valid: {post_validation.is_valid}")

if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        if test_name == "performance":
            test_performance_monitoring()
        elif test_name == "validation":
            test_validation()
        elif test_name == "combined":
            test_combined()
        else:
            print(f"Unknown test: {test_name}")
            print("Available tests: performance, validation, combined")
    else:
        # Alle Tests durchführen
        print("🚀 Running all tests...\n")
        
        try:
            test_validation()
        except Exception as e:
            print(f"❌ Validation test failed: {e}")
        
        try:
            test_performance_monitoring()
        except Exception as e:
            print(f"❌ Performance test failed: {e}")
        
        try:
            test_combined()
        except Exception as e:
            print(f"❌ Combined test failed: {e}")
        
        print("\n✅ All tests completed!")
