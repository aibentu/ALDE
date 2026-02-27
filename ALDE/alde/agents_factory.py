from __future__ import annotations

# Maintainer contact: see repository README.

from pathlib import Path
from importlib.metadata import metadata
import sys
import json
import os
import atexit
import hashlib
from typing import Any
from datetime import datetime
from pyexpat import model

try:
    from .chat_completion import ChatComE, ChatCompletion
except ImportError as e:
    msg = str(e)
    if "no known parent package" in msg or "attempted relative import" in msg:
        import os
        import sys

        _pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _pkg_parent not in sys.path:
            sys.path.insert(0, _pkg_parent)
        from alde.chat_completion import ChatComE, ChatCompletion
    else:
        raise
try:
    from .tools import UNIFIED_TOOLS, TOOL_GROUPS, vectordb, memorydb  # type: ignore
except ImportError as e:
    msg = str(e)
    if "no known parent package" in msg or "attempted relative import" in msg:
        from tools import UNIFIED_TOOLS, TOOL_GROUPS, vectordb, memorydb  # type: ignore
    else:
        raise
if __name__ == '__main__':  
    _script_dir = Path(__file__).parent
    _parent_dir = _script_dir.parent
    if str(_parent_dir) not in sys.path:
        
        sys.path.insert(0, str(_parent_dir))
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
try:
    from .get_path import GetPath  # type: ignore
except ImportError as e:
    msg = str(e)
    if "no known parent package" in msg or "attempted relative import" in msg:
        from get_path import GetPath  # type: ignore
    else:
        raise

#try:
    # ChatComE is the agent-capable chat client that accepts (_messages, tools)
    # and returns a full OpenAI response object via ._response().
  #  from .chat_completion import ChatComE as ChatCom, ChatHistory
#except ImportError:  # allow running directly from the repository root


_MAX_TOOL_DEPTH = 50
_TOOL_CACHE: dict[str, str] = {}
_MODEL = "gpt-4.1-mini-2025-04-14"
model = _MODEL
# Minimal, robust triage/dispatcher script.
# NOTE: This must be a real dict at runtime; tool-call dispatch reads from it.
try:
    from . import agents_registry as _agents_registry  # type: ignore
except Exception:
    import agents_registry as _agents_registry  # type: ignore
AGENTS_REGISTRY: dict[str, dict] = getattr(_agents_registry, "AGENTS_REGISTRY", {}) or {}

# Defer importing ChatHistory to runtime to avoid circular imports
_initial_history_length = 0

# Lazy accessor for the ChatHistory singleton to prevent circular imports.
_history_instance: Any | None = None
def get_history() -> Any:
    global _history_instance
    if _history_instance is None:
        try:
            from .chat_completion import ChatHistory as _CH
        except Exception:
            import os
            import sys

            _pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _pkg_parent not in sys.path:
                sys.path.insert(0, _pkg_parent)
            from alde.chat_completion import ChatHistory as _CH
        _history_instance = _CH()
    return _history_instance

def _latest_user_message(default: str = "") -> str:
    try:
        history = get_history()
        for entry in reversed(history._history_):
            if isinstance(entry, dict) and entry.get("role") == "user":
                content = entry.get("content") or ""
                if isinstance(content, str) and content.strip():
                    return content
    except Exception as exc:
        print(f"[DEBUG] could not read last user message: {exc}")
    return default

# Flush on exit only when new entries were added
#def _cleanup_on_exit():
 #   if len(ChatHistory._history_) > _initial_history_length:
  #      history._flush()

#atexit.register(_cleanup_on_exit)
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ParamSpec:
    """Parameter specification for tool functions."""
    name: str
    type: str = "string"  # string, number, boolean, array, object
    description: str = ""
    required: bool = False
    enum: list | None = None
    items: dict | None = None
    default: any = None

    def to_python_type(self) -> str:
        """Convert JSON schema type to Python type hint."""
        type_map = {
            "string": "str",
            "number": "float",
            "integer": "int",
            "boolean": "bool",
            "array": "list",
            "object": "dict"
        }
        py_type = type_map.get(self.type, "Any")
        if not self.required:
            py_type = f"{py_type} | None"
        return py_type
    
    def to_tool_property(self) -> dict:
        """Convert to OpenAI tool parameter property."""
        prop = {"type": self.type, "description": self.description}
        if self.enum:
            prop["enum"] = self.enum #:list
        if self.items:
            prop["items"] = self.items #:dict
        return prop

