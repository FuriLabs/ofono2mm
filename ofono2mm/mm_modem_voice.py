from time import sleep
import asyncio

from dbus_fast.service import ServiceInterface, method, dbus_property, signal
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant

from ofono2mm.mm_call import MMCallInterface
from ofono2mm.logging import ofono2mm_print

call_i = 1

class MMModemVoiceInterface(ServiceInterface):
    def __init__(self, bus, ofono_client, modem_name, ofono_interfaces, ofono_interface_props, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.Voice')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Voice interface", verbose)
        self.bus = bus
        self.ofono_client = ofono_client
        self.ofono_interfaces = ofono_interfaces
        self.ofono_interface_props = ofono_interface_props
        self.verbose = verbose
        self.props = {
            'Calls': Variant('ao', []),
            'EmergencyOnly': Variant('b', False),
        }
        self.call_path_map = {}

    def set_emergency_mode(self):
        if 'org.ofono.SimManager' in self.ofono_interfaces and 'FixedDialing' in self.ofono_interface_props['org.ofono.SimManager']:
            self.props['EmergencyOnly'] = Variant('b', self.ofono_interface_props['org.ofono.SimManager']['FixedDialing'].value)
        else:
            self.props['EmergencyOnly'] = Variant('b', False)

    def init_calls(self):
        ofono2mm_print("Initializing signals", self.verbose)

        try:
            self.set_emergency_mode()
        except Exception as e:
            ofono2mm_print(f"Failed to check for emergency state, marking as false: {e}", self.verbose)
            self.props['EmergencyOnly'] = Variant('b', False)

        if 'org.ofono.VoiceCallManager' in self.ofono_interfaces:
            self.ofono_interfaces['org.ofono.VoiceCallManager'].on_call_added(self.add_call)
            self.ofono_interfaces['org.ofono.VoiceCallManager'].on_call_removed(self.remove_call)
        else:
            ofono2mm_print("org.ofono.VoiceCallManager was not available when initializing call", self.verbose)

    def clean_phone_number(self, number):
        # Remove any *31#, #31#, or similar prefixes
        while number.startswith('*') or number.startswith('#'):
            number = number.split('#', 1)[-1]
        return number

    async def add_call(self, path, props):
        ofono2mm_print(f"Add call with object path {path} and properties {props}", self.verbose)

        global call_i

        self.set_emergency_mode()

        object_path = f'/org/freedesktop/ModemManager1/Call/{call_i}'
        if props['State'].value == 'incoming':
            mm_call_interface = MMCallInterface(self.ofono_client, self.ofono_interfaces, self.verbose)
            mm_call_interface.props.update({
                'State': Variant('i', 3), # ringing in MM_CALL_STATE_RINGING_IN
                'StateReason': Variant('i', 2), # incoming new MM_CALL_STATE_REASON_INCOMING_NEW
                'Direction': Variant('i', 1), # incoming MM_CALL_DIRECTION_INCOMING
                'Number': Variant('s', props['LineIdentification'].value),
                'Multiparty': props['Multiparty'],
            })

            mm_call_interface.voicecall = path
            mm_call_interface.init_call()

            self.bus.export(object_path, mm_call_interface)
            self.props['Calls'].value.append(object_path)
            self.call_path_map[path] = object_path
            self.emit_properties_changed({'Calls': self.props['Calls'].value})
            self.CallAdded(object_path)
            call_i += 1
        elif props['State'].value == 'dialing':
            mm_call_interface = MMCallInterface(self.ofono_client, self.ofono_interfaces, self.verbose)
            mm_call_interface.props.update({
                'State': Variant('i', 2),  # ringing out MM_CALL_STATE_RINGING_OUT
                'StateReason': Variant('i', 0), # outgoing started MM_CALL_STATE_REASON_UNKNOWN
                'Direction': Variant('i', 2), # outgoing MM_CALL_DIRECTION_OUTGOING
                'Number': Variant('s', props['LineIdentification'].value),
            })

            mm_call_interface.voicecall = path
            mm_call_interface.init_call()

            self.bus.export(object_path, mm_call_interface)
            self.props['Calls'].value.append(object_path)
            self.call_path_map[path] = object_path
            self.emit_properties_changed({'Calls': self.props['Calls'].value})
            self.CallAdded(object_path)
            call_i += 1
        elif props['State'].value == 'alerting':
            cleaned_number = self.clean_phone_number(props['LineIdentification'].value)
            mm_call_interface = MMCallInterface(self.ofono_client, self.ofono_interfaces, self.verbose)
            mm_call_interface.props.update({
                'State': Variant('i', 2), # ringing in MM_CALL_STATE_RINGING_OUT
                'StateReason': Variant('i', 1), # incoming new MM_CALL_STATE_REASON_OUTGOING_STARTED
                'Direction': Variant('i', 2), # incoming MM_CALL_DIRECTION_INCOMING
                'Number': Variant('s', cleaned_number),
                'Multiparty': props['Multiparty'],
            })

            mm_call_interface.voicecall = path
            mm_call_interface.init_call()

            self.bus.export(object_path, mm_call_interface)
            self.props['Calls'].value.append(object_path)
            self.call_path_map[path] = object_path
            self.emit_properties_changed({'Calls': self.props['Calls'].value})
            self.CallAdded(object_path)
            call_i += 1

    async def remove_call(self, path):
        ofono2mm_print(f"Remove call with object path {path}", self.verbose)

        try:
            mm_path = self.call_path_map[path]
            self.props['Calls'].value.remove(mm_path)
            self.bus.unexport(mm_path)
            del self.call_path_map[path]
            self.emit_properties_changed({'Calls': self.props['Calls'].value})
            self.CallDeleted(mm_path)
        except KeyError:
            ofono2mm_print(f"No mapping found for ofono path {path}", self.verbose)
        except Exception as e:
            ofono2mm_print(f"Error while removing call {path}: {e}", self.verbose)

        self.set_emergency_mode()

    @method()
    async def ListCalls(self) -> 'ao':
        ofono2mm_print("Returning list of calls", self.verbose)
        return self.props['Calls'].value

    @method()
    async def DeleteCall(self, path: 'o'):
        ofono2mm_print(f"Deleting call with object path {path}", self.verbose)

        if path in self.props['Calls'].value:
            await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_hangup_all()
            self.props['Calls'].value.remove(path)
            ofono_path = next((k for k, v in self.call_path_map.items() if v == path), None)
            if ofono_path:
                del self.call_path_map[ofono_path]
            self.bus.unexport(path)
            self.emit_properties_changed({'Calls': self.props['Calls'].value})
            self.CallDeleted(path)

            if 'org.ofono.SimManager' in self.ofono_interfaces and 'FixedDialing' in self.ofono_interface_props['org.ofono.SimManager']:
                self.props['EmergencyOnly'] = Variant('b', self.ofono_interface_props['org.ofono.SimManager']['FixedDialing'].value)
            else:
                self.props['EmergencyOnly'] = Variant('b', False)

    @method()
    async def CreateCall(self, properties: 'a{sv}') -> 'o':
        ofono2mm_print(f"Creating call with properties {properties}", self.verbose)

        global call_i

        self.set_emergency_mode()

        mm_call_interface = MMCallInterface(self.ofono_client, self.ofono_interfaces, self.verbose)
        mm_call_interface.props.update({
            'State': Variant('i', 2), # ringing out MM_CALL_STATE_RINGING_OUT
            'StateReason': Variant('i', 1), # outgoing started MM_CALL_STATE_REASON_OUTGOING_STARTED
            'Direction': Variant('i', 2), # outgoing MM_CALL_DIRECTION_OUTGOING
            'Number': Variant('s', properties['number'].value),
        })

        object_path = f'/org/freedesktop/ModemManager1/Call/{call_i}'

        try:
            path = await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_dial(properties['number'].value, "")
        except Exception as e:
            ofono2mm_print(f"Failed to dial: {e}", self.verbose)
            return object_path # CallAdded should take care of the rest on false failures? kind of a hack but it works ¯\_(ツ)_/¯

        mm_call_interface.voicecall = path
        mm_call_interface.init_call()

        self.bus.export(object_path, mm_call_interface)
        self.props['Calls'].value.append(object_path)
        self.call_path_map[path] = object_path
        self.emit_properties_changed({'Calls': self.props['Calls'].value})
        self.CallAdded(object_path)
        call_i += 1

        return object_path

    @method()
    async def HoldAndAccept(self):
        ofono2mm_print("Holding and accepting call", self.verbose)
        await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_hold_and_answer()

    @method()
    async def HangupAndAccept(self):
        ofono2mm_print("Hanging up and accepting call", self.verbose)
        await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_release_and_answer()

    @method()
    async def HangupAll(self):
        ofono2mm_print("Hanging up all calls", self.verbose)
        await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_hangup_all()

    @method()
    async def Transfer(self):
        ofono2mm_print("Transfering call", self.verbose)
        await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_transfer()

    @method()
    def CallWaitingSetup(self, enable: 'b'):
        ofono2mm_print(f"Activate call waiting network: {enable}", self.verbose)

    @method()
    def CallWaitingQuery(self) -> 'b':
        ofono2mm_print("Query the status of call waiting network", self.verbose)
        return True

    @signal()
    def CallAdded(self, path) -> 'o':
        ofono2mm_print(f"Signal: Call added with object path {path}", self.verbose)
        return path

    @signal()
    def CallDeleted(self, path) -> 'o':
        ofono2mm_print(f"Signal: Call deleted with object path {path}", self.verbose)
        return path

    @dbus_property(access=PropertyAccess.READ)
    def Calls(self) -> 'ao':
        return self.props['Calls'].value

    @dbus_property(access=PropertyAccess.READ)
    def EmergencyOnly(self) -> 'b':
        return self.props['EmergencyOnly'].value
