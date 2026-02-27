from __future__ import annotations
from pathlib import Path
                                            



class Counter():
    """
A tiny, persistent counter.

  * an instance-wide count   -> self.instance_count
  * a process-wide, persistent count stored in _ctr_ -> Counter._global_count

• Every process keeps its own *instance_count*.
• All processes share one global count that is written to `_ctr_` as default name.
  If you want to use the class Counter in several cases, set the '_cvar' parameter. 
  The class stores now for each new call to the class its self a further process-wide, 
  persistent counter namend as the parameter is namend.  
  

The implementation is intentionally very small – if you need
concurrency-safe increments use `fcntl`/`msvcrt` or SQLite.
    """
    _cvar:str | None = None or "_ctr_"
    _file_name     = Path(__file__).with_name(f"{_cvar}")
    _global_count: int | None = None          # loaded lazily
    

    # ───────────────── file helpers ──────────────────

    @classmethod
    def _load_global(cls) -> int:
        """Read the global value from disk once per process."""
        if cls._global_count is None:             # not loaded yet
            try:
                cls._global_count = int(cls._file_name.read_text().strip() or 0)
            except FileNotFoundError:
                cls._global_count = 0 #Counter()()[]

        return cls._global_count

    @classmethod
    def _store_global(cls) -> None:
        cls._file_name.write_text(str(cls._global_count))
   
 
           
   # ───────────────── public API ────────────────────
        
    def __init__(self, _cvar:None = None) -> None: # None Type
        super().__init__()
        _cvar
        self._instance_count: int = 0

        
        Counter._load_global()    

      

        
    def increment(self) -> int:
        """Increase both counters and return the *new global* value."""

        
        self._instance_count += 1
        Counter._global_count += 1   
        

        Counter._store_global()
        return self._instance_count


    # convenience
    __call__ = increment



# –– counter.py ––––––––––––––––––––––––––––––––––––––––––––––––
"""
count = Counter()
print(count._global_count)

for c in range(10):
 print(count.__call__())
print(Counter._global_count)"""

