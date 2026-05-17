from pathlib import Path

from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage

_msg_adapter: TypeAdapter = TypeAdapter(ModelMessage)


class MessageHistory:
    def __init__(self) -> None:
        self._messages: list = []

    def update_history(self, new_messages: list) -> None:
        self._messages += new_messages

    def __iter__(self):
        return iter(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __getitem__(self, index):
        return self._messages[index]

    def dump_history(self, path: Path) -> None:
        """Serialize message history to a .jsonl file, one message per line."""
        with open(path, "w", encoding="utf-8") as f:
            for msg in self._messages:
                f.write(_msg_adapter.dump_json(msg).decode() + "\n")
