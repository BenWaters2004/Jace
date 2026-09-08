import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from jace.database import SessionLocal, init_database
from jace.db.conversations import (
    create_conversation,
    delete_conversation,
    get_conversation,
    model_history,
    store_user_message,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


async def main() -> None:
    await init_database()
    marker = "CHAT_HISTORY_CURRENT_TURN_MARKER_7F2C9A"
    conversation_id: str | None = None

    try:
        async with SessionLocal() as session:
            conversation = await create_conversation(
                session,
                model="qwen3.5:4b",
                system_prompt="Test only",
            )
            conversation_id = conversation.id

            loaded = await get_conversation(session, conversation.id)
            require(loaded is not None, "test conversation loads")
            require(len(loaded.messages) == 0, "conversation begins with an empty loaded message collection")

            user_message = await store_user_message(session, loaded, marker)

            # This is the key regression check. add_message() must update the
            # already-loaded relationship collection even though SessionLocal
            # uses expire_on_commit=False.
            require(
                any(message.id == user_message.id for message in loaded.messages),
                "new user message is visible in the already-loaded relationship collection",
            )

            # get_conversation() must also force refresh identity-map state so
            # callers never receive stale message history in the same session.
            refreshed = await get_conversation(session, conversation.id)
            require(refreshed is not None, "conversation reload succeeds")
            history = model_history(refreshed)
            require(bool(history), "model history is not empty after storing the current user turn")
            require(history[-1]["role"] == "user", "current user turn is the final model-history role")
            require(history[-1]["content"] == marker, "current user text is the exact final model-history content")

        print("PASS: Jace current-turn chat history consistency checks completed.")
    finally:
        if conversation_id:
            async with SessionLocal() as cleanup:
                await delete_conversation(cleanup, conversation_id)


if __name__ == "__main__":
    asyncio.run(main())