@dataclass  
class ToolSpec:
    """Complete tool specification - single source of truth."""
    name: str
    description: str
    parameters: list[ParamSpec] = field(default_factory=list)
    implementation: Callable | None = None  # Optional: actual function reference
    
    # Callbacks bound to this tool 
    on_call: Callable[[str, dict], None] | None = None  # Called before execution
    on_result: Callable[[str, str], None] | None = None  # Called after execution
    
    def to_tool_definition(self) -> dict:
        """Generate OpenAI-compatible tool definition."""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_tool_property()
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }
    
    def execute(self, args: dict, tool_call_id: str = None) -> str:
        """Execute this tool with logging callbacks."""
        # Call on_call callback if registered
        if self.on_call:
            try:
                self.on_call(self.name, args)
            except Exception as e:
                print(f"on_call error: {e}")
        
        # Execute the tool
        result = ""
        try:
            if self.implementation:
                # Build kwargs from args
                kwargs = {}
                for p in self.parameters:
                    if p.name in args:
                        kwargs[p.name] = args[p.name]
                    elif p.default is not None:
                        kwargs[p.name] = p.default
                    elif not p.required:
                        kwargs[p.name] = None
                result = self.implementation(**kwargs)
            else:
                result = f"Tool '{self.name}' has no implementation"
        except Exception as e:
            result = f"Tool execution error: {e}"
        
        # Call on_result callback if registered
        if self.on_result:
            try:
                self.on_result(self.name, result, tool_call_id)
            except Exception as e:
                print(f"on_result error: {e}")
        
        return result
    
    def to_function_signature(self) -> str:
        """Generate Python function signature string."""
        params = []
        for p in self.parameters:
            if p.required:
                params.append(f"{p.name}: {p.to_python_type()}")
            else:
                default = f'"{p.default}"' if isinstance(p.default, str) else p.default
                params.append(f"{p.name}: {p.to_python_type()} = {default}")
        return f"def {self.name}({', '.join(params)}) -> str:"
    
    def to_function_stub(self) -> str:
        """Generate complete Python function stub."""
        sig = self.to_function_signature()
        # Prevent accidental triple-quote termination in generated source.
        safe_desc = (self.description or "").replace('"""', r'\"\"\"')
        docstring = f'    """{safe_desc}"""'
        body = f'    return f"{self.name} executed with params: {{{", ".join(p.name for p in self.parameters)}}}"'
        return f"{sig}\n{docstring}\n{body}"
    
    def compile_stub(
        self,
        *,
        attach_as_implementation: bool = True,
        globals_dict: dict | None = None,
    ) -> Callable:
        """Compile `to_function_stub()` into a real Python function.

        Uses `exec()` on the generated source code and returns the created
        callable. By default it also assigns it to `self.implementation`.

        Security note: only do this for trusted ToolSpec inputs.
        """

        import keyword
        import re

        def _is_identifier(name: str) -> bool:
            return bool(re.fullmatch(r"[A-Za-z_]\w*", name)) and not keyword.iskeyword(name)

        if not _is_identifier(self.name):
            raise ValueError(f"Tool name is not a valid Python identifier: {self.name!r}")
        for p in self.parameters:
            if not _is_identifier(p.name):
                raise ValueError(f"Param name is not a valid Python identifier: {p.name!r}")

        src = self.to_function_stub()

        ns: dict = {}
        if globals_dict is None:
            # Minimal, but still functional default. (We keep builtins so the
            # function can execute normally.)
            ns["__builtins__"] = __builtins__
        else:
            ns.update(globals_dict)
            ns.setdefault("__builtins__", __builtins__)

        exec(src, ns, ns)
        fn = ns.get(self.name)
        if not callable(fn):
            raise RuntimeError(f"Stub did not define a callable named {self.name!r}")

        if attach_as_implementation:
            self.implementation = fn
        return fn

