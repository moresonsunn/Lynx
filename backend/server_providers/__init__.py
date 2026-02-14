# Ensure providers are imported so they register themselves
from . import vanilla  # noqa: F401
from . import paper  # noqa: F401
from . import purpur  # noqa: F401
from . import fabric  # noqa: F401
from . import forge  # noqa: F401
from . import neoforge  # noqa: F401
# Hybrid servers (support both mods and plugins)
from . import mohist  # noqa: F401
from . import magma  # noqa: F401
from . import banner  # noqa: F401
from . import catserver  # noqa: F401
from . import spongeforge  # noqa: F401
