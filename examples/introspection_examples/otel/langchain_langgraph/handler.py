"""
LangChain First-Party Handler Example

Demonstrates using IntrospectionCallbackHandler with tools, system
prompt, and a full agent loop (model -> tool call -> tool result -> response).

Also exports to LangSmith via LANGSMITH_* env vars (LangChain's built-in
LangSmith integration picks these up automatically).

Run with:
    uv run -m introspection_examples.otel.langchain_langgraph.handler
"""

from introspection_sdk import IntrospectionCallbackHandler
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    weather = {
        "Boston": "Sunny, 72°F",
        "Tokyo": "Cloudy, 65°F",
        "Paris": "Rainy, 58°F",
    }
    return weather.get(city, f"Weather data unavailable for {city}")


def main():
    handler = IntrospectionCallbackHandler(
        service_name="langchain-python-example",
    )

    print("Running LangChain agent with tools + system prompt...")

    model = ChatOpenAI(model="gpt-4o-mini").bind_tools([get_weather])

    import random

    city = random.choice(["Boston", "Tokyo", "Paris"])

    messages: list[BaseMessage] = [
        SystemMessage(
            content="You are a helpful weather assistant. "
            "Always use the get_weather tool to answer weather questions. "
            "Be concise."
        ),
        HumanMessage(content=f"What's the weather in {city}?"),
    ]

    callbacks = {"callbacks": [handler]}

    # Agent loop: call model, execute tools, feed results back
    response = model.invoke(messages, config=callbacks)
    messages.append(response)

    while response.tool_calls:
        for tc in response.tool_calls:
            print(f"Calling tool: {tc['name']}({tc['args']})")
            result = get_weather.invoke(tc["args"], config=callbacks)  # type: ignore[arg-type]
            messages.append(
                ToolMessage(content=str(result), tool_call_id=tc["id"])
            )

        response = model.invoke(messages, config=callbacks)
        messages.append(response)

    print(f"Response: {response.content}")

    handler.shutdown()
    print("Done — spans exported to Introspection.")


if __name__ == "__main__":
    main()
