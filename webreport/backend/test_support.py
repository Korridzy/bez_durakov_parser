"""Install an isolated store and late-bound registry for legacy API fixtures."""
from pathlib import Path

from chat_store import ChatStore
from runs import RunRegistry


async def install_test_runtime(main_module, tmp_dir):
    store = ChatStore(Path(tmp_dir) / 'chats.db')
    await store.setup()
    main_module.chat_store = store
    main_module.registry = RunRegistry(store, runtime=lambda: main_module,
                                       boot_id=main_module.BOOT_ID)
    return main_module.registry