# ============================================================================
# Unified Tool & Function Definition Factory
# ============================================================================
# Define tools once - generate both Python functions (stubs) and OpenAI tool specs
# from a single source of truth.

def create_tool_registry(specs: list[ToolSpec]) -> dict[str, dict]:
    """Create tool registry from ToolSpec list."""
    return {spec.name: spec.to_tool_definition() for spec in specs}

def create_function_dispatcher(specs: list[ToolSpec]) -> dict[str, Callable]:
    """Create function dispatcher mapping names to implementations."""
    return {spec.name: spec.implementation for spec in specs if spec.implementation}

def generate_function_stubs(specs: list[ToolSpec]) -> str:
    """Generate Python code for all function stubs."""
    return "\n\n".join(spec.to_function_stub() for spec in specs)

# ============================================================================
# Helper: Quick creation from simple lists
# ============================================================================
def param(name: str, type: str = "string", desc: str = "", 
          required: bool = False, enum: list = None, default: any = None) -> ParamSpec:
    """Shorthand for creating ParamSpec."""
    return ParamSpec(name=name, type=type, description=desc, 
                     required=required, enum=enum, default=default)

def tool(name: str, desc: str, params: list[ParamSpec] = None, 
         impl: Callable = None) -> ToolSpec:
    """Shorthand for creating ToolSpec."""
    return ToolSpec(name=name, description=desc, 
                    parameters=params or [], implementation=impl)
# ============================================================================

# System prompt

sys1mi = [
    {"role": "system",
        "content": (
            "You are an triage agent. "
            "1. Ask clarifying questions if information is missing. "
            "2. If you can answer the question independently, do so. "
            "3. If a specialized agent is clearly better suited, "
            "   chose a suited tool or call the function route_to_agent with the appropriate 'target_agent'."

        )
    }
]

sys2mi = [
    {"role": "system",
        "content": (
            "You are an data manipulation agent. "
            "You are equipet with the tools: "
            "read_document, write_document, update_document, delete_document, list_documents."
            "You can perform data manipulation tasks based on user requests."
                
        )
    }
]

sys3mi = [
    {"role": "system",
        "content": (
            "You are an extract_json_schema_agent. "
            "You are equipet with the tools: iter_documents, extract_to_schema, code_tool, read_document."
            "Your task is to execute the tools iter_documents and extract_to_schema."
            "the tool flow runs locally."
            "after the job is done the tool send you an job report message."       
        )
    }
]

# Agent Registry

{
  
    "triage_agent": {
        "system": sys1mi,
        "tools": ["route_to_agent"]
    }
}                             

# Tools that require special handling in dispatcher
_SPECIAL_HANDLED_TOOLS = ['vectordb_tool', 'route_to_agent']

# ============================================================================
# Define ALL tools using the unified factory
# ============================================================================
# Define tool specifications with the shorthand helpers
# Each tool is defined ONCE with: name, description, parameters, implementation
# ============================================================================
# Generate all from unified specs - SINGLE SOURCE OF TRUTH
# ============================================================================
tool_registry = create_tool_registry(UNIFIED_TOOLS)
function_dispatcher = create_function_dispatcher(UNIFIED_TOOLS)
# Tool lookup by name
_tool_specs_by_name: dict[str, ToolSpec] = {spec.name: spec for spec in UNIFIED_TOOLS}

def get_tool_spec(name: str) -> ToolSpec | None:
    """Get ToolSpec by name."""
    return _tool_specs_by_name.get(name)

def get_agent_tools(tool_names: list[str]) -> list[dict]:
    """Get tool definitions for a list of tool names.

    This project sometimes stores agent tools as:
    - list[str] of tool names (preferred), or
    - list[dict] of already-built OpenAI tool definitions.

    Accept both forms to avoid TypeError: unhashable type: 'dict'.
    """
    resolved: list[dict] = []
    if not tool_names:
        return resolved

    for item in tool_names:
        # Already a tool definition dict
        if isinstance(item, dict):
            if item.get("type") == "function" and isinstance(item.get("function"), dict):
                resolved.append(item)
            continue

        # Tool name
        if isinstance(item, str):
            # Group reference, e.g. "@docs_rw".
            if item.startswith("@"):
                group = item[1:].strip()
                for tool_name in (TOOL_GROUPS.get(group) or []):
                    if isinstance(tool_name, str) and tool_name in tool_registry:
                        resolved.append(tool_registry[tool_name])
                continue

            if item in tool_registry:
                resolved.append(tool_registry[item])

    return resolved

