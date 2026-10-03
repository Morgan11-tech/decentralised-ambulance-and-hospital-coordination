"""Talk to the intake agent by typing, no audio involved.

Useful to prove "typed text -> Gemini -> incident state -> Jev" before adding
the microphone and speech. Uses the real Gemini/Jev/MongoDB from your .env.

    python chat_cli.py            # saves the final incident to MongoDB
    python chat_cli.py --no-save  # skips MongoDB
"""

import asyncio
import json
import sys
from uuid import uuid4

from intake_agent import AgentError, IntakeAgent


async def print_event(event: dict) -> None:
    kind = event["type"]
    if kind == "incident_state":
        topics = ", ".join(
            f"{t['topic']}={t['value'] if t['status'] == 'known' else t['status']}" for t in event["topics"]
        )
        print(f"  [state] {topics}")
        if event["state"]["patient_state"]["symptoms"]:
            print(f"  [state] symptoms: {event['state']['patient_state']['symptoms']}")
    elif kind == "classification":
        for name, label in event["data"]["labels"].items():
            print(f"  [jev] {name}: {label['value']} (confidence {label['confidence']}) -> {label['final']}")
        if event["data"]["error"]:
            print(f"  [jev] error: {event['data']['error']}")
    elif kind == "incident_complete":
        print("\n=== Incident JSON ===")
        print(json.dumps(event["incident"], indent=2))
        print(f"persisted: {event['persisted']}  {event['persistence_error'] or ''}")
    elif kind == "error":
        print(f"  [{event['source']} error] {event['message']}")


async def no_store(_incident, _metadata) -> None:
    return None


async def main() -> None:
    kwargs = {"store": no_store} if "--no-save" in sys.argv else {}
    agent = IntakeAgent(str(uuid4()), emit=print_event, **kwargs)
    print(f"Agent: {(await agent.start()).text}")
    while not agent.done:
        text = (await asyncio.to_thread(input, "You: ")).strip()
        if not text:
            continue
        try:
            reply = await agent.handle_caller_text(text)
        except AgentError as exc:
            print(f"  [{exc.source} error] {exc} (type anything to retry)")
            agent.transcript.pop()  # drop the failed message; the caller will retype
            continue
        print(f"Agent: {reply.text}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (EOFError, KeyboardInterrupt):
        print("\nBye.")
