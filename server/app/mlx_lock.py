"""One lock for every MLX model in this process (local hearing and local voice, issue #81).

MLX on the GPU isn't meant to be driven from several threads at once. Run each model call in a
worker thread (asyncio.to_thread) while holding MLX_LOCK, so hearing and voice take turns and the
event loop never blocks. Calls are short (tens of ms), so waiting is brief.
"""

import threading

MLX_LOCK = threading.Lock()
