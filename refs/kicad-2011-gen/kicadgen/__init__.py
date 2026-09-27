"""kicadgen — генератор и строгий валидатор файлов KiCad 2011 (bzr2986):
компонентные библиотеки .lib/.dcm, проектные файлы .pro и схемы .sch.

Формат восстановлен из исходников eeschema (см. docs/kicad-2011-formats.md).
"""

from .model import (  # noqa: F401
    PinType, PinOrient, PinShape, Fill, HJust, VJust,
    Field, Pin, Arc, Circle, Rect, Polyline, Bezier, Text,
    Component, Library, ValidationError,
)
from .writer_lib import write_library, write_doclib, save_library  # noqa: F401
from .reader_lib import read_library, read_doclib, load_library, LibLoadError  # noqa: F401
from .writer_pro import write_project, save_project  # noqa: F401
from .reader_pro import read_project  # noqa: F401
from .sch import (  # noqa: F401
    Schematic, SchComponent, Wire, Bus, BusEntry, Junction, NoConnect,
    Label, GlobalLabel, HierLabel, Note, Sheet, SheetPin, Orientation,
    write_schematic, read_schematic, save_schematic, SchLoadError,
)

__version__ = "0.1.0"
