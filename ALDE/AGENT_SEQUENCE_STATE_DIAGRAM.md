# Agent Configuration Diagrams (Current State)

Source of truth used:
- `alde/agents_registry.py`
- `alde/chat_completion.py`
- `alde/agents_factory.py`
- `alde/tools.py`

## 1) Sequence Diagram (Primary Agent initializes workflow + autonomous decision)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant P as P_Agent (_primary_assistant)
    participant O as OpenAI Chat API
    participant H as Tool Handler (_handle_tool_calls)
    participant R as route_to_agent
    participant D as _data_dispatcher
    participant JP as _job_posting_parser
    participant CL as _cover_letter_agent

    U->>P: User request
    P->>P: Load primary config (model/system/tools)
    P->>P: Detect forced route via @agent prefix?

    alt Forced route detected
        P->>R: execute_route_to_agent(target_agent, user_question)
        R-->>P: routing_request(messages, tools, model)
        P->>O: Follow-up call for target agent
    else No forced route
        P->>O: Primary model call (tool_choice=auto)
        O-->>P: Assistant message (+ optional tool_calls)
    end

    alt Tool calls present
        P->>H: _handle_tool_calls(message, depth=0)
        H->>H: Execute each tool + log tool result

        alt route_to_agent called
            H->>R: execute_route_to_agent(...)
            R-->>H: routing_request for target agent
            H->>O: Follow-up model call (target agent context)
            O-->>H: Target reply/tool_calls
        end

        alt target is _data_dispatcher
            D->>H: dispatch_job_posting_pdfs / batch_generate_cover_letters
            opt batch tool executed in dispatcher
                H-->>P: Return terminal tool result (deterministic stop)
            end
            opt dispatcher delegates
                D->>R: route_to_agent(_job_posting_parser / _cover_letter_agent)
                R-->>JP: Parsed routing request
                R-->>CL: Parsed routing request
            end
        end

        H-->>P: Final string result
    else No tool calls
        P-->>U: Assistant text response
    end

    P-->>U: Final response (text or serialized result)
```

## 2) State Diagram (Primary agent lifecycle + autonomous routing)

```mermaid
stateDiagram-v2
    [*] --> Init
    Init: Load _primary_assistant config
    Init --> AnalyzeInput

    AnalyzeInput: Normalize user input + parse @agent
    AnalyzeInput --> ForcedRoute : @agent recognized
    AnalyzeInput --> PrimaryLLM : no forced route

    ForcedRoute: Build route_to_agent args
    ForcedRoute --> RoutedLLM

    PrimaryLLM: Call OpenAI with primary tools
    PrimaryLLM --> HasToolCalls : tool_calls != null
    PrimaryLLM --> FinalText : tool_calls == null

    RoutedLLM: Follow-up call with routed agent context
    RoutedLLM --> HasToolCalls : returned tool_calls
    RoutedLLM --> FinalText : plain content

    HasToolCalls: _handle_tool_calls loop
    HasToolCalls --> RouteToSpecialist : tool == route_to_agent
    HasToolCalls --> DispatcherTerminal : tool == batch_generate_cover_letters && agent=_data_dispatcher
    HasToolCalls --> FollowupLLM : other tools executed

    RouteToSpecialist: Build routing_request from AGENTS_REGISTRY
    RouteToSpecialist --> RoutedLLM

    FollowupLLM: Continue model turn with updated history
    FollowupLLM --> HasToolCalls : more tool_calls
    FollowupLLM --> FinalText : no more tool_calls

    DispatcherTerminal: deterministic stop condition
    DispatcherTerminal --> FinalText

    FinalText --> [*]
```

## Notes about current configuration

- Registered agents:
  - `_primary_assistant`
  - `_data_dispatcher`
  - `_job_posting_parser`
  - `_cover_letter_agent`
- `route_to_agent` is the central handoff primitive.
- Tool group `@dispatcher` expands to:
  - `dispatch_job_posting_pdfs`
  - `batch_generate_cover_letters`
  - `vdb_worker`
- Deterministic stop exists for dispatcher batch runs after `batch_generate_cover_letters`.
- Current `ChatCom.get_response()` passes `agent_label="_data_dispatcher"` when handling tool calls, which influences follow-up tool context.
