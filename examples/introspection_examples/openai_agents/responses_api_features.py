"""
OpenAI Responses API Features Example

Demonstrates Introspection tracing with OpenAI Responses API features:
web search, reasoning with detailed summaries, encrypted reasoning, and
remote MCP tools via DeepWiki.

Run with:
    uv run python -m introspection_examples.openai_agents.responses_api_features
"""

from dotenv import load_dotenv

load_dotenv()

try:
    from agents import (
        Agent,
        ModelSettings,
        Runner,
        WebSearchTool,
        set_trace_processors,
    )
    from introspection_sdk import IntrospectionTracingProcessor
    from openai.types.shared.reasoning import Reasoning
except ImportError as e:
    raise ImportError(
        "Missing dependencies. Install with: uv sync --extra openai-agents"
    ) from e


def main():
    processor = IntrospectionTracingProcessor()
    set_trace_processors([processor])

    print("=== 1. Web Search Agent (gpt-4o) ===")

    web_agent = Agent(
        name="Web Search Agent",
        model="gpt-4o",
        instructions="You MUST use web search. Always search the web first before answering.",
        tools=[WebSearchTool()],
    )

    r1 = Runner.run_sync(
        web_agent, "What is the latest SpaceX launch in 2026?"
    )
    print(f"Response: {r1.final_output[:200]}...")
    print()

    print("=== 2. Reasoning with Detailed Summary (gpt-5.4) ===")

    reasoning_agent = Agent(
        name="Reasoning Agent",
        model="gpt-5.4",
        instructions="Think step by step. Show your work.",
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="high", summary="detailed"),
        ),
    )

    r2 = Runner.run_sync(
        reasoning_agent,
        "A farmer has 17 chickens and 23 cows. Each chicken eats 0.5kg of feed per day "
        "and each cow eats 15kg. If feed costs $0.40/kg, how much does the farmer spend per week?",
    )
    print(f"Response: {r2.final_output[:200]}...")
    print()

    print("=== 3. Encrypted Reasoning + Detailed Summary (gpt-5.4) ===")

    encrypted_agent = Agent(
        name="Encrypted Reasoning Agent",
        model="gpt-5.4",
        instructions="Think carefully before answering.",
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="high", summary="detailed"),
            response_include=["reasoning.encrypted_content"],
        ),
    )

    r3 = Runner.run_sync(
        encrypted_agent,
        "If a train travels at 120 km/h for 2.5 hours, then slows to 80 km/h for 1.75 hours, "
        "what is the total distance and average speed?",
    )
    print(f"Response: {r3.final_output[:200]}...")
    print()

    print("=== 4. MCP Tools - DeepWiki (gpt-4o) ===")

    mcp_agent = Agent(
        name="MCP DeepWiki Agent",
        model="gpt-4o",
        instructions="Use the DeepWiki MCP tools to answer questions about code repositories.",
        model_settings=ModelSettings(
            extra_body={
                "tools": [
                    {
                        "type": "mcp",
                        "server_label": "deepwiki",
                        "server_url": "https://mcp.deepwiki.com/mcp",
                        "require_approval": "never",
                    }
                ],
            },
        ),
    )

    r4 = Runner.run_sync(
        mcp_agent,
        "How does the Agent class work in the openai/openai-agents-python repo?",
    )
    print(f"Response: {r4.final_output[:200]}...")

    processor.shutdown()
    print("\n✓ All examples completed and traces exported.")


if __name__ == "__main__":
    main()
