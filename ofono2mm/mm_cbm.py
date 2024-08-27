from dbus_next.service import ServiceInterface, dbus_property
from dbus_next.constants import PropertyAccess
from dbus_next import Variant

from ofono2mm.logging import ofono2mm_print

class MMCbmInterface(ServiceInterface):
    def __init__(self, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Cbs')
        ofono2mm_print("Initializing CBM interface", verbose)
        self.verbose = verbose
        self.props = {
            "State": Variant('u', 0), # default value unknown MM_CBM_STATE_UNKNOWN
            "Text": Variant('s', ''),
            "Channel": Variant('u', 0),
            "MessageCode": Variant('u', 0),
            "Update": Variant('u', 0),
        }

    @dbus_property(access=PropertyAccess.READ)
    def State(self) -> 'u':
        return self.props['State'].value

    @dbus_property(access=PropertyAccess.READ)
    def Text(self) -> 's':
        return self.props['Text'].value

    @dbus_property(access=PropertyAccess.READ)
    def Channel(self) -> 'u':
        return self.props['Channel'].value

    @dbus_property(access=PropertyAccess.READ)
    def MessageCode(self) -> 'u':
        return self.props['MessageCode'].value

    @dbus_property(access=PropertyAccess.READ)
    def Update(self) -> 'u':
        return self.props['Update'].value
