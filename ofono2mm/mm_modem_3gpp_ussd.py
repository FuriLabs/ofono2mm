import asyncio

from dbus_fast.service import ServiceInterface, method, dbus_property
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant, DBusError

from ofono2mm.logging import ofono2mm_print

class MMModem3gppUssdInterface(ServiceInterface):
    def __init__(self, modem_name, ofono_interfaces, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd')
        self.modem_name = modem_name
        ofono2mm_print("Initializing 3GPP USSD interface", verbose)
        self.ofono_interfaces = ofono_interfaces
        self.verbose = verbose
        self.props = {
            'State': Variant('u', 0), # on runtime unknown MM_MODEM_3GPP_USSD_SESSION_STATE_UNKNOWN
            'NetworkNotification': Variant('s', ''),
            'NetworkRequest': Variant('s', ''),
        }

    def init_ussd(self):
        ofono2mm_print("Initializing signals", self.verbose)

        if 'org.ofono.SupplementaryServices' in self.ofono_interfaces:
            self.ofono_interfaces['org.ofono.SupplementaryServices'].on_notification_received(self.save_notification_received)
            self.ofono_interfaces['org.ofono.SupplementaryServices'].on_request_received(self.save_request_received)
            self.ofono_interfaces['org.ofono.SupplementaryServices'].on_property_changed(self.property_changed)
        else:
            ofono2mm_print("org.ofono.SupplementaryServices was not available when initializing ussd", self.verbose)

    @method()
    async def Initiate(self, command: 's') -> 's':
        ofono2mm_print(f"Initiating USSD with command {command}", self.verbose)

        if self.props['State'].value in (2, 3): # 2: active, 3: user-response
            raise DBusError('org.freedesktop.ModemManager1.Error.Core.WrongState', 'Cannot initiate USSD: a session is already active')

        ret = await self.ofono_interfaces['org.ofono.SupplementaryServices'].call_initiate(command)
        ussd_string = ret[1].value
        ofono2mm_print(f"USSD request result: {ussd_string}", self.verbose)
        return ussd_string

    @method()
    async def Respond(self, response: 's') -> 's':
        ofono2mm_print(f"Respond to 3GPP with command {response}", self.verbose)

        if self.props['State'].value in (1, 2): # 1: idle, 2: active
            raise DBusError('org.freedesktop.ModemManager1.Error.Core.WrongState', 'Cannot respond USSD: no active session')

        # when signal strength is low, ofono might take quite some time to respond
        retries = 10
        for attempt in range(retries):
            try:
                result = await self.ofono_interfaces['org.ofono.SupplementaryServices'].call_respond(response)
                return result
            except Exception as e:
                ofono2mm_print(f"Attempt {attempt + 1}: Failed to respond: {e}", self.verbose)
                if str(e) == "Operation already in progress" and attempt < retries - 1:
                    await asyncio.sleep(5)
                else:
                    return ''
        return ''

    @method()
    async def Cancel(self):
        ofono2mm_print("Cancelling USSD request", self.verbose)

        try:
            await self.ofono_interfaces['org.ofono.SupplementaryServices'].call_cancel()
        except DBusError as e:
            if "Operation is not active or in progress" in str(e):
                raise DBusError('org.freedesktop.ModemManager1.Error.Core.WrongState', 'Cannot respond USSD: no active session')
        except Exception as e:
            ofono2mm_print(f"Failed to cancel USSD: {e}", self.verbose)

    @dbus_property(access=PropertyAccess.READ)
    async def State(self) -> 'u':
        return self.props['State'].value

    def save_notification_received(self, message):
        ofono2mm_print(f"Save notification with message {message}", self.verbose)
        self.props['NetworkNotification'] = Variant('s', message)
        self.emit_properties_changed({'NetworkNotification': self.props['NetworkNotification'].value})

    @dbus_property(access=PropertyAccess.READ)
    def NetworkNotification(self) -> 's':
        return self.props['NetworkNotification'].value

    def save_request_received(self, message):
        ofono2mm_print(f"Save request with message {message}", self.verbose)
        self.props['NetworkRequest'] = Variant('s', message)
        self.emit_properties_changed({'NetworkRequest': self.props['NetworkRequest'].value})

    @dbus_property(access=PropertyAccess.READ)
    async def NetworkRequest(self) -> 's':
        return self.props['NetworkRequest'].value

    async def property_changed(self, prop, value):
        ofono2mm_print(f"Property changed: {prop}: {value.value}", self.verbose)
        if prop == "State":
            if value.value == 'idle':
                state = 1 # idle MM_MODEM_3GPP_USSD_SESSION_STATE_IDLE
            elif value.value == "active":
                state = 2 # active MM_MODEM_3GPP_USSD_SESSION_STATE_ACTIVE
            elif value.value == "user-response":
                state = 3 # user response MM_MODEM_3GPP_USSD_SESSION_STATE_USER_RESPONSE
            else:
                state = 0 # unknown MM_MODEM_3GPP_USSD_SESSION_STATE_UNKNOWN
            self.props['State'] = Variant('u', state)
            self.emit_properties_changed({'State': self.props['State'].value})
