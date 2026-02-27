try:
    from . import get_path
    from .chat_completion import ChatHistory
except Exception:
    import get_path
    import os
    import sys

    _pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _pkg_parent not in sys.path:
        sys.path.insert(0, _pkg_parent)
    from alde.chat_completion import ChatHistory
ChatHistor= ChatHistory()
ChatHistory._FINAL_PATH = get_path.GetPath()._parent(parg=f"{__file__}") + "/AppData/memory_db.json"

#data:list = ChatHistory._history_
data = ChatHistory._load()
Any = str | int | float | bool | list | dict | tuple | None

# return data from T, with key:type or with key:type where key:type, from (SQL/NoSQL) data structure
def retrieve_data(data: list | dict | Any, key: str | None = None, dtype: type | None = None) -> Any:
    """
    Generalized data retrieval from nested data structures.
    
    Args:
        data: Input data (list, dict, or primitive)
        key: Optional key to filter dict entries
        dtype: Optional type to filter values
    
    Returns:
        Filtered/extracted data matching criteria, or full structure if no filters
    """
    # Handle None
    if data is None:
        return None
    
    # Handle primitive types
    if isinstance(data, (str, int, float, bool)):
        if dtype and not isinstance(data, dtype):
            return None
        return data
    
    # Handle list - recurse into each element
    if isinstance(data, list):
        results = []
        for item in data:
            result = retrieve_data(item, key, dtype)
            if result is not None:
                results.append(result)
        return results if results else None
    
    # Handle dict
    if isinstance(data, dict):
        # If key specified, return matching value(s)
        if key is not None:
            if key in data:
                val = data[key]
                if dtype is None or isinstance(val, dtype):
                    return val
            # Recurse into nested dicts
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    result = retrieve_data(v, key, dtype)
                    if result is not None:
                        return result
            return None
        
        # No key filter - return full structure with type filtering
        if dtype is not None:
            return {k: v for k, v in data.items() if isinstance(v, dtype)}
        return data
    
    # Handle tuple
    if isinstance(data, tuple):
        results = tuple(retrieve_data(item, key, dtype) for item in data)
        return results if any(r is not None for r in results) else None
    
    return str(data)
 