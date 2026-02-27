#!/usr/bin/env python3
"""Test script to verify tools are loaded correctly for agents."""

import sys
from pathlib import Path

# Add alde to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from alde import agents_registry
    from alde.agents_factory import get_agent_tools
    
    print("=" * 60)
    print("Agent Registry Test")
    print("=" * 60)
    
    # Check if _primary_agent exists
    primary_agent = agents_registry.AGENTS_REGISTRY.get("_primary_agent")
    if primary_agent:
        print(f"\n✓ _primary_agent found")
        print(f"  Model: {primary_agent.get('model')}")
        print(f"  Tools (names): {primary_agent.get('tools')}")
        
        # Try to resolve tool definitions
        tool_names = primary_agent.get('tools', [])
        print(f"\n  Resolving {len(tool_names)} tool names...")
        
        try:
            tool_defs = get_agent_tools(tool_names)
            print(f"  ✓ Successfully loaded {len(tool_defs)} tool definitions:")
            for tool_def in tool_defs:
                if isinstance(tool_def, dict) and 'function' in tool_def:
                    func_name = tool_def.get('function', {}).get('name', 'unknown')
                    print(f"    - {func_name}")
        except Exception as e:
            print(f"  ✗ Failed to load tools: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("\n✗ _primary_agent NOT found in registry!")
        print(f"  Available agents: {list(agents_registry.AGENTS_REGISTRY.keys())}")
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
