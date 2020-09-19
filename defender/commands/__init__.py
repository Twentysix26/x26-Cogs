from .manualmodules import ManualModules
from .settings import Settings
from .stafftools import StaffTools
from ..abc import CompositeMetaClass

class Commands(ManualModules, StaffTools, Settings, metaclass=CompositeMetaClass): # type: ignore
    """Class joining all command subclasses"""