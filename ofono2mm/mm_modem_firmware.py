from copy import deepcopy

from dbus_fast.service import ServiceInterface, method, dbus_property
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant, DBusError

from ofono2mm.logging import ofono2mm_print

class MMModemFirmwareInterface(ServiceInterface):
    def __init__(self, mm_modem, modem_name, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.Firmware')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Firmware interface", verbose)
        self.mm_modem = mm_modem
        self.verbose = verbose
        self.hardware_revision = Variant('s', '')

        self.props = {
            'UpdateSettings': Variant('(ua{sv})', [0, {
                'device-ids': Variant('as', ['OFONO-BINDER-PLUGIN']),
                'version': Variant('s', '')
            }])
        }

    def set_props(self):
        ofono2mm_print("Setting properties", self.verbose)

        old_props = deepcopy(self.props)

        self.hardware_revision = self.mm_modem.props.get('HardwareRevision', Variant('s', ''))

        self.props['UpdateSettings'] = Variant('(ua{sv})', [0, {
            'device-ids': Variant('as', ['OFONO-BINDER-PLUGIN']),
            'version': self.hardware_revision
        }])

        changed_props = {}
        for prop in self.props:
            if self.props[prop].value != old_props[prop].value:
                changed_props.update({ prop: self.props[prop].value })

        if changed_props:
            self.emit_properties_changed(changed_props)

    @dbus_property(access=PropertyAccess.READ)
    def UpdateSettings(self) -> '(ua{sv})':
        return self.props['UpdateSettings'].value

    @method()
    def List(self) -> 'saa{sv}':
        ofono2mm_print("Returning list of installed firmware", self.verbose)

        self.set_props()
        selected = self.hardware_revision.value

        installed_firmware = {
            'image-type': Variant('u', 1),
            'unique-id': Variant('s', selected)
        }

        return [selected, [installed_firmware]]

    @method()
    def Select(self, uniqueid: 's'):
        raise DBusError('org.freedesktop.ModemManager1.Error.Core.Unsupported', 'Cannot select firmware: operation not supported')
