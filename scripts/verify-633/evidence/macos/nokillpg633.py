import os
import graftling.control as c
class _OS:
    def __getattr__(self, name):
        if name == "killpg": raise AttributeError("module \x27os\x27 has no attribute \x27killpg\x27")
        return getattr(os, name)
c.os = _OS()
