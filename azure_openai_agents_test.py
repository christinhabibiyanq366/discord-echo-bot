import asyncio

from azure_agent_bridge import run_azure_agent


async def main() -> None:
    result = await run_azure_agent(
        "Reply with exactly: Azure OpenAI agent test succeeded.",
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