# ============================================================================ 
# Default Logging Callbacks - bound to each tool
# ============================================================================
def _default_on_call(tool_name: str, args: dict) -> None:
    """Default callback: log tool call."""
    print(f"TOOL CALL: {tool_name} with args: {list(args.keys())}")

def _default_on_result(tool_name: str, result: str, tool_call_id: str = None) -> None:
    """Default callback: log tool result to history."""
    try:
        preview = result if isinstance(result, str) else str(result)
    except Exception:
        preview = "[unprintable result]"
    print(f"TOOL RESULT: {tool_name} -> {preview[:100]}...")
    # Do not log tool role directly into history here to avoid invalid
    # message sequences for OpenAI (tool messages must follow assistant
    # messages with matching tool_calls). Pairing is handled in _handle_tool_calls.
# Bind callbacks to all tools
for spec in UNIFIED_TOOLS:
    spec.on_call = _default_on_call
    spec.on_result = _default_on_result

# ============================================================================
# Special Tool Handlers (vectordb, route_to_agent)
# ============================================================================
def execute_vectordb(args: dict, tool_call_id: str = None) -> tuple[str, dict | None]:
    """Execute vectordb_tool with caching."""
    query = (args.get('Query') or args.get('query') or '').strip()
    tool_name = args.get('vector_tools', 'VectorDB')
    cache_key = f"{tool_name}:{query.lower()}"
    
    if cache_key in _TOOL_CACHE:
        result = _TOOL_CACHE[cache_key]
    else:
        if tool_name == 'VectorDB':
            result = vectordb(query, k=3)
        else:
            result = memorydb(query, k=3)
        _TOOL_CACHE[cache_key] = result
    
    # Log result
    _default_on_result(tool_name, result, tool_call_id)
    return result, None
   

def execute_route_to_agent(args: dict, tool_call_id: str = None) -> tuple[str, dict | None]:
    """Execute route_to_agent and return routing request."""
    target = args.get('target_agent', '')
    user_question = (
        args.get('user_question', '')
        or args.get('message_text', '')
        or _latest_user_message('')
    )
    if not user_question:
        result = (f"Unknown target agent: {target}" if target not in AGENTS_REGISTRY
                  else "No user question available for routing")
        _default_on_result('route_to_agent', result, tool_call_id)
        return result, None
    if target not in AGENTS_REGISTRY:
        result = f"Unknown target agent: {target}"
        _default_on_result('route_to_agent', result, tool_call_id)
        return result, None
    
    agent_config = AGENTS_REGISTRY[target]
    # Build a valid OpenAI `messages` payload.
    messages: list[dict] = [
        {"role": "system", "content": agent_config.get("system", "")},
        {"role": "user", "content": str(user_question)},
    ]
    routing_request = {
        'messages': messages,
        'agent_label': target,
        'tools': get_agent_tools(agent_config.get("tools") or []),
        'model': agent_config.get("model") or model,
    }
    
    result = f"Routing to {target}"
    _default_on_result('route_to_agent', result, tool_call_id)
    return result, routing_request

# ============================================================================
# Unified Tool Execution
# ============================================================================
def execute_tool(name: str, args: dict, tool_call_id: str = None) -> tuple[str, dict | None]:
    """
    Execute a tool by name. Returns (result, optional_routing_request).
    Logging is handled by the tool's bound callbacks.
    """
    # Special handlers
    if name == 'vectordb_tool':
        return execute_vectordb(args, tool_call_id)
    elif name == 'route_to_agent':
        return execute_route_to_agent(args, tool_call_id)
    
    # Standard tool execution via ToolSpec
    spec = get_tool_spec(name)
    if spec:
        result = spec.execute(args, tool_call_id)
        return result, None
    
    return f"Unknown tool: {name}", None

