import itertools
import logging
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from mindbase_layer.agent import SupportDependencies, langfuse, project_manager_agent
from mindbase_layer.agent_core.memory_layer import MessageHistory

_DIM = "\033[2;37m"   # dim white (light gray)
_RESET = "\033[0m"

logging.basicConfig(
    level=logging.INFO,
    format=f"{_DIM}%(name)s %(levelname)s %(message)s{_RESET}",
    stream=sys.stdout,
)


def _spinner(stop_event: threading.Event) -> None:
    for frame in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
        if stop_event.is_set():
            break
        sys.stdout.write(f"\r🤖 Thinking... {frame} ")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * 20 + "\r")
    sys.stdout.flush()


if __name__ == "__main__":
    deps = SupportDependencies(home_dir=Path.home())
    print("🤖 Project Manager Agent ready. Type 'exit' to quit.\n")
    message_history = MessageHistory()
    history_path = Path(os.environ["DATA_DIR"]) / f"{int(time.time())}_chat_history.jsonl"
    try:
        while True:
            user_input = input("👨 You: ").strip()
            if user_input.lower() == "exit":
                print("🤖 Goodbye!")
                break
            stop = threading.Event()
            spinner = threading.Thread(target=_spinner, args=(stop,), daemon=True)
            spinner.start()
            result = project_manager_agent.run_sync(user_input, deps=deps, message_history=message_history)
            stop.set()
            spinner.join()
            message_history.update_history(result.new_messages())
            print(f"🤖 Agent: {result.output}\n")
    finally:
        if message_history:
            message_history.dump_history(history_path)
        langfuse.flush()
