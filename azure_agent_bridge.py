import os
from pathlib import Path

from agents import Agent, Runner, set_default_openai_client, set_tracing_disabled
from openai import AsyncOpenAI


AZURE_ENV_FILE = Path("/home/ubuntu/.config/azure-openai.env")


def _ensure_azure_env() -> None:
    if os.environ.get("AZURE_OPENAI_ENDPOINT") and os.environ.get("AZURE_OPENAI_API_KEY"):
        return
    if not AZURE_ENV_FILE.exists():
        return

    for raw_line in AZURE_ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


def build_client() -> AsyncOpenAI:
    _ensure_azure_env()
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    base_url = os.environ.get("AZURE_OPENAI_BASE_URL", f"{endpoint}/openai/v1/")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


async def run_azure_agent(prompt: str) -> str:
    _ensure_azure_env()
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    set_tracing_disabled(True)
    set_default_openai_client(build_client())

    agent = Agent(
        name="Azure OpenAI Discord Agent",
        instructions="You are a concise assistant. Respond clearly and directly.",
        model=deployment,
    )
    result = await Runner.run(agent, prompt)
    return str(result.final_output).strip()