# ============================================================================
# Serialize Tool Calls for Logging
# ============================================================================
def serialize_tool_calls(tool_calls):
        serialized: list[dict] = []
        for tc in tool_calls:
            try:
                # Normalize to plain JSON-serializable dict
                tid = getattr(tc, 'id', '')
                fname = ''
                fargs = '{}'
                if hasattr(tc, 'function'):
                    fname = getattr(tc.function, 'name', '')
                    fargs = getattr(tc.function, 'arguments', '{}')
                elif isinstance(tc, dict):
                    f = tc.get('function', {})
                    fname = f.get('name', '')
                    fargs = f.get('arguments', '{}')
                    tid = tc.get('id', tid)
                serialized.append({
                    'id': tid,
                    'type': 'function',
                    'function': {'name': str(fname), 'arguments': str(fargs)}
                })
            except Exception:
                # Fallback safe stub
                serialized.append({
                    'id': '',
                    'type': 'function',
                    'function': {'name': '', 'arguments': '{}'}
                })
        return serialized

# ============================================================================
# Handle Tool Calls - uses execute_tool with bound callbacks
# ============================================================================

def _handle_tool_calls(agent_msg, depth: int = 0,
                        ChatCom = None,
                       agent_label: str ="") -> Any:
    """Execute tool calls and continue the conversation."""
    # Ensure we have a ChatHistory instance available (lazy import)
    history = get_history()

    def _sanitize(obj: Any) -> Any:
        """Recursively coerce data into JSON-safe types."""
        if isinstance(obj, dict):
            safe: dict[str, Any] = {}
            for k, v in obj.items():
                key = k if isinstance(k, (str, int, float, bool)) or k is None else str(k)
                safe[str(key)] = _sanitize(v)
            return safe
        if isinstance(obj, list):
            return [_sanitize(x) for x in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        try:
            return str(obj)
        except Exception:
            return "[unserializable]"
    if depth >= _MAX_TOOL_DEPTH:
        warning = "Aborting: tool-call depth exceeded."
        history._log(_role='assistant', _content=warning, 
                     _name='dispatcher_agent', _thread_name='chat', _obj='tool_call')
        return warning
    
    if not hasattr(agent_msg, 'tool_calls') or not agent_msg.tool_calls:
        return getattr(agent_msg, 'content', None) or None
    # Serialize tool_calls for logging (convert objects to dicts)
    routing_request: dict | None = None
    tool_results: list[str] = []
    executed_tool_names: list[str] = []
    terminal_tool_result: str | None = None
    # Log assistant message with tool_calls BEFORE executing tools     

    # This ensures the tool_calls are in history before tool responses
    history._log(_role='assistant', _content=agent_msg.content,
                 _name=agent_label, _thread_name='chat', _obj='tool_call',
                 _tool_calls=agent_msg.tool_calls)

    for tc in agent_msg.tool_calls:
        name = tc.function.name
        executed_tool_names.append(str(name))
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        # Execute tool.
        result, _request = execute_tool(name, args, tc.id)
        # IMPORTANT: Add the tool response as a proper OpenAI-style tool message
        # paired with the assistant message above (same tool_call_id). This keeps
        # the history sequence valid for subsequent model calls.
        try:
            if isinstance(result, (dict, list)):
                tool_content = json.dumps(_sanitize(result), ensure_ascii=False)
            else:
                tool_content = str(result)
        except Exception:
            tool_content = "[unprintable tool result]"

        tool_results.append(tool_content)

        # Deterministic stop condition for dispatcher batch runs:
        # Once we generated cover letters in batch, return that tool result
        # directly (no follow-up model call that could trigger more tools).
        if name == "batch_generate_cover_letters" and (agent_label or "") in (
            "_data_dispatcher",
            "data_dispatcher",
            "dispatcher_agent",
        ):
            terminal_tool_result = tool_content

        history._log(
            _role='tool',
            _content=tool_content,
            _obj='tool_call',
            _thread_name='chat',
            _name=agent_label, 
            _tool_call_id=getattr(tc, 'id', None),
            _name_tool=name
        )
        agent_label = agent_label or 'Primary Assistant'
        if isinstance(_request, dict) and _request.get('messages') is not None:
            routing_request = _request

    if terminal_tool_result is not None:
        return terminal_tool_result

    # After processing tools, make a follow-up model call so the assistant can
    # turn tool output into a user-facing answer.
    try:
        from . import ChatComE  # type: ignore
    except Exception:
        import os
        import sys

        _pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _pkg_parent not in sys.path:
            sys.path.insert(0, _pkg_parent)
        from alde.chat_completion import ChatComE, ChatCompletion  # type: ignore
    client = ChatCompletion._client
    if routing_request is not None:
        followup_messages = routing_request.get('messages') or []
        if not isinstance(followup_messages, list):
            followup_messages = [followup_messages]
        followup_messages = list(followup_messages)
        followup_messages.extend(history._insert(tool=True, f_depth=15))
        followup_tools = routing_request.get('tools') or []
        followup_model = routing_request.get('model') or model
    else:
        current_agent_config = AGENTS_REGISTRY.get(agent_label) or {}
        followup_tools = get_agent_tools(current_agent_config.get('tools') or [])
        followup_model = current_agent_config.get('model') or model
        followup_messages = history._insert(tool=True, f_depth=15)
        sys_text = current_agent_config.get('system')
        if sys_text and (not followup_messages or followup_messages[0].get('role') != 'system'):
            followup_messages = [{"role": "system", "content": sys_text}] + followup_messages

    # Absolute safety: OpenAI rejects an empty `messages` array.
    if not followup_messages:
        followup_messages = [{"role": "user", "content": ""}]

    c =  ChatComE(
           _model=followup_model,
           _messages=followup_messages,
           tools=followup_tools,
           tool_choice='auto'
    )

    try:
        resp = c._response()
    except Exception as exc:
        err = f"Follow-up model call failed: {exc}"
        history._log(_role='assistant', _content=err,
                     _name=agent_label or 'Primary Assistant',
                     _thread_name='tool_call', _obj='chat')
        return err

    if getattr(resp, 'choices', None):
        msg = resp.choices[0].message
        if getattr(msg, 'tool_calls', None):
            rec = _handle_tool_calls(msg, depth + 1, ChatCom=ChatCom, agent_label=agent_label)
            if rec is not None and str(rec).strip():
                return rec
        text = (getattr(msg, 'content', '') or '').strip()
        if text:
            history._log(_role='assistant', _content=text,
                         _name=agent_label, _thread_name='tool_call', _obj='chat')
            return text

    # Fallback: don't return None when we have tool output.
    return "\n".join(tool_results).strip() or None

# ============================================================================
# Main Entry Point
# ============================================================================
# if __name__ == '__main__':
#    import sys

        # Run triage agent with default prompt
    user_msg = ""       
    # Acquire history lazily to avoid circular import during module init
    history = get_history()
    history._log(_role='user', _content=user_msg, 
                 _name='dispatcher_agent', _thread_name='chat', _obj='chat')
    triage = ChatComE(_model=model, 
                      _messages=sys1mi + [{"role":"user", "content":user_msg}], 
                      tools=get_agent_tools(AGENTS_REGISTRY['triage_agent']['tools']), 
                      tool_choice='auto')
    rspn = triage._response()
    if hasattr(rspn, 'choices') and len(rspn.choices) > 0:
        msg = rspn.choices[0].message
        history._log(_role='assistant', _content=msg.content or '', 
                     _name='triage_agent', _thread_name='chat', _obj='chat', 
                     _tool_calls=msg.tool_calls if hasattr(msg, 'tool_calls') else None)
        result = _handle_tool_calls(msg, agent_label='triage_agent')
        if result:
            print("\n\n=== FINAL RESULT ===\n")
            print(result)
        else:
            print('\n\n=== RESPONSE ===\n')
            print(msg.content or 'No response')
    else:
        print('\n\n=== ERROR ===\n')
        print(str(rspn))
